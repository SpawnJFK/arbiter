"""HTML handler built on lxml.html.

A unit is a maximal run of text and inline elements inside a block element; a nested
block element ends the unit and starts its own. Inline elements become paired codes
whose `original` is their exact start and end tag, void elements (br, img, ...) become
standalone codes. Translatable attributes (alt, title, placeholder, aria-label, meta
descriptions) are separate unsegmented units.

Merge re-parses the original, finds the same units, and rebuilds only the changed ones
by re-inserting the live inline elements in target order, so attributes, classes and
ids always come from the source file. When nothing changed the original bytes are
returned untouched; otherwise the document is serialized by lxml, which keeps the
doctype and the markup but may normalize entities and attribute quoting.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

import lxml.html
from lxml import etree

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, FormatError, InlineCode, TargetMap
from arbiter.fileproc.text import (
    DecodedText,
    check_target_ids,
    check_xml_text,
    decode_text,
    make_unit,
    resolve_target,
)

INLINE = {
    "b", "strong", "i", "em", "u", "a", "span", "code", "sup", "sub", "small", "mark", "abbr", "kbd",
    "s", "strike", "q", "cite", "dfn", "var", "samp", "font", "label", "time", "bdi", "bdo", "big", "tt",
    "ins", "del", "data",
}
VOID = {"br", "img", "input", "wbr"}
# Embedded content that sits inside running text but is not text itself: kept whole as a standalone code.
EMBEDDED = {"svg", "math", "iframe", "video", "audio", "object", "canvas", "embed", "picture"}
SKIP = {"script", "style", "pre", "textarea", "template"} | EMBEDDED
ATTRS = ("alt", "title", "placeholder", "aria-label")
META_NAMES = {"description", "keywords", "og:title", "og:description", "twitter:title", "twitter:description"}

_FULL_DOC = re.compile(rb"<\s*(!doctype|html|head|body)\b", re.I)
_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)


def _tag(el: etree._Element) -> str:
    return el.tag.lower() if isinstance(el.tag, str) else ""


def _no_translate(el: etree._Element) -> bool:
    if not isinstance(el.tag, str):
        return False
    if (el.get("translate") or "").lower() == "no":
        return True
    return "notranslate" in (el.get("class") or "").split()


def _has_block_descendant(el: etree._Element) -> bool:
    for d in el.iterdescendants():
        t = _tag(d)
        if t and t not in INLINE and t not in VOID:
            return True
    return False


def _is_inline(el: etree._Element) -> bool:
    """Whether a child continues the surrounding text flow instead of starting a block."""
    if not isinstance(el.tag, str):
        return True  # comments and processing instructions sit inside text
    t = _tag(el)
    if t in VOID or t in EMBEDDED:
        return True
    if t in INLINE:
        return not _has_block_descendant(el) or _no_translate(el)
    return False


def start_tag(el: etree._Element) -> str:
    attrs = "".join(
        f' {k}' if v is None else f' {k}="{html_lib.escape(v, quote=True)}"' for k, v in el.attrib.items()
    )
    return f"<{el.tag}{attrs}>"


def _markup(el: etree._Element) -> str:
    return lxml.html.tostring(el, encoding="unicode", with_tail=False)


@dataclass
class _Flow:
    """A unit's location: children[first:first+len(children)] of parent, text starting at `anchor`."""

    unit_id: str
    parent: etree._Element
    anchor: etree._Element | None  # None: starts at parent.text, else at anchor.tail
    children: list[etree._Element]
    content: Content
    codes: dict[str, tuple[str, etree._Element]] = field(default_factory=dict)
    unit: ExtractedUnit | None = None


@dataclass
class _AttrUnit:
    unit_id: str
    elem: etree._Element
    attr: str
    unit: ExtractedUnit


