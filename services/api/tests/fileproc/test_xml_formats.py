from __future__ import annotations

import pytest
from extra_fixtures import ANDROID, DITA_TASK, DITAMAP, XML_DOC
from fileproc_fixtures import joined, plain, tagged
from lxml import etree
from roundtrip import identity, translation

from arbiter.fileproc.base import FormatError, InlineCode, source_targets
from arbiter.fileproc.registry import detect_and_extract, get_handler
from arbiter.fileproc.xmlfmt import DitaHandler, XmlHandler, XmlRules, android_decode, android_encode

RULES = {"rules": {"exclude": ["code"]}}


def _units(result) -> dict:  # noqa: ANN001
    return {uid: segs for uid, segs, _ in tagged(result)}


# --------------------------------------------------------------------------- generic XML


def test_xml_extraction_with_its_and_upload_rules() -> None:
    h = XmlHandler().configure(RULES)
    result = h.extract(XML_DOC, "en")
    units = _units(result)
    assert units["/manual/title#0"] == ["Getting started"]
    assert units["/manual/section/para[1]#0"] == ["Press the ⟦1⟧red⟦/1⟧ button.", "Then wait ⟦2/⟧ seconds."]
    assert units["/manual/section/para[3]#0"] == ["Model ⟦1/⟧ is new & improved."]  # its:translateRule //sku
    assert units["/manual/section/list/item#0"] == ["⟦1⟧Boil⟦/1⟧"]  # its:withinTextRule
    assert units["/manual/section/warning#0"] == ["Do not touch the ⟦1/⟧ lid."]  # comment kept as a code
    assert units["/manual/section/figure@caption"] == ["A blue kettle"]  # ITS rule on an attribute
    assert units["/manual/section/figure@alt"] == ["Kettle photo"]  # default translatable attribute
    texts = " ".join(plain(joined(u)) for u in result.units)
    for hidden in ("Do not translate this", "print(1)", "AB-12", "fig1", "k.png"):
        assert hidden not in texts
    notes = {u.unit_id: u.notes for u in result.units}
    assert notes["/manual/section/para[3]#0"] == ["Keep it short"]
    assert notes["/manual/section/warning#0"] == ["Legal text, keep the tone."]


def test_xml_identity_and_translation() -> None:
    h = XmlHandler().configure(RULES)
    merged, _ = identity(h, XML_DOC)
    assert merged == XML_DOC
    out, _, _ = translation(h, XML_DOC)
    text = out.decode()
    assert text.startswith(
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Product manual, fictional -->\n<manual'
    )
    assert 'xml:lang="de"' in text
    assert '<para>[[PRESS THE ]]<em>[[RED]]</em>[[ BUTTON.]] [[THEN WAIT ]]<ref target="x"/>' in text
    assert "<sku>AB-12</sku>[[ IS NEW &amp; IMPROVED.]]" in text
    assert (
        "<code>print(1)</code>" in text and '<para its:translate="no">Do not translate this.</para>' in text
    )
    assert "[[DO NOT TOUCH THE ]]<!-- hot -->[[ LID.]]" in text
    assert 'caption="[[A BLUE KETTLE]]"' in text and 'id="fig1"' in text
    assert text.endswith("</manual>\n")


def test_xml_reorder_inline_codes() -> None:
    data = b"<doc><p>Click <b>Save</b> then <i>Close</i>.</p></doc>"
    h = XmlHandler()
    result = h.extract(data, "en")
    o1, c1, o2, c2 = [c for c in result.units[0].segments[0].content if isinstance(c, InlineCode)]
    out = h.merge(data, {"/doc/p#0": [[o2, "Schliessen", c2, " nach ", o1, "Speichern", c1, "."]]}, "de")
    assert out == b"<doc><p><i>Schliessen</i> nach <b>Speichern</b>.</p></doc>"


