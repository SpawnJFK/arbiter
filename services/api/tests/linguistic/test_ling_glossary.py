from __future__ import annotations

import pytest
from lxml import etree

from arbiter.linguistic import (
    active_terms,
    add_term,
    check_target,
    create_glossary,
    current_version,
    export_csv,
    export_tbx,
    find_source_terms,
    import_csv,
    import_tbx,
    retire_term,
    update_term,
)
from arbiter.models import Organization, Term

_n = 0


def T(source, target, kind="mandatory", sl="en", tl="sr", case_sensitive=False):
    global _n
    _n += 1
    return Term(
        id=f"trm_{_n}",
        glossary_id="gls_x",
        source_lang=sl,
        target_lang=tl,
        source_term=source,
        target_term=target,
        kind=kind,
        case_sensitive=case_sensitive,
        note="",
        valid_from=1,
    )


def codes(violations):
    return sorted(v.code for v in violations)


# ------------------------------------------------------------------ matching (R-GL-01/03/05/06/07)


def test_serbian_mandatory_accepts_inflected_target():
    term = T("contract", "ugovor")
    hits = find_source_terms("Sign the contract today.", [term], "en")
    assert len(hits) == 1 and (hits[0].start, hits[0].end) == (9, 17)
    assert check_target("Potpišite ugovor danas.", hits, "sr") == []
    assert check_target("Raskid ugovora je moguć.", hits, "sr") == []
    assert check_target("Upravljajte ugovorom.", hits, "sr") == []
    # Cyrillic target satisfies a Latin glossary entry.
    assert check_target("Потпишите уговор данас.", hits, "sr-Cyrl") == []
    v = check_target("Potpišite sporazum danas.", hits, "sr")
    assert codes(v) == ["term_missing"] and v[0].severity == "error"


def test_source_side_inflection_and_multiword_longest_wins():
    terms = [T("payment", "plaćanje"), T("payment terms", "uslovi plaćanja")]
    hits = find_source_terms("Our Payment Terms changed; payments are monthly.", terms, "en")
    spans = [(h.source_term, h.start, h.end) for h in hits]
    assert spans == [("payment terms", 4, 17), ("payment", 27, 35)]
    # "uslovi plaćanja" inflected in the target still counts (R-GL-03).
    assert check_target("Naši uslovi plaćanja su promenjeni; plaćanje je mesečno.", hits, "sr") == []
    assert check_target("Promenili smo uslove plaćanja; plaćanja su mesečna.", hits, "sr") == []


def test_occurrence_counting():
    hits = find_source_terms("The contract replaces the old contract.", [T("contract", "ugovor")], "en")
    assert len(hits) == 2
    assert check_target("Ugovor zamenjuje stari ugovor.", hits, "sr") == []
    v = check_target("Ugovor zamenjuje stari sporazum.", hits, "sr")
    assert codes(v) == ["term_missing"] and "1 of 2" in v[0].message


def test_case_sensitive_brand():
    term = T("Apple", "Apple", case_sensitive=True)
    assert find_source_terms("I ate an apple.", [term], "en") == []
    hits = find_source_terms("Apple released a phone.", [term], "en")
    assert len(hits) == 1
    assert codes(check_target("apple je objavio telefon.", hits, "sr")) == ["term_missing"]
    assert check_target("Apple je objavio telefon.", hits, "sr") == []


def test_dnt_changed_in_cyrillic_target():
    # R-GL-07: a Latin brand inside Cyrillic text must stay Latin, char-exact.
    term = T("Arbiter Cloud", None, kind="do_not_translate", case_sensitive=True)
    hits = find_source_terms("Open Arbiter Cloud and log in.", [term], "en")
    assert len(hits) == 1 and hits[0].target_term is None
    assert check_target("Отворите Arbiter Cloud и пријавите се.", hits, "sr-Cyrl") == []
    v = check_target("Отворите Арбитер Цлоуд и пријавите се.", hits, "sr-Cyrl")
    assert codes(v) == ["dnt_changed"] and v[0].severity == "error"
    assert codes(check_target("Otvorite Arbiter cloud.", hits, "sr")) == ["dnt_changed"]


