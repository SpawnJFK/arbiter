"""Jobs and segments: status, human edits and approvals, downloads, evidence, exceptions.

Customer edits count as human work: they write provenance with actor_type "human", go
into the client's TM (R-TM-01, it is their data) and may finish the job. A tag-breaking
edit is refused (D-009: error-severity tag issues never ship).
"""

from __future__ import annotations

import mimetypes
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter import storage
from arbiter.api.deps import DB, PM, Customer, Paging, Principal, listing
from arbiter.billing.ledger import money
from arbiter.domain.states import transition
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.fileproc.base import Content, FormatError, from_tagged, validate_tags
from arbiter.fileproc.registry import detect_and_extract
from arbiter.fileproc.xliff import export_xliff21
from arbiter.models import FileAsset, Job, Segment, TermQuestion, utcnow
from arbiter.pipeline import events, evidence, orchestrator

router = APIRouter(tags=["jobs"])

DONE_STATES = ("auto_approved", "reviewed", "delivered")
OUTPUT_STATES = ("delivered", "settled", "disputed")


# --------------------------------------------------------------------------- helpers


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def actor_of(p: Principal) -> str:
    if p.user is not None:
        return p.user.id
    if p.api_key is not None:
        return p.api_key.id
    return p.role


def attachment(filename: str) -> str:
    safe = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in filename)
    return f"attachment; filename=\"{safe}\"; filename*=UTF-8''{urlquote(filename)}"


def get_job(db: Session, p: Principal, job_id: str, *, lock: bool = False) -> Job:
    """Tenancy-checked job lookup. A job of another org is a 404, never a 403."""
    q = select(Job).where(Job.id == job_id, Job.org_id == p.org_id)
    if lock:
        q = q.with_for_update()
    job = db.execute(q).scalar_one_or_none()
    if job is None:
        raise NotFound("job not found")
    return job


def _get_segment(db: Session, job: Job, seg_id: str) -> Segment:
    seg = db.execute(
        select(Segment).where(Segment.id == seg_id, Segment.job_id == job.id).with_for_update()
    ).scalar_one_or_none()
    if seg is None:
        raise NotFound("segment not found")
    return seg


def _done_counts(db: Session, job_ids: Sequence[str]) -> dict[str, int]:
    if not job_ids:
        return {}
    rows = db.execute(
        select(Segment.job_id, func.count())
        .where(Segment.job_id.in_(list(job_ids)), Segment.state.in_(DONE_STATES))
        .group_by(Segment.job_id)
    ).all()
    return {jid: int(n) for jid, n in rows}


def _job_dict(job: Job, filename: str | None, done: int, hide_money: bool) -> dict[str, Any]:
    cost = (job.cost_engines or Decimal("0")) + (job.cost_reviewers or Decimal("0"))
    revenue = job.revenue or Decimal("0")
    progress = 1.0 if job.state in OUTPUT_STATES else (done / job.segment_count if job.segment_count else 0.0)
    return {
        "id": job.id,
        "project_id": job.project_id,
        "file_id": job.file_id,
        "filename": filename,
        "source_lang": job.source_lang,
        "target_lang": job.target_lang,
        "tier": job.tier,
        "content_type": job.content_type,
        "state": job.state,
        "segment_count": job.segment_count,
        "word_count": job.word_count,
        "auto_approved_count": job.auto_approved_count,
        "review_count": job.review_count,
        "ai_reviewed_count": job.ai_reviewed_count,
        "progress": round(min(1.0, progress), 4),
        "threshold": job.threshold,
        "est_auto_rate": job.est_auto_rate,
        "revenue": None if hide_money else money(revenue),
        "cost": None if hide_money else money(cost),
        "margin": None if hide_money else money(revenue - cost),
        "no_reviewer_fallback_used": job.no_reviewer_fallback_used,
        "failure_reason": job.failure_reason,
        "due_at": _iso(job.due_at),
        "started_at": _iso(job.started_at),
        "delivered_at": _iso(job.delivered_at),
        "created_at": _iso(job.created_at),
    }


def jobs_view(db: Session, p: Principal, jobs: Sequence[Job]) -> list[dict[str, Any]]:
    """Job per docs/api-contract.md. Money (revenue/cost/margin) is null for the client role."""
    file_ids = {j.file_id for j in jobs}
    names = (
        dict(db.execute(select(FileAsset.id, FileAsset.filename).where(FileAsset.id.in_(file_ids))).all())
        if file_ids
        else {}
    )
    done = _done_counts(db, [j.id for j in jobs])
    hide = p.role == "client"
    return [_job_dict(j, names.get(j.file_id), done.get(j.id, 0), hide) for j in jobs]


