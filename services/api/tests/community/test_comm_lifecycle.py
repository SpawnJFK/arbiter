from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from comm_helpers import fill_tax, make_job, make_org, patch_hooks

from arbiter.billing import ledger
from arbiter.community import payouts, profiles, queue, review, testing
from arbiter.community.errors import Conflict, Invalid
from arbiter.models import LedgerEntry, ReviewerPair, TestAttempt


def _answers_for(test_items):
    """Perfect answers: report every expected error and submit the reference."""
    return [
        {"index": i, "target": it.get("reference") or it["target"], "errors": it.get("errors", [])}
        for i, it in enumerate(test_items)
    ]


def test_full_lifecycle_apply_to_settled_payout(db, monkeypatch):
    spy = patch_hooks(monkeypatch)
    testing.seed_default_tests(db)
    testing.seed_default_tests(db)  # idempotent

    user, profile = profiles.apply(
        db,
        name="Ana",
        email="Ana@Example.test",
        password="long enough pw",
        country="rs",
        pairs=[{"source_lang": "en", "target_lang": "sr"}],
        domains=["software"],
    )
    assert user.role == "reviewer" and user.email == "ana@example.test"
    assert profiles.verify_password(user, "long enough pw")
    with pytest.raises(Conflict):
        profiles.apply(
            db, name="x", email="ana@example.test", password="12345678", country="RS", pairs=[("en", "sr")]
        )

    view = profiles.profile_view(db, profile)
    assert view["level"] == "candidate" and view["status"] == "applied"
    assert view["pairs"][0]["status"] == "testing" and view["tax_info_complete"] is False
    assert view["balance"] == "0.00"

    tests = testing.available_tests(db, profile)
    by_kind = {t["kind"]: t for t in tests}
    assert set(by_kind) == {"language", "practical"}  # only en->sr, not en->de
    assert by_kind["language"]["status"] == "available"
    assert by_kind["practical"]["status"] == "locked"  # language test first

    lang = testing.start(db, profile, by_kind["language"]["id"])
    assert all(set(it) == {"index", "source", "target"} for it in lang["items"])  # no answer keys
    from arbiter.models import ReviewerTest

    lang_test = db.get(ReviewerTest, by_kind["language"]["id"])
    res = testing.grade(db, profile, lang["attempt_id"], _answers_for(lang_test.items))
    assert res["passed"] is True and res["score"] >= 99
    assert profile.level == "candidate"  # practical still missing

    prac = testing.start(db, profile, by_kind["practical"]["id"])
    prac_test = db.get(ReviewerTest, by_kind["practical"]["id"])
    res = testing.grade(db, profile, prac["attempt_id"], _answers_for(prac_test.items))
    assert res["passed"] is True
    pair = db.query(ReviewerPair).filter_by(reviewer_id=profile.id).one()
    assert pair.status == "active"
    assert profile.level == "reviewer" and profile.status == "active"
    assert {t["status"] for t in testing.available_tests(db, profile)} == {"passed"}

    # Work arrives.
    org = make_org(db)
    job, segs = make_job(
        db, org, ["Save your changes before closing the window.", "Click ⟦1⟧Next⟦/1⟧ to continue."]
    )
    for s in segs:
        queue.create_task(db, s, job)

    task = queue.next_task(db, profile)
    assert task is not None and task["segment_id"] == segs[0].id
    assert task["context_after"] == segs[1].source_tagged and task["context_before"] is None
    assert task["terms"] == [{"source_term": "window", "target_term": "prozor", "kind": "mandatory"}]
    assert "is_control" not in task and "expected" not in task
    assert queue.next_task(db, profile)["id"] == task["id"]  # one held task at a time

    out = review.submit(
        db,
        profile,
        task["id"],
        decision="edit",
        target_tagged="Sačuvajte izmene pre zatvaranja prozora.",
        errors=[{"dimension": "accuracy", "severity": "major", "span": "posle", "explanation": "wrong"}],
        comment="",
        time_ms=60_000,
    )
    # edit: 0.01 + 7 words * 0.012 = 0.094 -> 0.09
    assert out == {"ok": True, "pay_amount": "0.09", "state": "payable"}
    assert spy.reviewed[0]["segment_id"] == segs[0].id and spy.reviewed[0]["decision"] == "edit"
    assert payouts.balance(db, profile.id) == Decimal("0.09")
    assert job.cost_reviewers == Decimal("0.09")

    # Second task: accept.
    t2 = queue.next_task(db, profile)
    out2 = review.submit(db, profile, t2["id"], decision="accept", time_ms=30_000)
    assert out2["pay_amount"] == "0.02"  # 4 words * 0.004 = 0.016 -> minimum 0.02
    assert payouts.balance(db, profile.id) == Decimal("0.11")
    assert queue.next_task(db, profile) is None

    # Payout: threshold not reached, then lowered.
    assert payouts.run_payouts(db)["created"] == 0
    profile.payout_threshold = Decimal("0.10")
    fill_tax(db, profile)
    provider = payouts.MockPayoutProvider()
    run = payouts.run_payouts(db, provider=provider)
    assert run["created"] == 1 and run["total"] == "0.11"
    assert run["send"]["settled"] == 1
    assert payouts.balance(db, profile.id) == Decimal("0")
    assert ledger.account_balance(db, ledger.IN_TRANSIT) == Decimal("0")
    assert ledger.account_balance(db, ledger.CASH) == Decimal("0.11")
    total = sum(e.amount for e in db.query(LedgerEntry))
    assert total == 0  # double entry always balances

    earnings = payouts.earnings_view(db, profile)
    assert earnings["balance"] == "0.00" and earnings["paid"] == "0.11" and earnings["pending"] == "0.00"
    assert {e["kind"] for e in earnings["entries"]} == {"review_pay", "payout"}


