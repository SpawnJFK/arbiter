"""JSON handler for localization resource files.

Every string value is one unit (never sentence-segmented), identified by its JSON
pointer (RFC 6901). Keys are never translated.

Merge splices new string tokens into the original text at the exact offsets of the old
ones, so key order, indentation, spacing and number formatting are untouched by
construction, and an identity merge is byte identical for any input, not only for
json.dumps output.

Placeholders ({name}, {{name}}, %s, %1$s, ${name}) become standalone codes. ICU
MessageFormat plural/select arguments become nested paired codes: one pair around the
whole argument and one per branch, so the branch texts are translated while the
selectors and braces cannot be broken.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from arbiter.fileproc.base import Content, ExtractionResult, FormatError, InlineCode, TargetMap
from arbiter.fileproc.text import (
    PLACEHOLDER_RE,
    Span,
    decode_text,
    make_unit,
    render_markup,
    renumber,
    splice,
)

_STRING = re.compile(r'"(?:[^"\\\x00-\x1f]|\\.)*"', re.S)
_SCALAR = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null")
_WS = " \t\r\n"
_SKIP_VALUE = re.compile(r"^(?:https?://\S+|[\w.+-]+@[\w-]+\.[\w.-]+|#[0-9a-fA-F]{3,8}|[\w./-]+\.(?:png|jpe?g|gif|svg|webp|css|js|json|html?))$")
_ICU_HEAD = re.compile(r"\{\s*([A-Za-z0-9_]+)\s*,\s*(plural|selectordinal|select)\s*,")
_ICU_OFFSET = re.compile(r"\s*offset\s*:\s*\d+")
_ICU_SELECTOR = re.compile(r"(\s*)(=\d+|[A-Za-z0-9_-]+)(\s*)\{")


def pointer_escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


@dataclass
class _StrTok:
    pointer: str
    start: int
    end: int
    value: str


class _Scanner:
    """Locates every string value with its pointer. Input is already known to be valid JSON."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.found: list[_StrTok] = []

    def ws(self, i: int) -> int:
        while i < len(self.text) and self.text[i] in _WS:
            i += 1
        return i

    def string(self, i: int) -> tuple[str, int]:
        m = _STRING.match(self.text, i)
        if not m:
            raise FormatError("The JSON file is not valid JSON.")
        return json.loads(m.group(0)), m.end()

    def value(self, i: int, ptr: str) -> int:
        i = self.ws(i)
        ch = self.text[i]
        if ch == "{":
            i = self.ws(i + 1)
            if self.text[i] == "}":
                return i + 1
            while True:
                key, i = self.string(self.ws(i))
                i = self.ws(i)
                i = self.value(i + 1, f"{ptr}/{pointer_escape(key)}")  # skip ':'
                i = self.ws(i)
                if self.text[i] == ",":
                    i += 1
                    continue
                return i + 1  # '}'
        if ch == "[":
            i = self.ws(i + 1)
            if self.text[i] == "]":
                return i + 1
            idx = 0
            while True:
                i = self.value(i, f"{ptr}/{idx}")
                idx += 1
                i = self.ws(i)
                if self.text[i] == ",":
                    i += 1
                    continue
                return i + 1
        if ch == '"':
            value, end = self.string(i)
            self.found.append(_StrTok(ptr, i, end, value))
            return end
        m = _SCALAR.match(self.text, i)
        if not m:
            raise FormatError("The JSON file is not valid JSON.")
        return m.end()


