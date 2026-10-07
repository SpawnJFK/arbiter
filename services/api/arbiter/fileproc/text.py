"""Plain text (TXT, CSV) handlers plus the helpers every format handler shares.

The shared helpers live here because the ownership rules for this package only allow
format modules next to base.py and segmenter.py. They are format neutral: building a
unit from content, validating a translated unit before it is written back, decoding
text files without losing their encoding, and turning placeholders into codes.

TXT and CSV are merged by splicing: we remember the character span of every unit in
the decoded text and replace only the spans whose translation differs from the
source. Everything else (line endings, quoting, odd spacing) is copied verbatim,
which is what makes the identity round trip byte exact.
"""

from __future__ import annotations

import codecs
import csv
import io
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import count

from arbiter.fileproc import segmenter
from arbiter.fileproc.base import (
    Content,
    ExtractedUnit,
    ExtractionResult,
    FormatError,
    InlineCode,
    SegmentDraft,
    TargetMap,
    codes_of,
    join_unit,
    plain_text,
)

# --------------------------------------------------------------------------- content helpers

_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


def has_text(content: Content | str) -> bool:
    """True when there is at least one letter: numbers, punctuation and codes alone are not work."""
    text = content if isinstance(content, str) else plain_text(content)
    return bool(_LETTER.search(text))


def normalize(content: Iterable[str | InlineCode]) -> Content:
    """Merge adjacent strings and drop empty ones so equal content compares equal."""
    out: Content = []
    for run in content:
        if isinstance(run, str):
            if not run:
                continue
            if out and isinstance(out[-1], str):
                out[-1] += run
                continue
        out.append(run)
    return out


def renumber(content: Content) -> Content:
    """Give codes the ids "1", "2", ... in order of first appearance.

    Parsers create codes while recursing, so their raw ids follow creation order, not
    reading order. Reviewers expect ⟦1⟧ to come before ⟦2⟧.
    """
    mapping: dict[str, str] = {}
    out: Content = []
    for run in content:
        if isinstance(run, InlineCode):
            new = mapping.setdefault(run.id, str(len(mapping) + 1))
            out.append(InlineCode(new, run.kind, run.original, run.display))
        else:
            out.append(run)
    return out


def render_markup(content: Content) -> str:
    """Text plus each code's original markup, for formats whose codes are literal source text."""
    return "".join(r.original if isinstance(r, InlineCode) else r for r in content)


def check_xml_text(text: str, unit_id: str) -> None:
    """XML 1.0 cannot carry most control characters; refuse instead of writing a broken file."""
    if _INVALID_XML.search(text):
        raise FormatError(
            f"The translation of unit {unit_id} contains control characters that cannot be stored in this file."
        )


def make_unit(
    unit_id: str,
    content: Iterable[str | InlineCode],
    lang: str,
    *,
    segment: bool = True,
    context: str = "",
    notes: Sequence[str] = (),
    max_length: int | None = None,
) -> ExtractedUnit | None:
    """Build a unit, keeping outer whitespace out of what engines see.

    Leading whitespace goes to ExtractedUnit.leading_ws and trailing whitespace to the
    last segment's trailing_ws, so join_unit() restores the exact source. If segmentation
    ever fails to reproduce the source we fall back to one segment rather than risk
    changing the file.
    """
    full = normalize(content)
    if not has_text(full):
        return None
    core = list(full)
    lead = trail = ""
    if core and isinstance(core[0], str):
        stripped = core[0].lstrip()
        lead = core[0][: len(core[0]) - len(stripped)]
        if stripped:
            core[0] = stripped
        else:
            core.pop(0)
    if core and isinstance(core[-1], str):
        stripped = core[-1].rstrip()
        trail = core[-1][len(stripped):]
        if stripped:
            core[-1] = stripped
        else:
            core.pop()

    drafts = segmenter.segment(core, lang) if segment else [SegmentDraft(content=list(core))]
    folded: list[SegmentDraft] = []
    for d in drafts:
        if not d.content and folded:
            folded[-1].trailing_ws += d.trailing_ws
        elif d.content:
            folded.append(d)
    if not folded:
        folded = [SegmentDraft(content=list(core))]
    folded[-1].trailing_ws += trail

    if join_unit([d.content for d in folded], folded, lead) != full:
        folded = [SegmentDraft(content=list(core), trailing_ws=trail)]
    return ExtractedUnit(
        unit_id=unit_id,
        segments=folded,
        context=context,
        notes=list(notes),
        max_length=max_length,
        leading_ws=lead,
    )


