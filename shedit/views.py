"""Monta o conteudo de cada aba do editor a partir da arvore do savegame.

Cada campo editavel e descrito como um dicionario com o `path` do no e o
atributo a alterar, de modo que a interface possa renderizar e enviar
alteracoes de forma generica:

    {"path": "18/0/3", "attr": "v", "label": "Saude", "type": "int", "value": 120}

A interface devolve essas mesmas coordenadas em operacoes `set`, que
`SaveFile.apply` grava na arvore.
"""

from __future__ import annotations

from .gamedata import GAMEDATA as GD
from .i18n import DEFAULT_LANG, t
from .savefile import MAIN_DOC, SaveFile

TAB_IDS = ("game", "crew", "storage", "research", "ships", "factions", "raw")


def tabs(lang: str = DEFAULT_LANG) -> list:
    return [{"id": i, "label": t(f"tab.{i}", lang)} for i in TAB_IDS]

# Necessidades do personagem: quais atributos de cada <props> realmente valem
# ser editados, na ordem em que aparecem na ficha.
#
# Cada <props> tem `v` (valor presente) e às vezes `ltv` (valor de longo prazo)
# — os dois que as condições do jogo consultam como `whenPresent` e
# `whenLongTerm`. Mas em Food, Comfort, Oxygen e Temperature o `v` gravado é
# uma constante (100, 50, 0 e 100 em 568 tripulantes de três saves): o jogo
# recalcula esses valores ao carregar, então editá-los não faz nada. O valor
# que persiste ali é o `ltv` — e, no caso do oxigênio, a reserva do traje
# (`oxs`). Por isso a lista abaixo é por atributo, não por propriedade.
#
# Direção da escala, conforme os gatilhos das condições em CharacterCondition:
# Food < 20 "com fome", < 10 "desnutrição", > 120 "comeu demais";
# Rest < 15 "exausto", < -5 "inconsciente", > 85 "energético";
# Comfort < 50 "desconforto", > 80 "muito confortável";
# Health < 30 "problemas de saúde". Ou seja, maior = melhor nos quatro.
# Já os gases inalados são o contrário: 0 = ar limpo.
# A propriedade Rest é o que o jogo mostra como ENERGY, e o tooltip dela revela
# a conta: `Base 80 + Zest x 15`, menos as penalidades por tempo acordado e por
# trabalho — gravadas em <awl> e <wol>, que nos saves analisados vão de -203 a
# +20 (acordado) e -89 a 0 (trabalho). Zerá-las equivale a um turno de sono.
#
# Conferindo essa fórmula contra 1672 tripulantes, ela cai em `v` (33% exatos,
# 46% dentro de ±2) e não em `ltv` (2% / 10%): `v` é o número que aparece na
# tela. O resto do desvio são as condições ativas, que também somam em Rest
# (fome -1, comeu demais -5, desnutrição -2, e assim por diante).
#
# Um item é ("atributo", rótulo, min, max) ou ("filho@atributo", ...).
#
# A barra FOOD não é nenhum dos dois números do <Food>: o tooltip do jogo mostra
# "Estômago" e "No metabolismo", que são os nós <belly> e <stored>. O `v` é a
# constante 100 que vem da definição do personagem (`<l type="Food" v="100"/>`)
# e o `ltv` é a média de longo prazo. Quem enche a barra é o conteúdo do
# estômago, então é ele que fica editável aqui.
NEEDS = {
    "Health": [("v", "needs.health", 0, 300), ("ltv", "needs.healthLt", 0, 300)],
    "Food": [("ltv", "needs.foodLt", 0, 120),
             ("belly@protein", "needs.bellyProtein", 0, 200, "float"),
             ("belly@carbs", "needs.bellyCarbs", 0, 200, "float"),
             ("belly@fat", "needs.bellyFat", 0, 200, "float"),
             ("belly@vitamins", "needs.bellyVitamins", 0, 200, "float"),
             ("belly@toxins", "needs.bellyToxins", 0, 200, "float")],
    "Rest": [("v", "needs.energy", -10, 300), ("ltv", "needs.energyLt", 0, 300),
             ("awl@change", "needs.awakePenalty", -250, 50),
             ("wol@change", "needs.workPenalty", -100, 0)],
    "Comfort": [("ltv", "needs.comfort", 0, 100)],
    "Oxygen": [("oxs", "needs.suitOxygen", 0, 1500)],
    "Mood": [("v", "needs.mood", -100, 120), ("ltv", "needs.moodLt", 0, 100)],
    "Temperature": [("v", "needs.temperature", 0, 100)],
    "Co2Gas": [("v", "needs.co2", 0, 100)],
    "SmokeGas": [("v", "needs.smoke", 0, 100)],
    "HazardousGas": [("v", "needs.hazardous", 0, 100)],
}

