"""The translation pipeline: one job from upload to delivery.

Steps (each a work item, each idempotent so a retried or duplicated step is harmless):

    job.prepare    extract file -> segments, freeze glossary version and threshold
    job.translate  TM lookup (context 101 may ship directly, R-TM-03) -> engine or translation senate
    job.score      glossary check -> hard QA -> QE judge -> decide -> senate band -> route
    job.deadline   no reviewer before the deadline -> org no_reviewer_policy (never silent)
    job.merge      write the translated file + evidence pack, deliver, bill, notify

Routing (quality.qe.decide): auto_approve ships; senate convenes the council for the
uncertain band; review queues a human task; blocked (a deterministic failure such as a
dropped tag or a missing mandatory term) always goes to a human, never to a model.
On the ai_review tier, the senate + editor replace the human, and the client knows it.

Workflows (Agency OS): a job may carry a frozen workflow snapshot (job.workflow, see
arbiter.agency.workflows). Jobs without one behave exactly as before. With one:
    tm / mt / translation_senate   which translation sources run (translation_senate forces best-of-N)
    qe.params.threshold            overrides the job threshold frozen at prepare
    human_review.params.min_level  minimum reviewer level of the review tasks
    second_review                  after the first human review a second task (min_level senior,
                                   never the first reviewer); the segment stays needs_review
                                   until then; segment.signals["reviews"] counts the reviews
    client_review                  when every segment is done the job waits in `review` for
                                   POST /jobs/{id}/client-approve (webhook job.needs_attention,
                                   reason client_review), then goes ready -> merge
senate, ai_review and human_review follow the tier, which workflow validation keeps consistent.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.agency import workflows as wfl
from arbiter.community import queue as review_queue
from arbiter.config import get_settings
from arbiter.contracts import (
    EngineError,
    LlmClient,
    MqmError,
    MtEngine,
    MtRequest,
    SegmentContext,
    TermHit,
    TermViolation,
)
from arbiter.domain.states import transition
from arbiter.engines.registry import available_mt, get_llm, get_mt
from arbiter.fileproc.base import InlineCode, codes_of, from_tagged, plain_text, to_tagged
from arbiter.fileproc.registry import detect_and_extract
from arbiter.linguistic import glossary as gl
from arbiter.linguistic import tm
from arbiter.models import (
    ControlSample,
    EngineScore,
    EscapedError,
    FileAsset,
    Job,
    Organization,
    Segment,
    SenateRun,
    StyleCard,
    Threshold,
    new_id,
    utcnow,
)
from arbiter.pipeline import events
from arbiter.pipeline.queue import enqueue
from arbiter.quality import calibration
from arbiter.quality.editor import apply_fixes
from arbiter.quality.prompts import PROMPT_VERSION
from arbiter.quality.qe import decide, score_segment
from arbiter.quality.senate import review_senate, translation_senate

log = logging.getLogger(__name__)
LEVEL_RANK = {"candidate": 0, "reviewer": 1, "senior": 2, "domain_expert": 3}

MT_BATCH = 40
OPEN_STATES = ("pending", "translated", "needs_review", "in_review")
DONE_STATES = ("auto_approved", "reviewed", "delivered")


# --------------------------------------------------------------------------- helpers


def _job(session: Session, job_id: str, *, lock: bool = True) -> Job:
    q = select(Job).where(Job.id == job_id)
    if lock:
        q = q.with_for_update()
    job = session.execute(q).scalar_one_or_none()
    if job is None:
        raise LookupError(f"job {job_id} not found")
    return job


def _org(session: Session, job: Job) -> Organization:
    org = session.get(Organization, job.org_id)
    assert org is not None
    return org


def _codes(segment: Segment) -> list[InlineCode]:
    return [InlineCode(**c) for c in (segment.source_codes or [])]


def _segments(session: Session, job: Job, states: Sequence[str] | None = None) -> list[Segment]:
    q = select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)
    if states:
        q = q.where(Segment.state.in_(states))
    return list(session.execute(q).scalars())


def _terms_for(session: Session, job: Job) -> list[Any]:
    return gl.active_terms(
        session, job.org_id, job.source_lang, job.target_lang, job.content_type, job.glossary_version or None
    )


def _hits(segment: Segment, terms: list[Any], lang: str) -> list[TermHit]:
    return gl.find_source_terms(segment.source_plain, terms, lang) if terms else []


def _violations(target_tagged: str | None, hits: list[TermHit], lang: str) -> list[TermViolation]:
    if not hits or not target_tagged:
        return []
    return gl.check_target(tm.tagged_plain(target_tagged), hits, lang)


def _style(session: Session, job: Job) -> tuple[list[str], str | None]:
    card = (
        session.execute(
            select(StyleCard).where(
                StyleCard.org_id == job.org_id,
                StyleCard.target_lang == job.target_lang,
                StyleCard.content_type.in_([job.content_type, "general"]),
            )
        )
        .scalars()
        .first()
    )
    return (list(card.rules or []), card.formality) if card else ([], None)


def _threshold(session: Session, job: Job) -> Threshold | None:
    rows = (
        session.execute(
            select(Threshold).where(
                Threshold.org_id == job.org_id, Threshold.content_type == job.content_type
            )
        )
        .scalars()
        .all()
    )
    exact = [t for t in rows if t.target_lang == job.target_lang]
    default = [t for t in rows if t.target_lang is None]
    return (exact or default or [None])[0]


def _create_threshold(session: Session, job: Job) -> Threshold | None:
    """First job for (org, content type, target language): store the default threshold row so
    calibration and /quality/thresholds have something to show and tune."""
    from sqlalchemy.dialects.postgresql import insert

    settings = get_settings()
    session.execute(
        insert(Threshold)
        .values(
            id=new_id("thr"),
            org_id=job.org_id,
            content_type=job.content_type,
            target_lang=job.target_lang,
            value=settings.default_threshold,
            band_width=settings.band_width,
            safety_offset=0.0,
            auto_approval_suspended=False,
            updated_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["org_id", "content_type", "target_lang"])
    )
    return _threshold(session, job)


def _engine_names(session: Session, job: Job) -> list[str]:
    """R-MT-02: engines ordered by our own scoreboard for this pair and domain; default first otherwise."""
    settings = get_settings()
    avail = available_mt()
    if not settings.is_test and not settings.default_mt_engine.startswith("mock"):
        avail = [n for n in avail if "mock" not in n]
    board = (
        session.execute(
            select(EngineScore)
            .where(
                EngineScore.source_lang == job.source_lang,
                EngineScore.target_lang == job.target_lang,
                EngineScore.domain.in_([job.content_type, "general"]),
                EngineScore.segments_measured >= 200,
            )
            .order_by(EngineScore.mean_qe.desc())
        )
        .scalars()
        .all()
    )
    ranked = [b.engine for b in board if b.engine in avail]
    first = [settings.default_mt_engine] if settings.default_mt_engine in avail else []
    rest = [n for n in avail if n not in ranked and n not in first]
    return list(dict.fromkeys(ranked + first + rest))


def _judge() -> LlmClient:
    return get_llm(get_settings().default_judge_engine)


def _ctx(session: Session, job: Job, seg: Segment, hits: list[TermHit], style: list[str]) -> SegmentContext:
    neighbours = (
        session.execute(
            select(Segment)
            .where(
                Segment.job_id == job.id,
                Segment.seq.between(seg.seq - 10, seg.seq + 10),
                Segment.id != seg.id,
            )
            .order_by(Segment.seq)
        )
        .scalars()
        .all()
    )
    before = next((n.source_plain for n in reversed(neighbours) if n.seq < seg.seq), "")
    after = next((n.source_plain for n in neighbours if n.seq > seg.seq), "")
    return SegmentContext(
        segment_id=seg.id,
        source_tagged=seg.source_tagged,
        target_tagged=seg.target_tagged or "",
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        content_type=job.content_type,
        terms=hits,
        style_rules=style,
        context_before=before,
        context_after=after,
        max_length=seg.max_length,
        document_targets=[(n.source_tagged, n.target_tagged) for n in neighbours if n.target_tagged],
    )


def _add_cost(job: Job, amount: Decimal) -> None:
    job.cost_engines = (job.cost_engines or Decimal("0")) + (amount or Decimal("0"))


def _err_dict(e: MqmError) -> dict[str, Any]:
    return asdict(e)


def _set_target(
    session: Session, job: Job, seg: Segment, target: str, *, origin: str, actor: str, **data: Any
) -> None:
    seg.target_tagged = target
    seg.origin = origin
    seg.updated_at = utcnow()
    events.record(
        session,
        job,
        "target_set",
        segment=seg,
        actor_type="human" if origin == "human" else ("system" if origin == "tm" else "engine"),
        actor_id=actor,
        target=target,
        origin=origin,
        **data,
    )


# --------------------------------------------------------------------------- start


def start_job(session: Session, job: Job) -> None:
    """Called when a project is created from an accepted quote."""
    if job.state == "draft":
        transition(job, "job", "quoted")
    transition(job, "job", "running")
    job.started_at = utcnow()
    events.record(session, job, "job_started", tier=job.tier)
    enqueue(session, "job.prepare", {"job_id": job.id}, idempotency_key=f"{job.id}:prepare")


# --------------------------------------------------------------------------- prepare


def prepare(session: Session, job_id: str) -> None:
    from arbiter import storage

    job = _job(session, job_id)
    if job.state != "running" or job.segment_count:
        return  # already prepared (idempotent)
    settings = get_settings()
    fa = session.get(FileAsset, job.file_id)
    assert fa is not None
    result = detect_and_extract(fa.filename, storage.get(fa.storage_key), job.source_lang)

    # R-GL-11: freeze the glossary version and the threshold the job runs with.
    job.glossary_version = gl.current_version(session, job.org_id, job.content_type)
    thr = _threshold(session, job) or _create_threshold(session, job)
    job.threshold = thr.value if thr else settings.default_threshold
    job.band_width = thr.band_width if thr else settings.band_width
    qe_step = wfl.step(job.workflow, "qe")
    if qe_step and (qe_step.get("params") or {}).get("threshold") is not None:
        job.threshold = float(qe_step["params"]["threshold"])  # the workflow's own bar

    seq = 0
    flat: list[tuple[str, int, Any, Any]] = []
    for unit in result.units:
        for i, draft in enumerate(unit.segments):
            flat.append((unit.unit_id, i, unit, draft))
    words_total = 0
    tagged = [to_tagged(d.content) for _, _, _, d in flat]
    for idx, (unit_id, i, unit, draft) in enumerate(flat):
        plain = plain_text(draft.content)
        words = len(plain.split())
        words_total += words
        prev_src = tagged[idx - 1] if idx > 0 else ""
        next_src = tagged[idx + 1] if idx + 1 < len(tagged) else ""
        session.add(
            Segment(
                job_id=job.id,
                seq=seq,
                unit_id=unit_id,
                seg_index=i,
                context=unit.context[:200],
                max_length=unit.max_length,
                source_tagged=tagged[idx],
                source_plain=plain,
                source_codes=[asdict(c) for c in codes_of(draft.content)],
                word_count=words,
                state="pending",
                signals={"context_hash": tm.context_hash(prev_src, next_src)},
            )
        )
        seq += 1
    job.segment_count = seq
    job.word_count = words_total
    events.record(
        session,
        job,
        "prepared",
        segments=seq,
        words=words_total,
        glossary_version=job.glossary_version,
        threshold=job.threshold,
        warnings=result.warnings,
    )
    if job.due_at:
        remaining = job.due_at - utcnow()
        margin = min(timedelta(hours=2), remaining * 0.2) if remaining.total_seconds() > 0 else timedelta(0)
        enqueue(
            session,
            "job.deadline",
            {"job_id": job.id},
            run_at=job.due_at - margin,
            idempotency_key=f"{job.id}:deadline",
        )
    enqueue(session, "job.translate", {"job_id": job.id}, idempotency_key=f"{job.id}:translate")


# --------------------------------------------------------------------------- translate


def translate(session: Session, job_id: str) -> None:
    job = _job(session, job_id)
    if job.state != "running":
        return
    org = _org(session, job)
    pending = _segments(session, job, ["pending"])
    if not pending:
        enqueue(session, "job.score", {"job_id": job.id}, idempotency_key=f"{job.id}:score")
        return
    terms = _terms_for(session, job)
    style, formality = _style(session, job)
    wf = job.workflow
    use_tm = wf is None or wfl.has(wf, "tm")
    use_engine = wf is None or wfl.has(wf, "mt") or wfl.has(wf, "translation_senate")
    to_engine: list[tuple[Segment, MtRequest, list[TermHit]]] = []
    for seg in pending:
        hits = _hits(seg, terms, job.source_lang)
        seg.signals = {
            **(seg.signals or {}),
            "terms": [
                {"source_term": h.source_term, "target_term": h.target_term, "kind": h.kind} for h in hits
            ],
        }
        matches = (
            tm.lookup(
                session,
                job.org_id,
                job.source_lang,
                job.target_lang,
                seg.source_tagged,
                seg.signals.get("context_hash"),
            )
            if use_tm
            else []
        )
        best = matches[0] if matches else None
        if best and best.kind in ("context", "exact"):
            seg.tm_match, seg.tm_entry_id = best.score, best.entry_id
            _set_target(
                session, job, seg, best.target_tagged, origin="tm", actor=best.entry_id, tm_score=best.score
            )
            seg.engine_target_tagged = best.target_tagged
            # R-TM-03: an in-context (101) match whose target still satisfies the current
            # glossary ships without engine or judge. An exact 100 is still scored.
            if best.kind == "context" and not _violations(best.target_tagged, hits, job.target_lang):
                seg.qe_score, seg.decision = 100.0, "auto_approve"
                seg.reasons = ["tm_context_match"]
                transition(seg, "segment", "auto_approved")
                job.auto_approved_count += 1
            else:
                transition(seg, "segment", "translated")
            continue
        if best:
            seg.tm_match, seg.tm_entry_id = best.score, best.entry_id
        if not use_engine:
            # TM-only workflow: no engine runs; the human reviewer translates this segment.
            seg.signals = {**seg.signals, "needs_translation": True}
            events.record(session, job, "awaiting_translation", segment=seg, reason="no mt step")
            transition(seg, "segment", "translated")
            continue
        req = MtRequest(
            source_tagged=seg.source_tagged,
            source_lang=job.source_lang,
            target_lang=job.target_lang,
            terms=hits,
            style_rules=style,
            formality=formality,
            max_length=seg.max_length,
            tm_examples=[m for m in matches if m.kind == "fuzzy"][:2],
        )
        to_engine.append((seg, req, hits))

    if not to_engine:
        events.record(session, job, "translated", segments=len(pending), engines=[])
        enqueue(session, "job.score", {"job_id": job.id}, idempotency_key=f"{job.id}:score")
        return
    names = _engine_names(session, job)
    if not names:
        raise EngineError("no MT engine available")
    mt_step = wfl.step(wf, "mt")
    preferred = (mt_step.get("params") or {}).get("engine") if mt_step else None
    if preferred and preferred in names:
        names = [preferred] + [n for n in names if n != preferred]
    elif preferred:
        events.record(session, job, "engine_unavailable", engine=preferred, used=names[0])
    forced = wfl.has(wf, "translation_senate")
    use_senate = (bool((org.settings or {}).get("translation_senate")) or forced) and len(names) >= 2
    if forced and not use_senate:
        events.record(session, job, "translation_senate_skipped", reason="fewer than two engines available")
    engines: list[MtEngine] = []
    for n in names:
        try:
            engines.append(get_mt(n))
        except EngineError as e:  # provider down or not configured: router skips it
            log.warning("engine %s skipped: %s", n, e)
    if not engines:
        raise EngineError("no MT engine reachable")

    for start in range(0, len(to_engine), MT_BATCH):
        batch = to_engine[start : start + MT_BATCH]
        if use_senate:
            judge = _judge()
            for seg, req, hits in batch:
                verdict = translation_senate(
                    req, engines[:3], judge, lambda t, h=hits: _violations(t, h, job.target_lang)
                )
                _add_cost(job, verdict.usage.cost)
                _store_senate(session, job, seg, "translation", verdict)
                if verdict.winner_target is None:
                    seg.reasons = ["translation_senate_void"]
                    _set_target(session, job, seg, "", origin="mt", actor="senate")
                else:
                    winner = verdict.outcome.split(":", 1)[-1]
                    seg.engine = winner
                    seg.engine_target_tagged = verdict.winner_target
                    _set_target(
                        session,
                        job,
                        seg,
                        verdict.winner_target,
                        origin="mt",
                        actor=winner,
                        senate=verdict.outcome,
                    )
                transition(seg, "segment", "translated")
            continue
        results = _translate_with_fallback(engines, [r for _, r, _ in batch])
        for (seg, _r, _h), res in zip(batch, results, strict=True):
            _add_cost(job, res.usage.cost)
            seg.engine = res.engine
            seg.engine_target_tagged = res.target_tagged
            _set_target(
                session, job, seg, res.target_tagged or "", origin="mt", actor=res.engine, error=res.error
            )
            transition(seg, "segment", "translated")
    events.record(session, job, "translated", segments=len(pending), engines=names)
    enqueue(session, "job.score", {"job_id": job.id}, idempotency_key=f"{job.id}:score")


def _translate_with_fallback(engines: list[MtEngine], reqs: list[MtRequest]) -> list[Any]:
    """Try engines in order; a failed segment is retried on the next engine (provider outage runbook)."""
    results: list[Any] = [None] * len(reqs)
    todo = list(range(len(reqs)))
    last_err = ""
    for engine in engines:
        if not todo:
            break
        try:
            out = engine.translate([reqs[i] for i in todo])
        except EngineError as e:
            last_err = str(e)
            continue
        still = []
        for i, res in zip(todo, out, strict=True):
            if res.error or not res.target_tagged:
                still.append(i)
                last_err = res.error or "empty"
                if results[i] is None:
                    results[i] = res
            else:
                results[i] = res
        todo = still
    if any(r is None for r in results):
        raise EngineError(f"all engines failed: {last_err}")
    return results


# --------------------------------------------------------------------------- score & route


def score(session: Session, job_id: str) -> None:
    from arbiter.billing import usage

    settings = get_settings()
    job = _job(session, job_id)
    if job.state != "running":
        return
    org = _org(session, job)
    thr = _threshold(session, job)
    safety = thr.safety_offset if thr else 0.0
    suspended = bool(thr and thr.auto_approval_suspended)
    terms = _terms_for(session, job)
    style, _ = _style(session, job)
    judge = _judge()
    segs = _segments(session, job, ["translated"])
    n_qe = n_senate = 0
    for seg in segs:
        if (seg.signals or {}).get("needs_translation"):
            # TM-only workflow, no TM match: nothing to score, a human translates it.
            seg.decision, seg.reasons = "review", ["no_mt_step"]
            transition(seg, "segment", "needs_review")
            review_queue.create_task(session, seg, job, min_level=_level_for(org, "review", job))
            job.review_count += 1
            continue
        hits = _hits(seg, terms, job.source_lang)
        violations = _violations(seg.target_tagged, hits, job.target_lang)
        ctx = _ctx(session, job, seg, hits, style)
        qe = score_segment(ctx, judge, violations)
        n_qe += 1
        _add_cost(job, qe.usage.cost)
        seg.qe_score = qe.score
        decision = decide(
            qe.score,
            qe.hard_issues,
            job.threshold,
            job.band_width,
            tier=job.tier,
            regulated=org.regulated,
            safety_offset=safety,
            suspended=suspended,
        )
        errors = [_err_dict(e) for e in qe.errors]
        seg.signals = {
            **(seg.signals or {}),
            "hard_issues": [asdict(i) for i in qe.hard_issues],
            "term_violations": [asdict(v) for v in violations],
            "errors": errors,
        }
        seg.reasons = [i.code for i in qe.hard_issues if i.blocking] + [
            f"{e.dimension}:{e.severity}" for e in qe.errors
        ]
        events.record(
            session,
            job,
            "qe_scored",
            segment=seg,
            actor_type="engine",
            actor_id=judge.name,
            model_version=qe.model_version,
            score=qe.score,
            decision=decision,
            hard_issues=[i.code for i in qe.hard_issues],
            errors=errors,
            threshold=job.threshold,
            safety_offset=safety,
        )

        if decision == "senate":
            n_senate += 1
            verdict = review_senate(ctx, judge)
            _add_cost(job, verdict.usage.cost)
            _store_senate(session, job, seg, "review", verdict)
            seg.signals = {**seg.signals, "errors": [_err_dict(e) for e in verdict.confirmed]}
            if verdict.outcome == "void":
                decision = "review"  # a council that could not sit never approves anything
            elif verdict.outcome == "clean" and verdict.score is not None and job.tier != "hybrid":
                decision = "auto_approve"
            elif verdict.outcome == "clean" and job.tier == "hybrid":
                decision = "auto_approve" if (verdict.score or 0) >= job.threshold + safety else "review"
            else:
                decision = "ai_edit" if job.tier == "ai_review" else "review"
                if (
                    job.tier == "auto"
                    and verdict.score is not None
                    and verdict.score >= job.threshold + safety
                ):
                    decision = "auto_approve"
        elif decision == "review" and job.tier == "ai_review":
            decision = "ai_edit"

        if decision == "ai_edit":
            # Routing label only: the segment's final decision is "ai_reviewed", never "ai_edit".
            seg.decision = "ai_reviewed"
            _ai_edit(session, job, seg, ctx, judge, hits)
            continue
        seg.decision = decision
        if decision == "auto_approve":
            transition(seg, "segment", "auto_approved")
            job.auto_approved_count += 1
            if calibration.pick_control_sample(seg.id, settings.control_sample_rate):
                _queue_control_sample(session, job, seg)
        else:  # review | blocked
            transition(seg, "segment", "needs_review")
            review_queue.create_task(session, seg, job, min_level=_level_for(org, decision, job))
            job.review_count += 1

    if segs:
        usage.record(
            session,
            job.org_id,
            job.id,
            "ai_unit",
            usage.ai_units("qe", n_qe),
            Decimal("0"),
            f"{job.id}:qe",
            {"step": "qe"},
        )
        if n_senate:
            usage.record(
                session,
                job.org_id,
                job.id,
                "ai_unit",
                usage.ai_units("senate", n_senate),
                Decimal("0"),
                f"{job.id}:senate",
                {"step": "senate"},
            )
    _advance(session, job)


def _level_for(org: Organization, decision: str, job: Job | None = None) -> str:
    level = ("domain_expert" if decision == "blocked" else "senior") if org.regulated else "reviewer"
    hr = wfl.step(job.workflow, "human_review") if job is not None else None
    wanted = (hr.get("params") or {}).get("min_level") if hr else None
    if wanted in LEVEL_RANK and LEVEL_RANK[wanted] > LEVEL_RANK[level]:
        level = wanted
    return level


def _ai_edit(
    session: Session, job: Job, seg: Segment, ctx: SegmentContext, judge: LlmClient, hits: list[TermHit]
) -> None:
    """ai_review tier: the editor applies the confirmed fixes; the client bought AI review, not a human."""
    errors = [MqmError(**e) for e in (seg.signals or {}).get("errors", [])]
    transition(seg, "segment", "needs_review")
    if errors:
        new_target, used = apply_fixes(
            ctx, errors, judge, tier="ai_review", term_checker=lambda t: _violations(t, hits, job.target_lang)
        )
        _add_cost(job, used.cost)
        if new_target != seg.target_tagged:
            _set_target(session, job, seg, new_target, origin="editor", actor=judge.name, fixed=len(errors))
    seg.decision = "ai_reviewed"
    transition(seg, "segment", "reviewed")
    job.ai_reviewed_count += 1


def _queue_control_sample(session: Session, job: Job, seg: Segment) -> None:
    """2% of auto-approved segments go blind to a reviewer (calibration). The job does not wait."""
    seg.is_control_sample = True
    session.add(
        ControlSample(segment_id=seg.id, job_id=job.id, org_id=job.org_id, qe_score=seg.qe_score or 0.0)
    )
    review_queue.create_task(session, seg, job, priority=100_000)
    events.record(session, job, "control_sample", segment=seg)


def _store_senate(session: Session, job: Job, seg: Segment, purpose: str, verdict: Any) -> None:
    """Every convening counts in job.senate_count; the outcome stays on the segment for the UI
    (signals["senate"] for the review senate, signals["translation_senate"] for best-of-N)."""
    job.senate_count = (job.senate_count or 0) + 1
    key = "senate" if purpose == "review" else "translation_senate"
    seg.signals = {**(seg.signals or {}), key: verdict.outcome}
    session.add(
        SenateRun(
            segment_id=seg.id,
            job_id=job.id,
            purpose=purpose,
            roles_answered=verdict.roles_answered,
            roles_total=verdict.roles_total,
            findings=verdict.findings,
            confirmed=[_err_dict(e) for e in verdict.confirmed],
            discarded=[_err_dict(e) for e in verdict.discarded],
            score=verdict.score,
            outcome=verdict.outcome,
            cost=verdict.usage.cost,
        )
    )
    events.record(
        session,
        job,
        f"senate_{purpose}",
        segment=seg,
        actor_type="engine",
        model_version=PROMPT_VERSION,
        outcome=verdict.outcome,
        score=verdict.score,
        roles=f"{verdict.roles_answered}/{verdict.roles_total}",
        confirmed=len(verdict.confirmed),
    )


def _advance(session: Session, job: Job) -> None:
    """Move the job forward once every segment is decided."""
    open_count = session.execute(
        select(func.count())
        .select_from(Segment)
        .where(Segment.job_id == job.id, Segment.state.in_(OPEN_STATES))
    ).scalar_one()
    if open_count == 0:
        if job.state in ("running", "review"):
            if awaiting_client(job):
                _request_client_review(session, job)
                return
            transition(job, "job", "ready")
            enqueue(session, "job.merge", {"job_id": job.id}, idempotency_key=f"{job.id}:merge")
        return
    pending = session.execute(
        select(func.count())
        .select_from(Segment)
        .where(Segment.job_id == job.id, Segment.state.in_(("pending", "translated")))
    ).scalar_one()
    if pending == 0 and job.state == "running":
        transition(job, "job", "review")
        from arbiter import webhooks

        webhooks.emit(
            session, job.org_id, "job.needs_attention", {"job_id": job.id, "reason": "human_review"}
        )


def awaiting_client(job: Job) -> bool:
    """The workflow has client_review and the client has not approved yet."""
    return wfl.has(job.workflow, "client_review") and job.client_approved_at is None


def _request_client_review(session: Session, job: Job) -> None:
    """Every segment is done; the job waits in `review` for the client (once per job)."""
    from arbiter import webhooks

    if job.state == "running":
        transition(job, "job", "review")
    wf = dict(job.workflow or {})
    if wf.get("client_review_requested_at"):
        return
    wf["client_review_requested_at"] = utcnow().isoformat()
    job.workflow = wf
    events.record(session, job, "client_review_requested")
    webhooks.emit(session, job.org_id, "job.needs_attention", {"job_id": job.id, "reason": "client_review"})


def client_approve(session: Session, job: Job, actor: str) -> None:
    """POST /jobs/{id}/client-approve: the client signs off; the job goes ready -> merge."""
    job.client_approved_at = utcnow()
    events.record(session, job, "client_approved", actor_type="human", actor_id=actor)
    _advance(session, job)


# --------------------------------------------------------------------------- human review callbacks


def on_segment_reviewed(
    session: Session,
    segment_id: str,
    *,
    target_tagged: str,
    reviewer_id: str,
    decision: str,
    errors: list[dict[str, Any]],
) -> None:
    seg = session.get(Segment, segment_id)
    if seg is None:
        return
    job = _job(session, seg.job_id)
    if seg.state not in ("needs_review", "in_review"):
        return  # late duplicate (another reviewer or the deadline policy got there first)
    if decision == "edit" and target_tagged and target_tagged != seg.target_tagged:
        _set_target(session, job, seg, target_tagged, origin="human", actor=reviewer_id, errors=errors)
    seg.reviewer_id = reviewer_id
    reviews = [
        *list((seg.signals or {}).get("reviews") or []),
        {"reviewer_id": reviewer_id, "decision": decision, "at": utcnow().isoformat()},
    ]
    seg.signals = {**(seg.signals or {}), "reviews": reviews}
    if wfl.has(job.workflow, "second_review") and len(reviews) < 2:
        # second_review: the segment stays needs_review until a second, senior human reviews it.
        # Listing the first reviewer under skipped_by keeps the task away from them.
        seg.updated_at = utcnow()
        seg.reasons = [*[r for r in (seg.reasons or []) if r != "second_review"], "second_review"]
        events.record(
            session,
            job,
            "reviewed",
            segment=seg,
            actor_type="human",
            actor_id=reviewer_id,
            decision=decision,
            review=1,
            awaiting="second_review",
        )
        sr = wfl.step(job.workflow, "second_review") or {}
        level = (sr.get("params") or {}).get("min_level") or "senior"
        if LEVEL_RANK.get(level, 0) < LEVEL_RANK["senior"]:
            level = "senior"
        review_queue.create_task(session, seg, job, min_level=level, expected={"skipped_by": [reviewer_id]})
        job.review_count += 1
        return
    seg.decision = "reviewed"
    if seg.engine_target_tagged and seg.target_tagged:
        from rapidfuzz.distance import Levenshtein

        seg.edit_distance = Levenshtein.normalized_distance(seg.engine_target_tagged, seg.target_tagged)
    transition(seg, "segment", "reviewed")
    events.record(
        session,
        job,
        "reviewed",
        segment=seg,
        actor_type="human",
        actor_id=reviewer_id,
        decision=decision,
        review=len(reviews),
    )
    _learn(session, job, seg)
    _advance(session, job)


def on_segment_escalated(session: Session, segment_id: str, *, reviewer_id: str, reason: str) -> None:
    seg = session.get(Segment, segment_id)
    if seg is None:
        return
    job = _job(session, seg.job_id)
    events.record(
        session, job, "escalated", segment=seg, actor_type="human", actor_id=reviewer_id, reason=reason
    )
    review_queue.create_task(session, seg, job, min_level="senior", priority=0)


def on_control_verdict(
    session: Session, segment_id: str, *, reviewer_id: str, escaped: bool, note: str
) -> None:
    seg = session.get(Segment, segment_id)
    if seg is None:
        return
    job = session.get(Job, seg.job_id)
    assert job is not None
    cs = (
        session.execute(
            select(ControlSample).where(ControlSample.segment_id == seg.id, ControlSample.verdict.is_(None))
        )
        .scalars()
        .first()
    )
    if cs:
        cs.verdict = "escaped" if escaped else "ok"
        cs.reviewer_id = reviewer_id
        cs.decided_at = utcnow()
    if escaped:
        session.add(
            EscapedError(
                segment_id=seg.id,
                job_id=job.id,
                org_id=job.org_id,
                content_type=job.content_type,
                target_lang=job.target_lang,
                qe_score=seg.qe_score,
                was_auto_approved=True,
                source="control",
                note=note[:1000],
            )
        )
    events.record(
        session,
        job,
        "control_verdict",
        segment=seg,
        actor_type="human",
        actor_id=reviewer_id,
        escaped=escaped,
    )


def report_error(session: Session, job: Job, segment_id: str, note: str) -> EscapedError:
    """The client found an error in a delivered segment (feeds calibration and reviewer score)."""
    seg = session.get(Segment, segment_id)
    if seg is None or seg.job_id != job.id:
        raise LookupError("segment not found")
    err = EscapedError(
        segment_id=seg.id,
        job_id=job.id,
        org_id=job.org_id,
        content_type=job.content_type,
        target_lang=job.target_lang,
        qe_score=seg.qe_score,
        was_auto_approved=seg.decision == "auto_approve",
        source="client",
        note=note[:1000],
    )
    session.add(err)
    session.flush()
    if seg.reviewer_id:
        from arbiter.community import scoring
        from arbiter.models import ReviewTask

        task = (
            session.execute(
                select(ReviewTask).where(
                    ReviewTask.segment_id == seg.id, ReviewTask.reviewer_id == seg.reviewer_id
                )
            )
            .scalars()
            .first()
        )
        scoring.record_escaped(session, seg.reviewer_id, task.id if task else None, note)
    events.record(session, job, "error_reported", segment=seg, actor_type="human", note=note)
    return err


def _learn(session: Session, job: Job, seg: Segment) -> None:
    """Human-approved segments go into the client's TM (it is their data, R-TM-01)."""
    if not seg.target_tagged:
        return
    tm.store(
        session,
        job.org_id,
        job.source_lang,
        job.target_lang,
        seg.source_tagged,
        seg.target_tagged,
        content_type=job.content_type,
        context_hash=(seg.signals or {}).get("context_hash"),
        origin="review",
        job_id=job.id,
    )


