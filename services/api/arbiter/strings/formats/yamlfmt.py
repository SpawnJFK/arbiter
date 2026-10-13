"""Rails i18n YAML: `en: {users: {title: "Users"}}`.

The top-level key is the locale. Nested keys are joined with ".". A mapping whose keys
are CLDR categories and that includes `other` is a plural key (Rails pluralization);
a list of strings is an array key. Non-string scalars (numbers, booleans) are reported
and skipped: they are configuration, not copy. Comments and anchors are not kept on
render (YAML round trip is semantic, not byte identical).
"""

from __future__ import annotations

from typing import Any

import yaml

from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError, decode, is_plural_map


def parse(data: bytes, lang: str, base_lang: str) -> Doc:
    try:
        root = yaml.safe_load(decode(data))
    except yaml.YAMLError as e:
        raise StringsFormatError(f"The YAML file is not valid: {str(e).splitlines()[0]}") from None
    if not isinstance(root, dict):
        raise StringsFormatError("The YAML file must contain a mapping with the locale as its top key.")
    doc = Doc(base_lang=base_lang, langs=[lang])
    if len(root) == 1 and isinstance(next(iter(root.values())), dict):
        doc.meta["locale"] = str(next(iter(root)))
        body = next(iter(root.values()))
    else:
        body = root

    def walk(obj: dict[str, Any], prefix: str) -> None:
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, str):
                doc.rows.append(KeyRow(key=key, values={lang: v}))
            elif is_plural_map(v):
                doc.rows.append(
                    KeyRow(key=key, kind="plural", values={lang: {str(a): b for a, b in v.items()}})
                )
            elif isinstance(v, dict):
                walk(v, key)
            elif isinstance(v, list) and all(isinstance(x, str) for x in v):
                doc.rows.append(
                    KeyRow(key=key, kind="array", values={lang: {str(i): x for i, x in enumerate(v)}})
                )
            elif v is None:
                continue
            else:
                doc.warnings.append(f"{key}: non-text value skipped")

    walk(body, "")
    return doc


def render(doc: Doc, lang: str) -> bytes:
    body: dict[str, Any] = {}
    for r in doc.lang_rows(lang):
        v = r.values[lang]
        if r.kind == "array" and isinstance(v, dict):
            leaf: Any = [v[k] for k in sorted(v, key=lambda x: int(x) if x.isdigit() else 0)]
        elif r.kind == "plural" and isinstance(v, dict):
            leaf = {k: t for k, t in v.items() if not k.startswith("=")}
        else:
            leaf = v
        node = body
        parts = r.key.split(".")
        ok = True
        for p in parts[:-1]:
            nxt = node.setdefault(p, {})
            if not isinstance(nxt, dict):
                ok = False
                break
            node = nxt
        if ok and not isinstance(node.get(parts[-1]), dict):
            node[parts[-1]] = leaf
        else:
            body[r.key] = leaf
    locale = lang if lang != doc.base_lang else doc.meta.get("locale", lang)
    text = yaml.safe_dump(
        {locale: body}, allow_unicode=True, sort_keys=False, default_flow_style=False, width=4096
    )
    return text.encode("utf-8")
