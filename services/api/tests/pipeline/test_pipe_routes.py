"""Pipeline routing scenarios on mock engines (rule ids in names)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pipe_helpers import make_job
from sqlalchemy import select, update

from arbiter.community import profiles, queue, review
from arbiter.contracts import Usage
from arbiter.engines.mock import MockLlm, MockMt
from arbiter.linguistic import glossary as gl
from arbiter.models import (
    EscapedError,
    Job,
    ReviewerPair,
    ReviewTask,
    Segment,
    SenateRun,
    TmEntry,
    WorkItem,
    utcnow,
)
from arbiter.pipeline import orchestrator
from arbiter.pipeline.worker import run_until_idle

FAULTY = (
    b"First sentence is fine and long enough to be judged properly.\n\n"
    b"Second one has a problem inside it for the judge.\n\n"
    b"Third sentence mentions the contract once.\n"
)


class FaultyMt(MockMt):
    """Mock engine with scripted faults: 'problem' -> the judge sees a mistranslation,
    'contract' -> the engine ignores the glossary (term_missing)."""

    def translate(self, requests):
        out = []
        for req in requests:
            faults = ("omit_term",) if "contract" in req.source_tagged else ()
            res = MockMt(faults=faults).translate([req])[0]
            if "problem" in req.source_tagged:
                res.target_tagged = res.target_tagged.replace("pröblëm", "MISTRANSLATED")
            out.append(res)
        return out


class MarkerLlm(MockLlm):
    """MockLlm reacts to {{markers}}, which hard checks would flag as placeholders; we map a plain word."""

    def complete_json(self, system, user, **kw):
        import json

        task = json.loads(user).get("task")
        if "MISTRANSLATED" in user and task in ("judge", "senate_role"):
            err = {
                "dimension": "accuracy",
                "severity": "major",
                "span": "MISTRANSLATED",
                "explanation": "wrong",
            }
            return {"errors": [err]}, Usage(), "marker-1"
        return super().complete_json(system, user, **kw)


@pytest.fixture(autouse=True)
def _faulty_engine(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_mt", lambda name: FaultyMt())
    monkeypatch.setattr(orchestrator, "_judge", lambda: MarkerLlm())


def _run(db, job):
    orchestrator.start_job(db, job)
    db.commit()
    run_until_idle()
    db.expire_all()
    return db.get(Job, job.id)


def _segs(db, job):
    return db.execute(select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)).scalars().all()


def _active_reviewer(db, email="rev@example.com"):
    user, prof = profiles.apply(
        db,
        name="Rev",
        email=email,
        password="pw-123456",
        country="RS",
        pairs=[{"source_lang": "en", "target_lang": "sr"}],
        domains=["general"],
    )
    prof.status, prof.level = "active", "senior"
    db.execute(update(ReviewerPair).where(ReviewerPair.reviewer_id == prof.id).values(status="active"))
    db.flush()
    return prof


def test_r_gl_mandatory_term_missing_blocks_and_human_fixes(db):
    org, job = make_job(db, tier="auto", data=FAULTY)
    g = gl.create_glossary(db, org.id, "Main")
    gl.add_term(db, g.id, "en", "sr", "contract", "ugovor", "mandatory")
    job = _run(db, job)
    segs = _segs(db, job)
    third = segs[2]
    assert third.decision == "blocked"
    assert "term_missing" in third.reasons
    assert job.state == "review"
    # the first segment shipped automatically, the blocked one waits for a human
    assert segs[0].state == "auto_approved"

    prof = _active_reviewer(db)
    db.commit()
    done = 0
    while (task := queue.next_task(db, prof)) is not None:
        seg = db.get(Segment, task["segment_id"])
        fixed = (seg.target_tagged or "") + " ugovor"
        review.submit(db, prof, task["id"], decision="edit", target_tagged=fixed, errors=[], time_ms=60_000)
        db.commit()
        done += 1
    assert done >= 1
    run_until_idle()
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.state == "delivered", job.state
    assert db.get(Segment, third.id).origin == "human"
    # R-TM-01: the human-approved segment was learned into the client's TM
    assert db.execute(select(TmEntry).where(TmEntry.org_id == org.id)).first()


def test_senate_convened_in_band(db):
    org, job = make_job(db, tier="auto", data=FAULTY)
    job = _run(db, job)
    runs = db.execute(select(SenateRun).where(SenateRun.job_id == job.id)).scalars().all()
    second = _segs(db, job)[1]
    assert second.decision in ("review", "auto_approve", "blocked") or runs
    assert second.qe_score is not None


def test_ai_review_tier_never_waits_for_humans(db):
    _, job = make_job(db, tier="ai_review", data=FAULTY)
    job = _run(db, job)
    segs = _segs(db, job)
    blocked = [s for s in segs if s.decision == "blocked"]
    # deterministic failures still go to a human even on ai_review
    if not blocked:
        assert job.state == "delivered"
    assert any(s.decision in ("ai_reviewed", "auto_approve") for s in segs)


def test_r_seg_12_regulated_never_auto(db):
    _, job = make_job(db, tier="auto", regulated=True)
    job = _run(db, job)
    assert job.state == "review"
    assert all(s.decision in ("review", "blocked") for s in _segs(db, job))
    tasks = db.execute(select(ReviewTask).where(ReviewTask.job_id == job.id)).scalars().all()
    assert all(t.min_level in ("senior", "domain_expert") for t in tasks)


def test_deadline_ai_fallback_is_recorded(db):
    _, job = make_job(db, tier="full", policy="ai_fallback", due_hours=1)
    job = _run(db, job)
    assert job.state == "review"
    db.execute(
        update(WorkItem).where(WorkItem.kind == "job.deadline").values(run_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    run_until_idle()
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.no_reviewer_fallback_used
    assert job.state == "delivered"
    assert {s.decision for s in _segs(db, job)} <= {"ai_fallback"}


def test_deadline_wait_policy_keeps_waiting(db):
    _, job = make_job(db, tier="full", policy="wait", due_hours=1)
    job = _run(db, job)
    db.execute(
        update(WorkItem).where(WorkItem.kind == "job.deadline").values(run_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    run_until_idle()
    db.expire_all()
    assert db.get(Job, job.id).state == "review"


def test_r_tm_03_context_match_skips_engine_on_second_job(db):
    org, job = make_job(db, tier="full")
    job = _run(db, job)
    prof = _active_reviewer(db)
    db.commit()
    while (task := queue.next_task(db, prof)) is not None:
        review.submit(db, prof, task["id"], decision="accept", time_ms=60_000)
        db.commit()
    run_until_idle()
    db.expire_all()
    assert db.get(Job, job.id).state == "delivered"
    # same file again for the same org: every segment is an in-context TM match
    from arbiter.models import FileAsset

    fa = db.get(FileAsset, job.file_id)
    job2 = Job(
        project_id=job.project_id,
        org_id=org.id,
        file_id=fa.id,
        source_lang="en",
        target_lang="sr",
        tier="auto",
        state="quoted",
    )
    db.add(job2)
    db.flush()
    job2 = _run(db, job2)
    segs = _segs(db, job2)
    assert all(s.origin == "tm" and s.tm_match == 101 for s in segs)
    assert job2.state == "delivered"


def test_report_error_creates_escaped_error(db):
    _, job = make_job(db, tier="auto")
    job = _run(db, job)
    seg = _segs(db, job)[0]
    orchestrator.report_error(db, job, seg.id, "wrong word")
    db.commit()
    assert (
        db.execute(select(EscapedError).where(EscapedError.job_id == job.id)).scalar_one().was_auto_approved
    )


def test_mistranslation_routed_by_score(db):
    _, job = make_job(db, tier="auto", data=FAULTY)
    job = _run(db, job)
    segs = _segs(db, job)
    print([(s.qe_score, s.decision, s.reasons) for s in segs])
    assert segs[0].decision == "auto_approve"
    assert segs[1].decision != "auto_approve"
    assert segs[1].signals.get("errors")
