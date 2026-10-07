"""Markdown handler: block structure by lines, inline markup as codes, merge by splicing.

We do not render Markdown to HTML and back: that would normalize the author's syntax
(list markers, emphasis style, wrapping) and the identity round trip would not be byte
exact. Instead each translatable block is a character span of the source; markers that
start a block (#, -, 1., >) stay outside the span, and inline syntax inside it becomes
codes whose `original` is the literal Markdown. Merge writes text and code originals
back into the span and leaves every other byte alone.

Never translated: front matter, fenced and indented code blocks, link reference
definitions, HTML comments, table delimiter rows, link URLs and inline code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, InlineCode, TargetMap
from arbiter.fileproc.text import Span, decode_text, iter_lines, make_unit, renumber, splice

_FENCE = re.compile(r"^(\s*(?:>\s*)*)(`{3,}|~{3,})")
_ATX = re.compile(r"^( {0,3}#{1,6})([ \t]+)(.*?)([ \t]+#+[ \t]*)?[ \t]*$")
_ATX_EMPTY = re.compile(r"^ {0,3}#{1,6}[ \t]*$")
_QUOTE = re.compile(r"^((?:[ \t]*>[ \t]?)+)")
_LIST = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+)(\[[ xX]\][ \t]+)?")
_RULE = re.compile(r"^ {0,3}(?:[-*_=][ \t]*){3,}$|^ {0,3}=+[ \t]*$|^ {0,3}-+[ \t]*$")
_REFDEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*\S")
_TABLE_DELIM = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_AUTOLINK = re.compile(r"<(?:https?|ftp|mailto):[^<>\s]+>|<[^<>\s@]+@[^<>\s@]+>")
_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#@!$&'*+,;=%]*[A-Za-z0-9\-_~/#@$&*+=%]")
_TEMPLATE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")
_VOID_HTML = {"br", "img", "hr", "input", "wbr"}

# --------------------------------------------------------------------------- inline parsing


@dataclass
class _Tok:
    kind: str  # text | code | delim | html | node
    value: str = ""
    can_open: bool = False
    can_close: bool = False
    tag: str = ""
    node: Content | None = None
    partner: int = -1


class _Inline:
    """CommonMark-flavoured inline parser, deliberately forgiving.

    Every input character ends up in exactly one text run or code original, which is
    what guarantees the byte exact round trip. Delimiters that do not pair stay text.
    """

    def __init__(self) -> None:
        self.next_id = 0

    def code_id(self) -> str:
        self.next_id += 1
        return f"t{self.next_id}"

    def parse(self, s: str) -> Content:
        return self._build(self._tokens(s))

    def _find_close_bracket(self, s: str, i: int) -> int:
        depth = 0
        while i < len(s):
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                m = re.match(r"`+", s[i:])
                assert m
                n = len(m.group(0))
                end = s.find("`" * n, i + n)
                i = end + n if end != -1 else i + n
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    def _find_close_paren(self, s: str, i: int) -> int:
        depth = 0
        while i < len(s):
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    def _tokens(self, s: str) -> list[_Tok]:
        toks: list[_Tok] = []
        buf: list[str] = []
        i, n = 0, len(s)

        def flush() -> None:
            if buf:
                toks.append(_Tok("text", "".join(buf)))
                buf.clear()

        while i < n:
            ch = s[i]
            if ch == "\\" and i + 1 < n:
                buf.append(s[i : i + 2])
                i += 2
                continue
            if ch == "`":
                m = re.match(r"`+", s[i:])
                assert m
                run = m.group(0)
                end = s.find(run, i + len(run))
                while end != -1 and end + len(run) < n and s[end + len(run)] == "`":
                    end = s.find(run, end + len(run) + 1)
                if end != -1:
                    flush()
                    toks.append(_Tok("code", s[i : end + len(run)], tag="code"))
                    i = end + len(run)
                else:
                    buf.append(run)
                    i += len(run)
                continue
            if ch == "[" or (ch == "!" and i + 1 < n and s[i + 1] == "["):
                opener = "![" if ch == "!" else "["
                start = i + len(opener) - 1
                close = self._find_close_bracket(s, start)
                if close != -1 and close + 1 < n and s[close + 1] in "([":
                    if s[close + 1] == "(":
                        end = self._find_close_paren(s, close + 1)
                    else:
                        end = s.find("]", close + 2)
                    if end != -1:
                        flush()
                        inner = self._build(self._tokens(s[start + 1 : close]))
                        cid = self.code_id()
                        label = "image" if opener == "![" else "link"
                        node: Content = [InlineCode(cid, "open", opener, label), *inner,
                                         InlineCode(cid, "close", s[close : end + 1], label)]
                        toks.append(_Tok("node", node=node))
                        i = end + 1
                        continue
                buf.append(opener)
                i += len(opener)
                continue
            if ch == "<":
                for pat, kind in ((_HTML_COMMENT, "code"), (_AUTOLINK, "code"), (_HTML_TAG, "html")):
                    m = pat.match(s, i)
                    if m:
                        flush()
                        val = m.group(0)
                        tag = ""
                        if kind == "html":
                            tm = re.match(r"</?([A-Za-z][A-Za-z0-9-]*)", val)
                            tag = tm.group(1).lower() if tm else ""
                        toks.append(_Tok(kind, val, tag=tag or "html"))
                        i = m.end()
                        break
                else:
                    buf.append(ch)
                    i += 1
                continue
            if ch == "{":
                m = _TEMPLATE.match(s, i)
                if m:
                    flush()
                    toks.append(_Tok("code", m.group(0), tag="placeholder"))
                    i = m.end()
                    continue
            if ch == "h":
                m = _URL.match(s, i)
                if m and (i == 0 or not s[i - 1].isalnum()):
                    flush()
                    toks.append(_Tok("code", m.group(0), tag="url"))
                    i = m.end()
                    continue
            if ch in "*_~":
                m = re.match(r"\*+|_+|~+", s[i:])
                assert m
                run = m.group(0)
                if ch == "~" and len(run) != 2:
                    buf.append(run)
                    i += len(run)
                    continue
                d = run[:2] if len(run) >= 2 else run
                prev = s[i - 1] if i > 0 else " "
                nxt = s[i + len(d)] if i + len(d) < n else " "
                can_open = not nxt.isspace()
                can_close = not prev.isspace()
                if ch == "_":
                    can_open = can_open and not prev.isalnum()
                    can_close = can_close and not nxt.isalnum()
                flush()
                toks.append(_Tok("delim", d, can_open, can_close))
                i += len(d)
                continue
            buf.append(ch)
            i += 1
        flush()
        self._pair(toks)
        return toks

    @staticmethod
    def _pair(toks: list[_Tok]) -> None:
        """Pair emphasis delimiters and HTML tags with one stack so pairs always nest."""
        stack: list[int] = []
        for idx, t in enumerate(toks):
            if t.kind == "delim":
                matched = False
                if t.can_close:
                    for depth in range(len(stack) - 1, -1, -1):
                        o = toks[stack[depth]]
                        if o.kind == "delim" and o.value == t.value:
                            o.partner, t.partner = idx, stack[depth]
                            del stack[depth:]
                            matched = True
                            break
                if not matched and t.can_open:
                    stack.append(idx)
            elif t.kind == "html":
                if t.value.startswith("</"):
                    for depth in range(len(stack) - 1, -1, -1):
                        o = toks[stack[depth]]
                        if o.kind == "html" and o.tag == t.tag:
                            o.partner, t.partner = idx, stack[depth]
                            del stack[depth:]
                            break
                elif not t.value.endswith("/>") and t.tag not in _VOID_HTML:
                    stack.append(idx)

    def _build(self, toks: list[_Tok]) -> Content:
        out: Content = []
        ids: dict[int, str] = {}
        for idx, t in enumerate(toks):
            if t.kind == "text":
                out.append(t.value)
            elif t.kind == "node":
                assert t.node is not None
                out.extend(t.node)
            elif t.kind == "code":
                out.append(InlineCode(self.code_id(), "standalone", t.value, t.tag))
            elif t.partner == -1:
                if t.kind == "delim":
                    out.append(t.value)
                else:
                    out.append(InlineCode(self.code_id(), "standalone", t.value, f"<{t.tag}>"))
            elif t.partner > idx:
                cid = self.code_id()
                ids[idx] = cid
                disp = _DELIM_NAMES.get(t.value, f"<{t.tag}>")
                out.append(InlineCode(cid, "open", t.value, disp))
            else:
                cid = ids[t.partner]
                disp = _DELIM_NAMES.get(t.value, f"</{t.tag}>")
                out.append(InlineCode(cid, "close", t.value, disp))
        return out


_DELIM_NAMES = {"**": "bold", "__": "bold", "*": "italic", "_": "italic", "~~": "strikethrough"}


def parse_inline(text: str) -> Content:
    merged: Content = []
    for r in _Inline().parse(text):
        if isinstance(r, str) and merged and isinstance(merged[-1], str):
            merged[-1] += r
        elif r != "":
            merged.append(r)
    return renumber(merged)


# --------------------------------------------------------------------------- block scanning


def _block_start(body: str) -> bool:
    return bool(
        _FENCE.match(body) or _ATX.match(body) or _ATX_EMPTY.match(body) or _QUOTE.match(body)
        or _LIST.match(body) or _RULE.match(body) or _REFDEF.match(body)
        or body.lstrip().startswith("|") or body.lstrip().startswith("<!--")
    )


def _split_cells(body: str, offset: int) -> list[tuple[int, int]]:
    """Character spans of a table row's cells (whitespace trimmed), honouring escapes and code."""
    bounds: list[int] = []
    i, n = 0, len(body)
    in_code = ""
    while i < n:
        ch = body[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            m = re.match(r"`+", body[i:])
            assert m
            run = m.group(0)
            if not in_code:
                in_code = run
            elif in_code == run:
                in_code = ""
            i += len(run)
            continue
        if ch == "|" and not in_code:
            bounds.append(i)
        i += 1
    edges = [-1, *bounds, n]
    cells = []
    for a, b in zip(edges, edges[1:], strict=False):
        start, end = a + 1, b
        if start >= end and (a == -1 or b == n):
            continue
        seg = body[start:end]
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg) - len(seg.rstrip())
        if seg.strip():
            cells.append((offset + start + lead, offset + end - trail))
    return cells


