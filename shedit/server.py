"""Servidor local do editor: API JSON + arquivos estaticos da interface.

Usa apenas a biblioteca padrao. O servidor escuta em 127.0.0.1 e serve a
interface, que roda no navegador; a edicao acontece no processo Python, que
e quem le e grava o arquivo do savegame.
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import string
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import actions, i18n, views
from .gamedata import GAMEDATA as GD
from .resources import resource
from .savefile import SaveFile, SaveError, SAVE_FILENAME

WEB_DIR = resource("web")


class Session:
    """Estado compartilhado entre as requisicoes: o save aberto no momento."""

    def __init__(self, path: str | None = None):
        self.lock = threading.Lock()
        self.save: SaveFile | None = None
        self.error: str | None = None
        if path:
            try:
                self.open(path)
            except SaveError as exc:
                self.error = str(exc)

    def open(self, path: str) -> SaveFile:
        self.save = SaveFile(path)
        self.error = None
        return self.save

    def require(self) -> SaveFile:
        if self.save is None:
            raise SaveError("nenhum savegame carregado")
        return self.save

    def status(self, lang: str = i18n.DEFAULT_LANG) -> dict:
        common = {
            "tabs": views.tabs(lang),
            "lang": lang,
            "languages": i18n.languages(),
            "gamedata": GD.available,
            "gamedataVersion": GD.raw.get("version", ""),
        }
        if self.save is None:
            return {"loaded": False, "error": self.error, **common}
        status = self.save.status()
        status.update({"loaded": True, "error": None, **common})
        return status


class Handler(BaseHTTPRequestHandler):
    session: Session  # injetado em serve()
    server_version = "SpaceHavenEditor"

    # -- infraestrutura ----------------------------------------------------

    def log_message(self, fmt, *args):  # silencia o log padrao
        pass

    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _fail(self, message: str, status: int = 400):
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SaveError(f"corpo da requisição inválido: {exc}") from exc

    # -- rotas -------------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        try:
            if url.path.startswith("/api/"):
                with self.session.lock:
                    return self._api_get(url.path, query)
            return self._static(url.path)
        except SaveError as exc:
            return self._fail(str(exc))
        except Exception as exc:  # falha inesperada nao deve derrubar o servidor
            return self._fail(f"erro interno: {exc}", 500)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            body = self._body()
            with self.session.lock:
                return self._api_post(url.path, body)
        except SaveError as exc:
            return self._fail(str(exc))
        except KeyError as exc:
            return self._fail(f"parâmetro obrigatório ausente: {exc}")
        except Exception as exc:
            return self._fail(f"erro interno: {exc}", 500)

    def _api_get(self, path: str, query: dict):
        session = self.session
        lang = i18n.normalize((query.get("lang") or [None])[0])

        if path == "/api/state":
            return self._json(session.status(lang))

        if path == "/api/i18n":
            return self._json({"lang": lang, "languages": i18n.languages(),
                               "strings": i18n.catalog_for(lang)})

        if path == "/api/tab":
            sf = session.require()
            tab = (query.get("id") or [""])[0]
            builder = {
                "game": views.view_game,
                "crew": views.view_crew,
                "storage": views.view_storage,
                "research": views.view_research,
                "ships": views.view_ships,
                "factions": views.view_factions,
            }.get(tab)
            if builder is None:
                if tab == "raw":
                    node = (query.get("path") or [""])[0]
                    return self._json(views.view_raw(sf, node, lang))
                return self._fail(f"aba desconhecida: {tab!r}", 404)
            return self._json(builder(sf, lang))

        if path == "/api/search":
            sf = session.require()
            q = (query.get("q") or [""])[0]
            return self._json(views.search(sf, q, lang=lang))

        if path == "/api/browse":
            # Lista pastas/arquivos para o seletor de save embutido.
            start = (query.get("path") or [_default_saves_dir()])[0]
            return self._json(_browse(start))

        return self._fail("rota não encontrada", 404)

    def _api_post(self, path: str, body: dict):
        session = self.session

        if path == "/api/open":
            sf = session.open(body["path"])
            return self._json({"ok": True, "path": sf.path})

        if path == "/api/reload":
            sf = session.require()
            sf.load()
            return self._json({"ok": True, "path": sf.path})

        if path == "/api/patch":
            sf = session.require()
            applied = sf.apply(body.get("ops") or [])
            return self._json({"ok": True, "applied": applied, "dirty": sf.dirty})

        if path == "/api/action":
            sf = session.require()
            result = actions.dispatch(sf, body.get("name", ""), body.get("params"))
            result.update({"ok": True, "dirty": sf.dirty})
            return self._json(result)

        if path == "/api/save":
            sf = session.require()
            info = sf.save(backup=body.get("backup", True))
            info["ok"] = True
            return self._json(info)

        return self._fail("rota não encontrada", 404)

    # -- estaticos ---------------------------------------------------------

    def _static(self, path: str):
        if path in ("/", ""):
            path = "/index.html"
        rel = posixpath.normpath(path).lstrip("/")
        target = os.path.join(WEB_DIR, rel)
        if not os.path.abspath(target).startswith(WEB_DIR) or not os.path.isfile(target):
            return self._send(404, b"nao encontrado", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(target, "rb") as fh:
            return self._send(200, fh.read(), ctype)


# --------------------------------------------------------------------------
# Seletor de arquivos
# --------------------------------------------------------------------------

SAVE_DIRS = [
    "~/snap/steam/common/.local/share/Steam/steamapps/common/SpaceHaven/savegames",
    "~/.steam/steam/steamapps/common/SpaceHaven/savegames",
    "~/.local/share/Steam/steamapps/common/SpaceHaven/savegames",
    "~/Library/Application Support/Steam/steamapps/common/SpaceHaven/savegames",
    "C:/Program Files (x86)/Steam/steamapps/common/SpaceHaven/savegames",
]


def _drives() -> list:
    """Unidades disponíveis no Windows — não há uma raiz única para subir até ela."""
    if os.name != "nt":
        return []
    return [f"{letter}:\\" for letter in string.ascii_uppercase
            if os.path.exists(f"{letter}:\\")]


def _default_saves_dir() -> str:
    for candidate in SAVE_DIRS:
        p = os.path.expanduser(candidate)
        if os.path.isdir(p):
            return p
    return os.path.expanduser("~")


def _browse(path: str) -> dict:
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        path = os.path.dirname(path) or os.path.abspath(os.sep)
    parent = os.path.dirname(path.rstrip(os.sep)) or path
    drives = _drives()
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError as exc:
        return {"path": path, "parent": parent, "drives": drives,
                "entries": [], "error": str(exc)}
    entries = []

    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(path, name)
        is_dir = os.path.isdir(full)
        # Uma pasta de save contem o arquivo `game`; a pasta de uma partida
        # contem `save/` (e os autosaves), entao vale abrir as duas.
        is_save = is_dir and (
            os.path.isfile(os.path.join(full, SAVE_FILENAME))
            or os.path.isfile(os.path.join(full, "save", SAVE_FILENAME))
        )
        if not is_dir and name != SAVE_FILENAME:
            continue
        entries.append({"name": name, "path": full, "dir": is_dir, "save": is_save})
    return {"path": path, "parent": parent, "drives": drives,
            "entries": entries, "error": None}


# --------------------------------------------------------------------------


def serve(path: str | None, host: str = "127.0.0.1", port: int = 8713):
    session = Session(path)
    handler = type("BoundHandler", (Handler,), {"session": session})
    httpd = ThreadingHTTPServer((host, port), handler)
    return httpd, session
