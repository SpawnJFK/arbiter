"""XML handlers: generic XML with rules, DITA, and Android string resources.

All three share one engine, a mixed-content flow walker in the style of the HTML
handler. A unit is a maximal run of text and inline elements inside a block element.
Inline elements become paired codes (their start and end tag), empty inline elements,
comments, processing instructions and entity references become standalone codes,
and elements marked "do not translate" that sit inside running text are kept whole as
one standalone code. Merge re-parses the original, rebuilds only changed flows by
re-inserting the live inline elements in target order, and returns the original bytes
untouched when nothing changed.

What is translatable is decided by rules, in increasing precedence:

1. the dialect's default rule set (generic, DITA or Android);
2. ITS 2.0 global rules embedded in the document (its:rules with translateRule,
   withinTextRule and locNoteRule);
3. the per-upload rules passed as handler options (see XmlRules.from_options);
4. ITS local attributes on the element (its:translate, its:locNote), and for DITA the
   DITA translate attribute.

Which elements are inline: explicit rules first; otherwise an element is inline when
its parent has running text of its own (mixed content), which is how XML vocabularies
without a schema mark up inline formatting.

Rule selectors are deliberately simple: `name` (local name, any namespace),
`prefix:name` (with a namespace map), `name@attr` / `@attr` for attributes, and any
selector containing "/" or "[" is taken as an XPath 1.0 expression.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from lxml import etree

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, FormatError, InlineCode, TargetMap
from arbiter.fileproc.text import (
    check_target_ids,
    check_xml_text,
    decode_text,
    make_unit,
    resolve_target,
)

ITS_NS = "http://www.w3.org/2005/11/its"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XLIFF12_NS = "urn:oasis:names:tc:xliff:document:1.2"

_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=True,
    remove_blank_text=False,
    strip_cdata=False,
    load_dtd=False,
)
_DECL = re.compile(r"\A\s*<\?xml[^>]*\?>[ \t\r\n]*")
_DECL_ENC = re.compile(rb"""^\s*<\?xml[^>]*encoding\s*=\s*["']([A-Za-z0-9_.:-]+)["']""")

Role = Literal["block", "inline", "protect", "nested", "skip"]


# --------------------------------------------------------------------------- parse and serialize


def parse_document(data: bytes, label: str) -> etree._ElementTree:
    """Parse untrusted XML: no entity expansion, no DTD loading, no network."""
    try:
        root = etree.fromstring(data, _PARSER)
    except (etree.XMLSyntaxError, ValueError):
        raise FormatError(f"The {label} file is not well-formed XML and cannot be processed.") from None
    if root is None:
        raise FormatError(f"The {label} file is empty.")
    return root.getroottree()


def serialize_document(tree: etree._ElementTree, original: bytes) -> bytes:
    """Serialize a changed tree, keeping the original XML declaration, encoding and BOM verbatim."""
    m = _DECL_ENC.match(original.lstrip(b"\xef\xbb\xbf"))
    decoded = decode_text(original, m.group(1).decode("ascii") if m else None)
    text = decoded.text
    body = etree.tostring(tree.getroot(), encoding="unicode", with_tail=False)
    bounds = _root_bounds(text)
    if bounds is None:  # pragma: no cover (parsed documents always have a root)
        decl = _DECL.match(text)
        return decoded.encode((decl.group(0) if decl else "") + etree.tostring(tree, encoding="unicode"))
    # Prolog (declaration, comments, doctype) and epilog are never changed: copy them verbatim.
    return decoded.encode(text[: bounds[0]] + body + text[bounds[1] :])


_PROLOG_ITEM = re.compile(r"\s+|<\?.*?\?>|<!--.*?-->", re.S)
_DOCTYPE = re.compile(r"<!DOCTYPE\b", re.I)


def _root_bounds(text: str) -> tuple[int, int] | None:
    """Character offsets where the root element starts and where its end tag finishes."""
    i = 0
    n = len(text)
    while i < n:
        m = _PROLOG_ITEM.match(text, i)
        if m:
            i = m.end()
            continue
        if _DOCTYPE.match(text, i):
            depth = 0
            j = i
            while j < n:
                ch = text[j]
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                elif ch == ">" and depth <= 0:
                    break
                elif ch in "\"'":
                    end = text.find(ch, j + 1)
                    j = end if end != -1 else n
                j += 1
            i = j + 1
            continue
        break
    if i >= n or text[i] != "<":
        return None
    end = n
    while True:
        stripped = text[:end].rstrip()
        if stripped.endswith("-->"):
            end = stripped.rfind("<!--")
        elif stripped.endswith("?>"):
            end = stripped.rfind("<?")
        else:
            end = len(stripped)
            break
        if end < 0:
            return None
    return i, end


def local_name(node: Any) -> str:
    tag = getattr(node, "tag", None)
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def namespace_of(node: Any) -> str:
    tag = getattr(node, "tag", None)
    if isinstance(tag, str) and tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def is_element(node: Any) -> bool:
    return isinstance(getattr(node, "tag", None), str)


def qualified(el: etree._Element) -> str:
    """The element name as written in the file (prefix:local)."""
    name = local_name(el)
    return f"{el.prefix}:{name}" if el.prefix else name


def start_tag_markup(el: etree._Element) -> str:
    attrs = []
    for k, v in el.attrib.items():
        q = etree.QName(k)
        prefix = ""
        if q.namespace:
            if q.namespace == XML_NS:
                prefix = "xml:"
            else:
                for p, uri in (el.nsmap or {}).items():
                    if uri == q.namespace and p:
                        prefix = f"{p}:"
                        break
        escaped = v.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        attrs.append(f' {prefix}{q.localname}="{escaped}"')
    return f"<{qualified(el)}{''.join(attrs)}>"


def node_markup(node: Any) -> str:
    """Readable markup for a code's `original`, without namespace declarations inherited from ancestors."""
    if is_element(node):
        node = copy.deepcopy(node)
        node.tail = None
        etree.cleanup_namespaces(node)
    return etree.tostring(node, encoding="unicode", with_tail=False)


def _has_running_text(el: etree._Element) -> bool:
    """Whether an element has text of its own between its children (mixed content)."""
    if el.text and el.text.strip():
        return True
    return any(child.tail and child.tail.strip() for child in el)


# --------------------------------------------------------------------------- rules


@dataclass
class XmlRules:
    """Per-upload rules. Every list holds selectors (see module docstring).

    exclude     elements whose content is not translated (inherited by descendants)
    include     elements translated even inside an excluded ancestor
    inline      elements that are part of the running text (paired codes)
    block       elements that always start their own unit
    protect     inline elements kept whole as one code (code samples, variables)
    nested      inline elements whose content is a separate unit (footnotes)
    attributes  translatable attributes ("alt", "img@alt", "//figure/@title")
    namespaces  prefix -> namespace URI for prefixed selectors
    """

    exclude: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    inline: list[str] = field(default_factory=list)
    block: list[str] = field(default_factory=list)
    protect: list[str] = field(default_factory=list)
    nested: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    namespaces: dict[str, str] = field(default_factory=dict)

    _KEYS = ("exclude", "include", "inline", "block", "protect", "nested", "attributes", "namespaces")

    @classmethod
    def from_options(cls, raw: Any) -> XmlRules:
        """Validate a rules object from upload options. Every problem is a client-safe FormatError."""
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise FormatError("The XML rules must be a JSON object.")
        unknown = sorted(set(raw) - set(cls._KEYS))
        if unknown:
            raise FormatError(
                f"The XML rules contain an unknown setting '{unknown[0]}'. "
                f"Allowed settings: {', '.join(cls._KEYS)}."
            )
        values: dict[str, Any] = {}
        for key in cls._KEYS:
            if key not in raw:
                continue
            value = raw[key]
            if key == "namespaces":
                if not isinstance(value, Mapping) or not all(
                    isinstance(k, str) and isinstance(v, str) and k and v for k, v in value.items()
                ):
                    raise FormatError(
                        "The XML rules setting 'namespaces' must map prefixes to namespace URIs."
                    )
                values[key] = dict(value)
                continue
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or not all(isinstance(s, str) and s.strip() for s in value):
                raise FormatError(f"The XML rules setting '{key}' must be a list of selectors.")
            if len(value) > 500:
                raise FormatError(f"The XML rules setting '{key}' has too many selectors (500 at most).")
            values[key] = [s.strip() for s in value]
        return cls(**values)

    def merged_over(self, base: XmlRules) -> XmlRules:
        return XmlRules(
            exclude=base.exclude + self.exclude,
            include=base.include + self.include,
            inline=base.inline + self.inline,
            block=base.block + self.block,
            protect=base.protect + self.protect,
            nested=base.nested + self.nested,
            attributes=base.attributes + self.attributes,
            namespaces={**base.namespaces, **self.namespaces},
        )


_NAME = re.compile(r"^(?:([A-Za-z_][\w.-]*):)?([A-Za-z_][\w.-]*|\*)$")
_ATTR_SEL = re.compile(
    r"^(?:(?:([A-Za-z_][\w.-]*):)?([A-Za-z_][\w.-]*|\*))?@(?:([A-Za-z_][\w.-]*):)?([A-Za-z_][\w.-]*|\*)$"
)


def _name_test(prefix: str | None, name: str, namespaces: Mapping[str, str]) -> str:
    if name == "*" and not prefix:
        return "*"
    if prefix:
        if prefix == "xml":
            return f"xml:{name}"
        if prefix not in namespaces:
            raise FormatError(
                f"The XML rules use the prefix '{prefix}' without declaring it in 'namespaces'."
            )
        return f"{prefix}:{name}"
    return f"*[local-name()='{name}']"


def _attr_test(prefix: str | None, name: str, namespaces: Mapping[str, str]) -> str:
    if name == "*" and not prefix:
        return "@*"
    if prefix:
        if prefix == "xml":
            return f"@xml:{name}"
        if prefix not in namespaces:
            raise FormatError(
                f"The XML rules use the prefix '{prefix}' without declaring it in 'namespaces'."
            )
        return f"@{prefix}:{name}"
    return f"@*[local-name()='{name}']"


def to_xpath(selector: str, namespaces: Mapping[str, str], *, attribute: bool = False) -> str:
    """Turn a simple selector into XPath; anything with / or [ is already XPath."""
    if "/" in selector or "[" in selector or "(" in selector:
        return selector
    if attribute or "@" in selector:
        m = _ATTR_SEL.match(selector)
        if m and "@" in selector:
            el_prefix, el_name, at_prefix, at_name = m.groups()
            el = _name_test(el_prefix, el_name, namespaces) if el_name else "*"
            return f"//{el}/{_attr_test(at_prefix, at_name, namespaces)}"
        m2 = _NAME.match(selector)
        if m2 and attribute:
            return f"//*/{_attr_test(m2.group(1), m2.group(2), namespaces)}"
        raise FormatError(f"The XML rules contain an invalid attribute selector: {selector}")
    m = _NAME.match(selector)
    if not m:
        raise FormatError(f"The XML rules contain an invalid selector: {selector}")
    return f"//{_name_test(m.group(1), m.group(2), namespaces)}"


def select(tree: etree._ElementTree, xpath: str, namespaces: Mapping[str, str], selector: str) -> list[Any]:
    ns = {k: v for k, v in namespaces.items() if k != "xml"}
    try:
        result = tree.xpath(xpath, namespaces=ns)
    except (etree.XPathError, TypeError, ValueError):
        raise FormatError(f"The XML rules contain an invalid selector: {selector}") from None
    if not isinstance(result, list):
        raise FormatError(f"The XML rules selector does not select elements or attributes: {selector}")
    return result


# --------------------------------------------------------------------------- flows


@dataclass
class _Code:
    kind: Literal["paired", "element", "literal"]
    node: Any = None
    raw: str = ""


@dataclass
class Flow:
    """A unit's location: `children` of `parent`, text starting at parent.text or anchor.tail."""

    unit_id: str
    parent: etree._Element
    anchor: Any
    children: list[Any]
    codes: dict[str, _Code] = field(default_factory=dict)
    unit: ExtractedUnit | None = None


@dataclass
class AttrUnit:
    unit_id: str
    elem: etree._Element
    attr: str
    unit: ExtractedUnit
    literals: dict[str, str] = field(default_factory=dict)


class FlowWalker:
    """Mixed-content walker. Dialects override the hooks; the defaults are generic XML."""

    segment = True

    def __init__(self, tree: etree._ElementTree, lang: str) -> None:
        self.tree = tree
        self.lang = lang
        self.flows: list[Flow] = []
        self.attrs: list[AttrUnit] = []

    # hooks ---------------------------------------------------------------

    def translate(self, el: etree._Element) -> bool:
        return True

    def role(self, node: Any, *, in_inline: bool, parent_mixed: bool) -> Role:
        if not is_element(node):
            return "protect"
        return "inline" if in_inline or parent_mixed else "block"

    def translatable_attributes(self, el: etree._Element) -> list[str]:
        return []

    def decode(self, text: str) -> Content:
        """Text run as content; dialects turn escapes and placeholders into literal codes."""
        return [text]

    def encode(self, text: str, at_start: bool) -> str:
        return text

    def unit_id(self, el: etree._Element, index: int) -> str:
        return f"{self.tree.getpath(el)}#{index}"

    def context(self, el: etree._Element) -> str:
        return local_name(el) or "body"

    def notes(self, el: etree._Element) -> list[str]:
        return []

    def max_length(self, el: etree._Element) -> int | None:
        return None

    def roots(self) -> Iterable[etree._Element]:
        return [self.tree.getroot()]

    def is_mixed(self, el: etree._Element) -> bool:
        return _has_running_text(el)

    # walking ---------------------------------------------------------------

    def run(self) -> FlowWalker:
        for root in self.roots():
            self.block(root)
        for el in self.tree.getroot().iter():
            if is_element(el):
                self._attributes(el)
        return self

    def block(self, el: etree._Element) -> None:
        if not self.translate(el):
            for child in el:
                if is_element(child):
                    self.block(child)
            return
        mixed = self.is_mixed(el)
        anchor: Any = None
        run: list[Any] = []
        index = 0

        def flush(next_anchor: Any) -> None:
            nonlocal index, run, anchor
            text = el.text if anchor is None else anchor.tail
            if run or (text and text.strip()):
                flow = Flow(self.unit_id(el, index), el, anchor, list(run))
                nested = self._fill(flow, text, el)
                if flow.unit is not None:
                    self.flows.append(flow)
                for sub in nested:
                    self.block(sub)
            index += 1
            run = []
            anchor = next_anchor

        for child in el:
            r = self.role(child, in_inline=False, parent_mixed=mixed)
            if r in ("inline", "protect", "nested"):
                run.append(child)
            else:
                flush(child)
                if r == "block":
                    self.block(child)
                elif r == "skip":
                    self._descend_skipped(child)
                anchor = child
        flush(None)

    def _descend_skipped(self, el: etree._Element) -> None:
        for child in el:
            if is_element(child):
                if self.translate(child) and self.role(child, in_inline=False, parent_mixed=False) == "block":
                    self.block(child)
                else:
                    self._descend_skipped(child)

    def _fill(self, flow: Flow, text: str | None, owner: etree._Element) -> list[etree._Element]:
        content: Content = []
        nested: list[etree._Element] = []
        counter = [0]

        def new_id() -> str:
            counter[0] += 1
            return str(counter[0])

        def add_text(t: str | None) -> None:
            if not t:
                return
            for run in self.decode(t):
                if isinstance(run, InlineCode):
                    cid = new_id()
                    flow.codes[cid] = _Code("literal", raw=run.original)
                    content.append(InlineCode(cid, "standalone", run.original, run.display))
                elif run:
                    content.append(run)

        def standalone(node: Any, display: str) -> None:
            cid = new_id()
            flow.codes[cid] = _Code("element", node)
            content.append(InlineCode(cid, "standalone", node_markup(node), display))

        def inline(node: Any) -> None:
            if not is_element(node):
                if isinstance(node, etree._Comment):
                    standalone(node, "comment")
                elif isinstance(node, etree._ProcessingInstruction):
                    standalone(node, "processing instruction")
                else:
                    standalone(node, f"&{getattr(node, 'name', '')};")
                return
            r = self.role(node, in_inline=True, parent_mixed=True)
            name = qualified(node)
            if r == "nested":
                standalone(node, f"<{name}/>")
                nested.append(node)
                return
            if r in ("protect", "skip") or not self.translate(node):
                standalone(node, f"<{name}/>")
                return
            if len(node) == 0 and not node.text:
                standalone(node, f"<{name}/>")
                return
            cid = new_id()
            flow.codes[cid] = _Code("paired", node)
            content.append(InlineCode(cid, "open", start_tag_markup(node), f"<{name}>"))
            add_text(node.text)
            for child in node:
                inline(child)
                add_text(child.tail)
            content.append(InlineCode(cid, "close", f"</{name}>", f"</{name}>"))

        add_text(text)
        for child in flow.children:
            inline(child)
            add_text(child.tail)
        flow.unit = make_unit(
            flow.unit_id,
            content,
            self.lang,
            segment=self.segment,
            context=self.context(owner),
            notes=self.notes(owner),
            max_length=self.max_length(owner),
        )
        return nested

    def _attributes(self, el: etree._Element) -> None:
        for name in self.translatable_attributes(el):
            value = el.get(name)
            if not value:
                continue
            label = name
            q = etree.QName(name)
            if q.namespace:
                label = q.localname
            uid = f"{self.tree.getpath(el)}@{label}"
            content: Content = []
            literals: dict[str, str] = {}
            n = 0
            for run in self.decode(value):
                if isinstance(run, InlineCode):
                    n += 1
                    literals[str(n)] = run.original
                    content.append(InlineCode(str(n), "standalone", run.original, run.display))
                else:
                    content.append(run)
            unit = make_unit(uid, content, self.lang, segment=False, context=f"attribute:{label}")
            if unit is not None:
                self.attrs.append(AttrUnit(uid, el, name, unit, literals))

    # merging ---------------------------------------------------------------

    def rebuild(self, flow: Flow, content: Content) -> None:
        parent = flow.parent
        if flow.anchor is None:
            parent.text = None
            idx = 0
        else:
            flow.anchor.tail = None
            idx = parent.index(flow.anchor) + 1
        for child in flow.children:
            parent.remove(child)
        stack: list[tuple[etree._Element, int, Any]] = []
        cur: etree._Element = parent
        last: Any = flow.anchor
        first = [True]

        def add_raw(t: str) -> None:
            nonlocal last
            check_xml_text(t, flow.unit_id)
            if last is None:
                cur.text = (cur.text or "") + t
            else:
                last.tail = (last.tail or "") + t

        for item in content:
            if isinstance(item, str):
                add_raw(self.encode(item, first[0]))
                first[0] = False
                continue
            first[0] = False
            code = flow.codes[item.id]
            if code.kind == "literal":
                add_raw(code.raw)
            elif item.kind == "standalone":
                code.node.tail = None
                cur.insert(idx, code.node)
                idx += 1
                last = code.node
            elif item.kind == "open":
                el = code.node
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

    def attr_value(self, au: AttrUnit, content: Content) -> str:
        out: list[str] = []
        first = True
        for run in content:
            if isinstance(run, InlineCode):
                out.append(au.literals.get(run.id, run.original))
            else:
                out.append(self.encode(run, first))
            first = False
        value = "".join(out)
        check_xml_text(value, au.unit_id)
        return value


def merge_flows(walker: FlowWalker, targets: TargetMap) -> bool:
    """Apply targets to a walked tree. Returns whether anything changed."""
    check_target_ids(targets, [f.unit_id for f in walker.flows] + [a.unit_id for a in walker.attrs])
    plans: list[tuple[Flow, Content]] = []
    for flow in walker.flows:
        tgt = targets.get(flow.unit_id)
        if tgt is None or flow.unit is None:
            continue
        content, changed = resolve_target(flow.unit, tgt, resegment=walker.segment)
        if changed:
            plans.append((flow, content))
    attr_plans: list[tuple[AttrUnit, str]] = []
    for au in walker.attrs:
        tgt = targets.get(au.unit_id)
        if tgt is None:
            continue
        content, changed = resolve_target(au.unit, tgt)
        if changed:
            attr_plans.append((au, walker.attr_value(au, content)))
    for flow, content in plans:
        walker.rebuild(flow, content)
    for au, value in attr_plans:
        au.elem.set(au.attr, value)
    return bool(plans or attr_plans)


# --------------------------------------------------------------------------- generic XML with rules


GENERIC_RULES = XmlRules(attributes=["alt", "title"])

DITA_INLINE = [
    "ph", "b", "i", "u", "sup", "sub", "tt", "line-through", "overline", "keyword", "term", "xref",
    "cite", "q", "uicontrol", "wintitle", "menucascade", "synph", "userinput", "systemoutput",
    "tm", "abbreviated-form", "text", "msgph", "shortcut", "image", "data", "boolean", "state",
    "glossterm", "parml", "lq",
]  # fmt: skip
DITA_RULES = XmlRules(
    exclude=["draft-comment", "required-cleanup", "codeblock", "msgblock", "foreign", "unknown"],
    inline=[s for s in DITA_INLINE if s not in ("parml", "lq")],
    protect=[
        "codeph",
        "apiname",
        "cmdname",
        "filepath",
        "varname",
        "option",
        "parmname",
        "msgnum",
        "coderef",
    ],
    nested=["fn", "indexterm", "index-see", "index-see-also"],
    block=["p", "li", "title", "shortdesc", "note", "dt", "dd", "entry", "stentry", "navtitle", "linktext"],
    attributes=["alt", "navtitle"],
)


class _RuleWalker(FlowWalker):
    """Generic XML: default rules, ITS rules in the document, upload rules, local ITS attributes."""

    dita = False

    def __init__(self, tree: etree._ElementTree, lang: str, rules: XmlRules) -> None:
        super().__init__(tree, lang)
        self.rules = rules
        self._translate: dict[etree._Element, bool] = {}
        self._role: dict[etree._Element, Role] = {}
        self._notes: dict[etree._Element, str] = {}
        self._attr_on: set[tuple[etree._Element, str]] = set()
        self._attr_off: set[tuple[etree._Element, str]] = set()
        self._prepare()

    def _elements(self, selector: str, *, attribute: bool = False) -> list[Any]:
        return select(
            self.tree,
            to_xpath(selector, self.rules.namespaces, attribute=attribute),
            self.rules.namespaces,
            selector,
        )

    def _prepare(self) -> None:
        explicit: dict[etree._Element, bool] = {}
        for sel in self.rules.exclude:
            for el in self._elements(sel):
                if is_element(el):
                    explicit[el] = False
        roles: dict[etree._Element, Role] = {}
        for key, role in (
            ("block", "block"),
            ("inline", "inline"),
            ("protect", "protect"),
            ("nested", "nested"),
        ):
            for sel in getattr(self.rules, key):
                for el in self._elements(sel):
                    if is_element(el):
                        roles[el] = role  # type: ignore[assignment]
        notes: dict[etree._Element, str] = {}

        # ITS global rules in the document come after the defaults.
        root = self.tree.getroot()
        its_rules = [r for r in root.iter(f"{{{ITS_NS}}}rules")]
        ns_map = dict(self.rules.namespaces)
        for rules_el in its_rules:
            for prefix, uri in (rules_el.nsmap or {}).items():
                if prefix and prefix not in ns_map:
                    ns_map[prefix] = uri
            for rule in rules_el:
                if not is_element(rule) or namespace_of(rule) != ITS_NS:
                    continue
                sel = rule.get("selector")
                if not sel:
                    continue
                try:
                    nodes = self.tree.xpath(sel, namespaces={k: v for k, v in ns_map.items() if k != "xml"})
                except (etree.XPathError, TypeError, ValueError):
                    raise FormatError(f"The file contains an invalid ITS rule selector: {sel}") from None
                if not isinstance(nodes, list):
                    continue
                kind = local_name(rule)
                for node in nodes:
                    if kind == "translateRule":
                        value = rule.get("translate") == "yes"
                        if is_element(node):
                            explicit[node] = value
                        elif hasattr(node, "getparent") and getattr(node, "attrname", None):
                            pair = (node.getparent(), node.attrname)
                            (self._attr_on if value else self._attr_off).add(pair)
                    elif kind == "withinTextRule" and is_element(node):
                        wt = rule.get("withinText")
                        roles[node] = {"yes": "inline", "nested": "nested"}.get(wt or "", "block")  # type: ignore[assignment]
                    elif kind == "locNoteRule" and is_element(node):
                        note_el = rule.find(f"{{{ITS_NS}}}locNote")
                        text = rule.get("locNote") or (note_el.text if note_el is not None else "")
                        if text and text.strip():
                            notes[node] = " ".join(text.split())

        # Upload rules: include beats exclude and the document's own rules.
        for sel in self.rules.include:
            for el in self._elements(sel):
                if is_element(el):
                    explicit[el] = True
        for sel in self.rules.attributes:
            for node in self._elements(sel, attribute=True):
                if not is_element(node) and getattr(node, "attrname", None):
                    self._attr_on.add((node.getparent(), node.attrname))

        def visit(el: etree._Element, inherited: bool, note: str) -> None:
            if namespace_of(el) == ITS_NS and local_name(el) in ("rules", "param"):
                self._translate[el] = False
                for d in el.iter():
                    self._translate[d] = False
                return
            value = explicit.get(el, inherited)
            local_attr = el.get(f"{{{ITS_NS}}}translate")
            if self.dita and local_attr is None:
                local_attr = el.get("translate")
            if local_attr in ("yes", "no"):
                value = local_attr == "yes"
            local_note = el.get(f"{{{ITS_NS}}}locNote")
            note = " ".join(local_note.split()) if local_note else notes.get(el, note)
            self._translate[el] = value
            if note:
                self._notes[el] = note
            for child in el:
                if is_element(child):
                    visit(child, value, note)

        visit(root, True, "")
        self._role = roles

    def translate(self, el: etree._Element) -> bool:
        return self._translate.get(el, True)

    def role(self, node: Any, *, in_inline: bool, parent_mixed: bool) -> Role:
        if not is_element(node):
            return "protect"
        explicit = self._role.get(node)
        if not self.translate(node):
            return "protect" if (in_inline or parent_mixed or explicit in ("inline", "protect")) else "skip"
        if explicit == "protect":
            return "protect" if (in_inline or parent_mixed) else "skip"
        if explicit == "nested":
            return "nested" if (in_inline or parent_mixed) else "block"
        if explicit == "block":
            return "block" if not in_inline else "inline"
        if explicit == "inline":
            return "inline"
        return "inline" if in_inline or parent_mixed else "block"

    def is_mixed(self, el: etree._Element) -> bool:
        if _has_running_text(el):
            return True
        return any(self._role.get(c) in ("inline", "protect", "nested") for c in el if is_element(c))

    def translatable_attributes(self, el: etree._Element) -> list[str]:
        if not self.translate(el):
            return []
        defaults = [] if self.dita else GENERIC_RULES.attributes
        names: list[str] = []
        for name in el.attrib:
            pair = (el, name)
            if pair in self._attr_off:
                continue
            if pair in self._attr_on or name in defaults:
                names.append(name)
        return names

    def notes(self, el: etree._Element) -> list[str]:
        note = self._notes.get(el)
        return [note] if note else []


class _DitaWalker(_RuleWalker):
    dita = True


# --------------------------------------------------------------------------- Android strings.xml

_ANDROID_TOKEN = re.compile(
    r"""
    (?P<unicode>\\u[0-9a-fA-F]{4})
    |(?P<newline>\\n)
    |(?P<tab>\\t)
    |(?P<escape>\\.)
    |(?P<printf>%(?:\d+\$)?[-+\#0,(]*\d*(?:\.\d+)?(?:[tT][A-Za-z]|[bBhHsScCdoxXeEfgGaAn%]))
    |(?P<html></?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>)
    |(?P<quote>")
    """,
    re.VERBOSE,
)


def android_decode(text: str) -> Content:
    out: Content = []
    buf: list[str] = []
    pos = 0

    def flush() -> None:
        if buf:
            out.append("".join(buf))
            buf.clear()

    for m in _ANDROID_TOKEN.finditer(text):
        buf.append(text[pos : m.start()])
        kind = m.lastgroup
        tok = m.group(0)
        if kind == "unicode":
            buf.append(chr(int(tok[2:], 16)))
        elif kind == "escape":
            buf.append(tok[1])
        else:
            flush()
            display = {"newline": "line break", "tab": "tab", "quote": '"'}.get(kind or "", tok)
            out.append(InlineCode("0", "standalone", tok, display))
        pos = m.end()
    buf.append(text[pos:])
    flush()
    return [_join_surrogates(r) if isinstance(r, str) else r for r in out]


def _join_surrogates(text: str) -> str:
    if not any("\ud800" <= c <= "\udfff" for c in text):
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def android_encode(text: str, at_start: bool) -> str:
    out = (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    if at_start and out[:1] in ("@", "?"):
        out = "\\" + out
    return out


class _AndroidWalker(FlowWalker):
    """res/values/strings.xml: string, string-array items and plurals items, one segment each."""

    segment = False

    def __init__(self, tree: etree._ElementTree, lang: str) -> None:
        super().__init__(tree, lang)
        self._ids: dict[etree._Element, str] = {}
        self._notes: dict[etree._Element, list[str]] = {}

    def roots(self) -> Iterable[etree._Element]:
        out: list[etree._Element] = []
        pending_note = ""
        for child in self.tree.getroot():
            if isinstance(child, etree._Comment):
                pending_note = " ".join((child.text or "").split())
                continue
            if not is_element(child):
                continue
            note, pending_note = pending_note, ""
            tag = local_name(child)
            name = child.get("name", "")
            if (
                not name
                or child.get("translatable") == "false"
                or tag not in ("string", "string-array", "plurals")
            ):
                continue
            if tag == "string":
                self._ids[child] = f"string:{name}"
                self._notes[child] = [note] if note else []
                out.append(child)
                continue
            index = 0
            for item in child:
                if not is_element(item) or local_name(item) != "item":
                    continue
                if tag == "plurals":
                    self._ids[item] = f"plurals:{name}[{item.get('quantity', index)}]"
                else:
                    self._ids[item] = f"string-array:{name}[{index}]"
                self._notes[item] = [note] if note else []
                out.append(item)
                index += 1
        return out

    def run(self) -> FlowWalker:
        for root in self.roots():
            self._single_flow(root)
        return self

    def _single_flow(self, el: etree._Element) -> None:
        flow = Flow(self._ids[el], el, None, list(el))
        self._fill(flow, el.text, el)
        if flow.unit is not None:
            self.flows.append(flow)

    def role(self, node: Any, *, in_inline: bool, parent_mixed: bool) -> Role:
        if not is_element(node):
            return "protect"
        if namespace_of(node) == XLIFF12_NS:
            return "protect"  # xliff:g marks text that must not be translated
        return "inline"

    def decode(self, text: str) -> Content:
        return android_decode(text)

    def encode(self, text: str, at_start: bool) -> str:
        return android_encode(text, at_start)

    def context(self, el: etree._Element) -> str:
        uid = self._ids.get(el, "")
        return f"key:{uid.split(':', 1)[1]}" if ":" in uid else "string"

    def notes(self, el: etree._Element) -> list[str]:
        notes = list(self._notes.get(el, []))
        if self._ids.get(el, "").startswith("plurals:"):
            notes.append(f"Plural form '{el.get('quantity', '')}'.")
        return notes


# --------------------------------------------------------------------------- handlers

DIALECTS = ("auto", "generic", "dita", "android")
_DITA_ROOTS = {
    "topic", "concept", "task", "reference", "glossentry", "glossgroup", "troubleshooting",
    "map", "bookmap", "subjectScheme", "learningContent", "learningOverview", "dita",
}  # fmt: skip


def _is_android(tree: etree._ElementTree) -> bool:
    root = tree.getroot()
    return root.tag == "resources" and any(
        is_element(c) and c.tag in ("string", "string-array", "plurals") for c in root
    )


def _is_dita(tree: etree._ElementTree) -> bool:
    doctype = tree.docinfo.doctype or ""
    root = tree.getroot()
    if "DITA" in doctype:
        return True
    return local_name(root) in _DITA_ROOTS and (
        any("ditaarch" in (uri or "") for uri in (root.nsmap or {}).values())
        or root.get("{http://dita.oasis-open.org/architecture/2005/}DITAArchVersion") is not None
    )


class XmlHandler:
    """Generic XML (.xml) with rules; detects Android string resources and DITA content."""

    name = "xml"
    extensions: tuple[str, ...] = ("xml",)
    default_dialect = "auto"

    def __init__(self, rules: XmlRules | None = None, dialect: str | None = None) -> None:
        self.rules = rules or XmlRules()
        self.dialect = dialect or self.default_dialect

    def configure(self, options: Mapping[str, Any]) -> XmlHandler:
        unknown = sorted(set(options) - {"rules", "dialect"})
        if unknown:
            raise FormatError(
                f"Unknown option '{unknown[0]}' for XML files. Allowed options: rules, dialect."
            )
        dialect = options.get("dialect", self.dialect)
        if dialect not in DIALECTS:
            raise FormatError(f"Unknown XML dialect '{dialect}'. Allowed: {', '.join(DIALECTS)}.")
        return type(self)(XmlRules.from_options(options.get("rules")), dialect)

    def _walker(self, tree: etree._ElementTree, lang: str) -> FlowWalker:
        dialect = self.dialect
        if dialect == "auto":
            dialect = "android" if _is_android(tree) else "dita" if _is_dita(tree) else "generic"
        if dialect == "android":
            return _AndroidWalker(tree, lang).run()
        if dialect == "dita":
            return _DitaWalker(tree, lang, self.rules.merged_over(DITA_RULES)).run()
        return _RuleWalker(tree, lang, self.rules).run()

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        tree = parse_document(data, self.name.upper())
        walker = self._walker(tree, source_lang)
        units = [f.unit for f in walker.flows if f.unit is not None] + [a.unit for a in walker.attrs]
        return ExtractionResult(self.name, source_lang, units)

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        tree = parse_document(original, self.name.upper())
        walker = self._walker(tree, "en")
        if not merge_flows(walker, targets):
            return original
        root = tree.getroot()
        if root.get(f"{{{XML_NS}}}lang") is not None:
            root.set(f"{{{XML_NS}}}lang", target_lang)
        return serialize_document(tree, original)


class DitaHandler(XmlHandler):
    """DITA topics and maps: the XML engine with the DITA default rule set."""

    name = "dita"
    extensions: tuple[str, ...] = ("dita", "ditamap")
    default_dialect = "dita"
