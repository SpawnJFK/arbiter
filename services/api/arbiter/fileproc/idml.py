"""Adobe InDesign Markup Language (.idml) handler.

An IDML package is a zip of XML parts; text lives in Stories/*.xml. A story is a
sequence of ParagraphStyleRange elements holding CharacterStyleRange runs, whose
children are Content (text), Br (paragraph break) and inline objects. A paragraph ends
at a Br that is a direct child of a run or at the end of a ParagraphStyleRange.

Content model per paragraph, in the style of the DOCX run model: the run formatting
that covers most characters is the base, runs with other formatting become paired
codes, HyperlinkTextSource (and an XMLElement inside a run) becomes a paired code, and
everything else inside a run becomes a standalone code that keeps the live element:
editorial Notes, anchored frames and graphics, hyperlink destinations, text variables,
footnote references, tables, and processing instructions such as <?ACE 4?>. Footnote
and table cell text is extracted as separate units right after its paragraph.

Merge, per changed paragraph:
- when the target keeps the source order of codes, the new text is distributed into the
  existing Content slots and the structure is left exactly as it was;
- otherwise the paragraph's runs are rebuilt from the target, re-using the live inline
  elements, which needs the paragraph's runs to share one parent.
Unchanged stories keep their exact bytes and an identity merge returns the original.

Tracked changes are refused: their text cannot be translated unambiguously.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, FormatError, InlineCode, TargetMap
from arbiter.fileproc.ooxml import Package
from arbiter.fileproc.text import check_target_ids, check_xml_text, make_unit, resolve_target
from arbiter.fileproc.xmlfmt import parse_document, serialize_document

MIMETYPE = b"application/vnd.adobe.indesign-idml-package"
_INNER = {"HyperlinkTextSource", "XMLElement"}  # containers that may sit inside a run
_NESTED = {"Footnote", "Table"}
CHANGES_MESSAGE = (
    "The InDesign file contains tracked changes. Accept or reject all changes in InDesign, "
    "export the IDML again and upload it."
)


def _tag(node: Any) -> str:
    tag = getattr(node, "tag", None)
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _short(ref: str | None) -> str:
    if not ref:
        return ""
    name = ref.split("/", 1)[-1]
    return name.replace("$ID/", "").strip("[]")


# --------------------------------------------------------------------------- items


@dataclass
class _Slot:
    content: etree._Element  # the Content element
    pi: Any = None  # None: Content.text, else the processing instruction whose tail holds the text

    def set(self, text: str) -> None:
        if self.pi is None:
            self.content.text = text or None
        else:
            self.pi.tail = text or None


@dataclass
class _Piece:
    csr: etree._Element
    child: etree._Element


@dataclass
class _Para:
    unit_id: str
    pieces: list[_Piece]
    content: Content = field(default_factory=list)
    codes: dict[str, tuple[str, Any]] = field(default_factory=dict)
    gaps: list[list[_Slot]] = field(default_factory=list)  # text slots between consecutive codes
    base: etree._Element | None = None
    unit: ExtractedUnit | None = None


def _csr_key(csr: etree._Element) -> str:
    attrs = sorted((k, v) for k, v in csr.attrib.items())
    props = csr.find("Properties")
    tail = etree.tostring(props, method="c14n").decode() if props is not None else ""
    return repr(attrs) + tail


def _describe(csr: etree._Element) -> str:
    parts: list[str] = []
    style = _short(csr.get("AppliedCharacterStyle"))
    if style and style != "No character style":
        parts.append(f"style:{style}")
    font_style = (csr.get("FontStyle") or "").lower()
    if "bold" in font_style:
        parts.append("bold")
    if "italic" in font_style or "oblique" in font_style:
        parts.append("italic")
    position = csr.get("Position") or ""
    if "Superscript" in position:
        parts.append("superscript")
    elif "Subscript" in position:
        parts.append("subscript")
    if csr.get("Underline") == "true":
        parts.append("underline")
    if csr.get("StrikeThru") == "true":
        parts.append("strikethrough")
    if csr.get("FillColor"):
        parts.append("color")
    if csr.get("PointSize"):
        parts.append("size")
    return "+".join(parts[:3]) if parts else "format"


def _display(el: Any) -> str:
    if isinstance(el, etree._ProcessingInstruction):
        return "special character"
    tag = _tag(el)
    return {
        "Note": "note",
        "Footnote": "footnote",
        "Table": "table",
        "HyperlinkTextDestination": "anchor",
        "TextVariableInstance": "variable",
        "Br": "line break",
        "Rectangle": "graphic",
        "TextFrame": "text frame",
        "Group": "graphic",
        "Oval": "graphic",
        "Polygon": "graphic",
        "HyperlinkTextSource": "link",
        "XMLElement": f"tag:{_short(el.get('MarkupTag'))}" if el.get("MarkupTag") else "tag",
    }.get(tag, tag.lower() or "object")


def _markup(el: Any) -> str:
    c = copy.deepcopy(el)
    c.tail = None
    return etree.tostring(c, encoding="unicode", with_tail=False)


# --------------------------------------------------------------------------- walking


class _StoryWalker:
    def __init__(self, part: str, lang: str) -> None:
        self.part = part
        self.lang = lang
        self.paras: list[_Para] = []
        self.counter = 0

    def walk(self, container: etree._Element, kind: str) -> None:
        events: list[_Piece | None] = []  # None is a paragraph break
        self._collect(container, events)
        current: list[_Piece] = []
        for ev in [*events, None]:
            if ev is not None:
                current.append(ev)
                continue
            if current:
                self._paragraph(current, kind)
            current = []

    def _collect(self, el: etree._Element, events: list[_Piece | None]) -> None:
        for child in el:
            tag = _tag(child)
            if tag == "ParagraphStyleRange":
                self._collect(child, events)
                events.append(None)
            elif tag == "CharacterStyleRange":
                for item in child:
                    t = _tag(item)
                    if t == "Br":
                        events.append(None)
                    elif t == "Properties" or not isinstance(item.tag, str):
                        continue
                    else:
                        events.append(_Piece(child, item))
            elif tag in _INNER and any(
                _tag(d) in ("CharacterStyleRange", "ParagraphStyleRange") for d in child
            ):
                self._collect(child, events)  # tagging around runs: transparent

    def _paragraph(self, pieces: list[_Piece], kind: str) -> None:
        self.counter += 1
        para = _Para(f"{self.part}#{self.counter}", pieces)
        nested: list[tuple[etree._Element, str]] = []
        weights: dict[str, int] = {}
        order: list[str] = []
        firsts: dict[str, etree._Element] = {}

        def text_of(el: etree._Element) -> int:
            n = len(el.text or "")
            for c in el:
                n += len(c.tail or "")
            return n

        for p in pieces:
            key = _csr_key(p.csr)
            if key not in weights:
                weights[key] = 0
                order.append(key)
                firsts[key] = p.csr
            if _tag(p.child) == "Content":
                weights[key] += text_of(p.child)
            elif _tag(p.child) in _INNER:
                weights[key] += sum(text_of(c) for c in p.child if _tag(c) == "Content")
        base_key = max(order, key=lambda k: (weights[k], -order.index(k)))
        para.base = firsts[base_key]

        content: Content = []
        gaps: list[list[_Slot]] = [[]]
        counter = [0]

        def new_id() -> str:
            counter[0] += 1
            return str(counter[0])

        def code(c: InlineCode, spec: tuple[str, Any]) -> None:
            para.codes[c.id] = spec
            content.append(c)
            gaps.append([])

        def text(t: str | None, slot: _Slot) -> None:
            gaps[-1].append(slot)
            if t:
                if content and isinstance(content[-1], str):
                    content[-1] += t
                else:
                    content.append(t)

        def content_el(el: etree._Element) -> None:
            text(el.text, _Slot(el))
            for c in el:
                cid = new_id()
                code(InlineCode(cid, "standalone", _markup(c), _display(c)), ("node", c))
                text(c.tail, _Slot(el, c))

        def standalone(el: etree._Element) -> None:
            cid = new_id()
            code(InlineCode(cid, "standalone", _markup(el), _display(el)), ("node", el))
            tag = _tag(el)
            if tag == "Footnote":
                nested.append((el, "footnote"))
            elif tag == "Table":
                nested.append((el, "table"))

        i = 0
        while i < len(pieces):
            key = _csr_key(pieces[i].csr)
            j = i
            while j < len(pieces) and _csr_key(pieces[j].csr) == key:
                j += 1
            fmt_id = ""
            if key != base_key:
                fmt_id = new_id()
                disp = _describe(pieces[i].csr)
                code(InlineCode(fmt_id, "open", _markup_shell(pieces[i].csr), disp), ("fmt", pieces[i].csr))
            for p in pieces[i:j]:
                tag = _tag(p.child)
                if tag == "Content":
                    content_el(p.child)
                elif tag in _INNER:
                    cid = new_id()
                    disp = _display(p.child)
                    code(InlineCode(cid, "open", _markup_shell(p.child), disp), ("inner", p.child))
                    for c in p.child:
                        if _tag(c) == "Content":
                            content_el(c)
                        elif isinstance(c.tag, str) and _tag(c) != "Properties":
                            standalone(c)
                    code(InlineCode(cid, "close", f"</{_tag(p.child)}>", disp), ("inner", p.child))
                else:
                    standalone(p.child)
            if fmt_id:
                code(InlineCode(fmt_id, "close", "</CharacterStyleRange>", disp), ("fmt", pieces[i].csr))
            i = j

        para.content = content
        para.gaps = gaps
        psr = next((a for a in pieces[0].csr.iterancestors() if _tag(a) == "ParagraphStyleRange"), None)
        style = _short(psr.get("AppliedParagraphStyle")) if psr is not None else ""
        context = kind if not style or style == "NormalParagraphStyle" else f"{kind}, style {style}"
        para.unit = make_unit(para.unit_id, content, self.lang, context=context)
        if para.unit is not None:
            self.paras.append(para)
        for el, nkind in nested:
            if nkind == "table":
                for cell in el:
                    if _tag(cell) == "Cell":
                        self.walk(cell, "table")
            else:
                self.walk(el, "footnote")


def _markup_shell(el: etree._Element) -> str:
    shell = etree.Element(el.tag, attrib=dict(el.attrib))
    return etree.tostring(shell, encoding="unicode").replace("/>", ">")


# --------------------------------------------------------------------------- merging


def _target_codes(content: Content) -> list[tuple[str, str]]:
    return [(r.id, r.kind) for r in content if isinstance(r, InlineCode)]


def _target_gaps(content: Content) -> list[str]:
    gaps = [""]
    for r in content:
        if isinstance(r, InlineCode):
            gaps.append("")
        else:
            gaps[-1] += r
    return gaps


def _distribute(para: _Para, content: Content) -> bool:
    """Write target text into the existing Content slots. False if the shape does not allow it."""
    if _target_codes(content) != _target_codes(para.content):
        return False
    texts = _target_gaps(content)
    if len(texts) != len(para.gaps):
        return False
    for text, slots in zip(texts, para.gaps, strict=True):
        if text and not slots:
            return False
    for text, slots in zip(texts, para.gaps, strict=True):
        check_xml_text(text, para.unit_id)
        for idx, slot in enumerate(slots):
            slot.set(text if idx == 0 else "")
    return True


def _split(csr: etree._Element, at: etree._Element) -> etree._Element:
    """Move `at` and every later child of a run into a new run with the same formatting."""
    new = etree.Element(csr.tag, attrib=dict(csr.attrib))
    props = csr.find("Properties")
    if props is not None:
        new.append(copy.deepcopy(props))
    children = list(csr)
    for c in children[children.index(at) :]:
        new.append(c)
    csr.addnext(new)
    return new


def _new_run(template: etree._Element) -> etree._Element:
    run = etree.Element(template.tag, attrib=dict(template.attrib))
    props = template.find("Properties")
    if props is not None:
        run.append(copy.deepcopy(props))
    return run


def _rebuild(para: _Para, content: Content) -> None:
    pieces = para.pieces
    for p in pieces:  # an earlier rebuild in the same story may have split a shared run
        holder = p.child.getparent()
        if holder is not None:
            p.csr = holder
    parent = pieces[0].csr.getparent()
    if parent is None or any(p.csr.getparent() is not parent for p in pieces):
        raise FormatError(
            f"The translation of unit {para.unit_id} moves formatting across tagged InDesign structure. "
            "Keep the inline codes in their original order for this paragraph."
        )
    first, last = pieces[0], pieces[-1]
    before = [c for c in first.csr if isinstance(c.tag, str) and _tag(c) != "Properties"]
    if before and before[0] is not first.child:
        old = first.csr
        moved = _split(old, first.child)
        for p in pieces:
            if p.csr is old:
                p.csr = moved
    after = list(last.csr)
    idx = after.index(last.child)
    if idx + 1 < len(after):
        _split(last.csr, after[idx + 1])
    runs: list[etree._Element] = []
    for p in pieces:
        if p.csr not in runs:
            runs.append(p.csr)
    start = parent.index(runs[0])
    end = parent.index(runs[-1])
    between = list(parent)[start : end + 1]
    if any(el not in runs for el in between):
        raise FormatError(
            f"The translation of unit {para.unit_id} moves formatting across tagged InDesign structure. "
            "Keep the inline codes in their original order for this paragraph."
        )
    tail = runs[-1].tail
    for el in between:
        parent.remove(el)
    assert para.base is not None
    new_runs = _render(para, content)
    if new_runs:
        new_runs[-1].tail = tail
    for offset, run in enumerate(new_runs):
        parent.insert(start + offset, run)


def _render(para: _Para, content: Content) -> list[etree._Element]:
    assert para.base is not None
    runs: list[etree._Element] = []
    fmt: list[etree._Element] = [para.base]
    cur: list[etree._Element | None] = [None]
    inner: list[etree._Element | None] = [None]

    def run() -> etree._Element:
        if cur[0] is None or cur[0].get("__tpl") != str(id(fmt[-1])):
            r = _new_run(fmt[-1])
            r.set("__tpl", str(id(fmt[-1])))
            runs.append(r)
            cur[0] = r
        return cur[0]

    def target() -> etree._Element:
        return inner[0] if inner[0] is not None else run()

    def last_content(t: etree._Element) -> etree._Element:
        kids = list(t)
        if kids and _tag(kids[-1]) == "Content":
            return kids[-1]
        el = etree.SubElement(t, "Content")
        return el

    for item in content:
        if isinstance(item, str):
            check_xml_text(item, para.unit_id)
            c = last_content(target())
            kids = list(c)
            if kids:
                kids[-1].tail = (kids[-1].tail or "") + item
            else:
                c.text = (c.text or "") + item
            continue
        kind, node = para.codes[item.id]
        if kind == "fmt":
            if inner[0] is not None:
                raise FormatError(
                    f"The translation of unit {para.unit_id} puts formatting inside a link or tag, "
                    "which InDesign cannot store. Keep the codes in their original order."
                )
            if item.kind == "open":
                fmt.append(node)
            else:
                fmt.pop()
            cur[0] = None
        elif kind == "inner":
            if item.kind == "open":
                for child in list(node):
                    if _tag(child) == "Properties":
                        continue
                    node.remove(child)
                node.text = None
                node.tail = None
                run().append(node)
                inner[0] = node
            else:
                inner[0] = None
        else:
            node.tail = None
            if isinstance(node, etree._ProcessingInstruction):
                last_content(target()).append(node)
            else:
                target().append(node)
    for r in runs:
        del r.attrib["__tpl"]
    return runs


# --------------------------------------------------------------------------- handler


class IdmlHandler:
    name = "idml"
    extensions: tuple[str, ...] = ("idml",)

    def _stories(self, pkg: Package) -> list[str]:
        if "mimetype" not in pkg.names or pkg.read("mimetype").strip() != MIMETYPE:
            raise FormatError("The file is damaged or is not a valid IDML file.")
        stories: list[str] = []
        if "designmap.xml" in pkg.names:
            root = parse_document(pkg.read("designmap.xml"), "IDML").getroot()
            for el in root.iter():
                if _tag(el) == "Story" and el.get("src"):
                    src = el.get("src", "")
                    if src in pkg.names and src not in stories:
                        stories.append(src)
        for name in sorted(pkg.names, key=_natural):
            if name.startswith("Stories/") and name.endswith(".xml") and name not in stories:
                stories.append(name)
        return stories

    def _walk(self, pkg: Package, part: str, lang: str) -> tuple[etree._ElementTree, _StoryWalker]:
        tree = parse_document(pkg.read(part), "IDML")
        root = tree.getroot()
        if any(_tag(el) == "Change" for el in root.iter()):
            raise FormatError(CHANGES_MESSAGE)
        walker = _StoryWalker(part, lang)
        for story in _iter_stories(root):
            walker.walk(story, "body")
        return tree, walker

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        pkg = Package(data, "IDML")
        units: list[ExtractedUnit] = []
        for part in self._stories(pkg):
            _, walker = self._walk(pkg, part, source_lang)
            units.extend(p.unit for p in walker.paras if p.unit is not None)
        return ExtractionResult(self.name, source_lang, units)

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        pkg = Package(original, "IDML")
        replacements: dict[str, bytes] = {}
        known: list[str] = []
        for part in self._stories(pkg):
            tree, walker = self._walk(pkg, part, "en")
            plans: list[tuple[_Para, Content]] = []
            for para in walker.paras:
                assert para.unit is not None
                known.append(para.unit_id)
                tgt = targets.get(para.unit_id)
                if tgt is None:
                    continue
                content, changed = resolve_target(para.unit, tgt, resegment=True)
                if changed:
                    plans.append((para, content))
            # Distribute first: it only writes text, so later rebuilds see the same structure.
            rebuilds = [(p, c) for p, c in plans if not _distribute(p, c)]
            for para, content in rebuilds:
                _rebuild(para, content)
            if plans:
                replacements[part] = serialize_document(tree, pkg.read(part))
        check_target_ids(targets, known)
        return pkg.write(replacements) if replacements else original


def _iter_stories(root: etree._Element) -> Iterator[etree._Element]:
    if root.tag == "Story":  # a bare story without the packaging wrapper
        yield root
        return
    for el in root:
        if _tag(el) == "Story":
            yield el


def _natural(name: str) -> tuple:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name))
