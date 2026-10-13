from __future__ import annotations

import json

import pytest
from extra_fixtures import ARB, IOS_STRINGS, PROPERTIES, RESX, STRINGSDICT
from fileproc_fixtures import joined, plain, tagged
from roundtrip import identity, translation

from arbiter.fileproc.base import FormatError, source_targets
from arbiter.fileproc.registry import detect_and_extract
from arbiter.fileproc.resources import (
    ArbHandler,
    PropertiesHandler,
    ResxHandler,
    StringsdictHandler,
    StringsHandler,
)


def _units(result) -> dict:  # noqa: ANN001
    return {uid: segs for uid, segs, _ in tagged(result)}


# --------------------------------------------------------------------------- ARB


def test_arb() -> None:
    data = ARB.encode()
    result = ArbHandler().extract(data, "en")
    assert _units(result) == {
        "appTitle": ["Kettle"],
        "greeting": ["Hello ⟦1/⟧!"],
        "cups": ["⟦1⟧⟦2⟧No cups⟦/2⟧⟦3⟧One cup⟦/3⟧⟦4⟧⟦5/⟧ cups⟦/4⟧⟦/1⟧"],
    }
    notes = {u.unit_id: u.notes for u in result.units}
    assert notes["greeting"] == ["Greeting on the home screen", "{name} example: Ana"]
    assert identity(ArbHandler(), data)[0] == data
    out, _, _ = translation(ArbHandler(), data, target_lang="pt-BR")
    parsed = json.loads(out)
    assert parsed["@@locale"] == "pt_BR"
    assert parsed["greeting"] == "[[HELLO ]]{name}[[!]]"
    assert parsed["@greeting"]["description"] == "Greeting on the home screen"
    assert parsed["icon"] == "assets/kettle.png"
    with pytest.raises(FormatError, match="JSON object"):
        ArbHandler().extract(b'["a"]', "en")


# --------------------------------------------------------------------------- iOS .strings


def test_strings_extraction_and_round_trip() -> None:
    data = IOS_STRINGS.encode()
    result = StringsHandler().extract(data, "en")
    assert _units(result) == {
        "main.title": ["Kettle"],
        "button.start": ["Start boiling"],
        "greeting": ["Hello, ⟦1/⟧! You have ⟦2/⟧ cups."],
        "multiline": ['Line one⟦1/⟧Line "two"'],
        "legacyKey": ["Bare key works"],
    }
    notes = {u.unit_id: u.notes for u in result.units}
    assert notes["main.title"] == ["Title of the main screen"]
    assert notes["button.start"] == ["Button that starts boiling"]
    assert identity(StringsHandler(), data)[0] == data
    out, _, _ = translation(StringsHandler(), data)
    text = out.decode()
    assert '"greeting" = "[[HELLO, ]]%@[[! YOU HAVE ]]%1$d[[ CUPS.]]";' in text
    assert '"multiline" = "[[LINE ONE]]\\n[[LINE \\"TWO\\"]]";' in text
    assert '"number" = "42";' in text


def test_strings_utf16_and_errors() -> None:
    data = '"title" = "Kettle";\n'.encode("utf-16")
    assert identity(StringsHandler(), data)[0] == data
    out, _, _ = translation(StringsHandler(), data)
    assert out.startswith(b"\xff\xfe") and '"[[KETTLE]]"' in out.decode("utf-16")
    with pytest.raises(FormatError, match="line 2"):
        StringsHandler().extract(b'"a" = "b";\n"c" "d";\n', "en")


# --------------------------------------------------------------------------- .stringsdict


def test_stringsdict() -> None:
    result = StringsdictHandler().extract(STRINGSDICT, "en")
    assert _units(result) == {
        "cups_left/NSStringLocalizedFormatKey": ["You have ⟦1/⟧ left"],
        "cups_left/cups/one": ["⟦1/⟧ cup"],
        "cups_left/cups/other": ["⟦1/⟧ cups"],
    }
    assert identity(StringsdictHandler(), STRINGSDICT)[0] == STRINGSDICT
    out, _, _ = translation(StringsdictHandler(), STRINGSDICT)
    text = out.decode()
    assert "<string>[[YOU HAVE ]]%#@cups@[[ LEFT]]</string>" in text
    assert "<string>NSStringPluralRuleType</string>" in text
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist')
    with pytest.raises(FormatError, match="property list"):
        StringsdictHandler().extract(b"<plist><array/></plist>", "en")


# --------------------------------------------------------------------------- Java .properties


def test_properties_extraction() -> None:
    result = PropertiesHandler().extract(PROPERTIES.encode(), "en")
    assert _units(result) == {
        "app.title": ["Kettle"],
        "greeting": ["Hello ⟦1/⟧, welcome back!"],
        "long.text": ["This is a long text that continues on the next line."],
        "colon.key": ["Café is open"],
        "space.key": ["Water⟦1/⟧Tea⟦2/⟧Coffee"],
        "path": ["C:\\kettle"],
    }
    notes = {u.unit_id: u.notes for u in result.units}
    assert notes["app.title"] == ["Kettle app messages"]
    assert notes["greeting"] == ["Shown on the start screen"]


def test_properties_round_trip() -> None:
    data = PROPERTIES.encode()
    assert identity(PropertiesHandler(), data)[0] == data
    out, _, _ = translation(PropertiesHandler(), data)
    text = out.decode("ascii")  # an ASCII file stays ASCII: non-ASCII goes out as \\u escapes
    assert "long.text = [[THIS IS A LONG TEXT THAT CONTINUES ON THE NEXT LINE.]]\n" in text
    assert "colon.key: [[CAF\\u00c9 IS OPEN]]" in text
    assert "space.key [[WATER]]\\t[[TEA]]\\n[[COFFEE]]" in text
    assert "path=[[C:\\\\KETTLE]]" in text and "empty=\n" in text


def test_properties_encoding_rules() -> None:
    h = PropertiesHandler()
    raw = "title=Grüße\nlead=x\n".encode()
    result = h.extract(raw, "de")
    targets = source_targets(result)
    targets["title"] = [["Grüße 😀 aus Köln"]]
    targets["lead"] = [["  indented"]]
    out = h.merge(raw, targets, "de").decode("utf-8")
    assert "title=Grüße 😀 aus Köln\n" in out  # a UTF-8 file keeps raw characters
    assert "lead=\\ \\ indented\n" in out  # leading spaces survive the parser
    ascii_file = b"title=Kettle\n"
    result = h.extract(ascii_file, "en")
    out2 = h.merge(ascii_file, {"title": [["Wasserkocher 😀"]]}, "de")
    assert out2 == b"title=Wasserkocher \\ud83d\\ude00\n"
    again = {u.unit_id: u for u in h.extract(out2, "de").units}
    assert plain(joined(again["title"])) == "Wasserkocher 😀"


# --------------------------------------------------------------------------- .resx


def test_resx() -> None:
    result = ResxHandler().extract(RESX, "en")
    assert _units(result) == {"Greeting": ["Hello ⟦1/⟧, you have ⟦2/⟧ cups."], "Title": ["Kettle settings"]}
    assert result.units[0].notes == ["Shown on the home screen"]
    assert identity(ResxHandler(), RESX)[0] == RESX
    out, _, _ = translation(ResxHandler(), RESX)
    text = out.decode()
    assert "<value>[[HELLO ]]{0}[[, YOU HAVE ]]{1:N0}[[ CUPS.]]</value>" in text
    assert "<value>icon.png;System.Drawing.Bitmap</value>" in text and "<value>button1</value>" in text
    assert detect_and_extract("Strings.resw", RESX, "en").format == "resx"
