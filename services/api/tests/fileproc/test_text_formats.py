from __future__ import annotations

import json

import lxml.html
import pytest
from fileproc_fixtures import (
    CSV,
    HTML,
    JSON_DOC,
    MARKDOWN,
    PO,
    PO_TRANSLATED,
    TXT,
    joined,
    json_bytes,
    plain,
    pseudo_targets,
    tagged,
)
from roundtrip import identity, translation

from arbiter.fileproc.base import FormatError, InlineCode, source_targets, to_tagged
from arbiter.fileproc.html import HtmlHandler
from arbiter.fileproc.jsonfmt import JsonHandler
from arbiter.fileproc.markdown import MarkdownHandler
from arbiter.fileproc.po import PoHandler
from arbiter.fileproc.text import CsvHandler, TextHandler

# --------------------------------------------------------------------------- HTML


def html_signature(data: bytes) -> list[tuple]:
    root = lxml.html.document_fromstring(data.decode())
    return [(el.tag, sorted(el.attrib.items()), el.text, el.tail) for el in root.iter()]


def test_html_extraction() -> None:
    result = HtmlHandler().extract(HTML.encode(), "en")
    units = {uid: segs for uid, segs, _ in tagged(result)}
    assert units["/html/head/title#0"] == ["Arbiter test page"]
    assert units["/html/body/h1#0"] == ["Welcome & hello"]
    assert units["/html/body/p[1]#0"] == [
        "This is ⟦1⟧bold⟦/1⟧ and ⟦2⟧a link⟦/2⟧.⟦3/⟧Next line with ⟦4/⟧ picture.",
        "Another sentence!",
    ]
    assert units["/html/body/div/p#0"] == ["Nested paragraph"]
    assert units["/html/body/ul/li[1]#0"] == ["First ⟦1⟧item⟦/1⟧"]
    assert units["/html/body/p[4]#0"] == ["Code like ⟦1⟧print()⟦/1⟧ and ⟦2/⟧ inline."]
    assert units["/html/head/meta[2]@content"] == ["A page used to test HTML extraction"]
    assert units["/html/body/p[1]/img@alt"] == ["A cat"]
    assert units["/html/body/form/input[1]@placeholder"] == ["Your name"]
    assert units["/html/body/form/input[2]@value"] == ["Send"]
    assert units["/html/body/p[5]@title"] == ["Tooltip text"]
    texts = " ".join(plain(joined(u)) for u in result.units)
    for hidden in ("preformatted", "Brand name", "Also stays", "do not translate", "color: red"):
        assert hidden not in texts
    link = next(c for c in result.units[2].segments[0].content if isinstance(c, InlineCode) and c.display == "<a>")
    assert link.original == '<a href="/docs" class="x">'


def test_html_identity() -> None:
    data = HTML.encode()
    merged, _ = identity(HtmlHandler(), data)
    assert merged == data
    forced, _ = identity(HtmlHandler(rewrite_unchanged=True), data)
    assert html_signature(forced) == html_signature(data)
    assert forced.decode().startswith("<!DOCTYPE html>")


def test_html_translation() -> None:
    merged, _, _ = translation(HtmlHandler(), HTML.encode())
    out = merged.decode()
    assert '<html lang="de">' in out
    assert '<b>[[BOLD]]</b>' in out and '<a href="/docs" class="x">[[A LINK]]</a>' in out
    assert 'alt="[[A CAT]]"' in out and 'placeholder="[[YOUR NAME]]"' in out
    assert '<span class="notranslate">ACME</span>' in out
    assert "preformatted, not translated" in out and 'var greeting = "do not translate";' in out
    assert 'content="[[A PAGE USED TO TEST HTML EXTRACTION]]"' in out


def test_html_fragment_and_reorder() -> None:
    data = b"<p>Press <kbd>Ctrl</kbd> and <kbd>C</kbd> now.</p>\n"
    h = HtmlHandler()
    result = h.extract(data, "en")
    assert tagged(result)[0][1] == ["Press ⟦1⟧Ctrl⟦/1⟧ and ⟦2⟧C⟦/2⟧ now."]
    seg = result.units[0].segments[0].content
    o1, c1, o2, c2 = [c for c in seg if isinstance(c, InlineCode)]
    targets = {result.units[0].unit_id: [["Drücke ", o2, "C", c2, " mit ", o1, "Strg", c1, "."]]}
    out = h.merge(data, targets, "de")
    assert out == "<p>Drücke <kbd>C</kbd> mit <kbd>Strg</kbd>.</p>\n".encode()


# --------------------------------------------------------------------------- Markdown


