"""Live preview of a job's target document as one self-contained HTML page (for an iframe).

html      the original page merged with the current targets
markdown  merged, then rendered by a minimal Markdown renderer (headings, lists, emphasis,
          code, links, paragraphs)
docx      merged, then rendered by a minimal paragraph renderer (headings, bold/italic runs,
          tables, line breaks)
others    a side-by-side source/target table

Segments without a translation show their source, so the layout is always complete.
The page is served with a CSP that forbids scripts and remote loads (sandboxed preview).
"""

from __future__ import annotations

import html
import re
import zipfile
from io import BytesIO
from typing import Any

from lxml import etree

from arbiter.fileproc.base import FormatError
from arbiter.fileproc.registry import get_handler
from arbiter.pipeline.units import target_map
from arbiter.tms import tagged

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
RICH_FORMATS = ("html", "markdown", "docx")
_STYLE = (
    "body{font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;max-width:860px;margin:24px auto;"
    "padding:0 20px;color:#1f2328}table{border-collapse:collapse;width:100%}td,th{border:1px solid #d0d7de;"
    "padding:6px 8px;vertical-align:top;text-align:left}th{background:#f6f8fa}code,pre{background:#f6f8fa;"
    "border-radius:4px}pre{padding:10px;overflow:auto}.muted{color:#6e7781}.src{color:#57606a}"
)


def _page(body: str, lang: str, title: str) -> str:
    return (
        f'<!doctype html><html lang="{html.escape(lang)}"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>{body}</body></html>"
    )


def render(filename: str, original: bytes, segments: list[Any], target_lang: str) -> tuple[str, str]:
    """Returns (html, mode) with mode rich | side_by_side."""
    handler = get_handler(filename)
    if handler.name in RICH_FORMATS:
        try:
            merged = handler.merge(original, target_map(segments), target_lang)
        except (FormatError, ValueError, KeyError):
            merged = None
        if merged is not None:
            if handler.name == "html":
                return merged.decode("utf-8", errors="replace"), "rich"
            if handler.name == "markdown":
                text = merged.decode("utf-8", errors="replace")
                return _page(markdown_to_html(text), target_lang, filename), "rich"
            return _page(docx_to_html(merged), target_lang, filename), "rich"
    return _page(side_by_side(segments), target_lang, filename), "side_by_side"


def side_by_side(segments: list[Any]) -> str:
    rows = ["<table><tr><th>#</th><th>Source</th><th>Target</th></tr>"]
    for s in sorted(segments, key=lambda x: x.seq):
        tgt = tagged.plain(s.target_tagged) if s.target_tagged else ""
        cell = html.escape(tgt) if tgt else f'<span class="muted">{html.escape(s.source_plain)}</span>'
        rows.append(
            f"<tr><td class='muted'>{s.seq + 1}</td><td class='src'>{html.escape(s.source_plain)}</td>"
            f"<td>{cell}</td></tr>"
        )
    rows.append("</table>")
    return "".join(rows)


# --------------------------------------------------------------------------- markdown

_LINK = re.compile(r"\[([^\]]+)\]\(((?:https?://|mailto:)[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITAL = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])|(?<![_\w])_(?!\s)(.+?)(?<!\s)_(?![_\w])")
_CODE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    codes: list[str] = []

    def keep(m: re.Match[str]) -> str:
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE.sub(keep, text)
    out = html.escape(text, quote=False)
    out = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out)
    out = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", out)
    out = _ITAL.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


def markdown_to_html(text: str) -> str:
    out: list[str] = []
    para: list[str] = []
    list_tag: str | None = None
    in_code = False
    code: list[str] = []

    def close_para() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
                code.clear()
                in_code = False
            else:
                close_para()
                close_list()
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            close_para()
            close_list()
            continue
        h = re.match(r"(#{1,6})\s+(.*)", stripped)
        if h:
            close_para()
            close_list()
            level = len(h.group(1))
            out.append(f"<h{level}>{_inline(h.group(2).rstrip('#').strip())}</h{level}>")
            continue
        li = re.match(r"([-*+]|\d+[.)])\s+(.*)", stripped)
        if li:
            close_para()
            tag = "ol" if li.group(1)[0].isdigit() else "ul"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{_inline(li.group(2))}</li>")
            continue
        if stripped.startswith(">"):
            close_para()
            close_list()
            out.append(f"<blockquote>{_inline(stripped.lstrip('> '))}</blockquote>")
            continue
        close_list()
        para.append(stripped)
    if in_code:
        out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
    close_para()
    close_list()
    return "".join(out)


# --------------------------------------------------------------------------- docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(name: str) -> str:
    return f"{{{W}}}{name}"


def _on(rpr: Any, name: str) -> bool:
    if rpr is None:
        return False
    el = rpr.find(_w(name))
    return el is not None and el.get(_w("val"), "true") not in ("0", "false", "none")


def _paragraph(p: Any) -> str:
    parts: list[str] = []
    for r in p.iter(_w("r")):
        rpr = r.find(_w("rPr"))
        buf: list[str] = []
        for child in r:
            if child.tag == _w("t"):
                buf.append(html.escape(child.text or ""))
            elif child.tag == _w("tab"):
                buf.append("&emsp;")
            elif child.tag in (_w("br"), _w("cr")):
                buf.append("<br>")
        text = "".join(buf)
        if not text:
            continue
        if _on(rpr, "b"):
            text = f"<strong>{text}</strong>"
        if _on(rpr, "i"):
            text = f"<em>{text}</em>"
        if _on(rpr, "u"):
            text = f"<u>{text}</u>"
        parts.append(text)
    body = "".join(parts)
    style_el = p.find(f"{_w('pPr')}/{_w('pStyle')}")
    style = (style_el.get(_w("val")) if style_el is not None else "") or ""
    m = re.match(r"(?i)heading\s*([1-6])", style)
    if m:
        return f"<h{m.group(1)}>{body}</h{m.group(1)}>"
    if style.lower() == "title":
        return f"<h1>{body}</h1>"
    if p.find(f"{_w('pPr')}/{_w('numPr')}") is not None:
        return f"<p>&bull; {body}</p>"
    return f"<p>{body or '&nbsp;'}</p>"


def _table(tbl: Any) -> str:
    rows = []
    for tr in tbl.findall(_w("tr")):
        cells = []
        for tc in tr.findall(_w("tc")):
            cells.append("<td>" + "".join(_paragraph(p) for p in tc.findall(_w("p"))) + "</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def docx_to_html(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(xml, parser)
    body = root.find(_w("body"))
    if body is None:
        return ""
    out: list[str] = []
    for el in body:
        if el.tag == _w("p"):
            out.append(_paragraph(el))
        elif el.tag == _w("tbl"):
            out.append(_table(el))
    return "".join(out)
