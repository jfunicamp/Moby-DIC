"""Ponto de entrada do Moby-DIC.

    Moby-DIC                      abre o aplicativo (interface no navegador)
    Moby-DIC gui [--porta N] [--sem-navegador]
    Moby-DIC subsets ...          correlação por subsets (linha de comando)
    Moby-DIC mudic ...            backend muDIC (Q4 / B-spline), se instalado
    Moby-DIC viewer PASTA ...     (re)gera o visualizador de uma pasta de resultados
    Moby-DIC example [NOME]       gera imagens sintéticas de exemplo (tutoriais)
    Moby-DIC --version
"""

import argparse
import multiprocessing
import sys

from . import NOME, __version__
from .i18n import t as tx

AJUDA_EN = """Moby-DIC entry point.

    Moby-DIC                      opens the application (interface in the web browser)
    Moby-DIC gui [--port N] [--no-browser]
    Moby-DIC subsets ...          subset DIC (command line); see: Moby-DIC subsets --help
    Moby-DIC mudic ...            muDIC backend (Q4 / B-spline), if installed
    Moby-DIC viewer FOLDER ...    (re)builds the viewer of a result folder
    Moby-DIC example [NAME]       generates synthetic example images (tutorials)
    Moby-DIC --version

Set MOBYDIC_LANG=en or pt to choose the language of messages and figures.
"""


def main(argv=None):
    # Consoles do Windows costumam usar cp1252: ε, µ, ∇ quebrariam as mensagens.
    for fluxo in (sys.stdout, sys.stderr):
        if fluxo is not None and hasattr(fluxo, "reconfigure"):
            try:
                fluxo.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("--version", "-V", "version"):
        print(f"{NOME} {__version__}")
        return 0
    if argv and argv[0] in ("-h", "--help", "help"):
        print(tx(__doc__, AJUDA_EN))
        return 0
    cmd = argv[0] if argv and not argv[0].startswith("-") else "gui"
    resto = argv[1:] if argv and argv[0] == cmd else argv
    if cmd == "subsets":
        from .subsets import main as m
        return m(resto)
    if cmd == "mudic":
        from .mudic_backend import main as m
        return m(resto)
    if cmd == "viewer":
        from .viewer import main as m
        return m(resto)
    if cmd in ("example", "exemplo"):
        from .exemplos import main as m
        return m(resto)
    if cmd == "gui":
        pa = argparse.ArgumentParser(prog=NOME)
        pa.add_argument("--port", "--porta", dest="porta", type=int, default=8770)
        pa.add_argument("--no-browser", "--sem-navegador", dest="sem_navegador", action="store_true")
        a = pa.parse_args(resto)
        from .app import iniciar
        return iniciar(a.porta, not a.sem_navegador)
    print(tx(f"Comando desconhecido: {cmd}\n{__doc__}", f"Unknown command: {cmd}\n{AJUDA_EN}"))
    return 2


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main() or 0)
