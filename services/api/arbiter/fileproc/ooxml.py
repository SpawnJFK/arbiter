"""Shared OOXML machinery for DOCX, PPTX and XLSX.

Two concerns live here.

Package I/O: we keep every zip entry's raw bytes and ZipInfo so parts we do not touch
are written back byte for byte, in the original order and with the original compression.

The run model: Word and PowerPoint paragraphs are flat sequences of runs, each with its
own property element (w:rPr / a:rPr). Authoring tools split runs for reasons invisible
to the reader (spell check, revision ids, language tags), so a naive mapping produces
tag soup that engines translate badly. We collapse runs with equivalent properties, pick
the formatting that covers most characters as the paragraph's base, and only express
deviations from it as paired codes. On merge we rebuild the paragraph from the target
content, re-using the live elements of the original (drawings, fields, bookmarks) so
nothing the translator never saw can be lost.
"""

from __future__ import annotations

import copy
import io
import posixpath
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from arbiter.fileproc.base import Content, FormatError, InlineCode
from arbiter.fileproc.text import check_xml_text

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML_NS = "http://www.w3.org/XML/1998/namespace"

# Parts larger than this are refused instead of parsed: a zip bomb guard, far above real documents.
MAX_PART_BYTES = 512 * 1024 * 1024

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, remove_blank_text=False)


def parse_xml(data: bytes) -> etree._ElementTree:
    """Parse untrusted XML without entity expansion or network access."""
    try:
        return etree.ElementTree(etree.fromstring(data, _PARSER))
    except etree.XMLSyntaxError:
        raise FormatError("The file contains damaged XML and cannot be processed.") from None


def serialize_xml(tree: etree._ElementTree) -> bytes:
    info = tree.docinfo
    return etree.tostring(
        tree,
        xml_declaration=True,
        encoding=info.encoding or "UTF-8",
        standalone=info.standalone,
    )


