from __future__ import annotations

import pytest
from lxml import etree

from arbiter.linguistic import context_hash, export_tmx, import_tmx, lookup, source_hash, store, tagged_plain
from arbiter.models import Organization, TmEntry


@pytest.fixture
def org(db):
    o = Organization(name="Acme", slug="acme-tm")
    db.add(o)
    db.flush()
    return o


def test_hashes_normalise_whitespace_and_keep_tags():
    assert source_hash("  Save  the\tfile ", "en") == source_hash("Save the file", "en-US")
    assert source_hash("⟦1⟧Save⟦/1⟧ the file", "en") != source_hash("Save the file", "en")
    assert context_hash("a", "b") != context_hash("b", "a")
    assert tagged_plain("⟦1⟧Save⟦/1⟧ ⟦⟦x⟧⟧ ⟦2/⟧") == "Save ⟦x⟧ "


def test_context_beats_exact_and_upsert_replaces_target(db, org):
    ctx = context_hash("Open the menu.", "Close the window.")
    store(db, org.id, "en", "sr", "Click ⟦1⟧Save⟦/1⟧.", "Kliknite ⟦1⟧Sačuvaj⟦/1⟧.", context_hash=ctx)
    store(db, org.id, "en", "sr", "Click ⟦1⟧Save⟦/1⟧.", "Pritisnite ⟦1⟧Sačuvaj⟦/1⟧.")
    m = lookup(db, org.id, "en", "sr", "Click  ⟦1⟧Save⟦/1⟧.", ctx)
    assert [(x.kind, x.score) for x in m] == [("context", 101.0), ("exact", 100.0)]
    assert m[0].target_tagged == "Kliknite ⟦1⟧Sačuvaj⟦/1⟧."
    # Without context information both are plain exact matches.
    assert {x.kind for x in lookup(db, org.id, "en", "sr", "Click ⟦1⟧Save⟦/1⟧.")} == {"exact"}

    # R-TM-05: a newer approved translation replaces the target in place.
    e = store(db, org.id, "en", "sr", "Click ⟦1⟧Save⟦/1⟧.", "Kliknite na ⟦1⟧Sačuvaj⟦/1⟧.", context_hash=ctx)
    assert db.query(TmEntry).count() == 2
    assert e.target_plain == "Kliknite na Sačuvaj."
    assert lookup(db, org.id, "en", "sr", "Click ⟦1⟧Save⟦/1⟧.", ctx)[0].target_tagged == e.target_tagged


def test_fuzzy_ranking_with_tag_penalty(db, org):
    store(db, org.id, "en", "de", "The contract ends on 31 March.", "Der Vertrag endet am 31. März.")
    store(db, org.id, "en", "de", "The contract ends on 31 May.", "Der Vertrag endet am 31. Mai.")
    store(
        db,
        org.id,
        "en",
        "de",
        "The ⟦1⟧contract⟦/1⟧ ends on 31 March.",
        "Der ⟦1⟧Vertrag⟦/1⟧ endet am 31. März.",
    )
    store(db, org.id, "en", "de", "Penguins live in Antarctica.", "Pinguine leben in der Antarktis.")
    m = lookup(db, org.id, "en", "de", "The contract ends on 30 March.", limit=5)
    assert [x.kind for x in m] == ["fuzzy", "fuzzy", "fuzzy"]
    assert m[0].source_tagged == "The contract ends on 31 March."
    # Same text with an extra formatting pair ranks just below (2 codes differ -> -2).
    assert m[1].source_tagged == "The ⟦1⟧contract⟦/1⟧ ends on 31 March."
    assert m[0].score - m[1].score == pytest.approx(2.0)
    assert m[2].source_tagged == "The contract ends on 31 May."
    assert all(75 <= x.score < 100 for x in m)
    # Tenancy: another org never sees these.
    other = Organization(name="Other", slug="other-tm")
    db.add(other)
    db.flush()
    assert lookup(db, other.id, "en", "de", "The contract ends on 30 March.") == []


def test_semantic_fallback_only_without_good_fuzzy(db, org):
    store(
        db, org.id, "en", "fi", "Payment is due within thirty days of the invoice date.", "Maksu erääntyy..."
    )
    store(db, org.id, "en", "fi", "Click Save to store your changes.", "Tallenna muutokset.")
    q = "Within thirty days of the invoice date, payment is due."
    m = lookup(db, org.id, "en", "fi", q)
    assert len(m) == 1 and m[0].kind == "semantic" and 60 <= m[0].score < 100
    assert m[0].source_tagged.startswith("Payment is due")
    assert lookup(db, org.id, "en", "fi", q, use_semantic=False) == []
    # A good fuzzy suppresses semantic results entirely.
    m2 = lookup(db, org.id, "en", "fi", "Payment is due within thirty days of the invoice.")
    assert [x.kind for x in m2] == ["fuzzy"]


