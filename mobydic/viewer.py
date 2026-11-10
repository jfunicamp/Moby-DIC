"""Moby-DIC · gera um visualizador HTML autocontido (abre direto no navegador) para uma pasta de resultados.

Armazena ux, uy, εxx, εyy, εxy, a rotação ω e, quando disponível, a ZNCC por ponto
(qualidade_subsets.npz), além das trajetórias dos pontos para o extensômetro digital. Os campos são
interpolados numa grade regular na configuração deformada, quantizados em 12 bits, codificados por
diferença entre quadros e comprimidos com gzip dentro do HTML; as imagens de fundo entram como JPEG.

Na página:
- campos derivados calculados na hora (|u|, ε₁, ε₂, cisalhamento máximo, von Mises, variação de
  área, razão de contração, anisotropia r, incrementos por quadro);
- idioma português/inglês (interface e figuras exportadas);
- colormaps (jet, white-jet, turbo, viridis, …) com opção de inverter;
- layout de 1, 2 ou 4 painéis, escala de cor por barra ou valor digitado;
- zoom sincronizado nos painéis (roda do mouse, arrastar, duplo clique, botões e teclas + − 0);
- exportação: figura do quadro atual (PNG), intervalo de quadros (ZIP com PNG/JPEG) e animação
  (vídeo MP4 ou WebM, conforme o navegador), com quadro inicial, final, passo e velocidade.
"""

import argparse
import base64
import gzip
import io
import json
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image
from scipy import ndimage as nd

from .i18n import idioma, t as tx

from . import NOME, __version__
from .imagens import imagem_exibicao, listar_imagens
from .subsets import preencher

NIVEIS = 4094  # 12 bits: 0 = sem dado, 1..4095 = valor
COLORMAPS = ["jet", "whitejet", "turbo", "viridis", "plasma", "inferno", "magma", "cividis",
             "coolwarm", "RdBu_r", "seismic", "bwr", "gray"]
METODO_EN = {
    "DIC local por subsets (IC-GN, ZNSSD, forma afim, B-spline cúbica)":
        "Local subset DIC (IC-GN, ZNSSD, affine shape function, cubic B-spline)",
    "muDIC q4": "muDIC Q4 mesh", "muDIC spline": "muDIC B-spline mesh",
}


def colormaps():
    from matplotlib.colors import LinearSegmentedColormap
    whitejet = LinearSegmentedColormap.from_list("whitejet", [
        (0.00, (0.0, 0.0, 0.5)), (0.15, (0.0, 0.0, 1.0)), (0.32, (0.0, 1.0, 1.0)),
        (0.50, (1.0, 1.0, 1.0)), (0.68, (1.0, 1.0, 0.0)), (0.85, (1.0, 0.0, 0.0)),
        (1.00, (0.5, 0.0, 0.0))])
    return {nome: (whitejet if nome == "whitejet" else matplotlib.colormaps[nome]) for nome in COLORMAPS}


def carregar(arquivo):
    """Lê um .npz inteiro para a memória e fecha o arquivo (no Windows, arquivo aberto fica bloqueado)."""
    with np.load(arquivo) as z:
        return {k: z[k] for k in z.files}


def b64(dados):
    return base64.b64encode(dados).decode("ascii")


def traduzir_metodo(metodo):
    for pt, en in METODO_EN.items():
        if metodo.startswith(pt):
            return en + metodo[len(pt):].replace("(combinação de duas análises)", "(combination of two analyses)")
    return metodo


def gerar(pasta, celula, largura_fundo, qualidade, ate=None, cmap_padrao="jet", idioma="pt"):
    meta = json.loads((pasta / "parametros.json").read_text(encoding="utf-8"))
    escala = meta["escala_um_px"]
    z = carregar(pasta / "campos.npz")
    pos, val = z["centro_xy_px"], z["valido"]
    desloc = z["deslocamento_xy_um"]
    valores = {"ux": desloc[..., 0], "uy": desloc[..., 1],
               "exx": z["deformacao_xx"] * 100, "eyy": z["deformacao_yy"] * 100}
    if "deformacao_xy" in z:
        valores["exy"] = z["deformacao_xy"] * 100
    if "rotacao" in z:
        valores["rot"] = np.degrees(z["rotacao"])
    elif (pasta / "campos_extra.npz").exists():   # resultados antigos
        ze = carregar(pasta / "campos_extra.npz")
        valores["exy"] = ze["exy"] * 100
        valores["rot"] = np.degrees(ze["rotacao"])
    calibrado = bool(meta.get("calibrado", True))
    if (pasta / "qualidade_subsets.npz").exists():
        zq = carregar(pasta / "qualidade_subsets.npz")
        if zq["zncc"].shape == val.shape:
            valores["zncc"] = zq["zncc"]
    arquivos = [str(a) for a in z["arquivos"]]
    estados_z = [str(e) for e in z["estado"]]
    if ate is not None:  # desconsidera os quadros após "ate"
        pos, val, arquivos, estados_z = pos[:ate + 1], val[:ate + 1], arquivos[:ate + 1], estados_z[:ate + 1]
        valores = {k: a[:ate + 1] for k, a in valores.items()}
    ids = list(valores)
    n, ny, nx = val.shape
    largura_img, altura_img = meta["tamanho_imagem_px"]

    # Grade de saída (px, origem inferior) cobrindo todas as posições válidas.
    pv = pos[val]
    x0, y0 = np.floor(pv.min(0) / celula) * celula - celula
    x1, y1 = np.ceil(pv.max(0) / celula) * celula + celula
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, largura_img - 1), min(y1, altura_img - 1)
    gx = np.arange(x0, x1 + 1e-9, celula)
    gy = np.arange(y0, y1 + 1e-9, celula)
    GX, GY = np.meshgrid(gx, gy)
    W, H = len(gx), len(gy)

    faixas = {}
    for k, a in valores.items():
        v = a[val]
        lo, hi = np.nanpercentile(v, [0.05, 99.95])
        pad = 0.05 * (hi - lo + 1e-12)
        faixas[k] = (float(lo - pad), float(hi + pad))
    quant = np.zeros((len(ids), n, H, W), dtype=np.int32)
    X0, Y0 = pos[0, 0, 0, 0], pos[0, 0, 0, 1]
    dX = pos[0, 0, 1, 0] - X0 if nx > 1 else 1.0
    dY = pos[0, 1, 0, 1] - Y0 if ny > 1 else 1.0
    # Trajetórias lagrangianas para o extensômetro digital: deslocamento de cada nó da grade de
    # medição (subamostrada se for densa) em 1/64 px, codificado por diferença entre quadros.
    sub = max(1, int(np.ceil(np.sqrt(nx * ny / 6000))))
    trilha = np.zeros((n, len(range(0, ny, sub)), len(range(0, nx, sub)), 2), dtype=np.float64)
    mtr = np.zeros(trilha.shape[:3], dtype=np.uint8)
    for t in range(n):
        v = val[t]
        if v.sum() < 3:
            continue
        mtr[t] = v[::sub, ::sub]
        # Inversão x = X + u(X) por ponto fixo no campo de deslocamento contínuo (inválidos
        # preenchidos pelos vizinhos); depois amostra os campos na grade de referência.
        d = preencher(pos[t] - pos[0], v)
        trilha[t] = d[::sub, ::sub]
        cx, cy = (GX - X0) / dX, (GY - Y0) / dY
        for _ in range(12):
            ux = nd.map_coordinates(d[..., 0], [cy, cx], order=1, mode="nearest")
            uy = nd.map_coordinates(d[..., 1], [cy, cx], order=1, mode="nearest")
            cx, cy = (GX - ux - X0) / dX, (GY - uy - Y0) / dY
        dentro = (cx >= 0) & (cx <= nx - 1) & (cy >= 0) & (cy <= ny - 1)
        vale = nd.map_coordinates(v.astype(float), [cy, cx], order=1, mode="constant") > 0.999
        ok = dentro & vale
        for c, k in enumerate(ids):
            campo = np.where(v, valores[k][t], 0.0)
            g = nd.map_coordinates(campo, [cy, cx], order=1, mode="nearest")
            lo, hi = faixas[k]
            q = np.clip(np.round(1 + (g - lo) / (hi - lo) * NIVEIS), 1, NIVEIS + 1)
            quant[c, t] = np.where(ok & np.isfinite(g), q, 0)
    delta = np.diff(quant, axis=1, prepend=0).astype("<i2").view("<u2")
    planos = np.concatenate([(delta >> 8).astype(np.uint8).ravel(), (delta & 255).astype(np.uint8).ravel()])
    blob = b64(gzip.compress(planos.tobytes(), compresslevel=9))
    qt = np.round(np.nan_to_num(trilha) * 64).astype(np.int64)
    dq = np.clip(np.diff(qt, axis=0, prepend=0), -32768, 32767).astype("<i2")
    blob_trilhas = b64(gzip.compress(dq.tobytes() + mtr.tobytes(), compresslevel=9))

    pasta_img = Path(meta["pasta_imagens"])
    por_nome = {p.name: p for p in listar_imagens(pasta_img)}
    tempos = None                     # quadros extraídos de vídeo: tempo de cada quadro (frames.csv)
    if (pasta_img / "frames.csv").exists():
        import csv as _csv
        with (pasta_img / "frames.csv").open(encoding="utf-8") as f:
            t_por_nome = {r["arquivo"]: float(r["tempo_s"]) for r in _csv.DictReader(f)}
        if all(a in t_por_nome for a in arquivos):
            tempos = [t_por_nome[a] for a in arquivos]
    topo, base = int(altura_img - 1 - y1), int(altura_img - 1 - y0)
    esq, dir_ = int(x0), int(x1)
    fator = largura_fundo / (dir_ - esq + 1)
    tam = (largura_fundo, max(1, round((base - topo + 1) * fator)))
    fundos = []
    for nome in arquivos:
        rec = imagem_exibicao(por_nome[nome]).crop((esq, topo, dir_ + 1, base + 1)).resize(tam, Image.LANCZOS)
        buf = io.BytesIO()
        rec.save(buf, "JPEG", quality=qualidade)
        fundos.append(b64(buf.getvalue()))

    luts = {nome: (cm(np.linspace(0, 1, 256))[:, :3] * 255).round().astype(int).ravel().tolist()
            for nome, cm in colormaps().items()}
    amostra = pasta_img.name
    fe = escala / 1000 if calibrado else 1.0   # px -> unidade dos eixos
    metodo = meta.get("metodo", "")
    dados = {
        "amostra": amostra, "pasta": pasta.name, "metodo": {"pt": metodo, "en": traduzir_metodo(metodo)},
        "escala_um_px": escala, "calibrado": calibrado, "u_eixo": "mm" if calibrado else "px",
        "u_desl": "µm" if calibrado else "px", "programa": f"{NOME} {__version__}", "arquivos": arquivos, "n": n, "W": W, "H": H, "celula_px": celula,
        "x0_mm": (x0 - 0.5 * celula) * fe, "y0_mm": (y0 - 0.5 * celula) * fe,
        "x1_mm": (x1 + 0.5 * celula) * fe, "y1_mm": (y1 + 0.5 * celula) * fe,
        "armazenados": [{"id": k, "lo": faixas[k][0], "hi": faixas[k][1]} for k in ids],
        "luts": luts, "cmaps": COLORMAPS, "cmap_padrao": cmap_padrao, "idioma_padrao": idioma,
        "niveis": NIVEIS, "estado": estados_z,
        "trilhas": {"nx": trilha.shape[2], "ny": trilha.shape[1], "x0": float(X0), "y0": float(Y0),
                    "dx": float(dX * sub), "dy": float(dY * sub)},
        "tempos": tempos,
    }
    html = MODELO.replace("__DADOS__", json.dumps(dados, ensure_ascii=False)) \
                 .replace("__BLOB__", blob).replace("__FUNDOS__", json.dumps(fundos)) \
                 .replace("__TRILHAS__", blob_trilhas) \
                 .replace("__TITULO__", f"{NOME} · {amostra}")
    destino = pasta / "visualizador.html"
    destino.write_text(html, encoding="utf-8")
    return destino, len(html) / 1e6


