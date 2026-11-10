"""Moby-DIC · vídeo do ensaio: metadados, recomendação automática do trecho e extração de quadros.

    moby-dic video ARQUIVO                         mostra a recomendação automática
    moby-dic video ARQUIVO --output PASTA [--start S --end S --frames N]   extrai os quadros

Recomendação automática
-----------------------
A sequência é amostrada em ~60 instantes. Entre instantes consecutivos mede-se o movimento da
região que mais se move: a imagem é dividida em 4 × 4 blocos, o deslocamento de cada bloco é
medido por correlação de fase e toma-se o percentil 90 das magnitudes (px na resolução original).

- Início: primeiro intervalo com movimento acima do ruído (limiar = max(0,3 px, mediana + 4·MAD
  dos intervalos mais calmos)), refinado com amostragem densa em volta.
- Fim: último intervalo com movimento; se esse intervalo tem um salto muito maior que o resto
  (ruptura: as metades se soltam), o fim é o instante anterior a ele. Também refinado.
- Número de quadros: um quadro a cada ~5 px de movimento acumulado da região mais rápida,
  entre 40 e 300 e no máximo o número de quadros do vídeo no trecho.

Os quadros são gravados em PNG (8 bits, tons de cinza) com ``frames.csv`` (tempo de cada quadro no
vídeo) e ``video_source.json``. Vídeo comprimido com perdas (H.264 etc.) reduz a precisão do DIC.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np

from .i18n import t as tx

EXTENSOES_VIDEO = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".webm", ".mts", ".m2ts"}
PX_POR_QUADRO = 5.0
N_MIN, N_MAX = 40, 300


def _cv2():
    import cv2
    return cv2


def _caminho_para_opencv(caminho):
    """O backend FFmpeg do OpenCV não abre caminhos com acentos no Windows: usa o nome curto 8.3."""
    caminho = str(Path(caminho).resolve())
    if os.name == "nt" and not caminho.isascii():
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(caminho, buf, len(buf)):
            return buf.value
    return caminho


def abrir(caminho):
    cv2 = _cv2()
    alvo = _caminho_para_opencv(caminho)
    for api in (cv2.CAP_FFMPEG, cv2.CAP_MSMF, cv2.CAP_ANY):
        cap = cv2.VideoCapture(alvo, api)
        if cap.isOpened():
            return cap
        cap.release()
    raise ValueError(tx(f"Não foi possível abrir o vídeo: {caminho}", f"Could not open the video: {caminho}"))


def informacoes(caminho):
    cv2 = _cv2()
    cap = abrir(caminho)
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
        n = int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        codec = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join(chr((codec >> 8 * k) & 0xFF) for k in range(4)).strip("\x00 ") if codec > 0 else ""
        if fps <= 0 or fps > 10000:
            fps = 30.0
        if n <= 0:  # alguns contêineres não informam: conta lendo
            n = 0
            while cap.grab():
                n += 1
    finally:
        cap.release()
    return {"arquivo": str(Path(caminho).resolve()), "nome": Path(caminho).name, "fps": fps, "n_quadros": n,
            "duracao_s": n / fps, "largura": w, "altura": h, "codec": codec,
            "tamanho_mb": round(Path(caminho).stat().st_size / 1e6, 1)}


def _ler(cap, indice, largura=None):
    """Quadro ``indice`` em tons de cinza (uint8), opcionalmente reduzido para ``largura`` px."""
    cv2 = _cv2()
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(indice))
    ok, img = cap.read()
    if not ok:
        return None
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if largura and g.shape[1] > largura:
        g = cv2.resize(g, (largura, round(g.shape[0] * largura / g.shape[1])), interpolation=cv2.INTER_AREA)
    return g


def _movimento(a, b, escala):
    """Percentil 90 do deslocamento (px na resolução original) de 4 × 4 blocos entre a e b."""
    cv2 = _cv2()
    h, w = a.shape
    by, bx = h // 4, w // 4
    jan = cv2.createHanningWindow((bx, by), cv2.CV_32F)
    mags = []
    for i in range(4):
        for j in range(4):
            pa = a[i * by:(i + 1) * by, j * bx:(j + 1) * bx].astype(np.float32)
            pb = b[i * by:(i + 1) * by, j * bx:(j + 1) * bx].astype(np.float32)
            if pa.std() < 2 and pb.std() < 2:     # bloco sem textura (fundo liso)
                continue
            (dx, dy), _ = cv2.phaseCorrelate(pa, pb, jan)
            mags.append(np.hypot(dx, dy))
    if not mags:
        return 0.0
    return float(np.percentile(mags, 90)) * escala


def _curva(cap, indices, largura):
    quadros, ok_idx = [], []
    for k in indices:
        g = _ler(cap, k, largura)
        if g is not None:
            quadros.append(g)
            ok_idx.append(int(k))
    return ok_idx, quadros


def sugerir(caminho, amostras=60, largura=480):
    """Metadados + trecho e número de quadros recomendados (ver o docstring do módulo)."""
    info = informacoes(caminho)
    n, fps = info["n_quadros"], info["fps"]
    if n < 2:
        raise ValueError(tx("O vídeo tem menos de dois quadros.", "The video has fewer than two frames."))
    escala = info["largura"] / min(largura, info["largura"])
    cap = abrir(caminho)
    try:
        idx, qs = _curva(cap, np.unique(np.linspace(0, n - 1, min(amostras, n)).round().astype(int)), largura)
        mov = np.array([_movimento(qs[k], qs[k + 1], escala) for k in range(len(qs) - 1)])
        calmos = np.sort(mov)[: max(3, len(mov) // 3)]
        mad = np.median(np.abs(calmos - np.median(calmos)))
        limiar = max(0.3, float(np.median(calmos) + 4 * 1.4826 * mad))
        ativos = np.nonzero(mov > limiar)[0]
        ruptura, k_ruptura = False, None
        if ativos.size == 0:
            k_ini, k_fim, motivo = 0, len(idx) - 1, "sem_movimento"
        else:
            k_ini, k_fim = int(ativos[0]), int(ativos[-1]) + 1
            motivo = "movimento"
            # ruptura: último intervalo ativo com salto muito maior que a mediana dos ativos
            if ativos.size >= 4 and mov[ativos[-1]] > 5 * np.median(mov[ativos[:-1]]):
                k_fim, ruptura, k_ruptura = int(ativos[-1]), True, int(ativos[-1])

        def refinar(a, b, procurar_primeiro):
            """Amostra densa entre os índices de quadro a e b; devolve o quadro da transição."""
            if b - a < 3:
                return a if procurar_primeiro else b
            ii, qq = _curva(cap, np.unique(np.linspace(a, b, min(24, b - a + 1)).round().astype(int)), largura)
            m = np.array([_movimento(qq[k], qq[k + 1], escala) for k in range(len(qq) - 1)])
            passo = (b - a) / max(1, len(ii) - 1)
            lim = limiar * passo / ((n - 1) / max(1, len(idx) - 1))   # limiar proporcional ao intervalo
            at = np.nonzero(m > max(lim, 0.15))[0]
            if at.size == 0:
                return a if procurar_primeiro else b
            return ii[at[0]] if procurar_primeiro else ii[at[-1] + 1]

        q_ini = idx[k_ini] if k_ini == 0 or motivo != "movimento" else refinar(idx[k_ini - 1] if k_ini > 0 else 0, idx[k_ini + 1], True)
        if motivo != "movimento":
            q_fim = idx[k_fim]
        elif ruptura:
            # o fim fica antes do salto da ruptura: procura o último quadro estável antes dele
            ii, qq = _curva(cap, np.unique(np.linspace(idx[k_fim], idx[k_fim + 1], min(24, idx[k_fim + 1] - idx[k_fim] + 1)).round().astype(int)), largura)
            m = np.array([_movimento(qq[k], qq[k + 1], escala) for k in range(len(qq) - 1)])
            q_fim = ii[int(np.argmax(m))] if len(m) else idx[k_fim]
        else:
            q_fim = refinar(idx[k_fim - 1], idx[min(k_fim + 1, len(idx) - 1)], False)
        q_ini, q_fim = int(max(0, q_ini)), int(min(n - 1, max(q_fim, q_ini + 1)))
        movimento_total = float(mov[k_ini:max(k_ini + 1, k_fim)].sum()) if motivo == "movimento" else 0.0
        if ruptura:
            movimento_total = float(mov[k_ini:k_fim].sum())
    finally:
        cap.release()
    disponiveis = q_fim - q_ini + 1
    n_rec = int(np.clip(round(movimento_total / PX_POR_QUADRO) + 1, N_MIN, N_MAX))
    n_rec = int(min(n_rec, disponiveis))
    tempos = [i / fps for i in idx]
    return {**info, "inicio_s": q_ini / fps, "fim_s": q_fim / fps, "n_extrair": n_rec,
            "quadros_disponiveis": disponiveis, "movimento_total_px": round(movimento_total, 1),
            "limiar_px": round(limiar, 2), "ruptura": ruptura, "motivo": motivo,
            "curva": {"t": [(tempos[k] + tempos[k + 1]) / 2 for k in range(len(mov))],
                      "t0": tempos[:-1], "t1": tempos[1:], "mov_px": [round(float(v), 3) for v in mov],
                      "k_ruptura": k_ruptura},
            "px_por_quadro": PX_POR_QUADRO, "n_min": N_MIN, "n_max": N_MAX}


def indices_extracao(fps, n_total, inicio_s, fim_s, n):
    a = int(round(max(0.0, inicio_s) * fps))
    b = int(round(min(fim_s * fps, n_total - 1)))
    if b <= a:
        raise ValueError(tx("O tempo final precisa ser maior que o inicial.", "The end time must be after the start time."))
    n = int(max(2, min(n, b - a + 1)))
    return np.unique(np.linspace(a, b, n).round().astype(int))


def quadro_jpeg(caminho, t_s, largura=900):
    cv2 = _cv2()
    info = informacoes(caminho)
    cap = abrir(caminho)
    try:
        g = _ler(cap, min(info["n_quadros"] - 1, max(0, round(t_s * info["fps"]))), largura)
    finally:
        cap.release()
    if g is None:
        raise ValueError("frame")
    return cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def extrair(caminho, inicio_s, fim_s, n, destino, progresso=None, cancelar=None):
    """Grava os quadros escolhidos em ``destino`` (PNG 8 bits, cinza). Devolve a pasta."""
    cv2 = _cv2()
    info = informacoes(caminho)
    alvo = indices_extracao(info["fps"], info["n_quadros"], inicio_s, fim_s, n)
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=False)
    cap = abrir(caminho)
    linhas = []
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(alvo[0]))
        atual = int(round(cap.get(cv2.CAP_PROP_POS_FRAMES)))
        if atual != alvo[0]:                    # seek impreciso: decodifica desde o início
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            atual = 0
        pendentes = list(alvo)
        while pendentes:
            if cancelar and cancelar():
                raise InterruptedError
            if not cap.grab():
                break
            if atual == pendentes[0]:
                ok, img = cap.retrieve()
                if ok:
                    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
                    nome = f"frame_{len(linhas) + 1:04d}.png"
                    ok_w, buf = cv2.imencode(".png", g)
                    (destino / nome).write_bytes(buf.tobytes())   # imwrite não aceita acentos no caminho
                    linhas.append((len(linhas) + 1, nome, atual, atual / info["fps"]))
                    if progresso:
                        progresso(len(linhas), len(alvo))
                pendentes.pop(0)
            atual += 1
    finally:
        cap.release()
    if len(linhas) < 2:
        raise ValueError(tx("Não foi possível ler os quadros do vídeo.", "Could not read the video frames."))
    with (destino / "frames.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["indice", "arquivo", "quadro_video", "tempo_s"])
        w.writerows((i, a, q, f"{t:.4f}") for i, a, q, t in linhas)
    (destino / "video_source.json").write_text(json.dumps(
        {"video": info["arquivo"], "fps": info["fps"], "inicio_s": inicio_s, "fim_s": fim_s, "quadros_pedidos": int(n),
         "quadros_extraidos": len(linhas), "intervalo_s": (linhas[-1][3] - linhas[0][3]) / max(1, len(linhas) - 1),
         "largura": info["largura"], "altura": info["altura"], "codec": info["codec"]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return destino


def pasta_livre(base, nome):
    p = Path(base) / nome
    k = 2
    while p.exists():
        p = Path(base) / f"{nome}_{k}"
        k += 1
    return p


def main(argv=None):
    from . import pasta_trabalho_padrao
    ap = argparse.ArgumentParser(prog="moby-dic video", description=tx(
        "Recomenda o trecho do ensaio num vídeo e extrai os quadros para o DIC.",
        "Recommends the test interval of a video and extracts the frames for DIC."))
    ap.add_argument("video", type=Path)
    ap.add_argument("--output", "--saida", dest="saida", type=Path, metavar="FOLDER",
                    help=tx("Pasta dos quadros (sem ela, só mostra a recomendação).",
                            "Frame folder (without it, only shows the recommendation)."))
    ap.add_argument("--start", "--inicio", dest="inicio", type=float, metavar="S", help=tx("Tempo inicial (s).", "Start time (s)."))
    ap.add_argument("--end", "--fim", dest="fim", type=float, metavar="S", help=tx("Tempo final (s).", "End time (s)."))
    ap.add_argument("--frames", "--quadros", dest="quadros", type=int, metavar="N", help=tx("Número de quadros.", "Number of frames."))
    a = ap.parse_args(argv)
    s = sugerir(a.video)
    ini = a.inicio if a.inicio is not None else s["inicio_s"]
    fim = a.fim if a.fim is not None else s["fim_s"]
    n = a.quadros or s["n_extrair"]
    print(tx(f"{s['nome']}: {s['largura']}×{s['altura']} px, {s['fps']:.3g} q/s, {s['duracao_s']:.1f} s",
             f"{s['nome']}: {s['largura']}×{s['altura']} px, {s['fps']:.3g} fps, {s['duracao_s']:.1f} s"))
    print(tx(f"Recomendado: {s['inicio_s']:.2f} s a {s['fim_s']:.2f} s, {s['n_extrair']} quadros "
             f"(movimento {s['movimento_total_px']} px{', ruptura detectada' if s['ruptura'] else ''})",
             f"Recommended: {s['inicio_s']:.2f} s to {s['fim_s']:.2f} s, {s['n_extrair']} frames "
             f"(motion {s['movimento_total_px']} px{', fracture detected' if s['ruptura'] else ''})"))
    if a.saida:
        p = extrair(a.video, ini, fim, n, a.saida, progresso=lambda i, tot: print(f"\r{i}/{tot}", end="", flush=True))
        print("\n" + str(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
