"""Gettext PO/POT handler with its own small parser.

Written in-house instead of depending on polib because merge needs line positions: we
rewrite only the msgstr lines (and the flags line when dropping "fuzzy") of entries
that receive a translation, so comments, references, wrapping and ordering stay exactly
as the developer's tooling wrote them.

Units: one per non-header, non-obsolete entry. A singular entry has one segment. A
plural entry has two segments, the msgid and the msgid_plural; on merge the first
target goes to msgstr[0] and the last to every other form, sized by the target
language's nplurals. msgctxt becomes the unit context, translator and extracted
comments become notes. Leading and trailing newlines are kept out of what engines see
and restored on merge, because msgfmt rejects a msgstr whose outer newlines differ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from arbiter.fileproc.base import (
    ExtractedUnit,
    ExtractionResult,
    FormatError,
    SegmentDraft,
    TargetMap,
    codes_of,
)
from arbiter.fileproc.text import (
    DecodedText,
    check_codes,
    check_target_ids,
    decode_text,
    has_text,
    iter_lines,
    placeholder_content,
    render_markup,
    resolve_segments,
)

_KEYWORD = re.compile(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+(".*)$')
_CONT = re.compile(r'^\s*(".*")\s*$')
_CHARSET = re.compile(r"charset=([A-Za-z0-9_.-]+)")
_NPLURALS = re.compile(r"nplurals\s*=\s*(\d+)")

# Plural-Forms headers for common target languages (from the gettext manual / CLDR).
PLURAL_FORMS: dict[str, str] = {
    "sr": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "hr": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "bs": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "ru": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "uk": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "pl": "nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "cs": "nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;",
    "sk": "nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;",
    "sl": "nplurals=4; plural=(n%100==1 ? 0 : n%100==2 ? 1 : n%100==3 || n%100==4 ? 2 : 3);",
    "fr": "nplurals=2; plural=(n > 1);",
    "pt-br": "nplurals=2; plural=(n > 1);",
    "ja": "nplurals=1; plural=0;",
    "zh": "nplurals=1; plural=0;",
    "ko": "nplurals=1; plural=0;",
    "vi": "nplurals=1; plural=0;",
    "th": "nplurals=1; plural=0;",
    "id": "nplurals=1; plural=0;",
    "ar": "nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);",
    "ro": "nplurals=3; plural=(n==1 ? 0 : (n==0 || (n%100 > 0 && n%100 < 20)) ? 1 : 2);",
    "lt": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "lv": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n != 0 ? 1 : 2);",
    "ga": "nplurals=5; plural=(n==1 ? 0 : n==2 ? 1 : n<7 ? 2 : n<11 ? 3 : 4);",
}
DEFAULT_PLURAL_FORMS = "nplurals=2; plural=(n != 1);"

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
_REVERSE = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\t": "\\t",
    "\r": "\\r",
    "\a": "\\a",
    "\b": "\\b",
    "\f": "\\f",
    "\v": "\\v",
}


def unquote(token: str) -> str:
    token = token.strip()
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise FormatError("The PO file has a malformed string.")
    body = token[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 2
        elif nxt == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", body[i + 2 :])
            if not m:
                raise FormatError("The PO file has a malformed escape sequence.")
            out.append(chr(int(m.group(0), 16)))
            i += 2 + len(m.group(0))
        elif nxt.isdigit():
            m = re.match(r"[0-7]{1,3}", body[i + 1 :])
            assert m
            out.append(chr(int(m.group(0), 8)))
            i += 1 + len(m.group(0))
        else:
            raise FormatError("The PO file has a malformed escape sequence.")
    return "".join(out)


def quote(value: str) -> str:
    return '"' + "".join(_REVERSE.get(c, c) for c in value) + '"'


def format_field(keyword: str, value: str, eol: str) -> str:
    """gettext layout: one line, or an empty first line followed by one line per \\n."""
    inner = value[:-1] if value.endswith("\n") else value
    if "\n" not in inner:
        return f"{keyword} {quote(value)}{eol}"
    parts = re.findall(r"[^\n]*\n|[^\n]+$", value)
    lines = [f'{keyword} ""{eol}'] + [f"{quote(p)}{eol}" for p in parts]
    return "".join(lines)


@dataclass
class _Entry:
    index: int
    first_line: int
    comments: list[tuple[int, str]] = field(default_factory=list)  # (line no, text)
    msgctxt: str | None = None
    msgid: str = ""
    msgid_plural: str | None = None
    msgstr: dict[int, str] = field(default_factory=dict)
    msgstr_lines: tuple[int, int] = (-1, -1)  # [start, end) line range of all msgstr fields
    obsolete: bool = False
    has_msgid: bool = False

    @property
    def flags(self) -> list[str]:
        out: list[str] = []
        for _, c in self.comments:
            if c.startswith("#,"):
                out += [f.strip() for f in c[2:].split(",") if f.strip()]
        return out


def parse_po(text: str) -> tuple[list[_Entry], list[tuple[int, str, str]]]:
    lines = iter_lines(text)
    entries: list[_Entry] = []
    cur: _Entry | None = None
    field_name: str | None = None
    field_index = 0
    values: dict[tuple[str, int], list[str]] = {}

    def finish() -> None:
        nonlocal cur, values
        if cur is not None and (cur.has_msgid or cur.obsolete):
            for (name, idx), parts in values.items():
                val = "".join(parts)
                if name == "msgctxt":
                    cur.msgctxt = val
                elif name == "msgid":
                    cur.msgid = val
                elif name == "msgid_plural":
                    cur.msgid_plural = val
                else:
                    cur.msgstr[idx] = val
            entries.append(cur)
        cur = None
        values = {}

    for ln, (_, body, _) in enumerate(lines):
        stripped = body.strip()
        if not stripped:
            finish()
            field_name = None
            continue
        if stripped.startswith("#"):
            if cur is not None and cur.msgstr_lines[0] != -1:
                finish()
            if cur is None:
                cur = _Entry(len(entries), ln)
            if stripped.startswith("#~"):
                cur.obsolete = True
            cur.comments.append((ln, stripped))
            field_name = None
            continue
        m = _KEYWORD.match(stripped)
        if m:
            name = m.group(1)
            base = "msgstr" if name.startswith("msgstr") else name
            if base in ("msgctxt", "msgid") and cur is not None and cur.msgstr_lines[0] != -1:
                finish()
            if cur is None:
                cur = _Entry(len(entries), ln)
            if base == "msgid":
                cur.has_msgid = True
            idx = int(m.group(2)) if m.group(2) else 0
            field_name, field_index = base, idx
            values[(base, idx)] = [unquote(m.group(3))]
            if base == "msgstr":
                start = cur.msgstr_lines[0] if cur.msgstr_lines[0] != -1 else ln
                cur.msgstr_lines = (start, ln + 1)
            continue
        c = _CONT.match(body)
        if c and cur is not None and field_name is not None:
            values[(field_name, field_index)].append(unquote(c.group(1)))
            if field_name == "msgstr":
                cur.msgstr_lines = (cur.msgstr_lines[0], ln + 1)
            continue
        raise FormatError(f"The PO file could not be read (line {ln + 1}).")
    finish()
    return entries, lines


def _split_ws(value: str) -> tuple[str, str, str]:
    core = value.strip()
    if not core:
        return value, "", ""
    lead = value[: len(value) - len(value.lstrip())]
    trail = value[len(value.rstrip()) :]
    return lead, core, trail


def _header(entries: list[_Entry]) -> _Entry | None:
    for e in entries:
        if not e.obsolete and e.msgid == "" and e.msgctxt is None:
            return e
    return None


def _unit_for(e: _Entry) -> tuple[ExtractedUnit | None, list[tuple[str, str]]]:
    """Build the unit and the (lead, trail) whitespace per source form."""
    forms = [e.msgid] if e.msgid_plural is None else [e.msgid, e.msgid_plural]
    if not any(has_text(f) for f in forms):
        return None, []
    ws: list[tuple[str, str]] = []
    segments: list[SegmentDraft] = []
    next_id = 1
    for f in forms:
        lead, core, trail = _split_ws(f)
        content = placeholder_content(core, iter(range(next_id, 10_000)))
        next_id += len(codes_of(content))
        segments.append(SegmentDraft(content=content, trailing_ws=trail))
        ws.append((lead, trail))
    notes: list[str] = []
    for _, c in e.comments:
        if c.startswith("#."):
            notes.append(c[2:].strip())
        elif c.startswith("# ") and c[1:].strip():
            notes.append(c[1:].strip())
    if e.msgid_plural is not None:
        notes.append("Plural entry: segment 1 is the singular form, segment 2 the plural form.")
    unit = ExtractedUnit(
        unit_id=f"e{e.index}",
        segments=segments,
        context=e.msgctxt or "",
        notes=notes,
        leading_ws=ws[0][0],
    )
    return unit, ws


class PoHandler:
    name = "po"
    extensions: tuple[str, ...] = ("po", "pot")

    def _decode(self, data: bytes) -> DecodedText:
        m = _CHARSET.search(data[:8192].decode("ascii", "ignore"))
        declared = m.group(1) if m and m.group(1).upper() != "CHARSET" else None
        return decode_text(data, declared)

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = self._decode(data)
        entries, _ = parse_po(decoded.text)
        header = _header(entries)
        units: list[ExtractedUnit] = []
        for e in entries:
            if e.obsolete or e is header:
                continue
            unit, _ = _unit_for(e)
            if unit is not None:
                units.append(unit)
        return ExtractionResult(self.name, source_lang, units)

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = self._decode(original)
        text = decoded.text
        entries, lines = parse_po(text)
        header = _header(entries)
        units = {}
        for e in entries:
            if e.obsolete or e is header:
                continue
            unit, ws = _unit_for(e)
            if unit is not None:
                units[unit.unit_id] = (e, unit, ws)
        check_target_ids(targets, units)

        nplurals = self._nplurals(header, target_lang)
        replace: dict[int, tuple[int, str]] = {}  # start line -> (end line, new text)
        drop_lines: set[int] = set()
        for uid, (e, unit, ws) in units.items():
            tgt = targets.get(uid)
            if tgt is None:
                continue
            segs = resolve_segments(unit, tgt)
            for seg, draft in zip(segs, unit.segments, strict=True):
                check_codes(seg, draft.content, uid)
            forms = [ws[0][0] + render_markup(segs[0]) + ws[0][1]]
            if e.msgid_plural is not None:
                other = ws[1][0] + render_markup(segs[1]) + ws[1][1]
                # Languages with a single form (ja, zh, ...) use the general plural wording.
                forms = [other] if nplurals == 1 else [forms[0]] + [other] * (nplurals - 1)
            current = [e.msgstr.get(i, "") for i in range(len(forms))]
            fuzzy = "fuzzy" in e.flags
            if current == forms and not fuzzy and len(e.msgstr) == len(forms):
                continue
            if e.msgstr_lines[0] == -1:
                raise FormatError(f"The PO entry {uid} has no msgstr line.")
            eol = lines[e.msgstr_lines[0]][2] or "\n"
            if e.msgid_plural is None:
                new = format_field("msgstr", forms[0], eol)
            else:
                new = "".join(format_field(f"msgstr[{i}]", f, eol) for i, f in enumerate(forms))
            replace[e.msgstr_lines[0]] = (e.msgstr_lines[1], new)
            if fuzzy:
                self._unfuzzy(e, lines, replace, drop_lines)

        if not replace:
            return original
        if header is not None and header.msgstr_lines[0] != -1:
            new_header = self._header_text(header.msgstr.get(0, ""), target_lang)
            if new_header != header.msgstr.get(0, ""):
                eol = lines[header.msgstr_lines[0]][2] or "\n"
                replace[header.msgstr_lines[0]] = (
                    header.msgstr_lines[1],
                    format_field("msgstr", new_header, eol),
                )
        out: list[str] = []
        ln = 0
        while ln < len(lines):
            if ln in replace:
                end, new = replace[ln]
                out.append(new)
                ln = end
                continue
            if ln not in drop_lines:
                out.append(lines[ln][1] + lines[ln][2])
            ln += 1
        merged = "".join(out)
        try:
            return decoded.encode(merged, fallback_utf8=False)
        except FormatError:
            # A legacy charset cannot hold the target language: switch the file to UTF-8, header included.
            merged = re.sub(r"charset=[A-Za-z0-9_.-]+", "charset=UTF-8", merged, count=1)
            return merged.encode("utf-8")

    @staticmethod
    def _unfuzzy(
        e: _Entry, lines: list[tuple[int, str, str]], replace: dict[int, tuple[int, str]], drop: set[int]
    ) -> None:
        for ln, c in e.comments:
            if c.startswith("#,"):
                flags = [f for f in (x.strip() for x in c[2:].split(",")) if f and f != "fuzzy"]
                if flags:
                    replace[ln] = (ln + 1, "#, " + ", ".join(flags) + lines[ln][2])
                else:
                    drop.add(ln)
            elif c.startswith("#|"):
                drop.add(ln)  # previous-msgid lines only make sense on fuzzy entries

    @staticmethod
    def _nplurals(header: _Entry | None, target_lang: str) -> int:
        if header is not None:
            m = _NPLURALS.search(header.msgstr.get(0, ""))
            if m:
                return int(m.group(1))
        return int(_NPLURALS.search(_plural_forms(target_lang)).group(1))  # type: ignore[union-attr]

    @staticmethod
    def _header_text(header: str, target_lang: str) -> str:
        """Fill in what a POT template leaves as placeholders so the result compiles."""
        out = header
        out = re.sub(r"^Language:[ \t]*$", f"Language: {target_lang}", out, flags=re.M)
        if "nplurals=INTEGER" in out:
            out = re.sub(r"Plural-Forms:[^\n]*", f"Plural-Forms: {_plural_forms(target_lang)}", out)
        out = out.replace("charset=CHARSET", "charset=UTF-8")
        return out


def _plural_forms(lang: str) -> str:
    key = lang.lower().replace("_", "-")
    return PLURAL_FORMS.get(key) or PLURAL_FORMS.get(key.split("-")[0]) or DEFAULT_PLURAL_FORMS