# Fórmula da energia máxima, lida do tooltip do jogo ("Base: 80", "Zest 10 x 15").
ENERGY_BASE = 80
ENERGY_PER_ZEST = 15
ZEST_ATTR_ID = "212"

# Uma ração de "Comida espacial" (produto 712), o valor que o próprio jogo dá a
# uma refeição completa. Serve como alvo de "estômago cheio" ao restaurar.
#
# A escala exata da barra não está confirmada: numa leitura medida (estômago
# somando 32,06) o jogo mostrou FOOD 58, o que dá capacidade ~55 — exatamente a
# soma de uma ração. Bate também com a condição "comeu demais", que dispara
# pouco acima disso. Com um único ponto de medição, encher com uma ração é o
# valor defensável; passar disso arriscaria a condição de comer demais.
FULL_MEAL = {"protein": "15.0", "carbs": "20.0", "fat": "10.0",
             "vitamins": "10.0", "toxins": "0.0"}

def needs_hint(lang: str = DEFAULT_LANG) -> str:
    """Aviso mostrado acima da seção de necessidades."""
    return t("needs.hint", lang, base=ENERGY_BASE, perZest=ENERGY_PER_ZEST)


def energy_cap(c) -> int:
    """Energia máxima do personagem, sem nenhuma penalidade."""
    attrs = c.find("pers/attr")
    zest = 0
    if attrs is not None:
        for a in attrs.findall("a"):
            if a.get("id") == ZEST_ATTR_ID:
                zest = _int(a.get("points"))
                break
    return ENERGY_BASE + zest * ENERGY_PER_ZEST


def need_node(prop, ref: str):
    """Resolve "atributo" ou "filho@atributo" dentro de um <props>/<X>."""
    if "@" in ref:
        child_tag, attr = ref.split("@", 1)
        return prop.find(child_tag), attr
    return prop, ref

# Onde um <inv> pode estar pendurado; separa armazéns de buffers de máquina.
RACK_HOLDERS = {"feat", "storage"}


def _ship_label(ship, lang: str = DEFAULT_LANG) -> str:
    return ship.get("sname") or t("ships.unnamed", lang, sid=ship.get("sid"))


def field(sf: SaveFile, el, attr, label, type_="int", **extra):
    value = el.get(attr)
    rec = {
        "path": sf.path_of(el),
        "attr": attr,
        "label": label,
        "type": type_,
        "value": value,
    }
    rec.update(extra)
    return rec


# --------------------------------------------------------------------------
# Aba: Jogo
# --------------------------------------------------------------------------


