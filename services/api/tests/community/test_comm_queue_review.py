from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from comm_helpers import make_job, make_org, make_reviewer, patch_hooks

from arbiter import db as dbmod
from arbiter.community import disputes, payouts, queue, review, scoring
from arbiter.community.errors import Conflict, Invalid, NotFound
from arbiter.models import Dispute, ReviewerPair, ReviewerProfile, ReviewerScoreEvent, ReviewTask, utcnow


def test_skip_locked_two_reviewers_never_get_the_same_task(db):
    org = make_org(db)
    job, segs = make_job(db, org, ["One two three.", "Four five six."])
    for s in segs:
        queue.create_task(db, s, job)
    a = make_reviewer(db)
    b = make_reviewer(db)
    c = make_reviewer(db)
    db.commit()

    factory = dbmod.session_factory()
    s1, s2, s3 = factory(), factory(), factory()
    try:
        t1 = queue.next_task(s1, s1.get(ReviewerProfile, a.id))  # row locked, not committed
        t2 = queue.next_task(s2, s2.get(ReviewerProfile, b.id))
        assert t1 is not None and t2 is not None
        assert t1["id"] != t2["id"]
        # Both tasks are locked by open transactions: the third reviewer gets nothing, no waiting.
        assert queue.next_task(s3, s3.get(ReviewerProfile, c.id)) is None
        s1.commit()
        s2.commit()
    finally:
        for s in (s1, s2, s3):
            s.rollback()
            s.close()
    db.expire_all()
    held = db.query(ReviewTask).filter_by(state="held").all()
    assert {t.reviewer_id for t in held} == {a.id, b.id}


def test_priority_level_and_pair_routing(db, monkeypatch):
    patch_hooks(monkeypatch)
    org = make_org(db)
    late_job, late = make_job(db, org, ["Due later."], due_in_minutes=600)
    soon_job, soon = make_job(db, org, ["Due soon."], due_in_minutes=30)
    de_job, de = make_job(db, org, ["German pair."], target_lang="de")
    senior_job, senior_seg = make_job(db, org, ["Needs a senior."], due_in_minutes=1)
    queue.create_task(db, late[0], late_job)
    queue.create_task(db, soon[0], soon_job)
    queue.create_task(db, de[0], de_job)
    queue.create_task(db, senior_seg[0], senior_job, min_level="senior")
    r = make_reviewer(db)
    got = queue.next_task(db, r)
    assert got["segment_id"] == soon[0].id  # senior task skipped, de pair not served
    review.submit(db, r, got["id"], decision="accept", time_ms=10_000)
    assert queue.next_task(db, r)["segment_id"] == late[0].id

    s = make_reviewer(db, level="senior", pairs=(("en", "sr"),))
    assert queue.next_task(db, s)["segment_id"] == senior_seg[0].id
    assert queue.next_task(db, make_reviewer(db), target_lang="de") is None
    assert queue.next_task(db, make_reviewer(db, pairs=(("en", "de"),)))["segment_id"] == de[0].id


def test_hold_expiry_and_release(db):
    org = make_org(db)
    job, segs = make_job(db, org, ["A segment here."])
    task = queue.create_task(db, segs[0], job)
    r = make_reviewer(db)
    got = queue.next_task(db, r, hold_minutes=10)
    assert got["id"] == task.id and task.state == "held"
    assert queue.expire_holds(db) == 0
    task.hold_expires_at = utcnow() - timedelta(minutes=1)
    assert queue.expire_holds(db) == 1
    assert task.state == "queued" and task.reviewer_id is None
    with pytest.raises(NotFound):  # the hold is gone: the task is no longer theirs
        review.submit(db, r, task.id, decision="accept", time_ms=10_000)

    queue.next_task(db, r)
    queue.release(db, r, task.id)
    assert task.state == "queued"


