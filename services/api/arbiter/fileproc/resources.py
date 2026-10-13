"""App resource files handled as documents in the TMS file flow.

Formats: Flutter ARB, iOS .strings and .stringsdict, Java .properties and .NET .resx.
(Android strings.xml lives in xmlfmt.py because it shares the XML engine.) Every value
is one unit and one segment, identified by its key, exactly like the JSON handler; keys
are never translated. Placeholders and escape sequences become standalone codes, so a
translator cannot break `%1$@`, `{0}` or `\\n`.

Text formats (.strings, .properties, ARB) merge by splicing: only changed values are
rewritten and every other byte is copied, so an identity merge is byte exact. XML
formats (.resx, .stringsdict) re-serialize the tree when something changed and return
the original bytes otherwise.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from lxml import etree

from arbiter.fileproc.base import Content, ExtractedUnit, ExtractionResult, FormatError, InlineCode, TargetMap
from arbiter.fileproc.jsonfmt import _SKIP_VALUE, _Scanner, message_content, pointer_escape
from arbiter.fileproc.text import (
    PLACEHOLDER_RE,
    Span,
    check_target_ids,
    check_xml_text,
    decode_text,
    iter_lines,
    make_unit,
    normalize,
    placeholder_content,
    render_markup,
    renumber,
    resolve_target,
    splice,
)
from arbiter.fileproc.xmlfmt import is_element, local_name, parse_document, serialize_document

_PRINTF = (
    r"%(?:\d+\$)?(?:\#@[A-Za-z0-9_]+@|[-+\#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|L|z|j|t|q)?[diouxXeEfFgGaAcspn@%])"
)
APPLE_PH = re.compile(_PRINTF)
DOTNET_PH = re.compile(r"\{\{|\}\}|\{\d+(?:\s*,\s*-?\d+)?(?::[^{}]*)?\}")


def _codes(parts: list[str | tuple[str, str]], pattern: re.Pattern[str] | None) -> Content:
    """Decoded parts (text or (raw, display) codes) -> content with placeholders as codes."""
    out: Content = []
    for part in parts:
        if isinstance(part, tuple):
            out.append(InlineCode("0", "standalone", part[0], part[1]))
        elif pattern is not None:
            out.extend(placeholder_content(part, ids=iter(lambda: 0, 1), pattern=pattern))
        else:
            out.append(part)
    content = normalize(out)
    # Codes need distinct ids in reading order.
    numbered: Content = []
    n = 0
    for run in content:
        if isinstance(run, InlineCode):
            n += 1
            numbered.append(InlineCode(str(n), run.kind, run.original, run.display))
        else:
            numbered.append(run)
    return renumber(numbered)


def _render(content: Content, encode: Callable[[str, bool], str]) -> str:
    out: list[str] = []
    first = True
    for run in content:
        out.append(run.original if isinstance(run, InlineCode) else encode(run, first))
        first = False
    return "".join(out)


def join_surrogates(text: str) -> str:
    """\\uD83D\\uDE00 style escapes decode to two surrogates; join them into one character."""
    if not any("\ud800" <= c <= "\udfff" for c in text):
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _dedupe(seen: dict[str, int], key: str) -> str:
    seen[key] = seen.get(key, 0) + 1
    return key if seen[key] == 1 else f"{key}#{seen[key]}"


# --------------------------------------------------------------------------- ARB


class ArbHandler:
    """Flutter Application Resource Bundle: JSON whose @-keys carry metadata for translators."""

    name = "arb"
    extensions: tuple[str, ...] = ("arb",)

    def _spans(self, text: str, lang: str) -> list[Span]:
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            raise FormatError("The ARB file is not valid JSON.") from None
        if not isinstance(data, dict):
            raise FormatError("The ARB file must contain a JSON object of messages.")
        scanner = _Scanner(text)
        scanner.value(0, "")
        ensure_ascii = "\\u" in text and all(ord(c) < 128 for c in text)
        by_pointer = {f"/{pointer_escape(k)}": k for k in data if not k.startswith("@")}
        spans: list[Span] = []
        for tok in scanner.found:
            key = by_pointer.get(tok.pointer)
            if key is None or _SKIP_VALUE.match(tok.value.strip()):
                continue
            meta = data.get(f"@{key}")
            notes: list[str] = []
            if isinstance(meta, dict):
                if isinstance(meta.get("description"), str) and meta["description"].strip():
                    notes.append(meta["description"].strip())
                if isinstance(meta.get("context"), str) and meta["context"].strip():
                    notes.append(f"Context: {meta['context'].strip()}")
                placeholders = meta.get("placeholders")
                if isinstance(placeholders, dict):
                    for ph, spec in placeholders.items():
                        example = spec.get("example") if isinstance(spec, dict) else None
                        if example is not None:
                            notes.append(f"{{{ph}}} example: {example}")
            unit = make_unit(
                key, message_content(tok.value), lang, segment=False, context=f"key:{key}", notes=notes
            )
            if unit is None:
                continue

            def render(content: Content, _ea: bool = ensure_ascii) -> str:
                return json.dumps(render_markup(content), ensure_ascii=_ea)

            spans.append(Span(unit, tok.start, tok.end, render))
        return spans

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        return ExtractionResult(
            self.name, source_lang, [s.unit for s in self._spans(decoded.text, source_lang)]
        )

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        merged = splice(decoded.text, self._spans(decoded.text, "en"), targets)
        if merged == decoded.text:
            return original
        scanner = _Scanner(merged)
        scanner.value(0, "")
        for tok in scanner.found:
            if tok.pointer == "/@@locale":
                merged = merged[: tok.start] + json.dumps(target_lang.replace("-", "_")) + merged[tok.end :]
                break
        json.loads(merged)
        return decoded.encode(merged)


# --------------------------------------------------------------------------- iOS .strings

_STRINGS_ESC = re.compile(r"\\(?:[Uu][0-9a-fA-F]{4}|.)", re.S)
_BARE = re.compile(r"[A-Za-z0-9_.$:/-]+")


def strings_decode(raw: str) -> list[str | tuple[str, str]]:
    parts: list[str | tuple[str, str]] = []
    buf: list[str] = []
    pos = 0
    for m in _STRINGS_ESC.finditer(raw):
        buf.append(raw[pos : m.start()])
        tok = m.group(0)
        if tok in ("\\n", "\\t", "\\r"):
            if buf:
                parts.append("".join(buf))
                buf = []
            parts.append((tok, {"\\n": "line break", "\\t": "tab", "\\r": "carriage return"}[tok]))
        elif tok[1] in "Uu" and len(tok) == 6:
            buf.append(chr(int(tok[2:], 16)))
        else:
            buf.append(tok[1])
        pos = m.end()
    buf.append(raw[pos:])
    if buf:
        parts.append("".join(buf))
    return [join_surrogates(p) if isinstance(p, str) else p for p in parts]


def strings_encode(text: str, at_start: bool = False) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


class StringsHandler:
    """Apple .strings ("key" = "value"; with /* comments */), UTF-8 or UTF-16."""

    name = "strings"
    extensions: tuple[str, ...] = ("strings",)

    def _quoted(self, text: str, i: int) -> int:
        """Index just past the closing quote of a string starting at text[i] == '"'."""
        j = i + 1
        n = len(text)
        while j < n:
            if text[j] == "\\":
                j += 2
                continue
            if text[j] == '"':
                return j + 1
            j += 1
        raise self._error(text, i)

    def _error(self, text: str, i: int) -> FormatError:
        line = text.count("\n", 0, i) + 1
        return FormatError(f"The .strings file could not be read: unexpected text on line {line}.")

    def _skip(self, text: str, i: int, comments: list[str]) -> int:
        n = len(text)
        while i < n:
            if text[i].isspace():
                i += 1
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                if end == -1:
                    raise self._error(text, i)
                comments.append(text[i + 2 : end])
                i = end + 2
            elif text.startswith("//", i):
                end = text.find("\n", i)
                end = n if end == -1 else end
                comments.append(text[i + 2 : end])
                i = end
            else:
                break
        return i

    def _spans(self, text: str, lang: str) -> list[Span]:
        spans: list[Span] = []
        seen: dict[str, int] = {}
        i = 0
        n = len(text)
        while True:
            comments: list[str] = []
            i = self._skip(text, i, comments)
            if i >= n:
                break
            if text[i] == '"':
                end = self._quoted(text, i)
                key = "".join(
                    p if isinstance(p, str) else p[0] for p in strings_decode(text[i + 1 : end - 1])
                )
            else:
                m = _BARE.match(text, i)
                if not m:
                    raise self._error(text, i)
                key, end = m.group(0), m.end()
            i = self._skip(text, end, [])
            if i >= n or text[i] != "=":
                raise self._error(text, i)
            i = self._skip(text, i + 1, [])
            if i >= n or text[i] != '"':
                raise self._error(text, i)
            vend = self._quoted(text, i)
            vstart = i + 1
            i = self._skip(text, vend, [])
            if i >= n or text[i] != ";":
                raise self._error(text, i)
            i += 1
            notes = [" ".join(c.split()) for c in comments if c.strip() and "No comment provided" not in c]
            content = _codes(strings_decode(text[vstart : vend - 1]), APPLE_PH)
            uid = _dedupe(seen, key)
            unit = make_unit(uid, content, lang, segment=False, context=f"key:{key}", notes=notes)
            if unit is not None:
                spans.append(Span(unit, vstart, vend - 1, lambda c: _render(c, strings_encode)))
        return spans

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        return ExtractionResult(
            self.name, source_lang, [s.unit for s in self._spans(decoded.text, source_lang)]
        )

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        merged = splice(decoded.text, self._spans(decoded.text, "en"), targets)
        if merged == decoded.text:
            return original
        return decoded.encode(merged)


# --------------------------------------------------------------------------- Java .properties

_PROP_ESC = re.compile(r"\\(?:u[0-9a-fA-F]{4}|\r\n[ \t\f]*|[\r\n][ \t\f]*|.)", re.S)


def properties_decode(raw: str) -> list[str | tuple[str, str]]:
    parts: list[str | tuple[str, str]] = []
    buf: list[str] = []
    pos = 0
    for m in _PROP_ESC.finditer(raw):
        buf.append(raw[pos : m.start()])
        tok = m.group(0)
        c = tok[1]
        if c in "\r\n":
            pass  # line continuation: the break and the next line's indentation vanish
        elif c == "u" and len(tok) == 6:
            buf.append(chr(int(tok[2:], 16)))
        elif c in "ntrf":
            if buf:
                parts.append("".join(buf))
                buf = []
            parts.append((tok, {"n": "line break", "t": "tab", "r": "carriage return", "f": "form feed"}[c]))
        else:
            buf.append(c)
        pos = m.end()
    buf.append(raw[pos:])
    if buf:
        parts.append("".join(buf))
    return [join_surrogates(p) if isinstance(p, str) else p for p in parts]


def _key_decode(raw: str) -> str:
    return "".join(p if isinstance(p, str) else p[0] for p in properties_decode(raw))


@dataclass
class _PropEntry:
    key: str
    vstart: int
    vend: int
    notes: list[str]


class PropertiesHandler:
    """Java .properties: key=value / key: value / key value, # and ! comments, continuations."""

    name = "properties"
    extensions: tuple[str, ...] = ("properties",)

    def _entries(self, text: str) -> list[_PropEntry]:
        lines = iter_lines(text)
        entries: list[_PropEntry] = []
        comments: list[str] = []
        i = 0
        while i < len(lines):
            off, body, _ = lines[i]
            stripped = body.lstrip(" \t\f")
            if not stripped:
                comments = []
                i += 1
                continue
            if stripped[0] in "#!":
                comments.append(stripped[1:].strip())
                i += 1
                continue
            start = off + len(body) - len(stripped)
            end = off + len(body)
            # A line ending in an odd number of backslashes continues on the next line.
            while (len(lines[i][1]) - len(lines[i][1].rstrip("\\"))) % 2 == 1 and i + 1 < len(lines):
                i += 1
                end = lines[i][0] + len(lines[i][1])
            i += 1
            logical = text[start:end]
            j = 0
            while j < len(logical):
                ch = logical[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch in "=: \t\f":
                    break
                j += 1
            key = _key_decode(logical[:j])
            k = j
            while k < len(logical) and logical[k] in " \t\f":
                k += 1
            if k < len(logical) and logical[k] in "=:":
                k += 1
                while k < len(logical) and logical[k] in " \t\f":
                    k += 1
            entries.append(_PropEntry(key, start + k, end, [c for c in comments if c]))
            comments = []
        return entries

    def _spans(self, text: str, lang: str, encoding: str) -> list[Span]:
        ascii_only = all(ord(c) < 128 for c in text)

        def encode(s: str, at_start: bool) -> str:
            out: list[str] = []
            for idx, ch in enumerate(s):
                if ch == "\\":
                    out.append("\\\\")
                elif ch == "\n":
                    out.append("\\n")
                elif ch == "\t":
                    out.append("\\t")
                elif ch == "\r":
                    out.append("\\r")
                elif ch == "\f":
                    out.append("\\f")
                elif ch == " " and at_start and all(c == " " for c in s[:idx]):
                    out.append("\\ ")
                elif ord(ch) > 127 and (ascii_only or not _encodable(ch, encoding)):
                    out.append("".join(f"\\u{u:04x}" for u in _utf16_units(ch)))
                else:
                    out.append(ch)
            return "".join(out)

        spans: list[Span] = []
        seen: dict[str, int] = {}
        for e in self._entries(text):
            content = _codes(properties_decode(text[e.vstart : e.vend]), PLACEHOLDER_RE)
            uid = _dedupe(seen, e.key)
            unit = make_unit(uid, content, lang, segment=False, context=f"key:{e.key}", notes=e.notes)
            if unit is not None:
                spans.append(Span(unit, e.vstart, e.vend, lambda c, _enc=encode: _render(c, _enc)))
        return spans

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        decoded = decode_text(data)
        spans = self._spans(decoded.text, source_lang, decoded.encoding)
        return ExtractionResult(self.name, source_lang, [s.unit for s in spans])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        decoded = decode_text(original)
        merged = splice(decoded.text, self._spans(decoded.text, "en", decoded.encoding), targets)
        if merged == decoded.text:
            return original
        return decoded.encode(merged)


def _encodable(ch: str, encoding: str) -> bool:
    try:
        ch.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _utf16_units(ch: str) -> list[int]:
    data = ch.encode("utf-16-be")
    return [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data), 2)]


