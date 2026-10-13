"""JSON family: flat and nested JSON, i18next, FormatJS, next-intl (ICU), Flutter ARB.

    json         flat {"a.b": "..."}; parse also accepts nested (keys joined with ".")
    json_nested  nested {"a": {"b": "..."}} (next-intl, vue-i18n, ngx-translate)
    i18next      nested; plurals as key_one / key_other suffixes; {{name}} interpolation
    formatjs     {"id": {"defaultMessage": "...", "description": "..."}} (also compiled {"id": "..."})
    arb          Flutter: {"@@locale": "en", "key": "...", "@key": {"description", "placeholders"}}

ICU: a value that is exactly one plural argument ({count, plural, one {...} other {...}})
becomes a plural key with forms; the argument name is kept in meta["icu_arg"] so export
rebuilds the same message. Embedded ICU (text around the argument) stays a string; the
placeholder layer protects its selectors.
"""

from __future__ import annotations

import json
from typing import Any

from arbiter.strings import placeholders as ph
from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError, Value, decode, is_plural_map

I18NEXT_SUFFIXES = ("zero", "one", "two", "few", "many", "other")


def _load(data: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(decode(data))
    except json.JSONDecodeError as e:
        raise StringsFormatError(f"The JSON file is not valid JSON (line {e.lineno}).") from None
    if not isinstance(obj, dict):
        raise StringsFormatError("The JSON file must contain an object of keys.")
    return obj


def _icu_row(key: str, value: str, lang: str, icu: bool) -> KeyRow:
    if icu:
        c = ph.whole_plural(value)
        if c is not None:
            forms = {ph.selector_of(p): body for p, body, _ in c.branches}
            return KeyRow(
                key=key, kind="plural", values={lang: forms}, meta={"icu_arg": c.arg, "icu_kind": c.kind}
            )
    return KeyRow(key=key, values={lang: value})


def _walk(
    obj: dict[str, Any], prefix: str, lang: str, rows: list[KeyRow], warnings: list[str], icu: bool
) -> None:
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, str):
            rows.append(_icu_row(key, v, lang, icu))
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            rows.append(KeyRow(key=key, kind="array", values={lang: {str(i): x for i, x in enumerate(v)}}))
        elif isinstance(v, dict):
            _walk(v, key, lang, rows, warnings, icu)
        elif v is None:
            continue
        else:
            warnings.append(f"{key}: value of type {type(v).__name__} skipped")


def parse_json(data: bytes, lang: str, base_lang: str) -> Doc:
    doc = Doc(base_lang=base_lang, langs=[lang])
    _walk(_load(data), "", lang, doc.rows, doc.warnings, icu=True)
    return doc


def parse_i18next(data: bytes, lang: str, base_lang: str) -> Doc:
    doc = Doc(base_lang=base_lang, langs=[lang])
    flat: list[KeyRow] = []
    _walk(_load(data), "", lang, flat, doc.warnings, icu=False)
    groups: dict[str, dict[str, str]] = {}
    for r in flat:
        base, _, suffix = r.key.rpartition("_")
        if base and suffix in I18NEXT_SUFFIXES and r.kind == "string":
            groups.setdefault(base, {})[suffix] = str(r.values[lang])
    emitted: set[str] = set()
    for r in flat:
        base, _, suffix = r.key.rpartition("_")
        if base in groups and suffix in I18NEXT_SUFFIXES and "other" in groups[base]:
            if base not in emitted:
                emitted.add(base)
                doc.rows.append(KeyRow(key=base, kind="plural", values={lang: groups[base]}))
            continue
        doc.rows.append(r)
    return doc


def parse_formatjs(data: bytes, lang: str, base_lang: str) -> Doc:
    doc = Doc(base_lang=base_lang, langs=[lang])
    for k, v in _load(data).items():
        if isinstance(v, dict):
            msg = v.get("defaultMessage", v.get("message"))
            if not isinstance(msg, str):
                doc.warnings.append(f"{k}: no defaultMessage")
                continue
            row = _icu_row(k, msg, lang, True)
            row.description = str(v.get("description") or "")
            doc.rows.append(row)
        elif isinstance(v, str):
            doc.rows.append(_icu_row(k, v, lang, True))
        else:
            doc.warnings.append(f"{k}: value skipped")
    return doc


