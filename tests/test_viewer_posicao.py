"""Visualizador: gráfico tensão × posição da travessa (curva completa da máquina e o ponto do quadro).

Usa a sequência sintética de test_ensaio (fratura entre os arquivos 50 e 51, 4 quadros/s) com uma
curva de máquina que tem também a posição da travessa. Confere que ensaio.json guarda a posição na
curva reduzida e por quadro, e que o visualizador recebe os dados e oferece o gráfico.
"""

import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobydic import ensaio, subsets  # noqa: E402
from mobydic.viewer import gerar  # noqa: E402
from test_ensaio import FPS, T_FRAT, _sequencia  # noqa: E402

V_TRAVESSA = 0.01                    # mm/s


def _curva_com_posicao(arquivo):
    t = np.arange(0, 60, 0.05)
    F = np.where(t < T_FRAT, 1500 * (1 - np.exp(-t / 10)), 0.5)
    with arquivo.open("w", encoding="utf-8") as f:
        f.write('"Time", "Load (N)", "Position (mm)", "Stress (MPa)"\n')
        for a, b in zip(t, F):
            f.write(f"{a:.2f}, {b:.3f}, {V_TRAVESSA * a:.5f}, {b / 2.5:.3f}\n")


def test_grafico_tensao_posicao():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pasta = tmp / "imgs"
        pasta.mkdir()
        _sequencia(pasta)
        _curva_com_posicao(tmp / "ensaio.csv")
        c = ensaio.ler_curva(tmp / "ensaio.csv")
        assert c["sugestao"]["deslocamento"] == 2, c["sugestao"]
        res = tmp / "res"
        subsets.main(["--images", str(pasta), "--output", str(res), "--last", "48", "--every", "4",
                      "--roi", "40", "30", "280", "130", "--threads", "2"])
        r = ensaio.aplicar(res, c, c["sugestao"], "fratura", FPS)
        red, q = r["reduzida"], r["quadros"]
        # curva reduzida completa (até 60 s, depois da fratura) com a posição da travessa
        assert red["D"] is not None and len(red["D"]) == len(red["t"])
        assert np.allclose(red["D"], V_TRAVESSA * np.array(red["t"]), atol=1e-4)
        assert red["t"][-1] > T_FRAT
        assert np.allclose(q["deslocamento"], V_TRAVESSA * np.array(q["t_s"]), atol=1e-4)
        assert r["unidades"]["deslocamento"] == "mm"

        destino, _ = gerar(res, 8, 300, 70)
        html = destino.read_text(encoding="utf-8")
        dados = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1))
        ens = dados["ensaio"]
        assert ens["uD"] == "mm"
        assert np.allclose(ens["D"], q["deslocamento"][:len(ens["D"])])
        assert ens["red"]["D"] == red["D"]
        # opção no seletor de gráfico, nos dois idiomas, e exportação da figura com esse gráfico
        assert 'ops.push(["posicao"' in html
        assert 'gPosS:"tensão × posição da travessa"' in html and 'gPosS:"stress vs crosshead position"' in html
        assert "graficoDoEnsaio()" in html and 'modo === "posicao"' in html


def test_visualizador_sem_posicao_continua_funcionando():
    """ensaio.json antigo (sem 'D' na curva reduzida) ou curva sem posição: sem a opção, sem erro."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pasta = tmp / "imgs"
        pasta.mkdir()
        _sequencia(pasta, n=20)
        t = np.arange(0, 30, 0.05)
        with (tmp / "c.csv").open("w", encoding="utf-8") as f:
            f.write('"Time", "Load (N)"\n')
            f.writelines(f"{a:.2f}, {100 * a:.2f}\n" for a in t)
        c = ensaio.ler_curva(tmp / "c.csv")
        res = tmp / "res"
        subsets.main(["--images", str(pasta), "--output", str(res), "--last", "12", "--every", "4",
                      "--roi", "40", "30", "280", "130", "--threads", "2"])
        r = ensaio.aplicar(res, c, c["sugestao"], "manual", FPS, t_primeiro=1.0)
        assert r["reduzida"]["D"] is None and r["quadros"]["deslocamento"] is None
        destino, _ = gerar(res, 8, 300, 70)
        dados = json.loads(re.search(r"const D = (\{.*?\});\n", destino.read_text(encoding="utf-8"), re.S).group(1))
        assert dados["ensaio"]["D"] is None
