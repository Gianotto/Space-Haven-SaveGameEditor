"""Leitura, edicao e gravacao de um savegame do Space Haven.

Um save e uma pasta com varios arquivos XML:

    save/
      game               partida, pesquisa, banco, facções e as naves do setor
      ships/shipNNNN     uma nave fora do setor atual, por arquivo
      info, stats.bin, timeline.xml   (nao mexemos)

O jogo grava esses XML com um estilo proprio (tags vazias sem espaco antes de
`/>`, indentacao com tabs). A serializacao aqui reproduz esse estilo byte a
byte: carregar e gravar sem alterar resulta em arquivos identicos aos originais.

Cada no recebe um *path* estavel no formato `documento#i/j/k`, onde os numeros
sao indices de filho a partir da raiz daquele documento. Toda edicao vinda da
interface e expressa como uma operacao sobre um path, o que permite alterar
qualquer parametro do save sem que o backend precise conhecer o significado
dele.
"""

from __future__ import annotations

import glob
import os
import shutil
import time
import xml.etree.ElementTree as ET

SAVE_FILENAME = "game"
SHIPS_DIRNAME = "ships"
MAIN_DOC = "game"


class SaveError(Exception):
    pass


# --------------------------------------------------------------------------
# Serializacao no estilo do jogo
# --------------------------------------------------------------------------

_ATTR_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"))
_TEXT_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def _esc(value: str, table) -> str:
    for old, new in table:
        value = value.replace(old, new)
    return value


def serialize(root: ET.Element) -> bytes:
    """Serializa a arvore no mesmo formato que o jogo grava."""
    out = []

    def write(el: ET.Element):
        out.append("<" + el.tag)
        for key, val in el.attrib.items():
            out.append(f' {key}="{_esc(str(val), _ATTR_ESCAPES)}"')
        has_text = el.text is not None and el.text != ""
        if not len(el) and not has_text:
            out.append("/>")
        else:
            out.append(">")
            if has_text:
                out.append(_esc(el.text, _TEXT_ESCAPES))
            for child in el:
                write(child)
                if child.tail:
                    out.append(_esc(child.tail, _TEXT_ESCAPES))
            out.append(f"</{el.tag}>")

    write(root)
    if root.tail:
        out.append(_esc(root.tail, _TEXT_ESCAPES))
    return "".join(out).encode("utf-8")


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------


class Document:
    """Um arquivo XML do save, com indice de paths."""

    def __init__(self, key: str, path: str, expect_tag: str | None = None):
        self.key = key
        self.path = os.path.abspath(path)
        self.expect_tag = expect_tag
        self.dirty = False
        self.by_path: dict[str, ET.Element] = {}
        self.parents: dict[int, ET.Element] = {}
        self.paths: dict[int, str] = {}
        self.load()

    def load(self):
        try:
            with open(self.path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise SaveError(f"não foi possível ler {self.path}: {exc}") from exc
        try:
            self.root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise SaveError(f"{os.path.basename(self.path)} não é um XML válido: {exc}") from exc
        if self.expect_tag and self.root.tag != self.expect_tag:
            raise SaveError(
                f"raiz inesperada <{self.root.tag}> em {os.path.basename(self.path)}; "
                f"esperado <{self.expect_tag}>"
            )
        # O ElementTree descarta o que vem depois da tag de fechamento da raiz
        # (o jogo grava uma quebra de linha final em alguns arquivos). Guardamos
        # esse sufixo para regravar o arquivo exatamente como estava.
        body = serialize(self.root)
        self.trailer = raw[len(body):] if raw.startswith(body) else b""
        self.reindex()
        self.dirty = False

    def reindex(self):
        self.by_path = {}
        self.parents = {}
        self.paths = {}
        stack = [(self.key + "#", self.root)]
        while stack:
            path, el = stack.pop()
            self.by_path[path] = el
            self.paths[id(el)] = path
            sep = "" if path.endswith("#") else "/"
            for i, child in enumerate(el):
                self.parents[id(child)] = el
                stack.append((f"{path}{sep}{i}", child))

    def write(self, backup: bool = True) -> dict:
        blob = serialize(self.root) + getattr(self, "trailer", b"")
        try:
            ET.fromstring(blob)
        except ET.ParseError as exc:
            raise SaveError(
                f"a árvore gerada para {os.path.basename(self.path)} é inválida, "
                f"gravação abortada: {exc}"
            ) from exc

        backup_path = None
        if backup and os.path.exists(self.path):
            backup_path = f"{self.path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(self.path, backup_path)

        tmp = self.path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, self.path)
        self.dirty = False
        return {"doc": self.key, "path": self.path, "backup": backup_path, "bytes": len(blob)}


