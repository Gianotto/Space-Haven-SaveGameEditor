"""Acoes em lote — o que seria tedioso de fazer campo a campo na interface.

Todas retornam a quantidade de alteracoes feitas e deixam a arvore pronta
para ser gravada por `SaveFile.save`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .gamedata import GAMEDATA as GD
from .savefile import SaveFile, SaveError, _insert_child
from .views import (FULL_MEAL, RACK_HOLDERS, crew_of_ship, energy_cap,
                    need_node)


def dispatch(sf: SaveFile, name: str, params: dict) -> dict:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise SaveError(f"ação desconhecida: {name!r}")
    return handler(sf, params or {})


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _finish(sf: SaveFile, changed: int, touched, structural: bool = False) -> dict:
    """Marca como alterados os documentos tocados e reindexa se preciso.

    Um save tem varios arquivos (`game` e cada nave em `ships/`); so os que
    realmente mudaram sao regravados.
    """
    for el in touched:
        sf.mark_dirty(el)
    if structural:
        sf.reindex()
    return {"changed": changed}


# --------------------------------------------------------------------------
# Tripulação
# --------------------------------------------------------------------------

# O que "restaurar" significa em cada propriedade: (propriedade, atributo, alvo).
#
# Só entram aqui os atributos que o save realmente guarda — em Food, Comfort e
# Oxygen o `v` gravado é constante e o jogo o recalcula ao carregar, então
# escrever nele não teria efeito nenhum (ver NEEDS em views.py).
#
# `_RESTORE_KEEP_HIGHER` são os que podem passar de 100 legitimamente (saúde
# aumentada, descanso numa cama boa, humor alto): nesses, restaurar nunca
# reduz um valor que já estava melhor.
# Em energia (Rest) o alvo é o teto do próprio personagem (80 + Pique x 15) e
# as duas penalidades — tempo acordado e trabalho — vão a zero: é isso que o
# jogo desconta do número mostrado como ENERGY.
_RESTORE_GOOD = (
    ("Health", "v", 100), ("Health", "ltv", 100),
    ("Food", "ltv", 100),
    ("Rest", "v", "energy"), ("Rest", "ltv", "energy"),
    ("Rest", "awl@change", 0), ("Rest", "wol@change", 0),
    ("Comfort", "ltv", 100),
    ("Mood", "v", 100), ("Mood", "ltv", 100),
)
_RESTORE_KEEP_HIGHER = {("Health", "v"), ("Health", "ltv"),
                        ("Rest", "v"), ("Rest", "ltv"), ("Mood", "v")}
# Gases inalados: o ideal e zero.
_RESTORE_ZERO = ("Co2Gas", "SmokeGas", "HazardousGas")


def _characters(sf: SaveFile, params: dict):
    """Personagens alvo, do mais especifico para o mais amplo:

      `path`     -> um personagem
      `shipPath` -> todos os tripulantes daquela nave
      nenhum     -> todos os tripulantes do lado Player, em todas as naves

    O atributo `cid` do save nao identifica o individuo (todos os humanos
    compartilham o mesmo valor), por isso o alvo e sempre o path do no.
    """
    path = params.get("path")
    if path:
        el = sf.get(path)
        if el.tag != "c":
            raise SaveError(f"{path} não é um personagem")
        yield el
        return

    # `side` limita a uma facção: uma nave costuma ter visitantes de outras
    # (mercadores usando as camas médicas) que não deveriam entrar numa ação
    # feita para a própria tripulação.
    side = params.get("side")
    keep = (lambda c: side is None or c.get("side") == side)

    ship_path = params.get("shipPath")
    if ship_path:
        node = sf.get(ship_path)
        if node.tag == "ship":
            # Inclui quem está pilotando uma craft da nave.
            yield from (c for c, _where in crew_of_ship(sf, node) if keep(c))
            return
        if node.tag == "c" and node.get("cname") is not None:
            inner = node.find("characters")           # grupo de uma craft solta
            yield from (c for c in (inner.findall("c") if inner is not None else [])
                        if keep(c))
            return
        raise SaveError(f"{ship_path} não é uma nave")

    for _doc, ship in sf.ships():
        for c, _where in crew_of_ship(sf, ship):
            if c.get("side") == "Player":
                yield c
    # Crafts sem nave-mãe neste save.
    homed = {ship.get("sid") for _d, ship in sf.ships()}
    for _doc, craft in sf.crafts():
        if craft.get("homeSid") in homed:
            continue
        inner = craft.find("characters")
        for c in (inner.findall("c") if inner is not None else []):
            if c.get("side") == "Player":
                yield c


def act_restore(sf: SaveFile, params: dict) -> dict:
    changed, touched, structural = 0, set(), False
    for c in _characters(sf, params):
        props = c.find("props")
        if props is None:
            continue
        for tag, ref, target in _RESTORE_GOOD:
            prop = props.find(tag)
            if prop is None:
                continue
            node, attr = need_node(prop, ref)
            if node is None or node.get(attr) is None:
                continue
            if target == "energy":
                target = energy_cap(c)
            if (tag, attr) in _RESTORE_KEEP_HIGHER and _num(node.get(attr)) >= target:
                continue
            if node.get(attr) != str(target):
                node.set(attr, str(target))
                changed += 1
                touched.add(c)
        for tag in _RESTORE_ZERO:
            prop = props.find(tag)
            if prop is not None and prop.get("v") not in (None, "0"):
                prop.set("v", "0")
                changed += 1
                touched.add(c)
        # A barra de comida vem do conteúdo do estômago, não dos números do
        # <Food>: enche com uma ração e tira as toxinas.
        belly = props.find("Food/belly")
        if belly is not None:
            for key, value in FULL_MEAL.items():
                if belly.get(key) is not None and belly.get(key) != value:
                    belly.set(key, value)
                    changed += 1
                    touched.add(c)
        # Condicoes negativas tambem seguram o personagem.
        conditions = c.find("pers/conditions")
        if conditions is not None and params.get("clearConditions"):
            for cond in list(conditions.findall("c")):
                if cond.get("id") not in (None, "0"):
                    touched.add(c)
                    conditions.remove(cond)
                    changed += 1
                    structural = True
    return _finish(sf, changed, touched, structural)


def act_max_skills(sf: SaveFile, params: dict) -> dict:
    level = str(params.get("level", 8))
    only_capped = params.get("onlyWithinMax", True)
    changed, touched = 0, set()
    for c in _characters(sf, params):
        skills = c.find("pers/skills")
        if skills is None:
            continue
        for s in skills.findall("s"):
            if not GD.skill(s.get("sk")).get("show", True):
                continue
            target = level
            if only_capped:
                cap = s.get("mxn") or "0"
                # `mxn` e o teto que o personagem consegue atingir naquela pericia.
                target = cap if int(cap) < int(level) else level
            if int(target) <= 0:
                continue
            if s.get("level") != target:
                s.set("level", target)
                changed += 1
                touched.add(c)
    return _finish(sf, changed, touched)


def act_raise_skill_caps(sf: SaveFile, params: dict) -> dict:
    """Sobe o teto (`mxn`) das pericias, permitindo treinar alem do sorteado."""
    cap = str(params.get("cap", 8))
    changed, touched = 0, set()
    for c in _characters(sf, params):
        skills = c.find("pers/skills")
        if skills is None:
            continue
        for s in skills.findall("s"):
            if not GD.skill(s.get("sk")).get("show", True):
                continue
            if s.get("mxn") != cap:
                s.set("mxn", cap)
                changed += 1
                touched.add(c)
    return _finish(sf, changed, touched)


def act_max_attributes(sf: SaveFile, params: dict) -> dict:
    points = str(params.get("points", 10))
    changed, touched = 0, set()
    for c in _characters(sf, params):
        attrs = c.find("pers/attr")
        if attrs is None:
            continue
        for a in attrs.findall("a"):
            if a.get("points") != points:
                a.set("points", points)
                changed += 1
                touched.add(c)
    return _finish(sf, changed, touched)


def act_add_trait(sf: SaveFile, params: dict) -> dict:
    trait_id = str(params["traitId"])
    changed, touched = 0, set()
    for c in _characters(sf, params):
        traits = c.find("pers/traits")
        if traits is None:
            continue
        if any(t.get("id") == trait_id for t in traits.findall("t")):
            continue
        touched.add(c)
        _insert_child(traits, ET.Element("t", {"id": trait_id}))
        changed += 1
    return _finish(sf, changed, touched, structural=bool(changed))


def act_clear_conditions(sf: SaveFile, params: dict) -> dict:
    changed, touched = 0, set()
    for c in _characters(sf, params):
        conditions = c.find("pers/conditions")
        if conditions is None:
            continue
        for cond in list(conditions.findall("c")):
            if cond.get("id") not in (None, "0"):
                touched.add(c)
                conditions.remove(cond)
                changed += 1
    return _finish(sf, changed, touched, structural=bool(changed))


def act_set_all_jobs(sf: SaveFile, params: dict) -> dict:
    priority = params.get("priority", "Normal")
    changed, touched = 0, set()
    for c in _characters(sf, params):
        jobs = c.find("pers/jobsetting")
        if jobs is None:
            continue
        for j in jobs.findall("j"):
            if j.get("priority") != priority:
                j.set("priority", priority)
                changed += 1
                touched.add(c)
    return _finish(sf, changed, touched)


# --------------------------------------------------------------------------
# Armazenamento
# --------------------------------------------------------------------------


def _racks(sf: SaveFile, sid: str | None):
    """Inventarios de armazem (nao os buffers internos de maquinas)."""
    for _doc, ship in sf.ships():
        if sid is not None and ship.get("sid") != str(sid):
            continue
        for inv in ship.iter("inv"):
            holder = sf.parent_of(inv)
            if holder is not None and holder.tag in RACK_HOLDERS:
                yield ship, inv


def act_set_stacks(sf: SaveFile, params: dict) -> dict:
    """Define a quantidade de um recurso em todas as pilhas de armazem."""
    ident = str(params["elementaryId"])
    amount = str(max(0, int(params.get("amount", 0))))
    sid = params.get("sid")
    changed, touched = 0, set()
    for ship, inv in _racks(sf, sid):
        for s in inv.findall("s"):
            if s.get("elementaryId") == ident and s.get("inStorage") != amount:
                s.set("inStorage", amount)
                changed += 1
                touched.add(ship)
    return _finish(sf, changed, touched)


def act_fill_all(sf: SaveFile, params: dict) -> dict:
    """Preenche todas as pilhas de armazem existentes com uma quantidade."""
    amount = str(max(0, int(params.get("amount", 50))))
    sid = params.get("sid")
    changed, touched = 0, set()
    for ship, inv in _racks(sf, sid):
        for s in inv.findall("s"):
            if s.get("inStorage") != amount:
                s.set("inStorage", amount)
                changed += 1
                touched.add(ship)
    return _finish(sf, changed, touched)


def act_add_one_of_each(sf: SaveFile, params: dict) -> dict:
    """Coloca uma pilha de cada recurso/item conhecido no armazém escolhido.

    `scope` limita a produtos ou a itens; o que já estiver lá tem a quantidade
    ajustada em vez de duplicar a pilha.
    """
    inv = sf.get(params["invPath"])
    amount = str(max(0, int(params.get("amount", 1))))
    scope = params.get("scope") or "all"
    tables = {"products": ("products",), "items": ("items",)}.get(scope, ("products", "items"))

    existing = {s.get("elementaryId"): s for s in inv.findall("s")}
    added = updated = 0
    sf.mark_dirty(inv)
    for entry in GD.storables():
        if entry["table"] not in tables:
            continue
        stack = existing.get(entry["id"])
        if stack is not None:
            if stack.get("inStorage") != amount:
                stack.set("inStorage", amount)
                updated += 1
            continue
        _insert_child(inv, ET.Element("s", {
            "elementaryId": entry["id"], "inStorage": amount,
            "onTheWayIn": "0", "onTheWayOut": "0",
        }))
        added += 1

    if added:
        sf.reindex()
    return {"changed": added + updated, "added": added, "updated": updated}


def act_add_stack(sf: SaveFile, params: dict) -> dict:
    """Cria uma pilha nova de um recurso dentro de um inventario."""
    inv = sf.get(params["invPath"])
    ident = str(params["elementaryId"])
    amount = str(max(0, int(params.get("amount", 1))))
    for s in inv.findall("s"):
        if s.get("elementaryId") == ident:
            s.set("inStorage", amount)
            sf.mark_dirty(inv)
            return {"changed": 1, "merged": True}
    sf.mark_dirty(inv)
    _insert_child(inv, ET.Element("s", {
        "elementaryId": ident, "inStorage": amount,
        "onTheWayIn": "0", "onTheWayOut": "0",
    }))
    sf.reindex()
    return {"changed": 1, "merged": False}


# --------------------------------------------------------------------------
# Pesquisa
# --------------------------------------------------------------------------


def _state_node(tech_id: str) -> ET.Element:
    stages = GD.entry("techs", tech_id).get("stages") or [
        {"stage": "1", "level1": "0", "level2": "0", "level3": "0"}
    ]
    node = ET.Element("l", {"techId": str(tech_id), "paused": "false",
                            "activeStageIndex": str(len(stages) - 1)})
    holder = ET.SubElement(node, "stageStates")
    for st in stages:
        stage_el = ET.SubElement(holder, "l", {"stage": st["stage"], "done": "true"})
        ET.SubElement(stage_el, "blocksDone", {
            "level1": st["level1"], "level2": st["level2"], "level3": st["level3"],
        })
    return node


def act_complete_research(sf: SaveFile, params: dict) -> dict:
    """Marca uma tecnologia (ou todas) como pesquisada."""
    research = sf.main.find("research")
    if research is None:
        raise SaveError("este save não tem árvore de pesquisa")
    states = research.find("states")
    if states is None:
        states = ET.SubElement(research, "states")

    wanted = params.get("techIds")
    if not wanted:
        wanted = list(GD.raw.get("techs", {}))
    wanted = [str(t) for t in wanted]

    existing = {l.get("techId"): l for l in states.findall("l")}
    changed = 0
    structural = False

    for tech_id in wanted:
        node = existing.get(tech_id)
        if node is None:
            _insert_child(states, _state_node(tech_id))
            existing[tech_id] = states[-1]
            changed += 1
            structural = True
            continue
        stage_states = node.find("stageStates")
        if stage_states is None or not len(stage_states):
            for child in list(node):
                node.remove(child)
            fresh = _state_node(tech_id)
            for child in fresh:
                node.append(child)
            node.set("activeStageIndex", fresh.get("activeStageIndex"))
            changed += 1
            structural = True
            continue
        for st in stage_states:
            if st.get("done") != "true":
                st.set("done", "true")
                changed += 1
            blocks = st.find("blocksDone")
            cost = _stage_cost(tech_id, st.get("stage"))
            if blocks is not None and cost:
                for lvl in ("level1", "level2", "level3"):
                    if blocks.get(lvl) != cost[lvl]:
                        blocks.set(lvl, cost[lvl])
                        changed += 1

    if changed:
        sf.dirty = True
    if structural:
        sf.reindex()
    return {"changed": changed}


def act_reset_research(sf: SaveFile, params: dict) -> dict:
    """Volta uma tecnologia para nao-pesquisada, removendo o estado dela."""
    states = sf.main.find("research/states")
    if states is None:
        return {"changed": 0}
    wanted = {str(t) for t in (params.get("techIds") or [])}
    changed = 0
    for l in list(states.findall("l")):
        if not wanted or l.get("techId") in wanted:
            states.remove(l)
            changed += 1
    if changed:
        sf.dirty = True
        sf.reindex()
    return {"changed": changed}


def _stage_cost(tech_id: str, stage: str) -> dict | None:
    for st in GD.entry("techs", tech_id).get("stages") or []:
        if st["stage"] == stage:
            return st
    return None


_HANDLERS = {
    "crew.restore": act_restore,
    "crew.maxSkills": act_max_skills,
    "crew.raiseSkillCaps": act_raise_skill_caps,
    "crew.maxAttributes": act_max_attributes,
    "crew.addTrait": act_add_trait,
    "crew.clearConditions": act_clear_conditions,
    "crew.setAllJobs": act_set_all_jobs,
    "storage.setStacks": act_set_stacks,
    "storage.fillAll": act_fill_all,
    "storage.addStack": act_add_stack,
    "storage.addOneOfEach": act_add_one_of_each,
    "research.complete": act_complete_research,
    "research.reset": act_reset_research,
}
