from __future__ import annotations

import pytest
from quality_helpers import codes, ctx, term

from arbiter.contracts import TermViolation
from arbiter.quality.checks import CATALOGUE, number_readings, run_hard_checks


def only(issues, code):
    return [i for i in issues if i.code == code]


def test_clean_segment_has_no_issues():
    assert run_hard_checks(ctx("Open ⟦1⟧the file⟦/1⟧ now.", "Otvori ⟦1⟧datoteku⟦/1⟧ sada.")) == []


def test_catalogue_matches_issue_flags():
    for code, (sev, blocking) in CATALOGUE.items():
        assert sev in ("error", "warning", "info")
        assert not blocking or sev == "error", code


# ----------------------------------------------------------------- empty / untranslated


def test_empty_target_blocking():
    [i] = run_hard_checks(ctx("Hello world.", "  "))
    assert i.code == "empty_target" and i.blocking


def test_empty_source_and_target_fine():
    assert run_hard_checks(ctx("⟦1/⟧", "⟦1/⟧")) == []


def test_untranslated_warning_for_long_identical():
    issues = run_hard_checks(ctx("This is not translated at all.", "This is not translated at all."))
    [i] = only(issues, "untranslated")
    assert i.severity == "warning" and not i.blocking


def test_untranslated_short_or_dnt_only_not_flagged():
    assert "untranslated" not in codes(run_hard_checks(ctx("Save file", "Save file")))
    dnt = [term("do_not_translate", "Arbiter Cloud Platform Pro Edition", None)]
    c = ctx("Arbiter Cloud Platform Pro Edition", "Arbiter Cloud Platform Pro Edition", terms=dnt)
    assert "untranslated" not in codes(run_hard_checks(c))


# ----------------------------------------------------------------- tags


@pytest.mark.parametrize(
    ("target", "code", "blocking"),
    [
        ("Klik ⟦1⟧ovde⟦/1⟧.", "tag_missing", True),  # standalone ⟦2/⟧ dropped
        ("Klik ovde⟦2/⟧.", "tag_pair_dropped", False),  # whole pair dropped: warning
        ("Klik ⟦1⟧ovde⟦2/⟧.", "tag_unbalanced", True),  # half a pair
        ("Klik ⟦1⟧ovde⟦/1⟧⟦2/⟧⟦9/⟧.", "tag_unknown", True),
        ("Klik ⟦1⟧ovde⟦/1⟧⟦2/⟧⟦2/⟧.", "tag_extra", True),
        ("Klik ⟦1⟧ovde⟦/1⟧⟦2/⟧ ⟦bad", "tag_malformed", True),
    ],
)
def test_tag_checks(target, code, blocking):
    issues = run_hard_checks(ctx("Click ⟦1⟧here⟦/1⟧⟦2/⟧.", target))
    found = only(issues, code)
    assert found, codes(issues)
    assert found[0].blocking is blocking


def test_tag_order_error():
    issues = run_hard_checks(ctx("⟦1⟧a ⟦2⟧b⟦/2⟧⟦/1⟧", "⟦1⟧a ⟦2⟧b⟦/1⟧⟦/2⟧"))
    assert only(issues, "tag_order")[0].blocking


def test_tags_may_move():
    assert not [
        i for i in run_hard_checks(ctx("⟦1⟧Red⟦/1⟧ car", "auto ⟦1⟧crveni⟦/1⟧")) if i.code.startswith("tag")
    ]


# ----------------------------------------------------------------- numbers


@pytest.mark.parametrize(
    ("src", "tgt", "srcl", "tgtl"),
    [
        ("It costs 3.5 EUR", "Kosta 3,5 EUR", "en", "sr"),  # Serbian decimal comma
        ("We sold 1,000 units", "Wir verkauften 1.000 Einheiten", "en", "de"),  # German thousands
        ("We sold 1000 units", "Wir verkauften 1.000 Einheiten", "en", "de"),
        ("Total 1,234.56", "Ukupno 1.234,56", "en", "sr"),
        ("Total 1,234,567", "Total 1 234 567", "en", "fr"),
        ("Pages 10-20", "Strane 10–20", "en", "sr"),
        ("Up 50%", "Hausse de 50 %", "en", "fr"),
        ("2 of 3", "3 od 2", "en", "sr"),  # order may change
    ],
)
def test_numbers_accepted(src, tgt, srcl, tgtl):
    assert "number_mismatch" not in codes(run_hard_checks(ctx(src, tgt, srcl, tgtl)))


