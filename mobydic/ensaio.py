"""Moby-DIC · correlação da análise de imagens com a curva do ensaio de tração.

    moby-dic tensile RESULTADO --curve ENSAIO.csv --fps 5            sincroniza pela fratura (automático)
    moby-dic tensile RESULTADO --curve ENSAIO.csv --first-time -0.9  sincroniza pelo tempo do 1º quadro

Modelo de tempo
---------------
As imagens da pasta (todas, inclusive as não analisadas) são quadros de uma gravação contínua com
taxa ``fps`` informada pelo usuário. O tempo do arquivo n (1 = primeiro da pasta) no relógio da
máquina de ensaio é

    t(n) = t₀ + (n − 1)/fps

Com quadros extraídos de vídeo pelo Moby-DIC, o tempo de cada quadro no vídeo já é conhecido
(``frames.csv``) e t(n) = t_vídeo(n) + deslocamento.

Sincronização pela fratura (padrão)
-----------------------------------
- Na curva: a fratura final é a queda da carga para menos de 10 % da carga máxima sem voltar; o
  instante é o meio do trecho de queda (do último ponto ≥ 90 % da carga de 0,5 s antes ao primeiro
  ponto ≤ 10 % da máxima).
- Nas imagens: a separação da amostra produz um salto de movimento entre dois quadros
  consecutivos (recuo elástico das metades, abertura da trinca), muito maior que o movimento
  normal do ensaio e que um refoco. Mede-se, entre cada par de quadros consecutivos, o movimento
  de 4 × 4 blocos (correlação de fase, percentil 90); a fratura é o maior salto, se ele passar de
  1,5 % da largura da imagem e de 6 vezes a mediana. O instante fica entre o último quadro íntegro
  e o primeiro rompido (n_f − 0,5).
- t₀ = t_fratura − (n_f − 0,5 − 1)/fps.

Sincronização manual: o usuário informa t₀ (tempo do primeiro quadro no relógio da máquina), útil
quando a gravação termina antes da fratura.

Saídas na pasta do resultado: ``ensaio.json`` (configuração, curva reduzida e valores por quadro) e
``ensaio_por_quadro.csv`` (tempo, carga, tensão e deformações DIC de cada quadro analisado).
"""

import argparse
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .i18n import t as tx
from .imagens import listar_imagens

EXT_CURVA = (".csv", ".txt", ".dat", ".tsv", ".asc")
LARGURA_VARREDURA = 400


# ----------------------------------------------------------------------------- curva do ensaio