def test_xml_rules_selectors_and_precedence() -> None:
    data = b"""<?xml version="1.0"?>
<book xmlns:k="urn:kettle">
  <k:meta><k:label>Visible label</k:label><k:id>X-1</k:id></k:meta>
  <chapter status="draft"><heading>Chapter one</heading><body>Text with <var>name</var> inside.</body></chapter>
  <chapter status="final"><heading>Chapter two</heading></chapter>
  <img src="a.png" desc="A kettle on a table"/>
</book>
"""
    options = {
        "rules": {
            "namespaces": {"k": "urn:kettle"},
            "exclude": ["k:meta", "//chapter[@status='draft']"],
            "include": ["k:label"],
            "protect": ["var"],
            "attributes": ["img@desc"],
        }
    }
    result = detect_and_extract("book.xml", data, "en", options)
    texts = [plain(joined(u)) for u in result.units]
    assert texts == ["Visible label", "Chapter two", "A kettle on a table"]
    # Without the exclusion the protected element stays whole inside the flow.
    open_rules = detect_and_extract("book.xml", data, "en", {"rules": {"protect": ["var"]}})
    body = next(u for u in open_rules.units if "body" in u.unit_id)
    assert [to for to in (c.original for c in body.segments[0].content if isinstance(c, InlineCode))] == [
        "<var>name</var>"
    ]


@pytest.mark.parametrize(
    "rules,message",
    [
        ({"skip": ["x"]}, "unknown setting 'skip'"),
        ({"exclude": "["}, "invalid selector"),
        ({"exclude": ["k:meta"]}, "without declaring it"),
        ({"exclude": [3]}, "list of selectors"),
        ({"namespaces": ["k"]}, "map prefixes"),
        ("not an object", "must be a JSON object"),
        ({"attributes": ["@@"]}, "invalid attribute selector"),
    ],
)
def test_xml_rules_validation(rules: object, message: str) -> None:
    with pytest.raises(FormatError, match=message):
        XmlHandler().configure({"rules": rules}).extract(b"<a><b>Some text here</b></a>", "en")


def test_xml_options_validation() -> None:
    with pytest.raises(FormatError, match="Unknown option"):
        get_handler("a.xml", {"rule": {}})
    with pytest.raises(FormatError, match="Unknown XML dialect"):
        get_handler("a.xml", {"dialect": "svg"})
    assert XmlRules.from_options(None) == XmlRules()


def test_xml_entities_are_not_expanded() -> None:
    data = (
        b'<?xml version="1.0"?>\n<!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>\n'
        b"<d><p>Hello &b; world</p></d>\n"
    )
    h = XmlHandler()
    result = h.extract(data, "en")
    assert tagged(result)[0][1] == ["Hello ⟦1/⟧ world"]
    assert identity(h, data)[0] == data
    out, _, _ = translation(h, data)
    assert b"[[HELLO ]]&b;[[ WORLD]]" in out and b'<!ENTITY a "aaaaaaaaaa">' in out


def test_xml_utf16_round_trip() -> None:
    text = '<?xml version="1.0" encoding="UTF-16"?>\n<doc><p>Grüße aus der Küche</p></doc>\n'
    data = text.encode("utf-16")
    h = XmlHandler()
    assert identity(h, data)[0] == data
    out, _, _ = translation(h, data)
    assert out.startswith(b"\xff\xfe") and "[[GRÜSSE AUS DER KÜCHE]]" in out.decode("utf-16")


def test_xml_damaged_refused() -> None:
    with pytest.raises(FormatError, match="not well-formed"):
        detect_and_extract("broken.xml", b"<a><b>text</a>", "en")


# --------------------------------------------------------------------------- DITA


def test_dita_task() -> None:
    result = DitaHandler().extract(DITA_TASK, "en")
    units = _units(result)
    assert units["/task/title#0"] == ["Installing the ⟦1⟧Kettle⟦/1⟧ app"]
    assert units["/task/taskbody/steps/step/cmd#0"] == ["Open ⟦1⟧Settings⟦/1⟧ and run ⟦2/⟧."]
    assert units["/task/taskbody/steps/step/info/p#0"] == ["This takes a minute.⟦1/⟧"]
    assert units["/task/taskbody/steps/step/info/p/fn#0"] == [
        "Depends on your network."
    ]  # fn is its own unit
    assert units["/task/taskbody/result/p[2]#0"] == ["Done. ⟦1⟧⟦2⟧Success icon⟦/2⟧⟦/1⟧"]
    texts = " ".join(plain(joined(u)) for u in result.units)
    for hidden in ("INTERNAL-ONLY", "Check the wording", "sudo apt", "kettle --install"):
        assert hidden not in texts
    merged, _ = identity(DitaHandler(), DITA_TASK)
    assert merged == DITA_TASK
    out, _, _ = translation(DitaHandler(), DITA_TASK)
    text = out.decode()
    assert '<!DOCTYPE task PUBLIC "-//OASIS//DTD DITA Task//EN" "task.dtd">' in text
    assert '<task id="install" xml:lang="de">' in text
    assert "<codeph>kettle --install</codeph>" in text and "<fn>[[DEPENDS ON YOUR NETWORK.]]</fn>" in text


