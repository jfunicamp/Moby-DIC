"""Moby-DIC: 2D digital image correlation (DIC) for mechanical testing.

Copyright (c) 2026 João Felipe. MIT License (see LICENSE).
"""

import os
import sys
from pathlib import Path

NOME = "Moby-DIC"
__version__ = "1.1.0"


def pasta_dados_usuario():
    """Pasta de configuração do usuário (%APPDATA%\\Moby-DIC no Windows, ~/.config/moby-dic no resto)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        p = base / NOME
    else:
        p = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "moby-dic"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pasta_trabalho_padrao():
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / NOME


def configurar_numba():
    """Coloca o cache do numba numa pasta gravável (necessário no executável)."""
    if getattr(sys, "frozen", False) and "NUMBA_CACHE_DIR" not in os.environ:
        os.environ["NUMBA_CACHE_DIR"] = str(pasta_dados_usuario() / "numba_cache")