def job_view(db: Session, p: Principal, job: Job) -> dict[str, Any]:
    return jobs_view(db, p, [job])[0]


def segment_view(seg: Segment) -> dict[str, Any]:
    return {
        "id": seg.id,
        "seq": seg.seq,
        "source_tagged": seg.source_tagged,
        "target_tagged": seg.target_tagged,
        "state": seg.state,
        "origin": seg.origin,
        "engine": seg.engine,
        "tm_match": seg.tm_match,
        "qe_score": seg.qe_score,
        "decision": seg.decision,
        "reasons": list(seg.reasons or []),
        "signals": dict(seg.signals or {}),
        "reviewer_id": seg.reviewer_id,
        "is_control_sample": seg.is_control_sample,
        "context": seg.context,
        "max_length": seg.max_length,
        "updated_at": _iso(seg.updated_at),
    }


def _source_content(seg: Segment) -> Content:
    return from_tagged(seg.source_tagged, orchestrator._codes(seg))


class TagError(Invalid):
    code = "tag_error"


def _check_tags(seg: Segment, target: str) -> None:
    """D-009: error-severity tag issues (lost standalone code, broken pair, unknown code) refuse."""
    issues = [i for i in validate_tags(_source_content(seg), target) if i.severity == "error"]
    if issues:
        raise TagError(
            "the translation must keep the inline codes of the source",
            {"issues": [{"kind": i.kind, "code_id": i.code_id, "detail": i.detail} for i in issues]},
        )


def _mark_reviewed(db: Session, job: Job, seg: Segment, actor: str, event: str) -> None:
    """needs_review -> reviewed by a customer user; same effects as a reviewer's decision."""
    seg.decision = "reviewed"
    if seg.engine_target_tagged and seg.target_tagged:
        from rapidfuzz.distance import Levenshtein

        seg.edit_distance = Levenshtein.normalized_distance(seg.engine_target_tagged, seg.target_tagged)
    transition(seg, "segment", "reviewed")
    seg.updated_at = utcnow()
    events.record(db, job, event, segment=seg, actor_type="human", actor_id=actor, by="customer")
    orchestrator._cancel_tasks(db, seg)
    orchestrator._learn(db, job, seg)
    db.flush()
    orchestrator._advance(db, job)


# --------------------------------------------------------------------------- jobs