def test_skip_is_not_offered_again_to_same_reviewer(db, monkeypatch):
    patch_hooks(monkeypatch)
    org = make_org(db)
    job, segs = make_job(db, org, ["Hard segment to review."])
    task = queue.create_task(db, segs[0], job)
    a, b = make_reviewer(db), make_reviewer(db)
    queue.next_task(db, a)
    assert review.submit(db, a, task.id, decision="skip", time_ms=1000)["pay_amount"] == "0.00"
    assert task.state == "queued"
    assert queue.next_task(db, a) is None
    assert queue.next_task(db, b)["id"] == task.id


def test_speed_flag_records_but_does_not_block(db, monkeypatch):
    spy = patch_hooks(monkeypatch)
    org = make_org(db)
    job, segs = make_job(db, org, ["one two three four five six seven eight nine ten"])
    task = queue.create_task(db, segs[0], job)
    r = make_reviewer(db)
    queue.next_task(db, r)
    out = review.submit(db, r, task.id, decision="accept", time_ms=900)  # < 10 * 600 ms
    assert out["ok"] is True and out["pay_amount"] == "0.04"
    assert r.fraud_flags == 1
    ev = db.query(ReviewerScoreEvent).filter_by(reviewer_id=r.id, kind="speed_flag").one()
    assert ev.task_id == task.id
    assert len(spy.reviewed) == 1


def test_tag_breaking_edit_is_rejected_but_dropped_pair_is_allowed(db, monkeypatch):
    spy = patch_hooks(monkeypatch)
    org = make_org(db)
    job, segs = make_job(db, org, ["Click ⟦1⟧Next⟦/1⟧ to see ⟦2/⟧ details."])
    task = queue.create_task(db, segs[0], job)
    r = make_reviewer(db)
    queue.next_task(db, r)
    with pytest.raises(Invalid) as e:  # standalone code lost (D-009: error)
        review.submit(db, r, task.id, decision="edit", target_tagged="Kliknite ⟦1⟧Dalje⟦/1⟧.", time_ms=9000)
    assert e.value.details["tag_issues"][0]["code_id"] == "2"
    with pytest.raises(Invalid):  # half a pair
        review.submit(db, r, task.id, decision="edit", target_tagged="Kliknite ⟦1⟧Dalje ⟦2/⟧.", time_ms=9000)
    assert task.state == "held"
    out = review.submit(db, r, task.id, decision="edit", target_tagged="Kliknite Dalje ⟦2/⟧.", time_ms=9000)
    assert out["state"] == "payable"
    assert spy.reviewed[0]["target_tagged"] == "Kliknite Dalje ⟦2/⟧."


def test_escalate_and_control_sample_hooks(db, monkeypatch):
    spy = patch_hooks(monkeypatch)
    org = make_org(db)
    job, segs = make_job(db, org, ["Dosage: two tablets daily.", "Auto approved text here."])
    segs[1].is_control_sample = True
    segs[1].state = "auto_approved"
    t1 = queue.create_task(db, segs[0], job)
    t2 = queue.create_task(db, segs[1], job)
    r = make_reviewer(db)
    queue.next_task(db, r)
    out = review.submit(db, r, t1.id, decision="escalate", comment="medical term", time_ms=5000)
    assert out["pay_amount"] == "0.00" and t1.state == "accepted"
    assert spy.escalated == [{"segment_id": segs[0].id, "reviewer_id": r.id, "reason": "medical term"}]

    queue.next_task(db, r)
    review.submit(
        db,
        r,
        t2.id,
        decision="edit",
        target_tagged="Ispravljen tekst.",
        errors=[{"dimension": "accuracy", "severity": "critical", "span": "x", "explanation": "y"}],
        time_ms=5000,
    )
    assert spy.reviewed == []  # a control sample never moves the segment
    assert spy.control[0]["escaped"] is True and spy.control[0]["segment_id"] == segs[1].id
    assert t2.state == "payable"  # blind checks are real work and paid


