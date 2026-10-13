"""Apple formats: Localizable.strings, Localizable.stringsdict, Xcode String Catalogs (.xcstrings).

.strings      "key" = "value"; with /* comment */ or // comment before an entry (description).
              UTF-16 (with BOM) or UTF-8 input; rendered as UTF-8, which Xcode accepts.
.stringsdict  plist; one NSStringLocalizedFormatKey with a single %#@var@ plural variable per
              key becomes a plural key (format key and value type kept in meta). Keys with
              several variables are kept as-is in meta and rendered back unchanged.
.xcstrings    JSON String Catalog, every language in one file. Plural variations become
              plural keys; device variations and substitutions are reported and skipped.
              Our states map to stringUnit.state: reviewed/approved -> translated,
              machine -> needs_review.
"""

from __future__ import annotations

import json
import plistlib
import re
from typing import Any

from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError, decode

# ------------------------------------------------------------------ .strings

_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": "\0"}


def _read_string(s: str, i: int) -> tuple[str, int]:
    """s[i] is the opening quote. Returns (value, index after the closing quote)."""
    out: list[str] = []
    i += 1
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in "uU" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2 : i + 6]):
                out.append(chr(int(s[i + 2 : i + 6], 16)))
                i += 6
                continue
            out.append(_ESC.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise StringsFormatError("Unterminated string in the .strings file.")


def parse_strings(data: bytes, lang: str, base_lang: str) -> Doc:
    s = decode(data)
    doc = Doc(base_lang=base_lang, langs=[lang])
    i, n = 0, len(s)
    comment = ""
    while i < n:
        ch = s[i]
        if ch.isspace() or ch == ";":
            i += 1
            continue
        if s.startswith("/*", i):
            end = s.find("*/", i + 2)
            if end < 0:
                raise StringsFormatError("Unterminated comment in the .strings file.")
            comment = s[i + 2 : end].strip()
            i = end + 2
            continue
        if s.startswith("//", i):
            end = s.find("\n", i)
            end = n if end < 0 else end
            comment = s[i + 2 : end].strip()
            i = end
            continue
        if ch == '"':
            key, i = _read_string(s, i)
        else:
            m = re.compile(r"[A-Za-z0-9_.\-]+").match(s, i)
            if not m:
                raise StringsFormatError(f"Unexpected character {ch!r} in the .strings file.")
            key, i = m.group(0), m.end()
        while i < n and s[i].isspace():
            i += 1
        if i >= n or s[i] != "=":
            raise StringsFormatError(f"Expected '=' after key {key!r} in the .strings file.")
        i += 1
        while i < n and s[i].isspace():
            i += 1
        if i >= n or s[i] != '"':
            raise StringsFormatError(f"Expected a quoted value for key {key!r}.")
        value, i = _read_string(s, i)
        row = KeyRow(key=key, values={lang: value})
        if comment and comment != "No comment provided by engineer.":
            row.description = comment
        doc.rows.append(row)
        comment = ""
    return doc


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def render_strings(doc: Doc, lang: str) -> bytes:
    out: list[str] = []
    for r in doc.lang_rows(lang):
        if r.kind != "string":
            continue  # plurals live in .stringsdict / .xcstrings
        if r.description:
            out.append(f"/* {r.description.replace('*/', '* /')} */")
        out.append(f"{_q(r.key)} = {_q(str(r.values[lang]))};")
        out.append("")
    return "\n".join(out).encode("utf-8")


# ------------------------------------------------------------------ .stringsdict

_VAR = re.compile(r"%#@([A-Za-z0-9_]+)@")


def parse_stringsdict(data: bytes, lang: str, base_lang: str) -> Doc:
    try:
        root = plistlib.loads(data)
    except Exception:  # noqa: BLE001 - plistlib raises several types for broken input
        raise StringsFormatError("The .stringsdict file is not a valid property list.") from None
    if not isinstance(root, dict):
        raise StringsFormatError("A .stringsdict file must contain a dictionary.")
    doc = Doc(base_lang=base_lang, langs=[lang])
    for key, entry in root.items():
        if not isinstance(entry, dict):
            continue
        fmt = entry.get("NSStringLocalizedFormatKey", "")
        names = _VAR.findall(fmt) if isinstance(fmt, str) else []
        if len(names) == 1 and isinstance(entry.get(names[0]), dict):
            var = entry[names[0]]
            forms = {
                k: v
                for k, v in var.items()
                if k not in ("NSStringFormatSpecTypeKey", "NSStringFormatValueTypeKey") and isinstance(v, str)
            }
            doc.rows.append(
                KeyRow(
                    key=key,
                    kind="plural",
                    values={lang: forms},
                    meta={
                        "format_key": fmt,
                        "variable": names[0],
                        "value_type": var.get("NSStringFormatValueTypeKey", "d"),
                    },
                )
            )
        else:
            doc.warnings.append(f"{key}: several plural variables are not supported, skipped")
    return doc


def render_stringsdict(doc: Doc, lang: str) -> bytes:
    root: dict[str, Any] = {}
    for r in doc.lang_rows(lang):
        v = r.values[lang]
        if r.kind != "plural" or not isinstance(v, dict):
            continue
        var = r.meta.get("variable") or "count"
        entry: dict[str, Any] = {
            "NSStringFormatSpecTypeKey": "NSStringPluralRuleType",
            "NSStringFormatValueTypeKey": r.meta.get("value_type") or "d",
        }
        entry.update({k: t for k, t in v.items() if not k.startswith("=")})
        root[r.key] = {"NSStringLocalizedFormatKey": r.meta.get("format_key") or f"%#@{var}@", var: entry}
    return plistlib.dumps(root, fmt=plistlib.FMT_XML, sort_keys=False)


# ------------------------------------------------------------------ .xcstrings

_STATE_IN = {"translated": "reviewed", "needs_review": "machine", "new": "untranslated", "stale": "machine"}


def _unit(obj: Any) -> tuple[str, str] | None:
    if isinstance(obj, dict) and isinstance(obj.get("stringUnit"), dict):
        su = obj["stringUnit"]
        return str(su.get("value", "")), str(su.get("state", "translated"))
    return None


def parse_xcstrings(data: bytes, lang: str, base_lang: str) -> Doc:
    try:
        root = json.loads(decode(data))
    except json.JSONDecodeError as e:
        raise StringsFormatError(f"The String Catalog is not valid JSON (line {e.lineno}).") from None
    if not isinstance(root, dict) or not isinstance(root.get("strings"), dict):
        raise StringsFormatError("A String Catalog must have a `strings` object.")
    src = str(root.get("sourceLanguage") or base_lang)
    doc = Doc(base_lang=src, meta={"version": root.get("version", "1.0")})
    langs: set[str] = set()
    for key, entry in root["strings"].items():
        entry = entry if isinstance(entry, dict) else {}
        row = KeyRow(key=key, description=str(entry.get("comment") or ""))
        if entry.get("shouldTranslate") is False:
            row.translatable = False
        if entry.get("extractionState"):
            row.meta["extractionState"] = entry["extractionState"]
        locs = entry.get("localizations") or {}
        for loc, body in locs.items():
            u = _unit(body)
            if u is not None:
                row.values[loc], state = u
                row.states[loc] = _STATE_IN.get(state, "reviewed")
                langs.add(loc)
                continue
            plural = ((body or {}).get("variations") or {}).get("plural") if isinstance(body, dict) else None
            if isinstance(plural, dict):
                forms: dict[str, str] = {}
                states: set[str] = set()
                for cat, sub in plural.items():
                    pu = _unit(sub)
                    if pu is not None:
                        forms[cat], st = pu
                        states.add(st)
                row.kind = "plural"
                row.values[loc] = forms
                row.states[loc] = "machine" if "needs_review" in states else "reviewed"
                langs.add(loc)
            else:
                doc.warnings.append(f"{key} [{loc}]: variations other than plural are not supported")
        if src not in row.values and not locs:
            row.values[src] = key  # Xcode omits the source localization when value == key
            langs.add(src)
        doc.rows.append(row)
    doc.langs = sorted(langs)
    return doc


def _su(value: str, state: str) -> dict[str, Any]:
    st = "translated" if state in ("reviewed", "approved", "") else "needs_review"
    return {"stringUnit": {"state": st, "value": value}}


def render_xcstrings(doc: Doc, lang: str | None = None) -> bytes:
    """Every language in doc.langs (or the base plus `lang`)."""
    langs = doc.langs or [doc.base_lang] + ([lang] if lang and lang != doc.base_lang else [])
    strings: dict[str, Any] = {}
    for r in sorted(doc.rows, key=lambda r: r.key):
        entry: dict[str, Any] = {}
        if r.description:
            entry["comment"] = r.description
        if r.meta.get("extractionState"):
            entry["extractionState"] = r.meta["extractionState"]
        if not r.translatable:
            entry["shouldTranslate"] = False
        locs: dict[str, Any] = {}
        for loc in langs:
            if loc not in r.values or (not r.translatable and loc != doc.base_lang):
                continue
            v = r.values[loc]
            state = r.states.get(loc, "")
            if r.kind == "plural" and isinstance(v, dict):
                locs[loc] = {
                    "variations": {
                        "plural": {k: _su(t, state) for k, t in v.items() if not k.startswith("=")}
                    }
                }
            else:
                locs[loc] = _su(str(v), state)
        if locs:
            entry["localizations"] = locs
        strings[r.key] = entry
    root = {"sourceLanguage": doc.base_lang, "strings": strings, "version": doc.meta.get("version", "1.0")}
    return (json.dumps(root, ensure_ascii=False, indent=2, separators=(",", " : ")) + "\n").encode("utf-8")