# --------------------------------------------------------------------------- XML resources (.resx, .stringsdict)


@dataclass
class _XmlValue:
    unit: ExtractedUnit
    elem: etree._Element


def _xml_merge(
    original: bytes,
    label: str,
    values: Callable[[etree._ElementTree, str], list[_XmlValue]],
    targets: TargetMap,
) -> bytes:
    tree = parse_document(original, label)
    found = values(tree, "en")
    check_target_ids(targets, [v.unit.unit_id for v in found])
    changed = False
    for v in found:
        tgt = targets.get(v.unit.unit_id)
        if tgt is None:
            continue
        content, differs = resolve_target(v.unit, tgt)
        if not differs:
            continue
        text = render_markup(content)
        check_xml_text(text, v.unit.unit_id)
        v.elem.text = text
        changed = True
    return serialize_document(tree, original) if changed else original


class ResxHandler:
    """.NET .resx: string <data> entries (no type or mimetype), comments as translator notes."""

    name = "resx"
    extensions: tuple[str, ...] = ("resx", "resw")

    def _values(self, tree: etree._ElementTree, lang: str) -> list[_XmlValue]:
        out: list[_XmlValue] = []
        seen: dict[str, int] = {}
        for data in tree.getroot():
            if not is_element(data) or local_name(data) != "data":
                continue
            name = data.get("name", "")
            if not name or data.get("type") or data.get("mimetype") or name.startswith(">>"):
                continue
            value = next((c for c in data if is_element(c) and local_name(c) == "value"), None)
            if value is None or len(value) or not value.text:
                continue
            comment = next((c for c in data if is_element(c) and local_name(c) == "comment"), None)
            notes = (
                [comment.text.strip()]
                if comment is not None and comment.text and comment.text.strip()
                else []
            )
            uid = _dedupe(seen, name)
            content = _codes([value.text], DOTNET_PH)
            unit = make_unit(uid, content, lang, segment=False, context=f"key:{name}", notes=notes)
            if unit is not None:
                out.append(_XmlValue(unit, value))
        return out

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        tree = parse_document(data, "RESX")
        return ExtractionResult(self.name, source_lang, [v.unit for v in self._values(tree, source_lang)])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        return _xml_merge(original, "RESX", self._values, targets)