@router.get("/jobs")
def list_jobs(
    p: Customer,
    db: DB,
    pg: Paging,
    state: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    q = select(Job).where(Job.org_id == p.org_id)
    if state:
        q = q.where(Job.state == state)
    if project_id:
        q = q.where(Job.project_id == project_id)
    rows = list(
        db.execute(
            q.order_by(Job.created_at.desc(), Job.id.desc()).offset(pg.offset).limit(pg.limit + 1)
        ).scalars()
    )
    page = listing(rows, pg)
    page["items"] = jobs_view(db, p, page["items"])
    return page


@router.get("/jobs/{job_id}")
def get_job_route(job_id: str, p: Customer, db: DB) -> dict[str, Any]:
    return job_view(db, p, get_job(db, p, job_id))


@router.get("/jobs/{job_id}/segments")
def list_segments(
    job_id: str,
    p: Customer,
    db: DB,
    pg: Paging,
    state: str | None = None,
    decision: str | None = None,
) -> dict[str, Any]:
    job = get_job(db, p, job_id)
    q = select(Segment).where(Segment.job_id == job.id)
    if state:
        q = q.where(Segment.state == state)
    if decision:
        q = q.where(Segment.decision == decision)
    rows = list(db.execute(q.order_by(Segment.seq).offset(pg.offset).limit(pg.limit + 1)).scalars())
    return listing([segment_view(s) for s in rows], pg)


class SegmentPatch(BaseModel):
    target_tagged: str = Field(min_length=1, max_length=100_000)


@router.patch("/jobs/{job_id}/segments/{seg_id}")
def edit_segment(job_id: str, seg_id: str, body: SegmentPatch, p: Customer, db: DB) -> dict[str, Any]:
    """A PM/client edit counts as a human decision (provenance actor_type "human").

    needs_review -> reviewed (and the job may finish); auto_approved/reviewed keep their
    state; delivered stays delivered (the edit is recorded and learned into the TM, the
    delivered file is not rebuilt). Segments still in the machine pipeline or held by a
    reviewer cannot be edited.
    """
    job = get_job(db, p, job_id, lock=True)
    if job.state in ("cancelled", "failed", "merging"):
        raise Conflict(f"segments of a {job.state} job cannot be edited")
    seg = _get_segment(db, job, seg_id)
    if seg.state in ("pending", "translated"):
        raise Conflict("this segment is still being translated")
    if seg.state == "in_review":
        raise Conflict("a reviewer is working on this segment right now")
    target = body.target_tagged
    _check_tags(seg, target)
    actor = actor_of(p)
    if target != seg.target_tagged:
        orchestrator._set_target(db, job, seg, target, origin="human", actor=actor, by="customer")
    if seg.state == "needs_review":
        _mark_reviewed(db, job, seg, actor, "reviewed")
    else:
        events.record(db, job, "edited", segment=seg, actor_type="human", actor_id=actor, state=seg.state)
        orchestrator._learn(db, job, seg)
    db.flush()
    return segment_view(seg)


@router.post("/jobs/{job_id}/segments/{seg_id}/approve")
def approve_segment(job_id: str, seg_id: str, p: Customer, db: DB) -> dict[str, Any]:
    """needs_review -> reviewed as is. Approving again is a no-op; a target with broken
    tags must be fixed (PATCH) first."""
    job = get_job(db, p, job_id, lock=True)
    if job.state in ("cancelled", "failed", "merging"):
        raise Conflict(f"segments of a {job.state} job cannot be approved")
    seg = _get_segment(db, job, seg_id)
    if seg.state in ("auto_approved", "reviewed", "delivered"):
        return segment_view(seg)
    if seg.state != "needs_review":
        raise Conflict(f"a segment in state {seg.state} cannot be approved")
    if not seg.target_tagged:
        raise Invalid("this segment has no translation yet; edit it first")
    _check_tags(seg, seg.target_tagged)
    _mark_reviewed(db, job, seg, actor_of(p), "approved")
    return segment_view(seg)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, p: PM, db: DB) -> dict[str, Any]:
    """Cancelling twice is a no-op; a delivered or failed job cannot be cancelled (409)."""
    job = get_job(db, p, job_id, lock=True)
    if job.state != "cancelled":
        orchestrator.cancel_job(db, job)  # IllegalTransition -> 409 illegal_state
    db.flush()
    return job_view(db, p, job)


class NotDelivered(Conflict):
    code = "not_delivered"


@router.get("/jobs/{job_id}/download")
def download(job_id: str, p: Customer, db: DB) -> Response:
    job = get_job(db, p, job_id)
    if job.state not in OUTPUT_STATES or not job.output_storage_key:
        raise NotDelivered("the translated file is available once the job is delivered")
    try:
        data = storage.get(job.output_storage_key)
    except FileNotFoundError:
        raise NotFound("the translated file is no longer stored (retention)") from None
    name = job.output_storage_key.rsplit("/", 1)[-1]
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(data, media_type=media, headers={"Content-Disposition": attachment(name)})


@router.get("/jobs/{job_id}/xliff")
def xliff(job_id: str, p: Customer, db: DB) -> Response:
    """XLIFF 2.1 of the job: every unit whose segments all have a target carries it."""
    job = get_job(db, p, job_id)
    fa = db.get(FileAsset, job.file_id)
    if fa is None:
        raise NotFound("file not found")
    try:
        result = detect_and_extract(fa.filename, storage.get(fa.storage_key), job.source_lang)
    except FileNotFoundError:
        raise NotFound("the source file is no longer stored (retention)") from None
    segs = db.execute(select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)).scalars()
    by_unit: dict[str, dict[int, Content | None]] = {}
    for seg in segs:
        content: Content | None = None
        if seg.target_tagged:
            try:
                content = from_tagged(seg.target_tagged, orchestrator._codes(seg))
            except ValueError:
                content = None
        by_unit.setdefault(seg.unit_id, {})[seg.seg_index] = content
    targets: dict[str, list[Content]] = {}
    for unit in result.units:
        got = by_unit.get(unit.unit_id, {})
        row = [got.get(i) for i in range(len(unit.segments))]
        if row and all(c is not None for c in row):
            targets[unit.unit_id] = [c for c in row if c is not None]
    try:
        data = export_xliff21(result, targets, job.source_lang, job.target_lang, fa.filename)
    except FormatError:
        data = export_xliff21(result, None, job.source_lang, job.target_lang, fa.filename)
    name = f"{fa.filename}.{job.target_lang}.xlf"
    return Response(
        data, media_type="application/xliff+xml", headers={"Content-Disposition": attachment(name)}
    )


