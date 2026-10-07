"""The pipeline executes workflows: second review, client review, QE threshold, senate count,
default thresholds, evidence download header, ai_review final decision."""

from __future__ import annotations

import json

from agency_helpers import active_reviewer, client, drain, order, register, review_all, workflow
from sqlalchemy import select

from arbiter.contracts import Usage
from arbiter.engines.mock import MockLlm
from arbiter.models import Job, ReviewTask, Segment, SenateRun, WebhookDelivery
from arbiter.pipeline import orchestrator

FULL_TWO = ["tm", "mt", "qe", "human_review", "second_review", "delivery"]


def _segs(db, job_id):
    return db.execute(select(Segment).where(Segment.job_id == job_id).order_by(Segment.seq)).scalars().all()


def test_second_review_needs_two_different_reviewers_before_delivery(db):
    c = client()
    h = register(c)
    wf = workflow(c, h, "full", FULL_TWO)
    job_id = order(c, h, workflow_template_id=wf["id"])["jobs"][0]["id"]
    drain()
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["state"] == "review"
    n_segs = len(_segs(db, job_id))

    first = active_reviewer(db, "first@example.com")
    second = active_reviewer(db, "second@example.com")
    assert review_all(db, first) == n_segs
    drain()
    db.expire_all()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "review"  # one review is not enough
    segs = _segs(db, job_id)
    assert all(s.state == "needs_review" for s in segs)
    assert all(len(s.signals["reviews"]) == 1 for s in segs)
    assert all("second_review" in s.reasons for s in segs)
    # the second task is never offered to the first reviewer, and needs a senior
    assert review_all(db, first) == 0
    second_tasks = (
        db.execute(select(ReviewTask).where(ReviewTask.job_id == job_id, ReviewTask.state == "queued"))
        .scalars()
        .all()
    )
    assert len(second_tasks) == n_segs and {t.min_level for t in second_tasks} == {"senior"}

    assert review_all(db, second) == n_segs
    drain()
    db.expire_all()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "delivered", job
    for s in _segs(db, job_id):
        reviewers = [r["reviewer_id"] for r in s.signals["reviews"]]
        assert reviewers == [first.id, second.id]
        assert s.decision == "reviewed" and s.state == "delivered"


