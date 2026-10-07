"""DOCX (WordprocessingML) handler working directly on the package XML.

python-docx is not used at runtime: it hides the run structure we need to preserve and
silently drops constructs it does not model. Every w:p in the main document, headers,
footers, footnotes and endnotes is a unit; tables, nested tables and text boxes are
simply paragraphs found deeper in the tree.

Fields need special care. A complex field is a begin/separate/end sequence of
w:fldChar runs that may cross run, hyperlink and even paragraph boundaries (a table of
contents spans many paragraphs). Everything between begin and end, instruction and
cached result, becomes one standalone code per paragraph so engines never translate
"PAGEREF _Toc123" and the field still updates in Word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from arbiter.fileproc.base import ExtractedUnit, ExtractionResult, FormatError, TargetMap
from arbiter.fileproc.ooxml import (
    MC_NS,
    CodeItem,
    ContainerItem,
    Dialect,
    Item,
    Package,
    ParagraphModel,
    TextItem,
    build_paragraph_model,
    local,
    qn,
    render_paragraph,
    replace_children,
    serialize_xml,
    strip_key,
)
from arbiter.fileproc.text import check_target_ids, make_unit, resolve_target

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(name: str) -> str:
    return qn(W, name)


TRACKED = (_w("ins"), _w("del"), _w("moveFrom"), _w("moveTo"), _w("cellIns"), _w("cellDel"))
TRACKED_MESSAGE = (
    "This document contains tracked changes. Accept or reject all changes in Word and upload it again."
)

_DROP = {"proofErr", "lastRenderedPageBreak"}

_RUN_CODE_DISPLAY = {
    "tab": "tab",
    "ptab": "tab",
    "cr": "line break",
    "drawing": "image",
    "pict": "image",
    "object": "object",
    "footnoteReference": "footnote",
    "endnoteReference": "endnote",
    "footnoteRef": "footnote number",
    "endnoteRef": "endnote number",
    "sym": "symbol",
    "noBreakHyphen": "non-breaking hyphen",
    "softHyphen": "soft hyphen",
    "commentReference": "comment",
    "annotationRef": "comment",
    "separator": "separator",
    "continuationSeparator": "separator",
    "fldChar": "field",
    "instrText": "field",
    "AlternateContent": "object",
    "pgNum": "page number",
}

_PARA_CODE_DISPLAY = {
    "bookmarkStart": "bookmark",
    "bookmarkEnd": "bookmark",
    "fldSimple": "field",
    "oMath": "equation",
    "oMathPara": "equation",
    "commentRangeStart": "comment",
    "commentRangeEnd": "comment",
    "permStart": "permission",
    "permEnd": "permission",
    "AlternateContent": "object",
}

# Inline wrappers whose runs we translate; value is the child holding the content.
_CONTAINERS = {"hyperlink": "", "smartTag": "", "customXml": "", "sdt": "sdtContent", "dir": "", "bdo": ""}
_CONTAINER_DISPLAY = {
    "hyperlink": "link",
    "smartTag": "smart tag",
    "customXml": "custom XML",
    "sdt": "content control",
    "dir": "direction",
    "bdo": "direction",
}


def _rpr_key(rpr: etree._Element | None) -> str:
    return strip_key(rpr, lambda n: n.startswith("rsid"), {"lang"})


def _on(el: etree._Element) -> bool:
    return el.get(_w("val"), "true") not in ("0", "false", "off", "none")


def _describe(rpr: etree._Element | None) -> str:
    if rpr is None:
        return "plain"
    parts: list[str] = []
    for child in rpr:
        name = local(child)
        if name == "b" and _on(child):
            parts.append("bold")
        elif name == "i" and _on(child):
            parts.append("italic")
        elif name == "u" and _on(child):
            parts.append("underline")
        elif name in ("strike", "dstrike") and _on(child):
            parts.append("strikethrough")
        elif name == "vertAlign":
            val = child.get(_w("val"), "")
            if val in ("superscript", "subscript"):
                parts.append(val)
        elif name == "rStyle":
            parts.append(f"style {child.get(_w('val'), '')}".strip())
        elif name in ("color", "highlight", "shd"):
            parts.append("color")
        elif name in ("caps", "smallCaps") and _on(child):
            parts.append("caps")
        elif name in ("rFonts", "sz"):
            parts.append("font")
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return "+".join(seen[:3]) if seen else "format"


DIALECT = Dialect(
    ns=W,
    run=_w("r"),
    text=_w("t"),
    rpr=_w("rPr"),
    preserve_space=True,
    rpr_key=_rpr_key,
    describe_rpr=_describe,
    containers=_CONTAINERS,
)


@dataclass
class _FieldState:
    depth: int = 0
    code: CodeItem | None = None


def _field_delta(el: etree._Element) -> int:
    delta = 0
    for fc in el.iter(_w("fldChar")):
        typ = fc.get(_w("fldCharType"))
        if typ == "begin":
            delta += 1
        elif typ == "end":
            delta -= 1
    return delta


def _instr_label(el: etree._Element) -> str:
    instr = el.get(_w("instr")) if local(el) == "fldSimple" else None
    if instr is None and local(el) == "instrText":
        instr = el.text
    words = (instr or "").split()
    return f"field {words[0]}" if words else "field"


class _Walker:
    """Turns one paragraph into run-model items, carrying field state across paragraphs."""

    def __init__(self) -> None:
        self.state = _FieldState()

    def paragraph(self, p: etree._Element) -> list[Item]:
        self.state.code = None
        items: list[Item] = []
        self._walk([c for c in p if c.tag != _w("pPr")], items)
        return items

    def _field_add(
        self,
        items: list[Item],
        atom: etree._Element | tuple[etree._Element, etree._Element],
        instr_source: etree._Element | None = None,
    ) -> None:
        st = self.state
        if st.code is None:
            st.code = CodeItem([], "field")
            items.append(st.code)
        st.code.atoms.append(atom)
        if instr_source is not None and st.code.display == "field":
            st.code.display = _instr_label(instr_source)

    def _walk(self, children: list[etree._Element], items: list[Item]) -> None:
        st = self.state
        for child in children:
            if not isinstance(child.tag, str):
                continue  # comments / processing instructions inside a paragraph
            name = local(child)
            in_w = child.tag.startswith(f"{{{W}}}")
            if in_w and name in _DROP:
                continue
            if in_w and name == "r":
                self._run(child, items)
                continue
            if st.depth > 0:
                self._field_add(items, child)
                st.depth = max(0, st.depth + _field_delta(child))
                if st.depth == 0:
                    st.code = None
                continue
            if in_w and name in _CONTAINERS:
                holder_name = _CONTAINERS[name]
                if holder_name:
                    holder = child.find(_w(holder_name))
                    inner = list(holder) if holder is not None else []
                else:
                    inner = [c for c in child if not local(c).endswith("Pr")]
                sub: list[Item] = []
                self._walk(inner, sub)
                if st.depth > 0:
                    st.code = None  # a field left open inside: the outer level gets its own code
                items.append(ContainerItem(child, sub, _CONTAINER_DISPLAY[name]))
                continue
            display = _PARA_CODE_DISPLAY.get(name, name)
            if name == "fldSimple":
                display = _instr_label(child)
            items.append(CodeItem([child], display))

    def _run(self, run: etree._Element, items: list[Item]) -> None:
        st = self.state
        rpr = run.find(_w("rPr"))
        key = _rpr_key(rpr)
        for child in run:
            if not isinstance(child.tag, str):
                continue
            name = local(child)
            if child.tag == _w("rPr") or name in _DROP:
                continue
            if st.depth > 0:
                self._field_add(items, (run, child), child if name == "instrText" else None)
                if name == "fldChar":
                    typ = child.get(_w("fldCharType"))
                    st.depth += 1 if typ == "begin" else -1 if typ == "end" else 0
                    if st.depth <= 0:
                        st.depth = 0
                        st.code = None
                continue
            if name == "fldChar" and child.get(_w("fldCharType")) == "begin":
                st.depth = 1
                st.code = CodeItem([(run, child)], "field")
                items.append(st.code)
                continue
            if name == "t" and child.tag == _w("t"):
                items.append(TextItem(child.text or "", rpr, key))
                continue
            display = _RUN_CODE_DISPLAY.get(name, name)
            if name == "br":
                typ = child.get(_w("type"), "textWrapping")
                display = {"page": "page break", "column": "column break"}.get(typ, "line break")
            items.append(CodeItem([(run, child)], display))


@dataclass
class _Para:
    unit_id: str
    p: etree._Element
    model: ParagraphModel
    unit: ExtractedUnit | None


class DocxHandler:
    name = "docx"
    extensions: tuple[str, ...] = ("docx", "docm", "dotx", "dotm")

    def __init__(self, rewrite_unchanged: bool = False) -> None:
        # rewrite_unchanged forces untouched paragraphs through the rebuild path; tests use it
        # to prove the rebuild is lossless. Production leaves them byte-identical.
        self.rewrite_unchanged = rewrite_unchanged

    def _parts(self, pkg: Package) -> list[tuple[str, str]]:
        main = pkg.main_part("/officeDocument")
        parts = [(main, "body")]
        for suffix, kind in (
            ("/header", "header"),
            ("/footer", "footer"),
            ("/footnotes", "footnote"),
            ("/endnotes", "endnote"),
        ):
            for part in sorted(pkg.related(main, suffix), key=_natural):
                parts.append((part, kind))
        return parts

    def _walk_part(
        self, tree: etree._ElementTree, part: str, kind: str, lang: str, warnings: list[str]
    ) -> list[_Para]:
        root = tree.getroot()
        if any(True for _ in root.iter(*TRACKED)):
            raise FormatError(TRACKED_MESSAGE)
        walker = _Walker()
        out: list[_Para] = []
        fallback_text = False
        for idx, p in enumerate(root.iter(_w("p"))):
            if any(a.tag == qn(MC_NS, "Fallback") for a in p.iterancestors()):
                fallback_text = fallback_text or bool("".join(p.itertext()).strip())
                continue
            items = walker.paragraph(p)
            model = build_paragraph_model(items, DIALECT)
            context = kind
            if kind == "body" and any(a.tag == _w("tc") for a in p.iterancestors()):
                context = "table"
            uid = f"{part}#{idx}"
            unit = make_unit(uid, model.content, lang, context=context)
            out.append(_Para(uid, p, model, unit))
        if fallback_text:
            warnings.append(
                f"{part}: text boxes also have a legacy copy for very old Word versions; that copy is not translated."
            )
        return out

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        pkg = Package(data, "DOCX")
        units: list[ExtractedUnit] = []
        warnings: list[str] = []
        for part, kind in self._parts(pkg):
            for para in self._walk_part(pkg.xml(part), part, kind, source_lang, warnings):
                if para.unit is not None:
                    units.append(para.unit)
        return ExtractionResult(self.name, source_lang, units, warnings)

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        pkg = Package(original, "DOCX")
        replacements: dict[str, bytes] = {}
        known: list[str] = []
        for part, kind in self._parts(pkg):
            tree = pkg.xml(part)
            # Walk the whole part before touching it: rebuilding a paragraph moves live
            # elements (text boxes hold paragraphs of their own) and the walk must see the original.
            paras = self._walk_part(tree, part, kind, "en", [])
            touched = False
            for para in paras:
                if para.unit is None:
                    continue
                known.append(para.unit_id)
                tgt = targets.get(para.unit_id)
                if tgt is None:
                    continue
                content, changed = resolve_target(para.unit, tgt, resegment=True)
                if not changed and not self.rewrite_unchanged:
                    continue
                children = render_paragraph(content, para.model, DIALECT, para.unit_id)
                replace_children(para.p, children, head={"pPr"}, tail=set())
                touched = True
            if touched:
                replacements[part] = serialize_xml(tree)
        check_target_ids(targets, known)
        if not replacements:
            return original
        return pkg.write(replacements)


def _natural(name: str) -> tuple:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name))