def view_game(sf: SaveFile, lang: str = DEFAULT_LANG) -> dict:
    root = sf.main
    groups = []

    clock = root.find("clock")
    if clock is not None:
        groups.append({
            "title": t("game.clock", lang),
            "hint": t("game.clockHint", lang),
            "fields": [
                field(sf, clock, "days", t("game.days", lang), min=0),
                field(sf, clock, "hours", t("game.hours", lang), min=0, max=23),
                field(sf, clock, "minutes", t("game.minutes", lang), min=0, max=59),
                field(sf, clock, "turns", t("game.turns", lang), min=0),
            ],
        })

    bank = root.find("playerBank")
    if bank is not None:
        groups.append({
            "title": t("game.bank", lang),
            "hint": t("game.bankHint", lang),
            "fields": [
                field(sf, bank, "ca", t("game.creditsAvailable", lang), min=0),
                field(sf, bank, "cr", t("game.creditsReserved", lang), min=0),
                field(sf, bank, "slp", t("game.sellSeed", lang), min=0),
                field(sf, bank, "blp", t("game.buySeed", lang), min=0),
            ],
        })

    game_fields = [
        field(sf, root, "mode", t("game.mode", lang), "text"),
        field(sf, root, "seed", t("game.seed", lang), "text"),
    ]
    settings = root.find("settings")
    if settings is not None:
        game_fields.append(field(sf, settings, "gm", t("game.gameMode", lang), "text"))
        game_fields.append(field(sf, settings, "f", t("game.playerFaction", lang), "select",
                                 options=_faction_options(lang)))
    groups.append({"title": t("game.match", lang), "fields": game_fields})

    diff = root.find("settings/diff")
    if diff is not None:
        opts_diff = [{"value": v, "label": v} for v in ("VeryEasy", "Easy", "Normal", "Hard", "VeryHard")]
        name = GD.name("difficulties", diff.get("id"),
                       t("game.difficultyCustom", lang), lang)
        groups.append({
            "title": t("game.difficulty", lang, name=name),
            "fields": [
                field(sf, diff, "moodDifficulty", t("game.moodDifficulty", lang), "select", options=opts_diff),
                field(sf, diff, "npcTargeting", t("game.npcTargeting", lang), "select", options=opts_diff),
                field(sf, diff, "questDifficulty", t("game.questDifficulty", lang), "select", options=opts_diff),
                field(sf, diff, "sandbox", t("game.sandbox", lang), "bool"),
                field(sf, diff, "enemiesEnabled", t("game.enemies", lang), "bool"),
                field(sf, diff, "friendsEnabled", t("game.friends", lang), "bool"),
                field(sf, diff, "loversEnabled", t("game.lovers", lang), "bool"),
            ],
        })

    mode_settings = root.find("settings/diff/modeSettings")
    if mode_settings is not None:
        fields = []
        for attr, value in mode_settings.attrib.items():
            kind = "bool" if value in ("true", "false") else "text"
            fields.append(field(sf, mode_settings, attr, attr, kind))
        groups.append({
            "title": t("game.scenarioRules", lang),
            "hint": t("game.scenarioHint", lang),
            "fields": fields,
        })

    return {"groups": groups}


def _faction_options(lang: str):
    return [{"value": c["id"], "label": c["label"]}
            for c in GD.catalog("factions", lang=lang)]


# --------------------------------------------------------------------------
# Aba: Tripulação
# --------------------------------------------------------------------------


def player_ship_ids(sf: SaveFile) -> set:
    """sids das naves do jogador, lidos das frotas do mapa estelar."""
    out = set()
    for fleet in sf.main.iter("f"):
        if fleet.get("isPlayer") != "true":
            continue
        for l in fleet.findall("createdShips/l"):
            if l.get("createdShipId"):
                out.add(l.get("createdShipId"))
    return out


def _main_side(entries) -> str:
    """Lado dominante entre os tripulantes — de quem a nave é."""
    counts = {}
    for e in entries:
        counts[e["side"]] = counts.get(e["side"], 0) + 1
    return max(counts, key=counts.get) if counts else ""


def craft_label(craft, lang: str = DEFAULT_LANG) -> str:
    tipo = GD.name("crafts", craft.get("cid"), "", lang)
    name = craft.get("cname") or f"#{craft.get('id')}"
    return f"{tipo}: {name}" if tipo else name


def crew_of_ship(sf: SaveFile, ship, lang: str = DEFAULT_LANG) -> list:
    """Tripulantes da nave, incluindo quem está pilotando uma craft dela.

    Retorna pares (elemento <c>, onde) — `onde` vazio para quem está a bordo.
    """
    out = []
    chars = ship.find("characters")
    for c in (chars.findall("c") if chars is not None else []):
        out.append((c, ""))
    sid = ship.get("sid")
    if not sid:
        return out
    for _doc, craft in sf.crafts():
        if craft.get("homeSid") != sid:
            continue
        inner = craft.find("characters")
        for c in (inner.findall("c") if inner is not None else []):
            out.append((c, craft_label(craft, lang)))
    return out


