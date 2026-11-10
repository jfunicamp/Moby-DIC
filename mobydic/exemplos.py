"""Moby-DIC · conjuntos de imagens de exemplo (sintéticos, com campo exato conhecido).

    moby-dic exemplo                      lista os exemplos
    moby-dic exemplo necking [--saida P]  gera a sequência em P/necking

Cada exemplo grava as imagens (PNG 8 bits) e ``ground_truth.json`` com o campo imposto, para
comparar com o resultado da análise. As imagens simulam uma amostra pintada (clara, com speckle)
sobre fundo escuro, carregada na direção x, com ruído de câmera.

Example datasets (synthetic, with known exact fields) used by the tutorials.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd
from scipy.special import erf

from .i18n import t as tx

ALTURA, LARGURA = 520, 960          # px
BANDA = (110, 410)                  # faixa da amostra em y (origem inferior), px
FUNDO = 28.0


def _material(semente, tamanho=2.2):
    """Imagem no estado de referência: amostra clara com speckle escuro, fundo escuro liso."""
    rng = np.random.default_rng(semente)
    campo = nd.gaussian_filter(rng.random((ALTURA, LARGURA)), tamanho)
    campo = (campo - campo.mean()) / campo.std()
    amostra = 215 - 160 / (1 + np.exp(-4 * (campo - 0.35)))
    y = np.arange(ALTURA)[:, None]
    borda = 1 / (1 + np.exp(-(y - BANDA[0]) / 0.8)) - 1 / (1 + np.exp(-(y - BANDA[1]) / 0.8))
    img = FUNDO + (amostra - FUNDO) * borda
    return nd.gaussian_filter(img, 0.7)


def _coef(img):
    return nd.spline_filter(img, order=3, mode="mirror")


def _deformar(coef, campo):
    """g(x) = f(X(x)), com x = X + u(X) invertido por ponto fixo."""
    yy, xx = np.mgrid[0:ALTURA, 0:LARGURA].astype(float)
    X, Y = xx.copy(), yy.copy()
    for _ in range(40):
        u, v = campo(X, Y)
        X, Y = xx - u, yy - v
    return nd.map_coordinates(coef, [Y, X], order=3, prefilter=False, mode="nearest")


def _salvar(img, pasta, k, rng, ruido=1.6, desfoque=0.0):
    if desfoque > 0:
        img = nd.gaussian_filter(img, desfoque)
    img = img + rng.normal(0, ruido, img.shape)
    # arquivo em orientação usual (origem superior); o Moby-DIC inverte na leitura
    Image.fromarray(np.clip(np.flipud(img), 0, 255).round().astype(np.uint8)).save(pasta / f"frame_{k:03d}.png")


# ----------------------------------------------------------------------------- exemplos

def necking(pasta, n=13):
    """Tração com estricção localizada no centro e pequeno escorregamento da garra."""
    yc, xc, s = (BANDA[0] + BANDA[1]) / 2, LARGURA * 0.52, 70.0
    e0 = np.linspace(0, 0.030, n)                       # deformação de fundo (uniforme)
    a = np.r_[0, np.linspace(0, 1, n - 1) ** 2.2] * 0.16  # pico adicional da estricção
    desliz = np.linspace(0, 4.0, n)                     # translação rígida em x (px)

    def campo_k(k):
        def eps(X):
            return e0[k] + a[k] * np.exp(-((X - xc) / s) ** 2)

        def f(X, Y):
            u = e0[k] * (X - xc) + a[k] * s * math.sqrt(math.pi) / 2 * erf((X - xc) / s) + desliz[k]
            v = -0.5 * eps(X) * (Y - yc)                # plasticidade: contração ≈ metade
            return u, v
        return f

    coef, rng = _coef(_material(11)), np.random.default_rng(5)
    for k in range(n):
        _salvar(_deformar(coef, campo_k(k)), pasta, k + 1, rng)
    return {
        "description": "Uniaxial tension (x) with a Gaussian strain concentration (necking) and grip slip.",
        "u_x(X,Y) [px]": "e0*(X-xc) + a*s*sqrt(pi)/2*erf((X-xc)/s) + slip",
        "u_y(X,Y) [px]": "-0.5*(e0 + a*exp(-((X-xc)/s)^2))*(Y-yc)",
        "engineering_strain_xx": "e0 + a*exp(-((X-xc)/s)^2)  (du/dx)",
        "xc_px": xc, "yc_px": yc, "s_px": s, "e0": e0.tolist(), "a": a.tolist(), "slip_px": desliz.tolist(),
        "peak_engineering_strain_xx": (e0 + a).tolist(),
        "peak_true_strain_xx": np.log1p(e0 + a).tolist(),
    }


def laminado(pasta, n=11, espessura=50.0):
    """Lâminas paralelas à carga (x) de dois materiais com razões de contração diferentes."""
    nus = (0.30, 0.48)                                  # razão de contração das lâminas A e B
    e = np.linspace(0, 0.04, n)
    y0 = BANDA[0]
    ys = np.arange(ALTURA, dtype=float)
    camada = (np.floor((ys - y0) / espessura).astype(int) % 2)
    nu_y = np.where(camada == 0, nus[0], nus[1])
    nu_y[(ys < BANDA[0]) | (ys > BANDA[1])] = 0.40
    yc = (BANDA[0] + BANDA[1]) / 2
    # v(Y) = -e * ∫_{yc}^{Y} nu(y) dy  (iso-deformação em x, contração diferente por lâmina)
    integ = np.cumsum(nu_y) - nu_y / 2
    integ -= np.interp(yc, ys, integ)
    xc = LARGURA / 2

    def campo_k(k):
        def f(X, Y):
            return e[k] * (X - xc), -e[k] * np.interp(Y, ys, integ)
        return f

    coef, rng = _coef(_material(23)), np.random.default_rng(7)
    for k in range(n):
        _salvar(_deformar(coef, campo_k(k)), pasta, k + 1, rng)
    return {
        "description": "Layered specimen: layers parallel to the load (x), alternating contraction ratios.",
        "layer_thickness_px": espessura, "first_layer_starts_at_y_px": y0,
        "contraction_ratio_A_B": nus, "engineering_strain_xx": e.tolist(),
        "u_x(X,Y) [px]": "e*(X-xc)", "u_y(X,Y) [px]": "-e*integral_yc^Y nu(y) dy",
        "expected_true_strain_yy_A": np.log1p(-nus[0] * e).tolist(),
        "expected_true_strain_yy_B": np.log1p(-nus[1] * e).tolist(),
    }


def dificil(pasta, n=13):
    """Tração uniforme com refoco (desfoque em dois quadros) e salto rígido de 14 px."""
    e = np.linspace(0, 0.03, n)
    salto = np.where(np.arange(n) >= 7, 14.0, 0.0)
    desfoque = {4: 1.6, 5: 2.2}
    xc, yc = LARGURA / 2, (BANDA[0] + BANDA[1]) / 2

    def campo_k(k):
        def f(X, Y):
            return e[k] * (X - xc) + salto[k], -0.33 * e[k] * (Y - yc) + 0.3 * salto[k]
        return f

    coef, rng = _coef(_material(37)), np.random.default_rng(9)
    for k in range(n):
        _salvar(_deformar(coef, campo_k(k)), pasta, k + 1, rng, desfoque=desfoque.get(k, 0.0))
    return {
        "description": "Uniform tension with two defocused frames (5 and 6) and a 14 px rigid jump from frame 8 on.",
        "engineering_strain_xx": e.tolist(), "contraction_ratio": 0.33,
        "rigid_jump_px": salto.tolist(), "blur_sigma_px_by_frame_index": desfoque,
        "expected_true_strain_xx": np.log1p(e).tolist(),
    }


EXEMPLOS = {
    "necking": (necking, ("Tração com estricção localizada (tutorial 1)", "Tension with localized necking (tutorial 1)")),
    "layered": (laminado, ("Amostra laminada, lâminas paralelas à carga (tutorial 2)", "Layered specimen, layers parallel to the load (tutorial 2)")),
    "difficult": (dificil, ("Refoco e salto rígido durante o ensaio (tutorial 3)", "Refocusing and a rigid jump during the test (tutorial 3)")),
}


def gerar(nome, destino):
    """Gera o exemplo ``nome`` em ``destino/nome`` (reaproveita se já existir). Devolve a pasta."""
    funcao, _ = EXEMPLOS[nome]
    pasta = Path(destino) / nome
    if (pasta / "ground_truth.json").exists():
        return pasta
    pasta.mkdir(parents=True, exist_ok=True)
    gt = funcao(pasta)
    gt.update({"example": nome, "image_size_px": [LARGURA, ALTURA], "specimen_band_y_px": BANDA,
               "coordinates": "origin at the lower-left image corner, x right, y up (as in Moby-DIC results)",
               "note": "Synthetic images generated by Moby-DIC; any scale can be used (e.g. 1 µm/px)."})
    (pasta / "ground_truth.json").write_text(json.dumps(gt, indent=1), encoding="utf-8")
    return pasta


def main(argv=None):
    from . import pasta_trabalho_padrao
    ap = argparse.ArgumentParser(prog="moby-dic exemplo", description=tx(
        "Gera sequências sintéticas de exemplo, com campo exato conhecido.",
        "Generates synthetic example sequences with a known exact field."))
    ap.add_argument("nome", nargs="?", choices=[*EXEMPLOS, "all"])
    ap.add_argument("--output", "--saida", dest="saida", metavar="FOLDER", type=Path, default=pasta_trabalho_padrao() / "examples")
    a = ap.parse_args(argv)
    if not a.nome:
        for k, (_, d) in EXEMPLOS.items():
            print(f"  {k:10s} {tx(*d)}")
        return 0
    for nome in (EXEMPLOS if a.nome == "all" else [a.nome]):
        print(gerar(nome, a.saida), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