class _Message:
    """Placeholder and ICU MessageFormat tokenizer producing content with codes."""

    def __init__(self, s: str) -> None:
        self.s = s
        self.n = 0

    def cid(self) -> str:
        self.n += 1
        return f"m{self.n}"

    def parse(self) -> Content:
        content, _ = self._seq(0, in_plural=False, nested=False)
        return content

    def _seq(self, i: int, in_plural: bool, nested: bool) -> tuple[Content, int]:
        s = self.s
        out: Content = []
        buf: list[str] = []

        def flush() -> None:
            if buf:
                out.append("".join(buf))
                buf.clear()

        while i < len(s):
            ch = s[i]
            if ch == "}" and nested:
                flush()
                return out, i
            if ch == "{" and not s.startswith("{{", i):
                icu = self._icu(i)
                if icu is not None:
                    flush()
                    out.extend(icu[0])
                    i = icu[1]
                    continue
            if ch == "#" and in_plural:
                flush()
                out.append(InlineCode(self.cid(), "standalone", "#", "#"))
                i += 1
                continue
            if ch in "{%$":
                m = PLACEHOLDER_RE.match(s, i)
                if m:
                    flush()
                    out.append(InlineCode(self.cid(), "standalone", m.group(0), m.group(0)))
                    i = m.end()
                    continue
            buf.append(ch)
            i += 1
        if nested:
            raise ValueError("unterminated ICU branch")
        flush()
        return out, i

    def _icu(self, i: int) -> tuple[Content, int] | None:
        m = _ICU_HEAD.match(self.s, i)
        if not m:
            return None
        try:
            return self._icu_body(m)
        except ValueError:
            return None

    def _icu_body(self, m: re.Match[str]) -> tuple[Content, int]:
        s = self.s
        kind = m.group(2)
        j = m.end()
        off = _ICU_OFFSET.match(s, j)
        if off:
            j = off.end()
        outer = self.cid()
        content: Content = [InlineCode(outer, "open", s[m.start() : j], kind)]
        branches = 0
        while True:
            sel = _ICU_SELECTOR.match(s, j)
            if not sel:
                break
            bid = self.cid()
            content.append(InlineCode(bid, "open", sel.group(0), sel.group(2)))
            inner, k = self._seq(sel.end(), in_plural=kind != "select", nested=True)
            content.extend(inner)
            content.append(InlineCode(bid, "close", "}", sel.group(2)))
            j = k + 1
            branches += 1
        tail = re.match(r"\s*\}", s[j:])
        if not branches or not tail:
            raise ValueError("not an ICU argument")
        content.append(InlineCode(outer, "close", tail.group(0), kind))
        return content, j + tail.end()


def message_content(value: str) -> Content:
    """Content for a resource string: text, placeholders and ICU structure as codes."""
    raw = _Message(value).parse()
    merged: Content = []
    for r in raw:
        if isinstance(r, str) and merged and isinstance(merged[-1], str):
            merged[-1] += r
        elif r != "":
            merged.append(r)
    return renumber(merged)


class JsonHandler:
    name = "json"
    extensions: tuple[str, ...] = ("json",)

    def _spans(self, text: str, lang: str) -> tuple[list[Span], bool]:
        try:
            json.loads(text)
        except (ValueError, RecursionError):
            raise FormatError("The JSON file is not valid JSON.") from None
        scanner = _Scanner(text)
        try:
            scanner.value(0, "")
        except RecursionError:
            raise FormatError("The JSON file is nested too deeply to process.") from None
        # Keep the file's own escaping style: \u escapes only if the source used them and no raw non-ASCII.
        ensure_ascii = "\\u" in text and all(ord(c) < 128 for c in text)
        spans: list[Span] = []
        for tok in scanner.found:
            if _SKIP_VALUE.match(tok.value.strip()):
                continue
            unit = make_unit(tok.pointer, message_content(tok.value), lang, segment=False,
                             context=f"key:{tok.pointer}")
            if unit is None:
                continue

            def render(content: Content, _ea: bool = ensure_ascii) -> str:
                return json.dumps(render_markup(content), ensure_ascii=_ea)

            spans.append(Span(unit, tok.start, tok.end, render))
        return spans, ensure_ascii

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        spans, _ = self._spans(decoded.text, source_lang)
        return ExtractionResult(self.name, source_lang, [s.unit for s in spans])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        spans, _ = self._spans(decoded.text, "en")
        merged = splice(decoded.text, spans, targets)
        if merged == decoded.text:
            return original
        json.loads(merged)  # never hand back invalid JSON
        return decoded.encode(merged)