@pytest.mark.parametrize(
    ("src", "tgt"),
    [
        ("It costs 3.5 EUR", "Kosta 3,6 EUR"),
        ("We sold 1,000 units", "Prodali smo 100 jedinica"),
        ("Pages 10-20", "Strane 10-21"),
        ("Up 50%", "Rast 5%"),
        ("Call 2 times", "Pozovi dvaput"),
        ("Only text", "Samo 1 tekst"),
    ],
)
def test_numbers_rejected(src, tgt):
    [i] = only(run_hard_checks(ctx(src, tgt)), "number_mismatch")
    assert i.blocking and i.severity == "error"


def test_number_readings():
    assert {float(x) for x in number_readings("1.000")} == {1.0, 1000.0}
    assert {float(x) for x in number_readings("3,5")} == {3.5}
    assert {float(x) for x in number_readings("1.234.567")} == {1234567.0}


def test_numbers_inside_urls_and_placeholders_ignored():
    c = ctx("See https://ex.com/v2/page and {0}", "Vidi https://ex.com/v2/page i {0}")
    assert run_hard_checks(c) == []


# ----------------------------------------------------------------- urls / placeholders / length


def test_url_email_mismatch():
    ok = ctx("Write to info@ex.com or see https://ex.com/a.", "Pisite na info@ex.com ili https://ex.com/a.")
    assert "url_email_mismatch" not in codes(run_hard_checks(ok))
    bad = ctx("Write to info@ex.com.", "Pisite na info@ex.rs.")
    assert only(run_hard_checks(bad), "url_email_mismatch")[0].blocking
    bad2 = ctx("See https://ex.com/a.", "Vidi https://ex.com/b.")
    assert only(run_hard_checks(bad2), "url_email_mismatch")[0].blocking


@pytest.mark.parametrize("ph", ["{0}", "%s", "%1$s", "{{name}}", "${user}", "{count}", "%(name)s", "%.2f"])
def test_placeholders(ph):
    assert "placeholder_mismatch" not in codes(run_hard_checks(ctx(f"Hi {ph}!", f"Zdravo {ph}!")))
    [i] = only(run_hard_checks(ctx(f"Hi {ph}!", "Zdravo!")), "placeholder_mismatch")
    assert i.blocking


def test_placeholder_not_confused_with_percent_sign():
    assert "placeholder_mismatch" not in codes(run_hard_checks(ctx("50% sure", "50% siguran")))


def test_length_exceeded():
    assert "length_exceeded" not in codes(run_hard_checks(ctx("Save", "Snimi", max_length=5)))
    [i] = only(run_hard_checks(ctx("Save", "Sacuvaj", max_length=5)), "length_exceeded")
    assert i.blocking
    # codes do not count towards the length
    assert "length_exceeded" not in codes(run_hard_checks(ctx("⟦1⟧Save⟦/1⟧", "⟦1⟧Snimi⟦/1⟧", max_length=5)))


# ----------------------------------------------------------------- cosmetic


def test_whitespace_and_double_space_info():
    issues = run_hard_checks(ctx("Hello world. ", "Zdravo  svete."))
    assert only(issues, "whitespace_mismatch")[0].severity == "info"
    assert only(issues, "double_space")[0].severity == "info"
    assert not any(i.blocking for i in issues)


def test_repeated_word():
    [i] = only(run_hard_checks(ctx("Open the file.", "Otvori the the datoteku.")), "repeated_word")
    assert i.severity == "warning" and not i.blocking
    assert "repeated_word" not in codes(run_hard_checks(ctx("Bye bye now.", "Cao cao sada.")))


def test_punctuation_end():
    [i] = only(run_hard_checks(ctx("Are you sure?", "Da li ste sigurni.")), "punctuation_end")
    assert i.severity == "warning"
    assert "punctuation_end" not in codes(run_hard_checks(ctx("Done.", "完成。", tgt="zh")))
    assert "punctuation_end" not in codes(run_hard_checks(ctx("Really?", "Αλήθεια;", tgt="el")))
    assert "punctuation_end" not in codes(run_hard_checks(ctx('He said "go."', "Rekao je „idi.”")))


# ----------------------------------------------------------------- terms


def test_term_violations_mapped():
    vs = [
        TermViolation("t1", "mandatory", "term_missing", "error", "invoice -> faktura missing"),
        TermViolation("t2", "forbidden", "term_forbidden", "error", "racun used"),
        TermViolation("t3", "do_not_translate", "dnt_changed", "error", "Arbiter changed"),
        TermViolation("t4", "preferred", "term_preferred_missing", "warning", "prefer x"),
    ]
    issues = run_hard_checks(ctx("Open the invoice.", "Otvori fakturu."), vs)
    by = {i.code: i for i in issues}
    for code in ("term_missing", "term_forbidden", "dnt_changed"):
        assert by[code].blocking and by[code].severity == "error"
    assert not by["term_preferred_missing"].blocking and by["term_preferred_missing"].severity == "warning"
