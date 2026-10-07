"""XLIFF 1.2 and 2.x handler, plus XLIFF 2.1 export/import for any job.

As a FormatHandler: source text is extracted (existing targets are ignored), and merge
writes <target> elements back into the same file in its own version, touching nothing
else. Existing segmentation is respected: 2.x <segment> elements, 1.2 <seg-source>
with <mrk mtype="seg">. A 1.2 unit without seg-source is segmented by us and written
back as one target.

Inline elements map to codes whose `original` is the element's XML. Container elements
(1.2 g/mrk, 2.x pc/mrk) become paired codes, start/end markers (bx/ex, bpt/ept, sc/ec,
sm/em) become paired codes when both ends are in the segment, everything else is
standalone. On merge the live elements of the source are copied into the target, so
ids and attributes always match the source as XLIFF requires.

export_xliff21 / import_xliff_targets let the platform hand a client an XLIFF of any
extracted job and take an edited file back, independent of the job's original format.
Code markup travels in <originalData> so a round trip through a CAT tool is lossless.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from lxml import etree

from arbiter.fileproc.base import (
    Content,
    ExtractedUnit,
    ExtractionResult,
    FormatError,
    InlineCode,
    SegmentDraft,
    TargetMap,
    codes_of,
)
from arbiter.fileproc.ooxml import element_markup, local, parse_xml, serialize_xml
from arbiter.fileproc.text import (
    check_codes,
    check_target_ids,
    check_xml_text,
    has_text,
    make_unit,
    normalize,
    refit,
    resolve_segments,
    resolve_target,
)

X12 = "urn:oasis:names:tc:xliff:document:1.2"
X2 = "urn:oasis:names:tc:xliff:document:2.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_CONTAINERS = {"g", "mrk", "pc"}
_OPENERS = {"bx", "bpt", "sc", "sm"}
_CLOSERS = {"ex", "ept", "ec", "em"}


def _q(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


@dataclass
class _CodeRef:
    mode: str  # container | element
    elem: etree._Element


@dataclass
class _Seg:
    """Where a segment lives and the code table needed to render a target for it."""

    source: etree._Element  # element whose children are the segment content (source or mrk)
    codes: dict[str, _CodeRef]
    content: Content


@dataclass
class _Unit:
    unit_id: str
    elem: etree._Element  # trans-unit (1.2) or unit (2.x)
    version: int
    segs: list[_Seg]
    segmented_by_us: bool
    unit: ExtractedUnit
    seg_source: etree._Element | None = None
    seg_mrks: list[etree._Element] = field(default_factory=list)


def _marker_key(el: etree._Element, version: int) -> str | None:
    name = local(el)
    if version == 2:
        if name in ("sc", "sm"):
            return el.get("id")
        if name in ("ec", "em"):
            return el.get("startRef") or el.get("id")
        return None
    return el.get("rid") or el.get("id")


def _display(el: etree._Element) -> str:
    name = local(el)
    for attr in ("disp", "dispStart", "equiv", "equivStart", "ctype"):
        if el.get(attr):
            return el.get(attr)  # type: ignore[return-value]
    text = "".join(el.itertext()).strip()
    if text and name in ("ph", "it", "bpt", "ept"):
        return text[:40]
    return f"<{name}>"


class _Converter:
    """Inline XLIFF markup -> content, with a code id counter shared by the whole unit."""

    def __init__(self, version: int) -> None:
        self.version = version
        self.n = 0

    def segment(self, el: etree._Element) -> tuple[Content, dict[str, _CodeRef]]:
        # Pair start/end markers inside this segment first.
        markers: list[etree._Element] = []

        def collect(parent: etree._Element) -> None:
            for child in parent:
                if not isinstance(child.tag, str):
                    continue
                name = local(child)
                if name in _OPENERS | _CLOSERS:
                    markers.append(child)
                elif name in _CONTAINERS and not (name == "mrk" and child.get("mtype") == "seg"):
                    collect(child)

        collect(el)
        open_by_key: dict[str, etree._Element] = {}
        partner: dict[int, etree._Element] = {}
        for m in markers:
            key = _marker_key(m, self.version)
            if key is None or (self.version == 2 and m.get("isolated") == "yes"):
                continue
            if local(m) in _OPENERS:
                open_by_key[key] = m
            elif key in open_by_key:
                o = open_by_key.pop(key)
                partner[id(o)] = m
                partner[id(m)] = o
        ids: dict[int, str] = {}
        codes: dict[str, _CodeRef] = {}
        content: Content = []

        def new_id() -> str:
            self.n += 1
            return str(self.n)

        def walk(parent: etree._Element) -> None:
            if parent.text:
                content.append(parent.text)
            for child in parent:
                if isinstance(child.tag, str):
                    name = local(child)
                    if name in _CONTAINERS and not (name == "mrk" and child.get("mtype") == "seg"):
                        cid = new_id()
                        codes[cid] = _CodeRef("container", child)
                        content.append(InlineCode(cid, "open", _start_tag(child), _display(child)))
                        walk(child)
                        content.append(InlineCode(cid, "close", f"</{name}>", _display(child)))
                    elif id(child) in partner and name in _OPENERS:
                        cid = new_id()
                        ids[id(partner[id(child)])] = cid
                        codes[cid] = _CodeRef("element", child)
                        content.append(InlineCode(cid, "open", element_markup(child), _display(child)))
                    elif id(child) in partner:
                        cid = ids[id(child)]
                        codes[cid + "/close"] = _CodeRef("element", child)
                        content.append(InlineCode(cid, "close", element_markup(child), _display(child)))
                    elif name == "cp" and self.version == 2:
                        cid = new_id()
                        codes[cid] = _CodeRef("element", child)
                        content.append(InlineCode(cid, "standalone", element_markup(child), "char"))
                    else:
                        cid = new_id()
                        codes[cid] = _CodeRef("element", child)
                        content.append(InlineCode(cid, "standalone", element_markup(child), _display(child)))
                if child.tail:
                    content.append(child.tail)

        walk(el)
        return normalize(content), codes


def _start_tag(el: etree._Element) -> str:
    c = etree.Element(el.tag, attrib=dict(el.attrib), nsmap=el.nsmap)
    etree.cleanup_namespaces(c)
    s = etree.tostring(c, encoding="unicode")
    return s[:-2] + ">" if s.endswith("/>") else s


def _render(target: etree._Element, content: Content, codes: dict[str, _CodeRef], unit_id: str) -> None:
    """Fill an empty element with content, copying source inline elements."""
    stack: list[tuple[etree._Element, etree._Element | None]] = []
    cur: etree._Element = target
    last: etree._Element | None = None

    def text(t: str) -> None:
        check_xml_text(t, unit_id)
        if last is None:
            cur.text = (cur.text or "") + t
        else:
            last.tail = (last.tail or "") + t

    for item in content:
        if isinstance(item, str):
            text(item)
            continue
        key = item.id + "/close" if item.kind == "close" and item.id + "/close" in codes else item.id
        ref = codes.get(key)
        if ref is None:
            raise FormatError(
                f"The translation of unit {unit_id} contains inline code {item.id} which is not in the source."
            )
        if ref.mode == "container":
            if item.kind == "open":
                el = etree.SubElement(cur, ref.elem.tag, attrib=dict(ref.elem.attrib))
                stack.append((cur, el))
                cur, last = el, None
            else:
                parent, el = stack.pop()
                cur, last = parent, el
            continue
        el = copy.deepcopy(ref.elem)
        el.tail = None
        cur.append(el)
        last = el


class XliffHandler:
    name = "xliff"
    extensions: tuple[str, ...] = ("xlf", "xliff")

    def _units(self, root: etree._Element, lang: str) -> list[_Unit]:
        ns = etree.QName(root).namespace
        if ns == X12:
            return self._units12(root, lang)
        if ns == X2:
            return self._units2(root, lang)
        raise FormatError("The file is not a supported XLIFF version (1.2, 2.0 or 2.1).")

    def _units12(self, root: etree._Element, lang: str) -> list[_Unit]:
        out: list[_Unit] = []
        for fi, file_el in enumerate(root.iter(_q(X12, "file"))):
            for tu in file_el.iter(_q(X12, "trans-unit")):
                if any(a.get("translate") == "no" for a in [tu, *tu.iterancestors()]):
                    continue
                uid = f"{fi + 1}:{tu.get('id', '')}"
                notes = [n.text.strip() for n in tu.findall(_q(X12, "note")) if n.text and n.text.strip()]
                max_len = tu.get("maxwidth") if tu.get("size-unit", "pixel") == "char" else None
                context = tu.get("resname") or ""
                conv = _Converter(1)
                seg_source = tu.find(_q(X12, "seg-source"))
                mrks = (
                    [m for m in seg_source.iter(_q(X12, "mrk")) if m.get("mtype") == "seg"]
                    if seg_source is not None
                    else []
                )
                if mrks:
                    assert seg_source is not None
                    segs: list[_Seg] = []
                    drafts: list[SegmentDraft] = []
                    for m in mrks:
                        content, codes = conv.segment(m)
                        segs.append(_Seg(m, codes, content))
                        drafts.append(
                            SegmentDraft(
                                content=content,
                                trailing_ws=(m.tail or "") if not (m.tail or "").strip() else "",
                            )
                        )
                    if not any(has_text(s.content) for s in segs):
                        continue
                    unit = ExtractedUnit(
                        uid,
                        drafts,
                        context=context,
                        notes=notes,
                        max_length=int(max_len) if max_len and max_len.isdigit() else None,
                        leading_ws=seg_source.text if seg_source.text and not seg_source.text.strip() else "",
                    )
                    out.append(_Unit(uid, tu, 1, segs, False, unit, seg_source, mrks))
                    continue
                source = tu.find(_q(X12, "source"))
                if source is None:
                    continue
                content, codes = conv.segment(source)
                built = make_unit(
                    uid,
                    content,
                    lang,
                    context=context,
                    notes=notes,
                    max_length=int(max_len) if max_len and max_len.isdigit() else None,
                )
                if built is None:
                    continue
                out.append(_Unit(uid, tu, 1, [_Seg(source, codes, content)], True, built))
        return out

    def _units2(self, root: etree._Element, lang: str) -> list[_Unit]:
        out: list[_Unit] = []
        for fi, file_el in enumerate(root.iter(_q(X2, "file"))):
            for u in file_el.iter(_q(X2, "unit")):
                if any(a.get("translate") == "no" for a in [u, *u.iterancestors()]):
                    continue
                uid = f"{fi + 1}:{u.get('id', '')}"
                notes = [n.text.strip() for n in u.iter(_q(X2, "note")) if n.text and n.text.strip()]
                conv = _Converter(2)
                segs: list[_Seg] = []
                drafts: list[SegmentDraft] = []
                leading = ""
                for child in u:
                    name = local(child)
                    src = child.find(_q(X2, "source"))
                    if src is None:
                        continue
                    if name == "segment":
                        content, codes = conv.segment(src)
                        segs.append(_Seg(src, codes, content))
                        drafts.append(SegmentDraft(content=content))
                    elif name == "ignorable":
                        ws = "".join(src.itertext())
                        if drafts:
                            drafts[-1].trailing_ws += ws
                        else:
                            leading += ws
                if not segs or not any(has_text(s.content) for s in segs):
                    continue
                unit = ExtractedUnit(
                    uid, drafts, context=u.get("name") or "", notes=notes, leading_ws=leading
                )
                out.append(_Unit(uid, u, 2, segs, False, unit))
        return out

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        root = parse_xml(data).getroot()
        units = self._units(root, source_lang)
        return ExtractionResult(self.name, source_lang, [u.unit for u in units])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        tree = parse_xml(original)
        root = tree.getroot()
        units = self._units(root, "en")
        check_target_ids(targets, (u.unit_id for u in units))
        for u in units:
            tgt = targets.get(u.unit_id)
            if tgt is None:
                continue
            if u.version == 1:
                self._merge12(u, tgt, target_lang)
            else:
                self._merge2(u, tgt)
        if root.tag == _q(X2, "xliff") and not root.get("trgLang"):
            root.set("trgLang", target_lang)
        return serialize_xml(tree)

    def _merge12(self, u: _Unit, tgt: list[Content], target_lang: str) -> None:
        tu = u.elem
        file_el = next((a for a in tu.iterancestors() if a.tag == _q(X12, "file")), None)
        if file_el is not None and not file_el.get("target-language"):
            file_el.set("target-language", target_lang)
        old = tu.find(_q(X12, "target"))
        anchor = u.seg_source if u.seg_source is not None else tu.find(_q(X12, "source"))
        target = etree.Element(_q(X12, "target"))
        if old is not None:
            target.attrib.update(old.attrib)
            tu.remove(old)
        target.set("state", "translated")
        assert anchor is not None
        anchor.addnext(target)
        target.tail = anchor.tail
        if u.segmented_by_us:
            unit = refit(u.unit, len(tgt))
            content, _ = resolve_target(unit, tgt)
            _render(target, content, u.segs[0].codes, u.unit_id)
            return
        segs = resolve_segments(u.unit, tgt)
        for seg, src in zip(segs, u.segs, strict=True):
            check_codes(seg, src.content, u.unit_id)
        assert u.seg_source is not None
        clone = copy.deepcopy(u.seg_source)
        mrks = [m for m in clone.iter(_q(X12, "mrk")) if m.get("mtype") == "seg"]
        target.text = clone.text
        for child in clone:
            target.append(child)
        for m, seg, src in zip(mrks, segs, u.segs, strict=True):
            tail = m.tail
            for c in list(m):
                m.remove(c)
            m.text = None
            _render(m, seg, src.codes, u.unit_id)
            m.tail = tail

    def _merge2(self, u: _Unit, tgt: list[Content]) -> None:
        segs = resolve_segments(u.unit, tgt)
        for seg, src in zip(segs, u.segs, strict=True):
            check_codes(seg, src.content, u.unit_id)
            segment = src.source.getparent()
            assert segment is not None
            old = segment.find(_q(X2, "target"))
            target = etree.Element(_q(X2, "target"))
            if old is not None:
                target.attrib.update(old.attrib)
                segment.remove(old)
            space = src.source.get(_q(XML_NS, "space"))
            if space:
                target.set(_q(XML_NS, "space"), space)
            src.source.addnext(target)
            target.tail = src.source.tail
            _render(target, seg, src.codes, u.unit_id)
            if segment.get("state") not in ("reviewed", "final"):
                segment.set("state", "translated")


# --------------------------------------------------------------------------- export / import


def _seg_pairs(content: Content) -> set[str]:
    stack: list[str] = []
    matched: set[str] = set()
    for c in codes_of(content):
        if c.kind == "open":
            stack.append(c.id)
        elif c.kind == "close" and stack and stack[-1] == c.id:
            stack.pop()
            matched.add(c.id)
    return matched


def _export_content(parent: etree._Element, content: Content, unit_id: str) -> None:
    matched = _seg_pairs(content)
    stack: list[etree._Element] = []
    cur = parent
    last: etree._Element | None = None
    for item in content:
        if isinstance(item, str):
            check_xml_text(item, unit_id)
            if last is None:
                cur.text = (cur.text or "") + item
            else:
                last.tail = (last.tail or "") + item
            continue
        disp = item.display or ""
        if item.kind == "standalone":
            el = etree.SubElement(cur, _q(X2, "ph"), id=item.id, dataRef=f"d{item.id}")
            if disp:
                el.set("disp", disp)
            last = el
        elif item.kind == "open" and item.id in matched:
            el = etree.SubElement(
                cur, _q(X2, "pc"), id=item.id, dataRefStart=f"d{item.id}s", dataRefEnd=f"d{item.id}e"
            )
            if disp:
                el.set("dispStart", disp)
            stack.append(cur)
            cur, last = el, None
        elif item.kind == "close" and item.id in matched:
            closed = cur
            cur = stack.pop()
            last = closed
        elif item.kind == "open":
            el = etree.SubElement(cur, _q(X2, "sc"), id=item.id, dataRef=f"d{item.id}s")
            if disp:
                el.set("disp", disp)
            last = el
        else:
            el = etree.SubElement(cur, _q(X2, "ec"), startRef=item.id, dataRef=f"d{item.id}e")
            if disp:
                el.set("disp", disp)
            last = el


def export_xliff21(
    result: ExtractionResult,
    targets: TargetMap | None,
    source_lang: str,
    target_lang: str,
    original_name: str,
) -> bytes:
    """Write any extraction (and optional translations) as an XLIFF 2.1 file for CAT tools.

    Unit ids in XLIFF must be NMTOKENs, which our unit ids (paths, pointers) are not, so
    units get ids u1, u2, ... and carry the real unit id in the name attribute.
    """
    root = etree.Element(
        _q(X2, "xliff"), nsmap={None: X2}, version="2.1", srcLang=source_lang, trgLang=target_lang
    )
    file_el = etree.SubElement(root, _q(X2, "file"), id="f1", original=original_name)
    for n, unit in enumerate(result.units, start=1):
        u = etree.SubElement(file_el, _q(X2, "unit"), id=f"u{n}", name=unit.unit_id)
        note_texts = []
        if unit.context:
            note_texts.append(("context", unit.context))
        note_texts += [("note", t) for t in unit.notes]
        if unit.max_length:
            note_texts.append(("max-length", f"Maximum length: {unit.max_length}"))
        if note_texts:
            notes = etree.SubElement(u, _q(X2, "notes"))
            for cat, t in note_texts:
                check_xml_text(t, unit.unit_id)
                etree.SubElement(notes, _q(X2, "note"), category=cat).text = t
        data: dict[str, str] = {}
        tgt = (targets or {}).get(unit.unit_id)
        for content in [s.content for s in unit.segments] + (tgt or []):
            for c in codes_of(content):
                suffix = {"standalone": "", "open": "s", "close": "e"}[c.kind]
                data.setdefault(f"d{c.id}{suffix}", c.original)
        if data:
            od = etree.SubElement(u, _q(X2, "originalData"))
            for did, original in data.items():
                check_xml_text(original, unit.unit_id)
                d = etree.SubElement(od, _q(X2, "data"), id=did)
                d.text = original
                d.set(_q(XML_NS, "space"), "preserve")
        if unit.leading_ws:
            ign = etree.SubElement(u, _q(X2, "ignorable"))
            etree.SubElement(ign, _q(X2, "source")).text = unit.leading_ws
        if tgt is not None and len(tgt) != len(unit.segments):
            raise FormatError(f"The translation of unit {unit.unit_id} does not match its segments.")
        for i, seg in enumerate(unit.segments):
            s = etree.SubElement(u, _q(X2, "segment"), id=f"s{i + 1}")
            if tgt is not None:
                s.set("state", "translated")
            src = etree.SubElement(s, _q(X2, "source"))
            src.set(_q(XML_NS, "space"), "preserve")
            _export_content(src, seg.content, unit.unit_id)
            if tgt is not None:
                t = etree.SubElement(s, _q(X2, "target"))
                t.set(_q(XML_NS, "space"), "preserve")
                _export_content(t, tgt[i], unit.unit_id)
            if seg.trailing_ws:
                ign = etree.SubElement(u, _q(X2, "ignorable"))
                isrc = etree.SubElement(ign, _q(X2, "source"))
                isrc.text = seg.trailing_ws
                isrc.set(_q(XML_NS, "space"), "preserve")
    return etree.tostring(etree.ElementTree(root), xml_declaration=True, encoding="UTF-8", pretty_print=False)


def _import_content(el: etree._Element, data: dict[str, str], version: int) -> Content:
    out: Content = []

    def walk(parent: etree._Element) -> None:
        if parent.text:
            out.append(parent.text)
        for child in parent:
            if isinstance(child.tag, str):
                name = local(child)
                if version == 2:
                    if name == "pc":
                        cid = child.get("id", "")
                        out.append(
                            InlineCode(
                                cid,
                                "open",
                                data.get(child.get("dataRefStart", ""), ""),
                                child.get("dispStart", ""),
                            )
                        )
                        walk(child)
                        out.append(
                            InlineCode(
                                cid,
                                "close",
                                data.get(child.get("dataRefEnd", ""), ""),
                                child.get("dispStart", ""),
                            )
                        )
                    elif name == "ph":
                        out.append(
                            InlineCode(
                                child.get("id", ""),
                                "standalone",
                                data.get(child.get("dataRef", ""), ""),
                                child.get("disp", ""),
                            )
                        )
                    elif name == "sc":
                        out.append(
                            InlineCode(
                                child.get("id", ""),
                                "open",
                                data.get(child.get("dataRef", ""), ""),
                                child.get("disp", ""),
                            )
                        )
                    elif name == "ec":
                        out.append(
                            InlineCode(
                                child.get("startRef") or child.get("id", ""),
                                "close",
                                data.get(child.get("dataRef", ""), ""),
                                child.get("disp", ""),
                            )
                        )
                    elif name == "cp":
                        out.append(chr(int(child.get("hex", "0"), 16)))
                    elif name in ("mrk", "sm", "em"):
                        walk(child)  # annotations added by a reviewer are not part of the text
                    else:
                        walk(child)
                else:
                    if name == "g":
                        cid = child.get("id", "")
                        out.append(InlineCode(cid, "open", "", "<g>"))
                        walk(child)
                        out.append(InlineCode(cid, "close", "", "</g>"))
                    elif name in ("x", "ph", "it"):
                        out.append(InlineCode(child.get("id", ""), "standalone", element_markup(child), name))
                    elif name in ("bx", "bpt"):
                        out.append(
                            InlineCode(
                                child.get("rid") or child.get("id", ""), "open", element_markup(child), name
                            )
                        )
                    elif name in ("ex", "ept"):
                        out.append(
                            InlineCode(
                                child.get("rid") or child.get("id", ""), "close", element_markup(child), name
                            )
                        )
                    else:
                        walk(child)
            if child.tail:
                out.append(child.tail)

    walk(el)
    return normalize(out)


def import_xliff_targets(data: bytes) -> TargetMap:
    """Read translations back from an XLIFF file (2.x as exported by us, or 1.2).

    A unit is returned only when every one of its segments has a target, so a partially
    translated unit is never merged half way.
    """
    root = parse_xml(data).getroot()
    ns = etree.QName(root).namespace
    out: TargetMap = {}
    if ns == X2:
        for u in root.iter(_q(X2, "unit")):
            key = u.get("name") or u.get("id") or ""
            od = {d.get("id", ""): d.text or "" for d in u.iter(_q(X2, "data"))}
            segs: list[Content] = []
            complete = True
            for s in u.iter(_q(X2, "segment")):
                t = s.find(_q(X2, "target"))
                if t is None:
                    complete = False
                    break
                segs.append(_import_content(t, od, 2))
            if complete and segs:
                out[key] = segs
        return out
    if ns == X12:
        for tu in root.iter(_q(X12, "trans-unit")):
            key = tu.get("resname") or tu.get("id") or ""
            t = tu.find(_q(X12, "target"))
            if t is None:
                continue
            mrks = [m for m in t.iter(_q(X12, "mrk")) if m.get("mtype") == "seg"]
            out[key] = [_import_content(m, {}, 1) for m in mrks] if mrks else [_import_content(t, {}, 1)]
        return out
    raise FormatError("The file is not a supported XLIFF version (1.2, 2.0 or 2.1).")
