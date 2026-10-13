"""XLIFF 1.2 and 2.1 for handing strings to translators working in a CAT tool, and back.

Structure (both versions): one <file> per export; one group per namespace (when the key has
one); a plural or array key is a group of units, one per form; every unit carries the key
name (1.2 resname, 2.1 name), the description as a note and max_length as maxwidth (1.2)
or a note with category "max_length" (2.1). Placeholders stay as plain text: CAT tools
protect them with their own regex rules, and our QA validates them on import.

Parse accepts both versions (and files written by other tools when units carry resname /
name, falling back to the unit id as key).
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError

NS12 = "urn:oasis:names:tc:xliff:document:1.2"
NS20 = "urn:oasis:names:tc:xliff:document:2.0"
_STATE_OUT_12 = {"approved": "final", "reviewed": "translated", "machine": "needs-review-translation"}
_STATE_OUT_20 = {"approved": "final", "reviewed": "reviewed", "machine": "translated"}
_STATE_IN = {
    "final": "approved",
    "signed-off": "approved",
    "reviewed": "reviewed",
    "translated": "reviewed",
    "needs-review-translation": "machine",
    "needs-translation": "untranslated",
    "new": "untranslated",
    "initial": "untranslated",
}


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True)


def _text(el: etree._Element | None) -> str | None:
    if el is None:
        return None
    return "".join(el.itertext())


def _local(el: Any) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def parse(data: bytes, lang: str, base_lang: str) -> Doc:
    try:
        root = etree.fromstring(data, _parser())
    except etree.XMLSyntaxError as e:
        raise StringsFormatError(f"The XLIFF file is not valid XML: {e.msg}") from None
    if _local(root) != "xliff":
        raise StringsFormatError("Not an XLIFF file.")
    v2 = root.get("version", "1.2").startswith("2")
    src_lang = root.get("srcLang") if v2 else None
    tgt_lang = root.get("trgLang") if v2 else None
    doc = Doc(base_lang=base_lang)
    found: set[str] = set()
    for f in (e for e in root if _local(e) == "file"):
        s_lang = src_lang or f.get("source-language") or base_lang
        t_lang = tgt_lang or f.get("target-language") or lang
        if s_lang.lower() != base_lang.lower():
            doc.warnings.append(f"source language {s_lang} differs from the project base {base_lang}")
        _walk(f, doc, v2, base_lang, t_lang, namespace="", found=found)
    doc.langs = sorted(found | {base_lang})
    return doc


def _unit_parts(unit: etree._Element, v2: bool) -> tuple[str | None, str | None, str | None, str, int | None]:
    """(source, target, state, note, maxwidth)"""
    note = ""
    maxw: int | None = None
    if v2:
        seg = next((e for e in unit if _local(e) == "segment"), None)
        src = _text(next((e for e in seg if _local(e) == "source"), None)) if seg is not None else None
        tgt = _text(next((e for e in seg if _local(e) == "target"), None)) if seg is not None else None
        state = seg.get("state") if seg is not None else None
        notes = next((e for e in unit if _local(e) == "notes"), None)
        for n in notes if notes is not None else []:
            if n.get("category") == "max_length" and (n.text or "").strip().isdigit():
                maxw = int((n.text or "").strip())
            elif _local(n) == "note":
                note = note or (n.text or "")
    else:
        src = _text(next((e for e in unit if _local(e) == "source"), None))
        tel = next((e for e in unit if _local(e) == "target"), None)
        tgt = _text(tel)
        state = tel.get("state") if tel is not None else None
        n = next((e for e in unit if _local(e) == "note"), None)
        note = (n.text or "") if n is not None else ""
        mw = unit.get("maxwidth")
        maxw = int(mw) if mw and mw.isdigit() else None
    return src, tgt, state, note, maxw


def _walk(
    parent: etree._Element, doc: Doc, v2: bool, base: str, tgt: str, *, namespace: str, found: set[str]
) -> None:
    container = parent if v2 else next((e for e in parent if _local(e) == "body"), parent)
    for el in container:
        tag = _local(el)
        if tag == "group":
            gtype = el.get("type" if v2 else "restype", "")
            gname = el.get("name" if v2 else "resname", "") or ""
            if gtype.endswith("plural") or gtype.endswith("array"):
                kind = "plural" if gtype.endswith("plural") else "array"
                row = KeyRow(key=gname, namespace=namespace, kind=kind)  # type: ignore[arg-type]
                src_forms: dict[str, str] = {}
                tgt_forms: dict[str, str] = {}
                states: set[str] = set()
                for u in (e for e in el if _local(e) == "unit" or _local(e) == "trans-unit"):
                    form = u.get("name" if v2 else "resname") or u.get("id", "")
                    s, t, st, note, maxw = _unit_parts(u, v2)
                    src_forms[form] = s or ""
                    if t:
                        tgt_forms[form] = t
                        states.add(_STATE_IN.get(st or "translated", "reviewed"))
                    row.description = row.description or note
                    row.max_length = row.max_length or maxw
                row.values[base] = src_forms
                if tgt_forms and tgt != base:
                    row.values[tgt] = tgt_forms
                    row.states[tgt] = (
                        "machine"
                        if "machine" in states
                        else "approved"
                        if states == {"approved"}
                        else "reviewed"
                    )
                    found.add(tgt)
                doc.rows.append(row)
            else:
                _walk(
                    el,
                    doc,
                    v2,
                    base,
                    tgt,
                    namespace=gname if gtype.endswith("namespace") else namespace,
                    found=found,
                )
        elif tag in ("unit", "trans-unit"):
            key = el.get("name" if v2 else "resname") or el.get("id", "")
            s, t, st, note, maxw = _unit_parts(el, v2)
            row = KeyRow(key=key, namespace=namespace, description=note, max_length=maxw)
            row.values[base] = s or ""
            if t and tgt != base:
                row.values[tgt] = t
                row.states[tgt] = _STATE_IN.get(st or "translated", "reviewed")
                found.add(tgt)
            doc.rows.append(row)


# ------------------------------------------------------------------ render


def _sub(parent: etree._Element, tag: str, text: str | None = None, **attrs: str) -> etree._Element:
    el = etree.SubElement(parent, tag, {k: v for k, v in attrs.items() if v is not None})
    if text is not None:
        el.text = text
    return el


def render(doc: Doc, lang: str, *, version: str = "1.2") -> bytes:
    v2 = version.startswith("2")
    base = doc.base_lang
    counter = {"u": 0, "g": 0}

    def nid(kind: str) -> str:
        counter[kind] += 1
        return f"{kind}{counter[kind]}"

    if v2:
        root = etree.Element(
            f"{{{NS20}}}xliff", nsmap={None: NS20}, version="2.1", srcLang=base, trgLang=lang
        )
        file_el = _sub(root, f"{{{NS20}}}file", id="f1")
        q = lambda t: f"{{{NS20}}}{t}"  # noqa: E731
    else:
        root = etree.Element(f"{{{NS12}}}xliff", nsmap={None: NS12}, version="1.2")
        f = _sub(root, f"{{{NS12}}}file", **{"source-language": base, "target-language": lang})
        f.set("datatype", "plaintext")
        f.set("original", "strings")
        file_el = _sub(f, f"{{{NS12}}}body")
        q = lambda t: f"{{{NS12}}}{t}"  # noqa: E731

    groups: dict[str, etree._Element] = {}

    def container(ns: str) -> etree._Element:
        if not ns:
            return file_el
        if ns not in groups:
            if v2:
                groups[ns] = _sub(file_el, q("group"), id=nid("g"), name=ns, type="arb:namespace")
            else:
                groups[ns] = _sub(file_el, q("group"), id=nid("g"), resname=ns, restype="x-namespace")
        return groups[ns]

    def unit(parent: etree._Element, name: str, src: str, tgt: str | None, state: str, row: KeyRow) -> None:
        if v2:
            u = _sub(parent, q("unit"), id=nid("u"), name=name)
            if row.description or row.max_length:
                notes = _sub(u, q("notes"))
                if row.description:
                    _sub(notes, q("note"), row.description)
                if row.max_length:
                    _sub(notes, q("note"), str(row.max_length), category="max_length")
            seg = _sub(u, q("segment"))
            if tgt:
                seg.set("state", _STATE_OUT_20.get(state, "translated"))
            _sub(seg, q("source"), src)
            if tgt is not None:
                _sub(seg, q("target"), tgt)
        else:
            u = _sub(parent, q("trans-unit"), id=nid("u"), resname=name)
            if row.max_length:
                u.set("maxwidth", str(row.max_length))
                u.set("size-unit", "char")
            _sub(u, q("source"), src)
            if tgt is not None:
                t = _sub(u, q("target"), tgt)
                t.set("state", _STATE_OUT_12.get(state, "translated") if tgt else "needs-translation")
            if row.description:
                _sub(u, q("note"), row.description)

    for r in doc.rows:
        if not r.translatable or base not in r.values:
            continue
        src = r.values[base]
        tv = r.values.get(lang) if lang != base else None
        state = r.states.get(lang, "machine")
        parent = container(r.namespace)
        if isinstance(src, dict):
            if v2:
                g = _sub(parent, q("group"), id=nid("g"), name=r.key, type=f"arb:{r.kind}")
            else:
                g = _sub(parent, q("group"), id=nid("g"), resname=r.key, restype=f"x-{r.kind}")
            tforms = tv if isinstance(tv, dict) else {}
            forms = list(src) + [k for k in tforms if k not in src]
            for form in forms:
                unit(g, form, src.get(form, src.get("other", "")), tforms.get(form, ""), state, r)
        else:
            unit(parent, r.key, src, tv if isinstance(tv, str) else "", state, r)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