@router.get("/jobs/{job_id}/evidence")
def get_evidence(
    job_id: str, p: Customer, db: DB, format: Literal["json", "pdf"] = Query(default="json")
) -> Response:
    """The stored pack of a delivered job; for a job still in progress a live pack."""
    job = get_job(db, p, job_id)
    data: bytes | None = None
    if job.evidence_storage_key:
        key = job.evidence_storage_key
        if format == "pdf":
            key = key.rsplit("/", 1)[0] + "/evidence.pdf"
        try:
            data = storage.get(key)
        except FileNotFoundError:
            data = None
    if data is None:
        pack = evidence.build(db, job)
        data = evidence.to_pdf(pack) if format == "pdf" else evidence.to_json(pack)
    media = "application/pdf" if format == "pdf" else "application/json"
    headers = {"Content-Disposition": attachment(f"evidence-{job.id}.{format}")} if format == "pdf" else {}
    return Response(data, media_type=media, headers=headers)


class ErrorReport(BaseModel):
    segment_id: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=1000)


@router.post("/jobs/{job_id}/report-error", status_code=201)
def report_error(job_id: str, body: ErrorReport, p: Customer, db: DB) -> dict[str, Any]:
    """An error the client found in a delivered segment (escaped error, feeds calibration)."""
    job = get_job(db, p, job_id, lock=True)
    seg = db.execute(
        select(Segment).where(Segment.id == body.segment_id, Segment.job_id == job.id)
    ).scalar_one_or_none()
    if seg is None:
        raise NotFound("segment not found")
    if seg.state != "delivered":
        raise Conflict("errors can be reported on delivered segments; edit the segment instead")
    err = orchestrator.report_error(db, job, seg.id, body.note)
    return {"id": err.id}


# --------------------------------------------------------------------------- exceptions


@router.get("/exceptions")
def exceptions(p: PM, db: DB, pg: Paging) -> dict[str, Any]:
    """Only what needs a human: failed jobs, blocked segments, open term questions, overdue reviews."""
    org_id = p.org_id
    now = utcnow()
    out: list[dict[str, Any]] = []
    for job in db.execute(select(Job).where(Job.org_id == org_id, Job.state == "failed")).scalars():
        out.append(
            {
                "kind": "job_failed",
                "job_id": job.id,
                "segment_id": None,
                "reason": job.failure_reason or "the job failed",
                "created_at": _iso(job.started_at or job.created_at),
            }
        )
    blocked = db.execute(
        select(Segment, Job.id)
        .join(Job, Job.id == Segment.job_id)
        .where(
            Job.org_id == org_id,
            Job.state == "review",
            Segment.decision == "blocked",
            Segment.state == "needs_review",
        )
        .order_by(Segment.seq)
    ).all()
    for seg, jid in blocked:
        out.append(
            {
                "kind": "segment_blocked",
                "job_id": jid,
                "segment_id": seg.id,
                "reason": ", ".join(seg.reasons or []) or "blocked by a hard check",
                "created_at": _iso(seg.updated_at),
            }
        )
    for tq in db.execute(
        select(TermQuestion).where(TermQuestion.org_id == org_id, TermQuestion.status == "open")
    ).scalars():
        out.append(
            {
                "kind": "term_question",
                "job_id": tq.job_id,
                "segment_id": tq.segment_id,
                "term_question_id": tq.id,
                "reason": f"No approved {tq.target_lang} translation for the term '{tq.source_term}'",
                "created_at": _iso(tq.created_at),
            }
        )
    overdue = db.execute(
        select(Job, func.count(Segment.id))
        .join(Segment, Segment.job_id == Job.id)
        .where(
            Job.org_id == org_id,
            Job.state == "review",
            Job.due_at.is_not(None),
            Job.due_at < now,
            Segment.state.in_(("needs_review", "in_review")),
        )
        .group_by(Job.id)
    ).all()
    for job, n in overdue:
        out.append(
            {
                "kind": "overdue",
                "job_id": job.id,
                "segment_id": None,
                "reason": f"{n} segment(s) still waiting for review past the due date",
                "created_at": _iso(job.due_at),
            }
        )
    out.sort(key=lambda e: e["created_at"] or "", reverse=True)
    return listing(out[pg.offset : pg.offset + pg.limit + 1], pg)
