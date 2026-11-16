"""Qualidade do padrão (erro previsto do deslocamento, SSSIG) e ROI automática em microscopia."""

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage as nd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mobydic import auto  # noqa: E402

rng = np.random.default_rng(7)
H, W = 300, 400


def _speckle(sigma=2.0, contraste=150.0):
    c = nd.gaussian_filter(rng.random((H, W)), sigma)
    return 60 + contraste * (c - c.min()) / np.ptp(c)


def test_ruido_estimado():
    img = _speckle() + rng.normal(0, 2.0, (H, W))
    assert 1.5 < auto.ruido_imagem(img) < 2.8


def test_qualidade_speckle_e_superficie_lisa():
    bom = auto.qualidade_padrao(_speckle() + rng.normal(0, 1.0, (H, W)), 25)
    liso = auto.qualidade_padrao(120 + rng.normal(0, 1.0, (H, W)), 25)
    assert bom["frac_boa"] > 0.95 and bom["mediana_sigma_px"] < 0.02, bom
    assert liso["frac_boa"] < 0.05 and liso["mediana_sigma_px"] > 0.05, liso
    # subset maior reduz o erro previsto (σu ∝ 1/subset para textura uniforme)
    m15 = auto.qualidade_padrao(_speckle(4.0, 30.0) + rng.normal(0, 2.0, (H, W)), 15)["mediana_sigma_px"]
    m45 = auto.qualidade_padrao(_speckle(4.0, 30.0) + rng.normal(0, 2.0, (H, W)), 45)["mediana_sigma_px"]
    assert m45 < 0.5 * m15


def test_roi_microscopia_campo_inteiro():
    # camadas alternadas: escura e texturizada (atacada) / clara e lisa, ocupando o campo todo
    img = np.where((np.arange(H)[:, None] // 50) % 2 == 0, 70 + 0.5 * _speckle(), 200.0) + rng.normal(0, 1.0, (H, W))
    assert auto.bordas_amostra(img) == (0, H - 1, 0, W - 1)


def test_roi_amostra_clara_sobre_fundo_escuro():
    img = 15 + rng.normal(0, 1.0, (H, W))
    img[80:220, 30:370] = _speckle()[80:220, 30:370] + 60
    y0, y1, x0, x1 = auto.bordas_amostra(img)
    assert abs(y0 - 80) <= 3 and abs(y1 - 219) <= 3 and abs(x0 - 30) <= 3 and abs(x1 - 369) <= 3


def test_listras_nao_sao_textura():
    # listras (horizontais, verticais e diagonais): o deslocamento ao longo delas não é observável
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    for fase in (0.3 * xx, 0.3 * yy, 0.3 * (xx + yy), 0.3 * (xx - 0.5 * yy)):
        q = auto.qualidade_padrao(120 + 80 * np.sin(fase) + rng.normal(0, 1.0, (H, W)), 25)
        assert q["frac_boa"] < 0.05 and q["mediana_sigma_px"] > 0.05, q