def _numero(s, decimal_virgula):
    s = s.strip().strip('"').strip("'")
    if decimal_virgula:
        s = s.replace(".", "").replace(",", ".") if s.count(",") == 1 and s.count(".") >= 1 else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def ler_curva(caminho):
    """Lê um arquivo de texto de máquina de ensaio (CSV/TXT, separador , ; ou tab, decimal . ou ,).

    Devolve {"colunas": [...], "dados": array [n, ncol], "sugestao": {tempo, carga, tensao, deslocamento}}."""
    bruto = Path(caminho).read_bytes()
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = bruto.decode(cod)
            break
        except UnicodeDecodeError:
            continue
    linhas = [l for l in texto.splitlines() if l.strip()]
    if len(linhas) < 3:
        raise ValueError(tx("Arquivo de ensaio vazio ou curto demais.", "Test file empty or too short."))
    # separador: o que dá o mesmo número (≥ 2) de campos na maioria das últimas linhas; ";" e tab
    # têm preferência sobre "," (que pode ser o separador decimal)
    amostra = linhas[-min(len(linhas), 60):]
    sep = None
    for cand in ("\t", ";", ","):
        cont = [l.count(cand) for l in amostra]
        moda = max(set(cont), key=cont.count)
        if moda >= 1 and cont.count(moda) >= 0.8 * len(cont):
            sep = cand
            break

    def campos(l):
        return [c.strip() for c in (l.split(sep) if sep else l.split())]

    def e_numerica(l):
        cs = campos(l)
        ok = sum(1 for c in cs if re.fullmatch(r'\s*"?[-+]?(\d+[.,]?\d*|[.,]\d+)([eE][-+]?\d+)?"?\s*|\s*"?nan"?\s*', c, re.I))
        return len(cs) >= 2 and ok >= max(2, 0.8 * len(cs))

    i0 = next((i for i, l in enumerate(linhas) if e_numerica(l)), None)
    if i0 is None:
        raise ValueError(tx("Não encontrei dados numéricos no arquivo.", "No numeric data found in the file."))
    cab = None
    for l in reversed(linhas[max(0, i0 - 5):i0]):
        cs = campos(l)
        if len(cs) >= len(campos(linhas[i0])) and not e_numerica(l):
            cab = [c.strip('"').strip("'").strip() for c in cs]
            break
    ncol = len(campos(linhas[i0]))
    if not cab or len(cab) < ncol:
        cab = [f"col{k + 1}" for k in range(ncol)]
    cab = cab[:ncol]
    amostra_dados = [l for l in linhas[i0:i0 + 200] if e_numerica(l)]
    virgula = sep in (";", "\t", None) and any("," in c for l in amostra_dados for c in campos(l))
    dados = []
    for l in linhas[i0:]:
        cs = campos(l)
        if len(cs) < ncol:
            continue
        dados.append([_numero(c, virgula) for c in cs[:ncol]])
    dados = np.array(dados, dtype=float)
    validas = [k for k in range(ncol) if np.isfinite(dados[:, k]).mean() > 0.5]

    def achar(chaves, excluir=()):
        for k in validas:
            n = cab[k].lower()
            if any(c in n for c in chaves) and not any(e in n for e in excluir):
                return k
        return None
    sug = {"tempo": achar(["time", "tempo", "(s)", "[s]", "sec"]),
           "carga": achar(["load", "força", "forca", "force", "carga", "(n)", "[n]", "(kn)", "[kn]"]),
           "tensao": achar(["stress", "tensão", "tensao", "mpa"]),
           "deslocamento": achar(["position", "posição", "posicao", "deslocamento", "extension", "displacement",
                                  "travessa", "crosshead", "(mm)"], excluir=["strain", "deforma"])}
    if sug["tempo"] is None and validas:
        sug["tempo"] = validas[0]
    if sug["carga"] is None:
        resto = [k for k in validas if k not in (sug["tempo"], sug["tensao"], sug["deslocamento"])]
        sug["carga"] = resto[0] if resto else None
    return {"arquivo": str(Path(caminho).resolve()), "colunas": cab, "validas": validas, "dados": dados, "sugestao": sug}


def escala_tempo(nome):
    """Fator para segundos a partir da unidade no nome da coluna (ms, min, h); padrão: s."""
    u = _unidade(nome, "s").strip().lower()
    return {"ms": 1e-3, "min": 60.0, "h": 3600.0}.get(u, 1.0)


def curva_validada(c, colunas):
    """Colunas escolhidas como arrays (tempo em s, crescente), sem linhas inválidas. Erro claro se não servir."""
    dados, nomes = c["dados"], c["colunas"]
    it, ic = colunas.get("tempo"), colunas.get("carga")
    ncol = dados.shape[1]
    for k in (it, ic, colunas.get("tensao"), colunas.get("deslocamento")):
        if k is not None and not (0 <= int(k) < ncol):
            raise ValueError(tx("Coluna inválida na curva do ensaio.", "Invalid column in the test curve."))
    if it is None or ic is None:
        raise ValueError(tx("Escolha as colunas de tempo e de carga.", "Choose the time and load columns."))
    tc, Fc = dados[:, it] * escala_tempo(nomes[it]), dados[:, ic]
    ok = np.isfinite(tc) & np.isfinite(Fc)
    if ok.sum() < 10:
        raise ValueError(tx("A curva tem poucos pontos válidos de tempo e carga.", "The curve has too few valid time and load points."))
    tc, Fc = tc[ok], Fc[ok]
    iS, iD = colunas.get("tensao"), colunas.get("deslocamento")
    Sc = dados[ok, iS] if iS is not None else None
    Dc = dados[ok, iD] if iD is not None else None
    if np.any(np.diff(tc) < 0):
        raise ValueError(tx("O tempo da curva não é crescente (o arquivo tem tempos reiniciados ou fora de ordem).",
                            "The curve time is not increasing (the file has reset or out-of-order times)."))
    _, unicos = np.unique(tc, return_index=True)       # tempos repetidos: fica o primeiro
    if len(unicos) < len(tc):
        tc, Fc = tc[unicos], Fc[unicos]
        Sc = Sc[unicos] if Sc is not None else None
        Dc = Dc[unicos] if Dc is not None else None
    if len(tc) < 10 or not tc[-1] > tc[0]:
        raise ValueError(tx("A curva tem poucos instantes distintos de tempo.", "The curve has too few distinct time instants."))
    return tc, Fc, Sc, Dc