def unit_source(unit: ExtractedUnit) -> Content:
    return join_unit([s.content for s in unit.segments], unit.segments, unit.leading_ws)


def remap_codes(content: Content, source_codes: dict[tuple[str, str], InlineCode], unit_id: str) -> Content:
    """Swap target codes for the source code objects so markup always comes from the file."""
    out: Content = []
    for run in content:
        if isinstance(run, InlineCode):
            code = source_codes.get((run.id, run.kind))
            if code is None:
                raise FormatError(
                    f"The translation of unit {unit_id} contains inline code {run.id} which is not in the source."
                )
            out.append(code)
        elif isinstance(run, str):
            out.append(run)
        else:
            raise FormatError(f"The translation of unit {unit_id} is not valid content.")
    return out


def check_codes(target: Content, source: Content, unit_id: str) -> None:
    """Refuse targets that would corrupt markup on write-back.

    Codes may move (word order differs between languages), but each may appear at most
    once, pairs must stay complete and properly nested, and standalone codes cannot be
    dropped because they carry content (images, footnote references, placeholders).
    A paired code may be dropped as a whole, which only loses formatting.
    """
    src: dict[tuple[str, str], int] = {}  # (code id, kind)
    for c in codes_of(source):
        src[(c.id, c.kind)] = src.get((c.id, c.kind), 0) + 1
    tgt: dict[tuple[str, str], int] = {}
    stack: list[str] = []
    for c in codes_of(target):
        key: tuple[str, str] = (c.id, c.kind)
        tgt[key] = tgt.get(key, 0) + 1
        if key not in src:
            raise FormatError(
                f"The translation of unit {unit_id} contains inline code {c.id} which is not in the source."
            )
        if tgt[key] > src[key]:
            raise FormatError(f"The translation of unit {unit_id} repeats inline code {c.id}.")
        if c.kind == "open":
            stack.append(c.id)
        elif c.kind == "close":
            if not stack or stack[-1] != c.id:
                raise FormatError(
                    f"The translation of unit {unit_id} has inline code {c.id} closed in the wrong place."
                )
            stack.pop()
    if stack:
        raise FormatError(f"The translation of unit {unit_id} leaves inline code {stack[-1]} unclosed.")
    for key, n in src.items():
        if tgt.get(key, 0) < n and key[1] == "standalone":
            raise FormatError(f"The translation of unit {unit_id} is missing inline code {key[0]}.")


def resolve_segments(unit: ExtractedUnit, target: list[Content]) -> list[Content]:
    """Validate the target segments of one unit and remap their codes to source codes."""
    if len(target) != len(unit.segments):
        raise FormatError(
            f"The translation of unit {unit.unit_id} has {len(target)} segments but the source has "
            f"{len(unit.segments)}."
        )
    src_codes: dict[tuple[str, str], InlineCode] = {
        (c.id, c.kind): c for s in unit.segments for c in codes_of(s.content)
    }
    return [normalize(remap_codes(list(seg), src_codes, unit.unit_id)) for seg in target]


def _seg_langs() -> list[str]:
    langs = ["en"]
    for name in ("_PYSBD_LANGS", "_FALLBACK", "_ABBREV"):
        for lang in sorted(getattr(segmenter, name, ()) or ()):
            if lang not in langs:
                langs.append(lang)
    return langs


