"""PPTX (PresentationML) handler: slide text and speaker notes.

Text lives in DrawingML paragraphs (a:p) inside shapes, tables and groups. We use the
same run model as DOCX: runs whose a:rPr differ only in language, spell-check or
revision attributes are merged, deviations from the dominant formatting become paired
codes, a:br and a:fld (slide numbers, dates) become standalone codes. Hyperlinks in
DrawingML are run properties (a:hlinkClick inside a:rPr), so they surface as formatting
codes displayed as "link".

Slide layouts and masters are not translated: their placeholder prompts never show in
a finished presentation. SmartArt, charts and embedded objects keep their own XML parts
and are reported as a limitation rather than half-translated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from arbiter.fileproc.base import ExtractedUnit, ExtractionResult, TargetMap
from arbiter.fileproc.ooxml import (
    MC_NS,
    CodeItem,
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

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_IGNORED_RPR_ATTRS = {"lang", "altLang", "dirty", "err", "smtClean", "smtId", "noProof", "bmk"}


def _rpr_key(rpr: etree._Element | None) -> str:
    return strip_key(rpr, lambda n: n in _IGNORED_RPR_ATTRS, set())


def _describe(rpr: etree._Element | None) -> str:
    if rpr is None:
        return "plain"
    parts: list[str] = []
    if rpr.get("b") in ("1", "true"):
        parts.append("bold")
    if rpr.get("i") in ("1", "true"):
        parts.append("italic")
    if rpr.get("u") not in (None, "none"):
        parts.append("underline")
    if rpr.get("strike") not in (None, "noStrike"):
        parts.append("strikethrough")
    baseline = rpr.get("baseline")
    if baseline and baseline.lstrip("-").isdigit() and int(baseline) != 0:
        parts.append("superscript" if int(baseline) > 0 else "subscript")
    for child in rpr:
        name = local(child)
        if name in ("hlinkClick", "hlinkMouseOver"):
            parts.insert(0, "link")
        elif name in ("solidFill", "gradFill", "highlight"):
            parts.append("color")
        elif name in ("latin", "ea", "cs"):
            parts.append("font")
    if rpr.get("sz"):
        parts.append("size")
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return "+".join(seen[:3]) if seen else "format"


DIALECT = Dialect(
    ns=A,
    run=qn(A, "r"),
    text=qn(A, "t"),
    rpr=qn(A, "rPr"),
    preserve_space=False,
    rpr_key=_rpr_key,
    describe_rpr=_describe,
)

_HEAD = {"pPr"}
_TAIL = {"endParaRPr"}


def _paragraph_items(p: etree._Element) -> list[Item]:
    items: list[Item] = []
    for child in p:
        if not isinstance(child.tag, str):
            continue
        name = local(child)
        if child.tag.startswith(f"{{{A}}}") and name in _HEAD | _TAIL:
            continue
        if child.tag == qn(A, "r"):
            rpr = child.find(qn(A, "rPr"))
            key = _rpr_key(rpr)
            t = child.find(qn(A, "t"))
            others = [c for c in child if c.tag not in (qn(A, "rPr"), qn(A, "t"))]
            if others:
                # Unknown run content (extensions): keep the whole run untouched.
                items.append(CodeItem([child], "object"))
                continue
            items.append(TextItem((t.text or "") if t is not None else "", rpr, key))
        elif child.tag == qn(A, "br"):
            items.append(CodeItem([child], "line break"))
        elif child.tag == qn(A, "fld"):
            typ = child.get("type", "")
            label = "slide number" if typ == "slidenum" else "date" if typ.startswith("datetime") else "field"
            items.append(CodeItem([child], label))
        else:
            items.append(CodeItem([child], name))
    return items


@dataclass
class _Para:
    unit_id: str
    p: etree._Element
    model: ParagraphModel
    unit: ExtractedUnit | None


class PptxHandler:
    name = "pptx"
    extensions: tuple[str, ...] = ("pptx", "pptm", "potx", "ppsx")

    def __init__(self, rewrite_unchanged: bool = False) -> None:
        self.rewrite_unchanged = rewrite_unchanged

    def _parts(self, pkg: Package) -> list[tuple[str, str]]:
        pres = pkg.main_part("/officeDocument")
        rels = {rid: target for typ, target, rid in pkg.rels(pres) if typ.endswith("/slide")}
        order: list[str] = []
        root = pkg.xml(pres).getroot()
        for sld in root.iter(qn(P, "sldId")):
            target = rels.get(sld.get(qn(R, "id"), ""))
            if target and target in pkg.names and target not in order:
                order.append(target)
        for target in sorted(rels.values(), key=_natural):
            if target in pkg.names and target not in order:
                order.append(target)  # slides not listed in sldIdLst are still in the file
        parts: list[tuple[str, str]] = []
        for slide in order:
            parts.append((slide, "slide"))
            for notes in pkg.related(slide, "/notesSlide"):
                parts.append((notes, "notes"))
        return parts

    def _walk_part(self, tree: etree._ElementTree, part: str, kind: str, lang: str) -> list[_Para]:
        out: list[_Para] = []
        for idx, p in enumerate(tree.getroot().iter(qn(A, "p"))):
            if any(a.tag == qn(MC_NS, "Fallback") for a in p.iterancestors()):
                continue
            model = build_paragraph_model(_paragraph_items(p), DIALECT)
            context = kind
            if kind == "slide" and any(a.tag == qn(A, "tbl") for a in p.iterancestors()):
                context = "table"
            uid = f"{part}#{idx}"
            out.append(_Para(uid, p, model, make_unit(uid, model.content, lang, context=context)))
        return out

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        pkg = Package(data, "PPTX")
        units: list[ExtractedUnit] = []
        for part, kind in self._parts(pkg):
            units.extend(p.unit for p in self._walk_part(pkg.xml(part), part, kind, source_lang) if p.unit)
        return ExtractionResult(self.name, source_lang, units)

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        pkg = Package(original, "PPTX")
        replacements: dict[str, bytes] = {}
        known: list[str] = []
        for part, kind in self._parts(pkg):
            tree = pkg.xml(part)
            paras = self._walk_part(tree, part, kind, "en")
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
                replace_children(para.p, children, head=_HEAD, tail=_TAIL)
                touched = True
            if touched:
                replacements[part] = serialize_xml(tree)
        check_target_ids(targets, known)
        return pkg.write(replacements) if replacements else original


def _natural(name: str) -> tuple:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name))
