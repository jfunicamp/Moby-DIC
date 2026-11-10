"""Records the narrated English video tutorial of Moby-DIC and the documentation screenshots.

    python docs/video/make_tutorial_video.py [--no-video]

What it does
------------
1. Creates an isolated demo environment (fresh preferences, so the first-run language dialog
   appears; a neutral working folder) and starts the Moby-DIC server from the source tree.
2. Synthesises the narration of every segment with the Windows speech synthesiser (SAPI).
3. Drives the interface in a headless Microsoft Edge with Playwright, following the script below,
   while a CDP screencast records the page. A cursor and subtitles are drawn on the page.
4. Saves screenshots for the documentation (docs/img/).
5. Assembles frames + narration into docs/video/Moby-DIC-tutorial.mp4 (H.264/AAC, 1080p) and
   writes matching subtitles (.srt).

Requirements: Windows, Microsoft Edge, `pip install playwright imageio-ffmpeg`.
"""

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = Path(__file__).resolve().parent
IMG = RAIZ / "docs" / "img"
DEMO = Path(os.environ.get("MOBYDIC_DEMO", r"C:\Users\Public\Moby-DIC-demo"))
TMP = SAIDA / "_build"
PORTA = 8791
VW, VH, ESC = 1600, 900, 1.2          # viewport (CSS px) and device scale -> 1920x1080 frames
TAXA = 44100

# ----------------------------------------------------------------------------- narration
NARRACAO = [
    ("intro", "Welcome to Moby-DIC, free software for two-dimensional digital image correlation. "
              "In this tutorial we run a complete analysis of a tensile test, from the images to the strain maps."),
    ("idioma", "On the first start, Moby-DIC asks for your language. The interface, the messages and the figures "
               "will all follow this choice, and you can change it later in the top bar."),
    ("inicio", "Next, you can analyse your own images, try an example, or read the documentation. We will use the "
               "built-in example: a synthetic tensile test with a growing neck, whose exact solution is known."),
    ("imagens", "On the left is the workflow, in eight steps. Step one shows the image sequence: thirteen frames, "
                "the first and the last images, and the sharpness of the sequence. The focus is stable. "
                "Every parameter already has an automatic value."),
    ("escala", "Step two is the scale, in micrometres per pixel, which comes from a calibration of your set-up. "
               "These synthetic images have no physical scale, so we simply enter two. Strains do not depend on it."),
    ("roi", "Step three is the region of interest. The dashed yellow line marks the specimen edges, detected "
            "along the whole sequence. The cyan rectangle is the automatic region, kept inside the specimen with a margin."),
    ("roi2", "You can draw, move or resize it with the mouse, check it on the last frame, "
             "and return to the automatic region at any time."),
    ("metodo", "Step four chooses the algorithm and the grid. Local subset correlation is recommended. "
               "The subset size and the grid step were computed from the measured speckle size. Below the preview, "
               "Moby-DIC shows the number of points, the spatial resolution of the strain, and the expected run time."),
    ("referencia", "Step five controls the reference image. In automatic mode, the reference is updated only when "
                   "the correlation quality drops, which keeps accumulated errors small. Lost points are rescued "
                   "against the previous frame."),
    ("saida", "Step six sets the working folder and the name of the analysis. Each analysis gets its own folder."),
    ("executar", "Step seven summarises the configuration, and shows which values are automatic. Let's start the analysis."),
    ("rodando", "The analysis runs on this computer, in parallel. For every frame, the log shows the reference used, "
                "the fraction of measured points, and the correlation quality, where one would be a perfect match."),
    ("pronto", "When the correlation is finished, the interactive viewer is built. Let's open it."),
    ("visualizador", "The viewer opens with four panels: the horizontal and vertical displacements, and the axial "
                     "and transverse strains. Press play to animate the test, or step through it frame by frame."),
    ("exx", "Let's focus on the axial strain. We switch to a single panel and select the axial strain, epsilon x x, "
            "in the last frame."),
    ("leitura", "The neck has formed in the middle of the specimen. Hovering over the map reads the values. At the "
                "centre of the neck the strain is about seventeen percent, very close to the exact value. "
                "The small difference comes from the spatial resolution of the strain calculation."),
    ("incremento", "Derived fields are computed on the fly. The axial strain increment shows where the specimen is "
                   "deforming right now. Near the end of the test, almost all of the deformation happens in the neck."),
    ("escalas", "Colour scales can be automatic, taken from the current frame, or typed in, and thirteen colormaps "
                "are available."),
    ("exportar", "The export panel saves the current figure, a range of frames as images, or a video of the animation. "
                 "The viewer is a single file, which you can share with colleagues."),
    ("docs", "The documentation, available from the top bar, explains every option and the theory behind the method, "
             "and includes more tutorials. Thank you for watching, and enjoy Moby-DIC."),
]
TEXTO = dict(NARRACAO)


