from __future__ import annotations

from pipe_helpers import make_job
from sqlalchemy import select

from arbiter import storage
from arbiter.models import Job, ProvenanceEvent, ReviewTask, Segment
from arbiter.pipeline import orchestrator
from arbiter.pipeline.worker import run_until_idle


def _run(db, job):
    orchestrator.start_job(db, job)
    db.commit()
    run_until_idle()
    db.expire_all()
    return db.get(Job, job.id)


def test_auto_tier_end_to_end(db):
    _, job = make_job(db, tier="auto")
    job = _run(db, job)
    segs = db.execute(select(Segment).where(Segment.job_id == job.id)).scalars().all()
    assert segs, "segments created"
    states = {s.state for s in segs}
    print(job.state, states, [(s.qe_score, s.decision, s.reasons) for s in segs])
    assert job.state in ("delivered", "review")
    assert db.execute(select(ProvenanceEvent).where(ProvenanceEvent.job_id == job.id)).first()
    if job.state == "delivered":
        assert storage.get(job.output_storage_key)


def test_full_tier_waits_for_humans(db):
    _, job = make_job(db, tier="full")
    job = _run(db, job)
    assert job.state == "review"
    tasks = db.execute(select(ReviewTask).where(ReviewTask.job_id == job.id)).scalars().all()
    assert len(tasks) == job.segment_count
