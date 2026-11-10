"""Moby-DIC · DIC local por subsets (IC-GN, ZNSSD, forma de 1ª ordem) com numba.

Método
------
- Grade regular de pontos na ROI do primeiro quadro (passo ``--passo`` px). Cada ponto é o
  centro de um subset quadrado de ``--subset`` px.
- Correlação inverse-compositional Gauss-Newton (IC-GN) com critério ZNSSD (equivalente a
  ZNCC), mapeamento afim do subset e interpolação B-spline cúbica da imagem.
- Referência incremental: por padrão a referência só é trocada quando a ZNCC mediana com o
  quadro atual cai abaixo de ``--zncc-ref`` (menos trocas = menos erro acumulado); com
  ``--passo-referencia N`` a troca é a cada N quadros. A nova referência é o último quadro bom,
  com os subsets centrados nas posições atuais dos pontos. Chute inicial por
  extrapolação da velocidade; se a ZNCC ficar baixa, busca inteira e nova tentativa. Pontos que
  falham recebem posição estimada pelos vizinhos e voltam a ser tentados no quadro seguinte;
  só pontos efetivamente medidos entram nos resultados. Quadros ainda ruins recebem duas novas
  tentativas: salto global (correlação de fase) e igualação de nitidez (refoco), em que a imagem
  mais nítida é filtrada até ter a nitidez da outra. Pontos que ainda falham contra a referência
  são resgatados correlacionando-os contra o último quadro bom.
- Deformação: ajuste local de plano (mínimos quadrados) aos deslocamentos totais numa janela de
  ``--janela-deformacao`` × ``--janela-deformacao`` pontos (strain window), F = I + ∇u em relação
  à configuração inicial; deformação verdadeira (logarítmica) das fibras x e y.

Coordenadas: as imagens são invertidas verticalmente na leitura, para usar o mesmo sistema do
muDIC (origem no canto inferior esquerdo, x para a direita, y para cima).
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from . import configurar_numba

configurar_numba()
import numba as nb  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage as nd  # noqa: E402

from .export import exportar  # noqa: E402
from .i18n import t as tx  # noqa: E402
from .imagens import ler_cinza, listar_imagens  # noqa: E402

# Cache da compilação do numba. No executável, o código-fonte deste módulo vai junto (para o numba
# localizá-lo) e o cache fica na pasta numba_cache das configurações do usuário (configurar_numba).
CACHE = True

# Validação dos pontos medidos
GRADIENTE_MAX = 0.5      # |∂u/∂x| etc. entre referência e quadro atual acima disso = warp degenerado
DESVIO_MAX_PX = 2.0      # deslocamento que difere mais que isso da mediana dos vizinhos = falso casamento


def ler_imagem(caminho):
    """Imagem em tons de cinza (float), invertida verticalmente (origem no canto inferior)."""
    return ler_cinza(caminho, origem_inferior=True)


def coeficientes(imagem):
    return nd.spline_filter(imagem, order=3, mode="mirror")


# ----------------------------------------------------------------------------- numba kernels

@nb.njit(cache=CACHE, inline="always")
def _bases(t):
    s = 1.0 - t
    return (s * s * s / 6.0, (3.0 * t ** 3 - 6.0 * t * t + 4.0) / 6.0,
            (-3.0 * t ** 3 + 3.0 * t * t + 3.0 * t + 1.0) / 6.0, t ** 3 / 6.0)


@nb.njit(cache=CACHE, inline="always")
def _dbases(t):
    s = 1.0 - t
    return (-0.5 * s * s, 1.5 * t * t - 2.0 * t, -1.5 * t * t + t + 0.5, 0.5 * t * t)


@nb.njit(cache=CACHE)
def interp(c, x, y):
    ix = int(np.floor(x))
    iy = int(np.floor(y))
    bx = _bases(x - ix)
    by = _bases(y - iy)
    v = 0.0
    for j in range(4):
        linha = 0.0
        for i in range(4):
            linha += bx[i] * c[iy - 1 + j, ix - 1 + i]
        v += by[j] * linha
    return v


@nb.njit(cache=CACHE)
def interp_grad(c, x, y):
    ix = int(np.floor(x))
    iy = int(np.floor(y))
    tx, ty = x - ix, y - iy
    bx, by = _bases(tx), _bases(ty)
    dx, dy = _dbases(tx), _dbases(ty)
    v = gx = gy = 0.0
    for j in range(4):
        s0 = s1 = 0.0
        for i in range(4):
            cij = c[iy - 1 + j, ix - 1 + i]
            s0 += bx[i] * cij
            s1 += dx[i] * cij
        v += by[j] * s0
        gx += by[j] * s1
        gy += dy[j] * s0
    return v, gx, gy


@nb.njit(cache=CACHE)
def _dentro(c, x, y):
    return 2.0 <= x <= c.shape[1] - 3.0 and 2.0 <= y <= c.shape[0] - 3.0


@nb.njit(cache=CACHE)
def _zncc_inteiro(cr, ct, xc, yc, m, u0, v0, busca):
    """Busca inteira por translação em torno de (u0, v0); devolve melhor (u, v, zncc)."""
    n = (2 * m + 1) ** 2
    f = np.empty(n)
    k = 0
    for dy in range(-m, m + 1):
        for dx in range(-m, m + 1):
            f[k] = interp(cr, xc + dx, yc + dy)
            k += 1
    f -= f.mean()
    nf = np.sqrt((f * f).sum())
    melhor, bu, bv = -2.0, u0, v0
    g = np.empty(n)
    for sy in range(-busca, busca + 1):
        for sx in range(-busca, busca + 1):
            u, v = u0 + sx, v0 + sy
            if not (_dentro(ct, xc - m + u, yc - m + v) and _dentro(ct, xc + m + u, yc + m + v)):
                continue
            k = 0
            for dy in range(-m, m + 1):
                for dx in range(-m, m + 1):
                    g[k] = interp(ct, xc + dx + u, yc + dy + v)
                    k += 1
            g -= g.mean()
            ng = np.sqrt((g * g).sum())
            if ng == 0.0 or nf == 0.0:
                continue
            z = (f * g).sum() / (nf * ng)
            if z > melhor:
                melhor, bu, bv = z, u, v
    return bu, bv, melhor


@nb.njit(cache=CACHE)
def icgn(cr, ct, xc, yc, m, p, maxit, tol):
    """IC-GN de um subset. p = [u, ux, uy, v, vx, vy] (modificado in loco).

    Devolve (zncc, iteracoes, ok)."""
    n = (2 * m + 1) ** 2
    f = np.empty(n)
    jac = np.empty((n, 6))
    k = 0
    for dy in range(-m, m + 1):
        for dx in range(-m, m + 1):
            v, gx, gy = interp_grad(cr, xc + dx, yc + dy)
            f[k] = v
            jac[k, 0] = gx
            jac[k, 1] = gx * dx
            jac[k, 2] = gx * dy
            jac[k, 3] = gy
            jac[k, 4] = gy * dx
            jac[k, 5] = gy * dy
            k += 1
    fm = f.mean()
    f -= fm
    df = np.sqrt((f * f).sum())
    if df < 1e-9:
        return 0.0, 0, False
    hess = jac.T @ jac
    try:
        hinv = np.linalg.inv(hess)
    except Exception:
        return 0.0, 0, False

    g = np.empty(n)
    w = np.empty((3, 3))
    dw = np.empty((3, 3))
    for it in range(maxit):
        # Pontos do subset deformado
        k = 0
        for dy in range(-m, m + 1):
            for dx in range(-m, m + 1):
                x = xc + dx + p[0] + p[1] * dx + p[2] * dy
                y = yc + dy + p[3] + p[4] * dx + p[5] * dy
                if not _dentro(ct, x, y):
                    return 0.0, it, False
                g[k] = interp(ct, x, y)
                k += 1
        gm = g.mean()
        g -= gm
        dg = np.sqrt((g * g).sum())
        if dg < 1e-9:
            return 0.0, it, False
        r = f - (df / dg) * g
        dp = -(hinv @ (jac.T @ r))
        # W(p) <- W(p) o W(dp)^-1
        w[0, 0] = 1.0 + p[1]; w[0, 1] = p[2]; w[0, 2] = p[0]
        w[1, 0] = p[4]; w[1, 1] = 1.0 + p[5]; w[1, 2] = p[3]
        w[2, 0] = 0.0; w[2, 1] = 0.0; w[2, 2] = 1.0
        dw[0, 0] = 1.0 + dp[1]; dw[0, 1] = dp[2]; dw[0, 2] = dp[0]
        dw[1, 0] = dp[4]; dw[1, 1] = 1.0 + dp[5]; dw[1, 2] = dp[3]
        dw[2, 0] = 0.0; dw[2, 1] = 0.0; dw[2, 2] = 1.0
        nw = w @ np.linalg.inv(dw)
        p[0] = nw[0, 2]; p[1] = nw[0, 0] - 1.0; p[2] = nw[0, 1]
        p[3] = nw[1, 2]; p[4] = nw[1, 0]; p[5] = nw[1, 1] - 1.0
        norma = np.sqrt(dp[0] ** 2 + dp[3] ** 2
                        + (dp[1] ** 2 + dp[2] ** 2 + dp[4] ** 2 + dp[5] ** 2) * m * m)
        if norma < tol:
            znssd = ((f / df - g / dg) ** 2).sum()
            return 1.0 - 0.5 * znssd, it + 1, True
    znssd = ((f / df - g / dg) ** 2).sum()
    return 1.0 - 0.5 * znssd, maxit, False


@nb.njit(cache=CACHE, inline="always")
def _degenerado(p):
    """Warp com gradientes irreais (o IC-GN pode "encolher" o subset e achar uma ZNCC alta falsa)."""
    return (abs(p[1]) > GRADIENTE_MAX or abs(p[2]) > GRADIENTE_MAX
            or abs(p[4]) > GRADIENTE_MAX or abs(p[5]) > GRADIENTE_MAX)


@nb.njit(cache=CACHE, parallel=True)
def correlacionar_quadro(cr, ct, centros, params, ativo, m, maxit, tol, zmin, busca):
    """Resolve todos os pontos ativos. params [N, 6] entra como chute e sai como solução."""
    n = centros.shape[0]
    zncc = np.zeros(n)
    iters = np.zeros(n, dtype=np.int32)
    ok = np.zeros(n, dtype=np.bool_)
    for i in nb.prange(n):
        if not ativo[i]:
            continue
        xc, yc = centros[i, 0], centros[i, 1]
        if not (_dentro(cr, xc - m, yc - m) and _dentro(cr, xc + m, yc + m)):
            continue
        p = params[i].copy()
        z, it, conv = icgn(cr, ct, xc, yc, m, p, maxit, tol)
        if not conv or z < zmin or _degenerado(p):
            # Recomeça de uma busca inteira em torno do chute.
            bu, bv, _ = _zncc_inteiro(cr, ct, xc, yc, m, np.round(params[i, 0]),
                                      np.round(params[i, 3]), busca)
            p[:] = 0.0
            p[0], p[3] = bu, bv
            z, it2, conv = icgn(cr, ct, xc, yc, m, p, maxit, tol)
            it += it2
        params[i] = p
        zncc[i] = z
        iters[i] = it
        ok[i] = conv and z >= zmin and not _degenerado(p)
    return zncc, iters, ok


@nb.njit(cache=CACHE, parallel=True)
def _desvio_vizinhos(u, v, ok, h):
    """Distância (px) entre o deslocamento de cada ponto e a mediana dos vizinhos medidos numa
    janela (2h+1)² da grade (o próprio ponto excluído). NaN quando há menos de 5 vizinhos."""
    ny, nx = ok.shape
    saida = np.full((ny, nx), np.nan)
    for r in nb.prange(ny):
        bu = np.empty((2 * h + 1) ** 2)
        bv = np.empty((2 * h + 1) ** 2)
        for c in range(nx):
            if not ok[r, c]:
                continue
            k = 0
            for rr in range(max(0, r - h), min(ny, r + h + 1)):
                for cc in range(max(0, c - h), min(nx, c + h + 1)):
                    if (rr != r or cc != c) and ok[rr, cc]:
                        bu[k] = u[rr, cc]
                        bv[k] = v[rr, cc]
                        k += 1
            if k >= 5:
                saida[r, c] = np.hypot(u[r, c] - np.median(bu[:k]), v[r, c] - np.median(bv[:k]))
    return saida


def incoerentes(params, ok, forma, limite=DESVIO_MAX_PX, h=2):
    """Pontos medidos cujo deslocamento destoa dos vizinhos (falsos casamentos). Duas passadas,
    para que um aglomerado de pontos errados não esconda o vizinho errado."""
    ny, nx = forma
    ruins = np.zeros(len(ok), dtype=bool)
    for _ in range(2):
        bom = (ok & ~ruins).reshape(ny, nx)
        d = _desvio_vizinhos(params[:, 0].reshape(ny, nx).copy(), params[:, 3].reshape(ny, nx).copy(), bom, h)
        novo = (d > limite).ravel()
        if not novo.any():
            break
        ruins |= novo
    return ruins


# ----------------------------------------------------------------------------- deformação

def gradiente_local(desloc, valido, passo, meia_janela, fracao_minima=0.6):
    """Ajusta u = a + b·dX + c·dY numa janela (2h+1)² da grade. Devolve F [ny, nx, 2, 2]."""
    h = meia_janela
    off = np.arange(-h, h + 1, dtype=float) * passo
    kx = np.tile(off, (2 * h + 1, 1))         # dX ao longo das colunas
    ky = kx.T                                  # dY ao longo das linhas
    k1 = np.ones_like(kx)
    w = valido.astype(float)

    def conv(a, k):
        return nd.correlate(a, k, mode="constant", cval=0.0)

    s1, sx, sy = conv(w, k1), conv(w, kx), conv(w, ky)
    sxx, sxy, syy = conv(w, kx * kx), conv(w, kx * ky), conv(w, ky * ky)
    a = np.stack([np.stack([s1, sx, sy], -1), np.stack([sx, sxx, sxy], -1),
                  np.stack([sy, sxy, syy], -1)], -2)
    grad = np.full(valido.shape + (2, 2), np.nan)
    suficiente = s1 >= fracao_minima * (2 * h + 1) ** 2
    with np.errstate(invalid="ignore"):
        det = np.linalg.det(a)
    ok = suficiente & (np.abs(det) > 1e-9)
    for comp in range(2):
        u = np.where(valido, desloc[..., comp], 0.0)
        b = np.stack([conv(u, k1), conv(u, kx), conv(u, ky)], -1)
        sol = np.linalg.solve(a[ok], b[ok][..., None])[..., 0]
        g = np.full(valido.shape + (2,), np.nan)
        g[ok] = sol[:, 1:]
        grad[..., comp, :] = g
    grad[..., 0, 0] += 1.0
    grad[..., 1, 1] += 1.0
    return grad, ok


def salto_global(ref, atual, roi):
    """Deslocamento médio (x, y) do conteúdo da ROI de ref para atual, por correlação de fase."""
    from skimage.registration import phase_cross_correlation
    x1, y1, x2, y2 = (int(round(v)) for v in roi)
    a, b = ref[y1:y2, x1:x2], atual[y1:y2, x1:x2]
    desl, _, _ = phase_cross_correlation(a, b, upsample_factor=10, normalization=None)
    return -np.array([desl[1], desl[0]])  # (dy, dx) para alinhar b em a -> conteúdo moveu (-dx, -dy)


def nitidez(img, roi):
    x1, y1, x2, y2 = (int(round(v)) for v in roi)
    return float((nd.laplace(img[y1:y2, x1:x2]) ** 2).mean())


def sigma_igualar(img, alvo, roi):
    """σ do filtro gaussiano que leva a nitidez de img ao valor alvo (bisseção em escala log)."""
    lo, hi = 0.0, 8.0
    for _ in range(14):
        meio = 0.5 * (lo + hi)
        if nitidez(nd.gaussian_filter(img, meio), roi) > alvo:
            lo = meio
        else:
            hi = meio
    return 0.5 * (lo + hi)


def preencher(desloc, medido, sigmas=(1.5, 3, 6, 12, 24, 48)):
    """Estima o deslocamento dos pontos não medidos a partir dos vizinhos medidos.

    Convolução gaussiana normalizada na grade, aumentando o raio até cobrir todos os pontos.
    desloc [ny, nx, 2], medido [ny, nx] -> desloc completo [ny, nx, 2]."""
    saida = np.where(medido[..., None], desloc, np.nan)
    falta = ~medido
    if not medido.any():
        return np.zeros_like(desloc)
    w = medido.astype(float)
    for sg in sigmas:
        if not falta.any():
            break
        peso = nd.gaussian_filter(w, sg, mode="constant")
        for k in range(2):
            num = nd.gaussian_filter(np.where(medido, desloc[..., k], 0.0), sg, mode="constant")
            est = np.divide(num, peso, out=np.full_like(num, np.nan), where=peso > 1e-3)
            saida[..., k] = np.where(falta & np.isfinite(est), est, saida[..., k])
        falta = ~np.isfinite(saida).all(-1)
    if falta.any():
        saida[falta] = np.nanmedian(desloc[medido], axis=0)
    return saida


# ----------------------------------------------------------------------------- análise

def analisar(args):
    todos = listar_imagens(args.imagens)
    fim = args.fim if args.fim else len(todos)
    arquivos = todos[args.inicio - 1:fim][::args.a_cada]
    if args.limite:
        arquivos = arquivos[:args.limite]
    n = len(arquivos)
    if n < 2:
        raise ValueError("A pasta precisa de pelo menos dois PNGs.")
    nb.set_num_threads(args.threads)

    m = args.subset // 2
    x1, y1, x2, y2 = args.roi
    xs = np.arange(x1, x2 + 1e-9, args.passo)
    ys = np.arange(y1, y2 + 1e-9, args.passo)
    gx, gy = np.meshgrid(xs, ys)
    ny, nx = gx.shape
    p0 = np.c_[gx.ravel(), gy.ravel()].astype(float)
    npt = len(p0)

    pos = np.full((n, npt, 2), np.nan)
    pos[0] = p0
    zncc = np.full((n, npt), np.nan)
    zncc[0] = 1.0
    iters = np.zeros((n, npt), dtype=np.int32)
    # pos: só pontos medidos (saída). pos_est: medidos + estimados pelos vizinhos, usado
    # como centro de subset e chute; um ponto perdido volta a ser tentado no quadro seguinte.
    pos_est = np.full((n, npt, 2), np.nan)
    pos_est[0] = p0
    ativo = np.ones(npt, dtype=bool)
    estados = ["referencia"]

    coef = [None] * n
    def c(i):
        if coef[i] is None:
            coef[i] = coeficientes(ler_imagem(arquivos[i]))
        return coef[i]

    ref = 0
    bons = [0]
    trocar_ref = False
    nitidez_cache = {}
    def nit(i):
        if i not in nitidez_cache:
            nitidez_cache[i] = nitidez(ler_imagem(arquivos[i]), args.roi)
        return nitidez_cache[i]
    params = np.zeros((npt, 6))
    saltos = np.zeros((n, 2))          # salto rígido global corrigido em cada quadro (px)
    log = []
    t_total = time.time()
    for t in range(1, n):
        t0 = time.time()
        # Quadros "ruins" (menos de --fracao-minima dos pontos medidos) nunca viram referência
        # nem base do chute: o quadro seguinte é correlacionado com o último quadro bom.
        g = bons[-1]
        if args.passo_referencia > 0:
            trocar = t % args.passo_referencia == 0
        else:  # automático: troca quando a correlação com a referência piorou
            trocar = trocar_ref
        if trocar and g != ref:
            ref = g
            params[:, 1:3] = 0.0
            params[:, 4:6] = 0.0
        centros = pos_est[ref].copy()
        # Chute: deslocamento no último quadro bom + velocidade extrapolada até t.
        base = pos_est[g] - pos_est[ref]
        if len(bons) >= 2:
            g2 = bons[-2]
            # um salto rígido corrigido em g não se repete: fica fora da velocidade
            vel = (pos_est[g] - pos_est[g2] - saltos[g]) * (t - g) / (g - g2)
        else:
            vel = np.zeros_like(base)
        chute = base + vel
        params[~ativo] = 0.0  # pontos que falharam no quadro anterior recomeçam sem gradiente
        params[:, 0], params[:, 3] = chute[:, 0], chute[:, 1]
        cr_use, ct_use, sigma_q = c(ref), c(t), 0.0
        if args.igualar_nitidez:
            nr, nt = nit(ref), nit(t)
            if max(nr, nt) > 1.3 * min(nr, nt):
                nitida, alvo = (t, nr) if nt > nr else (ref, nt)
                img = ler_imagem(arquivos[nitida])
                sigma_q = sigma_igualar(img, alvo, args.roi)
                cb = coeficientes(nd.gaussian_filter(img, sigma_q))
                cr_use, ct_use = (cr_use, cb) if nitida == t else (cb, ct_use)
                sigma_q = sigma_q if nitida == t else -sigma_q  # negativo: referência filtrada
        z, it, ok = correlacionar_quadro(cr_use, ct_use, centros, params,
                                         np.ones(npt, dtype=bool), m, args.maxit, 1e-3,
                                         args.zncc_min, args.busca)
        ok &= ~incoerentes(params, ok, (ny, nx))
        correcao = np.zeros(2)
        if ok.mean() < args.fracao_minima:
            # Segunda tentativa: salto global (ex.: escorregamento da garra) estimado por
            # correlação de fase entre referência e quadro atual na ROI.
            salto = salto_global(ler_imagem(arquivos[ref]), ler_imagem(arquivos[t]), args.roi)
            correcao = salto - np.median(chute, axis=0)
            if np.hypot(*correcao) > 1.0:
                p2 = np.zeros_like(params)
                p2[:, 0], p2[:, 3] = chute[:, 0] + correcao[0], chute[:, 1] + correcao[1]
                tentar = ~ok
                z2, it2, ok2 = correlacionar_quadro(cr_use, ct_use, centros, p2, tentar, m,
                                                    args.maxit, 1e-3, args.zncc_min, args.busca)
                melhora = tentar & ok2
                params[melhora], z[melhora], it[melhora] = p2[melhora], z2[melhora], it2[melhora]
                ok = ok | melhora
                # pontos que tinham "convergido" sem o salto concordam entre si e só ficam
                # incoerentes agora, ao lado dos corrigidos: nova tentativa com o salto
                ruins = incoerentes(params, ok, (ny, nx))
                if ruins.any():
                    ok &= ~ruins
                    p2[ruins] = 0.0
                    p2[ruins, 0], p2[ruins, 3] = chute[ruins, 0] + correcao[0], chute[ruins, 1] + correcao[1]
                    z2, it2, ok2 = correlacionar_quadro(cr_use, ct_use, centros, p2, ruins, m,
                                                        args.maxit, 1e-3, args.zncc_min, args.busca)
                    melhora = ruins & ok2
                    params[melhora], z[melhora], it[melhora] = p2[melhora], z2[melhora], it2[melhora]
                    ok = ok | melhora
                if ok.mean() >= args.fracao_minima:
                    saltos[t] = correcao
                print(tx(f"  quadro {t}: salto global estimado ({salto[0]:+.1f}, {salto[1]:+.1f}) px; "
                         f"pontos medidos {ok.mean():.1%} após nova tentativa",
                         f"  frame {t}: global jump estimated ({salto[0]:+.1f}, {salto[1]:+.1f}) px; "
                         f"measured points {ok.mean():.1%} after retry"), flush=True)
        if ok.mean() < args.fracao_minima and not args.igualar_nitidez:
            # Terceira tentativa: diferença de foco (refoco durante o ensaio). Borra a imagem mais
            # nítida até igualar a nitidez da outra e correlaciona de novo.
            img_r, img_t = ler_imagem(arquivos[ref]), ler_imagem(arquivos[t])
            nr, nt = nitidez(img_r, args.roi), nitidez(img_t, args.roi)
            if max(nr, nt) > 1.5 * min(nr, nt):
                sigma = sigma_igualar(img_t if nt > nr else img_r, min(nr, nt), args.roi)
                cr_b = coeficientes(nd.gaussian_filter(img_r, sigma)) if nr > nt else c(ref)
                ct_b = coeficientes(nd.gaussian_filter(img_t, sigma)) if nt > nr else c(t)
                p3 = params.copy()
                p3[~ok] = 0.0
                p3[~ok, 0], p3[~ok, 3] = chute[~ok, 0], chute[~ok, 1]
                if np.hypot(*correcao) > 1.0:
                    p3[~ok, 0] += correcao[0]
                    p3[~ok, 3] += correcao[1]
                tentar = ~ok
                z3, it3, ok3 = correlacionar_quadro(cr_b, ct_b, centros, p3, tentar, m,
                                                    args.maxit, 1e-3, args.zncc_min, args.busca)
                melhora = tentar & ok3
                params[melhora], z[melhora], it[melhora] = p3[melhora], z3[melhora], it3[melhora]
                ok = ok | melhora
                print(tx(f"  quadro {t}: nitidez ref {nr:.0f} / atual {nt:.0f}, filtro σ = {sigma:.2f} px; "
                         f"pontos medidos {ok.mean():.1%}",
                         f"  frame {t}: sharpness ref {nr:.0f} / current {nt:.0f}, filter σ = {sigma:.2f} px; "
                         f"measured points {ok.mean():.1%}"), flush=True)
        ok &= ~incoerentes(params, ok, (ny, nx))
        ok_ref = ok.copy()
        resgatados = 0
        if (~ok).any() and g != ref and args.resgate:
            # Resgate: pontos que falharam contra a referência são correlacionados contra o último
            # quadro bom (mais próximo na deformação), a partir das posições estimadas nele.
            falhos = ~ok
            centros_g = pos_est[g].copy()
            # chute: posição atual estimada pelos vizinhos já medidos neste quadro (não carrega
            # para a frente um salto do quadro anterior, como a extrapolação da velocidade)
            atual = centros + params[:, [0, 3]]
            if ok.any():
                d_est = preencher((atual - p0).reshape(ny, nx, 2), ok.reshape(ny, nx)).reshape(-1, 2)
                atual = np.where(ok[:, None], atual, p0 + d_est)
            else:
                atual = centros_g + vel
            p4 = np.zeros_like(params)
            p4[:, 0], p4[:, 3] = (atual - centros_g)[:, 0], (atual - centros_g)[:, 1]
            cg, ctg = (c(g), c(t))
            if args.igualar_nitidez:
                ng_, nt_ = nit(g), nit(t)
                if max(ng_, nt_) > 1.3 * min(ng_, nt_):
                    nitida, alvo = (t, ng_) if nt_ > ng_ else (g, nt_)
                    img = ler_imagem(arquivos[nitida])
                    cb = coeficientes(nd.gaussian_filter(img, sigma_igualar(img, alvo, args.roi)))
                    cg, ctg = (cg, cb) if nitida == t else (cb, ctg)
            z4, it4, ok4 = correlacionar_quadro(cg, ctg, centros_g, p4, falhos, m,
                                                args.maxit, 1e-3, args.zncc_min, args.busca)
            resg = falhos & ok4
            # Converte para o formato "centro na referência + deslocamento" usado abaixo.
            params[resg, 0] = (centros_g[resg, 0] + p4[resg, 0]) - centros[resg, 0]
            params[resg, 3] = (centros_g[resg, 1] + p4[resg, 3]) - centros[resg, 1]
            params[resg, 1:3] = 0.0
            params[resg, 4:6] = 0.0
            z[resg], it[resg] = z4[resg], it4[resg]
            ok = ok | resg
            ok &= ~incoerentes(params, ok, (ny, nx))
            resgatados = int((resg & ok).sum())
        ativo = ok
        medida = centros + params[:, [0, 3]]
        pos[t] = np.where(ativo[:, None], medida, np.nan)
        d = preencher((medida - p0).reshape(ny, nx, 2), ativo.reshape(ny, nx)).reshape(-1, 2)
        pos_est[t] = np.where(ativo[:, None], medida, p0 + d)
        zncc[t] = np.where(ativo, z, np.nan)
        iters[t] = it
        # Libera coeficientes que não serão mais usados.
        for k in range(t - 1):
            if k != ref:
                coef[k] = None
        if ativo.mean() >= args.fracao_minima:
            bons.append(t)
            estados.append("convergiu")
            # Troca a referência quando a correlação piora na mediana, na cauda (p05) ou quando uma
            # fração pequena de pontos já falhou contra ela.
            zr = z[ativo]
            trocar_ref = (float(np.median(zr)) < args.zncc_ref
                          or float(np.percentile(zr, 5)) < args.zncc_ref_p05
                          or (1 - ok_ref.mean()) > args.falha_ref)
        else:
            estados.append("quadro_ruim")
            trocar_ref = True
        linha = dict(indice=t, arquivo=arquivos[t].name, referencia=ref, estado=estados[-1],
                     sigma_igualacao_px=round(sigma_q, 3), resgatados=resgatados,
                     pontos_ativos=int(ativo.sum()), fracao_ativa=float(ativo.mean()),
                     zncc_mediana=float(np.nanmedian(zncc[t])),
                     zncc_p05=float(np.nanpercentile(zncc[t], 5)),
                     iteracoes_mediana=float(np.median(it[ativo])) if ativo.any() else np.nan,
                     tempo_s=time.time() - t0)
        log.append(linha)
        print(tx("quadro", "frame") + f" {t:3d} ref {ref:3d} " + tx("ativos", "active") + f" {ativo.mean():6.1%} "
              f"zncc med {linha['zncc_mediana']:.4f} p05 {linha['zncc_p05']:.4f} "
              f"{linha['tempo_s']:.1f}s", flush=True)

    saida = args.saida
    with (saida / "convergencia.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(log[0]))
        w.writeheader()
        w.writerows(log)

    pos_g = pos.reshape(n, ny, nx, 2)
    desloc = pos_g - pos_g[:1]
    valido_pts = np.isfinite(pos_g).all(-1)
    grad = np.empty((n, ny, nx, 2, 2))
    valido = np.empty((n, ny, nx), dtype=bool)
    for t in range(n):
        grad[t], okt = gradiente_local(desloc[t], valido_pts[t], args.passo, args.janela_deformacao // 2)
        valido[t] = okt & valido_pts[t]
    np.savez_compressed(saida / "qualidade_subsets.npz", zncc=zncc.reshape(n, ny, nx),
                        iteracoes=iters.reshape(n, ny, nx))

    meta = {
        "metodo": "DIC local por subsets (IC-GN, ZNSSD, forma afim, B-spline cúbica)",
        "pasta_imagens": str(args.imagens), "roi_xyxy_px_origem_inferior": list(args.roi), "a_cada_n_imagens": args.a_cada,
        "imagem_inicial": args.inicio, "imagem_final": args.fim,
        "tamanho_imagem_px": list(ler_imagem(arquivos[0]).shape[::-1]),
        "subset_px": 2 * m + 1, "passo_px": args.passo, "grade_xy": [nx, ny],
        "janela_deformacao_pontos": args.janela_deformacao // 2 * 2 + 1,
        "janela_deformacao_px": (args.janela_deformacao // 2 * 2) * args.passo,
        "passo_referencia": args.passo_referencia or "automatico", "zncc_ref": args.zncc_ref, "zncc_ref_p05": args.zncc_ref_p05,
        "falha_ref": args.falha_ref, "resgate": args.resgate,
        "referencias_usadas": sorted({l["referencia"] for l in log}), "zncc_min": args.zncc_min,
        "busca_inteira_px": args.busca, "igualar_nitidez": args.igualar_nitidez, "fracao_minima": args.fracao_minima,
        "quadros_ruins": [i for i, e in enumerate(estados) if e == "quadro_ruim"], "maxit": args.maxit,
        "escala_um_px": args.escala_um_px, "calibrado": args.calibrado, "quadros": n,
        "tempo_total_s": time.time() - t_total, "threads": args.threads,
        "eixos": "origem no canto inferior esquerdo da imagem; x para a direita, y para cima",
        "deformacao": "verdadeira (logarítmica) por ajuste local de plano aos deslocamentos",
    }
    (saida / "parametros.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")

    imagens = {}
    def imagem(i):
        if i not in imagens:
            imagens[i] = ler_imagem(arquivos[i])
        return imagens[i]

    exportar(saida, imagem, arquivos, estados, args.escala_um_px, pos_g, desloc, grad,
             calibrado=args.calibrado,
             valido=valido, pontos_ref=p0[::max(1, npt // 3000)],
             titulo_malha=tx(f"Pontos de subset ({2 * m + 1} px, passo {args.passo} px)",
                             f"Subset points ({2 * m + 1} px, step {args.passo} px)"))


DOC_EN = """Moby-DIC · local subset DIC (IC-GN, ZNSSD, first-order shape function), numba kernels.