def test_markdown_extraction() -> None:
    result = MarkdownHandler().extract(MARKDOWN.encode(), "en")
    units = {uid: segs for uid, segs, _ in tagged(result)}
    assert units["L5"] == ["Main ⟦1⟧title⟦/1⟧ here"]
    assert units["L7"][0] == "Some ⟦1⟧bold⟦/1⟧ text with ⟦2/⟧ and a ⟦3⟧link ⟦4⟧inside⟦/4⟧⟦/3⟧ here."
    assert units["L10"] == ["item one with ⟦1⟧alt text⟦/1⟧"]
    assert units["L20.c1"] == ["snake_case_name"]
    assert units["L28"] == ["Numbered 5 * 3 = 15 see ⟦1/⟧."]
    texts = " ".join(plain(joined(u)) for u in result.units)
    for hidden in ("Front matter", 'print("no")', "indented code", "Col B" + "x"):
        assert hidden not in texts
    link_close = result.units[1].segments[0].content
    closes = [c.original for c in link_close if isinstance(c, InlineCode) and c.kind == "close"]
    assert "](http://x.com/a_(b))" in closes


def test_markdown_identity_bytes() -> None:
    data = MARKDOWN.encode()
    merged, _ = identity(MarkdownHandler(), data)
    assert merged == data


def test_markdown_translation() -> None:
    # Square brackets are Markdown syntax, so the pseudo-translation uses other markers here.
    merged, _, _ = translation(MarkdownHandler(), MARKDOWN.encode(), left="‹‹", right="››")
    out = merged.decode()
    assert "# ‹‹MAIN ››*‹‹TITLE››*‹‹ HERE››" in out
    assert "[‹‹LINK ››**‹‹INSIDE››**](http://x.com/a_(b))" in out
    assert "![‹‹ALT TEXT››](img.png)" in out
    assert '```python\nprint("no")\n```' in out
    assert "title: Front matter is not translated" in out
    assert "|------|:-----:|" in out


# --------------------------------------------------------------------------- JSON


@pytest.mark.parametrize("indent", [None, 2, 4, "\t"])
def test_json_identity_bytes(indent: int | str | None) -> None:
    data = json_bytes(indent)
    merged, _ = identity(JsonHandler(), data)
    assert merged == data


def test_json_placeholders_and_icu() -> None:
    result = JsonHandler().extract(json_bytes(2), "en")
    units = {uid: segs for uid, segs, _ in tagged(result)}
    assert units["/app/title"] == ["Hello ⟦1/⟧!"]
    assert units["/app/items"] == ["⟦1⟧⟦2⟧No items⟦/2⟧⟦3⟧⟦4/⟧ item⟦/3⟧⟦5⟧⟦6/⟧ items for ⟦7/⟧⟦/5⟧⟦/1⟧"]
    assert units["/app/gender"] == ["⟦1⟧⟦2⟧She liked it⟦/2⟧⟦3⟧He liked it⟦/3⟧⟦4⟧They liked it⟦/4⟧⟦/1⟧"]
    assert units["/app/fmt"] == ["Downloaded ⟦1/⟧ of ⟦2/⟧ files"]
    assert units["/app/tpl"] == ["Hi ⟦1/⟧, you have ⟦2/⟧ messages"]
    assert units["/app/a~1b~0c"] == ["Escaped key"]
    assert units["/app/list/4"] == ["Second entry"]
    for skipped in ("/app/url", "/app/number", "/empty"):
        assert skipped not in units
    assert all(u.context == f"key:{u.unit_id}" for u in result.units)


def test_json_translation_keeps_structure() -> None:
    merged, _, _ = translation(JsonHandler(), json_bytes(2))
    doc = json.loads(merged)
    assert list(doc["app"]) == list(JSON_DOC["app"])
    assert doc["app"]["title"] == "[[HELLO ]]{name}[[!]]"
    assert doc["app"]["items"] == (
        "{count, plural, =0 {[[NO ITEMS]]} one {#[[ ITEM]]} other {#[[ ITEMS FOR ]]{user}}}"
    )
    assert doc["app"]["fmt"] == "[[DOWNLOADED ]]%s[[ OF ]]%1$d[[ FILES]]"
    assert doc["app"]["tpl"] == "[[HI ]]{{user}}[[, YOU HAVE ]]${count}[[ MESSAGES]]"
    assert doc["app"]["url"] == "https://example.com"
    assert merged.decode().startswith('{\n  "app": {\n    "title"')


def test_json_placeholder_reorder_and_unknown() -> None:
    data = json.dumps({"msg": "From {start} to {end}"}).encode()
    h = JsonHandler()
    result = h.extract(data, "en")
    a, b = [c for c in result.units[0].segments[0].content if isinstance(c, InlineCode)]
    out = h.merge(data, {"/msg": [["Do ", b, " od ", a]]}, "sr")
    assert json.loads(out) == {"msg": "Do {end} od {start}"}
    with pytest.raises(FormatError):
        h.merge(data, {"/msg": [["x", InlineCode("9", "standalone", "{x}")]]}, "sr")
    with pytest.raises(FormatError, match="missing"):
        h.merge(data, {"/msg": [["Do ", b]]}, "sr")


