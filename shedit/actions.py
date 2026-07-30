"""Acoes em lote — o que seria tedioso de fazer campo a campo na interface.

Todas retornam a quantidade de alteracoes feitas e deixam a arvore pronta
para ser gravada por `SaveFile.save`.
"""

from __future__ import annotations

import copy
import random
import xml.etree.ElementTree as ET

from .gamedata import GAMEDATA as GD
from .savefile import SaveFile, SaveError, _insert_child, _remove_child
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


def _restore_one(c, clear_conditions: bool = False) -> tuple:
    """Devolve as necessidades de um personagem ao melhor estado.

    Retorna (quantas alteracoes, se mexeu na estrutura da arvore).
    """
    changed, structural = 0, False
    props = c.find("props")
    if props is None:
        return changed, structural
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
    for tag in _RESTORE_ZERO:
        prop = props.find(tag)
        if prop is not None and prop.get("v") not in (None, "0"):
            prop.set("v", "0")
            changed += 1
    # A barra de comida vem do conteúdo do estômago, não dos números do
    # <Food>: enche com uma ração e tira as toxinas.
    belly = props.find("Food/belly")
    if belly is not None:
        for key, value in FULL_MEAL.items():
            if belly.get(key) is not None and belly.get(key) != value:
                belly.set(key, value)
                changed += 1
    # Condicoes negativas tambem seguram o personagem.
    conditions = c.find("pers/conditions")
    if conditions is not None and clear_conditions:
        for cond in list(conditions.findall("c")):
            if cond.get("id") not in (None, "0"):
                conditions.remove(cond)
                changed += 1
                structural = True
    return changed, structural


def act_restore(sf: SaveFile, params: dict) -> dict:
    changed, touched, structural = 0, set(), False
    for c in _characters(sf, params):
        n, struct = _restore_one(c, params.get("clearConditions"))
        if n:
            touched.add(c)
        changed += n
        structural = structural or struct
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


# --------------------------------------------------------------------------
# Novo tripulante
# --------------------------------------------------------------------------

# Criar alguem do zero exigiria reproduzir de memoria uma ficha inteira —
# <props>, <ai>, <pers> com onze sub-nos, <colors>, <inv> — e qualquer peca
# faltando so apareceria como um save que o jogo recusa a carregar. Em vez
# disso, copiamos um tripulante que ja esta na nave e trocamos o que e
# individual. O alvo dessa limpeza e a forma mais enxuta que aparece no proprio
# save (personagens sem trabalho, equipamento ou historico), o que mantem tudo
# dentro do que o jogo grava.
#
# `<ai>` no seu estado minimo: sem trabalho em curso, sem objeto reservado, so
# a nave de origem. Os demais atributos (`inobj`, `rest`, `hobid`...) apontam
# para objetos especificos e nao podem ser herdados de outra pessoa.
_AI_IDLE = {"bts": "0", "suitOn": "0", "bstx": "-1", "bsty": "-1", "bstsh": "0"}
# So existem em situacoes especificas (dentro de uma cama medica, fora da nave)
# e nao fazem sentido em alguem recem-criado.
_DROP_CHAR_ATTRS = ("is", "outside", "oside", "owside", "mbsbp")
# Aparencia: vem toda de um mesmo doador, para as combinacoes continuarem
# coerentes em vez de sortear cada peca por conta propria.
_LOOK_ATTRS = ("bb", "bs", "bh", "bp", "orgColor", "colorSet")
# Equipamento e implantes tem entId proprio: clonar duplicaria esses ids, entao
# o novo tripulante nasce sem nada.
_DROP_CHAR_NODES = ("loadout", "aug", "npc")


def _all_characters(sf: SaveFile) -> list:
    out = []
    for _doc, ship in sf.ships():
        chars = ship.find("characters")
        out += chars.findall("c") if chars is not None else []
    for _doc, craft in sf.crafts():
        chars = craft.find("characters")
        out += chars.findall("c") if chars is not None else []
    return out


def _clear(parent, tag: str | None = None):
    """Esvazia um no, preservando a indentacao dos irmaos."""
    if parent is None:
        return
    for child in list(parent):
        if tag is None or child.tag == tag:
            _remove_child(parent, child)


