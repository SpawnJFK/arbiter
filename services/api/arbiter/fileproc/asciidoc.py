"""AsciiDoc handler (.adoc, .asciidoc), basic subset, merged by splicing like Markdown.

Translated: section titles, paragraphs, list items (*, -, ., 1.), description list
terms and definitions, admonition paragraphs (the NOTE: label stays), block titles
(.Title), table cells of |=== tables, and the text inside example, sidebar and quote
blocks.

Never translated: the document header attribute lines (:name: value), comments
(// and ////), listing, literal and passthrough blocks (----, ...., ++++), indented
literal paragraphs, block attribute lines ([source,python], [[anchor]]), directives
(include::, ifdef::, image:: blocks) and list continuation markers.

Inline markup becomes codes whose `original` is the literal AsciiDoc: *bold*, _italic_,
`monospace` (kept whole: code is not translated), #highlight#, ^super^, ~sub~,
attribute references {name}, macros such as link:url[text] or footnote:[text] (the
bracket text is translated, the target is a code), cross references <<id,text>>, bare
URLs and the hard line break " +".
"""

from __future__ import annotations

import re

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, InlineCode, TargetMap
from arbiter.fileproc.text import Span, decode_text, iter_lines, make_unit, renumber, splice

_HEADING = re.compile(r"^(={1,6}|#{1,6})([ \t]+)(\S.*?)[ \t]*$")
_ATTR_ENTRY = re.compile(r"^:!?[A-Za-z0-9_][\w-]*!?:(?:[ \t].*)?$")
_BLOCK_ATTR = re.compile(r"^\[.*\]\s*$")
_BLOCK_TITLE = re.compile(r"^\.([^ .\t].*)$")
_LIST = re.compile(r"^([ \t]*)(\*{1,5}|-|\.{1,5}|\d{1,9}\.)([ \t]+)(\[[ xX*]\][ \t]+)?")
_DLIST = re.compile(r"^([ \t]*)(.+?)(:{2,4}|;;)(?:([ \t]+)(.*))?$")
_ADMONITION = re.compile(r"^(NOTE|TIP|IMPORTANT|WARNING|CAUTION):[ \t]+")
_DIRECTIVE = re.compile(r"^(?:include|ifdef|ifndef|ifeval|endif|image|video|audio|toc)::")
_DELIMS_SKIP = {"----": "listing", "....": "literal", "++++": "pass", "////": "comment"}
_DELIMS_OPEN = {"====": "example", "****": "sidebar", "____": "quote", "--": "open"}
_TABLE = re.compile(r"^[|,!:]===\s*$")

_INLINE = re.compile(
    r"""
    (?P<pass>\+\+\+.*?\+\+\+|pass:[a-z,]*\[.*?\])
    |(?P<mono>`[^`\n]+`)
    |(?P<attr>\{[A-Za-z0-9_][\w-]*\})
    |(?P<xref><<[^<>,\n]+(?:,(?P<xtext>[^<>\n]+))?>>)
    |(?P<macro>\b(?:link|mailto|xref|footnote|image|kbd|btn|menu|anchor|icon|indexterm2?|https?|ftp|irc)
        :(?:[^\s\[\]]*)\[(?P<mtext>[^\]\n]*)\])
    |(?P<url>\b(?:https?|ftp)://[^\s\[\]<>]+)
    |(?P<hardbreak>[ \t]\+(?:\r\n|\n|\Z))
    """,
    re.VERBOSE | re.MULTILINE,
)
_TEXT_MACROS = (
    "link",
    "mailto",
    "xref",
    "footnote",
    "image",
    "anchor",
    "indexterm",
    "https",
    "http",
    "ftp",
    "irc",
)
_FORMAT = re.compile(
    r"(?P<u>\*\*|__|##)(?=\S)(?P<ub>.+?)(?<=\S)(?P=u)"
    r"|(?<![\w*_#])(?P<c>[*_#])(?=\S)(?P<cb>[^*_#\n]*?)(?<=\S)(?P=c)(?![\w*_#])"
    r"|(?P<s>[\^~])(?P<sb>[^\s^~]+)(?P=s)"
)
_FORMAT_NAMES = {
    "*": "bold",
    "**": "bold",
    "_": "italic",
    "__": "italic",
    "#": "highlight",
    "##": "highlight",
}


