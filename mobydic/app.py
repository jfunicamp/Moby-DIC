"""Moby-DIC · aplicativo (servidor local + interface no navegador).

Fluxo: imagens → escala → ROI → método e malha → referência → saída → executar → visualizar.
O servidor atende apenas 127.0.0.1. As análises rodam como subprocessos do próprio programa.
"""

import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

from . import NOME, __version__, pasta_dados_usuario, pasta_trabalho_padrao
from . import auto as ap
from .i18n import t as tx
from .imagens import EXTENSOES, imagem_exibicao, listar_imagens, selecionar

CONGELADO = getattr(sys, "frozen", False)


def recurso(rel):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "mobydic" / rel


def pasta_docs():
    """Documentação HTML: embutida no executável ou gerada de docs/*.md no código-fonte."""
    if CONGELADO:
        return recurso("docs")
    raiz = Path(__file__).resolve().parent.parent / "docs"
    html = raiz / "html"
    fontes = list(raiz.rglob("*.md"))
    if fontes and (not (html / "index.html").exists()
                   or max(f.stat().st_mtime for f in fontes) > (html / "index.html").stat().st_mtime):
        try:
            import runpy
            runpy.run_path(str(raiz / "build_docs.py"), run_name="__main__")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    return html


def comando_base():
    """Como chamar um subcomando do Moby-DIC (executável ou código-fonte)."""
    return [sys.executable] if CONGELADO else [sys.executable, "-m", "mobydic"]


import importlib.util  # noqa: E402

TEM_MUDIC = importlib.util.find_spec("muDIC") is not None


# ----------------------------------------------------------------------------- preferências

ARQ_PREFS = pasta_dados_usuario() / "config.json"


