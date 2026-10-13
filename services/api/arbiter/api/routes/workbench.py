"""Translator/PM workbench (module tms): the segment editor's API.

Reads are open to every customer role; structure changes (split, merge, locks), MT on
demand and forced replacements need a PM or an API key. Saving a target and approving
stay on PATCH /jobs/{id}/segments/{seg} and POST .../approve (routes/jobs.py), which now
also honour PM locks.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from arbiter import storage
from arbiter.api.deps import DB, PM, Customer, Paging, listing, require_module
from arbiter.api.routes.jobs import actor_of, get_job, segment_view
from arbiter.errors import Invalid, NotFound
from arbiter.linguistic.tm import SERVABLE_STATUSES, _compatible, _lang_clause
from arbiter.models import FileAsset, Job, Segment, SegmentComment, TmEntry
from arbiter.pipeline.units import slots_of
from arbiter.tms import comments as cm
from arbiter.tms import preview as pv
from arbiter.tms import workbench as wb

router = APIRouter(tags=["workbench"], dependencies=[require_module("tms")])


def editor_view(seg: Segment, counts: dict[str, int] | None = None) -> dict[str, Any]:
    c = counts or {}
    return {
        **segment_view(seg),
        "unit_id": seg.unit_id,
        "seg_index": seg.seg_index,
        "word_count": seg.word_count,
        "locked": bool(seg.locked_by),
        "locked_by": seg.locked_by,
        "locked_at": seg.locked_at.isoformat() if seg.locked_at else None,
        "qa_count": len((seg.signals or {}).get("hard_issues") or []),
        "comment_threads": c.get("threads", 0),
        "open_queries": c.get("open_queries", 0),
        "slots": slots_of(seg),
    }


def _bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    if value.lower() in ("1", "true", "yes"):
        return True
    if value.lower() in ("0", "false", "no"):
        return False
    raise Invalid("boolean filters take true or false")


@router.get("/jobs/{job_id}/editor/segments")
def editor_segments(
    job_id: str,
    p: Customer,
    db: DB,
    pg: Paging,
    state: str | None = None,
    decision: str | None = None,
    locked: str | None = None,
    has_comment: str | None = None,
    open_query: str | None = None,
    qa: str | None = None,
    tm_band: str | None = None,
    q: Annotated[str | None, Query(max_length=500)] = None,
) -> dict[str, Any]:
    """Segments for the editor with filters: state (comma list), decision, locked, has_comment,
    open_query, qa (stored hard QA issues), tm_band (none|lt75|75-84|85-94|95-99|100|101), q."""
    job = get_job(db, p, job_id)
    stmt = wb.editor_query(
        job,
        state=[s for s in (state or "").split(",") if s] or None,
        decision=decision or None,
        locked=_bool(locked),
        has_comment=_bool(has_comment),
        open_query=_bool(open_query),
        qa=_bool(qa),
        tm_band=tm_band or None,
        q=q or None,
    )
    rows = list(db.execute(stmt.offset(pg.offset).limit(pg.limit + 1)).scalars())
    page = listing(rows, pg)
    counts = wb.comment_counts(db, [s.id for s in page["items"]])
    page["items"] = [editor_view(s, counts.get(s.id)) for s in page["items"]]
    page["total"] = int(
        db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    )
    return page


class DraftIn(BaseModel):
    target_tagged: str = Field(max_length=100_000)


@router.post("/jobs/{job_id}/segments/{seg_id}/check")
def check_segment(job_id: str, seg_id: str, body: DraftIn, p: Customer, db: DB) -> dict[str, Any]:
    """Hard QA checks on a draft target. Nothing is saved."""
    job = get_job(db, p, job_id)
    seg = wb.get_segment(db, job, seg_id)
    return wb.check_draft(db, job, seg, body.target_tagged)


@router.get("/jobs/{job_id}/segments/{seg_id}/assist")
def assist(job_id: str, seg_id: str, p: Customer, db: DB) -> dict[str, Any]:
    """TM matches (with a diff of the match source against this source) and glossary hits."""
    job = get_job(db, p, job_id)
    return wb.assist(db, job, wb.get_segment(db, job, seg_id))


class MtIn(BaseModel):
    engine: str | None = Field(default=None, max_length=80)


@router.post("/jobs/{job_id}/segments/{seg_id}/mt")
def mt_suggestion(job_id: str, seg_id: str, body: MtIn, p: PM, db: DB) -> dict[str, Any]:
    """An MT suggestion on demand (not saved). The engine follows the org's routing."""
    job = get_job(db, p, job_id, lock=True)
    seg = wb.get_segment(db, job, seg_id)
    out = wb.mt_suggest(db, job, seg, body.engine)
    db.flush()
    return out


