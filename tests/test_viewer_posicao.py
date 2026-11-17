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


def _dados(destino):
    return json.loads(re.search(r"const D = (\{.*?\});\n", destino.read_text(encoding="utf-8"), re.S).group(1))


def test_quadros_anteriores_ao_dic():
    """DIC a partir do arquivo 21 (passo 4): os arquivos 1, 5, …, 17 entram como quadros só de imagem,
    com tempo, tensão e posição da travessa pela mesma sincronização; os campos começam no 21."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pasta = tmp / "imgs"
        pasta.mkdir()
        _sequencia(pasta)
        _curva_com_posicao(tmp / "ensaio.csv")
        c = ensaio.ler_curva(tmp / "ensaio.csv")
        res = tmp / "res"
        subsets.main(["--images", str(pasta), "--output", str(res), "--first", "21", "--last", "48", "--every", "4",
                      "--roi", "40", "30", "280", "130", "--threads", "2"])
        r = ensaio.aplicar(res, c, c["sugestao"], "fratura", FPS)
        q = r["quadros"]
        d = _dados(gerar(res, 8, 300, 70)[0])
        nomes = sorted(p.name for p in pasta.iterdir())
        assert d["pre"] == 5 and d["arquivos"][:5] == [nomes[k] for k in (0, 4, 8, 12, 16)], d["arquivos"][:6]
        assert d["arquivos"][5:] == q["arquivo"] and d["n"] == 5 + len(q["arquivo"])
        assert d["estado"][:5] == ["sem_dic"] * 5 and d["estado"][5] == "referencia"
        ens = d["ensaio"]
        assert len(ens["t"]) == len(ens["S"]) == len(ens["D"]) == d["n"]
        # mesma regra de tempo (índice na pasta / fps) e a curva da máquina nesses tempos
        t_esp = q["t_s"][0] + (np.array([0, 4, 8, 12, 16]) - 20) / FPS
        assert np.allclose(ens["t"][:5], t_esp, atol=1e-9)
        assert np.allclose(ens["D"][:5], V_TRAVESSA * t_esp, atol=2e-4)
        s_esp = 1500 * (1 - np.exp(-t_esp / 10)) / 2.5
        assert all(v is None for v, t in zip(ens["S"][:5], t_esp) if t < 0)
        ok = t_esp >= 0
        assert np.allclose(np.array(ens["S"][:5], dtype=float)[ok], s_esp[ok], rtol=2e-3)
        assert ens["t"][5:] == q["t_s"]

        # curva da máquina movida: usa a curva reduzida de ensaio.json (mesmos valores aqui)
        (tmp / "ensaio.csv").unlink()
        e2 = _dados(gerar(res, 8, 300, 70)[0])["ensaio"]
        assert np.allclose(np.array(e2["S"][:5], dtype=float)[ok], s_esp[ok], rtol=5e-3)

        # sem os quadros anteriores (opção), o visualizador fica como antes
        d2 = _dados(gerar(res, 8, 300, 70, anteriores=False)[0])
        assert d2["pre"] == 0 and d2["arquivos"] == q["arquivo"]
