"""Pipeline + engine routing: EU processing (D-052), budgets, provenance and evidence."""

from __future__ import annotations

import orjson
from pipe_helpers import make_job
from sqlalchemy import func, select

from arbiter import storage
from arbiter.engines import routing
from arbiter.engines.errors import BudgetExceeded
from arbiter.engines.mock import MockLlm, MockMt
from arbiter.models import Job, ProvenanceEvent, Segment, Webhook, WebhookDelivery, WorkItem
from arbiter.pipeline import evidence, orchestrator
from arbiter.pipeline.worker import run_until_idle


def _run(db, job):
    orchestrator.start_job(db, job)
    db.commit()
    run_until_idle()
    db.expire_all()
    return db.get(Job, job.id)


def _events(db, job, name):
    return (
        db.execute(
            select(ProvenanceEvent).where(ProvenanceEvent.job_id == job.id, ProvenanceEvent.event == name)
        )
        .scalars()
        .all()
    )


def test_eu_org_runs_on_eu_engines_and_records_region(db):
    org, job = make_job(db, tier="auto")
    org.settings = {"processing_region": "eu"}
    db.flush()
    job = _run(db, job)
    assert job.state in ("delivered", "review"), job.failure_reason
    routes = _events(db, job, "engine_route")
    assert {e.data["purpose"] for e in routes} >= {"mt", "judge"}
    assert all(e.data["processing_region"] == "eu" for e in routes)
    target_set = _events(db, job, "target_set")
    assert any(e.data.get("processing_region") == "eu" and e.model_version for e in target_set)
    pack = evidence.build(db, job)
    assert pack["processing"]["region"] == "eu"
    assert pack["processing"]["routes"]["mt"]["engine"] == "mock-mt"
    assert pack["processing"]["models"]
    if job.state == "delivered":
        stored = orjson.loads(storage.get(job.evidence_storage_key))
        assert stored["processing"]["org_setting"] == "eu"


def test_eu_org_without_eu_engine_fails_visibly_and_never_falls_back(db, monkeypatch):
    monkeypatch.setattr(MockMt, "region", "global")
    monkeypatch.setattr(MockLlm, "region", "global")
    org, job = make_job(db, tier="auto")
    org.settings = {"processing_region": "eu"}
    db.flush()
    job = _run(db, job)
    assert job.state == "failed"
    assert "no EU engine configured" in (job.failure_reason or "")
    blocked = _events(db, job, "routing_blocked")
    assert blocked and blocked[0].data["code"] == "no_eu_engine"
    segs = db.execute(select(Segment).where(Segment.job_id == job.id)).scalars().all()
    assert segs and all(s.target_tagged is None and s.state == "pending" for s in segs)


def test_global_org_unaffected_by_engine_regions(db, monkeypatch):
    monkeypatch.setattr(MockMt, "region", "global")
    monkeypatch.setattr(MockLlm, "region", "global")
    _, job = make_job(db, tier="auto")
    job = _run(db, job)
    assert job.state in ("delivered", "review")


def test_budget_exceeded_needs_attention_and_retries_hourly(db, monkeypatch):
    import httpx

    from arbiter import webhooks

    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(lambda r: httpx.Response(200)))
    org, job = make_job(db, tier="auto")
    db.add(
        Webhook(org_id=org.id, url="https://hooks.example.com/x", secret="s", events=["job.needs_attention"])
    )
    db.flush()
    real = routing.choose

    def capped(session, **kw):
        if kw["purpose"] == "mt":
            raise BudgetExceeded(["deepl"])
        return real(session, **kw)

    monkeypatch.setattr(routing, "choose", capped)
    orchestrator.start_job(db, job)
    db.commit()
    run_until_idle()
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.state == "running"  # waiting for budget, not failed
    flagged = _events(db, job, "engine_budget_exceeded")
    assert len(flagged) == 1 and flagged[0].data["providers"] == ["deepl"]
    retry = db.execute(
        select(WorkItem).where(WorkItem.kind == "job.translate", WorkItem.status == "ready")
    ).scalar_one()
    assert retry.idempotency_key.startswith(f"{job.id}:translate:budget:")
    # a second blocked run in the same day records provenance again but notifies once
    orchestrator.translate(db, job.id)
    db.commit()
    assert len(_events(db, job, "engine_budget_exceeded")) == 2
    deliveries = db.execute(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.event == "job.needs_attention")
    ).scalar_one()
    assert deliveries == 1
    # cap raised: the retry runs the job to the end
    monkeypatch.setattr(routing, "choose", real)
    orchestrator.translate(db, job.id)
    db.commit()
    run_until_idle()
    db.expire_all()
    assert db.get(Job, job.id).state in ("delivered", "review")


def test_routes_steer_the_pipeline(db):
    from arbiter.engines import manage

    org, job = make_job(db, tier="auto")
    manage.create_route(db, org.id, {"engines": ["llm-mt:mock-llm"], "fallback": False})
    db.flush()
    job = _run(db, job)
    segs = db.execute(select(Segment).where(Segment.job_id == job.id, Segment.origin == "mt")).scalars().all()
    assert segs and {s.engine for s in segs} == {"llm-mt:mock-llm"}
    mt_route = [e for e in _events(db, job, "engine_route") if e.data["purpose"] == "mt"][0]
    assert mt_route.data["source"] == "route" and mt_route.data["engines"] == ["llm-mt:mock-llm"]
