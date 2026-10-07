"""Helpers for the tagged-text form (⟦1⟧ ⟦/1⟧ ⟦2/⟧) shared by engines and quality.

Engines receive and must return tagged text. Quality checks need the plain text (for
numbers, spans, word counts) and the source as Content (for validate_tags). Parsing is
delegated to ``arbiter.fileproc.base`` so there is exactly one definition of the syntax.
"""

from __future__ import annotations

import re

from arbiter.fileproc.base import (
    LB,
    RB,
    Content,
    InlineCode,
    TaggedParseError,
    _split_tokens,  # noqa: PLC2701 - single source of truth for the token grammar
)

# Raw token regex used when a string cannot be parsed (malformed engine output).
_LOOSE_TOKEN_RE = re.compile(rf"{LB}/?[A-Za-z0-9_.-]+/?{RB}")


def pieces(tagged: str) -> list[tuple[str, str | tuple[str, str]]]:
    """("text", str) / ("code", (id, kind)) pieces. Raises TaggedParseError."""
    return _split_tokens(tagged)


def to_content(tagged: str) -> Content:
    """Parse tagged text into Content, synthesising InlineCodes from the tokens themselves.

    Used for the SOURCE side: the source is the reference, so every code it contains is
    by definition known.
    """
    content: Content = []
    for kind, value in _split_tokens(tagged):
        if kind == "text":
            assert isinstance(value, str)
            content.append(value)
        else:
            assert isinstance(value, tuple)
            cid, ckind = value
            content.append(InlineCode(cid, ckind))  # type: ignore[arg-type]
    return content


def plain(tagged: str) -> str:
    """Text with codes removed and escapes resolved. Never raises: malformed input falls
    back to a regex strip, because QA must still be able to look at broken engine output."""
    try:
        return "".join(v for k, v in _split_tokens(tagged) if k == "text" and isinstance(v, str))
    except TaggedParseError:
        return _LOOSE_TOKEN_RE.sub("", tagged).replace(LB + LB, LB).replace(RB + RB, RB)


def token_list(tagged: str) -> list[str]:
    """The code tokens in order, as written (e.g. ['⟦1⟧', '⟦/1⟧'])."""
    try:
        out = []
        for k, v in _split_tokens(tagged):
            if k == "code" and isinstance(v, tuple):
                cid, ckind = v
                out.append(InlineCode(cid, ckind).token())  # type: ignore[arg-type]
        return out
    except TaggedParseError:
        return _LOOSE_TOKEN_RE.findall(tagged)


def escape_text(text: str) -> str:
    """Escape literal brackets in plain text so it can be embedded in tagged text."""
    return text.replace(LB, LB + LB).replace(RB, RB + RB)


def is_balanced_tagged(tagged: str) -> bool:
    try:
        stack: list[str] = []
        for k, v in _split_tokens(tagged):
            if k != "code" or not isinstance(v, tuple):
                continue
            cid, ckind = v
            if ckind == "open":
                stack.append(cid)
            elif ckind == "close":
                if not stack or stack[-1] != cid:
                    return False
                stack.pop()
        return not stack
    except TaggedParseError:
        return False
