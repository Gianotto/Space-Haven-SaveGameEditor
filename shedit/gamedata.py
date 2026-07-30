"""Tabela de nomes do jogo (IDs -> nomes legiveis, EN e PT-BR).

Os dados vem de `data/gamedata.json`, gerado por `tools/extract_gamedata.py`
a partir do `spacehaven.jar`. Se o arquivo nao existir, o editor continua
funcionando e simplesmente exibe os IDs crus.
"""

from __future__ import annotations

import json
import os

from .i18n import DEFAULT_LANG
from .resources import resource

_DATA = resource("data", "gamedata.json")

_EMPTY = {
    "version": "",
    "elements": {}, "products": {}, "items": {}, "techs": {}, "traits": {},
    "conditions": {}, "factions": {}, "backstories": {}, "augmentations": {},
    "monsters": {}, "robots": {}, "crafts": {}, "difficulties": {},
    "scenarios": {}, "attributes": {}, "skills": {}, "enums": {},
}

# Tabelas consultadas, em ordem, quando o tipo de um ID nao e conhecido.
_STUFF_ORDER = ("products", "items", "elements", "crafts", "monsters", "robots")


class GameData:
    def __init__(self, path: str = _DATA):
        self.available = os.path.isfile(path)
        if self.available:
            with open(path, encoding="utf-8") as fh:
                self.raw = json.load(fh)
            for key, default in _EMPTY.items():
                self.raw.setdefault(key, default)
        else:
            self.raw = dict(_EMPTY)

    # -- consultas ---------------------------------------------------------

    def entry(self, table: str, ident) -> dict:
        return self.raw.get(table, {}).get(str(ident)) or {}

    @staticmethod
    def _pick(rec: dict, lang: str, prefix: str = "") -> str:
        """Texto no idioma pedido, caindo no outro quando faltar."""
        first, second = ("pt", "en") if lang == "pt" else ("en", "pt")
        return rec.get(prefix + first) or rec.get(prefix + second) or ""

    def name(self, table: str, ident, fallback: str | None = None,
             lang: str = DEFAULT_LANG) -> str:
        label = self._pick(self.entry(table, ident), lang)
        if label:
            return label
        return fallback if fallback is not None else f"#{ident}"

    def desc(self, table: str, ident, lang: str = DEFAULT_LANG) -> str:
        return self._pick(self.entry(table, ident), lang, "desc_")

    def stuff(self, ident, lang: str = DEFAULT_LANG) -> tuple[str, str]:
        """Resolve o ID de um recurso/item/objeto. Retorna (nome, tabela)."""
        key = str(ident)
        for table in _STUFF_ORDER:
            rec = self.raw.get(table, {}).get(key)
            label = self._pick(rec, lang) if rec else ""
            if label:
                return (label, table)
        return (f"#{ident}", "")

    def skill(self, save_nr) -> dict:
        return self.entry("skills", save_nr)

    def skill_label(self, save_nr, lang: str = DEFAULT_LANG) -> str:
        rec = self.entry("skills", save_nr)
        return self._pick(rec, lang) or rec.get("key") or f"skill {save_nr}"

    def enum(self, name: str) -> list:
        return self.raw.get("enums", {}).get(name, [])

    def enum_labels(self, name: str, lang: str = DEFAULT_LANG) -> list:
        """[{value, label}] para preencher <select> na interface."""
        return [{"value": rec["name"], "label": self._pick(rec, lang) or rec["name"]}
                for rec in self.enum(name)]

    # -- catalogos para os seletores da interface --------------------------

    def catalog(self, table: str, with_desc: bool = False,
                lang: str = DEFAULT_LANG) -> list:
        out = []
        for ident, rec in self.raw.get(table, {}).items():
            label = self._pick(rec, lang)
            if not label:
                continue
            item = {"id": ident, "label": label}
            if with_desc:
                item["desc"] = self._pick(rec, lang, "desc_")
            out.append(item)
        out.sort(key=lambda r: r["label"].lower())
        return out

    def storables(self, lang: str = DEFAULT_LANG) -> list:
        """Tudo que pode aparecer em um armazenamento (produtos + itens)."""
        out = []
        for table in ("products", "items"):
            for ident, rec in self.raw.get(table, {}).items():
                label = self._pick(rec, lang)
                if label:
                    out.append({"id": ident, "label": label, "table": table})
        out.sort(key=lambda r: r["label"].lower())
        return out


GAMEDATA = GameData()