def view_crew(sf: SaveFile, lang: str = DEFAULT_LANG) -> dict:
    player_sids = player_ship_ids(sf)
    ships = []
    seen = set()
    for doc, ship in sf.ships():
        crew = crew_of_ship(sf, ship, lang)
        if not crew:
            continue
        seen.update(id(c) for c, _ in crew)
        entries = []
        for c, where in crew:
            rec = _character(sf, c, lang)
            rec["where"] = where
            entries.append(rec)
        is_player = (ship.get("sid") in player_sids
                     or any(c.get("side") == "Player" for c, _ in crew))
        main_side = "Player" if is_player else _main_side(entries)
        ships.append({
            "ship": _ship_label(ship, lang),
            "sid": ship.get("sid"),
            "path": sf.path_of(ship),
            "doc": doc,
            "inSector": doc == MAIN_DOC,
            # A frota do mapa estelar diz de quem é a nave; se o save não
            # tiver essa informação, ter tripulante do lado Player serve.
            "isPlayer": is_player,
            # Naves recebem visitas (mercadores usando as camas médicas, por
            # exemplo) que ficam no mesmo <characters>. `mainSide` é de quem a
            # nave é; o resto a interface trata como visitante.
            "mainSide": main_side,
            "ownCount": sum(1 for e in entries if e["side"] == main_side),
            "visitorCount": sum(1 for e in entries if e["side"] != main_side),
            "characters": entries,
        })

    # Crafts cuja nave-mãe não está neste save entram como grupo próprio, para
    # que nenhum tripulante fique invisível.
    for doc, craft in sf.crafts():
        inner = craft.find("characters")
        orphans = [c for c in (inner.findall("c") if inner is not None else [])
                   if id(c) not in seen]
        if not orphans:
            continue
        entries = [dict(_character(sf, c, lang), where=craft_label(craft, lang))
                   for c in orphans]
        main_side = craft.get("side") or _main_side(entries)
        ships.append({
            "ship": craft_label(craft, lang),
            "sid": craft.get("homeSid") or craft.get("id"),
            "path": sf.path_of(craft),
            "doc": doc,
            "inSector": doc == MAIN_DOC,
            "isCraft": True,
            "isPlayer": craft.get("side") == "Player",
            "mainSide": main_side,
            "ownCount": sum(1 for e in entries if e["side"] == main_side),
            "visitorCount": sum(1 for e in entries if e["side"] != main_side),
            "characters": entries,
        })
    return {
        "ships": ships,
        "needsHint": needs_hint(lang),
        "traitCatalog": GD.catalog("traits", with_desc=True, lang=lang),
        "conditionCatalog": GD.catalog("conditions", with_desc=True, lang=lang),
        "priorityOptions": GD.enum_labels("WorkPriority", lang),
    }