def act_add_crew(sf: SaveFile, params: dict) -> dict:
    """Cria um tripulante novo na nave indicada.

    A ficha e uma copia de quem ja esta a bordo, com identidade, historico,
    equipamento e trabalho zerados. Copiar de dentro da propria nave e o que
    garante uma posicao valida: as coordenadas do personagem sao da grade
    daquela nave, e um tripulante colocado fora dela ficaria preso.
    """
    ship = sf.get(params["shipPath"])
    if ship.tag != "ship":
        raise SaveError("selecione uma nave — só dá para criar tripulante a bordo de uma")
    chars = ship.find("characters")
    pool = chars.findall("c") if chars is not None else []
    if not pool:
        raise SaveError(
            "esta nave não tem nenhum tripulante para servir de modelo; "
            "crie o primeiro numa nave que já tenha tripulação"
        )

    side = params.get("side") or None
    template = next((c for c in pool if side is None or c.get("side") == side), pool[0])
    new = copy.deepcopy(template)

    # -- identidade --------------------------------------------------------
    for attr in _DROP_CHAR_ATTRS:
        new.attrib.pop(attr, None)
    new.set("entId", sf.next_entity_id())
    new.set("task", "Walk")
    if side:
        new.set("side", side)
    everyone = _all_characters(sf)
    first = [c.get("name") for c in everyone if c.get("name")]
    last = [c.get("lname") for c in everyone if c.get("lname")]
    # Sem nome digitado, sorteia um dos que ja existem no save: sao nomes que o
    # proprio jogo gerou, entao nao ha risco de caractere que ele nao aceite.
    new.set("name", (params.get("name") or "").strip()
            or (random.choice(first) if first else "Crew"))
    new.set("lname", (params.get("lname") or "").strip()
            or (random.choice(last) if last else ""))

    # -- aparencia ---------------------------------------------------------
    same_species = [c for c in everyone if c.get("cid") == new.get("cid")] or [template]
    donor = random.choice(same_species)
    for attr in _LOOK_ATTRS:
        if donor.get(attr) is not None:
            new.set(attr, donor.get(attr))
    look, donor_look = new.find("colors"), donor.find("colors")
    if look is not None and donor_look is not None:
        look.attrib.clear()
        look.attrib.update(donor_look.attrib)

    # -- estado: sem trabalho, sem equipamento -----------------------------
    ai = new.find("ai")
    if ai is not None:
        ai.attrib.clear()
        ai.attrib.update(_AI_IDLE)
        if ship.get("sid"):
            ai.set("hsid", ship.get("sid"))
        for child in list(ai):
            if child.tag != "combatAI":
                _remove_child(ai, child)
    _clear(new.find("inv"))
    for tag in _DROP_CHAR_NODES:
        node = new.find(tag)
        if node is not None:
            _remove_child(new, node)

    # -- ficha pessoal -----------------------------------------------------
    pers = new.find("pers")
    if pers is not None:
        points = str(max(1, min(10, int(params.get("attributePoints", 5)))))
        for a in pers.findall("attr/a"):
            a.set("points", points)

        _clear(pers.find("traits"))
        # Os <c id="0"> sao encaixes vazios que o jogo mantem reservados; so as
        # condicoes de verdade saem.
        conditions = pers.find("conditions")
        if conditions is not None:
            for cond in list(conditions.findall("c")):
                if cond.get("id") not in (None, "0"):
                    _remove_child(conditions, cond)
        _clear(pers.find("sociality/relationships"))
        for n in pers.findall("needs/ns/*"):
            n.set("n", "0")
            n.set("cv", "0")
        _clear(pers.find("needs/factors"))
        _clear(pers.find("prefs"))
        for j in pers.findall("jobsetting/j"):
            j.set("priority", "Normal")

        level = str(max(0, min(8, int(params.get("skillLevel", 3)))))
        cap = str(max(int(level), min(8, int(params.get("skillCap", 8)))))
        for s in pers.findall("skills/s"):
            # As pericias ocultas ficam zeradas, como no resto do save.
            if not GD.skill(s.get("sk")).get("show", True):
                continue
            s.set("level", level)
            s.set("mxn", cap)
            s.set("exp", "0")
            s.set("expd", "0")

    _restore_one(new)
    # Restaurar nunca reduz saúde nem energia, para não desfazer um aumento —
    # mas quem acabou de nascer não tem nenhum: o modelo pode estar com 260 de
    # saúde por causa de implantes que não foram copiados. O mesmo vale para a
    # reserva de oxigênio, que é do traje, e ele veio sem equipamento.
    props = new.find("props")
    if props is not None:
        health = props.find("Health")
        if health is not None:
            for attr in ("v", "ltv"):
                if health.get(attr) is not None:
                    health.set(attr, "100")
        oxygen = props.find("Oxygen")
        if oxygen is not None and oxygen.get("oxs") is not None:
            oxygen.set("oxs", "0")

    _insert_child(chars, new)
    sf.mark_dirty(ship)
    sf.reindex()
    return {
        "changed": 1,
        "path": sf.path_of(new),
        "entId": new.get("entId"),
        "name": f"{new.get('name')} {new.get('lname')}".strip(),
    }


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
    "crew.add": act_add_crew,
    "storage.setStacks": act_set_stacks,
    "storage.fillAll": act_fill_all,
    "storage.addStack": act_add_stack,
    "storage.addOneOfEach": act_add_one_of_each,
    "research.complete": act_complete_research,
    "research.reset": act_reset_research,
}