def ler_prefs():
    padrao = {"escala_um_px": None, "ultima_pasta": str(Path.home()), "pasta_trabalho": str(pasta_trabalho_padrao()),
              "idioma": None, "resultados": []}
    try:
        return {**padrao, **json.loads(ARQ_PREFS.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return padrao


def salvar_prefs(**kw):
    p = ler_prefs()
    p.update(kw)
    ARQ_PREFS.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar_resultado(pasta):
    pasta = str(Path(pasta).resolve())
    lst = [r for r in ler_prefs()["resultados"] if r != pasta and Path(r).is_dir()]
    salvar_prefs(resultados=[pasta] + lst[:99])


def pastas_resultado_permitidas():
    prefs = ler_prefs()
    out = {Path(r).resolve() for r in prefs["resultados"] if Path(r).is_dir()}
    trab = Path(prefs["pasta_trabalho"])
    if trab.is_dir():
        out |= {d.resolve() for d in trab.iterdir() if d.is_dir() and (d / "parametros.json").exists()}
    return out


# ----------------------------------------------------------------------------- tarefa

class Tarefa:
    def __init__(self):
        self.lock = threading.Lock()
        self.estado, self.etapa, self.progresso, self.total = "parada", "", 0, 1
        self.log, self.saida, self.proc, self.cancelar = [], None, None, False

    def info(self):
        with self.lock:
            return {"estado": self.estado, "etapa": self.etapa, "progresso": self.progresso, "total": self.total,
                    "log": self.log[-400:], "saida": self.saida and str(self.saida)}

    def escrever(self, linha):
        with self.lock:
            self.log.append(linha.rstrip())
            m = re.match(r"\s*(?:quadro|frame)\s+(\d+)\s", linha) or re.search(r"Processing frame nr: (\d+)", linha)
            if m:
                self.progresso = int(m.group(1))


TAREFA = Tarefa()


def comando_analise(cfg, saida):
    s, roi, met, ref = cfg["selecao"], cfg["roi"], cfg["metodo"], cfg["referencia"]
    comum = ["--imagens", cfg["pasta"], "--saida", str(saida), "--roi", *[f"{v:.1f}" for v in roi],
             "--inicio", str(s["inicio"]), "--a-cada", str(s["a_cada"])]
    if s.get("fim"):
        comum += ["--fim", str(s["fim"])]
    if cfg.get("escala_um_px"):
        comum += ["--escala-um-px", str(cfg["escala_um_px"])]
    if met["tipo"] == "subsets":
        cmd = comando_base() + ["subsets", *comum, "--subset", str(met["subset_px"]), "--passo", str(met["passo_px"]),
                                "--janela-deformacao", str(met["janela_deformacao"]), "--zncc-min", str(ref["zncc_min"])]
        if ref["modo"] == "automatica":
            cmd += ["--passo-referencia", "0", "--zncc-ref", str(ref["zncc_ref"]),
                    "--zncc-ref-p05", str(ref["zncc_ref_p05"]), "--falha-ref", str(ref["falha_ref"])]
        elif ref["modo"] == "fixa":
            cmd += ["--passo-referencia", "100000"]
        else:
            cmd += ["--passo-referencia", str(ref["a_cada"])]
        if ref.get("igualar_nitidez"):
            cmd.append("--igualar-nitidez")
        if not ref.get("resgate", True):
            cmd.append("--sem-resgate")
        return cmd
    cmd = comando_base() + ["mudic", *comum, "--malha", "q4" if met["tipo"] == "q4" else "spline",
                            "--passo-referencia", str(ref["a_cada"] if ref["modo"] == "a_cada" else 2)]
    if met["tipo"] == "q4":
        cmd += ["--elemento-px", str(met["elemento_px"])]
    else:
        cmd += ["--pontos-controle", *[str(v) for v in met["pontos_controle"]]]
    return cmd


def rodar(cmd, rotulo, idioma=None):
    TAREFA.escrever(f"$ {rotulo}")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "OPENBLAS_NUM_THREADS": "4",
           "MOBYDIC_LANG": idioma or ler_prefs().get("idioma") or "en"}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    TAREFA.proc = p
    for linha in p.stdout:
        if " INFO " in linha and "Processing frame" not in linha:
            continue
        TAREFA.escrever(linha)
        if TAREFA.cancelar:
            p.terminate()
    p.wait()
    TAREFA.proc = None
    if TAREFA.cancelar:
        raise InterruptedError
    if p.returncode != 0:
        raise RuntimeError(f"{rotulo}: " + tx("código", "exit code") + f" {p.returncode}")


def executar(cfg, saida):
    try:
        with TAREFA.lock:
            TAREFA.estado, TAREFA.log, TAREFA.progresso, TAREFA.cancelar = "rodando", [], 0, False
            TAREFA.total, TAREFA.saida, TAREFA.etapa = max(1, cfg["n_quadros"] - 1), saida, "correlacao"
        idioma = cfg.get("pos", {}).get("idioma")
        rodar(comando_analise(cfg, saida), "DIC", idioma)
        (saida / "config_analise.json").write_text(json.dumps({**cfg, "programa": f"{NOME} {__version__}"},
                                                              ensure_ascii=False, indent=2), encoding="utf-8")
        TAREFA.etapa = "visualizador"
        meta = json.loads((saida / "parametros.json").read_text(encoding="utf-8"))
        ruins, n = set(meta.get("quadros_ruins", [])), meta.get("quadros", cfg["n_quadros"])
        ate = n - 1
        while ate > 0 and ate in ruins:
            ate -= 1
        pos = cfg.get("pos", {})
        rodar(comando_base() + ["viewer", str(saida), "--idioma", pos.get("idioma", "pt"), "--cmap", pos.get("cmap", "jet")]
              + (["--ate-quadro", str(ate)] if ate < n - 1 else []), "viewer", idioma)
        registrar_resultado(saida)
        with TAREFA.lock:
            TAREFA.estado, TAREFA.etapa = "concluida", "concluida"
        TAREFA.escrever("OK")
    except InterruptedError:
        with TAREFA.lock:
            TAREFA.estado, TAREFA.etapa = "cancelada", "cancelada"
    except Exception as e:  # noqa: BLE001
        TAREFA.escrever(traceback.format_exc())
        with TAREFA.lock:
            TAREFA.estado, TAREFA.etapa = "erro", str(e)


# ----------------------------------------------------------------------------- utilidades HTTP

def contar_videos(d):
    from .video import EXTENSOES_VIDEO
    try:
        return sum(1 for f in d.iterdir() if f.suffix.lower() in EXTENSOES_VIDEO)
    except OSError:
        return 0


class TarefaVideo:
    """Extração de quadros de um vídeo (uma por vez), acompanhada por /api/video/status."""
    def __init__(self):
        self.estado, self.feitos, self.total, self.pasta, self.erro, self.cancelar = "parada", 0, 0, None, "", False

    def info(self):
        return {"estado": self.estado, "feitos": self.feitos, "total": self.total,
                "pasta": self.pasta and str(self.pasta), "erro": self.erro}


TAREFA_VIDEO = TarefaVideo()


def extrair_video(d):
    from . import video
    tv = TAREFA_VIDEO
    try:
        base = Path(d.get("pasta_trabalho") or ler_prefs()["pasta_trabalho"]) / "videos"
        base.mkdir(parents=True, exist_ok=True)
        destino = video.pasta_livre(base, re.sub(r"[^\w.-]+", "_", Path(d["arquivo"]).stem) + "_frames")
        tv.pasta = destino
        video.extrair(d["arquivo"], float(d["inicio_s"]), float(d["fim_s"]), int(d["n"]), destino,
                      progresso=lambda i, n: setattr(tv, "feitos", i), cancelar=lambda: tv.cancelar)
        tv.estado = "concluida"
    except InterruptedError:
        tv.estado = "cancelada"
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        tv.estado, tv.erro = "erro", str(e)


def contar_imagens(d):
    try:
        return sum(1 for f in d.iterdir() if f.suffix.lower() in EXTENSOES)
    except OSError:
        return 0


def listar_pastas(caminho):
    p = Path(caminho).expanduser() if caminho else Path.home()
    if not p.is_dir():
        p = Path.home()
    pastas = []
    try:
        for d in sorted(p.iterdir(), key=lambda q: q.name.lower()):
            if d.is_dir() and not d.name.startswith((".", "$")):
                pastas.append({"nome": d.name, "caminho": str(d), "n_imagens": contar_imagens(d), "n_videos": contar_videos(d),
                               "resultado": (d / "visualizador.html").exists()})
    except OSError:
        pass
    unidades = [f"{c}:\\" for c in "CDEFGHIJ" if Path(f"{c}:\\").exists()] if os.name == "nt" else ["/"]
    atalhos = [{"nome": n, "caminho": str(c)} for n, c in (("Home", Path.home()), ("Documents", Path.home() / "Documents"),
               ("Desktop", Path.home() / "Desktop")) if c.is_dir()]
    from .video import EXTENSOES_VIDEO
    try:
        videos = [{"nome": f.name, "caminho": str(f), "mb": round(f.stat().st_size / 1e6, 1)}
                  for f in sorted(p.iterdir(), key=lambda q: q.name.lower()) if f.is_file() and f.suffix.lower() in EXTENSOES_VIDEO]
    except OSError:
        videos = []
    return {"caminho": str(p), "pai": str(p.parent) if p.parent != p else None, "pastas": pastas, "videos": videos,
            "n_imagens": contar_imagens(p), "resultado": (p / "visualizador.html").exists(),
            "unidades": unidades, "atalhos": atalhos}


def listar_resultados():
    out = []
    for d in sorted(pastas_resultado_permitidas(), key=lambda q: (q / "parametros.json").stat().st_mtime
                    if (q / "parametros.json").exists() else 0, reverse=True):
        if not (d / "visualizador.html").exists():
            continue
        try:
            meta = json.loads((d / "parametros.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        from .viewer import traduzir_metodo
        out.append({"nome": d.name, "caminho": str(d), "metodo": meta.get("metodo", ""),
                    "metodo_en": traduzir_metodo(meta.get("metodo", "")), "quadros": meta.get("quadros"),
                    "imagens": meta.get("pasta_imagens", ""), "figuras": [f.name for f in sorted(d.glob("*.png"))],
                    "data": datetime.fromtimestamp((d / "visualizador.html").stat().st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out


def imagem_jpeg(pasta, inicio, fim, a_cada, i, largura):
    sel = selecionar(listar_imagens(pasta), inicio, fim, a_cada)
    im = imagem_exibicao(sel[max(0, min(len(sel) - 1, i))])
    if largura and im.width > largura:
        im = im.resize((largura, round(im.height * largura / im.width)), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    servidor = None

    def log_message(self, *a):
        pass

    def enviar(self, corpo, tipo="application/json; charset=utf-8", codigo=200):
        if isinstance(corpo, (dict, list)):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        elif isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def corpo_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.enviar(recurso("web/app.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
            if u.path in ("/logo.svg", "/favicon.svg"):
                return self.enviar(recurso("assets/logo.svg").read_bytes(), "image/svg+xml")
            if u.path == "/api/info":
                prefs = ler_prefs()
                return self.enviar({"nome": NOME, "versao": __version__, "mudic": TEM_MUDIC, "prefs": prefs,
                                    "nucleos": os.cpu_count()})
            if u.path == "/api/pastas":
                return self.enviar(listar_pastas(q.get("caminho") or ler_prefs()["ultima_pasta"]))
            if u.path == "/api/imagem":
                dados = imagem_jpeg(q["pasta"], int(q.get("inicio", 1)), int(q["fim"]) if q.get("fim") else None,
                                    int(q.get("a_cada", 1)), int(q.get("i", 0)), int(q.get("largura", 1000)))
                return self.enviar(dados, "image/jpeg")
            if u.path == "/docs" or u.path.startswith("/docs/"):
                base = pasta_docs().resolve()
                rel = u.path[len("/docs/"):] or "index.html"
                alvo = (base / rel).resolve()
                if alvo.is_dir():
                    alvo = alvo / "index.html"
                if base not in alvo.parents or not alvo.is_file():
                    return self.enviar({"erro": "not found"}, codigo=404)
                tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
                return self.enviar(alvo.read_bytes(), tipo + ("; charset=utf-8" if tipo.startswith("text/") else ""))
            if u.path == "/tutorial.mp4":
                video = (Path(sys.executable).parent if CONGELADO else Path(__file__).resolve().parent.parent / "docs" / "video") / "Moby-DIC-tutorial.mp4"
                if not video.is_file():
                    return self.enviar({"erro": "not found"}, codigo=404)
                return self.enviar(video.read_bytes(), "video/mp4")
            if u.path == "/api/info/video":
                video = (Path(sys.executable).parent if CONGELADO else Path(__file__).resolve().parent.parent / "docs" / "video") / "Moby-DIC-tutorial.mp4"
                return self.enviar({"video": video.is_file()})
            if u.path == "/api/exemplos":
                from .exemplos import EXEMPLOS
                return self.enviar([{"nome": k, "pt": d[0], "en": d[1]} for k, (_, d) in EXEMPLOS.items()])
            if u.path == "/api/video/sugerir":
                from . import video
                r = video.sugerir(q["arquivo"])
                salvar_prefs(ultima_pasta=str(Path(q["arquivo"]).parent))
                return self.enviar(r)
            if u.path == "/api/video/quadro":
                from . import video
                return self.enviar(video.quadro_jpeg(q["arquivo"], float(q.get("t", 0)), int(q.get("largura", 900))), "image/jpeg")
            if u.path == "/api/video/status":
                return self.enviar(TAREFA_VIDEO.info())
            if u.path == "/api/status":
                return self.enviar(TAREFA.info())
            if u.path == "/api/resultados":
                return self.enviar(listar_resultados())
            if u.path == "/res":
                pasta, nome = Path(q["d"]).resolve(), q["f"]
                alvo = (pasta / nome).resolve()
                if pasta not in pastas_resultado_permitidas() or alvo.parent != pasta or not alvo.is_file():
                    return self.enviar({"erro": "not found"}, codigo=404)
                tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
                return self.enviar(alvo.read_bytes(), tipo + ("; charset=utf-8" if tipo.startswith("text/") else ""))
            return self.enviar({"erro": "not found"}, codigo=404)
        except Exception as e:  # noqa: BLE001
            return self.enviar({"erro": str(e)}, codigo=500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            d = self.corpo_json()
            if u.path == "/api/sugerir":
                r = ap.sugerir(d["pasta"], int(d.get("inicio", 1)), d.get("fim") or None, int(d.get("a_cada", 1)))
                salvar_prefs(ultima_pasta=str(Path(d["pasta"]).parent))
                return self.enviar(r)
            if u.path == "/api/prefs":
                salvar_prefs(**{k: v for k, v in d.items() if k in ("idioma", "pasta_trabalho")})
                return self.enviar({"ok": True})
            if u.path == "/api/executar":
                if TAREFA.estado == "rodando":
                    return self.enviar({"erro": "busy"}, codigo=409)
                if not re.fullmatch(r"[\w.\- ]+", d["saida"]):
                    return self.enviar({"erro": "nome_invalido"}, codigo=400)
                base = Path(d["pasta_trabalho"]).expanduser()
                base.mkdir(parents=True, exist_ok=True)
                saida = base / d["saida"]
                if saida.exists():
                    return self.enviar({"erro": "ja_existe"}, codigo=400)
                salvar_prefs(pasta_trabalho=str(base), **({"escala_um_px": d["escala_um_px"]} if d.get("escala_um_px") else {}))
                threading.Thread(target=executar, args=(d, saida), daemon=True).start()
                return self.enviar({"ok": True, "saida": str(saida)})
            if u.path == "/api/exemplo":
                from .exemplos import EXEMPLOS, gerar
                if d.get("nome") not in EXEMPLOS:
                    return self.enviar({"erro": "not found"}, codigo=404)
                pasta = gerar(d["nome"], Path(ler_prefs()["pasta_trabalho"]) / "examples")
                return self.enviar({"ok": True, "pasta": str(pasta)})
            if u.path == "/api/video/extrair":
                if TAREFA_VIDEO.estado == "rodando":
                    return self.enviar({"erro": "busy"}, codigo=409)
                from . import video
                alvo = video.indices_extracao(video.informacoes(d["arquivo"])["fps"], video.informacoes(d["arquivo"])["n_quadros"],
                                              float(d["inicio_s"]), float(d["fim_s"]), int(d["n"]))
                TAREFA_VIDEO.__init__()
                TAREFA_VIDEO.estado, TAREFA_VIDEO.total = "rodando", len(alvo)
                threading.Thread(target=extrair_video, args=(d,), daemon=True).start()
                return self.enviar({"ok": True, "total": len(alvo)})
            if u.path == "/api/video/cancelar":
                TAREFA_VIDEO.cancelar = True
                return self.enviar({"ok": True})
            if u.path == "/api/cancelar":
                TAREFA.cancelar = True
                if TAREFA.proc:
                    TAREFA.proc.terminate()
                return self.enviar({"ok": True})
            if u.path == "/api/abrir_resultado":
                pasta = Path(d["pasta"])
                if not (pasta / "visualizador.html").exists():
                    if (pasta / "campos.npz").exists():
                        subprocess.run(comando_base() + ["viewer", str(pasta), "--idioma", ler_prefs().get("idioma") or "en"],
                                       check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    else:
                        return self.enviar({"erro": "sem_resultado"}, codigo=400)
                registrar_resultado(pasta)
                return self.enviar({"ok": True, "caminho": str(pasta.resolve())})
            if u.path == "/api/abrir_pasta":
                pasta = Path(d["pasta"])
                if pasta.is_dir():
                    if os.name == "nt":
                        os.startfile(pasta)  # noqa: S606
                    else:
                        subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(pasta)])
                return self.enviar({"ok": True})
            if u.path == "/api/encerrar":
                self.enviar({"ok": True})
                threading.Thread(target=Handler.servidor.shutdown, daemon=True).start()
                return None
            return self.enviar({"erro": "not found"}, codigo=404)
        except Exception as e:  # noqa: BLE001
            return self.enviar({"erro": str(e)}, codigo=500)


def porta_livre(inicial):
    for p in range(inicial, inicial + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("nenhuma porta livre")


def iniciar(porta=8770, abrir_navegador=True):
    porta = porta_livre(porta)
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    Handler.servidor = srv
    url = f"http://127.0.0.1:{porta}/"
    print(f"{NOME} {__version__}\n  {url}\n  " + tx("Feche esta janela (ou use 'Encerrar' na página) para sair.",
                                                 "Close this window (or use 'Quit' on the page) to exit."), flush=True)
    if abrir_navegador:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if TAREFA.proc:
            TAREFA.proc.terminate()
