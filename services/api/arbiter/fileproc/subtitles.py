"""Subtitle handlers: SubRip (.srt), WebVTT (.vtt) and Advanced SubStation Alpha (.ass/.ssa).

A cue (or ASS Dialogue line) is one unit and one segment: subtitles are already cut to
reading speed, and splitting or joining cues would change the timing. Timing lines, cue
numbers, identifiers, cue settings, NOTE/STYLE/REGION blocks, the ASS script header and
styles are never part of a unit, so merge (splicing the cue text back at its offsets)
cannot touch them and an identity merge is byte exact.

Line breaks inside a cue are standalone codes, so a translation keeps the line layout
(and cannot accidentally insert a blank line, which would end the cue). Formatting tags
(<i>, <b>, <u>, <font>, WebVTT <c.class>, <v Speaker>, ASS {\\i1}...{\\i0}) become paired
codes when they open and close inside the cue, standalone codes otherwise.

Option `max_chars_per_line` sets max_length on every cue to that many characters times
the cue's line count, with a note for the reviewer.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, FormatError, InlineCode, TargetMap
from arbiter.fileproc.text import Span, decode_text, iter_lines, make_unit, renumber, splice

_SRT_TIME = re.compile(r"^\s*(\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})")
_VTT_TIME = re.compile(r"^\s*((?:\d+:)?\d{2}:\d{2}\.\d{3})\s+-->\s+((?:\d+:)?\d{2}:\d{2}\.\d{3})")
_HTML_TAG = re.compile(r"</?([A-Za-z][A-Za-z0-9]*)(?:[.\s][^<>]*)?>")
_VTT_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*|\d{1,2}:\d{2}(?::\d{2})?\.\d{3})([.\s][^<>]*)?>")
_SRT_OVERRIDE = re.compile(r"\{\\[^{}]*\}")
_VTT_ENTITY = re.compile(r"&(?:amp|lt|gt|nbsp|lrm|rlm|quot|apos|#\d+|#x[0-9a-fA-F]+);")
_ASS_TOKEN = re.compile(r"\{[^{}]*\}|\\[Nnh]")
_ASS_TOGGLE = re.compile(r"^\{\\([ibus])([01])\}$")


@dataclass
class _Tok:
    kind: str  # text | tag | code
    value: str
    name: str = ""
    closing: bool = False
    display: str = ""


def _pair_tokens(toks: list[_Tok]) -> Content:
    """Tags that open and close inside the cue become paired codes; the rest standalone."""
    partner: dict[int, int] = {}
    stack: list[int] = []
    for idx, t in enumerate(toks):
        if t.kind != "tag":
            continue
        if t.closing:
            for depth in range(len(stack) - 1, -1, -1):
                if toks[stack[depth]].name == t.name:
                    partner[stack[depth]] = idx
                    partner[idx] = stack[depth]
                    del stack[depth:]
                    break
        else:
            stack.append(idx)
    out: Content = []
    ids: dict[int, str] = {}
    n = 0
    for idx, t in enumerate(toks):
        if t.kind == "text":
            if out and isinstance(out[-1], str):
                out[-1] += t.value
            else:
                out.append(t.value)
            continue
        if t.kind == "tag" and idx in partner:
            if partner[idx] > idx:
                n += 1
                ids[idx] = str(n)
                out.append(InlineCode(str(n), "open", t.value, t.display or f"<{t.name}>"))
            else:
                out.append(InlineCode(ids[partner[idx]], "close", t.value, t.display or f"</{t.name}>"))
            continue
        n += 1
        out.append(InlineCode(str(n), "standalone", t.value, t.display or t.value))
    return renumber(out)


def _max_length(per_line: int | None, lines: int) -> tuple[int | None, list[str]]:
    if not per_line:
        return None, []
    return per_line * max(1, lines), [f"At most {per_line} characters per line, {max(1, lines)} line(s)."]


@dataclass
class _Cue:
    uid: str
    start: int
    end: int
    lines: list[str]
    newline: str
    context: str


class _SubtitleBase:
    name = "subtitles"
    extensions: tuple[str, ...] = ()

    def __init__(self, max_chars_per_line: int | None = None) -> None:
        self.max_chars_per_line = max_chars_per_line

    def configure(self, options: Mapping[str, Any]) -> _SubtitleBase:
        unknown = sorted(set(options) - {"max_chars_per_line"})
        if unknown:
            raise FormatError(
                f"Unknown option '{unknown[0]}' for subtitle files. Allowed options: max_chars_per_line."
            )
        value = options.get("max_chars_per_line", self.max_chars_per_line)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 500
        ):
            raise FormatError("The option max_chars_per_line must be a whole number between 1 and 500.")
        return type(self)(value)

    # subclasses ---------------------------------------------------------------

    def _cues(self, text: str) -> list[_Cue]:
        raise NotImplementedError

    def _tokens(self, line: str) -> list[_Tok]:
        raise NotImplementedError

    def _encode(self, text: str) -> str:
        return text

    # shared ---------------------------------------------------------------

    def _content(self, cue: _Cue) -> Content:
        toks: list[_Tok] = []
        for i, line in enumerate(cue.lines):
            if i:
                toks.append(_Tok("code", cue.newline, display="line break"))
            toks.extend(self._tokens(line))
        return _pair_tokens(toks)

    def _render(self, cue: _Cue) -> Callable[[Content], str]:
        def render(content: Content) -> str:
            out: list[str] = []
            for run in content:
                if isinstance(run, InlineCode):
                    out.append(run.original)
                else:
                    # A raw line break in a translation would end the cue: keep it on the line.
                    flat = re.sub(r"\s*[\r\n]+\s*", " ", run)
                    out.append(self._encode(flat))
            return "".join(out)

        return render

    def _spans(self, text: str, lang: str) -> list[Span]:
        spans: list[Span] = []
        for cue in self._cues(text):
            max_len, notes = _max_length(self.max_chars_per_line, len(cue.lines))
            unit: ExtractedUnit | None = make_unit(
                cue.uid,
                self._content(cue),
                lang,
                segment=False,
                context=cue.context,
                notes=notes,
                max_length=max_len,
            )
            if unit is not None:
                spans.append(Span(unit, cue.start, cue.end, self._render(cue)))
        return spans

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        spans = self._spans(decoded.text, source_lang)
        return ExtractionResult(self.name, source_lang, [s.unit for s in spans])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        merged = splice(decoded.text, self._spans(decoded.text, "en"), targets)
        if merged == decoded.text:
            return original
        return decoded.encode(merged)


def _text_block(lines: list[tuple[int, str, str]], i: int) -> int:
    """Index of the first blank line (or end) from i."""
    while i < len(lines) and lines[i][1].strip():
        i += 1
    return i


class SrtHandler(_SubtitleBase):
    name = "srt"
    extensions: tuple[str, ...] = ("srt",)

    def _cues(self, text: str) -> list[_Cue]:
        lines = iter_lines(text)
        cues: list[_Cue] = []
        i = 0
        n = 0
        while i < len(lines):
            if not lines[i][1].strip():
                i += 1
                continue
            j = i
            if not _SRT_TIME.match(lines[j][1]) and j + 1 < len(lines) and _SRT_TIME.match(lines[j + 1][1]):
                j += 1  # cue number
            m = _SRT_TIME.match(lines[j][1])
            if not m:
                raise FormatError(
                    f"The SRT file could not be read: line {i + 1} should be a cue number or a timing line."
                )
            first = j + 1
            last = _text_block(lines, first)
            n += 1
            if last > first:
                body = lines[first:last]
                start = body[0][0]
                end = body[-1][0] + len(body[-1][1])
                cues.append(
                    _Cue(
                        f"cue{n}",
                        start,
                        end,
                        [b[1] for b in body],
                        body[0][2] or "\n",
                        f"subtitle {m.group(1)} --> {m.group(2)}",
                    )
                )
            i = last
        return cues

    def _tokens(self, line: str) -> list[_Tok]:
        toks: list[_Tok] = []
        pos = 0
        pattern = re.compile(f"{_HTML_TAG.pattern}|{_SRT_OVERRIDE.pattern}")
        for m in pattern.finditer(line):
            if m.start() > pos:
                toks.append(_Tok("text", line[pos : m.start()]))
            tok = m.group(0)
            if tok.startswith("{"):
                toks.append(_Tok("code", tok, display="position"))
            else:
                name = (m.group(1) or "").lower()
                toks.append(_Tok("tag", tok, name, tok.startswith("</")))
            pos = m.end()
        if pos < len(line):
            toks.append(_Tok("text", line[pos:]))
        return toks


class VttHandler(_SubtitleBase):
    name = "vtt"
    extensions: tuple[str, ...] = ("vtt",)

    def _cues(self, text: str) -> list[_Cue]:
        lines = iter_lines(text)
        if not lines or not lines[0][1].lstrip("﻿").startswith("WEBVTT"):
            raise FormatError("The WebVTT file must start with the line WEBVTT.")
        cues: list[_Cue] = []
        i = _text_block(lines, 0)  # header block
        n = 0
        while i < len(lines):
            if not lines[i][1].strip():
                i += 1
                continue
            head = lines[i][1].strip()
            if head.startswith(("NOTE", "STYLE", "REGION")) and not _VTT_TIME.match(lines[i][1]):
                i = _text_block(lines, i)
                continue
            j = i
            if not _VTT_TIME.match(lines[j][1]) and j + 1 < len(lines) and _VTT_TIME.match(lines[j + 1][1]):
                j += 1  # cue identifier
            m = _VTT_TIME.match(lines[j][1])
            if not m:
                raise FormatError(f"The WebVTT file could not be read: line {i + 1} should be a timing line.")
            first = j + 1
            last = _text_block(lines, first)
            n += 1
            if last > first:
                body = lines[first:last]
                start = body[0][0]
                end = body[-1][0] + len(body[-1][1])
                cues.append(
                    _Cue(
                        f"cue{n}",
                        start,
                        end,
                        [b[1] for b in body],
                        body[0][2] or "\n",
                        f"subtitle {m.group(1)} --> {m.group(2)}",
                    )
                )
            i = last
        return cues

    def _tokens(self, line: str) -> list[_Tok]:
        toks: list[_Tok] = []
        pos = 0
        pattern = re.compile(f"{_VTT_TAG.pattern}|{_VTT_ENTITY.pattern}")
        for m in pattern.finditer(line):
            if m.start() > pos:
                toks.append(_Tok("text", line[pos : m.start()]))
            tok = m.group(0)
            if tok.startswith("&"):
                toks.append(_Tok("text", html.unescape(tok)))
            elif m.group(2) and m.group(2)[0].isdigit():
                toks.append(_Tok("code", tok, display="timestamp"))
            else:
                name = (m.group(2) or "").lower()
                display = f"<{name}>"
                if name == "v":
                    # <v.class Speaker>: classes come first, the speaker after the first space.
                    rest = (m.group(3) or "").split(None, 1)
                    speaker = rest[-1] if rest and (len(rest) > 1 or not rest[0].startswith(".")) else ""
                    if speaker.strip():
                        display = f"speaker:{speaker.strip()}"
                toks.append(_Tok("tag", tok, name, m.group(1) == "/", display if m.group(1) != "/" else ""))
            pos = m.end()
        if pos < len(line):
            toks.append(_Tok("text", line[pos:]))
        return toks

    def _encode(self, text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class AssHandler(_SubtitleBase):
    """ASS/SSA: Dialogue lines of the [Events] section; the Text field is the cue."""

    name = "ass"
    extensions: tuple[str, ...] = ("ass", "ssa")

    def _cues(self, text: str) -> list[_Cue]:
        cues: list[_Cue] = []
        section = ""
        fields: list[str] = []
        n = 0
        for off, body, _ending in iter_lines(text):
            stripped = body.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped.lower()
                continue
            if section != "[events]":
                continue
            key, sep, rest = body.partition(":")
            if not sep:
                continue
            key = key.strip()
            if key == "Format":
                fields = [f.strip().lower() for f in rest.split(",")]
                continue
            if key != "Dialogue":
                continue
            if "text" not in fields or fields[-1] != "text":
                raise FormatError("The subtitle file has no Format line with Text as the last field.")
            n += 1
            lead = len(body) - len(body.lstrip()) + len(key) + 1
            values_start = off + lead
            parts = body[lead:].split(",", len(fields) - 1)
            if len(parts) < len(fields):
                raise FormatError(f"Dialogue line {n} of the subtitle file has too few fields.")
            text_start = values_start + len(",".join(parts[:-1])) + 1
            payload = parts[-1]
            info = dict(zip(fields, parts, strict=False))
            context = f"subtitle {info.get('start', '').strip()} --> {info.get('end', '').strip()}"
            if info.get("style", "").strip():
                context += f", style {info['style'].strip()}"
            if info.get("name", "").strip():
                context += f", speaker {info['name'].strip()}"
            cues.append(_Cue(f"dlg{n}", text_start, text_start + len(payload), [payload], "\\N", context))
        return cues

    def _content(self, cue: _Cue) -> Content:
        line = cue.lines[0]
        toks: list[_Tok] = []
        pos = 0
        for m in _ASS_TOKEN.finditer(line):
            if m.start() > pos:
                toks.append(_Tok("text", line[pos : m.start()]))
            tok = m.group(0)
            toggle = _ASS_TOGGLE.match(tok)
            if toggle:
                names = {"i": "italic", "b": "bold", "u": "underline", "s": "strikethrough"}
                toks.append(_Tok("tag", tok, toggle.group(1), toggle.group(2) == "0", names[toggle.group(1)]))
            elif tok in ("\\N", "\\n"):
                toks.append(_Tok("code", tok, display="line break"))
            elif tok == "\\h":
                toks.append(_Tok("code", tok, display="hard space"))
            else:
                toks.append(_Tok("code", tok, display="override"))
            pos = m.end()
        if pos < len(line):
            toks.append(_Tok("text", line[pos:]))
        return _pair_tokens(toks)

    def _spans(self, text: str, lang: str) -> list[Span]:
        spans: list[Span] = []
        for cue in self._cues(text):
            content = self._content(cue)
            lines = 1 + sum(1 for r in content if isinstance(r, InlineCode) and r.display == "line break")
            max_len, notes = _max_length(self.max_chars_per_line, lines)
            unit = make_unit(
                cue.uid, content, lang, segment=False, context=cue.context, notes=notes, max_length=max_len
            )
            if unit is not None:
                spans.append(Span(unit, cue.start, cue.end, self._render(cue)))
        return spans

    def _encode(self, text: str) -> str:
        return text.replace("{", "(").replace("}", ")")