def test_control_fail_rejected_then_dispute_overturned_and_paid(db, monkeypatch):
    spy = patch_hooks(monkeypatch)
    org = make_org(db)
    job, segs = make_job(db, org, ["Save your changes before closing the window."])
    task = queue.create_task(
        db,
        segs[0],
        job,
        is_control=True,
        expected={"decision": "edit", "errors": [{"span": "posle", "severity": "major"}]},
    )
    r = make_reviewer(db)
    assert queue.next_task(db, r)["id"] == task.id
    out = review.submit(db, r, task.id, decision="accept", time_ms=60_000)
    assert out == {"ok": True, "pay_amount": "0.00", "state": "rejected"}
    assert spy.reviewed == []  # control tasks never reach the pipeline
    assert payouts.balance(db, r.id) == 0
    pair = db.query(ReviewerPair).filter_by(reviewer_id=r.id).one()
    assert (pair.control_seen, pair.control_passed) == (1, 0)
    score_after_fail = r.score
    assert score_after_fail < 70

    d = disputes.open_dispute(db, r, task.id, "The source says before; the target was correct.")
    assert task.state == "disputed"
    with pytest.raises(Conflict):
        disputes.open_dispute(db, r, task.id, "again")
    view = disputes.decide(db, d["id"], "overturned", "Reviewer is right.", "usr_admin")
    assert view["status"] == "overturned"
    assert task.state == "payable"
    assert payouts.balance(db, r.id) == Decimal("0.03")  # accept: 7 * 0.004 = 0.028 -> 0.03
    assert pair.control_passed == 1
    assert r.score == pytest.approx(72.73)  # the overturned fail now counts as a pass: (1 + 7) / (1 + 10)


def test_dispute_window_upheld_and_expiry(db, monkeypatch):
    patch_hooks(monkeypatch)
    org = make_org(db)
    job, segs = make_job(db, org, ["First control.", "Second control.", "Third control."])
    exp = {"decision": "edit", "errors": [{"span": "control", "severity": "major"}]}
    tasks = [queue.create_task(db, s, job, is_control=True, expected=exp) for s in segs]
    r = make_reviewer(db)
    for t in tasks:
        queue.next_task(db, r)
        review.submit(db, r, t.id, decision="accept", time_ms=60_000)
    assert all(t.state == "rejected" for t in tasks)

    d1 = disputes.open_dispute(db, r, tasks[0].id, "disagree")
    disputes.decide(db, d1["id"], "upheld", "Error was real.", "usr_admin")
    assert tasks[0].state == "rejected"
    assert db.query(ReviewerScoreEvent).filter_by(kind="dispute_lost").count() == 1

    d2 = disputes.open_dispute(db, r, tasks[1].id, "disagree")
    dispute = db.get(Dispute, d2["id"])
    dispute.due_at = utcnow() - timedelta(minutes=1)
    assert disputes.expire(db) == 1
    assert dispute.status == "expired" and tasks[1].state == "payable"

    tasks[2].submitted_at = utcnow() - timedelta(days=8)
    with pytest.raises(Conflict):
        disputes.open_dispute(db, r, tasks[2].id, "too late")


def test_score_formula_prior_demotion_and_promotion(db):
    now = utcnow()
    assert scoring.compute([], now) == 70.0
    assert scoring.compute([("control_pass", now)] * 10, now) == 85.0
    assert scoring.compute([("control_fail", now)] * 10, now) == 35.0
    old = now - timedelta(days=90)
    assert scoring.compute([("control_fail", old)] * 2, now) == scoring.compute([("control_fail", now)], now)

    r = make_reviewer(db)
    pair = db.query(ReviewerPair).filter_by(reviewer_id=r.id).one()
    org = make_org(db)
    job, segs = make_job(db, org, [f"Segment {i}." for i in range(20)])
    for s in segs:
        t = queue.create_task(db, s, job, is_control=True, expected={"decision": "accept", "errors": []})
        pair.control_seen += 1
        scoring.record_event(db, r, "control_fail", task=t)
    assert pair.score < 60 and pair.status == "demoted"
    assert queue.next_task(db, r) is None  # demoted pair gets no work

    s = make_reviewer(db)
    s.decisions_total = 200
    spair = db.query(ReviewerPair).filter_by(reviewer_id=s.id).one()
    spair.control_seen = 50
    for _ in range(50):
        scoring.record_event(db, s, "control_pass")
    assert s.score >= 90 and s.level == "senior"
