"""Position-aware helpers on tagged text (⟦n⟧ codes, ⟦⟦ ⟧⟧ escapes) for the workbench."""

from __future__ import annotations

import re
from dataclasses import dataclass

from arbiter.fileproc.base import LB, RB

_TOKEN_RE = re.compile(rf"{LB}(/?)([A-Za-z0-9_.-]+)(/?){RB}")


@dataclass(frozen=True)
class Piece:
    kind: str  # text | code
    raw: str  # exactly as in the tagged string
    start: int
    end: int
    value: str = ""  # text: unescaped text; code: id
    code_kind: str = ""  # open | close | standalone


def pieces(tagged: str) -> list[Piece]:
    """Split tagged text into text runs and code tokens with their [start, end) offsets.
    Lenient: an unparseable bracket stays text."""
    out: list[Piece] = []
    i, n = 0, len(tagged)
    buf_start = 0
    buf_raw: list[str] = []
    buf_val: list[str] = []

    def flush(end: int) -> None:
        nonlocal buf_raw, buf_val
        if buf_raw:
            out.append(Piece("text", "".join(buf_raw), buf_start, end, "".join(buf_val)))
            buf_raw, buf_val = [], []

    while i < n:
        ch = tagged[i]
        if ch in (LB, RB) and i + 1 < n and tagged[i + 1] == ch:
            if not buf_raw:
                buf_start = i
            buf_raw.append(ch + ch)
            buf_val.append(ch)
            i += 2
            continue
        if ch == LB:
            m = _TOKEN_RE.match(tagged, i)
            if m:
                flush(i)
                kind = "close" if m.group(1) else ("standalone" if m.group(3) else "open")
                out.append(Piece("code", m.group(0), i, m.end(), m.group(2), kind))
                i = m.end()
                continue
        if not buf_raw:
            buf_start = i
        buf_raw.append(ch)
        buf_val.append(ch)
        i += 1
    flush(n)
    return out


def escape(text: str) -> str:
    return text.replace(LB, LB + LB).replace(RB, RB + RB)


def is_boundary(tagged: str, offset: int) -> bool:
    """True when cutting at `offset` neither splits a code token nor an escape pair."""
    if offset <= 0 or offset >= len(tagged):
        return False
    for p in pieces(tagged):
        if p.start < offset < p.end:
            if p.kind == "code":
                return False
            # inside a text run: make sure we are not between the two halves of ⟦⟦ / ⟧⟧
            pos = p.start
            for chunk in _escaped_chunks(p.raw):
                if pos < offset < pos + len(chunk):
                    return False
                pos += len(chunk)
    return True


def _escaped_chunks(raw: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] in (LB, RB) and i + 1 < len(raw) and raw[i + 1] == raw[i]:
            out.append(raw[i : i + 2])
            i += 2
        else:
            out.append(raw[i])
            i += 1
    return out


def code_keys(tagged: str) -> list[tuple[str, str]]:
    return [(p.value, p.code_kind) for p in pieces(tagged) if p.kind == "code"]


def balanced(tagged: str) -> bool:
    """Every paired code opened in this text is also closed in it, properly nested."""
    stack: list[str] = []
    keys = code_keys(tagged)
    opens = {cid for cid, k in keys if k == "open"}
    closes = {cid for cid, k in keys if k == "close"}
    for cid, kind in keys:
        if kind == "open":
            stack.append(cid)
        elif kind == "close":
            if not stack or stack[-1] != cid:
                return False
            stack.pop()
    return not stack and opens == closes


def plain(tagged: str) -> str:
    return "".join(p.value for p in pieces(tagged) if p.kind == "text")


def replace_in_text(tagged: str, pattern: re.Pattern[str], repl: str, *, literal: bool) -> tuple[str, int]:
    """Replace inside text runs only, so codes can never be broken. Returns (new, count)."""
    out: list[str] = []
    total = 0
    for p in pieces(tagged):
        if p.kind == "code":
            out.append(p.raw)
            continue
        if literal:
            new, n = pattern.subn(lambda _m: repl, p.value)
        else:
            new, n = pattern.subn(repl, p.value)
        total += n
        out.append(escape(new) if n else p.raw)
    return "".join(out), total
