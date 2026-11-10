"""Builds the HTML documentation (docs/html) from the Markdown sources in docs/.

    python docs/build_docs.py

Display equations ($$ ... $$) are pre-rendered to inline SVG with Matplotlib's mathtext, so the
pages work offline (they are bundled in the executable and served under /docs/ by the app).
Requires: markdown (pip install markdown).
"""

import html
import io
import re
import shutil
from pathlib import Path

import markdown

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / "html"
LOGO = RAIZ.parent / "mobydic" / "assets" / "logo.svg"

# (file, title) in reading order; sections start with a "#" entry
PAGINAS = [
    ("#", "Getting started"),
    ("index.md", "Overview"),
    ("installation.md", "Installation"),
    ("tutorials/01-first-analysis.md", "Tutorial 1 · First analysis"),
    ("#", "Using Moby-DIC"),
    ("user-guide.md", "User guide"),
    ("viewer.md", "Interactive viewer"),
    ("output-files.md", "Output files"),
    ("command-line.md", "Command line and Python"),
    ("#", "Tutorials"),
    ("tutorials/02-layered-specimen.md", "Tutorial 2 · Layered specimen"),
    ("tutorials/03-difficult-sequences.md", "Tutorial 3 · Difficult sequences"),
    ("tutorials/04-python-post-processing.md", "Tutorial 4 · Post-processing in Python"),
    ("#", "Background"),
    ("theory.md", "Theory"),
    ("good-practice.md", "Good experimental practice"),
    ("troubleshooting.md", "Troubleshooting and FAQ"),
    ("changelog.md", "Changelog"),
]

CSS = """
:root{--bg:#ffffff;--side:#f4f6f9;--ink:#1d2330;--muted:#5d6678;--line:#d9dde5;--accent:#1d5aa0;--code:#f3f5f8;--marca:#14427a;--note:#eaf1fa}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#13171d;--side:#1a1f27;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2c333e;--accent:#6aa3f5;--code:#1e242d;--marca:#0e2f57;--note:#1c2634}
  :root:not([data-theme="light"]) .eq svg{filter:invert(1) hue-rotate(180deg)}}
:root[data-theme="dark"]{--bg:#13171d;--side:#1a1f27;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2c333e;--accent:#6aa3f5;--code:#1e242d;--marca:#0e2f57;--note:#1c2634}
:root[data-theme="dark"] .eq svg{filter:invert(1) hue-rotate(180deg)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.62 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{display:flex;align-items:center;gap:12px;padding:10px 20px;background:var(--marca);color:#fff;position:sticky;top:0;z-index:2}
header img{width:34px;height:34px}header b{font-size:18px}header span{color:#c5d7ee;font-size:13px}
header a{color:#fff;text-decoration:none}
#menu{display:none;margin-left:auto;background:transparent;border:1px solid rgba(255,255,255,.4);color:#fff;border-radius:6px;padding:4px 10px;font-size:15px}
.wrap{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:calc(100vh - 54px)}
nav{background:var(--side);border-right:1px solid var(--line);padding:16px 12px;position:sticky;top:54px;align-self:start;height:calc(100vh - 54px);overflow:auto;font-size:14.5px}
nav .sec{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:16px 8px 4px}
nav .sec:first-child{margin-top:0}
nav a{display:block;padding:4px 8px;border-radius:6px;color:var(--ink);text-decoration:none}
nav a:hover{background:var(--note)}nav a.atual{background:var(--note);color:var(--accent);font-weight:600}
main{padding:24px 40px 80px;max-width:940px;min-width:0}
h1{font-size:30px;line-height:1.25;margin:4px 0 14px}h2{font-size:22px;margin:34px 0 10px;padding-top:6px;border-top:1px solid var(--line)}
h3{font-size:18px;margin:24px 0 8px}
a{color:var(--accent)}
code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:.9em}
pre{background:var(--code);padding:12px 14px;border-radius:8px;overflow:auto;font-size:13.5px;line-height:1.5}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14.5px;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
th{background:var(--side)}
img{max-width:100%;border:1px solid var(--line);border-radius:8px}
blockquote{margin:14px 0;padding:8px 14px;background:var(--note);border-left:4px solid var(--accent);border-radius:6px}
blockquote p{margin:4px 0}
.eq{overflow-x:auto;text-align:center;margin:14px 0}.eq svg{max-width:100%;height:auto}
.pagnav{display:flex;justify-content:space-between;gap:12px;margin-top:48px;padding-top:14px;border-top:1px solid var(--line);font-size:14.5px}
@media (max-width:820px){.wrap{grid-template-columns:1fr}nav{display:none;position:static;height:auto}nav.aberto{display:block}#menu{display:block}main{padding:18px 16px 60px}}
"""


