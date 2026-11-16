"""Moby-DIC · escolha automática dos parâmetros da análise (ROI, subset, passo, foco).

Coordenadas: as funções recebem e devolvem a ROI em pixels com origem no canto INFERIOR esquerdo
(o sistema interno do Moby-DIC); ``roi_para_imagem`` converte para o sistema da imagem (origem no
canto superior esquerdo), usado na tela.

Regras:
- ROI: bordas da amostra (região clara/pintada sobre fundo escuro) detectadas em ~8 quadros; usa a
  interseção (região que é amostra em todos os quadros, descartando o quadro mais extremo) menos
  uma margem; nas laterais a margem é de pelo menos 10 % da largura, para o deslocamento axial.
  Se não houver contraste claro amostra/fundo, usa a imagem inteira menos as margens.
- Speckle: comprimento de correlação da imagem (onde a autocorrelação cai a 0,5); diâmetro ≈ 2×.
- Subset: ímpar, ≈ 3,25 diâmetros de speckle (≥ 3 speckles por lado), entre 15 e 61 px.
- Passo da grade: ≈ subset/5; janela de deformação: 5 pontos; elemento Q4: ≈ subset.
- Foco: nitidez (energia do Laplaciano) nos quadros amostrados; se varia mais de 3×, recomenda
  igualar a nitidez e indica os quadros com refoco.
- Qualidade do padrão (speckle ou textura natural, como a microestrutura atacada): erro previsto do
  deslocamento σu ≈ √2·σ_ruído / √SSSIG em cada subset (Pan et al. 2008), com SSSIG = soma dos
  quadrados dos gradientes de intensidade no subset (na direção menos texturizada) e σ_ruído
  estimado na própria imagem. Regiões com σu > 0,05 px praticamente não são medíveis.
"""

import json

import numpy as np
from PIL import Image
from scipy import ndimage as nd

from .imagens import EXTENSOES, ler_cinza, listar_imagens, selecionar  # noqa: F401


def nitidez(img, roi=None):
    if roi is not None:
        x1, y1, x2, y2 = (int(round(v)) for v in roi)
        img = img[y1:y2, x1:x2]
    return float((nd.laplace(img) ** 2).mean())


def bordas_amostra(img):
    """(y_min, y_max, x_min, x_max) da faixa clara (amostra pintada), origem inferior."""
    h, w = img.shape
    perfil_y = img[:, int(0.15 * w):int(0.85 * w)].mean(1)
    # sem fundo escuro (a amostra ocupa o campo todo, como em microscopia): imagem inteira
    if np.percentile(perfil_y, 5) > 0.33 * np.percentile(perfil_y, 95):
        return 0, h - 1, 0, w - 1
    lim = 0.5 * (np.percentile(perfil_y, 95) + np.percentile(perfil_y, 5))
    # faixas escuras com textura (ex.: camada atacada) também são amostra; fundo é escuro e liso
    textura = np.abs(img - nd.uniform_filter(img, 9))[:, int(0.15 * w):int(0.85 * w)].mean(1)
    escuras, claras = perfil_y <= lim, perfil_y > lim
    if escuras.any() and claras.any() and np.median(textura[escuras]) >= 0.5 * np.median(textura[claras]):
        return 0, h - 1, 0, w - 1
    linhas = np.nonzero(perfil_y > lim)[0]
    y0, y1 = (int(linhas.min()), int(linhas.max())) if linhas.size else (0, h - 1)
    meio = img[y0 + (y1 - y0) // 4: y1 - (y1 - y0) // 4]
    perfil_x = meio.mean(0)
    lim = 0.5 * (np.percentile(perfil_x, 95) + np.percentile(perfil_x, 5))
    cols = np.nonzero(perfil_x > lim)[0]
    x0, x1 = (int(cols.min()), int(cols.max())) if cols.size else (0, w - 1)
    if (y1 - y0) < 0.2 * h or (x1 - x0) < 0.2 * w:   # sem faixa clara definida: imagem inteira
        return 0, h - 1, 0, w - 1
    return y0, y1, x0, x1


def tamanho_speckle(img, roi):
    """Diâmetro médio do speckle (px) pela autocorrelação 2D da região central da ROI."""
    x1, y1, x2, y2 = (int(round(v)) for v in roi)
    a = img[y1:y2, x1:x2]
    h, w = a.shape
    a = a[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    a = a - nd.uniform_filter(a, 41)  # remove variação lenta de iluminação
    f = np.fft.fft2(a)
    ac = np.fft.fftshift(np.real(np.fft.ifft2(f * np.conj(f))))
    ac /= ac.max()
    cy, cx = np.array(ac.shape) // 2
    raio = []
    for perfil in (ac[cy, cx:], ac[cy:, cx]):
        abaixo = np.nonzero(perfil < 0.5)[0]
        if abaixo.size:
            i = abaixo[0]
            # interpolação linear entre i-1 e i
            raio.append(i - 1 + (perfil[i - 1] - 0.5) / (perfil[i - 1] - perfil[i]))
    r = float(np.mean(raio)) if raio else 3.0
    return 2.0 * r


def ruido_imagem(img):
    """Desvio-padrão do ruído (níveis de cinza) estimado numa única imagem (Immerkær 1996, versão
    robusta pela mediana, pouco sensível às bordas da textura)."""
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], float)
    c = nd.convolve(np.asarray(img, float), k)[1:-1, 1:-1]
    return float(1.4826 * np.median(np.abs(c)) / 6.0)


