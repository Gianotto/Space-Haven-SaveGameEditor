#!/usr/bin/env python3
"""Compara a galaxia gerada de dois ou mais savegames do Space Haven.

Serve para responder uma pergunta so: dois jogos criados com a mesma seed
produzem o mesmo mapa estelar? E a base da ideia de galaxia compartilhada — se a
geracao for reprodutivel, criar universos iguais e trivial; se nao for, o
universo tem que ser distribuido como arquivo.

O programa compara o *esqueleto* do mundo e ignora tudo que muda enquanto se
joga. Isso importa mais do que parece: os corpos celestes orbitam, entao a
posicao de um planeta em dois momentos da mesma partida e diferente sem que o
mundo tenha mudado. Comparando dois autosaves da mesma partida, o unico que
varia nos corpos e `x`, `y` e `timeStepA` — posicao e fase da orbita. O resto
(a semente de cada corpo, o tipo, o raio da orbita, de quem ele orbita) e
constante, e e disso que a impressao digital e feita.

Nos setores acontece o mesmo com um agravante: a lista mistura o terreno gerado
(asteroides, destrocos, bases) com coisas que aparecem e somem durante a partida
(missoes, naves no mapa, ofertas de novo lar). So o terreno entra na conta.

Uso:
    python3 tools/compare_galaxy.py SAVE_A SAVE_B [SAVE_C ...]
    python3 tools/compare_galaxy.py --json SAVE      # imprime a impressao digital
    python3 tools/compare_galaxy.py --verbose A B    # mostra tambem o que varia

Como testar a reprodutibilidade da seed:
    1. Novo jogo, anote a seed, salve assim que a partida abrir.
    2. Novo jogo com a mesma seed, salve do mesmo jeito.
    3. Rode este programa nos dois saves.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shedit.savefile import SaveFile, SaveError  # noqa: E402

# Atributos de um corpo celeste que o gerador define e o jogo nao mexe depois.
# Ficam de fora `x`, `y` e `timeStepA`: os tres acompanham a orbita e mudam
# sozinhos com o passar do tempo de jogo.
BODY_KEYS = ("type", "celeid", "seed", "starType", "starClass",
             "ox", "oy", "centerId", "maxLen", "orbitSpeedMul")
# O setor nao tem semente propria; o que o identifica e o tipo mais os
# parametros da orbita. `angle` fica de fora pelo mesmo motivo que `timeStepA`.
SECTOR_KEYS = ("type", "strength", "rich")
ORBIT_KEYS = ("rx", "ry", "speed")
# Entram na lista de setores mas nao sao terreno: aparecem e somem durante a
# partida. Conferido em quatro momentos da mesma partida, onde variaram de 3
# para 4, de 1 para 4 e de 6 para 5 enquanto o terreno ficou parado.
TRANSIENT_SECTORS = {"StarmapCraft", "SM_AwayMission", "SM_NewHomeSector",
                     "ExodusSupplyFleet"}
# Do <starmap> so o tamanho da galaxia e parametro de geracao. `sys` e `pa` sao
# contadores internos — nao batem com a quantidade de sistemas nem de corpos
# (73 sistemas com sys=31, 77 com sys=6), entao entrariam na conta como ruido.
# `objectIdCounter` e `awayMission` mudam sozinhos durante a partida.
MAP_KEYS = ("w", "h")


def _text(value: str | None) -> str:
    """Os nomes de sistema vem em hexadecimal no save."""
    if not value:
        return ""
    try:
        return binascii.unhexlify(value).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return value


def _pick(node, keys) -> dict:
    return {k: node.get(k) for k in keys if node.get(k) is not None}


def _key(rec: dict) -> str:
    return json.dumps(rec, sort_keys=True, ensure_ascii=False)


def fingerprint(path: str) -> dict:
    """Impressao digital da galaxia de um save."""
    sf = SaveFile(path)
    root = sf.main
    starmap = root.find("starmap")
    if starmap is None:
        raise SaveError(f"{path}: este save não tem <starmap>")

    systems, volatile = [], []
    for l in starmap.findall("systems/l"):
        # Ordenado, e nao na ordem do arquivo: o que interessa e o conjunto de
        # corpos, nao a ordem em que o jogo resolveu grava-los.
        bodies = sorted((_pick(b, BODY_KEYS) for b in l.findall("bodies/l")), key=_key)

        sectors, dropped = [], []
        for s in l.findall("emptySectors/l"):
            if s.get("type") in TRANSIENT_SECTORS:
                dropped.append(s.get("type"))
                continue
            rec = _pick(s, SECTOR_KEYS)
            orbit = s.find("orbit")
            if orbit is not None:
                rec.update({f"orbit_{k}": v for k, v in _pick(orbit, ORBIT_KEYS).items()})
            sectors.append(rec)
        sectors.sort(key=_key)
        volatile += dropped

        clouds = sorted(({"color": c.get("color"), "points": len(c.findall("cd"))}
                         for c in l.findall("clouds/c")), key=_key)
        systems.append({
            "id": l.get("systemId"),
            "name": _text(l.get("sn")),
            "short": _text(l.get("smn")),
            "bodies": bodies,
            "sectors": sectors,
            "clouds": clouds,
        })

    fp = {
        "save": os.path.abspath(path),
        "seed": root.get("seed"),
        "mode": root.get("mode"),
        "map": _pick(starmap, MAP_KEYS),
        "systems": systems,
        "ignored": len(volatile),
        "named": sum(1 for s in systems if s["name"].strip()),
    }
    # O nome do sistema fica de fora da conta: num save recem-criado nenhum
    # sistema tem nome, e nos jogados todos tem. Sao atribuidos depois da
    # criacao, entao entrariam como diferenca entre o mesmo universo novo e
    # jogado — que e justamente a comparacao que interessa.
    skeleton = {
        "map": fp["map"],
        "systems": [{k: s[k] for k in ("id", "bodies", "sectors", "clouds")}
                    for s in systems],
    }
    fp["digest"] = hashlib.sha256(
        json.dumps(skeleton, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    return fp


def _counts(fp: dict) -> str:
    s = fp["systems"]
    return (f"{len(s)} sistema(s), {sum(len(x['bodies']) for x in s)} corpos, "
            f"{sum(len(x['sectors']) for x in s)} setores de terreno "
            f"({fp['ignored']} ignorados por serem temporários)")


# O `seed` da raiz do save veio 0 em todas as partidas testadas, inclusive em
# jogos com galaxias completamente diferentes: o save nao guarda a seed que a
# pessoa digitou ao criar o jogo. Quem compara precisa saber disso, senao pode
# achar que dois saves com "a mesma seed" foram feitos iguais.
_SEED_NOTE = ("nota: o save não guarda a seed digitada na criação do jogo "
              "(vem sempre 0), então a comparação só faz sentido se você "
              "souber qual seed usou em cada partida.")


def _seed_warning(fps: list) -> str | None:
    return _SEED_NOTE if all(f["seed"] in (None, "0", "") for f in fps) else None


def _systems_line(fp: dict, show: int = 3) -> str:
    """Uma galaxia completa tem dezenas de sistemas; so os primeiros cabem."""
    if not fp["named"]:
        return "sistemas ainda sem nome (save recém-criado)"
    names = [s["name"] for s in fp["systems"] if s["name"].strip()]
    head = ", ".join(names[:show])
    return head + (f" … e mais {len(names) - show}" if len(names) > show else "")


def _diff_sets(a: list, b: list, label: str, limit: int = 4) -> list:
    """Diferencas entre dois conjuntos de registros, ja ordenados."""
    ka, kb = {_key(x) for x in a}, {_key(x) for x in b}
    out = []
    only_a, only_b = sorted(ka - kb), sorted(kb - ka)
    if not only_a and not only_b:
        return out
    out.append(f"    {label}: {len(only_a)} só no primeiro, {len(only_b)} só no segundo")
    for k in only_a[:limit]:
        out.append(f"      primeiro: {k}")
    for k in only_b[:limit]:
        out.append(f"      segundo:  {k}")
    return out


def compare(fps: list, verbose: bool = False) -> bool:
    base = fps[0]
    print(f"referência: {base['save']}")
    print(f"  seed={base['seed']!r} modo={base['mode']!r}")
    print(f"  {_counts(base)}")
    print(f"  {_systems_line(base)}")
    print(f"  impressão digital: {base['digest']}\n")

    all_equal = True
    for other in fps[1:]:
        same = other["digest"] == base["digest"]
        all_equal = all_equal and same
        print(f"[{'IGUAL' if same else 'DIFERENTE'}] {other['save']}")
        print(f"  seed={other['seed']!r} | {_counts(other)}")
        print(f"  impressão digital: {other['digest']}")
        if same and not verbose:
            print()
            continue

        if base["map"] != other["map"]:
            print(f"    mapa: {base['map']} vs {other['map']}")
        for i, (sa, sb) in enumerate(zip(base["systems"], other["systems"])):
            if sa["name"] != sb["name"]:
                print(f"    sistema[{i}] nome: {sa['name']!r} vs {sb['name']!r}")
            for line in _diff_sets(sa["bodies"], sb["bodies"], f"sistema[{i}] corpos"):
                print(line)
            for line in _diff_sets(sa["sectors"], sb["sectors"], f"sistema[{i}] setores"):
                print(line)
            for line in _diff_sets(sa["clouds"], sb["clouds"], f"sistema[{i}] nuvens"):
                print(line)
        if len(base["systems"]) != len(other["systems"]):
            print(f"    sistemas: {len(base['systems'])} vs {len(other['systems'])}")
        print()

    if len(fps) > 1:
        print("todas as galáxias são idênticas" if all_equal
              else "as galáxias são diferentes")
    warn = _seed_warning(fps)
    if warn:
        print(f"\n{warn}")
    return all_equal


def main() -> int:
    ap = argparse.ArgumentParser(description="compara a galáxia gerada de savegames")
    ap.add_argument("saves", nargs="+", help="pastas de save (ou o arquivo `game`)")
    ap.add_argument("--json", action="store_true",
                    help="imprime a impressão digital em JSON em vez de comparar")
    ap.add_argument("--verbose", action="store_true",
                    help="detalha as diferenças mesmo quando a impressão digital bate")
    args = ap.parse_args()

    try:
        fps = [fingerprint(p) for p in args.saves]
    except SaveError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(fps if len(fps) > 1 else fps[0], ensure_ascii=False, indent=2))
        return 0

    if len(fps) == 1:
        fp = fps[0]
        print(f"{fp['save']}\n  seed={fp['seed']!r} modo={fp['mode']!r}")
        print(f"  {_counts(fp)}")
        print(f"  {_systems_line(fp, show=8)}")
        print(f"  impressão digital: {fp['digest']}")
        print("\npasse dois ou mais saves para comparar.")
        warn = _seed_warning(fps)
        if warn:
            print(f"\n{warn}")
        return 0

    return 0 if compare(fps, args.verbose) else 1


if __name__ == "__main__":
    raise SystemExit(main())