MODELO = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--muted:#5d6678;--line:#d9dde5;--accent:#2a6fdb;--accent-ink:#fff;--warn:#b25b00;}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#14171c;--card:#1c2027;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2f3540;--accent:#5b95f0;--accent-ink:#0b0d10;--warn:#f0a040;}}
:root[data-theme="dark"]{--bg:#14171c;--card:#1c2027;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2f3540;--accent:#5b95f0;--accent-ink:#0b0d10;--warn:#f0a040;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{padding:14px 16px 6px;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:flex-end;justify-content:space-between}
h1{font-size:18px;margin:0 0 2px}
.sub{color:var(--muted);font-size:12.5px}
.barra{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;
  padding:9px 16px;background:var(--card);border-bottom:1px solid var(--line)}
.grupo{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;
  padding:6px 11px;cursor:pointer;min-width:38px}
button:hover{border-color:var(--accent)}
button:disabled{opacity:.5;cursor:default}
button.prim{background:var(--accent);color:var(--accent-ink);border-color:var(--accent);min-width:84px}
input[type=range]{accent-color:var(--accent)}
input[type=number]{font:inherit;width:78px;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink)}
select{font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);max-width:100%}
label{color:var(--muted)}
#quadro{flex:1 1 240px;min-width:160px}
.info{color:var(--muted);font-variant-numeric:tabular-nums}
.grade{display:grid;gap:14px;padding:14px 16px}
.grade.l1{grid-template-columns:1fr}
.grade.l2,.grade.l4{grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr))}
.painel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;min-width:0}
.painel select.campo{font-weight:600;width:100%}
canvas.mapa{width:100%;display:block;cursor:crosshair;margin-top:6px;touch-action:none}
.ctrl{display:grid;grid-template-columns:auto 1fr auto;gap:6px 8px;align-items:center;margin-top:6px;font-size:13px}
.ctrl .lin{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center}
.dica{position:fixed;pointer-events:none;background:rgba(15,18,24,.9);color:#fff;font-size:12.5px;padding:3px 8px;border-radius:6px;z-index:50;white-space:nowrap;display:none;font-variant-numeric:tabular-nums}
.leitura{padding:0 16px 10px;color:var(--muted);font-variant-numeric:tabular-nums;min-height:2.6em}
#carregando{padding:40px 16px;color:var(--muted)}
details.exportar{margin:0 16px 16px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px}
details.exportar summary{cursor:pointer;font-weight:600}
.exp{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:14px;margin-top:10px}
.exp section{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.exp h3{margin:0 0 8px;font-size:14px}
.exp .lin{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-bottom:8px}
.nota{color:var(--muted);font-size:12.5px}
progress{width:100%;height:10px}
.ext{margin-top:10px}.ext .lin{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-bottom:6px}
.extStatus{font-size:13.5px;font-variant-numeric:tabular-nums;min-height:1.4em;margin:4px 0}
.extGraf{width:100%;height:240px;display:block;border:1px solid var(--line);border-radius:8px;background:var(--card)}
#status{font-size:13px;color:var(--muted);margin-top:6px;min-height:1.3em}
</style>
</head>
<body>
<header>
  <div><h1 id="titulo"></h1><div class="sub" id="sub"></div></div>
  <div class="grupo">
    <label><span data-t="idioma"></span> <select id="idioma"><option value="pt">Português</option><option value="en">English</option></select></label>
    <label><span data-t="layout"></span> <select id="layout"><option value="1">1</option><option value="2">2</option><option value="4" selected>4</option></select></label>
    <span class="grupo"><span class="info" data-t="zoom"></span>
      <button id="zoomMais" data-tt="zoomMaisTip">+</button><button id="zoomMenos" data-tt="zoomMenosTip">−</button>
      <button id="zoomReset" data-t="ajustar" data-tt="ajustarTip"></button><span class="info" id="zoomNivel"></span></span>
  </div>
</header>
<div class="barra">
  <div class="grupo">
    <button id="ant" data-tt="anterior">◀</button>
    <button id="play" class="prim" data-tt="playTip"></button>
    <button id="prox" data-tt="proximo">▶</button>
  </div>
  <input type="range" id="quadro" min="0" value="0" aria-label="frame">
  <input type="number" id="quadroNum" min="0" step="1" aria-label="frame">
  <label><span data-t="velocidade"></span> <select id="fps"><option>2</option><option>5</option><option selected>10</option><option>20</option><option>30</option></select> <span data-t="qps"></span></label>
  <label><input type="checkbox" id="loop" checked> <span data-t="repetir"></span></label>
  <label><span data-t="opacidade"></span> <input type="range" id="alfa" min="0" max="100" value="85" style="width:84px"></label>
  <label><input type="checkbox" id="fundo" checked> <span data-t="imagem"></span></label>
  <label><span data-t="cores"></span> <select id="cmap"></select></label>
  <label><input type="checkbox" id="inverter"> <span data-t="inverter"></span></label>
  <span class="info" id="nomeQuadro"></span>
</div>
<div id="carregando"></div>
<div class="grade l4" id="grade"></div>
<div class="leitura" id="leitura"></div>
<div class="dica" id="dica"></div>
<details class="exportar" id="painelExt" open>
  <summary data-t="ext"></summary>
  <div class="ext">
    <div class="lin"><button id="extAuto" data-t="extAuto"></button><button id="extMarcar" data-t="extMarcar"></button>
      <button id="extLimpar" data-t="extLimpar"></button><button id="extCSV" data-t="extCSV"></button>
      <label><span data-t="extComp"></span> <select id="extComp"><option value="d">L</option><option value="x">x</option><option value="y">y</option></select></label></div>
    <p class="nota" data-t="extNota"></p>
    <div id="extStatus" class="extStatus"></div>
    <canvas id="extGraf" class="extGraf"></canvas>
  </div>
</details>
<details class="exportar" id="painelExportar">
  <summary data-t="exportar"></summary>
  <div class="exp">
    <section>
      <h3 data-t="expFigura"></h3>
      <div class="lin"><label><span data-t="resolucao"></span> <select id="escalaExp"><option value="1">1×</option><option value="2" selected>2×</option><option value="3">3×</option></select></label>
        <label><input type="checkbox" id="expTitulo" checked> <span data-t="comTitulo"></span></label></div>
      <button id="btnFigura" data-t="baixarPNG"></button>
      <p class="nota" data-t="notaFigura"></p>
    </section>
    <section>
      <h3 data-t="expQuadros"></h3>
      <div class="lin">
        <label><span data-t="de"></span> <input type="number" id="qIni" min="0" step="1"></label>
        <label><span data-t="ate"></span> <input type="number" id="qFim" min="0" step="1"></label>
        <label><span data-t="passo"></span> <input type="number" id="qPasso" min="1" step="1" value="1"></label>
      </div>
      <div class="lin"><label><span data-t="formato"></span> <select id="formatoImg"><option value="png">PNG</option><option value="jpeg">JPEG</option></select></label>
        <span class="info" id="contaQuadros"></span></div>
      <button id="btnZip" data-t="baixarZIP"></button>
    </section>
    <section>
      <h3 data-t="expAnimacao"></h3>
      <div class="lin">
        <label><span data-t="de"></span> <input type="number" id="aIni" min="0" step="1"></label>
        <label><span data-t="ate"></span> <input type="number" id="aFim" min="0" step="1"></label>
        <label><span data-t="passo"></span> <input type="number" id="aPasso" min="1" step="1" value="1"></label>
      </div>
      <div class="lin"><label><span data-t="velocidade"></span> <input type="number" id="aFps" min="1" max="60" step="1" value="10"> <span data-t="qps"></span></label>
        <label><span data-t="formato"></span> <select id="formatoVid"></select></label>
        <span class="info" id="contaAnim"></span></div>
      <button id="btnVideo" data-t="gravarVideo"></button>
      <p class="nota" data-t="notaVideo"></p>
    </section>
  </div>
  <progress id="progresso" value="0" max="1" hidden></progress>
  <div class="lin" style="display:flex;gap:10px;align-items:center"><span id="status"></span><button id="btnCancelar" data-t="cancelar" hidden></button></div>
</details>
<script>
const D = __DADOS__;
const FUNDOS = __FUNDOS__;
const BLOB = "__BLOB__";
const TRILHAS = "__TRILHAS__";
const N = D.n, W = D.W, H = D.H;

// ---------------------------------------------------------------- textos
const TXT = {
  pt: {idioma:"Idioma", layout:"Painéis", anterior:"Quadro anterior (←)", proximo:"Próximo quadro (→)", playTip:"Play/pausa (espaço)",
    play:"▶ Play", pausa:"❚❚ Pausa", velocidade:"Velocidade", qps:"quadros/s", repetir:"repetir", opacidade:"Opacidade",
    imagem:"imagem", cores:"Cores", inverter:"inverter", carregando:"Descompactando dados…", falha:"Falha ao descompactar os dados: ",
    lerCursor:"Passe o cursor sobre um mapa para ler os valores.", limite:"± limite", simetrico:"simétrico", min:"mín", max:"máx",
    auto:"auto", autoTip:"Escala automática (todos os quadros)", quadroBtn:"quadro", quadroTip:"Escala pelo quadro atual",
    quadro:"quadro", exportar:"Exportar", expFigura:"Figura do quadro atual", resolucao:"Resolução", comTitulo:"com título",
    baixarPNG:"Baixar PNG", notaFigura:"Exporta os painéis visíveis, com as escalas, colormap e idioma atuais.",
    expQuadros:"Quadros como imagens (ZIP)", de:"de", ate:"até", passo:"passo", formato:"Formato", baixarZIP:"Baixar ZIP",
    expAnimacao:"Animação (vídeo)", gravarVideo:"Gravar vídeo", cancelar:"Cancelar",
    notaVideo:"O vídeo é gravado em tempo real na velocidade escolhida; mantenha esta aba visível até terminar. MP4 aparece quando o navegador oferece suporte (Chrome/Edge recentes).",
    nQuadros:n=>`${n} quadros`, gerando:(i,n)=>`Gerando ${i}/${n}…`, pronto:"Pronto.", cancelado:"Cancelado.", semVideo:"Este navegador não grava vídeo a partir do canvas.",
    sub:(m,e,n,w,h,c)=>`${m} · ${e} · ${n} quadros · grade de exibição ${w}×${h} (${c} px) · origem no canto inferior esquerdo, y para cima`,
    eixoX:"x", eixoY:"y", deformada:"configuração deformada", semCal:"sem calibração (pixels)",
    estados:{referencia:"referência", convergiu:"convergiu", quadro_ruim:"quadro ruim", nao_convergiu:"não convergiu"},
    grupos:{desl:"Deslocamentos", def:"Deformações", der:"Grandezas derivadas", taxa:"Incrementos entre quadros", qual:"Qualidade da medição"},
    zoom:"Zoom", zoomMaisTip:"Aproximar (ou roda do mouse sobre um mapa)", zoomMenosTip:"Afastar", ajustar:"ajustar",
    ajustarTip:"Mostrar a região inteira (ou duplo clique no mapa)", dicaZoom:"Roda do mouse: zoom · arrastar: mover · duplo clique: ajustar.",
    ext:"Extensômetro digital", extAuto:"Sugestão automática", extMarcar:"Marcar dois pontos", extLimpar:"Remover", extCSV:"Baixar CSV",
    extComp:"Medir", extNota:"Deformação de engenharia entre dois pontos materiais marcados no quadro inicial, como um extensômetro de contato: ε = L/L₀ − 1 (L = distância entre os pontos; x ou y = só a componente nessa direção). Sugestão automática: linha na direção x, no centro da região medida, com metade da largura.",
    extA:"Clique no primeiro ponto (A) num mapa. O quadro inicial foi selecionado.", extB:"Agora clique no segundo ponto (B).", extFora:"Ponto fora da região medida no quadro inicial; escolha outro.",
    extVazio:"Nenhum extensômetro. Use a sugestão automática ou marque dois pontos.", extSem:"Este visualizador não tem as trajetórias dos pontos; gere-o de novo com o Moby-DIC 1.1 ou mais recente.",
    extResumo:(L0, u, e, et, tt) => `L₀ = ${L0} ${u} · ${T("quadro")} ${tt}: ε = ${e} % (verdadeira ${et} %)`, eixoQ:"quadro", eixoT:"tempo (s)", extEixoY:"ε extensômetro (%)"},
  en: {idioma:"Language", layout:"Panels", anterior:"Previous frame (←)", proximo:"Next frame (→)", playTip:"Play/pause (space)",
    play:"▶ Play", pausa:"❚❚ Pause", velocidade:"Speed", qps:"frames/s", repetir:"loop", opacidade:"Opacity",
    imagem:"image", cores:"Colormap", inverter:"reverse", carregando:"Decompressing data…", falha:"Could not decompress the data: ",
    lerCursor:"Hover over a map to read the values.", limite:"± limit", simetrico:"symmetric", min:"min", max:"max",
    auto:"auto", autoTip:"Automatic scale (all frames)", quadroBtn:"frame", quadroTip:"Scale from the current frame",
    quadro:"frame", exportar:"Export", expFigura:"Figure of the current frame", resolucao:"Resolution", comTitulo:"with title",
    baixarPNG:"Download PNG", notaFigura:"Exports the visible panels with the current scales, colormap and language.",
    expQuadros:"Frames as images (ZIP)", de:"from", ate:"to", passo:"step", formato:"Format", baixarZIP:"Download ZIP",
    expAnimacao:"Animation (video)", gravarVideo:"Record video", cancelar:"Cancel",
    notaVideo:"The video is recorded in real time at the chosen speed; keep this tab visible until it finishes. MP4 is offered when the browser supports it (recent Chrome/Edge).",
    nQuadros:n=>`${n} frames`, gerando:(i,n)=>`Rendering ${i}/${n}…`, pronto:"Done.", cancelado:"Cancelled.", semVideo:"This browser cannot record video from a canvas.",
    sub:(m,e,n,w,h,c)=>`${m} · ${e} · ${n} frames · display grid ${w}×${h} (${c} px) · origin at the lower-left corner, y up`,
    eixoX:"x", eixoY:"y", deformada:"deformed configuration", semCal:"uncalibrated (pixels)",
    estados:{referencia:"reference", convergiu:"converged", quadro_ruim:"bad frame", nao_convergiu:"not converged"},
    grupos:{desl:"Displacements", def:"Strains", der:"Derived quantities", taxa:"Frame-to-frame increments", qual:"Measurement quality"},
    zoom:"Zoom", zoomMaisTip:"Zoom in (or mouse wheel over a map)", zoomMenosTip:"Zoom out", ajustar:"fit",
    ajustarTip:"Show the whole region (or double-click the map)", dicaZoom:"Mouse wheel: zoom · drag: pan · double-click: fit.",
    ext:"Digital extensometer", extAuto:"Automatic suggestion", extMarcar:"Pick two points", extLimpar:"Remove", extCSV:"Download CSV",
    extComp:"Measure", extNota:"Engineering strain between two material points picked in the initial frame, like a clip-on extensometer: ε = L/L₀ − 1 (L = distance between the points; x or y = only that component). Automatic suggestion: a line along x, centred in the measured region, half its width long.",
    extA:"Click the first point (A) on a map. The initial frame has been selected.", extB:"Now click the second point (B).", extFora:"Point outside the region measured in the initial frame; pick another one.",
    extVazio:"No extensometer. Use the automatic suggestion or pick two points.", extSem:"This viewer has no point tracks; rebuild it with Moby-DIC 1.1 or later.",
    extResumo:(L0, u, e, et, tt) => `L₀ = ${L0} ${u} · ${T("quadro")} ${tt}: ε = ${e} % (true ${et} %)`, eixoQ:"frame", eixoT:"time (s)", extEixoY:"extensometer ε (%)"},
};
let L = "pt";
try { L = localStorage.getItem("dic_idioma") || D.idioma_padrao || "pt"; } catch(e) { L = D.idioma_padrao || "pt"; }
{ const q = new URLSearchParams(location.search).get("lang"); if (q === "pt" || q === "en") L = q; }
const T = k => TXT[L][k];

// ---------------------------------------------------------------- campos
// tipo: s = armazenado; d = derivado de outros armazenados (função de valores do ponto i no quadro t)
const ARM = {}; D.armazenados.forEach((c, j) => ARM[c.id] = j);
const tem = id => id in ARM;
const CAMPOS = [
  {id:"ux", g:"desl", s:1, sim:1, u:"µm", pt:"Deslocamento horizontal uₓ (direção da carga)", en:"Horizontal displacement uₓ (loading direction)", c:"uₓ"},
  {id:"uy", g:"desl", s:1, sim:1, u:"µm", pt:"Deslocamento vertical u_y", en:"Vertical displacement u_y", c:"u_y"},
  {id:"umag", g:"desl", dep:["ux","uy"], sim:0, u:"µm", pt:"Deslocamento total |u|", en:"Displacement magnitude |u|", c:"|u|",
    f:(v)=>Math.hypot(v.ux, v.uy)},
  {id:"exx", g:"def", s:1, sim:1, u:"%", pt:"Deformação axial εxx (direção da carga)", en:"Axial strain εxx (loading direction)", c:"εxx"},
  {id:"eyy", g:"def", s:1, sim:1, u:"%", pt:"Deformação transversal εyy", en:"Transverse strain εyy", c:"εyy"},
  {id:"exy", g:"def", s:1, sim:1, u:"%", pt:"Deformação de cisalhamento εxy", en:"Shear strain εxy", c:"εxy"},
  {id:"e1", g:"der", dep:["exx","eyy","exy"], sim:1, u:"%", pt:"Deformação principal máxima ε₁", en:"Major principal strain ε₁", c:"ε₁",
    f:(v)=>(v.exx+v.eyy)/2 + Math.hypot((v.exx-v.eyy)/2, v.exy)},
  {id:"e2", g:"der", dep:["exx","eyy","exy"], sim:1, u:"%", pt:"Deformação principal mínima ε₂", en:"Minor principal strain ε₂", c:"ε₂",
    f:(v)=>(v.exx+v.eyy)/2 - Math.hypot((v.exx-v.eyy)/2, v.exy)},
  {id:"gmax", g:"der", dep:["exx","eyy","exy"], sim:0, u:"%", pt:"Cisalhamento máximo (ε₁ − ε₂)/2", en:"Maximum shear strain (ε₁ − ε₂)/2", c:"γmax/2",
    f:(v)=>Math.hypot((v.exx-v.eyy)/2, v.exy)},
  {id:"eeq", g:"der", dep:["exx","eyy","exy"], sim:0, u:"%", pt:"Deformação equivalente de von Mises εeq", en:"Von Mises equivalent strain εeq", c:"εeq",
    f:(v)=>{const ezz=-(v.exx+v.eyy); return Math.sqrt(2/3*(v.exx*v.exx+v.eyy*v.eyy+ezz*ezz+2*v.exy*v.exy));}},
  {id:"dil", g:"der", dep:["exx","eyy"], sim:1, u:"%", pt:"Variação de área εxx + εyy", en:"Area change εxx + εyy", c:"εxx+εyy",
    f:(v)=>v.exx+v.eyy},
  {id:"razao", g:"der", dep:["exx","eyy"], sim:0, u:"–", pt:"Razão de contração −εyy/εxx (\"Poisson aparente\")", en:"Contraction ratio −εyy/εxx (\"apparent Poisson\")", c:"−εyy/εxx",
    f:(v)=>v.exx>0.5 ? -v.eyy/v.exx : NaN},
  {id:"lank", g:"der", dep:["exx","eyy"], sim:0, u:"–", pt:"Anisotropia plástica r = εyy/εzz", en:"Plastic anisotropy r = εyy/εzz", c:"r",
    f:(v)=>{ if(!(v.exx>0.5)) return NaN; const q=-v.eyy/v.exx; return (q>0&&q<0.95) ? q/(1-q) : NaN; }},
  {id:"rot", g:"der", s:1, sim:1, u:"°", pt:"Rotação local ω", en:"Local rotation ω", c:"ω"},
  {id:"dexx", g:"taxa", dep:["exx"], inc:1, sim:1, u:"%", pt:"Incremento de deformação axial Δεxx", en:"Axial strain increment Δεxx", c:"Δεxx",
    f:(v,a)=>v.exx-a.exx},
  {id:"deyy", g:"taxa", dep:["eyy"], inc:1, sim:1, u:"%", pt:"Incremento de deformação transversal Δεyy", en:"Transverse strain increment Δεyy", c:"Δεyy",
    f:(v,a)=>v.eyy-a.eyy},
  {id:"deeq", g:"taxa", dep:["exx","eyy","exy"], inc:1, sim:1, u:"%", pt:"Incremento de deformação equivalente Δεeq", en:"Equivalent strain increment Δεeq", c:"Δεeq",
    f:(v,a)=>{const e=(x)=>{const z=-(x.exx+x.eyy); return Math.sqrt(2/3*(x.exx*x.exx+x.eyy*x.eyy+z*z+2*x.exy*x.exy));}; return e(v)-e(a);}},
  {id:"zncc", g:"qual", s:1, sim:0, u:"–", pt:"Qualidade da correlação (ZNCC, 1 = perfeita)", en:"Correlation quality (ZNCC, 1 = perfect)", c:"ZNCC"},
].filter(c => c.s ? tem(c.id) : c.dep.every(tem));
const NC = CAMPOS.length;
const IDX = {}; CAMPOS.forEach((c, k) => IDX[c.id] = k);
const nomeCampo = c => c[L];
const unidade = c => c.inc && c.u === "%" ? (L === "pt" ? "%/quadro" : "%/frame") : (c.u === "µm" ? D.u_desl : c.u);

let Q = null;
let t = 0, tocando = false, timer = null;
// Vista (mm) compartilhada por todos os painéis e pelas exportações.
const V = {x0: D.x0_mm, x1: D.x1_mm, y0: D.y0_mm, y1: D.y1_mm};
const largD = D.x1_mm - D.x0_mm, altD = D.y1_mm - D.y0_mm;
function limitarVista(){
  const w = Math.min(largD, V.x1 - V.x0), h = Math.min(altD, V.y1 - V.y0);
  V.x0 = Math.max(D.x0_mm, Math.min(D.x1_mm - w, V.x0)); V.x1 = V.x0 + w;
  V.y0 = Math.max(D.y0_mm, Math.min(D.y1_mm - h, V.y0)); V.y1 = V.y0 + h;
}
function zoomEm(fator, cx, cy){   // fator > 1 aproxima; o ponto (cx, cy) em mm fica fixo
  const w = Math.max(largD/40, Math.min(largD, (V.x1 - V.x0)/fator)), h = w*altD/largD;
  cx = cx ?? (V.x0 + V.x1)/2; cy = cy ?? (V.y0 + V.y1)/2;
  const fx = (cx - V.x0)/(V.x1 - V.x0), fy = (cy - V.y0)/(V.y1 - V.y0);
  V.x0 = cx - fx*w; V.x1 = V.x0 + w; V.y0 = cy - fy*h; V.y1 = V.y0 + h;
  limitarVista(); desenhar();
}
function ajustarVista(){ V.x0 = D.x0_mm; V.x1 = D.x1_mm; V.y0 = D.y0_mm; V.y1 = D.y1_mm; desenhar(); }
function passoEixo(span){ const alvo = span/5, e = Math.pow(10, Math.floor(Math.log10(alvo)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m*e >= alvo) return m*e; return 10*e; }
function casas(passo){ for (let d = 0; d < 5; d++) if (Math.abs(passo*Math.pow(10, d) - Math.round(passo*Math.pow(10, d))) < 1e-6) return d; return 4; }
const imgs = new Array(N);
let nomeCmap = D.cmap_padrao, invertido = false, LUT = null;
function atualizarLUT(){ const b = D.luts[nomeCmap]; if (!invertido){ LUT = b; return; }
  LUT = new Array(b.length); for (let i = 0; i < 256; i++) for (let c = 0; c < 3; c++) LUT[i*3+c] = b[(255-i)*3+c]; }

function decimal(s){ return L === "pt" ? s.replace(".", ",") : s; }
function fmtEsc(v, span){ if (!isFinite(v)) return "—"; if (Math.abs(v) < span*1e-6) v = 0;
  const d = Math.max(0, Math.min(5, 2 - Math.floor(Math.log10(span || 1)))); return decimal(v.toFixed(d)); }
function fmt(v){ if (!isFinite(v)) return "—"; if (v === 0) return "0"; const a = Math.abs(v);
  return decimal(a>=100 ? v.toFixed(0) : a>=10 ? v.toFixed(1) : a>=1 ? v.toFixed(2) : a>=0.01 ? v.toFixed(3) : v.toExponential(1)); }

function bruto(id, tt, i){ const j = ARM[id], q = Q[((j*N+tt)*H)*W+i]; if (!q) return NaN;
  const a = D.armazenados[j]; return a.lo + (q-1)/D.niveis*(a.hi - a.lo); }
function valor(k, tt, i){
  const c = CAMPOS[k];
  if (c.s) return bruto(c.id, tt, i);
  const v = {}; for (const d of c.dep){ v[d] = bruto(d, tt, i); if (v[d] !== v[d]) return NaN; }
  if (!c.inc) return c.f(v);
  if (tt === 0) return 0;
  const a = {}; for (const d of c.dep){ a[d] = bruto(d, tt-1, i); if (a[d] !== a[d]) return NaN; }
  return c.f(v, a);
}

// Escalas automáticas: percentis de uma amostra de quadros/células, calculados uma vez por campo.
const estat = new Array(NC);
function estatisticas(k){
  if (estat[k]) return estat[k];
  const c = CAMPOS[k], vals = [];
  const passoT = Math.max(1, Math.floor(N/25)), passoI = Math.max(1, Math.floor(W*H/4000));
  const t0 = c.sim ? 0 : Math.floor(N/2);   // campos não simétricos: segunda metade (evita ruído inicial)
  for (let tt = t0; tt < N; tt += passoT) for (let i = 0; i < W*H; i += passoI){ const x = valor(k, tt, i); if (x === x) vals.push(x); }
  vals.sort((a, b) => a - b);
  const p = q => vals.length ? vals[Math.min(vals.length-1, Math.floor(q*vals.length))] : 0;
  let r;
  if (c.id === "zncc") r = {min: Math.max(0.8, p(0.01)), max: 1};
  else if (c.sim){ const m = Math.max(Math.abs(p(0.005)), Math.abs(p(0.995))) || 1; r = {min: -m, max: m}; }
  else r = {min: (c.id === "eeq" || c.id === "umag" || c.id === "gmax") ? 0 : p(0.02), max: p(0.98) || 1};
  r.ext = Math.max(Math.abs(p(0)), Math.abs(p(1)), r.max - r.min) || 1;
  return estat[k] = r;
}
const escala = new Array(NC);
function escalaDe(k){ if (!escala[k]){ const e = estatisticas(k); escala[k] = {min: e.min, max: e.max, sim: !!CAMPOS[k].sim}; } return escala[k]; }

// ---------------------------------------------------------------- extensômetro digital
const TR = D.trilhas, FE = D.calibrado ? D.escala_um_px/1000 : 1;   // px -> unidade dos eixos
let TRD = null, TRM = null;
const EXT = {A: null, B: null, marcando: 0, serie: null, L0: 0, comp: "d"};
async function descompactarTrilhas(){
  if (!TR || !TRILHAS || TRILHAS.startsWith("__")) return;
  const bin = Uint8Array.from(atob(TRILHAS), ch => ch.charCodeAt(0));
  const b = new Uint8Array(await new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer());
  const nn = TR.nx*TR.ny, q = new Int16Array(b.buffer, 0, N*nn*2);
  TRD = new Float32Array(N*nn*2); TRM = b.subarray(N*nn*4);
  const acc = new Int32Array(nn*2);
  for (let tt = 0; tt < N; tt++) for (let i = 0; i < nn*2; i++){ acc[i] += q[tt*nn*2 + i]; TRD[tt*nn*2 + i] = acc[i]/64; }
}
// deslocamento (px) do ponto material de posição inicial (x, y) px no quadro tt; null se não medido
function deslocPonto(x, y, tt){
  if (!TRD || TR.nx < 2 || TR.ny < 2) return null;
  const fx = (x - TR.x0)/TR.dx, fy = (y - TR.y0)/TR.dy;
  if (fx < 0 || fy < 0 || fx > TR.nx - 1 || fy > TR.ny - 1) return null;
  const c0 = Math.min(TR.nx - 2, Math.floor(fx)), r0 = Math.min(TR.ny - 2, Math.floor(fy)), a = fx - c0, b = fy - r0;
  let ux = 0, uy = 0;
  for (const [dr, dc, w] of [[0, 0, (1-a)*(1-b)], [0, 1, a*(1-b)], [1, 0, (1-a)*b], [1, 1, a*b]]){
    const i = (tt*TR.ny + r0 + dr)*TR.nx + c0 + dc;
    if (w > 1e-9 && !TRM[i]) return null;
    ux += w*TRD[2*i]; uy += w*TRD[2*i + 1];
  }
  return [ux, uy];
}
function calcularExt(){
  EXT.serie = null; if (!EXT.A || !EXT.B) return;
  const [ax, ay] = EXT.A, [bx, by] = EXT.B, comp = EXT.comp;
  const L = (p, q) => comp === "x" ? Math.abs(q[0] - p[0]) : comp === "y" ? Math.abs(q[1] - p[1]) : Math.hypot(q[0] - p[0], q[1] - p[1]);
  EXT.L0 = L([ax, ay], [bx, by]);
  EXT.serie = Array.from({length: N}, (_, tt) => { const da = deslocPonto(ax, ay, tt), db = deslocPonto(bx, by, tt);
    if (!da || !db || !(EXT.L0 > 0)) return NaN; return L([ax + da[0], ay + da[1]], [bx + db[0], by + db[1]])/EXT.L0 - 1; });
}
function sugerirExt(){
  if (!TRD) return;
  // linha de nós com mais quadros medidos, perto do centro; trecho medido em todos (ou quase todos) os quadros
  const conta = new Int32Array(TR.nx*TR.ny);
  for (let tt = 0; tt < N; tt++) for (let i = 0; i < conta.length; i++) conta[i] += TRM[tt*conta.length + i];
  let melhor = -1, rMelhor = 0;
  for (let r = 0; r < TR.ny; r++){ let s = 0; for (let c = 0; c < TR.nx; c++) s += conta[r*TR.nx + c] >= 0.95*N ? 1 : 0;
    const pena = Math.abs(r - (TR.ny - 1)/2)/TR.ny; const nota = s*(1 - pena); if (nota > melhor){ melhor = nota; rMelhor = r; } }
  const ok = []; for (let c = 0; c < TR.nx; c++) if (conta[rMelhor*TR.nx + c] >= 0.95*N) ok.push(c);
  if (ok.length < 4) return;
  const c1 = ok[0], c2 = ok[ok.length - 1], y = TR.y0 + rMelhor*TR.dy;
  EXT.A = [TR.x0 + (c1 + 0.25*(c2 - c1))*TR.dx, y]; EXT.B = [TR.x0 + (c1 + 0.75*(c2 - c1))*TR.dx, y];
  EXT.marcando = 0; calcularExt(); desenhar();
}
function marcarExt(mm){
  const px = [mm.x/FE, mm.y/FE];
  if (!deslocPonto(px[0], px[1], 0)){ document.getElementById("extStatus").textContent = T("extFora"); return; }
  if (EXT.marcando === 1){ EXT.A = px; EXT.B = null; EXT.serie = null; EXT.marcando = 2; }
  else { EXT.B = px; EXT.marcando = 0; calcularExt(); }
  desenhar();
}
// sobreposição nos mapas (tela e figuras exportadas)
function desenharExtEm(ctx, g, tt, fs){
  if (!EXT.A) return;
  const vw = V.x1 - V.x0, vh = V.y1 - V.y0;
  const tela = p => { const d = deslocPonto(p[0], p[1], tt) || [NaN, NaN];
    return [g.X + ((p[0] + d[0])*FE - V.x0)/vw*g.pw, g.Y + g.ph - ((p[1] + d[1])*FE - V.y0)/vh*g.ph]; };
  const pts = [EXT.A, EXT.B].filter(Boolean).map(tela);
  ctx.save(); ctx.beginPath(); ctx.rect(g.X, g.Y, g.pw, g.ph); ctx.clip();
  if (pts.length === 2 && pts.every(p => isFinite(p[0]))){
    ctx.strokeStyle = "rgba(0,0,0,.75)"; ctx.lineWidth = 4*fs; ctx.beginPath(); ctx.moveTo(...pts[0]); ctx.lineTo(...pts[1]); ctx.stroke();
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2*fs; ctx.setLineDash([6*fs, 4*fs]); ctx.beginPath(); ctx.moveTo(...pts[0]); ctx.lineTo(...pts[1]); ctx.stroke(); ctx.setLineDash([]);
  }
  pts.forEach((p, j) => { if (!isFinite(p[0])) return;
    ctx.fillStyle = "#fff"; ctx.strokeStyle = "#111"; ctx.lineWidth = 1.5*fs; ctx.beginPath(); ctx.arc(p[0], p[1], 5*fs, 0, 7); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#111"; ctx.font = `700 ${11*fs}px system-ui,sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    ctx.lineWidth = 3*fs; ctx.strokeStyle = "rgba(255,255,255,.9)"; ctx.strokeText(j ? "B" : "A", p[0], p[1] - 7*fs); ctx.fillText(j ? "B" : "A", p[0], p[1] - 7*fs); });
  if (EXT.serie && pts.length === 2 && isFinite(EXT.serie[tt])){
    const m = [(pts[0][0] + pts[1][0])/2, (pts[0][1] + pts[1][1])/2], txt = `ε = ${decimal((100*EXT.serie[tt]).toFixed(2))} %`;
    ctx.font = `700 ${12*fs}px system-ui,sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.lineWidth = 3.5*fs; ctx.strokeStyle = "rgba(0,0,0,.8)"; ctx.strokeText(txt, m[0], m[1] + 8*fs); ctx.fillStyle = "#fff"; ctx.fillText(txt, m[0], m[1] + 8*fs);
  }
  ctx.restore();
}
function desenharGrafExt(){
  const cv = document.getElementById("extGraf"), st = document.getElementById("extStatus"); if (!cv) return;
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth || 600, h = cv.clientHeight || 240;
  cv.width = Math.round(w*dpr); cv.height = Math.round(h*dpr); const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const est = estiloTela(); ctx.fillStyle = est.bg; ctx.fillRect(0, 0, w, h);
  if (!TRD){ st.textContent = T("extSem"); return; }
  if (EXT.marcando){ st.textContent = EXT.marcando === 1 ? T("extA") : T("extB"); }
  if (!EXT.serie){ if (!EXT.marcando) st.textContent = T("extVazio"); return; }
  const xs = D.tempos || EXT.serie.map((_, i) => i), ys = EXT.serie.map(v => 100*v);
  const fin = ys.filter(v => isFinite(v)); if (!fin.length) return;
  const u = D.u_eixo, L0 = decimal((EXT.L0*FE).toFixed(D.calibrado ? 3 : 1)), e = ys[t], et = 100*Math.log1p(EXT.serie[t]);
  st.textContent = T("extResumo")(L0, u, isFinite(e) ? decimal(e.toFixed(3)) : "—", isFinite(et) ? decimal(et.toFixed(3)) : "—", t);
  const ml = 54, mr = 14, mt = 12, mb = 36, pw = w - ml - mr, ph = h - mt - mb;
  let y0 = Math.min(0, ...fin), y1 = Math.max(0, ...fin); if (y1 - y0 < 1e-6) y1 = y0 + 1;
  const pad = 0.06*(y1 - y0); y0 -= pad; y1 += pad;
  const x0 = xs[0], x1 = xs[xs.length - 1] || 1, X = v => ml + (v - x0)/((x1 - x0) || 1)*pw, Y = v => mt + ph - (v - y0)/(y1 - y0)*ph;
  ctx.strokeStyle = est.line; ctx.lineWidth = 1; ctx.strokeRect(ml + .5, mt + .5, pw, ph);
  ctx.fillStyle = est.muted; ctx.font = "11px system-ui,sans-serif";
  const py = passoEixo(y1 - y0), dy = casas(py); ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let v = Math.ceil(y0/py)*py; v <= y1; v += py){ ctx.fillRect(ml - 4, Y(v), 4, 1); ctx.fillText(decimal(v.toFixed(dy)), ml - 6, Y(v)); }
  const px = passoEixo(x1 - x0), dx = casas(px); ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let v = Math.ceil(x0/px)*px; v <= x1 + 1e-9; v += px){ ctx.fillRect(X(v), mt + ph, 1, 4); ctx.fillText(decimal(v.toFixed(dx)), X(v), mt + ph + 6); }
  ctx.fillText(D.tempos ? T("eixoT") : T("eixoQ"), ml + pw/2, mt + ph + 20);
  ctx.save(); ctx.translate(12, mt + ph/2); ctx.rotate(-Math.PI/2); ctx.textBaseline = "middle"; ctx.fillText(T("extEixoY"), 0, 0); ctx.restore();
  ctx.strokeStyle = est.muted; ctx.globalAlpha = .4; ctx.beginPath(); ctx.moveTo(ml, Y(0)); ctx.lineTo(ml + pw, Y(0)); ctx.stroke(); ctx.globalAlpha = 1;
  ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#2a6fdb"; ctx.lineWidth = 2; ctx.beginPath();
  let novo = true; ys.forEach((v, i) => { if (!isFinite(v)){ novo = true; return; } if (novo){ ctx.moveTo(X(xs[i]), Y(v)); novo = false; } else ctx.lineTo(X(xs[i]), Y(v)); }); ctx.stroke();
  if (isFinite(ys[t])){ ctx.fillStyle = "#d33"; ctx.beginPath(); ctx.arc(X(xs[t]), Y(ys[t]), 4, 0, 7); ctx.fill(); }
}
function csvExt(){
  if (!EXT.serie) return;
  const sep = ",", linhas = [["frame", "file", "time_s", `L_${D.u_eixo}`, "eng_strain_pct", "true_strain_pct"].join(sep)];
  EXT.serie.forEach((e, i) => linhas.push([i, D.arquivos[i], D.tempos ? D.tempos[i] : "", isFinite(e) ? ((1 + e)*EXT.L0*FE).toFixed(6) : "",
    isFinite(e) ? (100*e).toFixed(5) : "", isFinite(e) ? (100*Math.log1p(e)).toFixed(5) : ""].join(sep)));
  const cab = `# Moby-DIC digital extensometer · ${D.amostra} · A = (${(EXT.A[0]*FE).toFixed(4)}, ${(EXT.A[1]*FE).toFixed(4)}) ${D.u_eixo}, B = (${(EXT.B[0]*FE).toFixed(4)}, ${(EXT.B[1]*FE).toFixed(4)}) ${D.u_eixo} in the initial frame (origin lower-left) · measure: ${EXT.comp}`;
  baixar(new Blob([cab + "\n" + linhas.join("\n") + "\n"], {type: "text/csv"}), `${nomeBase()}_extensometer.csv`);
}

// ---------------------------------------------------------------- dados
async function descompactar(){
  const bin = Uint8Array.from(atob(BLOB), ch => ch.charCodeAt(0));
  const ds = new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"));
  const b = new Uint8Array(await new Response(ds).arrayBuffer());
  const tot = b.length/2, quadro = H*W, NA = D.armazenados.length;
  Q = new Uint16Array(tot);
  for (let c = 0; c < NA; c++){
    const acc = new Int32Array(quadro);
    for (let tt = 0; tt < N; tt++){
      const off = (c*N + tt)*quadro;
      for (let i = 0; i < quadro; i++){
        let d = (b[off+i] << 8) | b[tot+off+i]; if (d > 32767) d -= 65536;
        acc[i] += d; Q[off+i] = acc[i];
      }
    }
  }
}
function fundo(tt){
  if (!imgs[tt]){ const im = new Image(); im.src = "data:image/jpeg;base64," + FUNDOS[tt]; im.onload = () => { if (tt === t) desenhar(); }; imgs[tt] = im; }
  return imgs[tt];
}
async function fundoPronto(tt){ const im = fundo(tt); if (!im.complete || !im.naturalWidth) { try { await im.decode(); } catch(e) {} } return im; }

// ---------------------------------------------------------------- desenho (tela e exportação)
const off = document.createElement("canvas"); off.width = W; off.height = H;
const offCtx = off.getContext("2d"); const offImg = offCtx.createImageData(W, H);
function rasterCampo(k, tt, alfa){
  const s = escalaDe(k), px = offImg.data, span = (s.max - s.min) || 1;
  for (let r = 0; r < H; r++){
    const dst = (H-1-r)*W;
    for (let c = 0; c < W; c++){
      const v = valor(k, tt, r*W + c), o = (dst + c)*4;
      if (v !== v){ px[o+3] = 0; continue; }
      let u = (v - s.min)/span; u = u < 0 ? 0 : u > 1 ? 1 : u;
      const li = Math.round(u*255)*3;
      px[o] = LUT[li]; px[o+1] = LUT[li+1]; px[o+2] = LUT[li+2]; px[o+3] = alfa;
    }
  }
  offCtx.putImageData(offImg, 0, 0);
  return off;
}
// Desenha um painel completo (título opcional, mapa, eixos e barra de cores) em ctx, a partir de (x, y),
// com largura total w. Retorna a altura usada. est = {fs (escala de fonte), ink, muted, line, bg, titulo}
function desenharPainelEm(ctx, x, y, w, k, tt, est, im){
  const fs = est.fs, c = CAMPOS[k], s = escalaDe(k);
  const mt = est.titulo ? 26*fs : 6*fs, ml = 46*fs, mr = 86*fs, mb = 38*fs;
  const pw = w - ml - mr, asp = altD/largD, ph = pw*asp;
  const vw = V.x1 - V.x0, vh = V.y1 - V.y0;
  const X = x + ml, Y = y + mt;
  ctx.fillStyle = est.bg; ctx.fillRect(x, y, w, mt + ph + mb);
  if (est.titulo){ ctx.fillStyle = est.ink; ctx.font = `600 ${14*fs}px system-ui,sans-serif`; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`${nomeCampo(c)} (${unidade(c)})`, x + 4*fs, y + 4*fs, w - 8*fs); }
  // Recorte da vista nas imagens de origem (fundo e campo cobrem a região inteira).
  const fx0 = (V.x0 - D.x0_mm)/largD, fw = vw/largD, fy0 = (D.y1_mm - V.y1)/altD, fh = vh/altD;
  if (document.getElementById("fundo").checked && im && im.complete && im.naturalWidth)
    ctx.drawImage(im, fx0*im.naturalWidth, fy0*im.naturalHeight, fw*im.naturalWidth, fh*im.naturalHeight, X, Y, pw, ph);
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.drawImage(rasterCampo(k, tt, Math.round(document.getElementById("alfa").value/100*255)), fx0*W, fy0*H, fw*W, fh*H, X, Y, pw, ph);
  ctx.strokeStyle = est.line; ctx.lineWidth = fs; ctx.strokeRect(X + .5, Y + .5, pw - 1, ph - 1);
  ctx.fillStyle = est.muted; ctx.font = `${11*fs}px system-ui,sans-serif`;
  const passo = passoEixo(vw), dig = casas(passo);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let v = Math.ceil(V.x0/passo - 1e-9)*passo; v <= V.x1 + 1e-9; v += passo){
    const px = X + (v - V.x0)/vw*pw; ctx.fillRect(px, Y + ph, fs, 4*fs); ctx.fillText(decimal(v.toFixed(dig)), px, Y + ph + 6*fs); }
  ctx.fillText(`${T("eixoX")} (${D.u_eixo})`, X + pw/2, Y + ph + 20*fs);
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let v = Math.ceil(V.y0/passo - 1e-9)*passo; v <= V.y1 + 1e-9; v += passo){
    const py = Y + ph - (v - V.y0)/vh*ph; ctx.fillRect(X - 4*fs, py, 4*fs, fs); ctx.fillText(decimal(v.toFixed(dig)), X - 6*fs, py); }
  ctx.save(); ctx.translate(x + 11*fs, Y + ph/2); ctx.rotate(-Math.PI/2); ctx.textAlign = "center"; ctx.fillText(`${T("eixoY")} (${D.u_eixo})`, 0, 0); ctx.restore();
  // barra de cores
  const bx = X + pw + 12*fs, bw = 14*fs;
  for (let i = 0; i < ph; i++){ const li = Math.round((1 - i/(ph-1))*255)*3;
    ctx.fillStyle = `rgb(${LUT[li]},${LUT[li+1]},${LUT[li+2]})`; ctx.fillRect(bx, Y + i, bw, 1.5); }
  ctx.strokeStyle = est.line; ctx.strokeRect(bx + .5, Y + .5, bw - 1, ph - 1);
  ctx.fillStyle = est.muted; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.font = `${11*fs}px system-ui,sans-serif`;
  for (let j = 0; j <= 4; j++){ const v = s.max - j/4*(s.max - s.min), py = Y + j/4*(ph - 1);
    ctx.fillRect(bx + bw, py, 3*fs, fs); ctx.fillText(fmtEsc(v, s.max - s.min), bx + bw + 5*fs, py); }
  ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillText(unidade(c), bx + bw/2, Y + ph + 6*fs);
  desenharExtEm(ctx, {X, Y, pw, ph}, tt, fs);
  return {h: mt + ph + mb, X, Y, pw, ph};
}
function estiloTela(){ const cs = getComputedStyle(document.body);
  return {fs: 1, ink: cs.getPropertyValue("--ink").trim(), muted: cs.getPropertyValue("--muted").trim(),
          line: cs.getPropertyValue("--line").trim(), bg: cs.getPropertyValue("--card").trim(), titulo: false}; }

// ---------------------------------------------------------------- painéis
const paineis = [];
const padrao = ["exx", "eyy", "exy", "eeq"].map(id => IDX[id] ?? 0);
function opcoesCampos(){
  const grupos = {};
  CAMPOS.forEach((c, k) => (grupos[c.g] = grupos[c.g] || []).push(`<option value="${k}">${nomeCampo(c)} (${unidade(c)})</option>`));
  return Object.entries(grupos).map(([g, o]) => `<optgroup label="${T("grupos")[g]}">${o.join("")}</optgroup>`).join("");
}
function criarPainel(k0){
  const el = document.createElement("section");
  el.className = "painel";
  el.innerHTML = `<select class="campo"></select>
    <canvas class="mapa"></canvas>
    <div class="ctrl">
      <label class="tLim"></label><input type="range" class="lim" min="0" max="1000" step="1">
      <input type="number" class="limNum" step="any">
      <div class="lin">
        <label><input type="checkbox" class="sim"> <span class="tSim"></span></label>
        <label><span class="tMin"></span> <input type="number" class="mn" step="any"></label>
        <label><span class="tMax"></span> <input type="number" class="mx" step="any"></label>
        <button class="auto"></button>
        <button class="quadroAuto"></button>
      </div>
    </div>`;
  const p = {el, k: k0}; ["campo","mapa","lim","limNum","sim","mn","mx","auto","quadroAuto"].forEach(n => p[n] = el.querySelector("." + n));
  const aplicar = () => { atualizarControles(p); desenharPainel(p); };
  const meia = v => { const s = escalaDe(p.k);
    if (s.sim){ s.min = -v; s.max = v; } else { const c0 = (s.min + s.max)/2; s.min = c0 - v; s.max = c0 + v; } };
  p.campo.addEventListener("change", () => { p.k = +p.campo.value; aplicar(); guardar(); });
  p.lim.addEventListener("input", () => { meia(p.lim.value/1000*estatisticas(p.k).ext); aplicar(); });
  p.limNum.addEventListener("change", () => { const v = Math.abs(parseFloat(p.limNum.value.replace(",", "."))); if (!isFinite(v) || !v) return; meia(v); aplicar(); });
  p.sim.addEventListener("change", () => { const s = escalaDe(p.k); s.sim = p.sim.checked;
    if (s.sim){ const v = Math.max(Math.abs(s.min), Math.abs(s.max)); s.min = -v; s.max = v; } aplicar(); });
  p.mn.addEventListener("change", () => { const v = parseFloat(p.mn.value.replace(",", ".")), s = escalaDe(p.k); if (!isFinite(v)) return;
    s.min = v; if (s.sim) s.max = -v; if (s.max <= s.min) s.max = s.min + 1e-6; aplicar(); });
  p.mx.addEventListener("change", () => { const v = parseFloat(p.mx.value.replace(",", ".")), s = escalaDe(p.k); if (!isFinite(v)) return;
    s.max = v; if (s.sim) s.min = -v; if (s.max <= s.min) s.min = s.max - 1e-6; aplicar(); });
  p.auto.addEventListener("click", () => { escala[p.k] = null; aplicar(); });
  p.quadroAuto.addEventListener("click", () => { const s = escalaDe(p.k); let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < W*H; i++){ const v = valor(p.k, t, i); if (v === v){ if (v < lo) lo = v; if (v > hi) hi = v; } }
    if (!isFinite(lo)) return; if (s.sim){ const v = Math.max(Math.abs(lo), Math.abs(hi)); s.min = -v; s.max = v; } else { s.min = lo; s.max = hi; } aplicar(); });
  p.mapa.addEventListener("mousemove", ev => { if (arraste) return; ler(ev, p); });
  p.mapa.addEventListener("wheel", ev => { if (!p.geo) return; ev.preventDefault();
    const mm = mmDoEvento(ev, p); zoomEm(ev.deltaY < 0 ? 1.25 : 0.8, mm.x, mm.y); }, {passive: false});
  p.mapa.addEventListener("pointerdown", ev => { if (!p.geo || ev.button !== 0) return;
    if (EXT.marcando){ if (t !== 0) irPara(0); marcarExt(mmDoEvento(ev, p)); return; } p.mapa.setPointerCapture(ev.pointerId);
    arraste = {x: ev.clientX, y: ev.clientY, v: {...V}, p}; p.mapa.style.cursor = "grabbing"; });
  p.mapa.addEventListener("pointermove", ev => { if (!arraste || arraste.p !== p) return; const g = p.geo;
    const dx = (ev.clientX - arraste.x)/g.pw*(arraste.v.x1 - arraste.v.x0), dy = (ev.clientY - arraste.y)/g.ph*(arraste.v.y1 - arraste.v.y0);
    V.x0 = arraste.v.x0 - dx; V.x1 = arraste.v.x1 - dx; V.y0 = arraste.v.y0 + dy; V.y1 = arraste.v.y1 + dy; limitarVista(); desenhar(); });
  const soltar = () => { arraste = null; p.mapa.style.cursor = "crosshair"; };
  p.mapa.addEventListener("pointerup", soltar); p.mapa.addEventListener("pointercancel", soltar);
  p.mapa.addEventListener("dblclick", ajustarVista);
  p.mapa.addEventListener("mouseleave", () => { document.getElementById("leitura").textContent = T("lerCursor"); document.getElementById("dica").style.display = "none"; });
  traduzirPainel(p);
  return p;
}
let arraste = null;
function mmDoEvento(ev, p){ const r = p.mapa.getBoundingClientRect(), g = p.geo;
  const u = Math.max(0, Math.min(1, (ev.clientX - r.left - g.X)/g.pw)), v = Math.max(0, Math.min(1, 1 - (ev.clientY - r.top - g.Y)/g.ph));
  return {x: V.x0 + u*(V.x1 - V.x0), y: V.y0 + v*(V.y1 - V.y0)}; }
function traduzirPainel(p){
  p.campo.innerHTML = opcoesCampos(); p.campo.value = p.k;
  p.el.querySelector(".tLim").textContent = T("limite"); p.el.querySelector(".tSim").textContent = T("simetrico");
  p.el.querySelector(".tMin").textContent = T("min"); p.el.querySelector(".tMax").textContent = T("max");
  p.auto.textContent = T("auto"); p.auto.title = T("autoTip"); p.quadroAuto.textContent = T("quadroBtn"); p.quadroAuto.title = T("quadroTip");
  atualizarControles(p);
}
function atualizarControles(p){
  const s = escalaDe(p.k), m = (s.max - s.min)/2;
  p.lim.value = Math.round(Math.min(1, m/estatisticas(p.k).ext)*1000);
  p.sim.checked = s.sim;
  p.limNum.value = +m.toPrecision(4); p.mn.value = +s.min.toPrecision(4); p.mx.value = +s.max.toPrecision(4);
}
function montarLayout(){
  const n = +document.getElementById("layout").value, grade = document.getElementById("grade");
  grade.className = "grade l" + n;
  while (paineis.length < n) { const p = criarPainel(padrao[paineis.length] ?? 0); paineis.push(p); }
  paineis.forEach((p, i) => { if (i < n){ if (!p.el.parentNode) grade.appendChild(p.el); } else if (p.el.parentNode) p.el.remove(); });
  desenhar();
}
const visiveis = () => paineis.slice(0, +document.getElementById("layout").value);
function desenharPainel(p){
  if (!Q || !p.el.parentNode) return;
  const dpr = window.devicePixelRatio || 1, w = p.mapa.clientWidth || 500, est = estiloTela();
  const asp = (D.y1_mm - D.y0_mm)/(D.x1_mm - D.x0_mm), h = 6 + (w - 46 - 86)*asp + 38;
  p.mapa.style.height = h + "px"; p.mapa.width = Math.round(w*dpr); p.mapa.height = Math.round(h*dpr);
  const ctx = p.mapa.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  p.geo = desenharPainelEm(ctx, 0, 0, w, p.k, t, est, fundo(t));
}
function desenhar(){
  visiveis().forEach(desenharPainel);
  desenharGrafExt();
  document.getElementById("quadro").value = t; document.getElementById("quadroNum").value = t;
  document.getElementById("nomeQuadro").textContent = `${D.arquivos[t]} · ${T("quadro")} ${t}/${N-1} · ${T("estados")[D.estado[t]] || D.estado[t]}`;
  for (let k = 1; k <= 3; k++) fundo(Math.min(N-1, t + k));
  const z = largD/(V.x1 - V.x0); document.getElementById("zoomNivel").textContent = z > 1.001 ? decimal(z.toFixed(1)) + "×" : "";
}
function ler(ev, p){
  if (!p.geo) return;
  const r = p.mapa.getBoundingClientRect(), g = p.geo;
  const u = (ev.clientX - r.left - g.X)/g.pw, v = 1 - (ev.clientY - r.top - g.Y)/g.ph;
  const dica = document.getElementById("dica");
  if (u < 0 || u > 1 || v < 0 || v > 1){ dica.style.display = "none"; return; }
  const xmm = V.x0 + u*(V.x1 - V.x0), ymm = V.y0 + v*(V.y1 - V.y0);
  const cu = (xmm - D.x0_mm)/largD, cvv = (ymm - D.y0_mm)/altD;
  const i = Math.min(H-1, Math.max(0, Math.floor(cvv*H)))*W + Math.min(W-1, Math.max(0, Math.floor(cu*W)));
  const ks = [...new Set(visiveis().map(q => q.k))];
  document.getElementById("leitura").textContent = `x = ${decimal(xmm.toFixed(3))} mm, y = ${decimal(ymm.toFixed(3))} mm · ` +
    ks.map(k => `${CAMPOS[k].c} = ${fmt(valor(k, t, i))} ${unidade(CAMPOS[k])}`).join(" · ");
  const vp = valor(p.k, t, i);
  if (vp === vp){ dica.textContent = `${CAMPOS[p.k].c} = ${fmt(vp)} ${unidade(CAMPOS[p.k])}`; dica.style.display = "block";
    dica.style.left = (ev.clientX + 14) + "px"; dica.style.top = (ev.clientY - 30) + "px"; } else dica.style.display = "none";
}
function irPara(n){ t = Math.max(0, Math.min(N-1, n)); desenhar(); }
function passoPlay(){ if (t >= N-1){ if (document.getElementById("loop").checked) irPara(0); else parar(); } else irPara(t+1); }
function tocar(){ tocando = true; document.getElementById("play").textContent = T("pausa");
  timer = setInterval(passoPlay, 1000/parseFloat(document.getElementById("fps").value)); }
function parar(){ tocando = false; document.getElementById("play").textContent = T("play"); clearInterval(timer); }

// ---------------------------------------------------------------- idioma
function aplicarIdioma(){
  document.documentElement.lang = L === "pt" ? "pt-BR" : "en";
  document.querySelectorAll("[data-t]").forEach(e => e.textContent = T(e.dataset.t));
  document.querySelectorAll("[data-tt]").forEach(e => e.title = T(e.dataset.tt));
  document.getElementById("play").textContent = tocando ? T("pausa") : T("play");
  document.getElementById("titulo").textContent = `${D.amostra}`;
  document.getElementById("sub").textContent = T("sub")(D.metodo[L], D.calibrado ? decimal(String(D.escala_um_px)) + " µm/px" : T("semCal"), N, W, H, decimal(String(D.celula_px))) + ` · ${D.programa}`;
  document.getElementById("leitura").textContent = T("lerCursor") + " " + T("dicaZoom");
  const c = document.getElementById("carregando"); if (c) c.textContent = T("carregando");
  paineis.forEach(traduzirPainel);
  contarExport();
  desenhar();
}
function guardar(){ try { localStorage.setItem("dic_idioma", L); localStorage.setItem("dic_cmap", nomeCmap); } catch(e) {} }

// ---------------------------------------------------------------- exportação
const estiloExp = fs => ({fs, ink: "#111", muted: "#333", line: "#888", bg: "#fff", titulo: true});
async function renderFigura(tt, fs, comTitulo, alvo){
  const ps = visiveis(), cols = ps.length === 1 ? 1 : 2, linhas = Math.ceil(ps.length/cols);
  const wPainel = 620*fs, est = estiloExp(fs);
  const asp = (D.y1_mm - D.y0_mm)/(D.x1_mm - D.x0_mm), hPainel = 26*fs + (wPainel - 46*fs - 86*fs)*asp + 38*fs;
  const cab = comTitulo ? 44*fs : 0, gap = 10*fs;
  let w = Math.round(cols*wPainel + (cols + 1)*gap), h = Math.round(cab + linhas*hPainel + (linhas + 1)*gap);
  w += w % 2; h += h % 2;                                   // dimensões pares (exigência do H.264)
  const cv = alvo || document.createElement("canvas");
  if (cv.width !== w || cv.height !== h){ cv.width = w; cv.height = h; }
  const ctx = cv.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);
  if (comTitulo){
    ctx.fillStyle = "#111"; ctx.font = `600 ${17*fs}px system-ui,sans-serif`; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`${D.amostra}`, gap, gap);
    ctx.fillStyle = "#444"; ctx.font = `${12*fs}px system-ui,sans-serif`;
    ctx.fillText(`${D.arquivos[tt]} · ${T("quadro")} ${tt}/${N-1} · ${T("deformada")} · ${D.calibrado ? decimal(String(D.escala_um_px)) + " µm/px" : T("semCal")} · ${D.programa}`, gap, gap + 22*fs);
  }
  const im = await fundoPronto(tt);
  ps.forEach((p, j) => { const cx = gap + (j % cols)*(wPainel + gap), cy = cab + gap + Math.floor(j/cols)*(hPainel + gap);
    desenharPainelEm(ctx, cx, cy, wPainel, p.k, tt, est, im); });
  return cv;
}
const nomeBase = () => `${D.pasta}`.replace(/[^\w.-]+/g, "_");
function baixar(blob, nome){ const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = nome;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000); }
const paraBlob = (cv, tipo, q) => new Promise(r => cv.toBlob(r, tipo, q));
function intervalo(a, b, s){ a = Math.max(0, Math.min(N-1, a|0)); b = Math.max(0, Math.min(N-1, b|0)); s = Math.max(1, s|0);
  if (b < a) [a, b] = [b, a]; const r = []; for (let i = a; i <= b; i += s) r.push(i); return r; }