def mapa_qualidade(img, subset, ruido=None):
    """Erro previsto do deslocamento (px) para um subset centrado em cada pixel, na pior direção.

    SSSIG generalizado: menor autovalor da matriz de estrutura [[Σgx², Σgxgy], [Σgxgy, Σgy²]] do
    subset. Para textura isotrópica é igual ao menor de Σgx² e Σgy²; para listras (inclusive
    diagonais) vai a ~0, porque o deslocamento ao longo das listras não é observável."""
    img = np.asarray(img, float)
    ruido = ruido if ruido is not None else ruido_imagem(img)
    gx, gy = nd.sobel(img, 1) / 8.0, nd.sobel(img, 0) / 8.0
    a = subset * subset
    sx, sy = nd.uniform_filter(gx * gx, subset) * a, nd.uniform_filter(gy * gy, subset) * a
    sxy = nd.uniform_filter(gx * gy, subset) * a
    lmin = 0.5 * (sx + sy) - np.sqrt(0.25 * (sx - sy) ** 2 + sxy ** 2)
    return np.sqrt(2.0) * max(ruido, 0.3) / np.sqrt(np.maximum(lmin, 0.0) + 1e-9)


def qualidade_padrao(img, subset, roi=None, ruido=None):
    """Resumo da qualidade do padrão na ROI: mediana de σu e frações com σu < 0,02 e < 0,05 px."""
    ruido = ruido if ruido is not None else ruido_imagem(img)
    m = mapa_qualidade(img, subset, ruido)
    if roi is not None:
        x1, y1, x2, y2 = (int(round(v)) for v in roi)
        m = m[max(0, y1):y2, max(0, x1):x2]
    return {"ruido_gl": round(ruido, 2), "mediana_sigma_px": round(float(np.median(m)), 4),
            "frac_boa": round(float((m < 0.02).mean()), 3), "frac_aceitavel": round(float((m < 0.05).mean()), 3)}


def gradiente_medio(img, roi):
    """Média de |∇I| na ROI (qualidade do padrão: maior é melhor)."""
    x1, y1, x2, y2 = (int(round(v)) for v in roi)
    gy, gx = np.gradient(img[y1:y2, x1:x2])
    return float(np.hypot(gx, gy).mean())


def impar(v):
    v = int(round(v))
    return v if v % 2 else v + 1


