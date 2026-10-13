"""Round trip per string format: parse(fixture) -> render -> parse gives the same keys, kinds,
values, descriptions and translatable flags (R-STR-IN-*). Realistic fixtures in fixtures/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arbiter.strings import formats
from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError

FIX = Path(__file__).parent / "fixtures"


def _sig(doc: Doc, lang: str) -> list[tuple]:
    return [
        (r.namespace, r.key, r.kind, r.values.get(lang), r.description, r.translatable)
        for r in doc.rows
        if lang in r.values
    ]


def _roundtrip(fmt: str, data: bytes, lang: str = "en", base: str = "en") -> tuple[Doc, Doc, bytes]:
    doc = formats.parse(fmt, data, lang, base)
    out = formats.render(fmt, doc, lang)
    again = formats.parse(fmt, out, lang, base)
    assert _sig(again, lang) == _sig(doc, lang), out.decode("utf-8", "replace")
    return doc, again, out


def test_json_flat_icu_plural_and_array():
    doc, _, out = _roundtrip("json", (FIX / "en.json").read_bytes())
    rows = {r.key: r for r in doc.rows}
    assert rows["home.files"].kind == "plural"
    assert rows["home.files"].values["en"] == {"=0": "No files yet", "one": "# file", "other": "# files"}
    assert rows["home.files"].meta["icu_arg"] == "count"
    assert rows["home.summary"].kind == "string"  # embedded ICU stays a string
    assert rows["weekdays"].kind == "array"
    assert json.loads(out)["home.files"].startswith("{count, plural, =0 {No files yet}")


def test_json_nested_next_intl():
    doc, _, out = _roundtrip("json_nested", (FIX / "en.nested.json").read_bytes())
    assert [r.key for r in doc.rows] == [
        "auth.login.title",
        "auth.login.submit",
        "auth.errors.invalid",
        "cart.items",
    ]
    assert json.loads(out)["auth"]["login"]["submit"] == "Continue with {provider}"


def test_i18next_plural_suffixes():
    doc, _, out = _roundtrip("i18next", (FIX / "en.i18next.json").read_bytes())
    rows = {r.key: r for r in doc.rows}
    assert rows["nav.inbox"].values["en"] == {
        "one": "{{count}} new message",
        "other": "{{count}} new messages",
    }
    assert rows["trash"].values["en"]["zero"] == "Trash is empty"
    assert json.loads(out)["nav"]["inbox_other"] == "{{count}} new messages"


def test_formatjs_descriptions():
    doc, _, _ = _roundtrip("formatjs", (FIX / "en.formatjs.json").read_bytes())
    assert doc.rows[0].description == "Primary button on the checkout page"
    assert doc.rows[1].kind == "plural" and doc.rows[1].meta["icu_arg"] == "itemCount"


def test_arb_metadata_kept():
    doc, _, out = _roundtrip("arb", (FIX / "app_en.arb").read_bytes())
    obj = json.loads(out)
    assert obj["@@locale"] == "en" and obj["@@last_modified"] == "2026-10-01T10:00:00Z"
    assert obj["@greeting"]["placeholders"]["userName"]["example"] == "Bob"
    wombats = next(r for r in doc.rows if r.key == "nWombats")
    assert wombats.values["en"] == {"=0": "no wombats", "=1": "1 wombat", "other": "{count} wombats"}
    de = formats.render("arb", Doc("en", [KeyRow("helloWorld", values={"de": "Hallo Welt!"})]), "de")
    assert json.loads(de) == {"@@locale": "de", "helloWorld": "Hallo Welt!"}


def test_android_escapes_markup_plurals_arrays():
    doc, _, out = _roundtrip("android", (FIX / "strings.xml").read_bytes())
    rows = {r.key: r for r in doc.rows}
    assert rows["app_name"].translatable is False
    assert rows["welcome_title"].description == "Title of the welcome screen"
    assert rows["dont_forget"].values["en"] == 'Don\'t forget to "save" & sync'
    assert (
        rows["tap_save"].values["en"]
        == 'Tap <b>Save</b> to keep <xliff:g id="count" example="3">%d</xliff:g> notes'
    )
    assert rows["email_hint"].values["en"] == "@username or email"
    assert rows["two_lines"].values["en"] == "First line\nSecond line"
    assert rows["padded"].values["en"] == "  spaced out  "
    assert rows["notes_count"].values["en"] == {"one": "%d note", "other": "%d notes"}
    assert rows["sort_options"].values["en"] == {"0": "Newest first", "1": "Oldest first", "2": "By title"}
    text = out.decode()
    assert 'Don\\\'t forget to \\"save\\" &amp; sync' in text
    assert "\\@username" in text and '"  spaced out  "' in text
    # target export leaves out translatable="false"
    tgt = Doc("en", [KeyRow("app_name", translatable=False, values={"en": "x", "de": "x"})])
    assert b"app_name" not in formats.render("android", tgt, "de")


def test_ios_strings_utf16_and_comments():
    utf8 = (FIX / "Localizable.utf8.strings").read_bytes()
    doc, _, _ = _roundtrip("ios_strings", utf8.decode().encode("utf-16"))
    rows = {r.key: r for r in doc.rows}
    assert rows["main.title"].description == "Title of the main screen"
    assert rows["quote"].values["en"] == 'She said "hi"\nthen left'
    assert rows["unquoted_key"].values["en"] == "Value"


def test_stringsdict_plural():
    doc, _, _ = _roundtrip("stringsdict", (FIX / "Localizable.stringsdict").read_bytes())
    assert doc.rows[0].values["en"] == {"zero": "No files", "one": "%d file", "other": "%d files"}
    assert doc.rows[0].meta["variable"] == "files"


def test_xcstrings_multilingual():
    data = (FIX / "Localizable.xcstrings").read_bytes()
    doc = formats.parse("xcstrings", data, "en", "en")
    assert doc.langs == ["de", "en"]
    rows = {r.key: r for r in doc.rows}
    assert rows["%lld items"].values["de"] == {"one": "%lld Eintrag", "other": "%lld Einträge"}
    assert rows["Done"].states["de"] == "machine"
    out = formats.render("xcstrings", doc, "en")
    assert json.loads(out) == json.loads(data)  # semantic identity, including states


def test_rails_yaml():
    doc, _, out = _roundtrip("yaml", (FIX / "en.yml").read_bytes())
    rows = {r.key: r for r in doc.rows}
    assert rows["users.count"].kind == "plural"
    assert rows["date.abbr_day_names"].kind == "array"
    assert any("number.precision" in w for w in doc.warnings)
    assert out.startswith(b"en:\n")


def test_po_plurals_context_fuzzy():
    data = (FIX / "de.po").read_bytes()
    doc = formats.parse("po", data, "de", "en")
    rows = {r.key: r for r in doc.rows}
    assert rows["Save"].values == {"en": "Save", "de": "Speichern"}
    assert rows["Save"].description == "Shown in the toolbar"
    assert rows["Deleted %d file"].values["de"] == {
        "one": "%d Datei gelöscht",
        "other": "%d Dateien gelöscht",
    }
    assert rows["menu::Open"].values["de"] == "Öffnen"
    assert "de" not in rows["verb::Open"].values
    long = next(r for r in doc.rows if r.key.startswith("A long"))
    assert long.values["en"] == "A long message that spans two lines.\nAnd a second line."
    assert long.states["de"] == "machine"
    out = formats.render("po", doc, "de")
    again = formats.parse("po", out, "de", "en")
    assert _sig(again, "de") == _sig(doc, "de") and _sig(again, "en") == _sig(doc, "en")
    assert b"#, fuzzy" in out and b'msgctxt "menu"' in out


def test_po_russian_three_forms():
    doc = formats.parse("po", (FIX / "ru.po").read_bytes(), "ru", "en")
    assert doc.rows[0].values["ru"] == {"one": "%d файл", "few": "%d файла", "many": "%d файлов"}
    out = formats.render("po", doc, "ru")
    assert b"nplurals=3" in out and 'msgstr[2] "%d файлов"'.encode() in out


def test_pot_template():
    doc = formats.parse("po", (FIX / "de.po").read_bytes(), "de", "en")
    pot = formats.render("pot", doc, "en")
    tdoc = formats.parse("pot", pot, "en", "en")
    assert all(set(r.values) == {"en"} for r in tdoc.rows)
    assert len(tdoc.rows) == len(doc.rows)


def _bilingual() -> Doc:
    return Doc(
        "en",
        [
            KeyRow(
                "title", description="Window title", max_length=20, values={"en": "Notes", "de": "Notizen"}
            ),
            KeyRow("greet", namespace="home", values={"en": "Hi {name}", "de": "Hallo {name}"}),
            KeyRow(
                "files",
                kind="plural",
                values={
                    "en": {"one": "# file", "other": "# files"},
                    "de": {"one": "# Datei", "other": "# Dateien"},
                },
            ),
            KeyRow("todo", values={"en": "Not yet"}),
        ],
        langs=["en", "de"],
    )


@pytest.mark.parametrize("fmt", ["xliff12", "xliff21"])
def test_xliff_export_import(fmt):
    doc = _bilingual()
    out = formats.render(fmt, doc, "de")
    again = formats.parse(fmt, out, "de", "en")
    assert _sig(again, "de") == _sig(doc, "de")
    assert _sig(again, "en") == _sig(doc, "en")
    title = next(r for r in again.rows if r.key == "title")
    assert title.max_length == 20
    assert next(r for r in again.rows if r.key == "greet").namespace == "home"
    assert formats.detect("x.xlf", out) == fmt


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_spreadsheets(fmt):
    doc = _bilingual()
    out = formats.render(fmt, doc, "de")
    again = formats.parse(fmt, out, "de", "en")
    for lang in ("en", "de"):
        assert _sig(again, lang) == _sig(doc, lang)
    assert next(r for r in again.rows if r.key == "title").max_length == 20


def test_xlsx_shared_strings_from_excel():
    openpyxl = pytest.importorskip("openpyxl")
    import io

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["key", "description", "en", "fr"])
    ws.append(["save", "Toolbar", "Save", "Enregistrer"])
    buf = io.BytesIO()
    wb.save(buf)
    doc = formats.parse("xlsx", buf.getvalue(), "fr", "en")
    assert doc.rows[0].values == {"en": "Save", "fr": "Enregistrer"}


def test_detect():
    assert formats.detect("app_en.arb", b"{}") == "arb"
    assert formats.detect("en.json", (FIX / "en.i18next.json").read_bytes()) == "i18next"
    assert formats.detect("en.json", (FIX / "en.nested.json").read_bytes()) == "json_nested"
    assert formats.detect("en.json", (FIX / "en.formatjs.json").read_bytes()) == "formatjs"
    assert formats.detect("Localizable.xcstrings", b"{}") == "xcstrings"
    assert formats.detect("strings.xml", b"") == "android"
    with pytest.raises(StringsFormatError):
        formats.detect("notes.docx", b"")


def test_broken_files_are_refused_with_a_message():
    for fmt, data in [
        ("json", b"{not json"),
        ("android", b"<resources><string>"),
        ("po", b'msgid "x"\nbogus line'),
        ("xlsx", b"PK not a zip"),
        ("yaml", b"en: [unclosed"),
    ]:
        with pytest.raises(StringsFormatError):
            formats.parse(fmt, data, "en", "en")