def test_ditamap_and_detection() -> None:
    result = DitaHandler().extract(DITAMAP, "en")
    assert _units(result) == {
        "/map/title#0": ["Kettle user guide"],
        "/map/topicref[1]/topicmeta/navtitle#0": ["Install"],
        "/map/topicref[1]/topicmeta/shortdesc#0": ["Set up in minutes."],
        "/map/topicref[1]@navtitle": ["Installing the app"],
    }
    translation(DitaHandler(), DITAMAP)
    assert get_handler("guide.ditamap").name == "dita"
    # A DITA topic saved as .xml is recognised by its doctype.
    as_xml = detect_and_extract("install.xml", DITA_TASK, "en")
    assert "kettle --install" not in " ".join(plain(joined(u)) for u in as_xml.units)


# --------------------------------------------------------------------------- Android strings.xml


def test_android_extraction() -> None:
    result = XmlHandler().extract(ANDROID, "en")
    units = _units(result)
    assert list(units) == [
        "string:welcome",
        "string:multi",
        "string:at_sign",
        "string:cdata",
        "string-array:modes[0]",
        "string-array:modes[1]",
        "plurals:cups[one]",
        "plurals:cups[other]",
    ]
    assert units["string:welcome"] == ["Welcome, ⟦1/⟧! You're in."]
    assert units["string:multi"] == ['Line one⟦1/⟧Line two with ⟦2⟧bold⟦/2⟧ & "quotes"']
    assert units["string:at_sign"] == ["@ mentions are on"]
    assert units["string:cdata"] == ["Tap ⟦1/⟧here⟦2/⟧ now"]
    assert units["plurals:cups[one]"] == ["⟦1/⟧ cup"]
    by_id = {u.unit_id: u for u in result.units}
    assert by_id["string:welcome"].notes == ["Greeting on the home screen"]
    assert by_id["plurals:cups[other]"].notes == ["Plural form 'other'."]
    assert by_id["string:welcome"].context == "key:welcome"
    assert all(len(u.segments) == 1 for u in result.units)


def test_android_identity_and_translation() -> None:
    merged, _ = identity(XmlHandler(), ANDROID)
    assert merged == ANDROID
    out, _, _ = translation(XmlHandler(), ANDROID)
    text = out.decode()
    assert '<xliff:g id="name" example="Ana">%1$s</xliff:g>[[! YOU\\\'RE IN.]]' in text
    assert '[[LINE ONE]]\\n[[LINE TWO WITH ]]<b>[[BOLD]]</b>[[ &amp; \\"QUOTES\\"]]' in text
    assert '<string name="app_name" translatable="false">Kettle</string>' in text
    assert '<integer name="max_cups">8</integer>' in text


def test_android_escapes_on_write() -> None:
    result = XmlHandler().extract(ANDROID, "en")
    targets = source_targets(result)
    targets["string:at_sign"] = [["@Erwähnungen sind 'an'"]]
    out = XmlHandler().merge(ANDROID, targets, "de").decode()
    assert "<string name=\"at_sign\">\\@Erwähnungen sind \\'an\\'</string>" in out
    again = {u.unit_id: u for u in XmlHandler().extract(out.encode(), "de").units}
    assert plain(joined(again["string:at_sign"])) == "@Erwähnungen sind 'an'"


def test_android_codec_round_trip() -> None:
    for text in ['It\'s "fine"', "back\\slash", "?question", "@mention", "tab\there"]:
        encoded = android_encode(text, True)
        decoded = android_decode(encoded)
        rebuilt = "".join(
            r if isinstance(r, str) else {"\\n": "\n", "\\t": "\t"}.get(r.original, r.original)
            for r in decoded
        )
        assert rebuilt == text, (text, encoded, decoded)
    assert [r for r in android_decode("Save %1$s now") if isinstance(r, InlineCode)][0].original == "%1$s"


def test_android_forced_generic_dialect() -> None:
    generic = get_handler("strings.xml", {"dialect": "generic"}).extract(ANDROID, "en")
    assert any("/resources/string" in u.unit_id for u in generic.units)
    tree = etree.fromstring(ANDROID)
    assert tree.tag == "resources"
