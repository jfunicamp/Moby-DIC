"""Moby-DIC · idioma das mensagens do programa (português / inglês).

Ordem de prioridade: variável de ambiente ``MOBYDIC_LANG`` (o aplicativo a define para as
análises que dispara), depois o idioma salvo nas preferências do usuário, depois inglês.
"""

import json
import os

IDIOMAS = ("pt", "en")
_cache = None


def idioma():
    global _cache
    v = os.environ.get("MOBYDIC_LANG", "").lower()[:2]
    if v in IDIOMAS:
        return v
    if _cache is None:
        _cache = "en"
        try:
            from . import pasta_dados_usuario
            p = json.loads((pasta_dados_usuario() / "config.json").read_text(encoding="utf-8")).get("idioma")
            if p in IDIOMAS:
                _cache = p
        except (OSError, ValueError, AttributeError):
            pass
    return _cache


def t(pt, en):
    """Texto no idioma atual."""
    return en if idioma() == "en" else pt
