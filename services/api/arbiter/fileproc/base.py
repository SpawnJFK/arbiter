"""Canonical content model shared by every file format.

A segment's content is a list of runs: plain text (str) or InlineCode. Inline codes
stand for formatting and markup we must carry through translation untouched
(bold, links, tabs, placeholders, HTML tags).

Engines and reviewers see the TAGGED TEXT form, where codes are written as

    paired open   ⟦1⟧
    paired close  ⟦/1⟧
    standalone    ⟦2/⟧

The brackets are U+27E6 and U+27E7. They do not collide with HTML, braces in
code or JSON, and MT/LLM engines pass them through. Literal U+27E6/U+27E7 in the
source text are escaped as ⟦⟦ and ⟧⟧ so the round trip is lossless.

Format handlers (docx, html, ...) live in sibling modules and implement
FormatHandler. The contract that matters most:

    merge(original, {unit_id: source_segments}) == original   (byte-identical
    or, for zip-based formats, identical XML parts)

i.e. extracting and merging back without translating must not change the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

LB, RB = "⟦", "⟧"

CodeKind = Literal["open", "close", "standalone"]


@dataclass(frozen=True)
class InlineCode:
    id: str
    kind: CodeKind
    original: str = ""  # opaque original markup, restored verbatim on merge
    display: str = ""  # short human hint shown to reviewers: "bold", "link", "tab", "<b>"

    def token(self) -> str:
        if self.kind == "open":
            return f"{LB}{self.id}{RB}"
        if self.kind == "close":
            return f"{LB}/{self.id}{RB}"
        return f"{LB}{self.id}/{RB}"


Run = str | InlineCode
Content = list[Run]

_TOKEN_RE = re.compile(rf"{LB}(/?)([A-Za-z0-9_.-]+)(/?){RB}")


def _escape(text: str) -> str:
    return text.replace(LB, LB + LB).replace(RB, RB + RB)


def _unescape(text: str) -> str:
    return text.replace(LB + LB, LB).replace(RB + RB, RB)


def to_tagged(content: Content) -> str:
    """Content -> tagged text with ⟦⟧ placeholders."""
    out: list[str] = []
    for run in content:
        out.append(run.token() if isinstance(run, InlineCode) else _escape(run))
    return "".join(out)


def plain_text(content: Content) -> str:
    """Text only, codes removed. Used for QE, TM matching and word counts."""
    return "".join(r for r in content if isinstance(r, str))


def codes_of(content: Content) -> list[InlineCode]:
    return [r for r in content if isinstance(r, InlineCode)]


@dataclass
class TagIssue:
    """A tag integrity problem in a target.

    severity "error": content or structure is lost (standalone code missing: image,
    footnote, placeholder; unknown/duplicated code; broken nesting). The segment must
    not ship. severity "warning": a whole paired code was dropped, which loses
    formatting only. Merge accepts it, QA shows it to the reviewer. This is the same
    policy merge() applies, see decisions.md D-009.
    """

    kind: Literal["missing", "extra", "unbalanced", "order", "unknown", "malformed"]
    code_id: str
    detail: str = ""
    severity: Literal["error", "warning"] = "error"


class TaggedParseError(ValueError):
    pass


def _split_tokens(text: str) -> list[tuple[str, str | tuple[str, str]]]:
    """Split tagged text into ("text", str) and ("code", (id, kind)) pieces, honouring escapes."""
    pieces: list[tuple[str, str | tuple[str, str]]] = []
    i = 0
    buf: list[str] = []
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == LB and i + 1 < n and text[i + 1] == LB:
            buf.append(LB)
            i += 2
            continue
        if ch == RB and i + 1 < n and text[i + 1] == RB:
            buf.append(RB)
            i += 2
            continue
        if ch == LB:
            m = _TOKEN_RE.match(text, i)
            if not m:
                raise TaggedParseError(f"malformed code token at position {i}")
            if buf:
                pieces.append(("text", "".join(buf)))
                buf = []
            close, cid, selfclose = m.group(1), m.group(2), m.group(3)
            if close and selfclose:
                raise TaggedParseError(f"code {cid} is both closing and self-closing")
            kind = "close" if close else ("standalone" if selfclose else "open")
            pieces.append(("code", (cid, kind)))
            i = m.end()
            continue
        if ch == RB:
            raise TaggedParseError(f"stray closing bracket at position {i}")
        buf.append(ch)
        i += 1
    if buf:
        pieces.append(("text", "".join(buf)))
    return pieces


def from_tagged(text: str, source_codes: list[InlineCode]) -> Content:
    """Tagged text (e.g. engine output) -> Content, re-attaching the original markup by id.

    Unknown ids raise TaggedParseError. Use validate_tags() first to get a full report.
    """
    by_key = {(c.id, c.kind): c for c in source_codes}
    content: Content = []
    for kind, value in _split_tokens(text):
        if kind == "text":
            assert isinstance(value, str)
            if content and isinstance(content[-1], str):
                content[-1] += value
            else:
                content.append(value)
        else:
            assert isinstance(value, tuple)
            cid, ckind = value
            code = by_key.get((cid, ckind))
            if code is None:
                raise TaggedParseError(f"unknown code {cid} ({ckind})")
            content.append(code)
    return content


def validate_tags(source: Content, target_tagged: str) -> list[TagIssue]:
    """Integrity check of a target against its source codes.

    Every standalone code must be present exactly once. Paired codes must stay balanced
    and properly nested; they may move. Dropping a whole pair is a warning (formatting
    lost), dropping only one half of a pair is an error (broken markup).
    """
    issues: list[TagIssue] = []
    try:
        pieces = _split_tokens(target_tagged)
    except TaggedParseError as e:
        return [TagIssue("malformed", "", str(e))]

    src_codes = codes_of(source)
    src_count: dict[tuple[str, str], int] = {}
    for c in src_codes:
        key = (c.id, str(c.kind))
        src_count[key] = src_count.get(key, 0) + 1
    tgt_keys: list[tuple[str, str]] = [v for k, v in pieces if k == "code" and isinstance(v, tuple)]
    tgt_count: dict[tuple[str, str], int] = {}
    for key in tgt_keys:
        tgt_count[key] = tgt_count.get(key, 0) + 1

    paired_ids = {c.id for c in src_codes if c.kind == "open"}
    for (cid, kind), cnt in src_count.items():
        if tgt_count.get((cid, kind), 0) >= cnt:
            continue
        if kind == "standalone":
            issues.append(TagIssue("missing", cid, "standalone code missing (content lost)"))
        elif kind == "open":
            whole_pair_gone = (cid, "open") not in tgt_count and (cid, "close") not in tgt_count
            if whole_pair_gone:
                issues.append(TagIssue("missing", cid, "formatting pair dropped", "warning"))
            else:
                issues.append(TagIssue("unbalanced", cid, "opening half of a pair missing"))
        elif kind == "close" and (cid, "open") in tgt_count:
            issues.append(TagIssue("unbalanced", cid, "closing half of a pair missing"))
    for key, cnt in tgt_count.items():
        if key not in src_count:
            issues.append(TagIssue("unknown", key[0], f"{key[1]} code not in source"))
        elif cnt > src_count[key]:
            issues.append(TagIssue("extra", key[0], f"{key[1]} code duplicated"))

    stack: list[str] = []
    for cid, ckind in tgt_keys:
        if cid not in paired_ids:
            continue
        if ckind == "open":
            stack.append(cid)
        elif ckind == "close":
            if not stack:
                if not any(i.code_id == cid and i.kind == "unbalanced" for i in issues):
                    issues.append(TagIssue("unbalanced", cid, "close without open"))
            elif stack[-1] != cid:
                issues.append(TagIssue("order", cid, f"closes {cid} while {stack[-1]} is open"))
                if cid in stack:
                    stack.remove(cid)
            else:
                stack.pop()
    for cid in stack:
        if not any(i.code_id == cid and i.kind == "unbalanced" for i in issues):
            issues.append(TagIssue("unbalanced", cid, "open without close"))
    return issues


def tag_errors(source: Content, target_tagged: str) -> list[TagIssue]:
    """Only the issues that must stop a segment from shipping."""
    return [i for i in validate_tags(source, target_tagged) if i.severity == "error"]


def is_balanced(content: Content) -> bool:
    depth = 0
    for r in content:
        if isinstance(r, InlineCode):
            if r.kind == "open":
                depth += 1
            elif r.kind == "close":
                depth -= 1
                if depth < 0:
                    return False
    return depth == 0


# --------------------------------------------------------------------------- units


@dataclass
class SegmentDraft:
    """One segment as extracted, before it enters the database."""

    content: Content
    # Whitespace that followed this segment in the source unit. Restored on merge so
    # paragraph spacing survives translation.
    trailing_ws: str = ""


@dataclass
class ExtractedUnit:
    """A translatable block: a paragraph, a table cell, a JSON value, a PO entry."""

    unit_id: str  # stable and deterministic within the file
    segments: list[SegmentDraft]
    context: str = ""  # "body", "header", "table", "footnote", "key:app.title", ...
    max_length: int | None = None
    notes: list[str] = field(default_factory=list)
    leading_ws: str = ""


@dataclass
class ExtractionResult:
    format: str
    source_lang: str
    units: list[ExtractedUnit]
    warnings: list[str] = field(default_factory=list)

    @property
    def segment_count(self) -> int:
        return sum(len(u.segments) for u in self.units)


TargetMap = dict[str, list[Content]]  # unit_id -> target content per segment


class FormatError(ValueError):
    """The file cannot be processed. Message is safe to show the client (R-IN-*)."""


class FormatHandler(Protocol):
    name: str
    extensions: tuple[str, ...]

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult: ...

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes: ...


def join_unit(segments: list[Content], drafts: list[SegmentDraft], leading_ws: str = "") -> Content:
    """Rebuild a unit's content from translated segments, restoring inter-segment whitespace."""
    out: Content = [leading_ws] if leading_ws else []
    for seg, draft in zip(segments, drafts, strict=True):
        out.extend(seg)
        if draft.trailing_ws:
            out.append(draft.trailing_ws)
    # merge adjacent strings
    merged: Content = []
    for r in out:
        if isinstance(r, str) and merged and isinstance(merged[-1], str):
            merged[-1] += r
        elif r != "":
            merged.append(r)
    return merged


def source_targets(result: ExtractionResult) -> TargetMap:
    """Identity target map: used by round-trip tests and to verify merge correctness."""
    return {u.unit_id: [s.content for s in u.segments] for u in result.units}
