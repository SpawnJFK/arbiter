"""gettext PO and POT.

gettext is source-keyed: msgid is both the key and the base-language text. With msgctxt
the key is "<msgctxt>::<msgid>" so one msgid can exist in several contexts; msgctxt is kept
in meta. Plural entries (msgid_plural) map msgid -> one, msgid_plural -> other in the base
language, and msgstr[i] -> plurals.gettext_forms(lang)[i] in the target.

Comments: "#." (extracted) is the description, "#:" references and "#," flags are kept in
meta. A "fuzzy" flag is reported as state machine. The header entry is regenerated on
render with Language and Plural-Forms for the target.
"""

from __future__ import annotations

import re
from typing import Any

from arbiter.strings import plurals
from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError, decode

_PLURAL_FORMS: dict[str, str] = {
    "one,other": "nplurals=2; plural=(n != 1);",
    "other": "nplurals=1; plural=0;",
    "one,few,many": "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);",
    "one,few,other": "nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;",
    "zero,one,two,few,many,other": "nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);",
}
_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
_KW = re.compile(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+(".*")\s*$')


def _unq(s: str) -> str:
    s = s.strip()
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        raise StringsFormatError(f"Invalid quoted string in the PO file: {s[:40]}")
    body = s[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            out.append(_ESC.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def _entries(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    cur: dict[str, Any] = {}
    last: str | None = None

    def push() -> None:
        nonlocal cur, last
        if "msgid" in cur:
            entries.append(cur)
        cur, last = {}, None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if "msgid" in cur:
                push()
            continue
        if line.startswith("#~"):
            continue  # obsolete entries are dropped
        if line.startswith("#"):
            if "msgid" in cur:
                push()
            kind, _, rest = line[1:2], None, line[2:].strip()
            if kind == ".":
                cur.setdefault("extracted", []).append(rest)
            elif kind == ":":
                cur.setdefault("refs", []).extend(rest.split())
            elif kind == ",":
                cur.setdefault("flags", []).extend(f.strip() for f in rest.split(",") if f.strip())
            elif kind == "|":
                pass
            else:
                cur.setdefault("comments", []).append(line[1:].strip())
            continue
        m = _KW.match(line)
        if m:
            kw, idx, val = m.group(1), m.group(2), m.group(3)
            if kw in ("msgctxt", "msgid") and "msgid" in cur and (kw == "msgctxt" or last != "msgctxt"):
                push()
            if idx is not None:
                cur.setdefault("msgstr_n", {})[int(idx)] = _unq(val)
                last = f"msgstr[{idx}]"
            else:
                cur[kw] = _unq(val)
                last = kw
            continue
        if line.startswith('"') and last:
            if last.startswith("msgstr["):
                i = int(last[7:-1])
                cur["msgstr_n"][i] += _unq(line)
            else:
                cur[last] += _unq(line)
            continue
        raise StringsFormatError(f"Unexpected line in the PO file: {line[:60]}")
    push()
    return entries


def parse(data: bytes, lang: str, base_lang: str, *, template: bool = False) -> Doc:
    entries = _entries(decode(data))
    doc = Doc(base_lang=base_lang, langs=[base_lang] if template else sorted({base_lang, lang}))
    for e in entries:
        msgid = e.get("msgid", "")
        if msgid == "" and "msgctxt" not in e:
            doc.meta["header"] = e.get("msgstr", "")
            continue
        ctxt = e.get("msgctxt")
        key = f"{ctxt}::{msgid}" if ctxt is not None else msgid
        row = KeyRow(key=key, description="\n".join(e.get("extracted", [])))
        meta: dict[str, Any] = {}
        if ctxt is not None:
            meta["msgctxt"] = ctxt
        if e.get("refs"):
            meta["refs"] = e["refs"]
        flags = [f for f in e.get("flags", []) if f != "fuzzy"]
        if flags:
            meta["flags"] = flags
        if e.get("comments"):
            meta["comments"] = e["comments"]
        row.meta = meta
        if "msgid_plural" in e:
            row.kind = "plural"
            row.values[base_lang] = {"one": msgid, "other": e["msgid_plural"]}
            strs = e.get("msgstr_n", {})
            if not template and any(strs.values()):
                order = plurals.gettext_forms(lang)
                row.values[lang] = {order[i]: v for i, v in sorted(strs.items()) if i < len(order) and v}
        else:
            row.values[base_lang] = msgid
            if not template and e.get("msgstr"):
                row.values[lang] = e["msgstr"]
        if lang in row.values and lang != base_lang:
            row.states[lang] = "machine" if "fuzzy" in e.get("flags", []) else "reviewed"
        doc.rows.append(row)
    return doc


def _q(s: str) -> str:
    body = s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\r", "\\r")
    if "\n" in body.rstrip("\n"):
        parts = body.split("\n")
        lines = [p + "\\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
        return '""\n' + "\n".join(f'"{p}"' for p in lines)
    return '"' + body.replace("\n", "\\n") + '"'


def render(doc: Doc, lang: str | None, *, template: bool = False) -> bytes:
    target = None if template or lang is None or lang == doc.base_lang else lang
    forms = plurals.gettext_forms(target or doc.base_lang)
    pf = _PLURAL_FORMS.get(",".join(forms), f"nplurals={len(forms)}; plural=(n != 1);")
    header = [
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: 8bit",
        f"Language: {(target or '').replace('-', '_')}",
        f"Plural-Forms: {pf}",
    ]
    out = ['msgid ""', 'msgstr ""'] + [f'"{h}\\n"' for h in header] + [""]
    for r in doc.rows:
        src = r.values.get(doc.base_lang)
        if src is None or not r.translatable:
            continue
        if r.description:
            out.extend(f"#. {line}" for line in r.description.splitlines())
        for c in r.meta.get("comments", []):
            out.append(f"# {c}")
        if r.meta.get("refs"):
            out.append("#: " + " ".join(r.meta["refs"]))
        flags = list(r.meta.get("flags", []))
        if target and r.states.get(target) == "machine":
            flags.append("fuzzy")
        if flags:
            out.append("#, " + ", ".join(flags))
        if "msgctxt" in r.meta:
            out.append(f"msgctxt {_q(r.meta['msgctxt'])}")
        tv = r.values.get(target) if target else None
        if r.kind == "plural" and isinstance(src, dict):
            out.append(f"msgid {_q(src.get('one', src.get('other', '')))}")
            out.append(f"msgid_plural {_q(src.get('other', ''))}")
            tforms = tv if isinstance(tv, dict) else {}
            for i, cat in enumerate(forms):
                out.append(f"msgstr[{i}] {_q(tforms.get(cat, ''))}")
        else:
            out.append(f"msgid {_q(src if isinstance(src, str) else src.get('other', ''))}")
            out.append(f"msgstr {_q(tv if isinstance(tv, str) else '')}")
        out.append("")
    return "\n".join(out).encode("utf-8")
