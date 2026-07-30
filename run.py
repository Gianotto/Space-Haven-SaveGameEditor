#!/usr/bin/env python3
"""Editor de savegames do Space Haven.

    python3 run.py                      # abre o seletor de saves na interface
    python3 run.py caminho/do/save      # abre um save direto (pasta ou arquivo `game`)
    python3 run.py --port 9000 --no-browser

Requer apenas Python 3.10+ (biblioteca padrao). A interface roda no navegador,
mas o arquivo e lido e gravado por este processo, na sua maquina.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from shedit.gamedata import GAMEDATA
from shedit.server import serve


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Editor de savegames do Space Haven",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("save", nargs="?", help="pasta do save ou o arquivo `game`")
    parser.add_argument("--port", type=int, default=8713, help="porta local (padrão: 8713)")
    parser.add_argument("--host", default="127.0.0.1", help="endereço de escuta")
    parser.add_argument("--no-browser", action="store_true", help="não abrir o navegador")
    args = parser.parse_args()

    try:
        httpd, session = serve(args.save, args.host, args.port)
    except OSError as exc:
        print(f"não foi possível abrir a porta {args.port}: {exc}", file=sys.stderr)
        print("use --port para escolher outra.", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"Editor de savegames do Space Haven — {url}")
    if session.save:
        print(f"  save aberto: {session.save.path}")
    elif session.error:
        print(f"  aviso: {session.error}")
    if not GAMEDATA.available:
        print("  aviso: shedit/data/gamedata.json ausente — os nomes aparecerão como IDs.")
        print("         gere com: python3 tools/extract_gamedata.py")
    print("  Ctrl+C para encerrar.")

    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