# --------------------------------------------------------------------------- deadline policy


def deadline(session: Session, job_id: str) -> None:
    """No reviewer finished before the deadline: apply the org's policy, visibly (never silent)."""
    job = _job(session, job_id)
    if job.state != "review":
        return
    org = _org(session, job)
    open_segs = _segments(session, job, ["needs_review", "in_review"])
    if not open_segs:
        return
    policy = org.no_reviewer_policy
    if policy == "wait" or org.regulated:
        from arbiter import webhooks

        events.record(session, job, "deadline_waiting", open_segments=len(open_segs), policy=policy)
        webhooks.emit(session, job.org_id, "job.needs_attention", {"job_id": job.id, "reason": "deadline"})
        return
    job.no_reviewer_fallback_used = True
    judge = _judge()
    terms = _terms_for(session, job)
    style, _ = _style(session, job)
    for seg in open_segs:
        if seg.state == "in_review":
            continue
        if policy == "ai_fallback":
            hits = _hits(seg, terms, job.source_lang)
            ctx = _ctx(session, job, seg, hits, style)
            verdict = review_senate(ctx, judge)
            _store_senate(session, job, seg, "review", verdict)
            seg.signals = {**(seg.signals or {}), "errors": [_err_dict(e) for e in verdict.confirmed]}
            blocking = any(i.get("blocking") for i in (seg.signals or {}).get("hard_issues", []))
            if blocking:
                continue  # a deterministic failure still waits for a human
            if verdict.confirmed:
                new_target, used = apply_fixes(
                    ctx,
                    verdict.confirmed,
                    judge,
                    tier="ai_review",
                    term_checker=lambda t, h=hits: _violations(t, h, job.target_lang),
                )
                _add_cost(job, used.cost)
                if new_target != seg.target_tagged:
                    _set_target(session, job, seg, new_target, origin="editor", actor=judge.name)
            seg.decision = "ai_fallback"
        else:  # partial: delivered as machine output, flagged unreviewed in the evidence pack
            seg.decision = "unreviewed"
        transition(seg, "segment", "reviewed")
        job.ai_reviewed_count += 1
        events.record(session, job, "no_reviewer_policy", segment=seg, policy=policy)
        _cancel_tasks(session, seg)
    _advance(session, job)


