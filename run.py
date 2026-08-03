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
import os
import sys
import threading
import webbrowser

from shedit.gamedata import GAMEDATA
from shedit.server import serve


def open_browser(url: str):
    """Abre o navegador sem deixar o barulho dele cair neste terminal.

    O navegador herda a saida deste processo, e os baseados em Chromium
    despejam avisos de GPU, de Wayland e do sandbox que nao tem nada a ver com
    o editor. Quem abre a ferramenta pela primeira vez le aquele bloco de
    ERROR como defeito daqui.

    A troca das duas saidas por /dev/null vale so durante o disparo — o filho
    herda o descritor nesse instante e fica com ele. A janela e de
    microssegundos e nada mais escreve nela: as mensagens do editor ja sairam
    e o servidor so imprime ao encerrar.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        devnull = os.open(os.devnull, os.O_RDWR)
    except OSError:
        webbrowser.open(url)          # sem /dev/null, o barulho e o menor problema
        return

    saved = []
    try:
        for fd in (1, 2):
            saved.append((fd, os.dup(fd)))
            os.dup2(devnull, fd)
        webbrowser.open(url)
    except Exception:
        pass                          # navegador que nao abre nao derruba o editor
    finally:
        for fd, copy in saved:
            os.dup2(copy, fd)
            os.close(copy)
        os.close(devnull)


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
    # Num terminal a saida sai linha a linha, mas redirecionada para arquivo ou
    # para um processo que le esta saida ela fica no buffer ate o fim — e quem
    # esta esperando o endereco aparecer nao ve nada.
    sys.stdout.flush()

    if not args.no_browser:
        threading.Timer(0.4, open_browser, args=(url,)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
