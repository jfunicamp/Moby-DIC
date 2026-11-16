"""Ponte de referência: a análise não pode ficar presa a uma referência que deixou de servir.

Situação real (refoco durante o ensaio): a referência é o último quadro bom, e todos os quadros
seguintes medem só parte dos pontos contra ela. Sem a ponte, todo quadro é "ruim", a referência
nunca muda e o resto do ensaio se perde. Aqui, a partir do quadro 1, a faixa esquerda da imagem
passa a ter outro padrão (fixo), então só ~65 % dos pontos casam com o quadro 0.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mobydic import subsets as ds  # noqa: E402
from tests.test_sintetico import deformar, speckle  # noqa: E402


def _rodar(extra):
    f = speckle(semente=5)
    outro = speckle(semente=9)
    h, w = f.shape
    corte = int(0.35 * w)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pasta = tmp / "imagens"
        pasta.mkdir()
        n = 8
        for k in range(n):
            base = f.copy()
            if k > 0:
                base[:, :corte] = outro[:, :corte]  # superfície mudou de aparência (fixa daqui em diante)
            img = base if k == 0 else deformar(base, lambda X, Y, k=k: (0.4 * k + 0.002 * k * (X - w / 2), 0 * Y))
            Image.fromarray(np.clip(np.flipud(img), 0, 255).astype(np.uint8)).save(pasta / f"q_{k + 1:03d}.png")
        saida = tmp / "resultado"
        ds.main(["--imagens", str(pasta), "--saida", str(saida), "--roi", "40", "40", str(w - 40), str(h - 40),
                 "--min-fraction", "0.8", "--threads", "2", *extra])
        meta = json.loads((saida / "parametros.json").read_text(encoding="utf-8"))
        with np.load(saida / "campos.npz") as z:
            estados = [str(e) for e in z["estado"]]
            valido = z["valido"]
            exx = z["deformacao_xx"]
        assert meta["quadros_ponte"] == [ds.PONTE_SEGUIDOS], (estados, meta)
        assert meta["quadros_ruins"] == list(range(1, ds.PONTE_SEGUIDOS)), estados
        depois = range(ds.PONTE_SEGUIDOS + 1, n)
        assert all(estados[k] == "convergiu" for k in depois), estados
        assert all(valido[k].mean() > 0.9 for k in depois), [float(valido[k].mean()) for k in depois]
        # a deformação continua coerente depois da ponte (εxx = ln(1 + 0,002 k))
        k = n - 1
        med = float(np.median(exx[k][valido[k]]))
        assert abs(med - np.log(1 + 0.002 * k)) < 1e-3, med
        return {"estados": estados, "exx_ultimo": med}


def test_ponte_destrava_referencia():
    _rodar([])


def test_ponte_com_referencia_fixa_sem_resgate():
    # passo fixo de referência (que nunca chegaria a trocar aqui) e sem resgate
    _rodar(["--reference-every", "100", "--no-rescue"])


if __name__ == "__main__":
    print(_rodar([]))
    print(_rodar(["--reference-every", "100", "--no-rescue"]))