def test_client_review_blocks_delivery_until_client_approves(db):
    c = client()
    h = register(c)
    hook = c.post(
        "/v1/webhooks", headers=h, json={"url": "http://hooks.example/x", "events": ["job.needs_attention"]}
    )
    assert hook.status_code == 201
    wf = workflow(c, h, "auto", ["tm", "mt", "qe", "client_review", "delivery"])
    job_id = order(c, h, workflow_template_id=wf["id"])["jobs"][0]["id"]
    # not finished yet: approving is refused
    r = c.post(f"/v1/jobs/{job_id}/client-approve", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_awaiting_client"
    drain()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "review" and job["awaiting_client_approval"] is True
    assert job["client_approved_at"] is None
    assert all(s.state == "auto_approved" for s in _segs(db, job_id))
    assert c.get(f"/v1/jobs/{job_id}/download", headers=h).status_code == 409
    exc = c.get("/v1/exceptions", headers=h).json()["items"]
    assert [e["kind"] for e in exc] == ["client_review"] and exc[0]["job_id"] == job_id
    payloads = [d.payload["data"] for d in db.execute(select(WebhookDelivery)).scalars()]
    assert {"job_id": job_id, "reason": "client_review"} in payloads
    drain()  # nothing moves on its own
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["state"] == "review"

    r = c.post(f"/v1/jobs/{job_id}/client-approve", headers=h)
    assert r.status_code == 200 and r.json()["state"] == "ready" and r.json()["client_approved_at"]
    drain()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "delivered" and job["awaiting_client_approval"] is False
    assert c.get(f"/v1/jobs/{job_id}/download", headers=h).status_code == 200
    # approving again is a no-op
    assert c.post(f"/v1/jobs/{job_id}/client-approve", headers=h).json()["state"] == "delivered"
    assert c.get("/v1/exceptions", headers=h).json()["items"] == []


def test_client_approve_needs_client_review_step_and_tenancy(db):
    c = client()
    h = register(c)
    job_id = order(c, h, tier="auto")["jobs"][0]["id"]
    drain()
    r = c.post(f"/v1/jobs/{job_id}/client-approve", headers=h)
    assert r.status_code == 409 and "no client review step" in r.json()["error"]["message"]
    hb = register(c, "b@example.com", "Other")
    assert c.post(f"/v1/jobs/{job_id}/client-approve", headers=hb).status_code == 404


def test_workflow_qe_threshold_and_min_level(db):
    c = client()
    h = register(c)
    wf = workflow(
        c,
        h,
        "full",
        ["tm", "mt", "qe", "human_review", "delivery"],
        qe={"threshold": 91.5},
        human_review={"min_level": "domain_expert"},
    )
    job_id = order(c, h, workflow_template_id=wf["id"])["jobs"][0]["id"]
    drain()
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["threshold"] == 91.5
    tasks = db.execute(select(ReviewTask).where(ReviewTask.job_id == job_id)).scalars().all()
    assert tasks and {t.min_level for t in tasks} == {"domain_expert"}


def test_translation_senate_step_counts_convenings(db):
    c = client()
    h = register(c)
    wf = workflow(c, h, "auto", ["tm", "translation_senate", "qe", "delivery"])
    job_id = order(c, h, workflow_template_id=wf["id"])["jobs"][0]["id"]
    drain()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    runs = db.execute(select(SenateRun).where(SenateRun.job_id == job_id)).scalars().all()
    assert job["senate_count"] == len(runs) and len(runs) >= job["segment_count"]
    segs = c.get(f"/v1/jobs/{job_id}/segments", headers=h).json()["items"]
    assert all(str(s["signals"]["translation_senate"]).startswith("winner:") for s in segs)
    for r in runs:
        if r.purpose == "review":
            assert db.get(Segment, r.segment_id).signals["senate"] == r.outcome


class ProblemLlm(MockLlm):
    """Judge and senate flag the pseudo-translated word "problem" as a critical accuracy error."""

    def complete_json(self, system, user, **kw):
        task = json.loads(user).get("task")
        if task in ("judge", "senate_role") and "pröblëm" in user:
            err = {"dimension": "accuracy", "severity": "critical", "span": "pröblëm", "explanation": "wrong"}
            return {"errors": [err]}, Usage(), "problem-1"
        return super().complete_json(system, user, **kw)


def test_threshold_row_created_and_evidence_header_and_no_ai_edit(db, monkeypatch):
    monkeypatch.setattr(orchestrator, "_judge", lambda: ProblemLlm())
    c = client()
    h = register(c)
    assert c.get("/v1/quality/thresholds", headers=h).json()["items"] == []
    doc = (
        b"First line is fine and long enough to be judged properly by the mock.\n\n"
        b"Second line has a problem that the judge flags.\n"
    )
    job_id = order(c, h, data=doc, tier="ai_review")["jobs"][0]["id"]
    drain()
    thr = c.get("/v1/quality/thresholds", headers=h).json()["items"]
    assert [(t["content_type"], t["target_lang"], t["value"]) for t in thr] == [("general", "sr", 78.0)]
    job = db.get(Job, job_id)
    decisions = [s.decision for s in _segs(db, job_id)]
    assert "ai_edit" not in decisions
    assert "ai_reviewed" in decisions, decisions
    assert job.state == "delivered"
    ev = c.get(f"/v1/jobs/{job_id}/evidence?format=json", headers=h)
    assert ev.status_code == 200 and f"evidence-{job_id}.json" in ev.headers["content-disposition"]