def sintetizar():
    """WAV (44.1 kHz, 16-bit mono) of each segment with SAPI; returns durations in seconds."""
    pasta = TMP / "voz"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "textos.json").write_text(json.dumps(dict(NARRACAO)), encoding="utf-8")
    ps1 = pasta / "falar.ps1"
    ps1.write_text(r"""
Add-Type -AssemblyName System.Speech
$t = Get-Content -Raw -Encoding UTF8 '%s' | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Zira Desktop')
$s.Rate = 0
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(44100, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($p in $t.PSObject.Properties) {
  $s.SetOutputToWaveFile((Join-Path '%s' ($p.Name + '.wav')), $f)
  $s.Speak($p.Value)
}
$s.SetOutputToNull()
""" % (pasta / "textos.json", pasta), encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)], check=True)
    dur = {}
    for k, _ in NARRACAO:
        with wave.open(str(pasta / f"{k}.wav")) as w:
            dur[k] = w.getnframes() / w.getframerate()
    return dur


# ----------------------------------------------------------------------------- page overlays
OVERLAY_JS = r"""
(() => {
  const css = `#__cur{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;
     transform:translate(-3px,-2px);transition:opacity .2s;display:none}
   #__rip{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:3px solid #ffb703;
     z-index:2147483646;pointer-events:none;opacity:0}
   #__cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:78%;background:rgba(10,14,22,.82);
     color:#fff;font:500 19px/1.4 "Segoe UI",system-ui,sans-serif;padding:9px 18px;border-radius:10px;z-index:2147483645;
     pointer-events:none;text-align:center;opacity:0;transition:opacity .25s}
   #__tit{position:fixed;inset:0;z-index:2147483640;background:linear-gradient(135deg,#0d2c55,#14427a 55%,#1d5aa0);color:#fff;
     display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;font-family:"Segoe UI",system-ui,sans-serif;
     transition:opacity .8s}
   #__tit img{width:150px;height:150px;border:0}
   #__tit h1{font-size:64px;margin:6px 0 0;letter-spacing:.5px}
   #__tit p{font-size:26px;margin:0;color:#c5d7ee}
   #__tit small{font-size:18px;color:#9fb8da;margin-top:26px}`;
  const add = () => {
    if (document.getElementById("__cur") || !document.body) return;
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    const c = document.createElement("div"); c.id = "__cur";
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M2 1 L2 17 L6.5 13 L9.5 20 L12.5 18.7 L9.6 12 L15.5 12 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    const r = document.createElement("div"); r.id = "__rip"; document.body.appendChild(r);
    if (window === window.top){ const k = document.createElement("div"); k.id = "__cap"; document.body.appendChild(k); }
    const mover = e => { c.style.display = "block"; c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; c.style.opacity = 1; };
    document.addEventListener("mousemove", mover, true);
    document.addEventListener("pointermove", mover, true);
    document.addEventListener("mouseout", e => { if (!e.relatedTarget) c.style.opacity = 0; }, true);
    document.addEventListener("mousedown", e => { r.style.left = e.clientX + "px"; r.style.top = e.clientY + "px";
      r.animate([{opacity:.95, transform:"scale(.4)"}, {opacity:0, transform:"scale(1.4)"}], {duration:450}); }, true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
  window.__cap = t => { add(); const k = document.getElementById("__cap"); if (!k) return; if (!t){ k.style.opacity = 0; return; } k.textContent = t; k.style.opacity = 1; };
  window.__titulo = (h, p, s) => { add(); let d = document.getElementById("__tit");
    if (!d){ d = document.createElement("div"); d.id = "__tit"; document.body.appendChild(d); }
    d.innerHTML = `<img src="/logo.svg"><h1>${h}</h1><p>${p}</p><small>${s || ""}</small>`; d.style.opacity = 1; };
  window.__semTitulo = () => { const d = document.getElementById("__tit"); if (d){ d.style.opacity = 0; setTimeout(() => d.remove(), 900); } };
  window.__overlays = v => { for (const id of ["__cur", "__cap", "__rip"]){ const e = document.getElementById(id); if (e) e.style.visibility = v ? "visible" : "hidden"; } };
})();
"""


