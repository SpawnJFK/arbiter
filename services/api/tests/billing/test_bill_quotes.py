from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from bill_helpers import make_file, make_org

from arbiter.billing import pricing, quotes
from arbiter.community.errors import Invalid
from arbiter.linguistic import tm
from arbiter.models import Job, Project, utcnow

NO_MIN = {"pricing": {"minimum": "0"}}


def test_quote_analysis_repetitions_and_minimum(db):
    org = make_org(db)
    f = make_file(db, org)
    q = quotes.build_quote(db, org, f, ["sr"], "ui")
    view = quotes.quote_view(q)
    assert view["word_count"] == 28
    assert view["analysis"]["new"] == 21 and view["analysis"]["repetitions"] == 7
    assert view["analysis"]["tm_exact"] == 0 and view["analysis"]["tm_fuzzy"] == 0
    # 21 + 7 * 0.1 = 21.7 weighted words; every tier is below the 5.00 minimum.
    assert {t["price"] for t in view["tiers"].values()} == {"5.00"}
    assert view["tiers"]["auto"]["est_auto_rate"] == 0.5  # prior, no history
    assert view["tiers"]["full"]["est_auto_rate"] == 0.0
    assert all(t["available"] for t in view["tiers"].values())
    assert q.valid_until > utcnow() + timedelta(days=13)


def test_tm_discounts_lower_the_price(db):
    plain = make_org(db, settings=NO_MIN)
    with_tm = make_org(db, settings=NO_MIN)
    tm.store(db, with_tm.id, "en", "sr", "Click Next to continue with the installation.", "Kliknite Dalje.")
    tm.store(
        db, with_tm.id, "en", "sr", "The report is generated every Monday morning.", "Izvestaj ponedeljkom."
    )
    tm.store(db, with_tm.id, "en", "sr", "Save your changes before closing the windows.", "Sacuvajte izmene.")

    q1 = quotes.build_quote(db, plain, make_file(db, plain), ["sr"], "ui")
    q2 = quotes.build_quote(db, with_tm, make_file(db, with_tm), ["sr"], "ui")
    assert q1.tiers["full"]["price"] == "2.60"  # 21.7 * 0.12
    a2 = q2.analysis
    assert a2["tm_exact"] == 14 and a2["tm_fuzzy"] == 7 and a2["repetitions"] == 7 and a2["new"] == 0
    # 14 * 0.1 + 7 * 0.3 (fuzzy 95-99) + 7 * 0.1 = 4.2 weighted words
    assert a2["weighted_words"] == "4.2"
    assert q2.tiers["full"]["price"] == "0.50"
    for tier in pricing.TIERS:
        assert Decimal(q2.tiers[tier]["price"]) < Decimal(q1.tiers[tier]["price"])

    # Two target languages: priced per language (no TM for de).
    q3 = quotes.build_quote(db, plain, make_file(db, plain), ["sr", "de"], "ui")
    assert q3.tiers["full"]["price"] == "5.21"  # 43.4 * 0.12 = 5.208


def test_regulated_org_quote_blocks_auto_and_ai_review(db):
    """R-SEG-12: regulated verticals never get auto or ai_review."""
    org = make_org(db, regulated=True)
    q = quotes.build_quote(db, org, make_file(db, org), ["sr"], "medical")
    for tier in ("auto", "ai_review"):
        assert q.tiers[tier]["available"] is False
        assert "R-SEG-12" in q.tiers[tier]["blocked_reason"]
        assert quotes.tier_allowed(q, tier) is False
    assert quotes.tier_allowed(q, "hybrid") and quotes.tier_allowed(q, "full")


def test_org_price_override_history_rate_and_expiry(db):
    org = make_org(db, settings={"pricing": {"tiers": {"hybrid": "1.00"}, "minimum": "0"}})
    f = make_file(db, org)
    p = Project(
        org_id=org.id, name="old", source_lang="en", target_langs=["sr"], tier="hybrid", content_type="ui"
    )
    db.add(p)
    db.flush()
    db.add(
        Job(
            project_id=p.id,
            org_id=org.id,
            file_id=f.id,
            source_lang="en",
            target_lang="sr",
            tier="hybrid",
            content_type="ui",
            state="delivered",
            segment_count=10,
            auto_approved_count=8,
        )
    )
    db.flush()
    q = quotes.build_quote(db, org, f, ["sr"], "ui")
    assert q.tiers["hybrid"]["price"] == "21.70"
    assert q.tiers["hybrid"]["est_auto_rate"] == 0.8
    assert q.analysis["by_lang"]["sr"]["auto_rate_source"] == "history"
    assert q.tiers["hybrid"]["eta_hours"] < q.tiers["full"]["eta_hours"]

    assert quotes.expire_quotes(db) == 0
    q.valid_until = utcnow() - timedelta(seconds=1)
    assert quotes.expire_quotes(db) == 1 and q.status == "expired"


def test_quote_rejects_foreign_file_and_bad_input(db):
    a, b = make_org(db), make_org(db)
    f = make_file(db, a)
    with pytest.raises(Invalid):
        quotes.build_quote(db, b, f, ["sr"], "ui")
    with pytest.raises(Invalid):
        quotes.build_quote(db, a, f, ["en"], "ui")
    bad = make_file(db, a, text="x", filename="scan.pdf")
    with pytest.raises(Invalid):
        quotes.build_quote(db, a, bad, ["sr"], "ui")