def test_json_invalid() -> None:
    with pytest.raises(FormatError, match="not valid JSON"):
        JsonHandler().extract(b"{'a': 1}", "en")


# --------------------------------------------------------------------------- PO


def test_po_extraction() -> None:
    result = PoHandler().extract(PO.encode(), "en")
    units = {u.unit_id: u for u in result.units}
    assert len(units) == 3  # header, numeric-only and obsolete entries are skipped
    hello = units["e1"]
    assert hello.context == "greeting"
    assert [to_tagged(s.content) for s in hello.segments] == ["Hello ⟦1/⟧, welcome!"]
    assert hello.segments[0].trailing_ws == "\n"
    assert hello.notes == ["Shown on the start page", "Developer comment"]
    assert [to_tagged(s.content) for s in units["e2"].segments] == ["Long text that wraps over lines. Second ⟦1/⟧."]
    plural = units["e3"]
    assert [to_tagged(s.content) for s in plural.segments] == ["One file", "⟦1/⟧ files"]


def test_po_identity_bytes_on_translated_file() -> None:
    data = PO_TRANSLATED.encode()
    merged, _ = identity(PoHandler(), data)
    assert merged == data


def test_po_identity_on_template_only_touches_msgstr_and_header() -> None:
    data = PO.encode()
    merged, _ = identity(PoHandler(), data, lang="en")
    before = data.decode().splitlines()
    after = merged.decode().splitlines()
    removed = [line for line in before if line not in after]
    assert all(line.startswith(("msgstr", "#,", "#|", '"Language', '"Plural')) for line in removed), removed


def test_po_translation_plural_and_fuzzy() -> None:
    h = PoHandler()
    data = PO.encode()
    result = h.extract(data, "en")
    merged = h.merge(data, pseudo_targets(result), "sr")
    assert tagged(h.extract(merged, "en")) == tagged(result)  # msgids untouched
    out = merged.decode()
    assert "fuzzy" not in out and "#, python-format" in out and "#| msgid" not in out
    assert 'msgstr "[[HELLO ]]%(name)s[[, WELCOME!]]\\n"' in out
    assert 'msgstr[0] "[[ONE FILE]]"' in out
    assert 'msgstr[1] "%d[[ FILES]]"' in out and 'msgstr[2] "%d[[ FILES]]"' in out
    assert '"Language: sr\\n"' in out and "nplurals=3" in out
    assert '#~ msgstr "zastarelo"' in out


# --------------------------------------------------------------------------- TXT / CSV


def test_txt_roundtrips() -> None:
    data = TXT.encode()
    merged, result = identity(TextHandler(), data)
    assert merged == data
    assert [segs for _, segs, _ in tagged(result)][0] == [
        "First paragraph has two sentences.", "This is the second one.", "It continues here."
    ]
    assert result.units[1].leading_ws == "   "
    out, _, _ = translation(TextHandler(), data)
    text = out.decode()
    assert "\r\n\r\n   [[INDENTED SECOND PARAGRAPH!]]\r\n" in text
    assert text.endswith("[[LAST LINE WITHOUT NEWLINE]]")


def test_txt_legacy_encoding_falls_back_to_utf8() -> None:
    data = "Café au lait is tasty.\n".encode("cp1252")
    h = TextHandler()
    result = h.extract(data, "en")
    out = h.merge(data, {result.units[0].unit_id: [["Кафа са млеком је укусна."]]}, "sr")
    assert out.decode("utf-8-sig") == "Кафа са млеком је укусна.\n"


def test_csv_roundtrips() -> None:
    data = CSV.encode()
    merged, result = identity(CsvHandler(), data)
    assert merged == data
    units = {uid: segs for uid, segs, _ in tagged(result)}
    assert units["R2C3"] == ["Strong; dark roast"]
    assert units["R4C3"] == ['He said "hi"']
    assert "R4C2" not in units and "R2C1" not in units
    assert result.units[3].context == "column:name"
    out, _, _ = translation(CsvHandler(), data)
    text = out.decode()
    assert '1;[[COFFEE]];"[[STRONG; DARK ROAST]]"\r\n' in text
    assert '2;"[[TEA]]";[[GREEN TEA, MILD]]\r\n' in text
    assert '"[[HE SAID ""HI""]]"' in text


def test_csv_column_filter() -> None:
    result = CsvHandler(columns=["description"], skip_header=True).extract(CSV.encode(), "en")
    assert [u.unit_id for u in result.units] == ["R2C3", "R3C3", "R4C3"]


def test_source_targets_identity_for_all_text_formats() -> None:
    for handler, data in ((TextHandler(), TXT.encode()), (CsvHandler(), CSV.encode()),
                          (MarkdownHandler(), MARKDOWN.encode()), (JsonHandler(), json_bytes(2))):
        result = handler.extract(data, "en")
        assert handler.merge(data, source_targets(result), "en") == data
