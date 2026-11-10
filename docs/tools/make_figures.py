"""Generates the figures of the documentation (theory and tutorials 2-4) from the example datasets.

    python docs/tools/make_figures.py

Runs the examples with the same automatic parameters the interface would choose, then plots the
results against the exact solutions and takes a screenshot of the viewer (Playwright + Edge).
Prints the numbers quoted in the tutorials.
"""

import asyncio
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
IMG = RAIZ / "docs" / "img"
TMP = Path(__file__).resolve().parent / "_build"
PY = str(RAIZ / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else sys.executable
ENV = {**os.environ, "MOBYDIC_LANG": "en"}
sys.path.insert(0, str(RAIZ))

from mobydic import auto  # noqa: E402

plt.rcParams.update({"font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 110, "savefig.dpi": 150})
AZUL, LARANJA, VERDE, CINZA = "#1d5aa0", "#d9822b", "#2a9d5c", "#555"


def mobydic(*args):
    subprocess.run([PY, "-m", "mobydic", *map(str, args)], cwd=RAIZ, env=ENV, check=True, stdout=subprocess.DEVNULL)


def analisar(nome, saida, janela=None):
    """Same command as the interface with every value automatic (and a 2 µm/px scale)."""
    pasta = TMP / "examples" / nome
    s = auto.sugerir(pasta)
    cmd = ["subsets", "--images", pasta, "--output", saida, "--scale-um-px", 2, "--roi", *s["roi"],
           "--subset", s["subset_px"], "--step", s["passo_px"], "--strain-window", janela or s["janela_deformacao"],
           "--zncc-min", s["zncc_min"], "--reference-every", 0, "--zncc-ref", s["zncc_ref"],
           "--zncc-ref-p05", s["zncc_ref_p05"], "--fail-ref", s["falha_ref"]]
    if s["igualar_nitidez"]:
        cmd.append("--match-sharpness")
    mobydic(*cmd)
    return s


def carregar(pasta):
    with np.load(Path(pasta) / "campos.npz") as z:
        return {k: z[k] for k in z.files}


def media_colunas(d, campo, t):
    return np.nanmean(np.where(d["valido"][t], d[campo][t], np.nan), axis=0)


def main():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    IMG.mkdir(parents=True, exist_ok=True)
    mobydic("example", "all", "--output", TMP / "examples")
    numeros = {}

    # ---------------------------------------------------------------- theory: subset and grid
    from mobydic.imagens import ler_cinza
    img = ler_cinza(TMP / "examples" / "necking" / "frame_001.png", origem_inferior=False)
    s = auto.sugerir(TMP / "examples" / "necking")
    y0, x0, h, w = 175, 380, 150, 240
    sub, passo = s["subset_px"], s["passo_px"]
    fig, ax = plt.subplots(figsize=(7.2, 4.6), layout="constrained")
    ax.imshow(img[y0:y0 + h, x0:x0 + w], cmap="gray", interpolation="nearest", extent=(0, w, h, 0))
    gx, gy = np.meshgrid(np.arange(12, w - 10, passo), np.arange(12, h - 10, passo))
    ax.plot(gx, gy, ".", color="#48defa", ms=2.2)
    cx, cy = gx[gx.shape[0] // 2, gx.shape[1] // 2], gy[gy.shape[0] // 2, gy.shape[1] // 2]
    ax.add_patch(plt.Rectangle((cx - sub / 2, cy - sub / 2), sub, sub, fill=False, ec="#ff4d6d", lw=2))
    ax.plot(cx, cy, "o", color="#ff4d6d", ms=5)
    ax.annotate(f"subset {sub} × {sub} px", (cx + sub / 2, cy - sub / 2), (cx + sub / 2 + 18, cy - sub / 2 - 22),
                color="#ff4d6d", fontsize=11, fontweight="bold", arrowprops=dict(arrowstyle="-", color="#ff4d6d"),
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=2))
    ax.annotate("", (gx[2, 3], gy[2, 3] - 6), (gx[2, 4], gy[2, 4] - 6), arrowprops=dict(arrowstyle="<->", color="#48defa"))
    ax.text((gx[2, 3] + gx[2, 4]) / 2 + 8, gy[2, 3] - 9, f"step {passo} px", color="#1d5aa0", ha="left", fontsize=10,
            fontweight="bold", bbox=dict(fc="white", ec="none", alpha=0.85, pad=2))
    ax.set(xlabel="px", ylabel="px", title=f"Speckle (measured size ≈ {s['speckle_px']:.1f} px), grid points and one subset")
    fig.savefig(IMG / "theory-subset.png")
    plt.close(fig)

    # ---------------------------------------------------------------- necking: strain windows
    gt = json.loads((TMP / "examples" / "necking" / "ground_truth.json").read_text())
    perfis = {}
    for jan in (3, 5, 9):
        out = TMP / f"necking_w{jan}"
        analisar("necking", out, janela=jan)
        d = carregar(out)
        t = len(d["valido"]) - 1
        x = d["centro_xy_px"][0, 0, :, 0]
        perfis[jan] = (x, media_colunas(d, "deformacao_xx", t), d)
    x = np.linspace(0, 960, 800)
    t = len(gt["e0"]) - 1
    exato = lambda xx: np.log1p(gt["e0"][t] + gt["a"][t] * np.exp(-((xx - gt["xc_px"]) / gt["s_px"]) ** 2))  # noqa: E731
    fig, ax = plt.subplots(figsize=(7.2, 3.9), layout="constrained")
    ax.plot(x, 100 * exato(x), color="k", lw=2, label="exact")
    for jan, cor in zip((3, 5, 9), (LARANJA, AZUL, VERDE)):
        xx, pf, _ = perfis[jan]
        vsg = sub + (jan - 1) * passo
        ax.plot(xx, 100 * pf, color=cor, lw=1.4, label=f"window {jan} (VSG ≈ {vsg} px): peak {100 * np.nanmax(pf):.1f} %")
        numeros[f"neck_peak_w{jan}"] = round(100 * float(np.nanmax(pf)), 2)
    ax.set(xlim=(300, 720), xlabel="initial position x (px)", ylabel="εxx (%)",
           title="Necking example, last frame: axial true strain averaged over the height")
    ax.legend(frameon=False, fontsize=9.5)
    fig.savefig(IMG / "theory-vsg.png")
    plt.close(fig)
    numeros["neck_peak_exact"] = round(100 * float(exato(np.array([gt["xc_px"]]))[0]), 2)

    # tutorial 4: profile with default window
    xx, pf, d5 = perfis[5]
    fig, ax = plt.subplots(figsize=(7.2, 3.6), layout="constrained")
    ax.plot(x, 100 * exato(x), "k-", lw=1.8, label="exact")
    ax.plot(xx, 100 * pf, "o", ms=3, color=AZUL, label="Moby-DIC (mean over rows)")
    ax.set(xlabel="initial position x (px)", ylabel="εxx (%)", title="Strain profile through the neck, last frame")
    ax.legend(frameon=False)
    fig.savefig(IMG / "tutorial4-profile.png")
    plt.close(fig)
    numeros["neck_points"] = int(d5["valido"][0].size)
    numeros["neck_subset"], numeros["neck_step"] = sub, passo
    numeros["neck_valid_min"] = round(float(d5["valido"].mean(axis=(1, 2)).min()), 4)
    meta = json.loads((TMP / "necking_w5" / "parametros.json").read_text(encoding="utf-8"))
    numeros["neck_refs"] = meta["referencias_usadas"]

    # ---------------------------------------------------------------- layered
    out = TMP / "layered"
    sl = analisar("layered", out)
    d = carregar(out)
    gl = json.loads((TMP / "examples" / "layered" / "ground_truth.json").read_text())
    t = len(d["valido"]) - 1
    Y = d["centro_xy_px"][0, :, 0, 1]
    v = d["valido"][t]
    eyy = np.nanmedian(np.where(v, d["deformacao_yy"][t], np.nan), axis=1)
    exx = np.nanmedian(np.where(v, d["deformacao_xx"][t], np.nan), axis=1)
    razao = -eyy / exx
    th, yb = gl["layer_thickness_px"], gl["first_layer_starts_at_y_px"]
    camada = (np.floor((Y - yb) / th) % 2).astype(int)
    meio = np.abs(((Y - yb) % th) - th / 2) < th / 2 - 12
    numeros["layer_eyy_A"] = round(100 * float(np.median(eyy[(camada == 0) & meio])), 2)
    numeros["layer_eyy_B"] = round(100 * float(np.median(eyy[(camada == 1) & meio])), 2)
    numeros["layer_ratio_A"] = round(float(np.median(razao[(camada == 0) & meio])), 3)
    numeros["layer_ratio_B"] = round(float(np.median(razao[(camada == 1) & meio])), 3)
    numeros["layer_exx"] = round(100 * float(np.nanmedian(exx)), 2)
    numeros["layer_subset_step"] = (sl["subset_px"], sl["passo_px"])
    e = gl["engineering_strain_xx"][t]
    nus = gl["contraction_ratio_A_B"]
    fig, ax = plt.subplots(figsize=(5.6, 4.6), layout="constrained")
    for k in range(int((Y.max() - yb) // th) + 1):
        if k % 2 == 1:
            ax.axhspan(yb + k * th, yb + (k + 1) * th, color="#eeeeee", lw=0)
    yy = np.linspace(Y.min(), Y.max(), 600)
    cy = (np.floor((yy - yb) / th) % 2).astype(int)
    ex = np.where(cy == 0, -np.log1p(-nus[0] * e), -np.log1p(-nus[1] * e)) / np.log1p(e)
    ax.plot(ex, yy, "k-", lw=1.4, label="exact")
    ax.plot(razao, Y, "o-", ms=3, lw=1, color=AZUL, label="Moby-DIC (median along x)")
    ax.set(xlabel="contraction ratio −εyy/εxx", ylabel="initial y (px)", xlim=(0.15, 0.65),
           title="Layered example, last frame\n(grey: material B, ν = 0.48; white: A, ν = 0.30)")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    fig.savefig(IMG / "tutorial4-layers.png")
    plt.close(fig)

    # ---------------------------------------------------------------- difficult
    out = TMP / "difficult"
    sd = analisar("difficult", out)
    d = carregar(out)
    gd = json.loads((TMP / "examples" / "difficult" / "ground_truth.json").read_text())
    med = [float(np.median(d["deformacao_xx"][k][d["valido"][k]])) for k in range(len(d["valido"]))]
    numeros["difficult_max_err_pct"] = round(100 * float(np.max(np.abs(np.array(med) - gd["expected_true_strain_xx"]))), 4)
    numeros["difficult_valid_min"] = round(float(d["valido"].mean(axis=(1, 2)).min()), 4)
    numeros["difficult_sharp_var"] = round(sd["variacao_nitidez"], 2)
    numeros["difficult_match"] = sd["igualar_nitidez"]
    meta = json.loads((out / "parametros.json").read_text(encoding="utf-8"))
    numeros["difficult_refs"] = meta["referencias_usadas"]
    with (out / "convergencia.csv").open(encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    numeros["difficult_log"] = [(int(r["indice"]), int(r["referencia"]), round(float(r["zncc_mediana"]), 4),
                                 round(float(r["zncc_p05"]), 4), round(float(r["fracao_ativa"]), 4),
                                 float(r["sigma_igualacao_px"]), int(r["resgatados"])) for r in linhas]
    k = [0] + [int(r["indice"]) for r in linhas]
    zm = [1.0] + [float(r["zncc_mediana"]) for r in linhas]
    zp = [1.0] + [float(r["zncc_p05"]) for r in linhas]
    fa = [1.0] + [float(r["fracao_ativa"]) for r in linhas]
    ref = [0] + [int(r["referencia"]) for r in linhas]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 4.8), sharex=True, layout="constrained")
    a1.plot(k, zm, "o-", color=AZUL, label="median ZNCC")
    a1.plot(k, zp, "s--", color=LARANJA, ms=4, label="5th-percentile ZNCC")
    for kk in sorted(set(ref) - {0}):
        a1.axvline(kk, color=CINZA, lw=0.8, ls=":")
        a1.text(kk, 1.0005, f" ref → {kk}", fontsize=8.5, color=CINZA, va="bottom")
    a1.axvspan(3.6, 5.4, color="#f2d0a4", alpha=0.45, lw=0)
    a1.text(4.5, 0.952, "blurred", ha="center", fontsize=9, color="#8a5a1f")
    a1.axvline(7, color="#c0392b", lw=1)
    a1.text(7.08, 0.952, "rigid jump", fontsize=9, color="#c0392b")
    a1.set(ylabel="ZNCC", ylim=(0.945, 1.004))
    a1.legend(frameon=False, fontsize=9, loc="lower left")
    a2.plot(k, 100 * np.array(fa), "o-", color=VERDE)
    a2.plot(k, 100 * np.array(med), alpha=0)
    a2.set(ylabel="measured points (%)", xlabel="frame index", ylim=(98.5, 100.2))
    ax2 = a2.twinx()
    ax2.plot(k, 100 * np.array(med), "^-", color=CINZA, ms=4, lw=1)
    ax2.plot(k, 100 * np.array(gd["expected_true_strain_xx"]), "k:", lw=1)
    ax2.set_ylabel("mean εxx (%) — dotted: exact", color=CINZA)
    ax2.spines["right"].set_visible(True)
    fig.suptitle("Difficult example: convergence diagnostics (convergencia.csv)")
    fig.savefig(IMG / "tutorial3-convergence.png")
    plt.close(fig)

    # ---------------------------------------------------------------- viewer screenshot (layered)
    mobydic("viewer", TMP / "layered", "--lang", "en")
    asyncio.run(foto_viewer(TMP / "layered" / "visualizador.html", IMG / "tutorial2-viewer.png"))
    print(json.dumps(numeros, indent=1))
    (TMP / "numeros.json").write_text(json.dumps(numeros, indent=1))


async def foto_viewer(html, destino):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        nav = await p.chromium.launch(channel="msedge", headless=True)
        pg = await nav.new_page(viewport={"width": 1500, "height": 760}, device_scale_factor=1.3)
        await pg.goto(html.as_uri() + "?lang=en")
        await pg.locator("#grade canvas").first.wait_for()
        await pg.locator("#layout").select_option("2")
        await pg.wait_for_timeout(400)
        campos = pg.locator("section.painel select.campo")
        await campos.nth(0).select_option("4")      # transverse strain
        await campos.nth(1).select_option("11")     # contraction ratio
        await pg.locator("section.painel input.sim").first.uncheck()
        await pg.locator("section.painel button.quadroAuto").first.click()
        n = await pg.locator("#quadro").evaluate("e => +e.max")
        await pg.locator("#quadro").evaluate("(e, n) => { e.value = n; e.dispatchEvent(new Event('input')); }", n)
        await pg.wait_for_timeout(600)
        caixa = await pg.locator("#grade").bounding_box()
        await pg.screenshot(path=str(destino), clip={"x": 0, "y": 0, "width": 1500, "height": caixa["y"] + caixa["height"]})
        await nav.close()


if __name__ == "__main__":
    main()
