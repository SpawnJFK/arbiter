from __future__ import annotations

import pytest
from fileproc_fixtures import XLIFF12, XLIFF20, joined, make_docx, plain, pseudo_targets, tagged
from lxml import etree
from roundtrip import identity

from arbiter.fileproc.base import FormatError, InlineCode, source_targets, to_tagged
from arbiter.fileproc.docx import DocxHandler
from arbiter.fileproc.jsonfmt import JsonHandler
from arbiter.fileproc.xliff import X2, X12, XliffHandler, export_xliff21, import_xliff_targets


def _targets12(data: bytes) -> dict[str, etree._Element]:
    root = etree.fromstring(data)
    return {tu.get("id"): tu.find(f"{{{X12}}}target") for tu in root.iter(f"{{{X12}}}trans-unit")}


def test_xliff12_extraction() -> None:
    result = XliffHandler().extract(XLIFF12.encode(), "en")
    units = {uid: segs for uid, segs, _ in tagged(result)}
    # no seg-source: we segment
    assert units["1:t1"] == ["Hello ⟦1⟧bold⟦/1⟧ world⟦2/⟧.", "Second sentence here."]
    # seg-source with one mrk: bx/ex become a pair
    assert units["1:t2"] == ["Click ⟦1⟧here⟦/1⟧ now."]
    # existing segmentation respected
    assert units["1:t3"] == ["First part.", "Second part."]
    assert units["1:t5"] == ["Value ⟦1/⟧ left"]
    assert "1:t4" not in units  # translate="no"
    t1 = next(u for u in result.units if u.unit_id == "1:t1")
    assert t1.notes == ["Shown on login"] and t1.context == "greeting"


def test_xliff12_roundtrip() -> None:
    data = XLIFF12.encode()
    merged, first = identity(XliffHandler(), data)
    targets = _targets12(merged)
    assert etree.tostring(targets["t1"], encoding="unicode").count('<g id="1">bold</g>') == 1
    h = XliffHandler()
    out = h.merge(data, pseudo_targets(first), "de")
    assert tagged(h.extract(out, "en")) == tagged(first)
    t = _targets12(out)
    xml = {k: etree.tostring(v, encoding="unicode") for k, v in t.items() if v is not None}
    assert "[[HELLO ]]<g" in xml["t1"] and "<x" in xml["t1"] and "[[SECOND SENTENCE HERE.]]" in xml["t1"]
    assert '<bx id="3" rid="1"/>[[HERE]]<ex id="4" rid="1"/>' in xml["t2"]
    assert (
        '<mrk mtype="seg" mid="1">[[FIRST PART.]]</mrk> <mrk mtype="seg" mid="2">[[SECOND PART.]]</mrk>'
        in xml["t3"]
    )
    assert "t4" not in xml or t["t4"] is None
    assert b'target-language="de"' in out
    assert import_xliff_targets(out)["t3"] == [["[[FIRST PART.]]"], ["[[SECOND PART.]]"]]


def test_xliff20_roundtrip() -> None:
    data = XLIFF20.encode()
    h = XliffHandler()
    result = h.extract(data, "en")
    units = {uid: segs for uid, segs, _ in tagged(result)}
    assert units["1:u1"] == ["Hello ⟦1⟧bold⟦/1⟧ and ⟦2/⟧ end.", "Second ⟦3⟧marked⟦/3⟧ segment."]
    assert units["1:u3"] == ["Already ⟦1⟧done⟦/1⟧."]
    assert "1:u2" not in units
    assert result.units[0].segments[0].trailing_ws == " "
    identity(h, data)
    out = h.merge(data, pseudo_targets(result), "fr")
    root = etree.fromstring(out)
    assert root.get("trgLang") == "fr"
    segs = list(root.iter(f"{{{X2}}}segment"))
    tgt = [
        etree.tostring(s.find(f"{{{X2}}}target"), encoding="unicode")
        for s in segs
        if s.find(f"{{{X2}}}target") is not None
    ]
    assert any('<pc id="1">[[BOLD]]</pc>' in t and '<ph id="2"/>' in t for t in tgt)
    assert any('<sc id="3"/>[[MARKED]]<ec startRef="3"/>' in t for t in tgt)
    assert any('<mrk id="m1" type="term">[[DONE]]</mrk>' in t for t in tgt)
    assert all(s.get("state") == "translated" for s in segs if s.find(f"{{{X2}}}target") is not None)
    assert len(root.findall(f".//{{{X2}}}target")) == 3  # old target replaced, not duplicated


def test_xliff_code_reorder_and_unknown() -> None:
    data = XLIFF20.encode()
    h = XliffHandler()
    result = h.extract(data, "en")
    unit = result.units[0]
    seg0 = unit.segments[0].content
    o, c, ph = [x for x in seg0 if isinstance(x, InlineCode)]
    targets = source_targets(result)
    targets[unit.unit_id] = [[ph, " zuerst, dann ", o, "fett", c, "."], unit.segments[1].content]
    out = h.merge(data, targets, "de")
    assert b'<target><ph id="2"/> zuerst, dann <pc id="1">fett</pc>.</target>' in out
    targets[unit.unit_id] = [["x", InlineCode("42", "standalone")], unit.segments[1].content]
    with pytest.raises(FormatError):
        h.merge(data, targets, "de")


def test_export_import_any_job() -> None:
    docx_data = make_docx()
    dh = DocxHandler()
    result = dh.extract(docx_data, "en")
    targets = pseudo_targets(result)
    xlf = export_xliff21(result, targets, "en", "de", "report.docx")
    root = etree.fromstring(xlf)
    assert root.get("version") == "2.1" and root.tag == f"{{{X2}}}xliff"
    # The exported file is itself a valid input for the XLIFF handler.
    reread = XliffHandler().extract(xlf, "en")
    assert [plain(joined(u)) for u in reread.units] == [plain(joined(u)) for u in result.units]
    back = import_xliff_targets(xlf)
    assert set(back) == {u.unit_id for u in result.units}
    for uid, segs in targets.items():
        assert [to_tagged(s) for s in back[uid]] == [to_tagged(s) for s in segs]
    # The original markup travels in originalData.
    bold = next(
        c for s in back["word/document.xml#0"] for c in s if isinstance(c, InlineCode) and c.kind == "open"
    )
    assert "<w:b/>" in bold.original
    merged = dh.merge(docx_data, back, "de")
    again = {u.unit_id: plain(joined(u)) for u in dh.extract(merged, "en").units}
    assert again["word/document.xml#0"].startswith("[[THIS IS ]][[IMPORTANT]]")


def test_export_without_targets_and_partial_import() -> None:
    data = b'{"a": "Hello {name}", "b": "Bye"}'
    result = JsonHandler().extract(data, "en")
    xlf = export_xliff21(result, None, "en", "sr", "app.json")
    assert b"<target" not in xlf
    assert import_xliff_targets(xlf) == {}
    xlf2 = export_xliff21(
        result, {"/a": [["Zdravo ", result.units[0].segments[0].content[1]]]}, "en", "sr", "app.json"
    )
    back = import_xliff_targets(xlf2)
    assert list(back) == ["/a"]
    out = JsonHandler().merge(data, back, "sr")
    assert out == b'{"a": "Zdravo {name}", "b": "Bye"}'


def test_not_xliff() -> None:
    with pytest.raises(FormatError):
        XliffHandler().extract(b"<root/>", "en")
    with pytest.raises(FormatError):
        XliffHandler().extract(b"<xliff", "en")