class _Inline:
    def __init__(self) -> None:
        self.n = 0

    def cid(self) -> str:
        self.n += 1
        return f"a{self.n}"

    def parse(self, s: str) -> Content:
        out: Content = []
        pos = 0
        for m in _INLINE.finditer(s):
            if m.start() > pos:
                out.extend(self.format(s[pos : m.start()]))
            kind = m.lastgroup if m.lastgroup not in ("xtext", "mtext") else None
            tok = m.group(0)
            if m.group("xref") is not None:
                if m.group("xtext"):
                    t0 = m.start("xtext") - m.start()
                    t1 = m.end("xtext") - m.start()
                    out.extend(self.pair(tok[:t0], tok[t0:t1], tok[t1:], "cross reference"))
                else:
                    out.append(InlineCode(self.cid(), "standalone", tok, "cross reference"))
            elif m.group("macro") is not None:
                name = tok.split(":", 1)[0]
                text = m.group("mtext") or ""
                t0 = m.start("mtext") - m.start()
                t1 = m.end("mtext") - m.start()
                if name.startswith(_TEXT_MACROS) and text.strip() and not name.startswith("kbd"):
                    out.extend(self.pair(tok[:t0], text, tok[t1:], name))
                else:
                    out.append(InlineCode(self.cid(), "standalone", tok, name))
            else:
                display = {"pass": "passthrough", "mono": "code", "attr": tok, "url": "url"}.get(
                    kind or "", ""
                )
                if m.group("hardbreak") is not None:
                    display = "line break"
                out.append(InlineCode(self.cid(), "standalone", tok, display))
            pos = m.end()
        if pos < len(s):
            out.extend(self.format(s[pos:]))
        return out

    def pair(self, open_: str, inner: str, close: str, display: str) -> Content:
        cid = self.cid()
        return [
            InlineCode(cid, "open", open_, display),
            *self.format(inner),
            InlineCode(cid, "close", close, display),
        ]

    def format(self, s: str) -> Content:
        out: Content = []
        pos = 0
        for m in _FORMAT.finditer(s):
            if m.start() > pos:
                out.append(s[pos : m.start()])
            mark = m.group("u") or m.group("c") or m.group("s")
            body = m.group("ub") if m.group("u") else m.group("cb") if m.group("c") else m.group("sb")
            display = _FORMAT_NAMES.get(mark, "superscript" if mark == "^" else "subscript")
            cid = self.cid()
            out.append(InlineCode(cid, "open", mark, display))
            out.extend(self.format(body))
            out.append(InlineCode(cid, "close", mark, display))
            pos = m.end()
        if pos < len(s):
            out.append(s[pos:])
        return out


def parse_inline(text: str) -> Content:
    merged: Content = []
    for r in _Inline().parse(text):
        if isinstance(r, str) and merged and isinstance(merged[-1], str):
            merged[-1] += r
        elif r != "":
            merged.append(r)
    return renumber(merged)


def _split_cells(body: str, offset: int) -> list[tuple[int, int]]:
    cells: list[tuple[int, int]] = []
    bounds = [i for i, ch in enumerate(body) if ch == "|" and (i == 0 or body[i - 1] != "\\")]
    if not bounds:
        return [(offset, offset + len(body))] if body.strip() else []
    edges = [*bounds, len(body)]
    for a, b in zip(edges, edges[1:], strict=False):
        seg = body[a + 1 : b]
        if not seg.strip():
            continue
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg) - len(seg.rstrip())
        cells.append((offset + a + 1 + lead, offset + b - trail))
    return cells


