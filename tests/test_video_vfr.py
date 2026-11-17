"""Vídeo com taxa de quadros variável (como as câmeras de microscópio que gravam AVI com quadros nulos).

O arquivo declara 100 quadros/s, mas só há um quadro real a cada 0,15–0,30 s; os demais são
quadros nulos. O Moby-DIC precisa usar os tempos reais de cada quadro: contar os quadros reais,
achar a ruptura no instante certo e gravar em frames.csv os tempos verdadeiros.

Precisa do ffmpeg (pacote imageio-ffmpeg) para gerar o vídeo; sem ele o teste é pulado.
"""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from scipy import ndimage as nd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mobydic import video  # noqa: E402

N, H, W = 50, 200, 320


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def _video_vfr(pasta):
    """Speckle que se desloca 0,6 px por quadro e salta 30 px no último (ruptura); tempos irregulares."""
    rng = np.random.default_rng(5)
    campo = nd.gaussian_filter(rng.random((H, W + 80)), 2.0)
    campo = 255 * (campo - campo.min()) / np.ptp(campo)
    dt = 0.04 * rng.integers(4, 8, N - 1)     # múltiplos de 0,04 s: o concat do ffmpeg usa base de 1/25 s
    tempos = np.concatenate([[0.0], np.cumsum(dt)])
    desl = 0.6 * np.arange(N)
    desl[-1] += 30.0
    linhas = []
    for k in range(N):
        img = nd.shift(campo, (0, desl[k]), order=1, mode="nearest")[:, 40:40 + W]
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGB").save(pasta / f"q{k:03d}.png")
        linhas.append(f"file 'q{k:03d}.png'\nduration {dt[k] if k < N - 1 else 0.2:.2f}\n")
    (pasta / "lista.txt").write_text("".join(linhas), encoding="utf-8")
    arq = pasta / "vfr.avi"
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "lista.txt",
                    "-fps_mode", "passthrough", "-enc_time_base", "1/100", "-c:v", "rawvideo", "-pix_fmt", "bgr24", "vfr.avi"],
                   cwd=pasta, check=True)
    return arq, tempos


@pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg (imageio-ffmpeg) indisponível")
def test_video_taxa_variavel():
    with tempfile.TemporaryDirectory() as tmp:
        arq, tempos = _video_vfr(Path(tmp))
        info = video.informacoes(arq)
        assert info["vfr"], info
        assert info["n_quadros"] == N, info["n_quadros"]                    # quadros reais, não os nulos
        ts = video.tempos_quadros(arq)
        assert np.allclose(ts - ts[0], tempos, atol=0.011), np.abs(ts - ts[0] - tempos).max()
        assert abs(info["fps"] - (N - 1) / (tempos[-1] - tempos[0])) < 0.05
        s = video.sugerir(arq)
        assert s["ruptura"]
        assert tempos[-2] - 1e-6 <= s["ruptura_s"] - ts[0] <= tempos[-1] + 1e-6, s["ruptura_s"]
        assert abs(s["fim_s"] - ts[-2]) < 1e-6                              # último quadro íntegro
        alvo = video.alvos_extracao(arq, ts[2], ts[-2], 10, info)
        assert len(alvo) == 10 and alvo[0] == 2 and alvo[-1] == N - 2
        pasta = video.extrair(arq, ts[2], ts[-2], 10, Path(tmp) / "quadros")
        with (pasta / "frames.csv").open(encoding="utf-8") as f:
            t_csv = np.array([float(r["tempo_s"]) for r in csv.DictReader(f)])
        assert np.allclose(t_csv, ts[alvo], atol=1e-6)                      # tempos reais dos quadros
        assert len(list(pasta.glob("frame_*.png"))) == 10
        fonte = json.loads((pasta / "video_source.json").read_text(encoding="utf-8"))
        assert fonte["taxa_variavel"] is True


def test_extracao_nao_perde_quadros_pedidos():
    from mobydic.video import _distintos
    ts = np.array([0, 0.1, 0.2, 8, 9.0])
    idx = _distintos(np.interp(np.linspace(0, 9, 5), ts, np.arange(5)), 0, 4)
    assert list(idx) == [0, 1, 2, 3, 4]
    # mais alvos que quadros próximos: continuam distintos, crescentes e dentro do trecho
    idx = _distintos(np.array([0.0, 0.2, 0.4, 0.6, 9.0]), 0, 20)
    assert len(set(idx)) == 5 and list(idx) == sorted(idx) and idx[0] == 0 and idx[-1] == 9