def test_status_and_script_filters(db, org):
    e = store(db, org.id, "en", "sr-Latn", "Good morning.", "Dobro jutro.")
    store(db, org.id, "en", "sr-Cyrl", "Good morning.", "Добро јутро.")
    assert [x.target_tagged for x in lookup(db, org.id, "en", "sr-latn", "Good morning.")] == ["Dobro jutro."]
    assert len(lookup(db, org.id, "en", "sr", "Good morning.")) == 2
    e.status = "stale"
    db.flush()
    assert [x.target_tagged for x in lookup(db, org.id, "en", "sr", "Good morning.")] == ["Добро јутро."]


TMX = """<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4">
 <header creationtool="X" creationtoolversion="1" segtype="sentence" o-tmf="x" adminlang="en"
         srclang="en-US" datatype="html"/>
 <body>
  <tu>
   <tuv xml:lang="en-US"><seg>Press <bpt i="1">&lt;b&gt;</bpt>Save<ept i="1">&lt;/b&gt;</ept> now<ph x="2">&lt;br/&gt;</ph></seg></tuv>
   <tuv xml:lang="pl-PL"><seg>Naciśnij teraz <bpt i="1">&lt;b&gt;</bpt>Zapisz<ept i="1">&lt;/b&gt;</ept><ph x="2">&lt;br/&gt;</ph></seg></tuv>
   <tuv xml:lang="sr-Latn"><seg><ph x="2"/>Pritisnite <bpt i="1"/>Sačuvaj<ept i="1"/> sada</seg></tuv>
  </tu>
  <tu>
   <prop type="x-context">abc</prop>
   <tuv xml:lang="en-US"><seg>Use ⟦brackets⟧ <hi>here</hi>.</seg></tuv>
   <tuv xml:lang="de-DE"><seg>Verwende ⟦Klammern⟧ <hi>hier</hi>.</seg></tuv>
  </tu>
  <tu><tuv xml:lang="en-US"><seg>Lonely</seg></tuv></tu>
  <tu><tuv xml:lang="fr"><seg>Bonjour</seg></tuv><tuv xml:lang="de"><seg>Hallo</seg></tuv></tu>
 </body>
</tmx>""".encode()


def test_tmx_requires_rights(db, org):
    with pytest.raises(ValueError, match="R-TM-01"):
        import_tmx(db, org.id, TMX, rights_confirmed_by=" ")


def test_tmx_import_inline_tags_and_round_trip(db, org):
    res = import_tmx(db, org.id, TMX, rights_confirmed_by="usr_owner")
    assert res["imported"] == 3 and res["skipped"] == 1 and len(res["errors"]) == 1

    pl = lookup(db, org.id, "en", "pl", "Press ⟦1⟧Save⟦/1⟧ now⟦2/⟧")
    assert [(x.kind, x.target_tagged) for x in pl] == [("exact", "Naciśnij teraz ⟦1⟧Zapisz⟦/1⟧⟦2/⟧")]
    sr = lookup(db, org.id, "en", "sr", "Press ⟦1⟧Save⟦/1⟧ now⟦2/⟧")
    assert sr[0].target_tagged == "⟦2/⟧Pritisnite ⟦1⟧Sačuvaj⟦/1⟧ sada"
    de = lookup(db, org.id, "en", "de", "Use ⟦⟦brackets⟧⟧ ⟦1⟧here⟦/1⟧.", "abc")
    assert de[0].kind == "context" and de[0].target_tagged == "Verwende ⟦⟦Klammern⟧⟧ ⟦1⟧hier⟦/1⟧."
    entry = db.query(TmEntry).filter_by(target_lang="pl-pl").one()
    assert (
        entry.status == "imported" and entry.origin == "import" and entry.rights_confirmed_by == "usr_owner"
    )

    # Import never overwrites reviewed work (R-TM-05).
    store(db, org.id, "en-US", "pl-PL", "Press ⟦1⟧Save⟦/1⟧ now⟦2/⟧", "Kliknij ⟦1⟧Zapisz⟦/1⟧ teraz⟦2/⟧")
    again = import_tmx(db, org.id, TMX, rights_confirmed_by="usr_owner")
    assert again["imported"] == 0 and again["skipped"] == 4
    assert lookup(db, org.id, "en", "pl", "Press ⟦1⟧Save⟦/1⟧ now⟦2/⟧")[0].target_tagged.startswith("Kliknij")

    # Export -> import into a fresh org gives identical tagged pairs.
    for tl in ("pl", "sr", "de"):
        out = export_tmx(db, org.id, "en", tl)
        root = etree.fromstring(out)
        assert root.get("version") == "1.4" and root.find("header").get("srclang") == "en"
        other = Organization(name=f"Copy {tl}", slug=f"copy-{tl}")
        db.add(other)
        db.flush()
        r = import_tmx(db, other.id, out, rights_confirmed_by="usr_owner")
        assert r["imported"] == 1 and not r["errors"]
        src = db.query(TmEntry).filter_by(org_id=org.id).filter(TmEntry.target_lang.like(f"{tl}%")).one()
        dst = db.query(TmEntry).filter_by(org_id=other.id).one()
        assert (dst.source_tagged, dst.target_tagged, dst.context_hash) == (
            src.source_tagged,
            src.target_tagged,
            src.context_hash,
        )
