"""Correlação com o ensaio de tração: fratura na curva e nas imagens, tempo de cada quadro.

Sequência sintética a 4 quadros/s em que a amostra rompe entre os arquivos 50 e 51 (as metades se
afastam 30 px) e curva de máquina (CSV, 20 Hz, separador ; e decimal com vírgula) com a fratura em
42,30 s. O primeiro arquivo deve ficar em t₀ = 42,30 − (51 − 1,5)/4 = 29,925 s.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mobydic import ensaio, subsets  # noqa: E402

FPS, N_ROMPIDO, T_FRAT = 4.0, 51, 42.30


def _sequencia(pasta, n=60):
    rng = np.random.default_rng(4)
    h, w = 160, 320
    campo = nd.gaussian_filter(rng.random((h, w)), 2.0)
    campo = (campo - campo.mean()) / campo.std()
    base = 205 - 150 / (1 + np.exp(-4 * (campo - 0.3)))
    coef = nd.spline_filter(base, order=3, mode="mirror")
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    for k in range(1, n + 1):
        e = 0.0004 * min(k, N_ROMPIDO - 1)
        X = (xx - w / 2) / (1 + e) + w / 2
        if k >= N_ROMPIDO:                         # fratura no meio: metades se afastam 30 px
            X = np.where(xx < w / 2, X + 15, X - 15)
        img = nd.map_coordinates(coef, [yy, X], order=3, prefilter=False, mode="nearest")
        if k >= N_ROMPIDO:
            img[:, w // 2 - 15:w // 2 + 15] = 25
        img = img + rng.normal(0, 1.0, img.shape)
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(pasta / f"img_{k:03d}.png")


def _curva(arquivo):
    t = np.arange(0, 60, 0.05)
    F = np.where(t < T_FRAT, 1500 * (1 - np.exp(-t / 10)), 0.5)
    S = F / 2.5
    with arquivo.open("w", encoding="utf-8") as f:
        f.write('"Tempo (s)";"Força (N)";"Tensão (MPa)"\n')
        for a, b, c in zip(t, F, S):
            f.write(f"{a:.2f};{b:.3f};{c:.3f}\n".replace(".", ","))


def test_sincronizacao_pela_fratura():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pasta = tmp / "imgs"
        pasta.mkdir()
        _sequencia(pasta)
        _curva(tmp / "ensaio.csv")
        c = ensaio.ler_curva(tmp / "ensaio.csv")
        assert c["sugestao"]["tempo"] == 0 and c["sugestao"]["carga"] == 1 and c["sugestao"]["tensao"] == 2
        f = ensaio.fratura_curva(c["dados"][:, 0], c["dados"][:, 1])
        assert abs(f["t_s"] - T_FRAT) <= 0.05, f
        v = ensaio.varrer_imagens(pasta)
        fi = ensaio.fratura_imagens(v)
        assert fi and fi["n_rompido"] == N_ROMPIDO, fi
        res = tmp / "res"
        subsets.main(["--images", str(pasta), "--output", str(res), "--last", "48", "--every", "2",
                      "--roi", "40", "30", "280", "130", "--threads", "2"])
        r = ensaio.aplicar(res, c, c["sugestao"], "fratura", FPS, varredura=v)
        t0 = T_FRAT - (N_ROMPIDO - 1.5) / FPS
        assert abs(r["t_primeiro_s"] - t0) < 0.03, r["t_primeiro_s"]
        q = r["quadros"]
        assert q["indice_pasta"][:3] == [1, 3, 5]
        assert abs(q["t_s"][1] - (t0 + 2 / FPS)) < 0.03
        esperado = 1500 * (1 - np.exp(-np.array(q["t_s"]) / 10))
        assert np.allclose(q["carga"], esperado, rtol=2e-3)
        assert (res / "ensaio_por_quadro.csv").exists()
        manual = ensaio.aplicar(res, c, c["sugestao"], "manual", FPS, t_primeiro=10.0)
        assert abs(manual["quadros"]["t_s"][2] - (10.0 + 4 / FPS)) < 1e-9
        return {"t0": r["t_primeiro_s"], "fratura_curva": f["t_s"], "fratura_imagens": fi["n_rompido"]}


if __name__ == "__main__":
    print(test_sincronizacao_pela_fratura())
