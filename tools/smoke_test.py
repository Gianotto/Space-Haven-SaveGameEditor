#!/usr/bin/env python3
"""Verifica que o executável empacotado realmente sobe e responde.

O erro mais comum ao empacotar é o binário nascer sem os arquivos de dados
(`gamedata.json`, `i18n.json`, a pasta `web/`): ele abre, mas a interface vem
vazia. Este teste roda o binário de verdade e confere que a API responde e que
os recursos foram embutidos.

    python3 tools/smoke_test.py dist/SpaceHavenEditor
    python3 tools/smoke_test.py dist/SpaceHavenEditor.exe --port 8791
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


def wait_for_api(url: str, process: subprocess.Popen, timeout: float = 40.0) -> dict:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            out = (process.stdout.read() if process.stdout else "") or ""
            raise SystemExit(f"o processo encerrou sozinho (código {process.returncode})\n{out}")
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return json.load(resp)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise SystemExit(f"a API não respondeu em {timeout:.0f}s: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="teste de fumaça do executável")
    parser.add_argument("binary", help="caminho do executável gerado")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()

    base = f"http://127.0.0.1:{args.port}"
    process = subprocess.Popen(
        [args.binary, "--port", str(args.port), "--no-browser"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    failures = []
    try:
        state = wait_for_api(f"{base}/api/state", process)
        print(f"  /api/state respondeu (abas: {len(state.get('tabs', []))})")

        if not state.get("gamedata"):
            failures.append("gamedata.json não foi embutido — os nomes sairiam como IDs")
        else:
            print(f"  gamedata embutido (versão {state.get('gamedataVersion') or '?'})")

        if len(state.get("tabs", [])) != 7:
            failures.append(f"esperava 7 abas, veio {len(state.get('tabs', []))}")

        with urllib.request.urlopen(f"{base}/api/i18n?lang=en", timeout=5) as resp:
            strings = json.load(resp).get("strings", {})
        if strings.get("app.save") != "Save":
            failures.append(f"catálogo de textos não embutido (app.save={strings.get('app.save')!r})")
        else:
            print(f"  i18n embutido ({len(strings)} textos, EN e PT-BR)")

        for asset in ("/", "/app.js", "/style.css"):
            with urllib.request.urlopen(base + asset, timeout=5) as resp:
                size = len(resp.read())
            if resp.status != 200 or size == 0:
                failures.append(f"{asset} não foi servido")
            else:
                print(f"  {asset} servido ({size} bytes)")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    if failures:
        print("\nFALHOU:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nteste de fumaça OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