class MarkdownHandler:
    name = "markdown"
    extensions: tuple[str, ...] = ("md", "markdown")

    def _spans(self, text: str, lang: str) -> list[Span]:
        lines = iter_lines(text)
        spans: list[Span] = []

        def add(uid: str, start: int, end: int, context: str) -> None:
            if end <= start:
                return
            unit: ExtractedUnit | None = make_unit(uid, parse_inline(text[start:end]), lang, context=context)
            if unit is not None:
                spans.append(Span(unit, start, end))

        i = 0
        n = len(lines)
        if n and lines[0][1].strip() in ("---", "+++"):
            marker = lines[0][1].strip()
            for j in range(1, n):
                if lines[j][1].strip() in (marker, "..."):
                    i = j + 1
                    break
        prev_blank = True
        in_list = False
        while i < n:
            off, body, _ = lines[i]
            if not body.strip():
                prev_blank = True
                i += 1
                continue
            fence = _FENCE.match(body)
            if fence:
                char, size = fence.group(2)[0], len(fence.group(2))
                close = re.compile(rf"^\s*(?:>\s*)*{re.escape(char)}{{{size},}}\s*$")
                i += 1
                while i < n and not close.match(lines[i][1]):
                    i += 1
                i += 1
                prev_blank = False
                continue
            if prev_blank and not in_list and re.match(r"^( {4}|\t)", body):
                while i < n and (not lines[i][1].strip() or re.match(r"^( {4}|\t)", lines[i][1])):
                    i += 1
                continue
            if body.lstrip().startswith("<!--"):
                while i < n and "-->" not in lines[i][1]:
                    i += 1
                i += 1
                continue
            if _REFDEF.match(body):
                i += 1
                prev_blank = False
                continue
            uid = f"L{i + 1}"
            if "|" in body and i + 1 < n and _TABLE_DELIM.match(lines[i + 1][1]) and "-" in lines[i + 1][1]:
                row = 0
                while i < n and lines[i][1].strip() and "|" in lines[i][1]:
                    o, b, _ = lines[i]
                    if not _TABLE_DELIM.match(b):
                        for c, (s, e) in enumerate(_split_cells(b, o)):
                            add(f"L{i + 1}.c{c + 1}", s, e, "table header" if row == 0 else "table")
                        row += 1
                    i += 1
                prev_blank = False
                in_list = False
                continue
            m = _ATX.match(body)
            if m:
                start = off + m.start(3)
                add(uid, start, start + len(m.group(3)), "heading")
                i += 1
                prev_blank = False
                in_list = False
                continue
            if _ATX_EMPTY.match(body) or _RULE.match(body):
                i += 1
                prev_blank = False
                continue
            prefix_len = 0
            context = "paragraph"
            q = _QUOTE.match(body)
            if q:
                prefix_len = q.end()
                context = "blockquote"
                inner = body[prefix_len:]
                hm = _ATX.match(inner)
                if hm:
                    add(uid, off + prefix_len + hm.start(3), off + prefix_len + hm.start(3) + len(hm.group(3)), "heading")
                    i += 1
                    prev_blank = False
                    continue
                lm = _LIST.match(inner)
                if lm:
                    prefix_len += lm.end()
                    context = "list item"
                add(uid, off + prefix_len, off + len(body), context)
                i += 1
                prev_blank = False
                continue
            lm = _LIST.match(body)
            if lm:
                prefix_len = lm.end()
                context = "list item"
                in_list = True
            elif prev_blank:
                in_list = in_list and body[:1] in (" ", "\t")
            start = off + prefix_len
            end = off + len(body)
            i += 1
            while i < n and lines[i][1].strip() and not _block_start(lines[i][1]) and not (
                "|" in lines[i][1] and i + 1 < n and _TABLE_DELIM.match(lines[i + 1][1])
            ):
                end = lines[i][0] + len(lines[i][1])
                i += 1
            add(uid, start, end, context)
            prev_blank = False
        return spans

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        return ExtractionResult(self.name, source_lang, [s.unit for s in self._spans(decoded.text, source_lang)])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        merged = splice(decoded.text, self._spans(decoded.text, "en"), targets, resegment=True)
        if merged == decoded.text:
            return original
        return decoded.encode(merged)
