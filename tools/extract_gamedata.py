#!/usr/bin/env python3
"""Extrai a tabela de nomes/IDs do Space Haven a partir do spacehaven.jar.

Gera `shedit/data/gamedata.json`, usado pelo editor para mostrar nomes reais
(em EN e PT-BR) no lugar dos IDs numericos do savegame.

Uso:
    python3 tools/extract_gamedata.py [caminho/para/spacehaven.jar]

Sem argumento, procura o jar nos locais padrao de instalacao (Steam).
Enums internos do jogo (skills, profissoes, prioridades) sao lidos por reflexao
usando o `jjs` do JRE que acompanha o jogo; se nao estiver disponivel, os
valores ja embutidos no gamedata.json anterior sao preservados.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "shedit", "data", "gamedata.json")

JAR_CANDIDATES = [
    "~/snap/steam/common/.local/share/Steam/steamapps/common/SpaceHaven/spacehaven.jar",
    "~/.steam/steam/steamapps/common/SpaceHaven/spacehaven.jar",
    "~/.local/share/Steam/steamapps/common/SpaceHaven/spacehaven.jar",
    "~/Library/Application Support/Steam/steamapps/common/SpaceHaven/spacehaven.jar",
    "C:/Program Files (x86)/Steam/steamapps/common/SpaceHaven/spacehaven.jar",
]

# Enums do jogo lidos por reflexao. Para cada um guardamos os campos indicados.
ENUMS = {
    "SkillClass": ("fi.bugbyte.spacehaven.ai.Job$SkillClass", ["saveNR", "textId", "sort", "showOnStats"]),
    "Profession": ("fi.bugbyte.spacehaven.ai.Job$Profession", ["textId", "saveNR", "sort"]),
    "WorkPriority": ("fi.bugbyte.spacehaven.ai.Job$WorkPriority", ["textId", "value"]),
    "AttributeType": ("fi.bugbyte.spacehaven.stuff.personality.PersonalitySetting$AttributeType", ["textId"]),
    "Stance": ("fi.bugbyte.spacehaven.stuff.FactionUtils$Stance", ["textId"]),
}


def find_jar(argv):
    if len(argv) > 1:
        p = os.path.expanduser(argv[1])
        if not os.path.isfile(p):
            sys.exit(f"jar nao encontrado: {p}")
        return p
    for c in JAR_CANDIDATES:
        p = os.path.expanduser(c)
        if os.path.isfile(p):
            return p
    sys.exit(
        "spacehaven.jar nao encontrado. Passe o caminho como argumento:\n"
        "  python3 tools/extract_gamedata.py /caminho/spacehaven.jar"
    )


def read_texts(blob: bytes) -> dict:
    """O arquivo `texts` nao e XML valido (& e < crus), entao usamos regex."""
    raw = blob.decode("utf-8", errors="replace")
    out = {}
    for m in re.finditer(r'<t id="(\d+)"[^>]*>(.*?)</t>', raw, re.S):
        tid, body = m.group(1), m.group(2)
        en = re.search(r"<EN>(.*?)</EN>", body, re.S)
        pt = re.search(r"<PTBR>(.*?)</PTBR>", body, re.S)
        en_s = clean(en.group(1)) if en else ""
        pt_s = clean(pt.group(1)) if pt else ""
        if en_s or pt_s:
            out[tid] = [en_s, pt_s]
    return out


TAG_RE = re.compile(r"<[^>]{0,40}>")


def clean(s: str) -> str:
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    s = TAG_RE.sub("", s)
    return " ".join(s.split())


def tid_of(node, tag="name"):
    """tid do primeiro <name>/<desc>; em Element eles ficam aninhados em objectInfo."""
    child = node.find(tag)
    if child is None:
        child = next((n for n in node.iter(tag) if n.get("tid")), None)
    if child is None:
        return None
    return child.get("tid")


def named_table(section, id_attr, texts, extra=None):
    """{id: {"en":..,"pt":..,"desc":..}} para uma secao do library/haven."""
    out = {}
    if section is None:
        return out
    for node in section:
        ident = node.get(id_attr)
        if ident is None:
            continue
        name_t = texts.get(tid_of(node, "name") or "", ["", ""])
        desc_t = texts.get(tid_of(node, "desc") or "", ["", ""])
        rec = {"en": name_t[0], "pt": name_t[1]}
        if desc_t[0] or desc_t[1]:
            rec["desc_en"], rec["desc_pt"] = desc_t[0], desc_t[1]
        if extra:
            extra(node, rec)
        out[ident] = rec
    return out


def tech_stages(node, rec):
    """Custo de cada estagio da tecnologia (usado para marcar como concluida)."""
    if node.get("hidden") is not None:
        rec["hidden"] = node.get("hidden")
    stages = []
    for st in node.findall("stages/l"):
        pts = st.find("labPoints")
        stages.append({
            "stage": st.get("stage"),
            "level1": (pts.get("level1") if pts is not None else "0") or "0",
            "level2": (pts.get("level2") if pts is not None else "0") or "0",
            "level3": (pts.get("level3") if pts is not None else "0") or "0",
        })
    if stages:
        rec["stages"] = stages


def reflect_enums(jar: str, jre_bin: str | None) -> dict:
    """Le enums do jogo via reflexao (jjs do JRE que acompanha o jogo)."""
    if not jre_bin or not os.path.isfile(jre_bin):
        return {}
    spec = {k: v for k, v in ENUMS.items()}
    js_specs = json.dumps([[k, cls, fields] for k, (cls, fields) in spec.items()])
    script = """
