"""Moby-DIC · exportação e mapas comuns às análises (subsets, Q4 e B-spline).

Todos os campos chegam numa grade estruturada ``[quadro, linha, coluna, ...]`` em pixels,
no sistema com origem no canto inferior esquerdo da imagem (x para a direita, y para cima).
"""

import csv

import matplotlib
import numpy as np

from .i18n import t as tx

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.tri import Triangulation


ESTADOS_EN = {"referencia": "reference", "convergiu": "converged", "quadro_ruim": "bad frame",
              "nao_convergiu": "not converged", "erro": "error", "sem_registro": "no record"}


def deformacao_verdadeira(grad):
    """Deformação logarítmica das fibras x e y e distorção xy a partir de F [..., 2, 2]."""
    c = np.swapaxes(grad, -1, -2) @ grad  # C = F^T F
    exx = 0.5 * np.log(c[..., 0, 0])
    eyy = 0.5 * np.log(c[..., 1, 1])
    exy = 0.5 * np.arcsin(c[..., 0, 1] / np.sqrt(c[..., 0, 0] * c[..., 1, 1]))
    return exx, eyy, exy


def escrever_csv_pontos(saida, arquivos, coords_px, campos, valido, escala, selecionados, sufixo="um",
                        max_linhas=2_000_000):
    """Tabela longa por ponto. Com muitos pontos, grava só os quadros dos mapas."""
    n, ny, nx = valido.shape
    quadros = range(n) if n * ny * nx <= max_linhas else selecionados
    x0, y0 = coords_px[0, ..., 0] * escala, coords_px[0, ..., 1] * escala
    ux, uy, exx, eyy = campos
    with (saida / "campos_por_ponto.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["indice", "arquivo", "linha", "coluna", f"x0_{sufixo}", f"y0_{sufixo}",
                    f"ux_{sufixo}", f"uy_{sufixo}", "exx_pct", "eyy_pct"])
        for i in quadros:
            arq = arquivos[i]
            for r, c in zip(*np.nonzero(valido[i])):
                w.writerow([i, arq.name if hasattr(arq, "name") else arq, r, c,
                            f"{x0[r, c]:.2f}", f"{y0[r, c]:.2f}",
                            f"{ux[i, r, c]:.4f}", f"{uy[i, r, c]:.4f}",
                            f"{exx[i, r, c]:.4f}", f"{eyy[i, r, c]:.4f}"])
    return list(quadros)