def svg_equacao(tex):
    """Renders a display equation to an inline SVG string (Matplotlib mathtext)."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    matplotlib.rcParams.update({"mathtext.fontset": "cm", "svg.fonttype": "path"})
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f"${tex}$", fontsize=15)
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", pad_inches=0.04, transparent=True)
    plt.close(fig)
    s = buf.getvalue()
    s = s[s.index("<svg"):]
    return re.sub(r"<metadata>.*?</metadata>", "", s, flags=re.S)


def converter(md_texto):
    eqs = []

    def guardar(m):
        eqs.append(m.group(1).strip())
        return f"\n\nEQUACAO{len(eqs) - 1}FIM\n\n"
    md_texto = re.sub(r"\$\$(.+?)\$\$", guardar, md_texto, flags=re.S)
    corpo = markdown.markdown(md_texto, extensions=["tables", "fenced_code", "toc", "attr_list", "sane_lists"])
    for k, tex in enumerate(eqs):
        alvo = f"<p>EQUACAO{k}FIM</p>"
        corpo = corpo.replace(alvo, f'<div class="eq" title="{html.escape(tex)}">{svg_equacao(tex)}</div>')
    # links between .md pages -> .html
    corpo = re.sub(r'href="([^":#]+)\.md(#[^"]*)?"', lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', corpo)
    return corpo


def main():
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    SAIDA.mkdir(parents=True)
    shutil.copy(LOGO, SAIDA / "logo.svg")
    if (RAIZ / "img").is_dir():
        shutil.copytree(RAIZ / "img", SAIDA / "img")
    paginas = [(f, t) for f, t in PAGINAS if f != "#"]
    for k, (arq, titulo) in enumerate(paginas):
        profundidade = arq.count("/")
        rel = "../" * profundidade
        corpo = converter((RAIZ / arq).read_text(encoding="utf-8"))
        corpo = corpo.replace('src="img/', f'src="{rel}img/').replace('src="../img/', f'src="{rel}img/')
        itens = []
        for f, t in PAGINAS:
            if f == "#":
                itens.append(f'<div class="sec">{t}</div>')
            else:
                href = rel + f.replace(".md", ".html")
                itens.append(f'<a href="{href}"{" class=atual" if f == arq else ""}>{t}</a>')
        ant = paginas[k - 1] if k > 0 else None
        prox = paginas[k + 1] if k + 1 < len(paginas) else None
        pagnav = '<div class="pagnav">' + (
            f'<a href="{rel}{ant[0].replace(".md", ".html")}">← {ant[1]}</a>' if ant else "<span></span>") + (
            f'<a href="{rel}{prox[0].replace(".md", ".html")}">{prox[1]} →</a>' if prox else "<span></span>") + "</div>"
        pagina = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo} · Moby-DIC documentation</title><link rel="icon" href="{rel}logo.svg"><style>{CSS}</style></head>
<body><header><a href="{rel}index.html"><img src="{rel}logo.svg" alt=""></a><div><b>Moby-DIC</b> <span>documentation</span></div>
<button id="menu" onclick="document.querySelector('nav').classList.toggle('aberto')">☰</button></header>
<div class="wrap"><nav>{''.join(itens)}</nav><main>{corpo}{pagnav}</main></div></body></html>"""
        destino = SAIDA / arq.replace(".md", ".html")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(pagina, encoding="utf-8")
    print(f"{len(paginas)} pages -> {SAIDA}")


if __name__ == "__main__":
    main()