def _character(sf: SaveFile, c, lang: str = DEFAULT_LANG) -> dict:
    out = {
        "cid": c.get("cid"),
        "path": sf.path_of(c),
        "name": c.get("name") or "",
        "lname": c.get("lname") or "",
        "side": c.get("side") or "",
        "faction": GD.name("factions", c.get("fac"), c.get("fac") or "", lang),
        "task": c.get("task") or "",
        "identity": [
            field(sf, c, "name", t("crew.firstName", lang), "text"),
            field(sf, c, "lname", t("crew.lastName", lang), "text"),
        ],
        "needs": [], "attributes": [], "skills": [],
        "traits": [], "conditions": [], "jobs": [],
    }

    props = c.find("props")
    if props is not None:
        for prop in props:
            for spec in NEEDS.get(prop.tag, [("v", prop.tag, 0, 100)]):
                ref, label, lo, hi = spec[:4]
                kind = spec[4] if len(spec) > 4 else "int"
                node, attr = need_node(prop, ref)
                if node is None or node.get(attr) is None:
                    continue
                if prop.tag == "Rest" and attr in ("v", "ltv"):
                    hi = max(hi, energy_cap(c))
                out["needs"].append(
                    field(sf, node, attr, t(label, lang), kind, min=lo, max=hi))

    pers = c.find("pers")
    if pers is None:
        return out

    attrs = pers.find("attr")
    if attrs is not None:
        for a in attrs.findall("a"):
            out["attributes"].append(
                field(sf, a, "points", GD.name("attributes", a.get("id"), lang=lang),
                      min=1, max=10)
            )

    skills = pers.find("skills")
    if skills is not None:
        rows = []
        for s in skills.findall("s"):
            info = GD.skill(s.get("sk"))
            rows.append({
                "sk": s.get("sk"),
                "label": GD.skill_label(s.get("sk"), lang),
                "sort": info.get("sort", 99),
                "hidden": not info.get("show", True),
                "level": field(sf, s, "level", t("crew.level", lang), min=0, max=8),
                "max": field(sf, s, "mxn", t("crew.max", lang), min=0, max=8),
                "exp": field(sf, s, "exp", t("crew.exp", lang), min=0),
            })
        rows.sort(key=lambda r: (r["hidden"], r["sort"]))
        out["skills"] = rows

    traits = pers.find("traits")
    if traits is not None:
        out["traitsPath"] = sf.path_of(traits)
        for trait in traits.findall("t"):
            out["traits"].append({
                "path": sf.path_of(trait),
                "id": trait.get("id"),
                "label": GD.name("traits", trait.get("id"), lang=lang),
                "desc": GD.desc("traits", trait.get("id"), lang),
            })

    conditions = pers.find("conditions")
    if conditions is not None:
        out["conditionsPath"] = sf.path_of(conditions)
        for cond in conditions.findall("c"):
            if cond.get("id") in (None, "0"):
                continue  # slots vazios que o jogo mantem reservados
            out["conditions"].append({
                "path": sf.path_of(cond),
                "id": cond.get("id"),
                "label": GD.name("conditions", cond.get("id"), lang=lang),
                "desc": GD.desc("conditions", cond.get("id"), lang),
                "level": field(sf, cond, "level", t("crew.level", lang), min=0, max=10),
            })

    jobs = pers.find("jobsetting")
    if jobs is not None:
        prof_label = {o["value"]: o["label"] for o in GD.enum_labels("Profession", lang)}
        priorities = GD.enum_labels("WorkPriority", lang)
        for j in jobs.findall("j"):
            prof = j.get("profession")
            out["jobs"].append(
                field(sf, j, "priority", prof_label.get(prof, prof), "select",
                      options=priorities)
            )

    return out


# --------------------------------------------------------------------------
# Aba: Armazenamento
# --------------------------------------------------------------------------


def view_storage(sf: SaveFile, lang: str = DEFAULT_LANG) -> dict:
    ships = []
    for doc, ship in sf.ships():
        stacks = []
        for inv in ship.iter("inv"):
            holder = sf.parent_of(inv)
            if holder is None:
                continue
            kind = "rack" if holder.tag in RACK_HOLDERS else "machine"
            tile = _owning_tile(sf, inv)
            for s in inv.findall("s"):
                ident = s.get("elementaryId")
                if ident is None:
                    continue
                name, table = GD.stuff(ident, lang)
                stacks.append({
                    "path": sf.path_of(s),
                    "invPath": sf.path_of(inv),
                    "id": ident,
                    "name": name,
                    "table": table,
                    "kind": kind,
                    "holder": holder.tag,
                    "where": tile,
                    "amount": _int(s.get("inStorage")),
                    "amountField": field(sf, s, "inStorage", name, min=0, max=9999),
                })
        if not stacks:
            continue

        totals = {}
        for st in stacks:
            row = totals.setdefault(st["id"], {"id": st["id"], "name": st["name"],
                                               "table": st["table"], "rack": 0,
                                               "machine": 0, "rackStacks": 0,
                                               "stacks": 0})
            row[st["kind"]] += st["amount"]
            row["stacks"] += 1
            if st["kind"] == "rack":
                row["rackStacks"] += 1
        summary = sorted(totals.values(), key=lambda r: -(r["rack"] + r["machine"]))
        for row in summary:
            row["total"] = row["rack"] + row["machine"]

        ships.append({
            "ship": _ship_label(ship, lang),
            "sid": ship.get("sid"),
            "doc": doc,
            "inSector": doc == MAIN_DOC,
            "summary": summary,
            "stacks": sorted(stacks, key=lambda s: (s["kind"] != "rack", s["name"])),
        })

    return {"ships": ships, "catalog": GD.storables(lang)}