def test_failed_test_locks_retest_for_30_days_and_late_submit_fails(db):
    testing.seed_default_tests(db)
    _u, profile = profiles.apply(
        db, name="B", email="b@example.test", password="12345678", country="DE", pairs=[("en", "de")]
    )
    lang = next(t for t in testing.available_tests(db, profile) if t["kind"] == "language")
    att = testing.start(db, profile, lang["id"])
    res = testing.grade(db, profile, att["attempt_id"], [])
    assert res == {"score": 0.0, "passed": False}
    status = next(t for t in testing.available_tests(db, profile) if t["id"] == lang["id"])
    assert status["status"] == "failed" and status["retest_after"] is not None
    with pytest.raises(Conflict):
        testing.start(db, profile, lang["id"])

    # After the lock expires the test is available again; a late submission fails even if perfect.
    pair = db.query(ReviewerPair).filter_by(reviewer_id=profile.id).one()
    pair.retest_after = pair.retest_after - timedelta(days=31)
    att2 = testing.start(db, profile, lang["id"])
    a = db.get(TestAttempt, att2["attempt_id"])
    a.started_at = a.started_at - timedelta(hours=2)
    from arbiter.models import ReviewerTest

    items = db.get(ReviewerTest, lang["id"]).items
    res2 = testing.grade(db, profile, att2["attempt_id"], _answers_for(items))
    assert res2["passed"] is False and res2.get("late") is True


def test_false_positives_on_clean_items_cost_points():
    item = {"source": "a", "target": "b", "errors": [], "reference": "b"}
    assert testing.grade_item(item, {"index": 0, "target": "b", "errors": []}) == pytest.approx(1.0)
    noisy = {
        "index": 0,
        "target": "b",
        "errors": [{"span": "b", "category": "accuracy", "severity": "major"}],
    }
    assert testing.grade_item(item, noisy) == pytest.approx(0.7 * 0.5 + 0.3)


def test_tax_info_validation(db):
    _u, profile = profiles.apply(
        db, name="C", email="c@example.test", password="12345678", country="RS", pairs=[("en", "sr")]
    )
    with pytest.raises(Invalid):
        profiles.update_tax_info(db, profile, payout_method="cash")
    with pytest.raises(Invalid):
        profiles.update_tax_info(db, profile, date_of_birth="01.01.1990")
    fill_tax(db, profile)
    assert profiles.profile_view(db, profile)["tax_info_complete"] is True
    view = profiles.set_status(db, profile.id, "suspended", level="senior")
    assert view["status"] == "suspended" and view["level"] == "senior"