def fratura_curva(t, F):
    """Instante da fratura final (queda da carga a < 10 % da máxima sem voltar). None se não houver."""
    t, F = np.asarray(t, float), np.asarray(F, float)
    ok = np.isfinite(t) & np.isfinite(F)
    t, F = t[ok], F[ok]
    if len(F) < 10:
        return None
    imax = int(np.argmax(F))
    Fmax = float(F[imax])
    baixo = F <= 0.1 * Fmax
    # primeiro ponto, depois do máximo, a partir do qual a carga não volta acima de 10 %
    j = None
    for k in range(imax + 1, len(F)):
        if baixo[k] and baixo[k:].mean() > 0.98:
            j = k
            break
    if j is None:
        return None
    dt = float(np.median(np.diff(t)))
    n0 = max(1, int(round(0.5 / max(dt, 1e-9))))
    Fpre = F[max(imax, j - n0)]
    i = j - 1
    while i > imax and F[i] < 0.9 * Fpre:
        i -= 1
    eventos = quedas(t, F)
    return {"t_s": float((t[i] + t[j]) / 2), "incerteza_s": float((t[j] - t[i]) / 2), "t_antes_s": float(t[i]),
            "t_depois_s": float(t[j]), "F_antes": float(F[i]), "Fmax": Fmax, "t_Fmax_s": float(t[imax]),
            "quedas": [e for e in eventos if e["t_s"] < t[i] - 0.25]}


def quedas(t, F, fracao=0.03, janela_s=0.5):
    """Quedas bruscas de carga (> fracao·Fmax em janela_s): rupturas parciais, escorregamentos."""
    dt = float(np.median(np.diff(t)))
    n = max(1, int(round(janela_s / max(dt, 1e-9))))
    if len(F) <= n:
        return []
    d = F[n:] - F[:-n]
    lim = -fracao * np.nanmax(F)
    ev, k = [], 0
    while k < len(d):
        if d[k] < lim:
            m = k
            while m < len(d) and d[m] < lim:
                m += 1
            p = k + int(np.argmin(d[k:m]))
            ev.append({"t_s": float((t[p] + t[p + n]) / 2), "dF": float(-d[p])})
            k = m
        else:
            k += 1
    return ev


# ----------------------------------------------------------------------------- imagens

VERSAO_VARREDURA = 2


def assinatura_pasta(pasta):
    """Identifica o conjunto de imagens (nomes, tamanhos, datas) para validar o cache da varredura."""
    import hashlib
    h = hashlib.sha1()
    for a in listar_imagens(pasta):
        st = a.stat()
        h.update(f"{a.name}|{st.st_size}|{st.st_mtime_ns};".encode("utf-8"))
    return f"v{VERSAO_VARREDURA}-" + h.hexdigest()


def _ler_reduzida(caminho):
    """Imagem reduzida (LARGURA_VARREDURA px) em float32 0–255, preservando o contraste de 8 e 16 bits."""
    import cv2
    from .imagens import ler_cinza
    try:
        a = ler_cinza(caminho, origem_inferior=False)
    except Exception:  # noqa: BLE001  (arquivo corrompido)
        return None, None
    h, w = a.shape
    lo, hi = np.percentile(a[::4, ::4], [0.5, 99.5])
    a = np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1).astype(np.float32) * 255
    pequena = cv2.resize(a, (LARGURA_VARREDURA, max(8, round(h * LARGURA_VARREDURA / w))), interpolation=cv2.INTER_AREA)
    return pequena, w