class SplitIn(BaseModel):
    source_offset: int = Field(ge=1)
    target_offset: int | None = Field(default=None, ge=0)


@router.post("/jobs/{job_id}/segments/{seg_id}/split")
def split_segment(job_id: str, seg_id: str, body: SplitIn, p: PM, db: DB) -> dict[str, Any]:
    job = get_job(db, p, job_id, lock=True)
    seg = wb.get_segment(db, job, seg_id, lock=True)
    wb.ensure_unlocked(seg, "client")  # locked segments are never split
    a, b = wb.split(db, job, seg, body.source_offset, body.target_offset, actor_of(p))
    return {"segments": [editor_view(a), editor_view(b)], "segment_count": job.segment_count}


@router.post("/jobs/{job_id}/segments/{seg_id}/merge-next")
def merge_next(job_id: str, seg_id: str, p: PM, db: DB) -> dict[str, Any]:
    job = get_job(db, p, job_id, lock=True)
    seg = wb.get_segment(db, job, seg_id, lock=True)
    keep = wb.merge_next(db, job, seg, actor_of(p))
    return {"segment": editor_view(keep), "segment_count": job.segment_count}


class LockIn(BaseModel):
    segment_ids: list[str] = Field(min_length=1, max_length=5000)
    locked: bool = True


@router.post("/jobs/{job_id}/segments/lock")
def lock_segments(job_id: str, body: LockIn, p: PM, db: DB) -> dict[str, Any]:
    job = get_job(db, p, job_id, lock=True)
    segs = list(
        db.execute(
            select(Segment).where(Segment.job_id == job.id, Segment.id.in_(body.segment_ids))
        ).scalars()
    )
    if len(segs) != len(set(body.segment_ids)):
        raise NotFound("segment not found")
    changed = wb.set_lock(db, job, segs, body.locked, actor_of(p))
    return {"changed": changed, "locked": body.locked}


class FindReplaceIn(BaseModel):
    find: str = Field(min_length=1, max_length=500)
    replace: str | None = Field(default=None, max_length=2000)
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False
    scope: Literal["target", "source", "both"] = "target"
    states: list[str] | None = None
    segment_ids: list[str] | None = Field(default=None, max_length=5000)
    apply: bool = False
    force: bool = False


@router.post("/jobs/{job_id}/find-replace")
def find_replace(job_id: str, body: FindReplaceIn, p: Customer, db: DB) -> dict[str, Any]:
    """Preview (apply=false) then apply. Replaces in target text runs only; skips locked and
    approved segments unless a PM sets force=true."""
    job = get_job(db, p, job_id, lock=body.apply)
    return wb.find_replace(
        db,
        job,
        find=body.find,
        replace=body.replace,
        regex=body.regex,
        case_sensitive=body.case_sensitive,
        whole_word=body.whole_word,
        scope=body.scope,
        states=body.states,
        segment_ids=body.segment_ids,
        apply=body.apply,
        force=body.force,
        role=p.role if p.role != "api" else "pm",
        actor=actor_of(p),
    )


# --------------------------------------------------------------------------- comments and queries


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    kind: Literal["comment", "query"] = "comment"
    segment_id: str | None = Field(default=None, max_length=40)
    parent_id: str | None = Field(default=None, max_length=40)
    mentions: list[str] | None = Field(default=None, max_length=20)


@router.get("/jobs/{job_id}/comments")
def list_comments(
    job_id: str,
    p: Customer,
    db: DB,
    segment_id: str | None = None,
    kind: Literal["comment", "query"] | None = None,
    resolved: str | None = None,
) -> dict[str, Any]:
    job = get_job(db, p, job_id)
    rows = cm.listing(db, job, role=p.role, segment_id=segment_id, kind=kind, resolved=_bool(resolved))
    return {"items": [cm.view(c) for c in rows], "next_offset": None}


@router.post("/jobs/{job_id}/comments", status_code=201)
def add_comment(job_id: str, body: CommentIn, p: Customer, db: DB) -> dict[str, Any]:
    job = get_job(db, p, job_id)
    if body.segment_id:
        wb.get_segment(db, job, body.segment_id)
    c = cm.create(
        db,
        job,
        role=p.role,
        actor=actor_of(p),
        body=body.body,
        kind=body.kind,
        segment_id=body.segment_id,
        parent_id=body.parent_id,
        mentions=body.mentions,
    )
    return cm.view(c)


class CommentPatch(BaseModel):
    resolved: bool


