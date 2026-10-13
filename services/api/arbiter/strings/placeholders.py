"""Placeholder protection for software strings (R-STR-PH-*).

Software strings carry runtime placeholders that crash or misrender the app when an engine
or a translator changes them. Before a value goes to the TM or an engine it is converted to
the platform's tagged text (see arbiter.fileproc.base): every placeholder becomes a
standalone code ``⟦n/⟧`` and the original text of code n is kept beside it. The engine sees
codes it must keep; hard QA (tag_missing, tag_unknown, ...) blocks a target that drops or
invents one; ``restore()`` puts the original placeholder text back.

Recognised (R-STR-PH-01):
    ICU / FormatJS / next-intl   {name}  {n, number}  {d, date, short}  and the complex
                                 arguments {count, plural, one {...} other {...}},
                                 select and selectordinal (selectors and braces become codes,
                                 branch texts stay translatable)
    printf / Android / iOS       %s %d %1$s %2$d %.2f %lld %@ %1$@ %%
    Rails / Ruby i18n            %{name}
    Mustache / i18next / Vue     {{name}}  {{ name }}
    template literals            ${name}
    inline markup                <b> </b> <xliff:g id="x"> <br/> (HTML or XML tags in values)

``#`` inside an ICU plural branch is left as text on purpose: a translation may drop it in
the "one" branch ("one {one file}") and that is correct.

Style "none" in project settings turns protection off (strings are plain text).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from arbiter.engines import tags
from arbiter.fileproc.base import LB, RB, TaggedParseError

PLACEHOLDER_RE = re.compile(
    r"""
    (?P<rails>%\{[A-Za-z_][\w.-]*\})
    |(?P<mustache>\{\{-?\s*[^{}]+?\s*\}\})
    |(?P<printf>%(?:\d+\$)?[-+0\#]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|q|z|j|t)?[@diouxXeEfFgGaAcsSp%])
    |(?P<dollar>\$\{[^{}]+\})
    |(?P<icu>\{\s*[A-Za-z0-9_]+\s*(?:,\s*(?:number|date|time|spellout|ordinal|duration)\s*(?:,\s*[^{}]*)?)?\})
    |(?P<markup></?[A-Za-z][\w:.-]*(?:\s+[^<>]*?)?/?>)
    """,
    re.VERBOSE,
)
_ICU_COMPLEX = re.compile(r"\{\s*([A-Za-z0-9_]+)\s*,\s*(plural|selectordinal|select)\s*,")
_ICU_OFFSET = re.compile(r"\s*offset\s*:\s*\d+")
_ICU_SELECTOR = re.compile(r"\s*(=\d+|[A-Za-z0-9_-]+)\s*\{")

STYLES = ("auto", "icu", "printf", "rails", "mustache", "none")


class IcuError(ValueError):
    pass


@dataclass
class Protected:
    """A value in tagged-text form plus the original text of every code (index = id - 1)."""

    tagged: str
    codes: list[str] = field(default_factory=list)

    @property
    def placeholders(self) -> list[str]:
        return list(self.codes)


# ------------------------------------------------------------------ ICU complex arguments


def _match_brace(s: str, i: int) -> int:
    """Index of the brace closing the one at s[i] (ICU apostrophe quoting honoured)."""
    depth = 0
    n = len(s)
    j = i
    while j < n:
        ch = s[j]
        if ch == "'" and j + 1 < n and s[j + 1] in "{}#":
            k = s.find("'", j + 1)
            j = n if k < 0 else k + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise IcuError("unbalanced braces in ICU message")


@dataclass
class IcuComplex:
    start: int
    end: int  # exclusive
    arg: str
    kind: str  # plural | select | selectordinal
    head: str  # "{count, plural, offset:1 " (up to the first selector)
    branches: list[tuple[str, str, str]]  # (prefix incl. selector and "{", body, closing "}")
    tail: str  # whitespace + final "}"


def parse_complex(s: str, i: int) -> IcuComplex | None:
    m = _ICU_COMPLEX.match(s, i)
    if not m:
        return None
    end = _match_brace(s, i)
    pos = m.end()
    off = _ICU_OFFSET.match(s, pos)
    if off:
        pos = off.end()
    head = s[i:pos]
    branches: list[tuple[str, str, str]] = []
    while True:
        sm = _ICU_SELECTOR.match(s, pos)
        if not sm or sm.end() > end:
            break
        open_at = sm.end() - 1
        close_at = _match_brace(s, open_at)
        branches.append((s[pos : open_at + 1], s[open_at + 1 : close_at], "}"))
        pos = close_at + 1
    if not branches or s[pos:end].strip():
        raise IcuError(f"invalid {m.group(2)} argument {m.group(1)!r}")
    return IcuComplex(i, end + 1, m.group(1), m.group(2), head, branches, s[pos : end + 1])


def selector_of(prefix: str) -> str:
    m = _ICU_SELECTOR.search(prefix)
    return m.group(1) if m else ""


def whole_plural(value: str) -> IcuComplex | None:
    """The value IS one ICU plural/select argument (nothing around it): {n, plural, ...}."""
    v = value.strip()
    if not v.startswith("{"):
        return None
    try:
        c = parse_complex(v, 0)
    except IcuError:
        return None
    if c is None or c.end != len(v) or c.kind not in ("plural", "selectordinal"):
        return None
    return c


def build_plural(arg: str, forms: dict[str, str], kind: str = "plural") -> str:
    """{arg, plural, one {...} other {...}} from forms (inverse of whole_plural)."""
    from arbiter.strings.plurals import sort_forms

    body = " ".join(f"{k} {{{v}}}" for k, v in sort_forms(forms).items())
    return f"{{{arg}, {kind}, {body}}}"


def icu_skeleton(value: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """(arg, kind, sorted selectors) of every complex argument, for structure checks."""
    out: list[tuple[str, str, tuple[str, ...]]] = []
    i = 0
    while True:
        m = _ICU_COMPLEX.search(value, i)
        if not m:
            return out
        c = parse_complex(value, m.start())
        assert c is not None
        out.append((c.arg, c.kind, tuple(sorted(selector_of(p) for p, _, _ in c.branches))))
        for _, body, _ in c.branches:
            out.extend(icu_skeleton(body))
        i = c.end


# ------------------------------------------------------------------ protect / restore


def _esc(text: str) -> str:
    return text.replace(LB, LB + LB).replace(RB, RB + RB)


def protect(value: str, style: str = "auto") -> Protected:
    """value -> tagged text with one standalone code per placeholder (R-STR-PH-02)."""
    if style == "none":
        return Protected(_esc(value), [])
    codes: list[str] = []
    out: list[str] = []

    def code(original: str) -> None:
        codes.append(original)
        out.append(f"{LB}{len(codes)}/{RB}")

    def walk(s: str) -> None:
        i = 0
        buf: list[str] = []

        def flush() -> None:
            if buf:
                out.append(_esc("".join(buf)))
                buf.clear()

        while i < len(s):
            if s[i] == "{":
                try:
                    c = parse_complex(s, i)
                except IcuError:
                    c = None
                if c is not None:
                    flush()
                    lead = c.head
                    for prefix, body, close in c.branches:
                        code(lead + prefix)
                        walk(body)
                        lead = close
                    code(lead + c.tail)
                    i = c.end
                    continue
            m = PLACEHOLDER_RE.match(s, i)
            if m:
                flush()
                code(m.group(0))
                i = m.end()
                continue
            buf.append(s[i])
            i += 1
        flush()

    walk(value)
    return Protected("".join(out), codes)


def restore(tagged: str, codes: list[str]) -> str:
    """Tagged text -> value with original placeholders. Raises TaggedParseError on an unknown
    or non-standalone code (QA has already blocked such targets)."""
    out: list[str] = []
    for kind, v in tags.pieces(tagged):
        if kind == "text":
            assert isinstance(v, str)
            out.append(v)
            continue
        assert isinstance(v, tuple)
        cid, ckind = v
        if ckind != "standalone" or not cid.isdigit() or not 1 <= int(cid) <= len(codes):
            raise TaggedParseError(f"unknown code {cid}")
        out.append(codes[int(cid) - 1])
    return "".join(out)


def extract(value: str, style: str = "auto") -> list[str]:
    """Placeholders of a value as written (complex ICU arguments counted by their arg name)."""
    if style == "none":
        return []
    found: list[str] = []
    i = 0
    s = value
    while i < len(s):
        if s[i] == "{":
            try:
                c = parse_complex(s, i)
            except IcuError:
                c = None
            if c is not None:
                found.append(f"{{{c.arg}, {c.kind}}}")
                for _, body, _ in c.branches:
                    found.extend(p for p in extract(body, style) if p not in found)
                i = c.end
                continue
        m = PLACEHOLDER_RE.match(s, i)
        if m:
            found.append(_norm(m.group(0)))
            i = m.end()
            continue
        i += 1
    return found


def _norm(ph: str) -> str:
    return re.sub(r"\s+", "", ph)


def diff(source: str, target: str, style: str = "auto") -> tuple[list[str], list[str]]:
    """(missing in target, added in target) placeholder multisets."""
    s, t = Counter(extract(source, style)), Counter(extract(target, style))
    return sorted((s - t).elements()), sorted((t - s).elements())


def icu_valid(value: str) -> str | None:
    """None when the value parses as ICU (or has no ICU syntax), else the error message."""
    try:
        icu_skeleton(value)
    except IcuError as e:
        return str(e)
    depth = 0
    for ch in value:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "closing brace without opening brace"
    return None if depth == 0 else "unbalanced braces"


def chips(value: str, style: str = "auto") -> list[str]:
    """Placeholders shown as chips in the editor (original spelling, in order)."""
    p = protect(value, style)
    return p.codes


__all__ = [
    "PLACEHOLDER_RE",
    "STYLES",
    "IcuComplex",
    "IcuError",
    "Protected",
    "TaggedParseError",
    "build_plural",
    "chips",
    "diff",
    "extract",
    "icu_skeleton",
    "icu_valid",
    "parse_complex",
    "protect",
    "restore",
    "selector_of",
    "whole_plural",
]