var jarFile = new java.io.File(JARPATH);
var cl = new java.net.URLClassLoader([jarFile.toURI().toURL()], null);
var specs = SPECS;
var result = {};
for (var i = 0; i < specs.length; i++) {
    var key = specs[i][0], clsName = specs[i][1], fields = specs[i][2];
    try {
        var c = java.lang.Class.forName(clsName, false, cl);
        var consts = c.getEnumConstants();
        if (consts === null) continue;
        var entries = [];
        for (var j = 0; j < consts.length; j++) {
            var o = consts[j];
            var rec = { name: String(o.name()), ordinal: o.ordinal() };
            for (var k = 0; k < fields.length; k++) {
                try {
                    var f = c.getDeclaredField(fields[k]);
                    f.setAccessible(true);
                    var v = f.get(o);
                    rec[fields[k]] = (v === null) ? null : String(v);
                } catch (e) { }
            }
            entries.push(rec);
        }
        result[key] = entries;
    } catch (e) { }
}
print(JSON.stringify(result));
"""
    script = script.replace("JARPATH", json.dumps(jar)).replace("SPECS", js_specs)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        raw = subprocess.run(
            [jre_bin, path], capture_output=True, text=True, timeout=120
        ).stdout.strip()
        line = raw.splitlines()[-1] if raw else ""
        return json.loads(line) if line.startswith("{") else {}
    except Exception as exc:  # pragma: no cover - ambiente sem jjs
        print(f"  aviso: reflexao de enums falhou ({exc})", file=sys.stderr)
        return {}
    finally:
        os.unlink(path)


def main():
    jar = find_jar(sys.argv)
    print(f"jar: {jar}")
    jre = os.path.join(os.path.dirname(jar), "jre", "bin", "jjs")

    with zipfile.ZipFile(jar) as z:
        texts = read_texts(z.read("library/texts"))
        haven_raw = z.read("library/haven")
    print(f"  textos: {len(texts)}")

    haven = ET.fromstring(re.sub(rb"&(?![A-Za-z#][A-Za-z0-9]*;)", b"&amp;", haven_raw))
    # `library/version` só diz "pc"; a versão de verdade está na raiz do haven.
    version = haven.get("libVersion", "")
    print(f"  versão do jogo: {version or '?'}")

    def with_attrs(*attrs):
        def f(node, rec):
            for a in attrs:
                if node.get(a) is not None:
                    rec[a] = node.get(a)
        return f

    data = {
        "version": version,
        "elements": named_table(haven.find("Element"), "mid", texts, with_attrs("ec")),
        "products": named_table(haven.find("Product"), "eid", texts, with_attrs("type")),
        "items": named_table(haven.find("Item"), "mid", texts, with_attrs("handness")),
        "techs": named_table(haven.find("Tech"), "id", texts, tech_stages),
        "traits": named_table(haven.find("CharacterTrait"), "id", texts),
        "conditions": named_table(haven.find("CharacterCondition"), "id", texts),
        "factions": named_table(haven.find("Faction"), "id", texts, with_attrs("side", "primaryColor")),
        "backstories": named_table(haven.find("BackStory"), "id", texts),
        "augmentations": named_table(haven.find("Augmentation"), "id", texts),
        "monsters": named_table(haven.find("Monster"), "cid", texts),
        "robots": named_table(haven.find("Robot"), "cid", texts),
        "crafts": named_table(haven.find("Craft"), "cid", texts, with_attrs("type")),
        "difficulties": named_table(haven.find("DifficultySettings"), "id", texts),
        "scenarios": named_table(haven.find("GameScenario"), "id", texts),
    }

    # Faction usa `id` ou `mid` dependendo da versao; tenta o outro se vazio.
    if not data["factions"]:
        data["factions"] = named_table(haven.find("Faction"), "mid", texts)

    enums = reflect_enums(jar, jre)
    if enums:
        print(f"  enums: {', '.join(sorted(enums))}")
    else:
        print("  enums: nenhum (jjs indisponivel) - mantendo tabela anterior se existir")
        if os.path.isfile(OUT):
            with open(OUT, encoding="utf-8") as fh:
                enums = json.load(fh).get("enums", {})

    # Resolve os textId dos enums para nomes legiveis.
    for entries in enums.values():
        for rec in entries:
            t = texts.get(str(rec.get("textId")))
            if t:
                rec["en"], rec["pt"] = t[0], t[1]
    data["enums"] = enums

    # Atributos de personagem: o `id` no save e o proprio textId.
    data["attributes"] = {}
    for rec in enums.get("AttributeType", []):
        tid = rec.get("textId")
        if tid and tid in texts:
            data["attributes"][tid] = {"en": texts[tid][0], "pt": texts[tid][1], "key": rec["name"]}
    if not data["attributes"]:
        for tid in ("210", "212", "213", "214"):
            if tid in texts:
                data["attributes"][tid] = {"en": texts[tid][0], "pt": texts[tid][1]}

    # Skills indexadas pelo numero gravado no save (`sk`).
    data["skills"] = {}
    for rec in enums.get("SkillClass", []):
        nr = rec.get("saveNR")
        if nr is None:
            continue
        data["skills"][str(nr)] = {
            "key": rec["name"],
            "en": rec.get("en") or rec["name"],
            "pt": rec.get("pt") or rec["name"],
            "sort": int(rec.get("sort") or 0),
            "show": rec.get("showOnStats") == "true",
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    sizes = {k: len(v) for k, v in data.items() if isinstance(v, dict)}
    print(f"gravado: {OUT} ({os.path.getsize(OUT) // 1024} KB)")
    print("  " + ", ".join(f"{k}={v}" for k, v in sorted(sizes.items())))


if __name__ == "__main__":
    main()