# --------------------------------------------------------------------------
# Savegame (conjunto de documentos)
# --------------------------------------------------------------------------


class SaveFile:
    """O save inteiro: o arquivo `game` e as naves guardadas em `ships/`."""

    def __init__(self, path: str):
        self.path = _resolve_main(path)
        self.dir = os.path.dirname(self.path)
        self.docs: dict[str, Document] = {}
        self.load()

    # -- carregamento ------------------------------------------------------

    def load(self):
        self.docs = {MAIN_DOC: Document(MAIN_DOC, self.path, expect_tag="game")}
        ships_dir = os.path.join(self.dir, SHIPS_DIRNAME)
        if os.path.isdir(ships_dir):
            for f in sorted(glob.glob(os.path.join(ships_dir, "ship*"))):
                if not os.path.isfile(f) or f.endswith((".tmp", ".bak")) or ".bak-" in f:
                    continue
                key = os.path.basename(f)
                try:
                    self.docs[key] = Document(key, f, expect_tag="ship")
                except SaveError:
                    # Um arquivo de nave corrompido nao deve impedir abrir o save.
                    continue

    @property
    def main(self) -> ET.Element:
        return self.docs[MAIN_DOC].root

    @property
    def root(self) -> ET.Element:
        return self.main

    @property
    def dirty(self) -> bool:
        return any(d.dirty for d in self.docs.values())

    @dirty.setter
    def dirty(self, value: bool):
        if value:
            self.docs[MAIN_DOC].dirty = True
        else:
            for d in self.docs.values():
                d.dirty = False

    def reindex(self):
        for d in self.docs.values():
            d.reindex()

    # -- acesso ------------------------------------------------------------

    def _doc_for_path(self, path: str) -> Document:
        key = path.split("#", 1)[0] if "#" in path else MAIN_DOC
        doc = self.docs.get(key)
        if doc is None:
            raise SaveError(f"documento inexistente: {key!r}")
        return doc

    def get(self, path: str) -> ET.Element:
        if "#" not in path:
            path = f"{MAIN_DOC}#{path}"
        el = self._doc_for_path(path).by_path.get(path)
        if el is None:
            raise SaveError(f"caminho inexistente: {path!r}")
        return el

    def path_of(self, el: ET.Element) -> str:
        for doc in self.docs.values():
            p = doc.paths.get(id(el))
            if p is not None:
                return p
        raise SaveError(f"elemento <{el.tag}> fora do índice (reindex pendente?)")

    def parent_of(self, el: ET.Element):
        for doc in self.docs.values():
            p = doc.parents.get(id(el))
            if p is not None:
                return p
        return None

    def doc_of(self, el: ET.Element) -> str:
        return self.path_of(el).split("#", 1)[0]

    def ships(self):
        """Todas as naves do save: as do setor atual e as guardadas em `ships/`.

        Retorna pares (rotulo_do_documento, elemento <ship>).
        """
        holder = self.main.find("ships")
        for ship in (holder if holder is not None else []):
            if ship.tag == "ship":
                yield MAIN_DOC, ship
        for key, doc in self.docs.items():
            if key != MAIN_DOC:
                yield key, doc.root

    def crafts(self):
        """Todas as naves auxiliares (mineradores, construtores, caças).

        Elas ficam em <crafts> — na raiz do `game` e dentro de cada nave — e
        têm o próprio <characters>: quem está pilotando não aparece na lista de
        tripulantes da nave-mãe. O vínculo com ela é o atributo `homeSid`.
        """
        for key, doc in self.docs.items():
            for holder in doc.root.iter("crafts"):
                for craft in holder.findall("c"):
                    yield key, craft

    def iter_all(self):
        for doc in self.docs.values():
            yield from doc.root.iter()

    def next_entity_id(self) -> str:
        """Reserva um id de entidade novo, do mesmo contador que o jogo usa.

        Toda entidade do save — personagem, item, objeto — tem um `entId`
        tirado de `masterData/@idCounter`, que guarda o proximo id livre.
        Reservar dali (e avancar o contador) e o que garante que nada criado
        aqui colida com o que o jogo criar depois.
        """
        master = self.main.find("masterData")
        current = master.get("idCounter") if master is not None else None
        if current is None or not str(current).isdigit():
            raise SaveError("este save não tem masterData/@idCounter")
        master.set("idCounter", str(int(current) + 1))
        self.docs[MAIN_DOC].dirty = True
        return str(current)

    # -- edicao ------------------------------------------------------------

    def apply(self, ops: list) -> int:
        """Aplica uma lista de operacoes. Retorna quantas foram aplicadas.

        Operacoes suportadas:
          {"op":"set",    "path":P, "attrs":{k:v|null}}  altera/remove atributos
          {"op":"add",    "path":P, "tag":T, "attrs":{}, "index":n?}  novo filho
          {"op":"remove", "path":P}                       remove o no
          {"op":"text",   "path":P, "value":S}            altera o texto do no
        """
        touched: set[str] = set()
        structural = False
        applied = 0

        for op in ops:
            kind = op.get("op", "set")
            path = op.get("path")
            if path is None:
                raise SaveError("operação sem 'path'")

            if kind == "set":
                el = self.get(path)
                for key, val in (op.get("attrs") or {}).items():
                    if val is None:
                        el.attrib.pop(key, None)
                    else:
                        el.set(key, str(val))
                applied += 1

            elif kind == "text":
                el = self.get(path)
                el.text = op.get("value") or None
                applied += 1

            elif kind == "add":
                parent = self.get(path)
                child = ET.Element(op["tag"],
                                   {k: str(v) for k, v in (op.get("attrs") or {}).items()})
                _insert_child(parent, child, op.get("index"))
                structural = True
                applied += 1

            elif kind == "remove":
                el = self.get(path)
                parent = self.parent_of(el)
                if parent is None:
                    raise SaveError("não é possível remover a raiz de um documento")
                _remove_child(parent, el)
                structural = True
                applied += 1

            else:
                raise SaveError(f"operação desconhecida: {kind!r}")

            touched.add(self._doc_for_path(path if "#" in path else f"{MAIN_DOC}#{path}").key)

        for key in touched:
            self.docs[key].dirty = True
        if structural:
            self.reindex()
        return applied

    def mark_dirty(self, el: ET.Element):
        """Marca como alterado o documento ao qual o elemento pertence."""
        self.docs[self.doc_of(el)].dirty = True

    # -- gravacao ----------------------------------------------------------

    def save(self, backup: bool = True) -> dict:
        """Regrava apenas os arquivos que mudaram, cada um com seu backup."""
        written = [d.write(backup) for d in self.docs.values() if d.dirty]
        if not written:
            written = [self.docs[MAIN_DOC].write(backup)]
        return {
            "path": self.path,
            "files": written,
            "backup": written[0].get("backup"),
            "bytes": sum(w["bytes"] for w in written),
        }

    def status(self) -> dict:
        return {
            "path": self.path,
            "dirty": self.dirty,
            "documents": [
                {"key": d.key, "file": os.path.basename(d.path), "dirty": d.dirty,
                 "tag": d.root.tag,
                 "name": d.root.get("sname") or ("partida" if d.key == MAIN_DOC else d.key)}
                for d in self.docs.values()
            ],
        }