def _owning_tile(sf: SaveFile, node) -> str:
    """Coordenadas do objeto que contem este inventario, para orientacao."""
    cur = sf.parent_of(node)
    while cur is not None:
        if cur.tag in ("l", "e") and cur.get("x") is not None:
            return f"({cur.get('x')}, {cur.get('y')})"
        cur = sf.parent_of(cur)
    return ""


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Aba: Pesquisa
# --------------------------------------------------------------------------


def view_research(sf: SaveFile, lang: str = DEFAULT_LANG) -> dict:
    research = sf.main.find("research")
    if research is None:
        return {"techs": [], "statesPath": None}

    states = research.find("states")
    known = {}
    if states is not None:
        for l in states.findall("l"):
            known[l.get("techId")] = l

    techs = []
    for tech_id, rec in GD.raw.get("techs", {}).items():
        label = GD.name("techs", tech_id, "", lang)
        if not label:
            continue
        node = known.get(tech_id)
        stages = []
        complete = False
        if node is not None:
            stage_states = node.find("stageStates")
            for st in (stage_states if stage_states is not None else []):
                blocks = st.find("blocksDone")
                stages.append({
                    "path": sf.path_of(st),
                    "stage": st.get("stage"),
                    "done": st.get("done") == "true",
                    "doneField": field(sf, st, "done", t("research.complete", lang), "bool"),
                    "blocks": [
                        field(sf, blocks, lvl, f"{t('crew.level', lang)} {lvl[-1]}", min=0)
                        for lvl in ("level1", "level2", "level3")
                    ] if blocks is not None else [],
                })
            complete = bool(stages) and all(s["done"] for s in stages)
        techs.append({
            "id": tech_id,
            "label": label,
            "desc": GD.desc("techs", tech_id, lang),
            "inSave": node is not None,
            "path": sf.path_of(node) if node is not None else None,
            "stages": stages,
            "complete": complete,
            "cost": rec.get("stages", []),
        })
    techs.sort(key=lambda t: (not t["inSave"], t["label"].lower()))

    return {
        "techs": techs,
        "statesPath": sf.path_of(states) if states is not None else None,
        "treeId": research.get("treeId"),
    }


def research_state_payload(tech_id: str) -> dict:
    """Bloco <l> completo para marcar uma tecnologia como pesquisada."""
    stages = GD.entry("techs", tech_id).get("stages") or [{"stage": "1", "level1": "0",
                                                           "level2": "0", "level3": "0"}]
    return {
        "tag": "l",
        "attrs": {"techId": tech_id, "paused": "false",
                  "activeStageIndex": str(len(stages) - 1)},
        "stages": stages,
    }


# --------------------------------------------------------------------------
# Aba: Naves
# --------------------------------------------------------------------------


def view_ships(sf: SaveFile, lang: str = DEFAULT_LANG) -> dict:
    ships = []
    for doc, ship in sf.ships():
        chars = ship.find("characters")
        crew = len(chars.findall("c")) if chars is not None else 0
        tiles = len(ship.findall("e"))
        ships.append({
            "sid": ship.get("sid"),
            "path": sf.path_of(ship),
            "doc": doc,
            "inSector": doc == MAIN_DOC,
            "name": ship.get("sname") or "",
            "crew": crew,
            "tiles": tiles,
            "size": f"{ship.get('sx')}×{ship.get('sy')}",
            "isStation": ship.get("sta") == "1",
            "explored": ship.get("unex") != "1",
            "fields": [
                field(sf, ship, "sname", t("ships.name", lang), "text"),
                field(sf, ship, "sid", t("ships.id", lang), "int"),
                field(sf, ship, "fog", t("ships.fog", lang), "bool"),
            ] + ([field(sf, ship, "unex", t("ships.unexplored", lang), "text")]
                 if ship.get("unex") is not None else []),
        })
    return {"ships": ships}


# --------------------------------------------------------------------------
# Aba: Facções
# --------------------------------------------------------------------------


