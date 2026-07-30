"""Onde estão os arquivos que acompanham o programa (dados e interface).

Rodando do código-fonte eles ficam ao lado deste módulo. Empacotado com o
PyInstaller em arquivo único, o executável se descompacta numa pasta temporária
cujo caminho vem em `sys._MEIPASS` — por isso nada aqui pode usar `__file__`
direto.
"""

from __future__ import annotations

import os
import sys

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def base_dir() -> str:
    """Raiz dos recursos do pacote `shedit`."""
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
        return os.path.join(bundle, "shedit")
    return _MODULE_DIR


def resource(*parts: str) -> str:
    """Caminho de um recurso, ex.: resource("data", "i18n.json")."""
    return os.path.join(base_dir(), *parts)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