class _Builder:
    def __init__(self, lang: str, tree: etree._ElementTree) -> None:
        self.lang = lang
        self.tree = tree
        self.flows: list[_Flow] = []
        self.attrs: list[_AttrUnit] = []

    def path(self, el: etree._Element) -> str:
        return self.tree.getpath(el)

    def attributes(self, el: etree._Element) -> None:
        if not isinstance(el.tag, str):
            return
        tag = _tag(el)
        names: list[str] = [a for a in ATTRS if el.get(a)]
        if tag == "meta" and (el.get("name") or el.get("property") or "").lower() in META_NAMES and el.get("content"):
            names.append("content")
        if tag == "input" and (el.get("type") or "").lower() in ("submit", "button", "reset") and el.get("value"):
            names.append("value")
        for name in names:
            uid = f"{self.path(el)}@{name}"
            unit = make_unit(uid, [el.get(name) or ""], self.lang, segment=False, context=f"attribute:{name}")
            if unit is not None:
                self.attrs.append(_AttrUnit(uid, el, name, unit))

    def block(self, el: etree._Element) -> None:
        """Walk a block element: split its children into flows and nested blocks."""
        self.attributes(el)
        if _tag(el) in SKIP or _no_translate(el):
            return
        anchor: etree._Element | None = None
        run: list[etree._Element] = []
        flow_idx = 0

        def flush(next_anchor: etree._Element | None) -> None:
            nonlocal flow_idx, run, anchor
            text = el.text if anchor is None else anchor.tail
            if run or (text and text.strip()):
                flow = _Flow(f"{self.path(el)}#{flow_idx}", el, anchor, list(run), [])
                self._fill(flow, text)
                if flow.unit is not None:
                    self.flows.append(flow)
            flow_idx += 1
            run = []
            anchor = next_anchor

        for child in el:
            if _is_inline(child):
                run.append(child)
                self._attrs_inline(child)
            else:
                flush(child)
                self.block(child)
                anchor = child
        flush(None)

    def _attrs_inline(self, el: etree._Element) -> None:
        if not isinstance(el.tag, str) or _no_translate(el) or _tag(el) in SKIP:
            return
        self.attributes(el)
        for d in el.iterdescendants():
            if isinstance(d.tag, str) and not any(_no_translate(a) for a in d.iterancestors()):
                self.attributes(d)

    def _fill(self, flow: _Flow, text: str | None) -> None:
        counter = [0]
        content: Content = []

        def new_id() -> str:
            counter[0] += 1
            return str(counter[0])

        def inline(el: etree._Element) -> None:
            tag = _tag(el)
            if not isinstance(el.tag, str):
                cid = new_id()
                flow.codes[cid] = ("standalone", el)
                content.append(InlineCode(cid, "standalone", _markup(el), "comment"))
            elif tag in VOID or tag in SKIP or _no_translate(el):
                cid = new_id()
                flow.codes[cid] = ("standalone", el)
                content.append(InlineCode(cid, "standalone", _markup(el), f"<{tag}>"))
            else:
                cid = new_id()
                flow.codes[cid] = ("paired", el)
                content.append(InlineCode(cid, "open", start_tag(el), f"<{tag}>"))
                if el.text:
                    content.append(el.text)
                for child in el:
                    inline(child)
                    if child.tail:
                        content.append(child.tail)
                content.append(InlineCode(cid, "close", f"</{el.tag}>", f"</{tag}>"))

        if text:
            content.append(text)
        for child in flow.children:
            inline(child)
            if child.tail:
                content.append(child.tail)
        flow.content = content
        flow.unit = make_unit(flow.unit_id, content, self.lang, context=_tag(flow.parent) or "body")