def _resolve_main(path: str) -> str:
    """Aceita a pasta do save, a pasta que contem `save/`, ou o arquivo `game`."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(path):
        inner = os.path.join(path, SAVE_FILENAME)
        if os.path.isfile(inner):
            return inner
        nested = os.path.join(path, "save", SAVE_FILENAME)
        if os.path.isfile(nested):
            return nested
        raise SaveError(f"{path} não contém um arquivo '{SAVE_FILENAME}'")
    if not os.path.isfile(path):
        raise SaveError(f"não encontrado: {path}")
    return path


def _insert_child(parent: ET.Element, child: ET.Element, index=None):
    """Insere um filho preservando a indentacao usada pelos irmaos.

    Num bloco indentado, `parent.text` e o espaco antes do primeiro filho (o
    mesmo que separa irmaos) e o `tail` do ultimo filho e o espaco que fecha o
    bloco. Manter essa distincao evita reindentar o arquivo inteiro.
    """
    if not len(parent):
        # Nó vazio (`<inv/>`): a indentação sai do próprio tail, um nível acima.
        if parent.text is None and parent.tail and "\n" in parent.tail:
            parent.text = parent.tail + "\t"
            child.tail = parent.tail
        parent.append(child)
        return
    between = parent.text
    if index is None or index >= len(parent):
        last = parent[-1]
        child.tail = last.tail
        last.tail = between
        parent.append(child)
    else:
        child.tail = between
        parent.insert(index, child)


def _remove_child(parent: ET.Element, child: ET.Element):
    idx = list(parent).index(child)
    if idx == len(parent) - 1:
        if idx > 0:
            # o ultimo filho carrega o espaco que fecha o bloco
            parent[idx - 1].tail = child.tail
        else:
            parent.text = None  # ficou vazio: serializa como <tag/>
    parent.remove(child)