def _blocos(n):
    """(quantidade, tamanho) dos blocos numa dimensão: até 4 blocos, tamanho múltiplo de 8 (o
    phaseCorrelate do OpenCV desloca 0,5 px em blocos de tamanho ímpar); imagens pequenas: 1 bloco par."""
    q = max(1, min(4, n // 32))
    t = (n // q) // 8 * 8
    if t < 8:
        q, t = 1, max(2, n - n % 2)
    return q, t


def _movimento(a, b, escala):
    import cv2
    h, w = a.shape
    ny, by = _blocos(h)
    nx, bx = _blocos(w)
    jan = cv2.createHanningWindow((bx, by), cv2.CV_32F)
    m = []
    for i in range(ny):
        for j in range(nx):
            # cópias contíguas: o phaseCorrelate com janela não pode alterar as imagens guardadas
            pa = np.array(a[i * by:(i + 1) * by, j * bx:(j + 1) * bx], dtype=np.float32, copy=True)
            pb = np.array(b[i * by:(i + 1) * by, j * bx:(j + 1) * bx], dtype=np.float32, copy=True)
            if pa.std() < 2 and pb.std() < 2:
                continue
            (dx, dy), _ = cv2.phaseCorrelate(pa, pb, jan)
            m.append(np.hypot(dx, dy))
    return float(np.percentile(m, 90)) * escala if m else 0.0


def varrer_imagens(pasta, progresso=None, cancelar=None, threads=8, lote=64):
    """Movimento entre quadros consecutivos de TODAS as imagens da pasta (para achar a fratura).

    Lê em lotes (memória limitada a ~lote imagens reduzidas) e mede o movimento à medida que lê."""
    arqs = listar_imagens(pasta)
    if len(arqs) < 3:
        raise ValueError(tx("A pasta precisa de pelo menos três imagens.", "The folder needs at least three images."))
    largura, ruins, mov = None, [], []
    anterior = None
    with ThreadPoolExecutor(threads) as ex:
        for ini in range(0, len(arqs), lote):
            bloco = list(ex.map(_ler_reduzida, arqs[ini:ini + lote]))
            for k, (a, w) in enumerate(bloco):
                if cancelar and cancelar():
                    raise InterruptedError
                n = ini + k
                if a is None:                  # arquivo ilegível: repete o anterior (movimento zero)
                    ruins.append(arqs[n].name)
                    a = anterior
                else:
                    largura = largura or w
                if anterior is not None and a is not None:
                    mov.append(_movimento(anterior, a, (largura or w) / LARGURA_VARREDURA))
                elif n > 0:
                    mov.append(0.0)
                anterior = a if a is not None else anterior
            if progresso:
                progresso(min(len(arqs), ini + lote), len(arqs))
    if largura is None:
        raise ValueError(tx("Nenhuma imagem legível na pasta.", "No readable image in the folder."))
    return {"pasta": str(Path(pasta).resolve()), "n": len(arqs), "largura_px": largura, "movimento_px": mov,
            "ilegiveis": ruins, "arquivos": [a.name for a in arqs], "assinatura": assinatura_pasta(pasta)}


def varredura_valida(v, pasta):
    return bool(v) and v.get("assinatura") == assinatura_pasta(pasta)


def fratura_imagens(varredura):
    """Arquivo n_f (1 = primeiro) do primeiro quadro rompido, ou None. Ver o docstring do módulo."""
    mov = np.asarray(varredura["movimento_px"])
    if mov.size == 0:
        return None
    k = int(np.argmax(mov))
    lim = max(0.015 * varredura["largura_px"], 6 * float(np.median(mov)))
    if mov[k] < lim:
        return None
    return {"n_rompido": k + 2, "n_intacto": k + 1, "salto_px": float(mov[k]), "limiar_px": float(lim),
            "mediana_px": float(np.median(mov))}


def tempos_video(pasta):
    """Tempos de cada imagem no vídeo, quando a pasta foi extraída de um vídeo pelo Moby-DIC."""
    p = Path(pasta) / "frames.csv"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        return {r["arquivo"]: float(r["tempo_s"]) for r in csv.DictReader(f)}


def origem_video(pasta):
    p = Path(pasta) / "video_source.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ----------------------------------------------------------------------------- sincronização

def tempo_primeiro_quadro(fps, t_fratura, n_rompido):
    """t₀ (tempo do arquivo 1 no relógio da máquina) com a fratura entre os arquivos n_rompido−1 e n_rompido."""
    return t_fratura - (n_rompido - 1.5) / fps


def _extensometro_auto(pos, val):
    """Mesmo critério do visualizador: linha central medida em ≥ 95 % dos quadros, 25 % a 75 % da largura."""
    n, ny, nx = val.shape
    conta = val.sum(axis=0)
    melhor, rm = -1, 0
    for r in range(ny):
        s = int((conta[r] >= 0.95 * n).sum())
        nota = s * (1 - abs(r - (ny - 1) / 2) / ny)
        if nota > melhor:
            melhor, rm = nota, r
    ok = np.nonzero(conta[rm] >= 0.95 * n)[0]
    if len(ok) < 4:
        return None
    c1 = int(round(ok[0] + 0.25 * (ok[-1] - ok[0])))
    c2 = int(round(ok[0] + 0.75 * (ok[-1] - ok[0])))
    L0 = np.hypot(*(pos[0, rm, c2] - pos[0, rm, c1]))
    e = np.full(n, np.nan)
    for t in range(n):
        if val[t, rm, c1] and val[t, rm, c2]:
            e[t] = np.hypot(*(pos[t, rm, c2] - pos[t, rm, c1])) / L0 - 1
    return {"linha": rm, "colunas": [c1, c2], "L0_px": float(L0), "eps": e}


def aplicar(resultado, curva, colunas, metodo="fratura", fps=None, t_fratura=None, n_rompido=None,
            t_primeiro=None, varredura=None, escolhas=None):
    """Sincroniza o resultado com a curva e grava ensaio.json e ensaio_por_quadro.csv. Devolve o resumo."""
    resultado = Path(resultado)
    meta = json.loads((resultado / "parametros.json").read_text(encoding="utf-8"))
    pasta = Path(meta["pasta_imagens"])
    c = curva if isinstance(curva, dict) else ler_curva(curva)
    dados = c["dados"]
    it, ic = colunas["tempo"], colunas["carga"]
    iS, iD = colunas.get("tensao"), colunas.get("deslocamento")
    tc, Fc, Sc, Dc = curva_validada(c, colunas)
    frat = fratura_curva(tc, Fc)
    if t_fratura is None and frat:
        t_fratura = frat["t_s"]

    with np.load(resultado / "campos.npz") as z:
        arquivos = [str(a) for a in z["arquivos"]]
        val, pos = z["valido"], z["centro_xy_px"]
        exx, eyy = z["deformacao_xx"], z["deformacao_yy"]
    todos = [p.name for p in listar_imagens(pasta)]
    indice = {nome: k + 1 for k, nome in enumerate(todos)}
    tv = tempos_video(pasta)
    vid = origem_video(pasta)

    if tv is not None and all(a in tv for a in arquivos):
        # quadros extraídos de vídeo: tempo no vídeo conhecido, falta só o deslocamento
        base = np.array([tv[a] for a in arquivos])
        fonte = "video"
        if metodo == "fratura":
            t_video_frat = (vid or {}).get("ruptura_s")
            if t_video_frat is None or t_fratura is None:
                raise ValueError(tx("A fratura não foi encontrada no vídeo ou na curva; use a sincronização manual.",
                                    "The fracture was not found in the video or in the curve; use manual synchronisation."))
            desloc = t_fratura - t_video_frat
        else:                                   # t_primeiro = tempo do primeiro arquivo da pasta
            desloc = float(t_primeiro or 0.0) - tv.get(todos[0], base[0])
        tempos = base + desloc
        t0 = float(tv.get(todos[0], base[0]) + desloc)     # tempo do primeiro arquivo da pasta
        fps = (vid or {}).get("fps", fps)
    else:
        fonte = "fps"
        if not fps or fps <= 0:
            raise ValueError(tx("Informe a taxa de quadros (fps) da gravação.", "Enter the frame rate (fps) of the recording."))
        if metodo == "fratura":
            if n_rompido is None:
                if not varredura_valida(varredura, pasta):
                    varredura = varrer_imagens(pasta)
                fi = fratura_imagens(varredura)
                if fi is None:
                    raise ValueError(tx("A fratura não aparece nas imagens; use a sincronização manual.",
                                        "The fracture does not appear in the images; use manual synchronisation."))
                n_rompido = fi["n_rompido"]
            if t_fratura is None:
                raise ValueError(tx("Não encontrei a fratura na curva do ensaio.", "The fracture was not found in the test curve."))
            t0 = tempo_primeiro_quadro(fps, t_fratura, n_rompido)
        else:
            t0 = float(t_primeiro or 0.0)
        tempos = np.array([t0 + (indice[a] - 1) / fps for a in arquivos])

    dentro = (tempos >= tc[0]) & (tempos <= tc[-1])
    carga = np.where(dentro, np.interp(tempos, tc, Fc), np.nan)
    tensao = np.where(dentro, np.interp(tempos, tc, Sc), np.nan) if Sc is not None else None
    desl = np.where(dentro, np.interp(tempos, tc, Dc), np.nan) if Dc is not None else None
    if t_fratura is not None:                      # depois da fratura a amostra não carrega
        apos = tempos > t_fratura
        carga[apos] = np.nan
        if tensao is not None:
            tensao[apos] = np.nan
    med = lambda a, k: float(np.median(a[k][val[k]])) if val[k].any() else np.nan  # noqa: E731
    exx_m = np.array([med(exx, k) for k in range(len(arquivos))])
    eyy_m = np.array([med(eyy, k) for k in range(len(arquivos))])
    ext = _extensometro_auto(pos, val)

    # curva reduzida para os gráficos do visualizador (≤ 4000 pontos)
    passo = max(1, len(tc) // 4000)
    nomes = c["colunas"]
    resumo = {
        "programa": "Moby-DIC", "curva": {"arquivo": c["arquivo"], "colunas": {k: (nomes[v] if v is not None else None)
                                                                                for k, v in colunas.items()}},
        "metodo": metodo, "fonte_tempo": fonte, "fps": fps, "t_primeiro_s": t0, "t_primeiro_analisado_s": float(tempos[0]),
        "t_fratura_s": t_fratura, "colunas_idx": {k: (None if v is None else int(v)) for k, v in colunas.items()},
        "escolhas": escolhas or {},
        "n_rompido": n_rompido, "fratura_curva": frat,
        "unidades": {"tempo": _unidade(nomes[it], "s"), "carga": _unidade(nomes[ic], "N"),
                     "tensao": _unidade(nomes[iS], "MPa") if iS is not None else None,
                     "deslocamento": _unidade(nomes[iD], "mm") if iD is not None else None},
        "reduzida": {"t": tc[::passo].tolist(), "F": Fc[::passo].tolist(),
                     "S": Sc[::passo].tolist() if Sc is not None else None,
                     "D": Dc[::passo].tolist() if Dc is not None else None},
        "quadros": {"arquivo": arquivos, "indice_pasta": [indice.get(a) for a in arquivos], "t_s": tempos.tolist(),
                    "carga": _lista(carga), "tensao": _lista(tensao) if tensao is not None else None,
                    "deslocamento": _lista(desl) if desl is not None else None,
                    "exx_mediana": _lista(exx_m), "eyy_mediana": _lista(eyy_m),
                    "extensometro_auto": _lista(ext["eps"]) if ext else None},
        "imagens_cobrem_s": [float(tempos.min()), float(tempos.max())],
    }
    (resultado / "ensaio.json").write_text(json.dumps(resumo, ensure_ascii=False), encoding="utf-8")
    with (resultado / "ensaio_por_quadro.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        u = resumo["unidades"]
        w.writerow(["indice", "arquivo", "arquivo_n", "tempo_s", f"carga_{u['carga']}"]
                   + ([f"tensao_{u['tensao']}"] if tensao is not None else [])
                   + ([f"deslocamento_{u['deslocamento']}"] if desl is not None else [])
                   + ["exx_mediana_pct", "eyy_mediana_pct", "extensometro_auto_eng_pct"])
        for k, a in enumerate(arquivos):
            w.writerow([k, a, indice.get(a), f"{tempos[k]:.4f}", _f(carga[k])]
                       + ([_f(tensao[k])] if tensao is not None else []) + ([_f(desl[k])] if desl is not None else [])
                       + [_f(100 * exx_m[k]), _f(100 * eyy_m[k]), _f(100 * ext["eps"][k]) if ext else ""])
    return resumo


def _unidade(nome, padrao):
    m = re.search(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]", nome or "")
    return m.group(1) if m and m.group(1).strip() else padrao


def _lista(a):
    return [None if not np.isfinite(v) else float(v) for v in np.asarray(a, float)]


def _f(v):
    return "" if v is None or not np.isfinite(v) else f"{v:.6g}"


# ----------------------------------------------------------------------------- linha de comando

def main(argv=None):
    ap = argparse.ArgumentParser(prog="moby-dic tensile", description=tx(
        "Correlaciona um resultado com a curva do ensaio de tração (tempo, carga, tensão por quadro).",
        "Correlates a result with the tensile test curve (time, load and stress for every frame)."))
    ap.add_argument("resultado", type=Path, metavar="RESULT_FOLDER")
    ap.add_argument("--curve", "--curva", dest="curva", type=Path, required=True, metavar="FILE",
                    help=tx("Arquivo da máquina (CSV/TXT).", "Machine file (CSV/TXT)."))
    ap.add_argument("--fps", type=float, help=tx("Taxa de quadros da gravação.", "Frame rate of the recording."))
    ap.add_argument("--first-time", "--t-primeiro", dest="t_primeiro", type=float, metavar="S",
                    help=tx("Sincronização manual: tempo do primeiro quadro no relógio da máquina (s).",
                            "Manual synchronisation: time of the first frame on the machine clock (s)."))
    ap.add_argument("--fracture-time", dest="t_fratura", type=float, metavar="S",
                    help=tx("Tempo da fratura na curva (s); padrão: automático.", "Fracture time in the curve (s); default: automatic."))
    ap.add_argument("--fracture-frame", dest="n_rompido", type=int, metavar="N",
                    help=tx("Primeiro arquivo já rompido (1 = primeiro da pasta); padrão: automático.",
                            "First file already broken (1 = first in the folder); default: automatic."))
    for nome in ("time", "load", "stress", "position"):
        ap.add_argument(f"--{nome}-col", dest=f"col_{nome}", type=int, metavar="K",
                        help=tx(f"Coluna (1 = primeira) de {nome}; padrão: automático.", f"Column (1 = first) of {nome}; default: automatic."))
    ap.add_argument("--no-viewer", action="store_true", help=tx("Não regenera o visualizador.", "Do not rebuild the viewer."))
    a = ap.parse_args(argv)
    c = ler_curva(a.curva)
    col = dict(c["sugestao"])
    for nome, chave in (("time", "tempo"), ("load", "carga"), ("stress", "tensao"), ("position", "deslocamento")):
        if getattr(a, f"col_{nome}"):
            col[chave] = getattr(a, f"col_{nome}") - 1
    metodo = "manual" if a.t_primeiro is not None else "fratura"
    try:
        r = aplicar(a.resultado, c, col, metodo, a.fps, a.t_fratura, a.n_rompido, a.t_primeiro)
    except ValueError as e:
        print(tx("Erro: ", "Error: ") + str(e), file=sys.stderr)
        return 2
    print(tx("Colunas:", "Columns:"), {k: v for k, v in r["curva"]["colunas"].items() if v})
    if r["fratura_curva"]:
        print(tx(f"Fratura na curva: {r['fratura_curva']['t_s']:.3f} s (Fmax {r['fratura_curva']['Fmax']:.1f})",
                 f"Fracture in the curve: {r['fratura_curva']['t_s']:.3f} s (Fmax {r['fratura_curva']['Fmax']:.1f})"))
    if r["n_rompido"]:
        print(tx(f"Fratura nas imagens: entre os arquivos {r['n_rompido'] - 1} e {r['n_rompido']}",
                 f"Fracture in the images: between files {r['n_rompido'] - 1} and {r['n_rompido']}"))
    print(tx(f"Primeiro quadro em t = {r['t_primeiro_s']:.3f} s; imagens analisadas cobrem {r['imagens_cobrem_s'][0]:.2f}–{r['imagens_cobrem_s'][1]:.2f} s",
             f"First frame at t = {r['t_primeiro_s']:.3f} s; analysed images cover {r['imagens_cobrem_s'][0]:.2f}–{r['imagens_cobrem_s'][1]:.2f} s"))
    if not a.no_viewer:
        from .viewer import main as viewer
        viewer([str(a.resultado)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