# ----------------------------------------------------------------------------- demo environment
def preparar_demo():
    if DEMO.exists():
        shutil.rmtree(DEMO)
    (DEMO / "Documents").mkdir(parents=True)
    (DEMO / "AppData").mkdir()
    env = {**os.environ, "USERPROFILE": str(DEMO), "HOME": str(DEMO), "APPDATA": str(DEMO / "AppData"),
           "MOBYDIC_LANG": ""}
    py = str(RAIZ / ".venv" / "Scripts" / "python.exe")
    # example images generated beforehand so the video does not wait for them
    exemplos = DEMO / "Documents" / "Moby-DIC" / "examples"
    subprocess.run([py, "-m", "mobydic", "example", "necking", "--output", str(exemplos)], cwd=RAIZ, env=env, check=True)
    # compile the numba kernel beforehand (cached), so the recorded run starts immediately
    aquec = TMP / "aquecimento"
    subprocess.run([py, "-m", "mobydic", "subsets", "--images", str(exemplos / "necking"), "--output", str(aquec),
                    "--limit", "2"], cwd=RAIZ, env=env, check=True, stdout=subprocess.DEVNULL)
    srv = subprocess.Popen([py, "-m", "mobydic", "gui", "--port", str(PORTA), "--no-browser"], cwd=RAIZ, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", PORTA)) == 0:
                return srv
        time.sleep(0.2)
    raise RuntimeError("server did not start")


# ----------------------------------------------------------------------------- recording
class Gravador:
    def __init__(self, page, cdp, dur, video):
        self.page, self.cdp, self.dur, self.video = page, cdp, dur, video
        self.frames, self.marcas, self.n = [], [], 0
        (TMP / "frames").mkdir(parents=True, exist_ok=True)

    async def iniciar(self):
        if not self.video:
            return
        self.cdp.on("Page.screencastFrame", lambda e: asyncio.ensure_future(self._frame(e)))
        await self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90,
                                                     "maxWidth": int(VW * ESC), "maxHeight": int(VH * ESC)})

    async def _frame(self, e):
        caminho = TMP / "frames" / f"{self.n:06d}.jpg"
        self.n += 1
        import base64
        caminho.write_bytes(base64.b64decode(e["data"]))
        self.frames.append((e["metadata"]["timestamp"], caminho))
        try:
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": e["sessionId"]})
        except Exception:  # noqa: BLE001
            pass

    async def parar(self):
        if self.video:
            await self.cdp.send("Page.stopScreencast")

    async def segmento(self, chave, acao=None, folga=0.5):
        t0 = time.time()
        self.marcas.append((chave, t0))
        await self.page.evaluate("t => window.__cap(t)", TEXTO[chave])
        if acao:
            await acao()
        resto = self.dur[chave] + folga - (time.time() - t0)
        if resto > 0:
            await self.page.wait_for_timeout(resto * 1000)

    async def foto(self, nome, clip=None):
        await self.page.evaluate("window.__overlays(false)")
        await self.page.screenshot(path=str(IMG / nome), clip=clip)
        await self.page.evaluate("window.__overlays(true)")


