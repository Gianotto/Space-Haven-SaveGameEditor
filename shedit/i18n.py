"""Textos da interface em PT-BR e EN.

O catálogo (`data/i18n.json`) é um só, usado tanto aqui — para os rótulos que o
backend monta — quanto no navegador, que o recebe por `/api/i18n`. Assim uma
tradução nova aparece nos dois lados de uma vez.

Os nomes do próprio jogo (recursos, tecnologias, traços) não estão aqui: vêm de
`gamedata.json`, que já traz EN e PT-BR extraídos do `spacehaven.jar`.
"""

from __future__ import annotations

import json

from .resources import resource

_CATALOG_PATH = resource("data", "i18n.json")

LANGS = ("pt", "en")
DEFAULT_LANG = "pt"

LANG_NAMES = {"pt": "Português (BR)", "en": "English"}


def _load() -> dict:
    try:
        with open(_CATALOG_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_")}


CATALOG = _load()


def normalize(lang: str | None) -> str:
    """Aceita 'pt', 'pt-BR', 'en-US'… e devolve um idioma suportado."""
    if not lang:
        return DEFAULT_LANG
    code = str(lang).replace("_", "-").split("-")[0].lower()
    return code if code in LANGS else DEFAULT_LANG


def t(key: str, lang: str = DEFAULT_LANG, **fmt) -> str:
    """Texto de `key` no idioma pedido.

    Sem tradução no idioma, cai no outro; sem a chave, devolve a própria chave
    — assim um texto faltando aparece na tela em vez de virar string vazia.
    """
    entry = CATALOG.get(key)
    if not entry:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or next(iter(entry.values()), key)
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def catalog_for(lang: str) -> dict:
    """{chave: texto} num idioma só, para enviar ao navegador."""
    return {k: t(k, lang) for k in CATALOG}


def languages() -> list:
    return [{"code": c, "label": LANG_NAMES.get(c, c)} for c in LANGS]
