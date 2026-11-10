"""Leitura de sequências de imagens (PNG, TIFF 8/16 bits, BMP, JPEG)."""

from pathlib import Path

import numpy as np
from natsort import natsorted
from PIL import Image

EXTENSOES = (".png", ".tif", ".tiff", ".bmp", ".jpg", ".jpeg")


def listar_imagens(pasta):
    """Imagens da pasta em ordem natural (img2 antes de img10)."""
    pasta = Path(pasta)
    return natsorted([p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in EXTENSOES],
                     key=lambda p: p.name)


def selecionar(arquivos, inicio=1, fim=None, a_cada=1):
    """Subconjunto 1-indexado [inicio, fim] tomando uma imagem a cada `a_cada`."""
    return arquivos[max(1, inicio) - 1:(fim or len(arquivos))][::max(1, a_cada)]


def ler_cinza(caminho, origem_inferior=True):
    """Imagem em tons de cinza como float64, preservando a profundidade de bits (16 bits incluído).

    Com origem_inferior=True a imagem é invertida verticalmente (linha 0 = base da imagem), que é
    o sistema de coordenadas usado em todo o Moby-DIC (x para a direita, y para cima)."""
    with Image.open(caminho) as im:
        if im.mode in ("L", "I", "F") or im.mode.startswith("I;16"):
            a = np.asarray(im, dtype=np.float64)
        else:
            a = np.asarray(im.convert("L"), dtype=np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    return np.flipud(a).copy() if origem_inferior else a


def para_8bits(a):
    """Converte um array qualquer em 8 bits para exibição (percentis 0,5–99,5)."""
    lo, hi = np.percentile(a, [0.5, 99.5])
    return (np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype(np.uint8)


def imagem_exibicao(caminho):
    """PIL.Image em 8 bits, orientação original (para miniaturas e fundos)."""
    with Image.open(caminho) as im:
        if im.mode == "L":
            return im.copy()
        if im.mode in ("RGB", "RGBA", "P", "LA"):
            return im.convert("L")
    return Image.fromarray(para_8bits(ler_cinza(caminho, origem_inferior=False)))