def view_factions(sf: SaveFile, lang: str = DEFAULT_LANG) -> dict:
    rows = []
    stance_options = GD.enum_labels("Stance", lang) or [
        {"value": v, "label": v} for v in ("Player", "Neutral", "Enemies", "Friends", "NotSet")
    ]
    for l in sf.main.findall("hostmap/map/l"):
        rows.append({
            "path": sf.path_of(l),
            "s1": l.get("s1"),
            "s2": l.get("s2"),
            "fields": [
                field(sf, l, "stance", t("factions.stance", lang), "select", options=stance_options),
                field(sf, l, "relationship", t("factions.relationship", lang), min=-100, max=100),
                field(sf, l, "patience", t("factions.patience", lang), min=0, max=100),
                field(sf, l, "accessTrade", t("factions.trade", lang), "bool"),
                field(sf, l, "accessShip", t("factions.shipAccess", lang), "bool"),
                field(sf, l, "accessVision", t("factions.vision", lang), "bool"),
                field(sf, l, "accessServices", t("factions.services", lang), "bool"),
                field(sf, l, "accessHire", t("factions.hire", lang), "bool"),
            ],
        })
    return {"rows": rows}


# --------------------------------------------------------------------------
# Aba: XML (navegador genérico)
# --------------------------------------------------------------------------


def view_raw(sf: SaveFile, path: str = "", lang: str = DEFAULT_LANG) -> dict:
    if not path:
        path = f"{MAIN_DOC}#"
    el = sf.get(path)
    doc_key, _, inner = path.partition("#")

    # Trilha: a raiz do documento e depois um passo por indice de filho.
    root_path = f"{doc_key}#"
    breadcrumb = [{"path": root_path, "tag": sf.get(root_path).tag, "doc": doc_key}]
    parts = [p for p in inner.split("/") if p != ""]
    for i in range(len(parts)):
        p = root_path + "/".join(parts[: i + 1])
        breadcrumb.append({"path": p, "tag": sf.get(p).tag})

    prefix = path if path.endswith("#") else path + "/"
    children = [{
        "path": f"{prefix}{i}",
        "tag": child.tag,
        "childCount": len(child),
        "attrs": dict(child.attrib),
        "summary": _summary(child, lang),
    } for i, child in enumerate(el)]

    return {
        "path": path,
        "tag": el.tag,
        "doc": doc_key,
        "documents": [
            {"key": d.key, "path": f"{d.key}#", "label": _doc_label(d, lang)}
            for d in sf.docs.values()
        ],
        "breadcrumb": breadcrumb,
        "attrs": [field(sf, el, k, k, "text") for k in el.attrib],
        "text": el.text if (el.text or "").strip() else None,
        "children": children,
        "total": len(children),
    }


def _doc_label(doc, lang: str = DEFAULT_LANG) -> str:
    if doc.key == MAIN_DOC:
        return t("raw.mainDoc", lang)
    return f"{doc.root.get('sname') or doc.key} ({doc.key})"


def _summary(el, lang: str = DEFAULT_LANG) -> str:
    """Rotulo curto para a lista do navegador de XML."""
    for key in ("sname", "name", "sn", "profession", "type", "techId", "elementaryId", "id", "cid", "mid"):
        val = el.get(key)
        if val:
            if key in ("elementaryId",):
                return GD.stuff(val, lang)[0]
            if key == "techId":
                return GD.name("techs", val, val, lang)
            if key == "name" and el.get("lname"):
                return f"{val} {el.get('lname')}"
            return str(val)
    return ""


def search(sf: SaveFile, query: str, limit: int = 200,
           lang: str = DEFAULT_LANG) -> dict:
    """Busca por tag, nome de atributo ou valor em toda a arvore."""
    needle = query.strip().lower()
    hits = []
    if not needle:
        return {"query": query, "hits": hits, "truncated": False}

    for el in sf.iter_all():
        if len(hits) >= limit:
            return {"query": query, "hits": hits, "truncated": True}
        matched = None
        if needle in el.tag.lower():
            matched = f"<{el.tag}>"
        else:
            for key, val in el.attrib.items():
                if needle in key.lower() or needle in str(val).lower():
                    matched = f'{key}="{val}"'
                    break
        if matched:
            node_path = sf.path_of(el)
            hits.append({
                "path": node_path,
                "doc": node_path.split("#", 1)[0],
                "tag": el.tag,
                "match": matched,
                "attrs": dict(el.attrib),
                "summary": _summary(el, lang),
            })
    return {"query": query, "hits": hits, "truncated": False}