def exportar(saida, imagem, arquivos, estados, escala, coords_px, disp_px, grad, calibrado=True,
             valido=None, poligonos_ref=None, pontos_ref=None, titulo_malha="malha"):
    """Grava NPZ, CSVs e figuras.

    imagem(i) -> array 2D já na orientação com origem inferior.
    coords_px, disp_px: [T, ny, nx, 2]; grad: [T, ny, nx, 2, 2]; valido: [T, ny, nx] bool.
    poligonos_ref: [n, 4, 2] px (contorno de elementos no quadro 0) ou pontos_ref: [n, 2] px.
    """
    n = len(arquivos)
    if valido is None:
        valido = np.ones(coords_px.shape[:3], dtype=bool)
    exx, eyy, exy = deformacao_verdadeira(grad)
    valido = valido & np.isfinite(exx) & np.isfinite(eyy) & np.isfinite(disp_px).all(-1)
    with np.errstate(invalid="ignore"):
        det_f = np.linalg.det(grad)

    disp_um = disp_px * escala
    u_d = "µm" if calibrado else "px"            # unidade dos deslocamentos
    u_c = "mm" if calibrado else "px"            # unidade dos eixos
    sufixo = "um" if calibrado else "px"
    rot = np.arctan2(grad[..., 1, 0] - grad[..., 0, 1], grad[..., 0, 0] + grad[..., 1, 1])
    f32 = np.float32
    np.savez_compressed(
        saida / "campos.npz",
        centro_xy_px=coords_px.astype(f32),
        deslocamento_xy_px=disp_px.astype(f32), deslocamento_xy_um=disp_um.astype(f32),
        deformacao_xx=exx.astype(f32), deformacao_yy=eyy.astype(f32), deformacao_xy=exy.astype(f32),
        rotacao=rot.astype(f32), valido=valido, calibrado=calibrado,
        arquivos=[p.name for p in arquivos], estado=list(estados), escala_um_px=escala,
    )

    ux, uy = disp_um[..., 0], disp_um[..., 1]
    campos = [ux, uy, exx * 100, eyy * 100]
    nomes = [f"ux_{sufixo}", f"uy_{sufixo}", "exx_pct", "eyy_pct"]

    def q(a, i):
        return a[i][valido[i]]

    with (saida / "resumo_por_quadro.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["indice", "arquivo", "estado", "pontos_validos"]
                   + [f"{nm}_{s}" for nm in nomes for s in ("media", "p05", "p95")] + ["det_F_min"])
        for i, arq in enumerate(arquivos):
            vals = []
            for a in campos:
                v = q(a, i)
                vals += [v.mean(), *np.percentile(v, [5, 95])] if v.size else [np.nan] * 3
            dv = q(det_f, i)
            w.writerow([i, arq.name, estados[i], int(valido[i].sum()), *(f"{v:.6g}" for v in vals),
                        f"{dv.min():.6f}" if dv.size else "nan"])

    selecionados = sorted({n // 2, n - 1, *(i for i in (24, 80) if i < n)})
    escrever_csv_pontos(saida, arquivos, coords_px, campos, valido, escala, selecionados, sufixo)

    altura, largura = imagem(0).shape
    mm = escala / 1000 if calibrado else 1.0
    extent = (-0.5 * mm, (largura - 0.5) * mm, -0.5 * mm, (altura - 0.5) * mm)

    def fundo(ax, i):
        ax.imshow(imagem(i), cmap="gray", origin="lower", extent=extent)
        ax.set(xlabel=f"x ({u_c})", ylabel=f"y ({u_c})", aspect="equal")

    fig, ax = plt.subplots(figsize=(9, 6.5), layout="constrained")
    fundo(ax, 0)
    if poligonos_ref is not None:
        ax.add_collection(PolyCollection(poligonos_ref * mm, facecolors="none",
                                         edgecolors="#48defa", linewidths=0.5))
    if pontos_ref is not None:
        ax.plot(pontos_ref[:, 0] * mm, pontos_ref[:, 1] * mm, ".", color="#48defa", ms=2)
    ax.set_title(f"{titulo_malha} · {arquivos[0].name}" + (f" · {escala} µm/px" if calibrado else ""))
    fig.savefig(saida / "malha_referencia.png", dpi=150)
    plt.close(fig)

    # Triangulação estruturada da grade; triângulos com vértice inválido são mascarados.
    ny, nx = coords_px.shape[1:3]
    idx = np.arange(ny * nx).reshape(ny, nx)
    a0, a1 = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    b0, b1 = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    tris = np.r_[np.c_[a0, a1, b1], np.c_[a0, b1, b0]]
    pos_mm = coords_px.reshape(n, -1, 2) * mm

    desl, defo = tx("Deslocamento", "Displacement"), tx("Deformação", "Strain")
    titulos = [f"{desl} $u_x$ ({u_d})", f"{desl} $u_y$ ({u_d})",
               defo + " $\\varepsilon_{xx}$ (%)", defo + " $\\varepsilon_{yy}$ (%)"]
    def p995(a):
        v = np.abs(np.concatenate([q(a, i) for i in selecionados]))
        return max(float(np.percentile(v, 99.5)), 1e-12) if v.size else 1.0
    escalas = [p995(a) for a in campos]
    for i in selecionados:
        val = valido[i].ravel()
        mascara = ~val[tris].all(axis=1)
        fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
        fig.suptitle(f"{arquivos[i].name} · " + tx(f"quadro {i} · {estados[i]} · configuração deformada",
                                                   f"frame {i} · {ESTADOS_EN.get(estados[i], estados[i])} · deformed configuration"))
        for ax, a, titulo, ec in zip(axes.flat, campos, titulos, escalas):
            fundo(ax, i)
            if mascara.all():
                ax.set_title(titulo + tx(" — sem pontos válidos", " — no valid points"))
                continue
            xy = np.where(val[:, None], pos_mm[i], pos_mm[0])  # posição segura para pontos inválidos
            tri = Triangulation(xy[:, 0], xy[:, 1], tris, mask=mascara)
            valores = np.where(val, a[i].ravel(), 0.0)
            col = ax.tripcolor(tri, valores, shading="gouraud", cmap="RdBu_r",
                               vmin=-ec, vmax=ec, antialiased=False, rasterized=True)
            ax.set_title(titulo)
            fig.colorbar(col, ax=ax, shrink=0.80)
        fig.savefig(saida / f"mapas_{arquivos[i].stem}.png", dpi=150)
        plt.close(fig)

    quadros = np.arange(n)
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout="constrained", sharex=True)
    for ax, a, titulo in zip(axes.flat, campos, titulos):
        media = np.array([q(a, i).mean() if valido[i].any() else np.nan for i in quadros])
        p05, p95 = np.array([np.percentile(q(a, i), [5, 95]) if valido[i].any() else [np.nan] * 2
                             for i in quadros]).T
        ax.fill_between(quadros, p05, p95, color="#2a78b5", alpha=0.18, linewidth=0, label="p05–p95")
        ax.plot(quadros, media, color="#2a78b5", linewidth=2, label=tx("média", "mean"))
        ax.axhline(0, color="#888", linewidth=0.8)
        ax.set(title=titulo)
        ax.grid(alpha=0.25)
    for ax in axes[1]:
        ax.set_xlabel(tx("quadro", "frame"))
    axes[0, 0].legend(frameon=False)
    fig.suptitle(tx("Evolução na ROI", "Evolution in the ROI"))
    fig.savefig(saida / "evolucao_por_quadro.png", dpi=150)
    plt.close(fig)
