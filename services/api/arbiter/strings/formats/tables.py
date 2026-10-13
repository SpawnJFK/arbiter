"""CSV and XLSX spreadsheets: one row per key (per form for plural and array keys).

Columns: key, namespace, form, description, max_length, then one column per language
(base first). `form` is empty for a plain string, a CLDR category for a plural form and an
index for an array item. Unknown columns are languages. The XLSX reader and writer are a
small OOXML implementation (inline strings out, shared or inline strings in), so the
production image needs no spreadsheet library.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.sax.saxutils import escape

from lxml import etree

from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError, decode

FIXED = ("key", "namespace", "form", "description", "max_length")
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _rows_to_doc(table: list[list[str]], base_lang: str) -> Doc:
    if not table:
        raise StringsFormatError("The spreadsheet is empty.")
    header = [h.strip() for h in table[0]]
    lower = [h.lower() for h in header]
    if "key" not in lower:
        raise StringsFormatError("The spreadsheet needs a `key` column in the first row.")
    idx = {name: lower.index(name) for name in FIXED if name in lower}
    langs = [(i, h) for i, h in enumerate(header) if h and h.lower() not in FIXED]
    doc = Doc(base_lang=base_lang, langs=[h for _, h in langs])
    rows: dict[tuple[str, str], KeyRow] = {}

    def cell(r: list[str], name: str) -> str:
        i = idx.get(name)
        return r[i].strip() if i is not None and i < len(r) else ""

    for n, r in enumerate(table[1:], start=2):
        key = cell(r, "key")
        if not key:
            continue
        ns, form = cell(r, "namespace"), cell(r, "form")
        row = rows.get((ns, key))
        if row is None:
            row = rows[(ns, key)] = KeyRow(key=key, namespace=ns)
            doc.rows.append(row)
            ml = cell(r, "max_length")
            row.max_length = int(ml) if ml.isdigit() else None
        row.description = row.description or cell(r, "description")
        if form:
            row.kind = "array" if form.isdigit() else "plural"
        for i, lang in langs:
            text = r[i] if i < len(r) else ""
            if text == "":
                continue
            if form:
                cur = row.values.setdefault(lang, {})
                if isinstance(cur, dict):
                    cur[form] = text
                else:
                    doc.warnings.append(f"row {n}: {key} mixes plain and form rows")
            else:
                row.values[lang] = text
    return doc


def _doc_to_rows(doc: Doc, langs: list[str]) -> list[list[str]]:
    out = [[*FIXED, *langs]]
    for r in doc.rows:
        base = r.values.get(doc.base_lang)
        common = [r.namespace]
        if r.kind == "string":
            out.append(
                [r.key, *common, "", r.description, str(r.max_length or "")]
                + [v if isinstance(v := r.values.get(lg), str) else "" for lg in langs]
            )
            continue
        forms: list[str] = list(base) if isinstance(base, dict) else []
        for lg in langs:
            v = r.values.get(lg)
            if isinstance(v, dict):
                forms += [k for k in v if k not in forms]
        for i, form in enumerate(forms):
            vals = []
            for lg in langs:
                v = r.values.get(lg)
                vals.append(v.get(form, "") if isinstance(v, dict) else "")
            out.append(
                [
                    r.key,
                    *common,
                    form,
                    r.description if i == 0 else "",
                    str(r.max_length or "") if i == 0 else "",
                ]
                + vals
            )
    return out


def _langs(doc: Doc, lang: str | None) -> list[str]:
    if doc.langs:
        return [doc.base_lang] + [lg for lg in doc.langs if lg != doc.base_lang]
    return [doc.base_lang] + ([lang] if lang and lang != doc.base_lang else [])


# ------------------------------------------------------------------ CSV


def parse_csv(data: bytes, lang: str, base_lang: str) -> Doc:
    text = decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]
    return _rows_to_doc(list(csv.reader(io.StringIO(text), dialect)), base_lang)


def render_csv(doc: Doc, lang: str | None = None) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for row in _doc_to_rows(doc, _langs(doc, lang)):
        w.writerow(row)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel opens UTF-8 correctly


# ------------------------------------------------------------------ XLSX

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def render_xlsx(doc: Doc, lang: str | None = None) -> bytes:
    rows = _doc_to_rows(doc, _langs(doc, lang))
    sheet = [f'<worksheet xmlns="{_NS}"><sheetData>']
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, val in enumerate(row):
            if val == "":
                continue
            v = escape(_BAD_XML.sub("", val))
            cells.append(f'<c r="{_col(ci)}{ri}" t="inlineStr"><is><t xml:space="preserve">{v}</t></is></c>')
        sheet.append(f'<row r="{ri}">{"".join(cells)}</row>')
    sheet.append("</sheetData></worksheet>")
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_RNS}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{_NS}" xmlns:r="{_RNS}"><sheets>'
            '<sheet name="Strings" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_RNS}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8"?>' + "".join(sheet),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


def _cell_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "A")
    n = 0
    for ch in letters.group(0) if letters else "A":
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def parse_xlsx(data: bytes, lang: str, base_lang: str) -> Doc:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        wb = etree.fromstring(z.read("xl/workbook.xml"), parser)
        rels = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"), parser)
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError):
        raise StringsFormatError("The file is not a valid XLSX workbook.") from None
    first = wb.find(f"{{{_NS}}}sheets/{{{_NS}}}sheet")
    if first is None:
        raise StringsFormatError("The workbook has no sheets.")
    rid = first.get(f"{{{_RNS}}}id")
    target = next((r.get("Target") for r in rels if r.get("Id") == rid), "worksheets/sheet1.xml")
    path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        sst = etree.fromstring(z.read("xl/sharedStrings.xml"), parser)
        shared = ["".join(si.itertext()) for si in sst.findall(f"{{{_NS}}}si")]
    try:
        ws = etree.fromstring(z.read(path), parser)
    except (KeyError, etree.XMLSyntaxError):
        raise StringsFormatError("The first sheet of the workbook cannot be read.") from None
    table: list[list[str]] = []
    for row in ws.iter(f"{{{_NS}}}row"):
        vals: list[str] = []
        for c in row.findall(f"{{{_NS}}}c"):
            i = _cell_index(c.get("r", ""))
            t = c.get("t")
            if t == "inlineStr":
                v = "".join(c.find(f"{{{_NS}}}is").itertext()) if c.find(f"{{{_NS}}}is") is not None else ""
            else:
                ve = c.find(f"{{{_NS}}}v")
                raw = ve.text if ve is not None and ve.text is not None else ""
                v = shared[int(raw)] if t == "s" and raw.isdigit() and int(raw) < len(shared) else raw
            while len(vals) < i:
                vals.append("")
            vals.append(v)
        table.append(vals)
    return _rows_to_doc(table, base_lang)
