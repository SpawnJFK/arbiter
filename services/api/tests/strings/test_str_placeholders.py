"""Placeholder protection, restore and string QA (R-STR-PH-*, R-STR-QA-*, R-STR-PL-*)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arbiter.contracts import SegmentContext
from arbiter.engines.mock import pseudo_translate
from arbiter.quality.checks import blocking, run_hard_checks
from arbiter.strings import placeholders as ph
from arbiter.strings import plurals
from arbiter.strings.qa import check_value


@pytest.mark.parametrize(
    ("value", "codes"),
    [
        ("Hello {name}!", ["{name}"]),
        ("%1$s sent %2$d files", ["%1$s", "%2$d"]),
        ("Welcome, %@", ["%@"]),
        ("Hi %{user}, 100%% done", ["%{user}", "%%"]),
        ("{{count}} new", ["{{count}}"]),
        ("Total ${amount}", ["${amount}"]),
        ("Tap <b>Save</b>", ["<b>", "</b>"]),
        ("{n, number} items {d, date, short}", ["{n, number}", "{d, date, short}"]),
        ("Save 50% off now", []),
    ],
)
def test_protect_restore_roundtrip(value, codes):
    p = ph.protect(value)
    assert p.codes == codes
    assert ph.restore(p.tagged, p.codes) == value


def test_icu_plural_selectors_become_codes_branch_text_translatable():
    v = "You have {count, plural, =0 {no files} one {# file} other {# files}} in {folder}"
    p = ph.protect(v)
    assert p.tagged == "You have ⟦1/⟧no files⟦2/⟧# file⟦3/⟧# files⟦4/⟧ in ⟦5/⟧"
    out = pseudo_translate(p.tagged)
    restored = ph.restore(out, p.codes)
    assert ph.icu_valid(restored) is None
    assert ph.icu_skeleton(restored) == ph.icu_skeleton(v)


def test_engine_dropping_a_placeholder_is_blocking():
    p = ph.protect("Delete %1$s from %2$s?")
    ctx = SegmentContext("s", p.tagged, "Löschen ⟦1/⟧?", "en", "de")
    issues = run_hard_checks(ctx)
    assert any(i.code == "tag_missing" for i in blocking(issues))


def test_restore_rejects_unknown_code():
    with pytest.raises(ph.TaggedParseError):
        ph.restore("Hallo ⟦9/⟧", ["{name}"])


def test_whole_plural_and_build():
    c = ph.whole_plural("{count, plural, one {# item} other {# items}}")
    assert c is not None and c.arg == "count"
    assert ph.whole_plural("Text {count, plural, one {a} other {b}}") is None
    assert (
        ph.build_plural("n", {"other": "b", "=0": "z", "one": "a"}) == "{n, plural, =0 {z} one {a} other {b}}"
    )


def _key(kind="string", max_length=None):
    return SimpleNamespace(kind=kind, max_length=max_length)


def test_qa_string_placeholders_icu_length():
    assert check_value(_key(), "Hi {name}", "Hallo {name}", "de") == []
    codes = {i["code"] for i in check_value(_key(), "Hi {name}", "Hallo {nombre}", "de")}
    assert codes == {"placeholder_changed"}
    bad_icu = check_value(_key(), "{n, plural, one {a} other {b}}", "{n, plural, one {a} other {b}", "de")
    assert any(i["code"] == "icu_syntax" for i in bad_icu)
    no_other = check_value(_key(), "{n, plural, one {a} other {b}}", "{n, plural, one {a}}", "de")
    assert any(i["code"] == "icu_structure" for i in no_other)
    long = check_value(_key(max_length=5), "Save", "Speichern", "de")
    assert [i["code"] for i in long] == ["length_exceeded"]
    assert check_value(_key(), "Save", "  ", "de")[0]["code"] == "empty_value"


def test_qa_plural_forms_per_language():
    base = {"one": "One note", "other": "%d notes"}
    ok = check_value(
        _key("plural"),
        base,
        {"one": "%d заметка", "few": "%d заметки", "many": "%d заметок", "other": "%d заметки"},
        "ru",
    )
    assert not [i for i in ok if i["blocking"]]
    missing = check_value(_key("plural"), base, {"one": "%d заметка", "other": "%d заметки"}, "ru")
    assert any(i["code"] == "plural_forms_missing" and i["blocking"] for i in missing)
    # "one" may drop the number placeholder; an unknown placeholder is still blocking
    de = check_value(_key("plural"), base, {"one": "Eine Notiz", "other": "%d Notizen"}, "de")
    assert not [i for i in de if i["blocking"]]
    added = check_value(_key("plural"), base, {"one": "%s Notiz", "other": "%d Notizen"}, "de")
    assert any(i["code"] == "placeholder_changed" and i["blocking"] for i in added)
    # French "many" is optional (compact numbers only)
    fr = check_value(_key("plural"), base, {"one": "%d note", "other": "%d notes"}, "fr")
    assert not [i for i in fr if i["blocking"]]


def test_plural_tables():
    assert plurals.categories("ru") == ("one", "few", "many", "other")
    assert plurals.required("pt-BR") == ("one", "other")
    assert plurals.categories("ja") == ("other",)
    assert plurals.gettext_forms("ru") == ("one", "few", "many")
    assert plurals.categories("de", {"de": ["other", "one", "zero"]}) == ("zero", "one", "other")
    assert plurals.source_form_for("few", {"one": "a", "other": "b"}) == "other"
