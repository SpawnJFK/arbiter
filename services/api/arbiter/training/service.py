"""Training job lifecycle: export -> provider -> poll -> register model -> evaluate -> scoreboard.

States (domain/states.py, machine "training"):
    created -> running -> evaluating -> ready
    created -> exported (manual provider) -> evaluating (endpoint registered) -> ready
    any open state -> failed / cancelled

Polling and evaluation run as work_items (`training.poll`, `training.evaluate`), enqueued in
the same transaction as the state change that caused them (CLAUDE.md queue rule).

Evaluation translates the held-out validation set with the new model and scores every
output with the org's judge route (the same QE judge as production). The result is written
to engine_scores as engine `custom:<model id>`, so the scoreboard decides whether the model
is used: an active model ranks above the default only when it measures better. A model is
never used before an admin activates it (POST /v1/custom-models/{id}/activate).

EU processing (D-057): an org with processing_region "eu" may only train with a provider
whose inference runs in the EU (today: the manual provider with an EU-hosted trainer), and a
model is evaluated only when its endpoint is declared "eu". Data never leaves the region.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from arbiter import storage
from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError, LlmClient, MtEngine, MtRequest, SegmentContext
from arbiter.domain.states import transition
from arbiter.engines import credentials, registry, routing
from arbiter.engines.catalog import TRAINING_PROVIDERS
from arbiter.engines.openai_compatible import from_training_text
from arbiter.engines.pricing import MILLION, TRAINING_RATES
from arbiter.errors import Invalid, NotFound
from arbiter.models import CustomModel, EngineScore, Organization, TrainingJob, utcnow
from arbiter.pipeline.queue import enqueue
from arbiter.training import dataset
from arbiter.training.providers import get_provider

EPOCHS = 3
OPEN_STATES = ("created", "running", "evaluating", "exported")


def _job(session: Session, job_id: str, org_id: str | None = None) -> TrainingJob:
    job = session.get(TrainingJob, job_id)
    if job is None or (org_id is not None and job.org_id != org_id):
        raise NotFound("training job not found")
    return job


def _region(org: Organization) -> str:
    return routing.processing_region(org)


def preview(
    session: Session, org: Organization, source_lang: str, target_lang: str, domain: str
) -> dict[str, Any]:
    ds = dataset.build(session, org, source_lang, target_lang, domain, require_consent=False)
    stats = dict(ds.stats)
    stats["estimated_cost"] = {
        p: str(estimate_training_cost(p, int(stats["train_tokens_estimate"]))) for p in TRAINING_PROVIDERS
    }
    stats["currency"] = get_settings().currency
    return stats


def estimate_training_cost(provider: str, tokens: int) -> Decimal:
    rate = TRAINING_RATES.get(provider, Decimal("3"))
    return (Decimal(tokens * EPOCHS) * rate / MILLION).quantize(Decimal("0.01"))


def _schedule_poll(session: Session, job: TrainingJob) -> None:
    delay = min(120 * 2 ** min(job.polls, 4), 1800)  # 2, 4, 8, 16, 30 min
    enqueue(
        session,
        "training.poll",
        {"training_job_id": job.id},
        run_at=utcnow() + timedelta(seconds=delay),
        idempotency_key=f"{job.id}:poll:{job.polls}",
    )


def start_job(
    session: Session,
    org: Organization,
    *,
    source_lang: str,
    target_lang: str,
    domain: str,
    provider: str,
    base_model: str,
    actor: str | None,
    settings: Settings | None = None,
    http_client: httpx.Client | None = None,
) -> TrainingJob:
    s = settings or get_settings()
    if provider not in TRAINING_PROVIDERS:
        raise Invalid(f"unknown training provider {provider!r}")
    if source_lang == target_lang:
        raise Invalid("source and target language must differ")
    cred = credentials.resolve(session, org.id, provider, s) if provider != "manual" else None
    try:
        prov = get_provider(provider, cred, s, http_client=http_client)
    except EngineError as e:
        raise Invalid(str(e)) from e
    if _region(org) == "eu" and prov.inference_region != "eu" and provider != "manual":
        raise Invalid("EU processing is on: train with the manual provider and an EU-hosted trainer")
    ds = dataset.build(session, org, source_lang, target_lang, domain, s)
    if not ds.stats["enough"]:
        raise Invalid(
            f"not enough approved segments to train: {ds.stats['train']} of {s.training_min_examples} needed"
        )
    job = TrainingJob(
        org_id=org.id,
        source_lang=source_lang,
        target_lang=target_lang,
        domain=domain,
        provider=provider,
        base_model=base_model,
        dataset_stats=ds.stats,
        cost=estimate_training_cost(provider, int(ds.stats["train_tokens_estimate"])),
        currency=s.currency,
        created_by=actor,
    )
    session.add(job)
    session.flush()
    train = dataset.to_jsonl(ds.train, source_lang, target_lang)
    val = dataset.to_jsonl(ds.validation, source_lang, target_lang)
    job.train_storage_key = storage.make_key(org.id, "training", job.id, "train.jsonl")
    job.validation_storage_key = storage.make_key(org.id, "training", job.id, "validation.jsonl")
    storage.put(job.train_storage_key, train)
    storage.put(job.validation_storage_key, val)
    started = prov.start(train, val, base_model=base_model, suffix=f"{org.slug}-{source_lang}-{target_lang}")
    job.provider_job_id = started.id
    if started.status == "manual":
        transition(job, "training", "exported")
    else:
        transition(job, "training", "running")
        _schedule_poll(session, job)
    return job


def refresh(
    session: Session, job_id: str, *, org_id: str | None = None, http_client: httpx.Client | None = None
) -> TrainingJob:
    """Poll the provider once (POST .../refresh and the training.poll work item)."""
    s = get_settings()
    job = _job(session, job_id, org_id)
    if job.state != "running" or not job.provider_job_id:
        return job
    cred = credentials.resolve(session, job.org_id, job.provider, s)
    prov = get_provider(job.provider, cred, s, http_client=http_client)
    st = prov.poll(job.provider_job_id)
    job.polls += 1
    if st.cost is not None:
        job.cost = st.cost
    if st.status == "running":
        _schedule_poll(session, job)
        return job
    if st.status in ("failed", "cancelled"):
        job.error = st.error or st.status
        job.finished_at = utcnow()
        transition(job, "training", "failed" if st.status == "failed" else "cancelled")
        return job
    # succeeded: register the model (inactive) and evaluate it on the held-out set
    job.result_model_id = st.model_id
    job.endpoint = st.endpoint
    org = session.get(Organization, job.org_id)
    assert org is not None
    model = CustomModel(
        org_id=job.org_id,
        training_job_id=job.id,
        name=f"{job.source_lang}-{job.target_lang} {job.domain} ({job.base_model.rsplit('/', 1)[-1]})",
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        domain=job.domain,
        base_model=job.base_model,
        provider_model_id=st.model_id or "",
        endpoint=st.endpoint or "",
        credential_id=cred.credential_id if cred else None,
        region=prov.inference_region,
    )
    session.add(model)
    session.flush()
    job.custom_model_id = model.id
    transition(job, "training", "evaluating")
    enqueue(session, "training.evaluate", {"training_job_id": job.id}, idempotency_key=f"{job.id}:evaluate")
    return job


def register_model(
    session: Session,
    org: Organization,
    *,
    name: str,
    source_lang: str,
    target_lang: str,
    domain: str,
    endpoint: str,
    provider_model_id: str,
    credential_id: str | None,
    region: str,
    base_model: str = "",
    training_job_id: str | None = None,
) -> CustomModel:
    """An externally served model (manual provider or any OpenAI-compatible endpoint)."""
    s = get_settings()
    if credential_id and credentials.by_id(session, credential_id, org.id, s) is None:
        raise NotFound("credential not found")
    job = _job(session, training_job_id, org.id) if training_job_id else None
    if job is not None and job.state != "exported":
        raise Invalid("only an exported (manual) training job can take an external model")
    model = CustomModel(
        org_id=org.id,
        training_job_id=job.id if job else None,
        name=name,
        source_lang=source_lang,
        target_lang=target_lang,
        domain=domain,
        base_model=base_model or (job.base_model if job else ""),
        provider_model_id=provider_model_id,
        endpoint=endpoint,
        credential_id=credential_id,
        region=region,
    )
    session.add(model)
    session.flush()
    if job is not None:
        job.custom_model_id = model.id
        job.endpoint, job.result_model_id = endpoint, provider_model_id
        transition(job, "training", "evaluating")
        enqueue(
            session, "training.evaluate", {"training_job_id": job.id}, idempotency_key=f"{job.id}:evaluate"
        )
    return model


def _default_engine(session: Session, model: CustomModel) -> MtEngine:
    s = get_settings()
    if s.is_test:
        raise EngineError("custom model endpoints are not called in the test environment")
    cred = credentials.by_id(session, model.credential_id, model.org_id, s) if model.credential_id else None
    return registry.custom_model_engine(model, cred)


def _default_judge(session: Session, org: Organization, model: CustomModel) -> LlmClient:
    choice = routing.choose(
        session,
        org=org,
        purpose="judge",
        source_lang=model.source_lang,
        target_lang=model.target_lang,
        content_type=model.domain,
    )
    ctx = registry.EngineContext(session, org.id)
    return routing.wrap_llm(registry.get_llm(choice.engines[0], context=ctx), session, org.id)


def evaluate(
    session: Session,
    job_id: str,
    *,
    engine: MtEngine | None = None,
    judge: LlmClient | None = None,
) -> TrainingJob:
    from rapidfuzz.distance import Levenshtein

    from arbiter.quality.qe import score_segment

    job = _job(session, job_id)
    if job.state != "evaluating" or not job.custom_model_id:
        return job
    model = session.get(CustomModel, job.custom_model_id)
    org = session.get(Organization, job.org_id)
    assert model is not None and org is not None
    if _region(org) == "eu" and model.region != "eu":
        job.error = "EU processing is on and the model endpoint is not declared as EU: not evaluated"
        job.finished_at = utcnow()
        transition(job, "training", "failed")
        return job
    heldout = dataset.heldout_from_jsonl(storage.get(job.validation_storage_key or ""))
    engine = engine or _default_engine(session, model)
    judge = judge or _default_judge(session, org, model)
    scores: list[float] = []
    distances: list[float] = []
    failures = 0
    for src_text, ref_text in heldout:
        source = from_training_text(src_text)
        reference = from_training_text(ref_text)
        res = engine.translate([MtRequest(source, job.source_lang, job.target_lang)])[0]
        if res.error or not res.target_tagged:
            failures += 1
            scores.append(0.0)  # a model that does not answer is scored as failing, never skipped
            distances.append(1.0)
            continue
        ctx = SegmentContext(
            segment_id=f"eval-{job.id}-{len(scores)}",
            source_tagged=source,
            target_tagged=res.target_tagged,
            source_lang=job.source_lang,
            target_lang=job.target_lang,
            content_type=job.domain,
        )
        try:
            qe = score_segment(ctx, judge)
            scores.append(qe.score)
        except EngineError:
            failures += 1
            scores.append(0.0)
        distances.append(Levenshtein.normalized_distance(res.target_tagged, reference))
    n = len(scores)
    mean_qe = sum(scores) / n if n else 0.0
    mean_ed = sum(distances) / n if n else 1.0
    stmt = insert(EngineScore).values(
        engine=model.engine_name,
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        domain=job.domain,
        segments_measured=n,
        mean_qe=mean_qe,
        mean_edit_distance=mean_ed,
        glossary_supported=False,
        updated_at=utcnow(),
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["engine", "source_lang", "target_lang", "domain"],
            set_={
                "segments_measured": n,
                "mean_qe": mean_qe,
                "mean_edit_distance": mean_ed,
                "updated_at": utcnow(),
            },
        )
    )
    model.eval_mean_qe = mean_qe
    model.eval_segments = n
    job.dataset_stats = {**(job.dataset_stats or {}), "eval": {"segments": n, "failures": failures}}
    job.finished_at = utcnow()
    transition(job, "training", "ready")
    return job


def set_active(session: Session, org: Organization, model_id: str, active: bool) -> CustomModel:
    model = session.get(CustomModel, model_id)
    if model is None or model.org_id != org.id:
        raise NotFound("custom model not found")
    model.active = active
    model.activated_at = utcnow() if active else None
    return model


def fail(session: Session, job_id: str, reason: str) -> None:
    job = session.get(TrainingJob, job_id)
    if job is None or job.state not in OPEN_STATES:
        return
    job.error = reason[:2000]
    job.finished_at = utcnow()
    transition(job, "training", "failed")


def list_jobs(session: Session, org_id: str) -> list[TrainingJob]:
    return list(
        session.execute(
            select(TrainingJob).where(TrainingJob.org_id == org_id).order_by(TrainingJob.created_at.desc())
        ).scalars()
    )


HANDLERS = {
    "training.poll": lambda s, p: refresh(s, p["training_job_id"]),
    "training.evaluate": lambda s, p: evaluate(s, p["training_job_id"]),
}