def qn(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def local(el: etree._Element) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


class Package:
    """A read-only view of an OOXML zip that can be re-written with selected parts replaced."""

    def __init__(self, data: bytes, label: str) -> None:
        self.label = label
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise FormatError(
                f"This {label} file is password protected or saved in a legacy format. "
                "Remove the password or save it as a regular file and upload it again."
            )
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(data))
            self.infos = self._zip.infolist()
        except (zipfile.BadZipFile, ValueError, OSError):
            raise FormatError(f"The file is damaged or is not a valid {label} file.") from None
        self.names = {i.filename for i in self.infos}
        for info in self.infos:
            if info.file_size > MAX_PART_BYTES:
                raise FormatError(f"The {label} file contains a part that is too large to process.")

    def read(self, name: str) -> bytes:
        try:
            return self._zip.read(name)
        except (KeyError, zipfile.BadZipFile, OSError, RuntimeError):
            raise FormatError(f"The file is damaged or is not a valid {self.label} file.") from None

    def xml(self, name: str) -> etree._ElementTree:
        return parse_xml(self.read(name))

    def rels(self, part: str) -> list[tuple[str, str, str]]:
        """(relationship type, resolved target part name, id) for internal relationships of a part."""
        base_dir, base_name = posixpath.split(part)
        rels_name = posixpath.join(base_dir, "_rels", base_name + ".rels")
        if rels_name not in self.names:
            return []
        out = []
        for rel in self.xml(rels_name).getroot().iter(qn(REL_NS, "Relationship")):
            if rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target", "")
            if target.startswith("/"):
                resolved = target.lstrip("/")
            else:
                resolved = posixpath.normpath(posixpath.join(base_dir, target))
            out.append((rel.get("Type", ""), resolved, rel.get("Id", "")))
        return out

    def related(self, part: str, type_suffix: str) -> list[str]:
        return [t for typ, t, _ in self.rels(part) if typ.endswith(type_suffix) and t in self.names]

    def main_part(self, type_suffix: str = "/officeDocument") -> str:
        parts = self.related("", type_suffix)
        if not parts:
            raise FormatError(f"The file is damaged or is not a valid {self.label} file.")
        return parts[0]

    def write(self, replacements: dict[str, bytes]) -> bytes:
        """Rewrite the zip in original order; untouched entries keep their exact bytes."""
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zout:
            for info in self.infos:
                data = replacements.get(info.filename)
                if data is None:
                    data = self._zip.read(info.filename)
                zi = zipfile.ZipInfo(info.filename, info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zi.create_system = info.create_system
                zi.comment = info.comment
                zout.writestr(zi, data)
        return out.getvalue()


# --------------------------------------------------------------------------- run model items


@dataclass
class TextItem:
    text: str
    rpr: etree._Element | None
    key: str


# An atom of a standalone code: a whole element to move, or (run, child) meaning one
# child of a run that must be re-wrapped in a run carrying that run's properties.
type Atom = etree._Element | tuple[etree._Element, etree._Element]


@dataclass
class CodeItem:
    atoms: list[Atom]
    display: str


@dataclass
class ContainerItem:
    elem: etree._Element
    items: list[TextItem | CodeItem | ContainerItem]
    display: str


Item = TextItem | CodeItem | ContainerItem


@dataclass
class FormatSpec:
    rpr: etree._Element | None


@dataclass
class ContainerSpec:
    elem: etree._Element
    base_rpr: etree._Element | None


@dataclass
class StandaloneSpec:
    atoms: list[Atom]


CodeSpec = FormatSpec | ContainerSpec | StandaloneSpec


@dataclass
class Dialect:
    """What differs between WordprocessingML, DrawingML and SpreadsheetML runs."""

    ns: str
    run: str
    text: str
    rpr: str
    preserve_space: bool  # w:t and SpreadsheetML t need xml:space; DrawingML a:t does not
    rpr_key: Callable[[etree._Element | None], str]
    describe_rpr: Callable[[etree._Element | None], str]
    # Container element local name -> local name of the child that holds its content ("" = itself).
    containers: dict[str, str] = field(default_factory=dict)


@dataclass
class ParagraphModel:
    content: Content
    codes: dict[str, CodeSpec]
    base_rpr: etree._Element | None


def strip_key(rpr: etree._Element | None, drop_attrs: Callable[[str], bool], drop_children: set[str]) -> str:
    """Canonical string for property equality, ignoring revision ids and language tags."""
    if rpr is None:
        return ""
    c = copy.deepcopy(rpr)
    for el in c.iter():
        for name in list(el.attrib):
            if drop_attrs(name.rsplit("}", 1)[-1]):
                del el.attrib[name]
    for child in list(c):
        if local(child) in drop_children:
            c.remove(child)
    if len(c) == 0 and not c.attrib:
        return ""
    return etree.tostring(c, method="c14n").decode()


def _dominant(items: list[Item]) -> tuple[str, etree._Element | None]:
    weight: dict[str, int] = {}
    first: dict[str, etree._Element | None] = {}
    order: list[str] = []
    for it in items:
        if isinstance(it, TextItem) and it.text:
            if it.key not in weight:
                weight[it.key] = 0
                first[it.key] = it.rpr
                order.append(it.key)
            weight[it.key] += len(it.text)
    if not order:
        return "", None
    best = max(order, key=lambda k: (weight[k], -order.index(k)))
    return best, first[best]


def element_markup(el: etree._Element) -> str:
    """Readable markup for a code's `original`: the element alone, without inherited namespace noise."""
    c = copy.deepcopy(el)
    c.tail = None
    etree.cleanup_namespaces(c)
    return etree.tostring(c, encoding="unicode", with_tail=False)


def shell_markup(el: etree._Element) -> str:
    """The start tag of a container, for the code's `original` hint."""
    c = etree.Element(el.tag, attrib=dict(el.attrib), nsmap=el.nsmap)
    etree.cleanup_namespaces(c)
    return etree.tostring(c, encoding="unicode")


def atom_markup(atom: Atom) -> str:
    if isinstance(atom, tuple):
        return element_markup(atom[1])
    return element_markup(atom)


def build_paragraph_model(items: list[Item], dialect: Dialect) -> ParagraphModel:
    """Turn walker items into content with paired codes for formatting deviations."""
    codes: dict[str, CodeSpec] = {}
    counter = [0]

    def new_id() -> str:
        counter[0] += 1
        return str(counter[0])

    def level(seq: list[Item]) -> tuple[Content, etree._Element | None]:
        base_key, base_rpr = _dominant(seq)
        out: Content = []
        i = 0
        while i < len(seq):
            it = seq[i]
            if isinstance(it, TextItem):
                if it.key == base_key:
                    out.append(it.text)
                    i += 1
                    continue
                # Extend the span over same-formatted text, allowing standalone codes in between.
                last = i
                j = i + 1
                while j < len(seq):
                    nxt = seq[j]
                    if isinstance(nxt, TextItem):
                        if nxt.key != it.key:
                            break
                        last = j
                    elif not isinstance(nxt, CodeItem):
                        break
                    j += 1
                cid = new_id()
                codes[cid] = FormatSpec(it.rpr)
                disp = dialect.describe_rpr(it.rpr)
                original = element_markup(it.rpr) if it.rpr is not None else ""
                out.append(InlineCode(cid, "open", original, disp))
                for x in seq[i : last + 1]:
                    if isinstance(x, TextItem):
                        out.append(x.text)
                    else:
                        assert isinstance(x, CodeItem)
                        sid = new_id()
                        codes[sid] = StandaloneSpec(x.atoms)
                        out.append(InlineCode(sid, "standalone", "".join(atom_markup(a) for a in x.atoms), x.display))
                out.append(InlineCode(cid, "close", "", disp))
                i = last + 1
            elif isinstance(it, CodeItem):
                sid = new_id()
                codes[sid] = StandaloneSpec(it.atoms)
                out.append(InlineCode(sid, "standalone", "".join(atom_markup(a) for a in it.atoms), it.display))
                i += 1
            else:
                cid = new_id()
                spec = ContainerSpec(it.elem, None)
                codes[cid] = spec
                out.append(InlineCode(cid, "open", shell_markup(it.elem), it.display))
                inner, inner_base = level(it.items)
                spec.base_rpr = inner_base
                out.extend(inner)
                out.append(InlineCode(cid, "close", f"</{it.elem.prefix + ':' if it.elem.prefix else ''}{local(it.elem)}>", it.display))
                i += 1
        return out, base_rpr

    content, base = level(items)
    merged: Content = []
    for r in content:
        if isinstance(r, str) and merged and isinstance(merged[-1], str):
            merged[-1] += r
        elif r != "":
            merged.append(r)
    return ParagraphModel(merged, codes, base)


# --------------------------------------------------------------------------- rendering


def _set_text(t: etree._Element, text: str, preserve: bool) -> None:
    t.text = text
    if preserve and text and (text != text.strip() or "  " in text):
        t.set(qn(XML_NS, "space"), "preserve")


def _render_atoms(parent: etree._Element, atoms: list[Atom], dialect: Dialect) -> None:
    """Re-insert the live elements of a standalone code, grouping children of one run back together."""
    i = 0
    while i < len(atoms):
        atom = atoms[i]
        if not isinstance(atom, tuple):
            atom.tail = None
            parent.append(atom)
            i += 1
            continue
        run = atom[0]
        group = [atom[1]]
        j = i + 1
        while j < len(atoms):
            nxt = atoms[j]
            if not (isinstance(nxt, tuple) and nxt[0] is run):
                break
            group.append(nxt[1])
            j += 1
        i = j
        if [c for c in run if c.tag != dialect.rpr] == group:
            # The code covers the whole run: move it as is, keeping revision ids and the like.
            run.tail = None
            parent.append(run)
            continue
        wrapper = etree.SubElement(parent, run.tag, attrib=dict(run.attrib))
        rpr = run.find(dialect.rpr)
        if rpr is not None:
            wrapper.append(copy.deepcopy(rpr))
        for child in group:
            child.tail = None
            wrapper.append(child)


def _make_shell(spec: ContainerSpec, dialect: Dialect) -> tuple[etree._Element, etree._Element]:
    el = spec.elem
    shell = etree.Element(el.tag, attrib=dict(el.attrib), nsmap=el.nsmap)
    content_child = dialect.containers.get(local(el), "")
    insert = shell
    for child in el:
        name = local(child)
        if content_child and name == content_child:
            holder = etree.SubElement(shell, child.tag, attrib=dict(child.attrib))
            insert = holder
        elif name.endswith("Pr") or name.endswith("EndPr"):
            shell.append(copy.deepcopy(child))
    return shell, insert


def render_paragraph(
    content: Content,
    model: ParagraphModel,
    dialect: Dialect,
    unit_id: str,
    emit_text: Callable[[etree._Element, str, etree._Element | None], None] | None = None,
) -> list[etree._Element]:
    """Build the new children of a paragraph from validated target content."""
    root = etree.Element("frag")
    # stack entries: ("c", parent, base_rpr) for containers, ("f", rpr) for formatting
    stack: list[tuple] = [("c", root, model.base_rpr)]

    def current() -> tuple[etree._Element, etree._Element | None]:
        rpr_set = False
        rpr: etree._Element | None = None
        for entry in reversed(stack):
            if entry[0] == "f" and not rpr_set:
                rpr, rpr_set = entry[1], True
            elif entry[0] == "c":
                return entry[1], (rpr if rpr_set else entry[2])
        raise AssertionError("container stack empty")

    def default_emit(parent: etree._Element, text: str, rpr: etree._Element | None) -> None:
        run = etree.SubElement(parent, dialect.run)
        if rpr is not None:
            run.append(copy.deepcopy(rpr))
        t = etree.SubElement(run, dialect.text)
        _set_text(t, text, dialect.preserve_space)

    emit = emit_text or default_emit
    for item in content:
        if isinstance(item, str):
            check_xml_text(item, unit_id)
            parent, rpr = current()
            emit(parent, item, rpr)
            continue
        spec = model.codes.get(item.id)
        if spec is None:
            raise FormatError(f"The translation of unit {unit_id} contains inline code {item.id} which is not in the source.")
        if item.kind == "standalone":
            assert isinstance(spec, StandaloneSpec)
            parent, _ = current()
            _render_atoms(parent, spec.atoms, dialect)
        elif item.kind == "open":
            if isinstance(spec, FormatSpec):
                stack.append(("f", spec.rpr))
            else:
                assert isinstance(spec, ContainerSpec)
                parent, _ = current()
                shell, insert = _make_shell(spec, dialect)
                parent.append(shell)
                stack.append(("c", insert, spec.base_rpr))
        else:
            stack.pop()
    return list(root)


def replace_children(
    p: etree._Element, new_children: list[etree._Element], head: set[str], tail: set[str]
) -> None:
    """Swap a paragraph's content children, keeping its property elements in place."""
    keep_head: list[etree._Element] = []
    keep_tail: list[etree._Element] = []
    for child in list(p):
        name = local(child)
        if name in head and not keep_tail:
            keep_head.append(child)
        elif name in tail:
            keep_tail.append(child)
        p.remove(child)
    for child in keep_head:
        p.append(child)
    for child in new_children:
        p.append(child)
    for child in keep_tail:
        p.append(child)


__all__ = [
    "MC_NS",
    "REL_NS",
    "XML_NS",
    "CodeItem",
    "ContainerItem",
    "ContainerSpec",
    "Dialect",
    "FormatSpec",
    "Package",
    "ParagraphModel",
    "StandaloneSpec",
    "TextItem",
    "build_paragraph_model",
    "element_markup",
    "local",
    "parse_xml",
    "qn",
    "render_paragraph",
    "replace_children",
    "serialize_xml",
    "strip_key",
]