Method
------
- Regular grid of points in the ROI of the first frame (spacing --step px). Each point is the
  centre of a square subset of --subset px.
- Inverse-compositional Gauss-Newton (IC-GN) correlation with the ZNSSD criterion (equivalent to
  ZNCC), affine subset mapping and cubic B-spline image interpolation.
- Incremental reference: by default the reference is only updated when the median ZNCC with the
  current frame drops below --zncc-ref (fewer updates = less accumulated error), or when the 5th
  percentile or the failure fraction degrade; with --reference-every N it is updated every N
  frames. The new reference is the last good frame, with the subsets centred on the current point
  positions. Initial guess by velocity extrapolation; integer search and retry when ZNCC is low.
  Failed points get a position estimated from their neighbours and are retried on the next frame;
  only actually measured points enter the results. Difficult frames get two more attempts: global
  jump (phase correlation) and sharpness matching (refocusing). Points that still fail against the
  reference are rescued by correlating them against the last good frame.
- Strain: local least-squares plane fit to the total displacements in a window of
  --strain-window x --strain-window points, F = I + grad(u) relative to the initial configuration;
  true (logarithmic) strain of the x and y fibres.

Coordinates: images are flipped vertically when read (origin at the lower-left corner, x to the
right, y up).
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="Moby-DIC subsets", description=tx(__doc__, DOC_EN),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", "--imagens", metavar="IMAGES", dest="imagens", type=Path, required=True,
                    help=tx("Pasta com a sequência de imagens.", "Folder with the image sequence."))
    ap.add_argument("--output", "--saida", metavar="OUTPUT", dest="saida", type=Path, required=True,
                    help=tx("Pasta de resultados (não pode existir).", "Result folder (must not exist)."))
    ap.add_argument("--scale-um-px", "--escala-um-px", metavar="SCALE_UM_PX", dest="escala_um_px", type=float,
                    help=tx("Calibração em µm/px. Sem ela os resultados ficam em pixels.",
                            "Calibration in µm/px. Without it, results are in pixels."))
    ap.add_argument("--subset", type=int, default=25,
                    help=tx("Lado do subset em px (ímpar, padrão 25).", "Subset side in px (odd, default 25)."))
    ap.add_argument("--step", "--passo", metavar="STEP", dest="passo", type=int, default=5,
                    help=tx("Espaçamento da grade em px (padrão 5).", "Grid spacing in px (default 5)."))
    ap.add_argument("--strain-window", "--janela-deformacao", metavar="STRAIN_WINDOW", dest="janela_deformacao", type=int, default=5,
                    help=tx("Janela de ajuste da deformação em pontos da grade (ímpar, padrão 5).",
                            "Strain fitting window in grid points (odd, default 5)."))
    ap.add_argument("--reference-every", "--passo-referencia", metavar="REFERENCE_EVERY", dest="passo_referencia", type=int, default=0,
                    help=tx("Troca a referência a cada N quadros; 0 = automático (padrão), quando a ZNCC "
                            "mediana com a referência fica abaixo de --zncc-ref.",
                            "Update the reference every N frames; 0 = automatic (default): when the median "
                            "ZNCC against the reference drops below --zncc-ref."))
    ap.add_argument("--zncc-ref", type=float, default=0.98,
                    help=tx("Modo automático: limite da ZNCC mediana para trocar a referência (padrão 0,98).",
                            "Automatic mode: median ZNCC threshold to update the reference (default 0.98)."))
    ap.add_argument("--zncc-ref-p05", type=float, default=0.95,
                    help=tx("Modo automático: troca também se a ZNCC p05 ficar abaixo disto (padrão 0,95).",
                            "Automatic mode: also update if the 5th-percentile ZNCC drops below this (default 0.95)."))
    ap.add_argument("--fail-ref", "--falha-ref", metavar="FAIL_REF", dest="falha_ref", type=float, default=0.003,
                    help=tx("Modo automático: troca também se esta fração de pontos falhar (padrão 0,003).",
                            "Automatic mode: also update if this fraction of points fails (default 0.003)."))
    ap.add_argument("--no-rescue", "--sem-resgate", dest="resgate", action="store_false",
                    help=tx("Desliga o resgate de pontos falhos contra o último quadro bom.",
                            "Disable rescuing failed points against the last good frame."))
    ap.add_argument("--zncc-min", type=float, default=0.8,
                    help=tx("ZNCC mínima para aceitar um ponto (padrão 0,8).",
                            "Minimum ZNCC to accept a point (default 0.8)."))
    ap.add_argument("--match-sharpness", "--igualar-nitidez", dest="igualar_nitidez", action="store_true",
                    help=tx("Em todo quadro, filtra a imagem mais nítida (referência ou atual) até a nitidez "
                            "da outra antes de correlacionar. Útil com foco variável e referência fixa.",
                            "On every frame, blur the sharper image (reference or current) to the sharpness of "
                            "the other before correlating. Useful with varying focus and a fixed reference."))
    ap.add_argument("--min-fraction", "--fracao-minima", metavar="MIN_FRACTION", dest="fracao_minima", type=float, default=0.5,
                    help=tx("Fração mínima de pontos medidos para o quadro servir de referência (padrão 0,5).",
                            "Minimum fraction of measured points for a frame to become a reference (default 0.5)."))
    ap.add_argument("--search", "--busca", metavar="SEARCH", dest="busca", type=int, default=6,
                    help=tx("Raio da busca inteira de recuperação (px).", "Radius of the integer recovery search (px)."))
    ap.add_argument("--maxit", type=int, default=50,
                    help=tx("Iterações máximas do IC-GN (padrão 50).", "Maximum IC-GN iterations (default 50)."))
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                    help=tx("Núcleos usados (padrão: metade).", "CPU threads (default: half of the cores)."))
    ap.add_argument("--roi", type=float, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                    help=tx("ROI em px, origem no canto inferior esquerdo. Sem ela, é detectada automaticamente.",
                            "ROI in px, origin at the lower-left corner. Detected automatically if omitted."))
    ap.add_argument("--every", "--a-cada", metavar="EVERY", dest="a_cada", type=int, default=1,
                    help=tx("Usa uma imagem a cada N (padrão 1).", "Use one image every N (default 1)."))
    ap.add_argument("--first", "--inicio", metavar="FIRST", dest="inicio", type=int, default=1,
                    help=tx("Primeira imagem usada (1 = primeira da pasta).", "First image used (1 = first in the folder)."))
    ap.add_argument("--last", "--fim", metavar="LAST", dest="fim", type=int,
                    help=tx("Última imagem usada (padrão: a última da pasta).", "Last image used (default: the last one)."))
    ap.add_argument("--limit", "--limite", metavar="LIMIT", dest="limite", type=int,
                    help=tx("Número máximo de quadros (após --a-cada).", "Maximum number of frames (after --every)."))
    args = ap.parse_args(argv)
    args.calibrado = args.escala_um_px is not None
    if not args.calibrado:
        args.escala_um_px = 1.0
    if args.roi is None:
        from .auto import sugerir
        args.roi = sugerir(args.imagens, args.inicio, args.fim, args.a_cada)["roi"]
        print(tx("ROI automática (origem inferior):", "Automatic ROI (lower-left origin):"), [round(v) for v in args.roi], flush=True)
    if args.a_cada < 1:
        ap.error(tx("--a-cada deve ser >= 1", "--every must be >= 1"))
    if args.subset < 7 or args.subset % 2 == 0:
        ap.error(tx("--subset deve ser ímpar e >= 7", "--subset must be odd and >= 7"))
    if args.janela_deformacao < 3 or args.janela_deformacao % 2 == 0:
        ap.error(tx("--janela-deformacao deve ser ímpar e >= 3", "--strain-window must be odd and >= 3"))
    args.imagens = args.imagens.resolve()
    args.saida.mkdir(parents=True, exist_ok=False)
    analisar(args)


if __name__ == "__main__":
    main()
