"""Gera o logo do Moby-DIC (SVG para a interface, ICO/PNG para o executável).

Uma cachalote branca (Moby Dick) sobre azul-oceano, com o corpo coberto por um padrão de
speckle, como uma amostra preparada para DIC.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent.parent  # raiz do repositório
ASSETS = RAIZ / "mobydic" / "assets"

# Contorno da baleia em coordenadas 0–64 (curvas Bézier cúbicas).
CAMINHO = [
    ("M", (8, 31)),
    ("C", (8, 22), (17, 19.5), (28, 19.5)),
    ("L", (40, 20.5)),
    ("C", (46.5, 21.5), (50.5, 25.5), (52, 29.5)),
    ("L", (55.5, 25.5)),
    ("C", (56.8, 23.8), (60, 24), (60, 26.5)),
    ("L", (58, 33)),
    ("L", (60, 39.5)),
    ("C", (60, 42), (56.8, 42.2), (55.5, 40.5)),
    ("L", (52, 36.5)),
    ("C", (49, 41.5), (42, 44.5), (33.5, 44.5)),
    ("L", (19, 44.5)),
    ("C", (12.5, 44.5), (8, 40.5), (8, 35)),
    ("Z",),
]
SPECKLE = [(14, 27, 1.3), (20, 24, 1.1), (25, 29, 1.5), (31, 24, 1.0), (35, 30, 1.4), (41, 26, 1.1),
           (45, 32, 1.2), (28, 36, 1.3), (22, 39, 1.0), (37, 39, 1.2), (43, 38, 0.9), (49, 33, 0.9),
           (33, 33, 0.8), (17, 35, 0.9), (26, 41.5, 0.8), (39, 34.5, 0.8)]
OLHO = (14.5, 33.5, 1.4)
FUNDO, BALEIA, PONTO = "#14427a", "#f4f7fb", "#14427a"


def svg():
    d = []
    for seg in CAMINHO:
        if seg[0] == "Z":
            d.append("Z")
        else:
            d.append(seg[0] + " " + " ".join(f"{x:g} {y:g}" for x, y in seg[1:]))
    pontos = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{PONTO}"/>' for x, y, r in SPECKLE)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<rect width="64" height="64" rx="14" fill="{FUNDO}"/>'
            f'<path d="M4 50 Q16 46 28 50 T52 50 T64 50 V64 H0 V50 Z" fill="#1d5aa0" opacity=".7"/>'
            f'<path d="{" ".join(d)}" fill="{BALEIA}"/>{pontos}'
            f'<circle cx="{OLHO[0]}" cy="{OLHO[1]}" r="{OLHO[2]}" fill="#0b2a50"/>'
            f'<path d="M30 19.5 C29 15 27 13 25 12 M30 19.5 C31 15 33 13 35 12" stroke="#9fc4ee" stroke-width="1.6" fill="none" stroke-linecap="round"/>'
            f'</svg>')


def poligono(escala):
    pts, atual = [], None
    for seg in CAMINHO:
        if seg[0] == "M":
            atual = seg[1]
            pts.append(atual)
        elif seg[0] == "L":
            atual = seg[1]
            pts.append(atual)
        elif seg[0] == "C":
            p0, (p1, p2, p3) = np.array(atual), map(np.array, seg[1:])
            for t in np.linspace(0, 1, 24)[1:]:
                b = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
                pts.append(tuple(b))
            atual = seg[3]
    return [(x * escala, y * escala) for x, y in pts]


def png(tam=512):
    s = tam / 64
    im = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, tam - 1, tam - 1], radius=14 * s, fill=FUNDO)
    onda = [(x * s, (50 + 2 * np.sin((x - 4) / 24 * 2 * np.pi)) * s) for x in np.linspace(0, 64, 60)]
    dr.polygon(onda + [(64 * s, 64 * s), (0, 64 * s)], fill="#1d5aa0")
    dr.rounded_rectangle([0, 0, tam - 1, tam - 1], radius=14 * s, outline=FUNDO, width=int(2 * s))
    dr.polygon(poligono(s), fill=BALEIA)
    for x, y, r in SPECKLE:
        dr.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], fill=PONTO)
    x, y, r = OLHO
    dr.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], fill="#0b2a50")
    for sinal in (-1, 1):
        dr.line([(30 * s, 19.5 * s), ((30 + sinal * 2.5) * s, 15 * s), ((30 + sinal * 5) * s, 12 * s)],
                fill="#9fc4ee", width=int(1.6 * s), joint="curve")
    # recorta os cantos arredondados
    mask = Image.new("L", (tam, tam), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tam - 1, tam - 1], radius=14 * s, fill=255)
    im.putalpha(mask)
    return im


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "logo.svg").write_text(svg(), encoding="utf-8")
    grande = png(512)
    grande.save(ASSETS / "logo.png")
    grande.save(ASSETS / "moby-dic.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok:", ", ".join(p.name for p in ASSETS.iterdir()))