_SEG_LANGS = _seg_langs()


def refit(unit: ExtractedUnit, n_segments: int) -> ExtractedUnit:
    """Re-segment a unit so it has the segment count the target was produced for.

    merge() is not told the source language, yet sentence segmentation depends on it.
    Joining the target needs the inter-sentence whitespace of the extraction that produced
    it, so we look for the segmentation (by language rule set) with a matching count.
    """
    if len(unit.segments) == n_segments:
        return unit
    raw = unit_source(unit)
    for lang in _SEG_LANGS:
        cand = make_unit(unit.unit_id, raw, lang, context=unit.context, notes=unit.notes,
                         max_length=unit.max_length)
        if cand is not None and len(cand.segments) == n_segments:
            return cand
    raise FormatError(
        f"The translation of unit {unit.unit_id} has {n_segments} segments, which does not match the source."
    )


def resolve_target(
    unit: ExtractedUnit, target: list[Content], *, resegment: bool = False
) -> tuple[Content, bool]:
    """Join a validated target into unit content. Returns (content, differs_from_source).

    resegment=True is for prose units that went through the sentence segmenter, see refit().
    """
    if resegment:
        unit = refit(unit, len(target))
    segs = resolve_segments(unit, target)
    joined = join_unit(segs, unit.segments, unit.leading_ws)
    source = unit_source(unit)
    check_codes(joined, source, unit.unit_id)
    return joined, joined != source


def check_target_ids(targets: TargetMap, known: Iterable[str]) -> None:
    """A target for a unit the file does not have means the job and the file disagree."""
    missing = set(targets) - set(known)
    if missing:
        sample = sorted(missing)[0]
        raise FormatError(f"The translation refers to unit {sample}, which does not exist in this file.")


# --------------------------------------------------------------------------- placeholders

PLACEHOLDER_RE = re.compile(
    r"""
    (?P<double>\{\{[^{}]*\}\})                                         # {{name}}
    |(?P<dollar>\$\{[^{}]*\})                                          # ${name}
    |(?P<pyfmt>%\([A-Za-z_][\w.-]*\)[-+\#0]*\d*(?:\.\d+)?[sdifuxXeEgGcr])   # %(name)s
    |(?P<printf>%(?:\d+\$)?[-+\#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|z|j|t|q)?[diouxXeEfFgGaAcspn@%])
    |(?P<brace>\{[A-Za-z0-9_.$-]*(?:\s*,[^{}]*)?\})                    # {name} {0} {} {n, number}
    """,
    re.VERBOSE,
)