def test_taxa_variavel_que_comeca_no_meio():
    """Câmera que só começa a perder quadros depois do começo: o início parece taxa constante."""
    from mobydic import video

    class Cap:
        def __init__(self, ts):
            self.ts, self.i = ts, -1

        def set(self, prop, v):
            self.i = int(v) - 1

        def grab(self):
            self.i += 1
            return self.i < len(self.ts)

        def get(self, prop):
            return 1000.0 * self.ts[self.i]

    fps = 100.0
    ini = np.arange(300) / fps                              # 3 s regulares
    resto = ini[-1] + np.cumsum(np.random.default_rng(1).uniform(0.1, 0.3, 300))
    ts = np.concatenate([ini, resto])
    assert video._taxa_variavel(Cap(ts), fps, len(ts))
    assert not video._taxa_variavel(Cap(np.arange(600) / fps), fps, 600)


def test_taxa_variavel_em_video_curto():
    """Vídeo curto (60 quadros): 40 regulares a 100 quadros/s e depois passos de 30 ms."""
    from mobydic import video

    class Cap:
        def __init__(self, ts):
            self.ts, self.i = ts, -1

        def set(self, prop, v):
            self.i = int(v) - 1

        def grab(self):
            self.i += 1
            return self.i < len(self.ts)

        def get(self, prop):
            return 1000.0 * self.ts[self.i]

    ts = np.concatenate([np.arange(40) / 100.0, 0.39 + 0.03 * np.arange(1, 21)])
    assert video._taxa_variavel(Cap(ts), 100.0, 98)
    assert not video._taxa_variavel(Cap(np.arange(98) / 100.0), 100.0, 98)


def test_taxa_variavel_sem_contagem_de_quadros():
    """Contêiner que não informa o número de quadros: a mudança de taxa vem depois do quadro 120."""
    from mobydic import video

    class Cap:
        def __init__(self, ts):
            self.ts, self.i = ts, -1

        def set(self, prop, v):
            self.i = int(v) - 1

        def grab(self):
            self.i += 1
            return self.i < len(self.ts)

        def get(self, prop):
            return 1000.0 * self.ts[self.i]

    ts = np.concatenate([np.arange(150) / 100.0, 1.49 + 0.03 * np.arange(1, 101)])
    assert video._taxa_variavel(Cap(ts), 100.0, 0)
    assert not video._taxa_variavel(Cap(np.arange(250) / 100.0), 100.0, 0)


@pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg (imageio-ffmpeg) indisponível")
def test_taxa_de_aquisicao_nominal():
    """--acquisition-fps: o k-ésimo quadro real fica em k/taxa (relógio da câmera, não o do arquivo)."""
    with tempfile.TemporaryDirectory() as tmp:
        arq, _ = _video_vfr(Path(tmp))
        FPS_AQ = 5.0
        info = video.informacoes(arq, fps_aquisicao=FPS_AQ)
        assert info["vfr"] and info["n_quadros"] == N
        assert info["fps"] == FPS_AQ and info["fps_aquisicao"] == FPS_AQ
        assert abs(info["fps_arquivo"] - video.informacoes(arq)["fps"]) < 1e-9
        assert abs(info["duracao_s"] - N / FPS_AQ) < 1e-9
        s = video.sugerir(arq, fps_aquisicao=FPS_AQ)
        assert s["ruptura"]
        assert abs(s["ruptura_s"] - (N - 1.5) / FPS_AQ) < 1e-9                # entre os quadros N−2 e N−1
        assert abs(s["fim_s"] - (N - 2) / FPS_AQ) < 1e-9
        assert np.allclose(s["tempos_quadros"], np.arange(N) / FPS_AQ)
        pasta = Path(tmp) / "quadros"
        assert video.main([str(arq), "--output", str(pasta), "--start", "0.4", "--end", str((N - 2) / FPS_AQ),
                           "--frames", "10", "--acquisition-fps", str(FPS_AQ)]) == 0
        with (pasta / "frames.csv").open(encoding="utf-8") as f:
            linhas = list(csv.DictReader(f))
        k = np.array([int(r["quadro_video"]) for r in linhas])
        assert k[0] == 2 and k[-1] == N - 2 and len(k) == 10
        assert np.allclose([float(r["tempo_s"]) for r in linhas], k / FPS_AQ, atol=1e-4)
        fonte = json.loads((pasta / "video_source.json").read_text(encoding="utf-8"))
        assert fonte["fps"] == FPS_AQ and fonte["fps_aquisicao"] == FPS_AQ and fonte["base_tempo"] == "aquisicao"
        assert abs(fonte["ruptura_s"] - (N - 1.5) / FPS_AQ) < 1e-9
        # a mesma ruptura nas duas bases: o quadro é o mesmo, só o relógio muda
        ts = video.tempos_quadros(arq)
        assert abs(np.interp(video.sugerir(arq)["ruptura_s"], ts, np.arange(N)) - (N - 1.5)) < 1e-6
        with pytest.raises(ValueError):
            video.informacoes(arq, fps_aquisicao=0)