@router.patch("/comments/{comment_id}")
def patch_comment(comment_id: str, body: CommentPatch, p: Customer, db: DB) -> dict[str, Any]:
    c = db.get(SegmentComment, comment_id)
    if c is None or c.org_id != p.org_id:
        raise NotFound("comment not found")
    return cm.view(cm.resolve(db, c, resolved=body.resolved, role=p.role, actor=actor_of(p)))


@router.get("/queries")
def open_queries(p: Customer, db: DB, pg: Paging) -> dict[str, Any]:
    """Open client queries of the organization (the client portal inbox), with their replies."""
    roots = cm.open_queries(db, p.org_id, pg.limit + 1, pg.offset)
    page = listing(roots, pg)
    ids = [r.id for r in page["items"]]
    replies: dict[str, list[dict[str, Any]]] = {}
    if ids:
        for c in db.execute(
            select(SegmentComment)
            .where(SegmentComment.thread_id.in_(ids), SegmentComment.id != SegmentComment.thread_id)
            .order_by(SegmentComment.created_at)
        ).scalars():
            replies.setdefault(c.thread_id, []).append(cm.view(c))
    seg_ids = [r.segment_id for r in page["items"] if r.segment_id]
    segs = (
        {s.id: s for s in db.execute(select(Segment).where(Segment.id.in_(seg_ids))).scalars()}
        if seg_ids
        else {}
    )
    job_ids = {r.job_id for r in page["items"]}
    names = (
        dict(
            db.execute(
                select(Job.id, FileAsset.filename)
                .join(FileAsset, FileAsset.id == Job.file_id)
                .where(Job.id.in_(job_ids))
            ).all()
        )
        if job_ids
        else {}
    )
    out = []
    for r in page["items"]:
        seg = segs.get(r.segment_id or "")
        out.append(
            {
                **cm.view(r),
                "filename": names.get(r.job_id),
                "segment_seq": seg.seq if seg else None,
                "source_tagged": seg.source_tagged if seg else None,
                "target_tagged": seg.target_tagged if seg else None,
                "replies": replies.get(r.id, []),
            }
        )
    page["items"] = out
    return page


# --------------------------------------------------------------------------- preview


@router.get("/jobs/{job_id}/preview")
def preview(job_id: str, p: Customer, db: DB) -> Response:
    """The target document as HTML with the current translations (sandboxed by CSP)."""
    job = get_job(db, p, job_id)
    fa = db.get(FileAsset, job.file_id)
    if fa is None:
        raise NotFound("file not found")
    try:
        original = storage.get(fa.storage_key)
    except FileNotFoundError:
        raise NotFound("the source file is no longer stored (retention)") from None
    segs = list(db.execute(select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)).scalars())
    html, mode = pv.render(fa.filename, original, segs, job.target_lang, fa.options)
    return Response(
        html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": pv.CSP,
            "X-Preview-Mode": mode,
            "X-Content-Type-Options": "nosniff",
        },
    )


# --------------------------------------------------------------------------- concordance


@router.get("/tm/concordance")
def concordance(
    p: Customer,
    db: DB,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    source_lang: Annotated[str, Query(min_length=2, max_length=16)],
    target_lang: Annotated[str, Query(min_length=2, max_length=16)],
    side: Literal["source", "target", "both"] = "both",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    """TM entries containing the phrase on the source and/or target side (pg_trgm indexes),
    best word similarity first."""
    if not q.strip():
        raise Invalid("q is empty")
    like = f"%{q.strip()}%"
    conds = []
    if side in ("source", "both"):
        conds.append(TmEntry.source_plain.ilike(like))
    if side in ("target", "both"):
        conds.append(TmEntry.target_plain.ilike(like))
    sim = func.greatest(
        func.word_similarity(q, TmEntry.source_plain) if side != "target" else 0.0,
        func.word_similarity(q, TmEntry.target_plain) if side != "source" else 0.0,
    )
    rows = db.execute(
        select(TmEntry, sim.label("sim"))
        .where(
            TmEntry.org_id == p.org_id,
            TmEntry.status.in_(SERVABLE_STATUSES),
            _lang_clause(TmEntry.source_lang, source_lang),
            _lang_clause(TmEntry.target_lang, target_lang),
            conds[0] if len(conds) == 1 else (conds[0] | conds[1]),
        )
        .order_by(sim.desc(), TmEntry.updated_at.desc())
        .limit(limit)
    ).all()
    items = [
        {
            "entry_id": e.id,
            "source_tagged": e.source_tagged,
            "target_tagged": e.target_tagged,
            "score": round(float(s or 0) * 100, 1),
            "origin": e.origin,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None,
        }
        for e, s in rows
        if _compatible(e.source_lang, source_lang) and _compatible(e.target_lang, target_lang)
    ]
    return {"items": items, "next_offset": None}