def placeholder_content(text: str, ids: Iterable[int] | None = None, pattern: re.Pattern[str] = PLACEHOLDER_RE) -> Content:
    """Split text into strings and standalone codes for every placeholder match."""
    counter = iter(ids) if ids is not None else count(1)
    out: Content = []
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            out.append(text[pos : m.start()])
        out.append(InlineCode(str(next(counter)), "standalone", m.group(0), m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


# --------------------------------------------------------------------------- text decoding


@dataclass
class DecodedText:
    text: str
    encoding: str
    bom: bytes = b""

    def encode(self, text: str, *, fallback_utf8: bool = True) -> bytes:
        """Encode in the source encoding; legacy 8-bit files switch to UTF-8 when the target needs it."""
        try:
            return self.bom + text.encode(self.encoding)
        except UnicodeEncodeError:
            if not fallback_utf8:
                raise FormatError(
                    f"The translation contains characters that cannot be saved in the file's {self.encoding} encoding."
                ) from None
            return codecs.BOM_UTF8 + text.encode("utf-8")


_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


def decode_text(data: bytes, declared: str | None = None) -> DecodedText:
    """Decode without guessing wrong silently: BOM, then a declared charset, then UTF-8, then cp1252."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            try:
                return DecodedText(data[len(bom):].decode(enc), enc, bom)
            except UnicodeDecodeError:
                raise FormatError("The file's text encoding could not be read.") from None
    candidates = [declared] if declared else []
    candidates += ["utf-8", "cp1252", "latin-1"]
    for enc in candidates:
        if not enc:
            continue
        try:
            codecs.lookup(enc)
            return DecodedText(data.decode(enc), enc)
        except (LookupError, UnicodeDecodeError):
            continue
    raise FormatError("The file's text encoding could not be read.")  # pragma: no cover (latin-1 decodes all)


# --------------------------------------------------------------------------- splice merging


@dataclass
class Span:
    """A translatable stretch of a text file, identified by character offsets."""

    unit: ExtractedUnit
    start: int
    end: int
    render: Callable[[Content], str] = field(default=render_markup)


def splice(text: str, spans: list[Span], targets: TargetMap, *, resegment: bool = False) -> str:
    """Replace only the spans whose translation differs; everything else stays byte for byte."""
    check_target_ids(targets, (s.unit.unit_id for s in spans))
    out: list[str] = []
    pos = 0
    for span in sorted(spans, key=lambda s: s.start):
        tgt = targets.get(span.unit.unit_id)
        if tgt is None:
            continue
        content, changed = resolve_target(span.unit, tgt, resegment=resegment)
        if not changed:
            continue
        out.append(text[pos : span.start])
        out.append(span.render(content))
        pos = span.end
    out.append(text[pos:])
    return "".join(out)


# --------------------------------------------------------------------------- TXT

_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)?")


def iter_lines(text: str) -> list[tuple[int, str, str]]:
    """(offset, line body, line ending) for every line, keeping the exact terminators."""
    out: list[tuple[int, str, str]] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _LINE_RE.match(text, pos)
        assert m is not None
        raw = m.group(0)
        if not raw:
            break
        body = raw.rstrip("\r\n")
        out.append((pos, body, raw[len(body):]))
        pos = m.end()
    return out


class TextHandler:
    """Plain text: a paragraph is a run of non-blank lines, segmented into sentences."""

    name = "txt"
    extensions: tuple[str, ...] = ("txt",)

    def _spans(self, text: str, lang: str) -> list[Span]:
        spans: list[Span] = []
        block: list[tuple[int, str, str]] = []
        counter = [1]  # paragraph ordinal: stable even when translation changes offsets

        def flush() -> None:
            if not block:
                return
            start = block[0][0]
            end = block[-1][0] + len(block[-1][1])
            unit = make_unit(f"p{counter[0]}", [text[start:end]], lang, context="body")
            counter[0] += 1
            if unit is not None:
                spans.append(Span(unit, start, end))
            block.clear()

        for line in iter_lines(text):
            if line[1].strip():
                block.append(line)
            else:
                flush()
        flush()
        return spans

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        spans = self._spans(decoded.text, source_lang)
        return ExtractionResult(self.name, source_lang, [s.unit for s in spans])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        spans = self._spans(decoded.text, "en")
        merged = splice(decoded.text, spans, targets, resegment=True)
        if merged == decoded.text:
            return original
        return decoded.encode(merged)


# --------------------------------------------------------------------------- CSV


@dataclass
class _Cell:
    row: int
    col: int
    start: int  # span of the raw cell text including quotes
    end: int
    value: str
    quoted: bool


class CsvHandler:
    """CSV/TSV cell by cell. One cell is one unit and one segment.

    Parsed with a small span-recording tokenizer because the csv module cannot tell us
    where a cell sits in the file, and rewriting the whole file with csv.writer would
    change quoting and line endings. The csv module still decides the dialect (Sniffer)
    and cross-checks our parse, so we never write back a file we misread.
    """

    name = "csv"
    extensions: tuple[str, ...] = ("csv", "tsv")

    def __init__(
        self,
        delimiter: str | None = None,
        quotechar: str = '"',
        columns: Sequence[int | str] | None = None,
        skip_header: bool = False,
    ) -> None:
        self.delimiter = delimiter
        self.quotechar = quotechar
        self.columns = columns
        self.skip_header = skip_header

    def _delimiter(self, text: str) -> str:
        if self.delimiter:
            return self.delimiter
        sample = text[:64 * 1024]
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            return "\t" if sample.count("\t") > sample.count(",") else ","

    def _parse(self, text: str, delim: str) -> list[list[_Cell]]:
        q = self.quotechar
        rows: list[list[_Cell]] = []
        row: list[_Cell] = []
        i, n = 0, len(text)
        r = 0
        if n == 0:
            return rows
        while True:
            start = i
            if i < n and text[i] == q:
                i += 1
                buf: list[str] = []
                while True:
                    if i >= n:
                        raise FormatError("The CSV file has an unclosed quoted field.")
                    if text[i] == q:
                        if i + 1 < n and text[i + 1] == q:
                            buf.append(q)
                            i += 2
                            continue
                        i += 1
                        break
                    buf.append(text[i])
                    i += 1
                # Text between the closing quote and the delimiter is kept in the span.
                while i < n and text[i] not in (delim, "\r", "\n"):
                    buf.append(text[i])
                    i += 1
                row.append(_Cell(r, len(row), start, i, "".join(buf), True))
            else:
                while i < n and text[i] not in (delim, "\r", "\n"):
                    i += 1
                row.append(_Cell(r, len(row), start, i, text[start:i], False))
            if i >= n:
                rows.append(row)
                break
            if text[i] == delim:
                i += 1
                continue
            # line ending
            if text[i] == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 2
            else:
                i += 1
            rows.append(row)
            row = []
            r += 1
            if i >= n:
                break
        return rows

    def _cross_check(self, text: str, delim: str, rows: list[list[_Cell]]) -> None:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim, quotechar=self.quotechar)
        try:
            expected = [r for r in reader]
        except csv.Error:
            raise FormatError("The CSV file could not be read.") from None
        got = [[c.value for c in row] for row in rows if row != [] and not (len(row) == 1 and row[0].start == row[0].end and not row[0].quoted)]
        exp = [r for r in expected if r]
        if got != exp:
            raise FormatError("The CSV file has an irregular structure that cannot be translated safely.")

    def _wanted(self, header: list[_Cell] | None, col: int) -> bool:
        if self.columns is None:
            return True
        names = [c.value for c in header] if header else []
        for c in self.columns:
            if isinstance(c, int) and c == col:
                return True
            if isinstance(c, str) and col < len(names) and names[col] == c:
                return True
        return False

    def _spans(self, text: str, lang: str) -> tuple[list[Span], str]:
        delim = self._delimiter(text)
        rows = self._parse(text, delim)
        self._cross_check(text, delim, rows)
        header = rows[0] if rows else None
        spans: list[Span] = []
        for row in rows:
            if self.skip_header and row and row[0].row == 0:
                continue
            for cell in row:
                if not self._wanted(header, cell.col):
                    continue
                name = header[cell.col].value if header and cell.col < len(header) and cell.row > 0 else ""
                unit = make_unit(
                    f"R{cell.row + 1}C{cell.col + 1}",
                    [cell.value],
                    lang,
                    segment=False,
                    context=f"column:{name}" if name else f"row:{cell.row + 1}",
                )
                if unit is None:
                    continue
                spans.append(Span(unit, cell.start, cell.end, self._renderer(cell, delim)))
        return spans, delim

    def _renderer(self, cell: _Cell, delim: str) -> Callable[[Content], str]:
        q = self.quotechar

        def render(content: Content) -> str:
            value = render_markup(content)
            if cell.quoted or any(ch in value for ch in (delim, q, "\r", "\n")):
                return q + value.replace(q, q + q) + q
            return value

        return render

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
        return decoded.encode(merged)