_PLURAL_CATEGORIES = ("zero", "one", "two", "few", "many", "other")


def _plist_pairs(d: etree._Element) -> list[tuple[str, etree._Element]]:
    children = [c for c in d if is_element(c)]
    pairs: list[tuple[str, etree._Element]] = []
    for k, v in zip(children[::2], children[1::2], strict=False):
        if local_name(k) == "key":
            pairs.append((k.text or "", v))
    return pairs


class StringsdictHandler:
    """Apple .stringsdict plural rules: the format string and every plural category string."""

    name = "stringsdict"
    extensions: tuple[str, ...] = ("stringsdict",)

    def _values(self, tree: etree._ElementTree, lang: str) -> list[_XmlValue]:
        root = tree.getroot()
        top = next((c for c in root if is_element(c) and local_name(c) == "dict"), None)
        if local_name(root) != "plist" or top is None:
            raise FormatError("The .stringsdict file is not a property list of plural rules.")
        out: list[_XmlValue] = []

        def add(uid: str, el: etree._Element, context: str, notes: list[str]) -> None:
            if local_name(el) != "string" or len(el) or not el.text:
                return
            unit = make_unit(
                uid, _codes([el.text], APPLE_PH), lang, segment=False, context=context, notes=notes
            )
            if unit is not None:
                out.append(_XmlValue(unit, el))

        for key, entry in _plist_pairs(top):
            if local_name(entry) != "dict":
                continue
            for sub, value in _plist_pairs(entry):
                if sub == "NSStringLocalizedFormatKey":
                    add(
                        f"{key}/{sub}",
                        value,
                        f"key:{key}",
                        ["Format string; %#@name@ refers to a plural rule."],
                    )
                elif local_name(value) == "dict":
                    for cat, text_el in _plist_pairs(value):
                        if cat in _PLURAL_CATEGORIES:
                            add(
                                f"{key}/{sub}/{cat}",
                                text_el,
                                f"key:{key}",
                                [f"Plural form '{cat}' of {sub}."],
                            )
        return out

    def extract(self, data: bytes, source_lang: str) -> ExtractionResult:
        tree = parse_document(data, "STRINGSDICT")
        return ExtractionResult(self.name, source_lang, [v.unit for v in self._values(tree, source_lang)])

    def merge(self, original: bytes, targets: TargetMap, target_lang: str) -> bytes:
        return _xml_merge(original, "STRINGSDICT", self._values, targets)