let cancelar = false;
function progresso(i, n){ const pr = document.getElementById("progresso"); pr.hidden = false; pr.max = n; pr.value = i;
  document.getElementById("status").textContent = T("gerando")(i, n); document.getElementById("btnCancelar").hidden = false; }
function fim(msg){ document.getElementById("progresso").hidden = true; document.getElementById("btnCancelar").hidden = true;
  document.getElementById("status").textContent = msg; ["btnFigura","btnZip","btnVideo"].forEach(id => document.getElementById(id).disabled = false); }
function ocupar(){ cancelar = false; ["btnFigura","btnZip","btnVideo"].forEach(id => document.getElementById(id).disabled = true); }

// ZIP sem compressão (as imagens já são comprimidas)
const CRC = (() => { const tb = new Uint32Array(256); for (let n = 0; n < 256; n++){ let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; tb[n] = c >>> 0; } return tb; })();
function crc32(u8){ let c = 0xFFFFFFFF; for (let i = 0; i < u8.length; i++) c = CRC[(c ^ u8[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
function zip(arquivos){
  const partes = [], central = []; let offset = 0; const enc = new TextEncoder();
  for (const {nome, dados} of arquivos){
    const nb = enc.encode(nome), crc = crc32(dados), lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true); lh.setUint16(8, 0, true);
    lh.setUint32(14, crc, true); lh.setUint32(18, dados.length, true); lh.setUint32(22, dados.length, true); lh.setUint16(26, nb.length, true);
    partes.push(lh.buffer, nb, dados);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true);
    ch.setUint32(16, crc, true); ch.setUint32(20, dados.length, true); ch.setUint32(24, dados.length, true); ch.setUint16(28, nb.length, true);
    ch.setUint32(42, offset, true); central.push(ch.buffer, nb);
    offset += 30 + nb.length + dados.length;
  }
  const tam = central.reduce((s, b) => s + (b.byteLength ?? b.length), 0), e = new DataView(new ArrayBuffer(22));
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, arquivos.length, true); e.setUint16(10, arquivos.length, true);
  e.setUint32(12, tam, true); e.setUint32(16, offset, true);
  return new Blob([...partes, ...central, e.buffer], {type: "application/zip"});
}
async function exportarFigura(){
  ocupar(); const cv = await renderFigura(t, +document.getElementById("escalaExp").value, document.getElementById("expTitulo").checked);
  baixar(await paraBlob(cv, "image/png"), `${nomeBase()}_${T("quadro")}${String(t).padStart(4, "0")}.png`); fim(T("pronto"));
}
async function exportarZip(){
  const lista = intervalo(+document.getElementById("qIni").value, +document.getElementById("qFim").value, +document.getElementById("qPasso").value);
  const fmtI = document.getElementById("formatoImg").value, fs = +document.getElementById("escalaExp").value, tit = document.getElementById("expTitulo").checked;
  ocupar(); const arq = [], cv = document.createElement("canvas");
  for (let j = 0; j < lista.length; j++){
    if (cancelar) return fim(T("cancelado"));
    progresso(j + 1, lista.length);
    await renderFigura(lista[j], fs, tit, cv);
    const b = await paraBlob(cv, "image/" + fmtI, 0.92);
    arq.push({nome: `${nomeBase()}_${T("quadro")}${String(lista[j]).padStart(4, "0")}.${fmtI === "jpeg" ? "jpg" : "png"}`, dados: new Uint8Array(await b.arrayBuffer())});
  }
  baixar(zip(arq), `${nomeBase()}_${T("quadro")}s_${lista[0]}-${lista[lista.length-1]}.zip`); fim(T("pronto"));
}
const TIPOS_VIDEO = [["video/mp4;codecs=avc1.640028", "MP4 (H.264)", "mp4"], ["video/mp4", "MP4", "mp4"],
                     ["video/webm;codecs=vp9", "WebM (VP9)", "webm"], ["video/webm;codecs=vp8", "WebM (VP8)", "webm"], ["video/webm", "WebM", "webm"]];
function tiposVideo(){ if (typeof MediaRecorder === "undefined") return [];
  const vistos = new Set(); return TIPOS_VIDEO.filter(([m, , ext]) => { if (!MediaRecorder.isTypeSupported(m)) return false;
    const chave = ext + (m.includes("codecs") ? m : ""); if (vistos.has(ext) && !m.includes("codecs")) return false; vistos.add(ext); return true; }); }
async function exportarVideo(){
  const tipos = tiposVideo(); if (!tipos.length) return fim(T("semVideo"));
  const mime = document.getElementById("formatoVid").value, ext = mime.includes("mp4") ? "mp4" : "webm";
  const lista = intervalo(+document.getElementById("aIni").value, +document.getElementById("aFim").value, +document.getElementById("aPasso").value);
  const fps = Math.max(1, Math.min(60, +document.getElementById("aFps").value || 10)), fs = +document.getElementById("escalaExp").value;
  const tit = document.getElementById("expTitulo").checked;
  ocupar(); const cv = document.createElement("canvas");
  await renderFigura(lista[0], fs, tit, cv);
  const stream = cv.captureStream(0), trilha = stream.getVideoTracks()[0];
  const rec = new MediaRecorder(stream, {mimeType: mime, videoBitsPerSecond: Math.round(cv.width*cv.height*fps*0.15)});
  const pedacos = []; rec.ondataavailable = e => { if (e.data.size) pedacos.push(e.data); };
  const parou = new Promise(r => rec.onstop = r);
  rec.start();
  const espera = ms => new Promise(r => setTimeout(r, ms));
  for (let j = 0; j < lista.length; j++){
    if (cancelar) break;
    progresso(j + 1, lista.length);
    const t0 = performance.now();
    await renderFigura(lista[j], fs, tit, cv);
    if (trilha.requestFrame) trilha.requestFrame();
    await espera(Math.max(0, 1000/fps - (performance.now() - t0)));
  }
  await espera(1000/fps);
  rec.stop(); await parou;
  if (cancelar) return fim(T("cancelado"));
  baixar(new Blob(pedacos, {type: mime.split(";")[0]}), `${nomeBase()}_${lista[0]}-${lista[lista.length-1]}_${fps}fps.${ext}`); fim(T("pronto"));
}
function contarExport(){
  const q = intervalo(+document.getElementById("qIni").value, +document.getElementById("qFim").value, +document.getElementById("qPasso").value);
  const a = intervalo(+document.getElementById("aIni").value, +document.getElementById("aFim").value, +document.getElementById("aPasso").value);
  const fps = Math.max(1, +document.getElementById("aFps").value || 10);
  document.getElementById("contaQuadros").textContent = T("nQuadros")(q.length);
  document.getElementById("contaAnim").textContent = `${T("nQuadros")(a.length)} · ${decimal((a.length/fps).toFixed(1))} s`;
}

// ---------------------------------------------------------------- início
(async function(){
  try { const c = localStorage.getItem("dic_cmap"); if (c && D.luts[c]) nomeCmap = c; } catch(e) {}
  const selC = document.getElementById("cmap");
  selC.innerHTML = D.cmaps.map(c => `<option value="${c}">${c === "whitejet" ? "white-jet" : c}</option>`).join(""); selC.value = nomeCmap;
  atualizarLUT();
  selC.onchange = () => { nomeCmap = selC.value; atualizarLUT(); guardar(); desenhar(); };
  document.getElementById("inverter").onchange = e => { invertido = e.target.checked; atualizarLUT(); desenhar(); };
  const selI = document.getElementById("idioma"); selI.value = L;
  selI.onchange = () => { L = selI.value; guardar(); aplicarIdioma(); };
  const q = document.getElementById("quadro"), qn = document.getElementById("quadroNum");
  q.max = N-1; qn.max = N-1;
  q.addEventListener("input", () => irPara(+q.value));
  qn.addEventListener("change", () => irPara(+qn.value));
  document.getElementById("ant").onclick = () => { parar(); irPara(t-1); };
  document.getElementById("prox").onclick = () => { parar(); irPara(t+1); };
  document.getElementById("play").onclick = () => tocando ? parar() : tocar();
  document.getElementById("fps").onchange = () => { if (tocando){ parar(); tocar(); } };
  document.getElementById("alfa").oninput = desenhar;
  document.getElementById("fundo").onchange = desenhar;
  document.getElementById("layout").onchange = montarLayout;
  document.getElementById("zoomMais").onclick = () => zoomEm(1.5);
  document.getElementById("zoomMenos").onclick = () => zoomEm(1/1.5);
  document.getElementById("zoomReset").onclick = ajustarVista;
  ["qIni","qFim","aIni","aFim"].forEach((id, j) => { const e = document.getElementById(id); e.max = N-1; e.value = j % 2 ? N-1 : 0; });
  ["qIni","qFim","qPasso","aIni","aFim","aPasso","aFps"].forEach(id => document.getElementById(id).addEventListener("input", contarExport));
  const tv = tiposVideo(), sv = document.getElementById("formatoVid");
  sv.innerHTML = tv.length ? tv.map(([m, n]) => `<option value="${m}">${n}</option>`).join("") : `<option value="">—</option>`;
  document.getElementById("btnFigura").onclick = exportarFigura;
  document.getElementById("btnZip").onclick = exportarZip;
  document.getElementById("btnVideo").onclick = exportarVideo;
  document.getElementById("btnCancelar").onclick = () => { cancelar = true; };
  document.getElementById("extAuto").onclick = sugerirExt;
  document.getElementById("extMarcar").onclick = () => { parar(); EXT.marcando = 1; irPara(0); };
  document.getElementById("extLimpar").onclick = () => { EXT.A = EXT.B = EXT.serie = null; EXT.marcando = 0; desenhar(); };
  document.getElementById("extCSV").onclick = csvExt;
  document.getElementById("extComp").onchange = e => { EXT.comp = e.target.value; calcularExt(); desenhar(); };
  document.addEventListener("keydown", ev => {
    if (["INPUT","SELECT"].includes(ev.target.tagName) && ev.target.type !== "range" && ev.target.type !== "checkbox") return;
    if (ev.key === " "){ ev.preventDefault(); tocando ? parar() : tocar(); }
    else if (ev.key === "ArrowRight"){ ev.preventDefault(); parar(); irPara(t+1); }
    else if (ev.key === "ArrowLeft"){ ev.preventDefault(); parar(); irPara(t-1); }
    else if (ev.key === "Home"){ parar(); irPara(0); } else if (ev.key === "End"){ parar(); irPara(N-1); }
    else if (ev.key === "+" || ev.key === "="){ zoomEm(1.5); } else if (ev.key === "-"){ zoomEm(1/1.5); } else if (ev.key === "0"){ ajustarVista(); }
  });
  aplicarIdioma();
  try { await descompactar(); await descompactarTrilhas(); sugerirExt(); }
  catch(e){ document.getElementById("carregando").textContent = T("falha") + e; return; }
  document.getElementById("carregando").remove();
  montarLayout();
  new ResizeObserver(() => desenhar()).observe(document.getElementById("grade"));
  irPara(N-1);
})();
</script>
</body>
</html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="Moby-DIC viewer", description=tx(__doc__, "Moby-DIC · builds the self-contained interactive viewer (visualizador.html) of a result folder."),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pastas", type=Path, nargs="+", metavar="RESULT_FOLDER")
    ap.add_argument("--cell", "--celula", metavar="CELL", dest="celula", type=float, default=6.0, help=tx("Tamanho da célula da grade de exibição (px).", "Display grid cell size (px)."))
    ap.add_argument("--background-width", "--largura-fundo", metavar="BACKGROUND_WIDTH", dest="largura_fundo", type=int, default=640, help=tx("Largura da imagem de fundo (px).", "Background image width (px)."))
    ap.add_argument("--until-frame", "--ate-quadro", metavar="UNTIL_FRAME", dest="ate_quadro", type=int, help=tx("Último quadro incluído (desconsidera os seguintes).", "Last frame included (later frames are ignored)."))
    ap.add_argument("--cmap", choices=COLORMAPS, default="jet", help=tx("Colormap inicial (pode ser trocado na página).", "Initial colormap (can be changed on the page)."))
    ap.add_argument("--lang", "--idioma", dest="idioma", choices=["pt", "en"], default=idioma(), help=tx("Idioma inicial (pode ser trocado na página).", "Initial language (can be changed on the page)."))
    ap.add_argument("--quality", "--qualidade", metavar="QUALITY", dest="qualidade", type=int, default=65, help=tx("Qualidade JPEG do fundo.", "JPEG quality of the background."))
    args = ap.parse_args(argv)
    for pasta in args.pastas:
        destino, mb = gerar(pasta, args.celula, args.largura_fundo, args.qualidade, args.ate_quadro,
                            args.cmap, args.idioma)
        print(f"{destino} ({mb:.1f} MB)")


if __name__ == "__main__":
    main()