async def ir_ate(page, loc, passos=22):
    caixa = await loc.bounding_box()
    x, y = caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2
    await page.mouse.move(x, y, steps=passos)
    await page.wait_for_timeout(180)
    return x, y


async def clicar(page, loc, espera=350):
    await loc.scroll_into_view_if_needed()
    x, y = await ir_ate(page, loc)
    await page.mouse.click(x, y)
    await page.wait_for_timeout(espera)


async def roteiro(page, g):
    url = f"http://127.0.0.1:{PORTA}/"
    # title card on the server origin (so /logo.svg resolves), before the app opens its dialog
    await page.goto(url + "docs/index.html")
    await page.set_content("<!doctype html><html><head><title>Moby-DIC</title></head><body style='margin:0'></body></html>")
    await page.evaluate(OVERLAY_JS)
    await page.evaluate("window.__titulo('Moby-DIC', 'Getting started: your first analysis', 'Digital image correlation for mechanical testing · version 1.0')")
    await page.mouse.move(VW * 0.62, VH * 0.7)
    await g.iniciar()
    await page.wait_for_timeout(800)

    async def abrir_app():
        await page.wait_for_timeout(max(0, (g.dur["intro"] - 1.2) * 1000))
        await page.evaluate("window.__semTitulo()")
        await page.wait_for_timeout(700)
    await g.segmento("intro", abrir_app, folga=0.1)
    await page.goto(url)
    await page.wait_for_selector("#dlgIdioma[open]")
    await page.wait_for_timeout(500)
    await g.foto("welcome.png")

    async def idioma():
        await page.wait_for_timeout(1500)
        await ir_ate(page, page.locator('#dlgIdioma [data-l="pt"]'))
        await page.wait_for_timeout(700)
        await clicar(page, page.locator('#dlgIdioma [data-l="en"]'))
    await g.segmento("idioma", idioma)

    async def inicio():
        await page.wait_for_timeout(2500)
        for a in ("imagens", "docs"):
            await ir_ate(page, page.locator(f'#dlgIdioma [data-a="{a}"]'))
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(1200)
        await clicar(page, page.locator('#dlgIdioma [data-a="exemplo"]'))
        await page.wait_for_selector("#tudoAuto", timeout=120000)
    await g.segmento("inicio", inicio)
    await page.wait_for_timeout(600)
    await g.foto("app-overview.png")
    await g.foto("tutorial1-images.png")

    async def imagens():
        await ir_ate(page, page.locator("#fluxo .no").nth(0))
        await page.wait_for_timeout(600)
        await ir_ate(page, page.locator("#fluxo .no").nth(7))
        await page.wait_for_timeout(600)
        await ir_ate(page, page.locator("#cardInfo .kv"))
        await page.wait_for_timeout(1500)
        await ir_ate(page, page.locator("#cardInfo .thumbs"))
        await page.wait_for_timeout(1800)
        await ir_ate(page, page.locator("#cardInfo svg.spark"))
        await page.wait_for_timeout(1500)
        await ir_ate(page, page.locator("#cardInfo .okbox"))
    await g.segmento("imagens", imagens)
    await clicar(page, page.locator(".etapa .nav .prox").last)

    async def escala():
        await page.wait_for_timeout(2800)
        await clicar(page, page.locator('.metodo[data-m="manual"]'))
        campo = page.locator("#cEsc input[type=number]")
        await clicar(page, campo)
        await campo.fill("")
        await page.keyboard.type("2", delay=120)
        await campo.dispatch_event("change")
        await page.wait_for_timeout(600)
    await g.segmento("escala", escala)
    await clicar(page, page.locator(".etapa .nav .prox").last)

    async def roi():
        await page.wait_for_timeout(1200)
        cv = page.locator("#ed")
        await cv.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        caixa = await cv.bounding_box()
        # trace the specimen edge and the ROI with the cursor
        y = caixa["y"] + caixa["height"] * 0.5
        await page.mouse.move(caixa["x"] + caixa["width"] * 0.2, caixa["y"] + caixa["height"] * 0.19, steps=25)
        await page.mouse.move(caixa["x"] + caixa["width"] * 0.8, caixa["y"] + caixa["height"] * 0.19, steps=40)
        await page.mouse.move(caixa["x"] + caixa["width"] * 0.5, y, steps=25)
    await g.segmento("roi", roi)
    await g.foto("tutorial1-roi.png")

    async def roi2():
        cv = page.locator("#ed")
        caixa = await cv.bounding_box()
        x1, y1, x2, y2 = await page.evaluate("() => S.roi.img")
        largura = await page.evaluate("() => S.info.largura")
        esc = caixa["width"] / largura
        ym = caixa["y"] + (y1 + y2) / 2 * esc
        xr = caixa["x"] + x2 * esc
        await page.mouse.move(xr, ym, steps=25)
        await page.wait_for_timeout(300)
        await page.mouse.down()
        await page.mouse.move(xr - 0.12 * caixa["width"], ym, steps=30)
        await page.mouse.up()
        await page.wait_for_timeout(900)
        sel = page.locator("#roiQuadro")
        await ir_ate(page, sel)
        await sel.select_option(index=1)
        await page.wait_for_timeout(2200)
        await clicar(page, page.locator("#roiBotoes button").first)
        await page.wait_for_timeout(1000)
    await g.segmento("roi2", roi2)
    await clicar(page, page.locator(".etapa .nav .prox").last)

    async def metodo():
        await page.wait_for_timeout(1500)
        await ir_ate(page, page.locator('.metodo[data-t="subsets"]'))
        await page.wait_for_timeout(1800)
        await ir_ate(page, page.locator("#cPar .campo").nth(0))
        await page.wait_for_timeout(1800)
        await ir_ate(page, page.locator("#cPar .campo").nth(1))
        await page.wait_for_timeout(1500)
        await page.locator("#notaGrade").scroll_into_view_if_needed()
        await ir_ate(page, page.locator("#notaGrade"))
    await g.segmento("metodo", metodo)
    await g.foto("tutorial1-method.png")
    await clicar(page, page.locator(".etapa .nav .prox").last)

    async def referencia():
        await page.wait_for_timeout(1200)
        await ir_ate(page, page.locator('.metodo[data-m="automatica"]'))
        await page.wait_for_timeout(3000)
        await ir_ate(page, page.locator("#cRef .campo").nth(1))
    await g.segmento("referencia", referencia)
    await clicar(page, page.locator(".etapa .nav .prox").last)

    async def saida():
        await page.wait_for_timeout(800)
        await ir_ate(page, page.locator("#cPos .campo").nth(0))
        await page.wait_for_timeout(1500)
        await ir_ate(page, page.locator("#cPos .campo").nth(1))
    await g.segmento("saida", saida)
    await clicar(page, page.locator(".etapa .nav .prox").last)

    async def executar():
        await page.wait_for_timeout(1500)
        await ir_ate(page, page.locator("table.resumo tr").nth(3))
        await page.wait_for_timeout(1500)
        await ir_ate(page, page.locator("table.resumo tr").nth(4))
        await page.wait_for_timeout(800)
        await clicar(page, page.locator("#rodar"))
    await g.segmento("executar", executar)

    async def rodando():
        await page.wait_for_timeout(1500)
        await page.locator("#log").scroll_into_view_if_needed()
        await ir_ate(page, page.locator("#log"))
        await page.wait_for_selector("#abrirVis:not([hidden])", timeout=600000)
    await g.segmento("rodando", rodando)
    await g.foto("tutorial1-run.png")

    async def pronto():
        await page.wait_for_timeout(1200)
        await clicar(page, page.locator("#abrirVis"))
    await g.segmento("pronto", pronto)

    vis = page.frame_locator("#vis")
    await vis.locator("#grade canvas").first.wait_for(timeout=60000)
    await page.wait_for_timeout(1500)

    async def visualizador():
        await page.locator("#vis").scroll_into_view_if_needed()
        await page.wait_for_timeout(800)
        await vis.locator("#fps").select_option("5")
        await clicar(page, vis.locator("#play"))
        await page.wait_for_timeout(5600)
        await clicar(page, vis.locator("#play"))
        await clicar(page, vis.locator("#ant"))
        await clicar(page, vis.locator("#prox"))
    await g.segmento("visualizador", visualizador)
    n = await vis.locator("#quadro").evaluate("e => +e.max")
    await vis.locator("#quadro").evaluate("(e, n) => { e.value = n; e.dispatchEvent(new Event('input')); }", n)
    await page.wait_for_timeout(500)
    await g.foto("viewer.png")

    async def exx():
        await ir_ate(page, vis.locator("#layout"))
        await vis.locator("#layout").select_option("1")
        await page.wait_for_timeout(900)
        campo = vis.locator("section.painel select.campo").first
        await ir_ate(page, campo)
        await campo.select_option("3")
        await page.wait_for_timeout(900)
    await g.segmento("exx", exx)

    async def leitura():
        cv = vis.locator("section.painel canvas.mapa").first
        caixa = await cv.bounding_box()
        y = caixa["y"] + caixa["height"] * 0.5
        dica = vis.locator("#dica")
        await page.mouse.move(caixa["x"] + caixa["width"] * 0.22, y, steps=20)
        melhor, xm = -1e9, None
        for k in range(70):                       # sweep across the neck, reading the tooltip
            x = caixa["x"] + caixa["width"] * (0.22 + 0.5 * k / 69)
            await page.mouse.move(x, y)
            await page.wait_for_timeout(45)
            txt = await dica.text_content()
            try:
                v = float(txt.split("=")[1].split()[0].replace(",", "."))
            except (IndexError, ValueError, AttributeError):
                continue
            if v > melhor:
                melhor, xm = v, x
        await page.mouse.move(xm, y, steps=45)
        await page.wait_for_timeout(1800)
    await g.segmento("leitura", leitura)
    await g.foto("tutorial1-viewer.png")

    async def incremento():
        campo = vis.locator("section.painel select.campo").first
        await ir_ate(page, campo)
        await campo.select_option("14")
        await page.wait_for_timeout(800)
        await clicar(page, vis.locator("#play"))
        await page.wait_for_timeout(5400)
        await clicar(page, vis.locator("#play"))
    await g.segmento("incremento", incremento)

    async def escalas():
        await vis.locator("#quadro").evaluate("(e, n) => { e.value = n; e.dispatchEvent(new Event('input')); }", n)
        campo = vis.locator("section.painel select.campo").first
        await campo.select_option("3")
        await page.wait_for_timeout(600)
        await clicar(page, vis.locator("section.painel button.quadroAuto").first)
        await page.wait_for_timeout(900)
        lim = vis.locator("section.painel input.lim").first
        caixa = await lim.bounding_box()
        y = caixa["y"] + caixa["height"] / 2
        await page.mouse.move(caixa["x"] + caixa["width"] * 0.5, y, steps=20)
        await page.mouse.down()
        await page.mouse.move(caixa["x"] + caixa["width"] * 0.3, y, steps=25)
        await page.mouse.up()
        await page.wait_for_timeout(700)
        await ir_ate(page, vis.locator("#cmap"))
        for c in ("viridis", "turbo", "jet"):
            await vis.locator("#cmap").select_option(c)
            await page.wait_for_timeout(900)
        await clicar(page, vis.locator("section.painel button.auto").first)
    await g.segmento("escalas", escalas)

    async def exportar():
        sumario = vis.locator("#painelExportar summary")
        await clicar(page, sumario)
        await vis.locator("#btnVideo").scroll_into_view_if_needed()
        await page.wait_for_timeout(600)
        for b in ("#btnFigura", "#btnZip", "#btnVideo"):
            await ir_ate(page, vis.locator(b))
            await page.wait_for_timeout(1300)
    await g.segmento("exportar", exportar)

    async def docs():
        await page.evaluate("window.scrollTo({top:0, behavior:'smooth'})")
        await page.wait_for_timeout(700)
        await ir_ate(page, page.locator("#ajuda"))
        await page.wait_for_timeout(400)
        await page.mouse.down()
        await page.mouse.up()
        await page.goto(url + "docs/")
        await page.wait_for_timeout(2500)
        await page.mouse.move(VW * 0.1, VH * 0.45, steps=20)
        await page.locator('nav a[href$="theory.html"]').click()
        await page.wait_for_timeout(2500)
        await page.mouse.wheel(0, 1400)
        await page.wait_for_timeout(2500)
    await g.segmento("docs", docs)
    await page.evaluate("window.__titulo('Moby-DIC', 'Free and open source · MIT License', 'Documentation included · English and Português')")
    await page.wait_for_timeout(4500)