def test_forbidden_detected_inflected_and_preferred_warning():
    forbidden = T("agreement", "sporazum", kind="forbidden")
    preferred = T("user", "korisnik", kind="preferred")
    hits = find_source_terms("The user signs.", [forbidden, preferred], "en")
    fb = [h for h in hits if h.kind == "forbidden"]
    assert len(fb) == 1 and fb[0].start == fb[0].end == -1 and fb[0].target_term == "sporazum"
    assert check_target("Korisnik potpisuje.", hits, "sr") == []
    v = check_target("Klijent potpisuje sporazuma.", hits, "sr")
    assert codes(v) == ["term_forbidden", "term_preferred_missing"]
    sev = {x.code: x.severity for x in v}
    assert sev == {"term_forbidden": "error", "term_preferred_missing": "warning"}


def test_german_compounds_and_umlaut_plural():
    hits = find_source_terms("Both contracts were signed.", [T("contract", "Vertrag", tl="de")], "en")
    assert check_target("Beide Verträge wurden unterschrieben.", hits, "de") == []
    hits = find_source_terms(
        "Die Kündigungen und die Kündigung.", [T("Kündigung", "termination", sl="de", tl="en")], "de"
    )
    assert len(hits) == 2
    assert check_target("The terminations and the termination.", hits, "en") == []


def test_polish_and_finnish_inflection():
    hits = find_source_terms("Read the agreement.", [T("agreement", "umowa", tl="pl")], "en")
    assert check_target("Przeczytaj warunki umowy.", hits, "pl") == []
    assert check_target("Zgodnie z umową.", hits, "pl") == []
    hits = find_source_terms("Read the agreement.", [T("agreement", "sopimus", tl="fi")], "en")
    for target in ("Lue sopimus.", "Lue sopimuksen ehdot.", "Sopimuksessa sanotaan.", "Lue sopimusta."):
        assert check_target(target, hits, "fi") == [], target
    assert codes(check_target("Lue ehdot.", hits, "fi")) == ["term_missing"]


# ------------------------------------------------------------------ versioning (R-GL-11)


@pytest.fixture
def org(db):
    o = Organization(name="Acme", slug="acme")
    db.add(o)
    db.flush()
    return o


def test_job_frozen_at_version_does_not_see_later_terms(db, org):
    g = create_glossary(db, org.id, "Main")
    legal = create_glossary(db, org.id, "Legal only", content_type="legal")
    t1 = add_term(db, g.id, "en", "sr", "contract", "ugovor")
    frozen = current_version(db, org.id, "general")
    add_term(db, g.id, "en", "sr", "invoice", "faktura")
    add_term(db, legal.id, "en", "sr-Latn", "clause", "klauzula")

    frozen_terms = active_terms(db, org.id, "en", "sr", "general", frozen)
    assert [t.source_term for t in frozen_terms] == ["contract"]
    now = active_terms(db, org.id, "en-US", "sr", "general", None)
    assert sorted(t.source_term for t in now) == ["contract", "invoice"]
    legal_now = active_terms(db, org.id, "en", "sr", "legal", None)
    assert sorted(t.source_term for t in legal_now) == ["clause", "contract", "invoice"]
    assert active_terms(db, org.id, "en", "de", "general", None) == []

    # Update closes the old row and inserts a new one; the frozen job keeps the old target.
    v_before = current_version(db, org.id, "general")
    t1b = update_term(db, t1.id, target_term="kontrakt")
    assert t1b.id != t1.id and t1.valid_to == t1b.valid_from > v_before
    assert {t.target_term for t in active_terms(db, org.id, "en", "sr", "general", frozen)} == {"ugovor"}
    assert "kontrakt" in {t.target_term for t in active_terms(db, org.id, "en", "sr", "general", None)}

    retire_term(db, t1b.id)
    assert "contract" not in {t.source_term for t in active_terms(db, org.id, "en", "sr", "general", None)}
    assert "contract" in {t.source_term for t in active_terms(db, org.id, "en", "sr", "general", frozen)}

    with pytest.raises(ValueError):
        add_term(db, g.id, "en", "sr", "x", "y", kind="weird")
    with pytest.raises(ValueError):
        add_term(db, g.id, "en", "sr", "x", None, kind="mandatory")


# ------------------------------------------------------------------ CSV / TBX