def parse_arb(data: bytes, lang: str, base_lang: str) -> Doc:
    obj = _load(data)
    file_lang = obj.get("@@locale")
    doc = Doc(base_lang=base_lang, langs=[lang])
    if isinstance(file_lang, str):
        doc.meta["locale"] = file_lang
    doc.meta["globals"] = {k: v for k, v in obj.items() if k.startswith("@@") and k != "@@locale"}
    for k, v in obj.items():
        if k.startswith("@"):
            continue
        if not isinstance(v, str):
            doc.warnings.append(f"{k}: value skipped")
            continue
        row = _icu_row(k, v, lang, True)
        attrs = obj.get(f"@{k}")
        if isinstance(attrs, dict):
            row.description = str(attrs.get("description") or "")
            extra = {a: b for a, b in attrs.items() if a != "description"}
            if extra:
                row.meta["arb"] = extra
        doc.rows.append(row)
    return doc


# ------------------------------------------------------------------ render


def _icu_value(row: KeyRow, value: Value) -> str:
    if isinstance(value, dict) and row.kind == "plural":
        return ph.build_plural(
            row.meta.get("icu_arg") or "count", value, row.meta.get("icu_kind") or "plural"
        )
    if isinstance(value, dict):
        return json.dumps(list(value.values()), ensure_ascii=False)
    return value


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _set_nested(root: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    node = root
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            if nxt is not None:  # leaf and branch collide: keep the flat key
                root[key] = value
                return
            nxt = node[p] = {}
        node = nxt
    if isinstance(node.get(parts[-1]), dict):
        root[key] = value
        return
    node[parts[-1]] = value


def _leaf(row: KeyRow, value: Value) -> Any:
    if row.kind == "array" and isinstance(value, dict):
        return [value[k] for k in sorted(value, key=lambda x: int(x) if x.isdigit() else 0)]
    return _icu_value(row, value)


def render_json(doc: Doc, lang: str) -> bytes:
    return _dump({r.key: _leaf(r, r.values[lang]) for r in doc.lang_rows(lang)})


def render_json_nested(doc: Doc, lang: str) -> bytes:
    root: dict[str, Any] = {}
    for r in doc.lang_rows(lang):
        _set_nested(root, r.key, _leaf(r, r.values[lang]))
    return _dump(root)


def render_i18next(doc: Doc, lang: str) -> bytes:
    root: dict[str, Any] = {}
    for r in doc.lang_rows(lang):
        v = r.values[lang]
        if r.kind == "plural" and isinstance(v, dict):
            for form, text in v.items():
                if not form.startswith("="):
                    _set_nested(root, f"{r.key}_{form}", text)
        else:
            _set_nested(root, r.key, _leaf(r, v))
    return _dump(root)


def render_formatjs(doc: Doc, lang: str) -> bytes:
    out: dict[str, Any] = {}
    for r in doc.lang_rows(lang):
        entry: dict[str, Any] = {"defaultMessage": _icu_value(r, r.values[lang])}
        if r.description:
            entry["description"] = r.description
        out[r.key] = entry
    return _dump(out)


def render_arb(doc: Doc, lang: str) -> bytes:
    out: dict[str, Any] = {"@@locale": lang.replace("-", "_")}
    out.update(doc.meta.get("globals") or {})
    for r in doc.lang_rows(lang):
        out[r.key] = _icu_value(r, r.values[lang])
        if lang == doc.base_lang:
            attrs: dict[str, Any] = {}
            if r.description:
                attrs["description"] = r.description
            attrs.update(r.meta.get("arb") or {})
            if attrs:
                out[f"@{r.key}"] = attrs
    return _dump(out)


def sniff(data: bytes) -> str | None:
    """Best JSON flavour for an uploaded .json file."""
    try:
        obj = json.loads(decode(data))
    except (json.JSONDecodeError, StringsFormatError):
        return None
    if not isinstance(obj, dict):
        return None
    if "sourceLanguage" in obj and isinstance(obj.get("strings"), dict):
        return "xcstrings"
    if "@@locale" in obj or any(k.startswith("@") and k[1:] in obj for k in obj):
        return "arb"
    vals = list(obj.values())
    if vals and all(isinstance(v, dict) and "defaultMessage" in v for v in vals):
        return "formatjs"
    keys: list[str] = []

    def collect(o: dict[str, Any], prefix: str) -> None:
        for k, v in o.items():
            keys.append(f"{prefix}{k}")
            if isinstance(v, dict) and not is_plural_map(v):
                collect(v, f"{prefix}{k}.")

    collect(obj, "")
    if any(k.endswith("_other") for k in keys) and any(k.endswith("_one") for k in keys):
        return "i18next"
    if any(isinstance(v, dict) for v in vals):
        return "json_nested"
    return "json"
