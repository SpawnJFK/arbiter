"""Android res/values/strings.xml: <string>, <plurals>, <string-array>, translatable="false".

Values are stored unescaped (what the user sees): Android escapes (\\' \\" \\n \\t \\\\ \\@ \\?
\\uXXXX), XML entities and double-quoted runs are decoded on parse and re-applied on render.
Inline markup inside a value (<b>, <i>, <u>, <xliff:g id="...">) is kept as markup text,
so the placeholder layer can protect it as codes. The XML comment right before an element
becomes the key description.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape as xml_escape

from lxml import etree

from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError

XLIFF_NS = "urn:oasis:names:tc:xliff:document:1.2"
_MARKUP = re.compile(r"</?[A-Za-z][\w:.-]*(?:\s+[^<>]*?)?/?>")
_NS_DECL = re.compile(r'\s+xmlns(?::\w+)?="[^"]*"')


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)


def unescape_text(s: str) -> str:
    """Android string escapes of one text run (already XML-decoded)."""
    out: list[str] = []
    i = 0
    in_quotes = False
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2 : i + 6] or ""):
                out.append(chr(int(s[i + 2 : i + 6], 16)))
                i += 6
                continue
            out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            in_quotes = not in_quotes
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def escape_text(s: str, *, first: bool) -> str:
    out = (
        s.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    if first and out[:1] in ("@", "?"):
        out = "\\" + out
    return xml_escape(out)


def _inner(el: etree._Element) -> str:
    parts = [unescape_text(el.text or "")]
    for child in el:
        if isinstance(child, etree._Comment):
            parts.append(unescape_text(child.tail or ""))
            continue
        tail = child.tail
        child.tail = None
        markup = etree.tostring(child, encoding="unicode", with_tail=False)
        child.tail = tail
        markup = _NS_DECL.sub("", markup)
        # child text is Android-escaped too (e.g. <b>Don\'t</b>)
        parts.append(_unescape_markup(markup))
        parts.append(unescape_text(tail or ""))
    return "".join(parts)


def _unescape_markup(markup: str) -> str:
    out: list[str] = []
    pos = 0
    for m in _MARKUP.finditer(markup):
        out.append(_xml_unescape(unescape_text(markup[pos : m.start()])))
        out.append(m.group(0))
        pos = m.end()
    out.append(_xml_unescape(unescape_text(markup[pos:])))
    return "".join(out)


def _xml_unescape(s: str) -> str:
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def _qname(tag: object) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def parse(data: bytes, lang: str, base_lang: str) -> Doc:
    try:
        root = etree.fromstring(data, _parser())
    except etree.XMLSyntaxError as e:
        raise StringsFormatError(f"The Android strings file is not valid XML: {e.msg}") from None
    if _qname(root.tag) != "resources":
        raise StringsFormatError("An Android strings file must have a <resources> root.")
    doc = Doc(base_lang=base_lang, langs=[lang])
    comment = ""
    for el in root:
        if isinstance(el, etree._Comment):
            comment = (el.text or "").strip()
            continue
        tag = _qname(el.tag)
        name = el.get("name")
        if not name:
            comment = ""
            continue
        translatable = el.get("translatable", "true") != "false"
        row: KeyRow | None = None
        if tag == "string":
            row = KeyRow(key=name, values={lang: _inner(el)})
        elif tag == "plurals":
            forms = {
                i.get("quantity", ""): _inner(i) for i in el if _qname(i.tag) == "item" and i.get("quantity")
            }
            row = KeyRow(key=name, kind="plural", values={lang: forms})
        elif tag == "string-array":
            items = [_inner(i) for i in el if _qname(i.tag) == "item"]
            row = KeyRow(key=name, kind="array", values={lang: {str(i): v for i, v in enumerate(items)}})
        else:
            doc.warnings.append(f"<{tag} name={name!r}> skipped")
        if row is not None:
            row.translatable = translatable
            row.description = comment
            if el.get("formatted") == "false":
                row.meta["formatted"] = "false"
            doc.rows.append(row)
        comment = ""
    return doc


def render_value(value: str) -> str:
    """Escape for XML + Android while keeping inline markup tags as markup."""
    out: list[str] = []
    pos = 0
    first = True
    for m in _MARKUP.finditer(value):
        out.append(escape_text(value[pos : m.start()], first=first))
        out.append(m.group(0))
        first = False
        pos = m.end()
    out.append(escape_text(value[pos:], first=first and pos == 0))
    candidate = "".join(out)
    try:
        etree.fromstring(f'<r xmlns:xliff="{XLIFF_NS}">{candidate}</r>'.encode(), _parser())
    except etree.XMLSyntaxError:  # markup-looking text that is not well formed: escape it all
        candidate = escape_text(value, first=True)
    # Android collapses unquoted runs of whitespace: quote the value to keep them.
    if re.search(r"^\s|\s$|\s\s", value):
        candidate = f'"{candidate}"'
    return candidate


def _attr(s: str) -> str:
    return xml_escape(s, {'"': "&quot;"})


def render(doc: Doc, lang: str) -> bytes:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', f'<resources xmlns:xliff="{XLIFF_NS}">']
    for r in doc.lang_rows(lang):
        if not r.translatable and lang != doc.base_lang:
            continue
        if r.description:
            lines.append(f"    <!-- {r.description.replace('--', '- -')} -->")
        extra = ' translatable="false"' if not r.translatable else ""
        if r.meta.get("formatted") == "false":
            extra += ' formatted="false"'
        v = r.values[lang]
        name = _attr(r.key)
        if r.kind == "plural" and isinstance(v, dict):
            lines.append(f'    <plurals name="{name}"{extra}>')
            for q, text in v.items():
                if not q.startswith("="):
                    lines.append(f'        <item quantity="{_attr(q)}">{render_value(text)}</item>')
            lines.append("    </plurals>")
        elif r.kind == "array" and isinstance(v, dict):
            lines.append(f'    <string-array name="{name}"{extra}>')
            for k in sorted(v, key=lambda x: int(x) if x.isdigit() else 0):
                lines.append(f"        <item>{render_value(v[k])}</item>")
            lines.append("    </string-array>")
        else:
            lines.append(f'    <string name="{name}"{extra}>{render_value(str(v))}</string>')
    lines.append("</resources>")
    return ("\n".join(lines) + "\n").encode("utf-8")