def sugerir(pasta, inicio=1, fim=None, a_cada=1, n_amostras=8):
    """Analisa a sequência e devolve um dicionário com todas as sugestões automáticas."""
    todos = listar_imagens(pasta)
    if len(todos) < 2:
        raise ValueError("A pasta precisa ter pelo menos duas imagens.")
    sel = selecionar(todos, inicio, fim, a_cada)
    idx = sorted(set(np.linspace(0, len(sel) - 1, min(n_amostras, len(sel))).round().astype(int).tolist()))
    imgs, origem = {}, {}
    for i in idx:                       # amostra: arquivo ilegível é trocado pelo vizinho legível
        for j in sorted(range(len(sel)), key=lambda q: abs(q - i))[:20]:
            try:
                imgs[i] = ler_cinza(sel[j])
                origem[i] = j
                break
            except Exception:  # noqa: BLE001
                continue
    idx = [i for i in idx if i in imgs]
    if not idx:
        raise ValueError("Não foi possível ler as imagens da pasta.")
    h, w = imgs[idx[0]].shape
    with Image.open(sel[origem[idx[0]]]) as im:
        modo = im.mode

    bordas = [bordas_amostra(imgs[i]) for i in idx]
    # Interseção robusta: descarta o quadro mais extremo (ex.: imagem final já rompida).
    def robusto(vals, maior):
        v = sorted(vals, reverse=maior)
        return v[1] if len(v) >= 4 else v[0]
    ya = robusto([b[0] for b in bordas], True)
    yb = robusto([b[1] for b in bordas], False)
    xa = robusto([b[2] for b in bordas], True)
    xb = robusto([b[3] for b in bordas], False)

    # Primeiro palpite de ROI para medir o speckle, depois margem final com o subset.
    roi0 = (xa + 0.1 * (xb - xa), ya + 0.1 * (yb - ya), xb - 0.1 * (xb - xa), yb - 0.1 * (yb - ya))
    speckle = tamanho_speckle(imgs[idx[0]], roi0)
    subset = int(np.clip(impar(3.25 * speckle), 15, 61))
    passo = max(2, int(round(subset / 5)))
    margem = max(20, subset // 2 + 8)
    # Margem lateral de 10 % da largura: espaço para o deslocamento axial (carga em x).
    mx = max(margem, int(0.10 * w))
    x1 = max(xa + margem, mx)
    x2 = min(xb - margem, w - 1 - mx)
    y1, y2 = ya + margem, yb - margem
    roi = [float(x1), float(y1), float(x2), float(y2)]

    padrao = qualidade_padrao(imgs[idx[0]], subset, roi)
    nit = [nitidez(imgs[i], roi) for i in idx]
    variacao = max(nit) / max(min(nit), 1e-9)
    brilho = [float(imgs[i][int(y1):int(y2), int(x1):int(x2)].mean()) for i in idx]

    return {
        "pasta": str(pasta), "n_imagens_pasta": len(todos), "n_quadros": len(sel),
        "largura": w, "altura": h, "modo": modo, "primeira": sel[0].name, "ultima": sel[-1].name,
        "roi": roi, "bordas_amostra": [xa, ya, xb, yb],
        "speckle_px": round(speckle, 2), "gradiente_medio": round(gradiente_medio(imgs[idx[0]], roi), 2),
        "subset_px": subset, "passo_px": passo, "janela_deformacao": 5, "elemento_q4_px": subset + 5,
        "quadros_amostrados": idx, "nitidez": [round(v, 2) for v in nit], "brilho": [round(v, 1) for v in brilho],
        "variacao_nitidez": round(variacao, 2), "igualar_nitidez": bool(variacao > 3.0), "padrao": padrao,
        "referencia": "automatica", "zncc_ref": 0.98, "zncc_ref_p05": 0.95, "falha_ref": 0.003,
        "zncc_min": 0.8,
    }


def roi_para_imagem(roi, altura):
    """ROI origem inferior -> origem superior (x1, y1_topo, x2, y2_topo)."""
    x1, y1, x2, y2 = roi
    return [x1, altura - 1 - y2, x2, altura - 1 - y1]


def roi_de_imagem(roi_img, altura):
    x1, yt1, x2, yt2 = roi_img
    return [x1, altura - 1 - yt2, x2, altura - 1 - yt1]


if __name__ == "__main__":
    import sys
    r = sugerir(sys.argv[1], a_cada=int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    print(json.dumps(r, ensure_ascii=False, indent=1))