async def principal(video):
    from playwright.async_api import async_playwright
    IMG.mkdir(parents=True, exist_ok=True)
    dur = sintetizar()
    print("narration:", round(sum(dur.values()), 1), "s")
    srv = preparar_demo()
    try:
        async with async_playwright() as p:
            nav = await p.chromium.launch(channel="msedge", headless=True)
            ctx = await nav.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=ESC,
                                        color_scheme="light", locale="en-US")
            await ctx.add_init_script(OVERLAY_JS)
            page = await ctx.new_page()
            cdp = await ctx.new_cdp_session(page)
            g = Gravador(page, cdp, dur, video)
            await roteiro(page, g)
            await g.parar()
            await page.wait_for_timeout(500)
            await nav.close()
    finally:
        srv.terminate()
    if video:
        montar(g, dur)


def montar(g, dur):
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    frames = sorted(g.frames)
    t0 = frames[0][0]
    fim = frames[-1][0] + 1.0
    # concat list with per-frame durations
    linhas = []
    for (t, c), (t2, _) in zip(frames, frames[1:] + [(fim, None)]):
        linhas += [f"file '{c.as_posix()}'", f"duration {max(t2 - t, 0.001):.4f}"]
    linhas.append(f"file '{frames[-1][1].as_posix()}'")
    (TMP / "frames.txt").write_text("\n".join(linhas), encoding="utf-8")
    # narration track
    total = int((fim - t0 + 1) * TAXA)
    audio = np.zeros(total, dtype=np.float32)
    srt, k = [], 1
    for chave, tm in g.marcas:
        with wave.open(str(TMP / "voz" / f"{chave}.wav")) as w:
            a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
        i = max(0, int((tm - t0 + 0.15) * TAXA))
        a = a[: max(0, total - i)]
        audio[i:i + len(a)] += a
        ini, fim_s = tm - t0 + 0.15, tm - t0 + 0.15 + dur[chave]

        def ts(s):
            h, r = divmod(s, 3600)
            m, s2 = divmod(r, 60)
            return f"{int(h):02d}:{int(m):02d}:{int(s2):02d},{int((s2 % 1) * 1000):03d}"
        srt += [str(k), f"{ts(ini)} --> {ts(fim_s)}", TEXTO[chave], ""]
        k += 1
    audio = np.clip(audio * 0.95, -32768, 32767).astype(np.int16)
    with wave.open(str(TMP / "narracao.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA)
        w.writeframes(audio.tobytes())
    destino = SAIDA / "Moby-DIC-tutorial.mp4"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(TMP / "frames.txt"), "-i", str(TMP / "narracao.wav"),
                    "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-tune", "stillimage",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                    "-metadata", "title=Moby-DIC tutorial: your first analysis", str(destino)], check=True)
    (SAIDA / "Moby-DIC-tutorial.srt").write_text("\n".join(srt), encoding="utf-8")
    print(destino, round(destino.stat().st_size / 1e6, 1), "MB,", round(fim - t0, 1), "s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-video", action="store_true", help="only take the documentation screenshots")
    a = ap.parse_args()
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    asyncio.run(principal(not a.no_video))
    sys.exit(0)
