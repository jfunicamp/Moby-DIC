"""Vídeo do ensaio: recomendação automática do trecho e extração dos quadros.

Gera um vídeo sintético (parado → tração uniforme → parado) com o próprio OpenCV e confere que o
trecho recomendado cobre o ensaio e que a extração grava os quadros e os tempos.
"""

import csv
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy import ndimage as nd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mobydic import video  # noqa: E402

FPS = 20


def _video(caminho):
    import cv2
    rng = np.random.default_rng(2)
    h, w = 240, 400
    campo = nd.gaussian_filter(rng.random((h, w)), 2.0)
    campo = (campo - campo.mean()) / campo.std()
    base = 210 - 150 / (1 + np.exp(-4 * (campo - 0.3)))
    coef = nd.spline_filter(base, order=3, mode="mirror")
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    quadros = [0.0] * 30 + list(np.linspace(0, 0.05, 60)) + [0.05] * 30   # 1.5 s parado, 3 s de ensaio
    out = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (w, h), isColor=False)
    for e in quadros:
        img = nd.map_coordinates(coef, [yy, (xx - e * w / 2) / (1 + e) + e * w / 2 / (1 + e)], order=3,
                                 prefilter=False, mode="nearest")
        img = img + rng.normal(0, 1.0, img.shape)
        out.write(np.clip(img, 0, 255).astype(np.uint8))
    out.release()


def test_video_recomendacao_e_extracao():
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "ensaio.avi"
        _video(arq)
        s = video.sugerir(arq)
        assert s["n_quadros"] == 120 and abs(s["fps"] - FPS) < 0.01
        assert 1.0 <= s["inicio_s"] <= 1.6, s["inicio_s"]          # ensaio começa em 1,5 s
        assert 4.3 <= s["fim_s"] <= 4.8, s["fim_s"]                # e termina em 4,5 s
        assert not s["ruptura"]
        assert video.N_MIN <= s["n_extrair"] <= s["quadros_disponiveis"]
        pasta = video.extrair(arq, s["inicio_s"], s["fim_s"], 20, Path(tmp) / "quadros")
        pngs = sorted(pasta.glob("frame_*.png"))
        assert len(pngs) == 20
        with (pasta / "frames.csv").open(encoding="utf-8") as f:
            linhas = list(csv.DictReader(f))
        tempos = [float(r["tempo_s"]) for r in linhas]
        assert abs(tempos[0] - s["inicio_s"]) < 1 / FPS + 1e-9 and np.all(np.diff(tempos) > 0)
        return {"inicio_s": s["inicio_s"], "fim_s": s["fim_s"], "n_extrair": s["n_extrair"]}


if __name__ == "__main__":
    print(test_video_recomendacao_e_extracao())
