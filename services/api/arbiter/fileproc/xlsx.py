"""XLSX (SpreadsheetML) handler: shared strings and inline strings.

Excel stores most cell text once in xl/sharedStrings.xml and points cells at it by
index, so one shared string is one unit no matter how many cells show it. Cells with
inline strings (t="inlineStr", common in generated files) are units of their own.
Formula cells are never touched: their cached value is recomputed by Excel.

A cell is not split into sentences: a cell is the smallest thing a spreadsheet user
edits, and engines handle the short texts well. Rich text runs (<r><rPr/><t/></r>)
go through the same run model as Word so a bold word inside a cell becomes a paired code.

Excel escapes characters XML cannot hold as _xHHHH_; we decode them for translators and
encode them again on write so a carriage return in a cell survives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, TargetMap
from arbiter.fileproc.ooxml import (
    Dialect,
    Item,
    Package,
    ParagraphModel,
    TextItem,
    build_paragraph_model,
    qn,
    render_paragraph,
    serialize_xml,
    strip_key,
)
from arbiter.fileproc.text import check_target_ids, make_unit, resolve_target

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_ESC = re.compile(r"_x([0-9A-Fa-f]{4})_")
_LITERAL_ESC = re.compile(r"_(x[0-9A-Fa-f]{4}_)")
_NEEDS_ESC = re.compile("[\x00-\x08\x0b\x0c\x0d\x0e-\x1f￾￿]")


def decode_x(text: str) -> str:
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), text)


def encode_x(text: str) -> str:
    text = _LITERAL_ESC.sub(r"_x005F_\1", text)
    return _NEEDS_ESC.sub(lambda m: f"_x{ord(m.group(0)):04X}_", text)


def _s(name: str) -> str:
    return qn(S, name)


def _describe(rpr: etree._Element | None) -> str:
    if rpr is None:
        return "plain"
    names = {c.tag.rsplit("}", 1)[-1] for c in rpr if isinstance(c.tag, str)}
    parts = [
        label
        for tag, label in (
            ("b", "bold"),
            ("i", "italic"),
            ("u", "underline"),
            ("strike", "strikethrough"),
            ("vertAlign", "position"),
            ("color", "color"),
            ("rFont", "font"),
            ("sz", "size"),
        )
        if tag in names
    ]
    return "+".join(parts[:3]) if parts else "format"


DIALECT = Dialect(
    ns=S,
    run=_s("r"),
    text=_s("t"),
    rpr=_s("rPr"),
    preserve_space=True,
    rpr_key=lambda rpr: strip_key(rpr, lambda n: False, set()),
    describe_rpr=_describe,
)


def _items(si: etree._Element) -> list[Item]:
    items: list[Item] = []
    for child in si:
        if child.tag == _s("t"):
            items.append(TextItem(decode_x(child.text or ""), None, ""))
        elif child.tag == _s("r"):
            rpr = child.find(_s("rPr"))
            t = child.find(_s("t"))
            items.append(
                TextItem(decode_x((t.text or "") if t is not None else ""), rpr, DIALECT.rpr_key(rpr))
            )
    return items


def _rewrite(si: etree._Element, content: Content, model: ParagraphModel, unit_id: str) -> None:
    encoded: Content = [encode_x(r) if isinstance(r, str) else r for r in content]
    children = render_paragraph(encoded, model, DIALECT, unit_id)
    phonetic = si.find(_s("phoneticPr"))
    for child in list(si):
        si.remove(child)
    # A string without any run formatting is stored as a single <t>, as Excel does.
    if all(c.tag == _s("r") and c.find(_s("rPr")) is None for c in children):
        t = etree.SubElement(si, _s("t"))
        text = "".join((c.find(_s("t")).text or "") for c in children)  # type: ignore[union-attr]
        t.text = text
        if text != text.strip():
            t.set(qn("http://www.w3.org/XML/1998/namespace", "space"), "preserve")
    else:
        for c in children:
            si.append(c)
    # Phonetic runs (rPh) point at character offsets of the source text, so they are dropped.
    if phonetic is not None:
        si.append(phonetic)


@dataclass
class _Entry:
    unit_id: str
    elem: etree._Element  # <si> or <is>
    model: ParagraphModel
    unit: ExtractedUnit | None


class XlsxHandler:
    name = "xlsx"
    extensions: tuple[str, ...] = ("xlsx", "xlsm", "xltx")

    def __init__(self, rewrite_unchanged: bool = False) -> None:
        self.rewrite_unchanged = rewrite_unchanged

    def _sheets(self, pkg: Package, workbook: str) -> list[tuple[str, str]]:
        rels = {rid: target for _, target, rid in pkg.rels(workbook)}
        out = []
        for sheet in pkg.xml(workbook).getroot().iter(_s("sheet")):
            target = rels.get(sheet.get(qn(R, "id"), ""))
            if target and target in pkg.names:
                out.append((sheet.get("name", ""), target))
        return out

    def _walk(self, pkg: Package, lang: str, trees: dict[str, etree._ElementTree]) -> list[_Entry]:
        workbook = pkg.main_part("/officeDocument")
        sheets = self._sheets(pkg, workbook)
        first_ref: dict[int, str] = {}
        inline: list[tuple[str, str, str, etree._Element]] = []
        for sheet_name, part in sheets:
            tree = trees.setdefault(part, pkg.xml(part))
            for c in tree.getroot().iter(_s("c")):
                typ = c.get("t")
                ref = c.get("r", "")
                if typ == "s":
                    v = c.find(_s("v"))
                    if v is not None and (v.text or "").strip().isdigit():
                        first_ref.setdefault(int(v.text.strip()), f"sheet:{sheet_name}!{ref}")  # type: ignore[union-attr]
                elif typ == "inlineStr" and c.find(_s("f")) is None:
                    is_el = c.find(_s("is"))
                    if is_el is not None:
                        inline.append((sheet_name, part, ref, is_el))

        entries: list[_Entry] = []
        for sst_part in pkg.related(workbook, "/sharedStrings"):
            tree = trees.setdefault(sst_part, pkg.xml(sst_part))
            for idx, si in enumerate(tree.getroot().iter(_s("si"))):
                if idx not in first_ref:
                    continue  # orphan strings are invisible; translating them costs money for nothing
                model = build_paragraph_model(_items(si), DIALECT)
                uid = f"{sst_part}#{idx}"
                unit = make_unit(uid, model.content, lang, segment=False, context=first_ref[idx])
                entries.append(_Entry(uid, si, model, unit))
        for sheet_name, part, ref, is_el in inline:
            model = build_paragraph_model(_items(is_el), DIALECT)
            uid = f"{part}!{ref}"
            unit = make_unit(uid, model.content, lang, segment=False, context=f"sheet:{sheet_name}!{ref}")
            entries.append(_Entry(uid, is_el, model, unit))
        return entries

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        pkg = Package(data, "XLSX")
        entries = self._walk(pkg, source_lang, {})
        return ExtractionResult(self.name, source_lang, [e.unit for e in entries if e.unit is not None])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        pkg = Package(original, "XLSX")
        trees: dict[str, etree._ElementTree] = {}
        entries = self._walk(pkg, "en", trees)
        check_target_ids(targets, (e.unit_id for e in entries if e.unit is not None))
        touched: set[str] = set()
        for e in entries:
            if e.unit is None or e.unit_id not in targets:
                continue
            content, changed = resolve_target(e.unit, targets[e.unit_id])
            if not changed and not self.rewrite_unchanged:
                continue
            _rewrite(e.elem, content, e.model, e.unit_id)
            touched.add(e.unit_id.split("#", 1)[0].split("!", 1)[0])
        if not touched:
            return original
        return pkg.write({part: serialize_xml(trees[part]) for part in touched})
