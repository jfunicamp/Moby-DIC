"""Testes do Moby-DIC com imagens sintéticas (não dependem de dados externos).

    python -m pytest tests            # ou
    python tests/test_sintetico.py

1. Precisão do núcleo IC-GN: padrão de speckle sintético deformado por um campo conhecido
   (translação + estiramento + cisalhamento + senoide); erro de deslocamento e de deformação.
2. Fluxo completo: sequência de 6 imagens com deformação crescente, análise pela linha de comando
   (`mobydic subsets`), leitura de campos.npz e geração do visualizador.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mobydic import subsets as ds  # noqa: E402
from mobydic.viewer import gerar  # noqa: E402


def speckle(h=420, w=620, semente=1):
    """Padrão de speckle: manchas escuras de ~6 px sobre fundo claro."""
    rng = np.random.default_rng(semente)
    campo = nd.gaussian_filter(rng.random((h, w)), 2.2)
    campo = (campo - campo.mean()) / campo.std()
    img = 200 - 150 / (1 + np.exp(-4 * (campo - 0.3)))
    return nd.gaussian_filter(img, 0.7)


def deformar(f, campo):
    """g(x) = f(X(x)) com x = X + u(X), invertido por ponto fixo."""
    h, w = f.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    X, Y = xx.copy(), yy.copy()
    for _ in range(30):
        u, v = campo(X, Y)
        X, Y = xx - u, yy - v
    return nd.map_coordinates(ds.coeficientes(f), [Y, X], order=3, prefilter=False, mode="mirror")


def test_precisao_icgn():
    f = speckle()
    h, w = f.shape
    xc, yc = w / 2, h / 2
    a, b, exx, eyy, amp, lam = 2.3, -1.7, 0.02, -0.01, 1.0, 250.0

    def campo(X, Y):
        u = a + exx * (X - xc) + 0.004 * (Y - yc) + amp * np.sin(2 * np.pi * (X - xc) / lam)
        return u, b + eyy * (Y - yc)

    g = deformar(f, campo)
    cr, ct = ds.coeficientes(f), ds.coeficientes(g)
    xs, ys = np.meshgrid(np.arange(60, w - 60, 5.0), np.arange(60, h - 60, 5.0))
    centros = np.c_[xs.ravel(), ys.ravel()]
    uv = np.array(campo(centros[:, 0], centros[:, 1])).T
    rng = np.random.default_rng(0)
    params = np.zeros((len(centros), 6))
    params[:, 0] = uv[:, 0] + rng.uniform(-1.5, 1.5, len(centros))
    params[:, 3] = uv[:, 1] + rng.uniform(-1.5, 1.5, len(centros))
    z, it, ok = ds.correlacionar_quadro(cr, ct, centros, params, np.ones(len(centros), bool), 12, 50, 1e-3, 0.8, 6)
    erro_u = params[ok, 0] - uv[ok, 0]
    erro_v = params[ok, 3] - uv[ok, 1]
    assert ok.mean() > 0.99
    assert np.std(erro_u) < 0.02 and np.std(erro_v) < 0.02, (np.std(erro_u), np.std(erro_v))
    ny, nx = xs.shape
    grad, val = ds.gradiente_local(np.stack([params[:, 0], params[:, 3]], -1).reshape(ny, nx, 2),
                                   ok.reshape(ny, nx), 5.0, 2)
    dudx = exx + amp * 2 * np.pi / lam * np.cos(2 * np.pi * (xs - xc) / lam)
    e1 = (grad[..., 0, 0] - 1 - dudx)[val]
    e2 = (grad[..., 1, 1] - 1 - eyy)[val]
    assert np.std(e1) < 5e-4 and np.std(e2) < 5e-4, (np.std(e1), np.std(e2))
    return {"pontos": int(ok.sum()), "erro_u_px": float(np.std(erro_u)), "erro_v_px": float(np.std(erro_v)),
            "erro_dudx_pct": float(np.std(e1) * 100), "erro_dvdy_pct": float(np.std(e2) * 100)}


def test_fluxo_completo():
    f = speckle(semente=3)
    h, w = f.shape
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pasta = tmp / "imagens"
        pasta.mkdir()
        alongamentos = np.linspace(0, 0.03, 6)
        for k, e in enumerate(alongamentos):
            img = f if k == 0 else deformar(f, lambda X, Y, e=e: (e * (X - w / 2) + 0.5 * k, -0.3 * e * (Y - h / 2)))
            # imagem em orientação de arquivo (origem superior); o Moby-DIC inverte na leitura
            Image.fromarray(np.clip(np.flipud(img), 0, 255).astype(np.uint8)).save(pasta / f"quadro_{k + 1:03d}.png")
        saida = tmp / "resultado"
        ds.main(["--imagens", str(pasta), "--saida", str(saida), "--escala-um-px", "2.0",
                 "--roi", "80", "60", str(w - 80), str(h - 60), "--threads", "2"])
        with np.load(saida / "campos.npz") as zz:
            z = {k: zz[k] for k in zz.files}
        v = z["valido"]
        exx = [float(np.median(z["deformacao_xx"][t][v[t]])) for t in range(len(v))]
        eyy = [float(np.median(z["deformacao_yy"][t][v[t]])) for t in range(len(v))]
        esperado_xx = np.log(1 + alongamentos)
        esperado_yy = np.log(1 - 0.3 * alongamentos)
        assert np.allclose(exx, esperado_xx, atol=3e-4), (exx, esperado_xx)
        assert np.allclose(eyy, esperado_yy, atol=3e-4), (eyy, esperado_yy)
        assert v.mean() > 0.99
        meta = json.loads((saida / "parametros.json").read_text(encoding="utf-8"))
        assert meta["calibrado"] and meta["quadros"] == 6
        destino, mb = gerar(saida, 6.0, 400, 60)
        assert destino.exists() and mb > 0.1
        return {"exx_medido": exx, "exx_esperado": esperado_xx.tolist(), "pontos_validos": float(v.mean())}


if __name__ == "__main__":
    print("precisão IC-GN:", test_precisao_icgn())
    print("fluxo completo:", test_fluxo_completo())
    print("OK")