def _rebuild(flow: _Flow, content: Content) -> None:
    parent = flow.parent
    if flow.anchor is None:
        parent.text = None
        idx = 0
    else:
        flow.anchor.tail = None
        idx = parent.index(flow.anchor) + 1
    for child in flow.children:
        parent.remove(child)

    stack: list[tuple[etree._Element, int, etree._Element | None]] = []
    cur, last = parent, flow.anchor

    def add_text(t: str) -> None:
        check_xml_text(t, flow.unit_id)
        if last is None:
            cur.text = (cur.text or "") + t
        else:
            last.tail = (last.tail or "") + t

    for item in content:
        if isinstance(item, str):
            add_text(item)
            continue
        kind, el = flow.codes[item.id]
        if item.kind == "standalone":
            el.tail = None
            cur.insert(idx, el)
            idx += 1
            last = el
        elif item.kind == "open":
            for child in list(el):
                el.remove(child)
            el.text = None
            el.tail = None
            cur.insert(idx, el)
            stack.append((cur, idx + 1, el))
            cur, idx, last = el, 0, None
        else:
            cur, idx, closed = stack.pop()
            last = closed


class HtmlHandler:
    name = "html"
    extensions: tuple[str, ...] = ("html", "htm")

    def __init__(self, rewrite_unchanged: bool = False) -> None:
        self.rewrite_unchanged = rewrite_unchanged

    def _decode(self, data: bytes) -> DecodedText:
        m = _CHARSET.search(data[:4096])
        declared = m.group(1).decode("ascii", "ignore") if m else None
        return decode_text(data, declared)

    def _parse(self, data: bytes) -> tuple[DecodedText, etree._Element, bool]:
        decoded = self._decode(data)
        full = bool(_FULL_DOC.search(data[:4096]))
        text = decoded.text
        try:
            if full:
                root = lxml.html.document_fromstring(text)
            else:
                root = lxml.html.fragment_fromstring(text, create_parent="div")
        except (etree.ParserError, ValueError):
            raise FormatError("The HTML file could not be read.") from None
        return decoded, root, full

    def _walk(self, root: etree._Element, lang: str) -> _Builder:
        b = _Builder(lang, root.getroottree())
        b.block(root)
        return b

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        _, root, _ = self._parse(data)
        b = self._walk(root, source_lang)
        units = [f.unit for f in b.flows if f.unit is not None] + [a.unit for a in b.attrs]
        return ExtractionResult(self.name, source_lang, units)

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded, root, full = self._parse(original)
        b = self._walk(root, "en")
        check_target_ids(targets, [f.unit_id for f in b.flows] + [a.unit_id for a in b.attrs])
        changed_any = False
        plans: list[tuple[_Flow, Content]] = []
        for flow in b.flows:
            tgt = targets.get(flow.unit_id)
            if tgt is None or flow.unit is None:
                continue
            content, changed = resolve_target(flow.unit, tgt, resegment=True)
            if changed or self.rewrite_unchanged:
                plans.append((flow, content))
        attr_plans: list[tuple[_AttrUnit, str]] = []
        for au in b.attrs:
            tgt = targets.get(au.unit_id)
            if tgt is None:
                continue
            content, changed = resolve_target(au.unit, tgt)
            if changed or self.rewrite_unchanged:
                value = "".join(r if isinstance(r, str) else r.original for r in content)
                check_xml_text(value, au.unit_id)
                attr_plans.append((au, value))
        # Rebuild innermost flows first is unnecessary: flows never overlap, and inline
        # elements moved by one flow are not part of another.
        for flow, content in plans:
            _rebuild(flow, content)
            changed_any = True
        for au, value in attr_plans:
            au.elem.set(au.attr, value)
            changed_any = True
        if not changed_any:
            return original
        if full:
            html_el = root if _tag(root) == "html" else None
            if html_el is not None and html_el.get("lang") is not None:
                html_el.set("lang", target_lang)
            doctype = root.getroottree().docinfo.doctype
            out = lxml.html.tostring(root, encoding="unicode", doctype=doctype or None, method="html")
            if decoded.text.endswith("\n") and not out.endswith("\n"):
                out += "\n"
        else:
            out = (root.text or "") + "".join(
                lxml.html.tostring(c, encoding="unicode", with_tail=True) for c in root
            )
        return decoded.encode(out)