def test_csv_import_tolerant_headers_and_round_trip(db, org):
    g = create_glossary(db, org.id, "Imported")
    data = (
        "﻿Source Language;Target Language;Source;Translation;Type;Case;Comment\n"
        "en;sr;contract;ugovor;required;no;legal\n"
        "en;sr;Arbiter;;DNT;yes;brand\n"
        "en;sr;agreement;sporazum;deprecated;;\n"
        "en;sr;user;korisnik;preferred;;\n"
        "en;sr;;nothing;mandatory;;\n"
        "en;sr;thing;stvar;bogus;;\n"
        "en;sr;invoice;;mandatory;;\n"
    ).encode()
    res = import_csv(db, g.id, data)
    assert res["imported"] == 4 and res["skipped"] == 0 and len(res["errors"]) == 3

    again = import_csv(db, g.id, data)
    assert again["imported"] == 0 and again["skipped"] == 4

    exported = export_csv(db, g.id)
    assert (
        exported.splitlines()[0] == "source_lang,target_lang,source_term,target_term,kind,case_sensitive,note"
    )
    g2 = create_glossary(db, org.id, "Copy")
    res2 = import_csv(db, g2.id, exported)
    assert res2 == {"imported": 4, "skipped": 0, "errors": []}
    assert export_csv(db, g2.id) == exported

    # Defaults for files without language columns, tab separated.
    g3 = create_glossary(db, org.id, "Plain")
    res3 = import_csv(db, g3.id, "term\ttranslation\nVertrag\tugovor\n", source_lang="de", target_lang="sr")
    assert res3["imported"] == 1


def test_tbx_round_trip_v3(db, org):
    g = create_glossary(db, org.id, "TBX")
    import_csv(
        db,
        g.id,
        "source_lang,target_lang,source_term,target_term,kind,case_sensitive,note\n"
        "en,de,contract,Vertrag,mandatory,false,legal\n"
        "en,de,Arbiter,,do_not_translate,true,brand\n"
        "en,de,agreement,Abkommen,forbidden,false,\n"
        "en,de,user,Benutzer,preferred,false,\n",
    )
    data = export_tbx(db, g.id)
    root = etree.fromstring(data)
    assert root.tag == "{urn:iso:std:iso:30042:ed-2}tbx"
    g2 = create_glossary(db, org.id, "TBX copy")
    res = import_tbx(db, g2.id, data, source_lang="en")
    assert res == {"imported": 4, "skipped": 0, "errors": []}
    assert export_csv(db, g2.id) == export_csv(db, g.id)


def test_tbx_basic_martif_import(db, org):
    g = create_glossary(db, org.id, "Martif")
    tbx = b"""<?xml version="1.0"?>
<martif type="TBX-Basic" xml:lang="en-US">
 <text><body>
  <termEntry id="e1">
   <descrip type="definition">A binding agreement.</descrip>
   <langSet xml:lang="en-US"><tig><term>contract</term></tig></langSet>
   <langSet xml:lang="pl-PL">
     <tig><term>umowa</term><termNote type="administrativeStatus">preferredTerm-admn-sts</termNote></tig>
     <tig><term>kontrakt</term><termNote type="administrativeStatus">deprecatedTerm-admn-sts</termNote></tig>
   </langSet>
   <langSet xml:lang="fi"><ntig><termGrp><term>sopimus</term></termGrp>
     <termNote type="administrativeStatus">admittedTerm-admn-sts</termNote></ntig></langSet>
  </termEntry>
  <termEntry id="e2"><langSet xml:lang="de"><tig><term>Nur Deutsch</term></tig></langSet></termEntry>
 </body></text>
</martif>"""
    res = import_tbx(db, g.id, tbx, source_lang="en")
    assert res["imported"] == 3 and res["skipped"] == 1
    pl = {t.target_term: t.kind for t in active_terms(db, org.id, "en", "pl", None, None)}
    assert pl == {"umowa": "mandatory", "kontrakt": "forbidden"}
    fi = active_terms(db, org.id, "en", "fi", None, None)
    assert [(t.target_term, t.kind, t.note) for t in fi] == [("sopimus", "preferred", "A binding agreement.")]
    assert import_tbx(db, g.id, b"<not-xml", source_lang="en")["errors"]