def _cancel_tasks(session: Session, seg: Segment) -> None:
    from arbiter.models import ReviewTask

    for t in session.execute(
        select(ReviewTask).where(ReviewTask.segment_id == seg.id, ReviewTask.state.in_(("queued", "offered")))
    ).scalars():
        session.delete(t)


# --------------------------------------------------------------------------- merge & deliver


def merge(session: Session, job_id: str) -> None:
    from arbiter import storage, webhooks
    from arbiter.billing import usage
    from arbiter.fileproc.registry import get_handler
    from arbiter.pipeline import evidence

    job = _job(session, job_id)
    if job.state != "ready":
        return
    transition(job, "job", "merging")
    fa = session.get(FileAsset, job.file_id)
    assert fa is not None
    original = storage.get(fa.storage_key)
    segs = _segments(session, job)
    targets: dict[str, list[Any]] = {}
    for seg in segs:
        codes = _codes(seg)
        try:
            content = from_tagged(seg.target_tagged or seg.source_tagged, codes)
        except ValueError:
            content = from_tagged(seg.source_tagged, codes)
        targets.setdefault(seg.unit_id, []).append((seg.seg_index, content))
    target_map = {u: [c for _, c in sorted(v, key=lambda x: x[0])] for u, v in targets.items()}
    out = get_handler(fa.filename).merge(original, target_map, job.target_lang)
    base, _, ext = fa.filename.rpartition(".")
    out_name = (
        f"{base or fa.filename}.{job.target_lang}.{ext}" if base else f"{fa.filename}.{job.target_lang}"
    )
    job.output_storage_key = storage.make_key(job.org_id, "output", job.id, out_name)
    storage.put(job.output_storage_key, out)

    for seg in segs:
        if seg.state in ("auto_approved", "reviewed"):
            transition(seg, "segment", "delivered")
    job.delivered_at = utcnow()
    transition(job, "job", "delivered")
    events.record(session, job, "delivered", output=out_name)
    session.flush()
    pack = evidence.build(session, job)
    job.evidence_storage_key = storage.make_key(job.org_id, "evidence", job.id, "evidence.json")
    storage.put(job.evidence_storage_key, evidence.to_json(pack))
    storage.put(storage.make_key(job.org_id, "evidence", job.id, "evidence.pdf"), evidence.to_pdf(pack))

    usage.record(
        session,
        job.org_id,
        job.id,
        "word",
        Decimal(job.word_count),
        job.revenue or Decimal("0"),
        f"{job.id}:words",
        {"tier": job.tier, "pair": f"{job.source_lang}-{job.target_lang}"},
    )
    webhooks.emit(session, job.org_id, "job.delivered", {"job_id": job.id, "project_id": job.project_id})


def fail_job(session: Session, job_id: str, reason: str) -> None:
    from arbiter import webhooks

    job = _job(session, job_id)
    if job.state in ("delivered", "cancelled", "failed", "settled"):
        return
    job.failure_reason = reason[:2000]
    transition(job, "job", "failed")
    events.record(session, job, "failed", reason=reason[:500])
    webhooks.emit(session, job.org_id, "job.failed", {"job_id": job.id, "reason": reason[:500]})


def cancel_job(session: Session, job: Job) -> None:
    transition(job, "job", "cancelled")
    for seg in _segments(session, job, ["needs_review"]):
        _cancel_tasks(session, seg)
    events.record(session, job, "cancelled")


HANDLERS = {
    "job.prepare": prepare,
    "job.translate": translate,
    "job.score": score,
    "job.deadline": deadline,
    "job.merge": merge,
}