def _block_start(body: str) -> bool:
    s = body.strip()
    return bool(
        not s
        or _HEADING.match(body)
        or _BLOCK_ATTR.match(s)
        or _BLOCK_TITLE.match(body)
        or _LIST.match(body)
        or _DLIST.match(body)
        or _ATTR_ENTRY.match(body)
        or s in _DELIMS_SKIP
        or s in _DELIMS_OPEN
        or _TABLE.match(s)
        or s == "+"
        or s.startswith("//")
        or _DIRECTIVE.match(s)
    )


class AsciidocHandler:
    name = "asciidoc"
    extensions: tuple[str, ...] = ("adoc", "asciidoc", "asc")

    def _spans(self, text: str, lang: str) -> list[Span]:
        lines = iter_lines(text)
        spans: list[Span] = []

        def add(uid: str, start: int, end: int, context: str) -> None:
            if end <= start:
                return
            unit: ExtractedUnit | None = make_unit(uid, parse_inline(text[start:end]), lang, context=context)
            if unit is not None:
                spans.append(Span(unit, start, end))

        i, n = 0, len(lines)
        while i < n:
            off, body, _ = lines[i]
            s = body.strip()
            uid = f"L{i + 1}"
            if not s or s == "+" or _ATTR_ENTRY.match(body) or _BLOCK_ATTR.match(s) or _DIRECTIVE.match(s):
                i += 1
                continue
            if s in _DELIMS_SKIP:
                j = i + 1
                while j < n and lines[j][1].strip() != s:
                    j += 1
                i = j + 1
                continue
            if s.startswith("//"):
                i += 1
                continue
            if s in _DELIMS_OPEN:
                i += 1  # the delimiter itself; the content is walked normally
                continue
            if _TABLE.match(s):
                i += 1
                while i < n and not _TABLE.match(lines[i][1].strip()):
                    o, b, _ = lines[i]
                    for c, (a, e) in enumerate(_split_cells(b, o)):
                        add(f"L{i + 1}.c{c + 1}", a, e, "table")
                    i += 1
                i += 1
                continue
            m = _HEADING.match(body)
            if m:
                start = off + m.start(3)
                add(uid, start, start + len(m.group(3)), "heading")
                i += 1
                continue
            m = _BLOCK_TITLE.match(body)
            if m:
                add(uid, off + 1, off + len(body.rstrip()), "block title")
                i += 1
                continue
            if body[:1] in (" ", "\t") and not _LIST.match(body):
                while i < n and lines[i][1].strip():
                    i += 1  # literal paragraph
                continue
            prefix = 0
            context = "paragraph"
            lm = _LIST.match(body)
            dm = _DLIST.match(body) if not lm else None
            am = _ADMONITION.match(body)
            if lm:
                prefix = lm.end()
                context = "list item"
            elif dm and not dm.group(2).strip().startswith(("http", "link:")):
                add(f"{uid}.t", off + dm.start(2), off + dm.end(2), "term")
                if not dm.group(5):
                    i += 1
                    continue
                prefix = dm.start(5)
                context = "definition"
            elif am:
                prefix = am.end()
                context = am.group(1).lower()
            start = off + prefix
            end = off + len(body)
            i += 1
            nested = context in ("list item", "definition")
            while (
                i < n
                and not _block_start(lines[i][1])
                and (nested or not lines[i][1].startswith((" ", "\t")))
            ):
                end = lines[i][0] + len(lines[i][1])
                i += 1
            add(uid, start, end, context)
        return spans

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        return ExtractionResult(
            self.name, source_lang, [s.unit for s in self._spans(decoded.text, source_lang)]
        )

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        merged = splice(decoded.text, self._spans(decoded.text, "en"), targets, resegment=True)
        if merged == decoded.text:
            return original
        return decoded.encode(merged)
