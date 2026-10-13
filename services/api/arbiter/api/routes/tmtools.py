"""TM tools (module tms): TM editor, alignment into the TM, term extraction, TM QA.

R-TM-01 holds for every write path into the TM: alignment commits need the same rights
confirmation as a TMX import, and the confirming user is stored on each entry.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from arbiter.api.deps import DB, PM, Customer, Paging, listing, require_module
from arbiter.api.routes.assets import RightsNotConfirmed, get_glossary, term_view
from arbiter.api.routes.jobs import actor_of, get_job
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.fileproc.base import FormatError
from arbiter.linguistic import glossary as gl
from arbiter.linguistic import tm
from arbiter.linguistic.align import align
from arbiter.linguistic.tm import _compatible, _lang_clause
from arbiter.models import FileAsset, Segment, Term, TmAlignment, TmEntry, utcnow
from arbiter.tms import tmtools
from arbiter.tms.tagged import escape

router = APIRouter(tags=["tm-tools"], dependencies=[require_module("tms")])

MAX_BYTES = 100 * 1024 * 1024
TM_STATUSES = ("approved", "imported", "stale")


def _read(upload: UploadFile) -> bytes:
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise Invalid("the file is larger than the 100 MB limit")
    if not data.strip():
        raise Invalid("the file is empty")
    return data


# --------------------------------------------------------------------------- TM editor


def entry_view(e: TmEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "source_lang": e.source_lang,
        "target_lang": e.target_lang,
        "content_type": e.content_type,
        "source_tagged": e.source_tagged,
        "target_tagged": e.target_tagged,
        "status": e.status,
        "origin": e.origin,
        "job_id": e.job_id,
        "has_context": e.context_hash is not None,
        "rights_confirmed_by": e.rights_confirmed_by,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _get_entry(db: Any, org_id: str, entry_id: str, *, lock: bool = False) -> TmEntry:
    q = select(TmEntry).where(TmEntry.id == entry_id, TmEntry.org_id == org_id)
    if lock:
        q = q.with_for_update()
    e = db.execute(q).scalar_one_or_none()
    if e is None:
        raise NotFound("TM entry not found")
    return e


@router.get("/tm/entries")
def list_entries(
    p: Customer,
    db: DB,
    pg: Paging,
    q: Annotated[str | None, Query(max_length=500)] = None,
    source_lang: Annotated[str | None, Query(max_length=16)] = None,
    target_lang: Annotated[str | None, Query(max_length=16)] = None,
    origin: Literal["review", "import", "client"] | None = None,
    status: Literal["approved", "imported", "stale"] | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
) -> dict[str, Any]:
    """Browse the TM: text search on both sides, filters by pair, origin, status and date."""
    stmt = select(TmEntry).where(TmEntry.org_id == p.org_id)
    if source_lang:
        stmt = stmt.where(_lang_clause(TmEntry.source_lang, source_lang))
    if target_lang:
        stmt = stmt.where(_lang_clause(TmEntry.target_lang, target_lang))
    if origin:
        stmt = stmt.where(TmEntry.origin == origin)
    if status:
        stmt = stmt.where(TmEntry.status == status)
    if created_from:
        stmt = stmt.where(TmEntry.created_at >= datetime.combine(created_from, time.min).astimezone())
    if created_to:
        stmt = stmt.where(TmEntry.created_at <= datetime.combine(created_to, time.max).astimezone())
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(TmEntry.source_plain.ilike(like) | TmEntry.target_plain.ilike(like))
    rows = list(
        db.execute(
            stmt.order_by(TmEntry.updated_at.desc(), TmEntry.id.desc()).offset(pg.offset).limit(pg.limit + 1)
        ).scalars()
    )
    if source_lang or target_lang:
        rows = [
            e
            for e in rows
            if (not source_lang or _compatible(e.source_lang, source_lang))
            and (not target_lang or _compatible(e.target_lang, target_lang))
        ]
    return listing([entry_view(e) for e in rows], pg)


class EntryPatch(BaseModel):
    source_tagged: str | None = Field(default=None, min_length=1, max_length=100_000)
    target_tagged: str | None = Field(default=None, min_length=1, max_length=100_000)
    status: Literal["approved", "stale"] | None = None


@router.patch("/tm/entries/{entry_id}")
def update_entry(entry_id: str, body: EntryPatch, p: PM, db: DB) -> dict[str, Any]:
    e = _get_entry(db, p.org_id, entry_id, lock=True)
    if body.source_tagged is not None and body.source_tagged != e.source_tagged:
        if not tm.tagged_plain(body.source_tagged).strip():
            raise Invalid("the source has no text")
        tm.set_source(e, body.source_tagged)
    if body.target_tagged is not None and body.target_tagged != e.target_tagged:
        if not tm.tagged_plain(body.target_tagged).strip():
            raise Invalid("the target has no text")
        tm.set_target(e, body.target_tagged)
    if body.status is not None:
        e.status = body.status
        e.updated_at = utcnow()
    db.flush()
    return entry_view(e)


@router.delete("/tm/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: str, p: PM, db: DB) -> Response:
    db.delete(_get_entry(db, p.org_id, entry_id, lock=True))
    return Response(status_code=204)


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=5000)
    action: Literal["delete", "mark_stale", "mark_approved"]


@router.post("/tm/entries/bulk")
def bulk_entries(body: BulkIn, p: PM, db: DB) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(TmEntry).where(TmEntry.org_id == p.org_id, TmEntry.id.in_(body.ids)).with_for_update()
        ).scalars()
    )
    for e in rows:
        if body.action == "delete":
            db.delete(e)
        else:
            e.status = "stale" if body.action == "mark_stale" else "approved"
            e.updated_at = utcnow()
    db.flush()
    return {"changed": len(rows), "action": body.action}


# --------------------------------------------------------------------------- alignment


def alignment_view(a: TmAlignment) -> dict[str, Any]:
    pairs = list(a.pairs or [])
    return {
        "id": a.id,
        "source_lang": a.source_lang,
        "target_lang": a.target_lang,
        "source_filename": a.source_filename,
        "target_filename": a.target_filename,
        "content_type": a.content_type,
        "status": a.status,
        "committed_count": a.committed_count,
        "pairs": pairs,
        "stats": {
            "pairs": len(pairs),
            "one_to_one": sum(1 for x in pairs if len(x["src"]) == 1 and len(x["tgt"]) == 1),
            "unaligned": sum(1 for x in pairs if not x["src"] or not x["tgt"]),
            "low_confidence": sum(1 for x in pairs if x["src"] and x["tgt"] and x["confidence"] < 0.5),
        },
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "committed_at": a.committed_at.isoformat() if a.committed_at else None,
    }


@router.post("/tm/align", status_code=201)
def create_alignment(
    p: PM,
    db: DB,
    source_file: Annotated[UploadFile, File()],
    target_file: Annotated[UploadFile, File()],
    source_lang: Annotated[str, Form(min_length=2, max_length=16)],
    target_lang: Annotated[str, Form(min_length=2, max_length=16)],
    content_type: Annotated[str, Form(max_length=60)] = "general",
) -> dict[str, Any]:
    """Extract both documents (any supported format), align sentences (Gale-Church refined by
    embedding similarity) and return the review grid. Nothing enters the TM until commit."""
    try:
        src = tmtools.document_sentences(source_file.filename or "source", _read(source_file), source_lang)
        tgt = tmtools.document_sentences(target_file.filename or "target", _read(target_file), target_lang)
    except FormatError as e:
        raise Invalid(str(e)) from None
    src_plain = [tm.tagged_plain(s) for s in src]
    tgt_plain = [tm.tagged_plain(t) for t in tgt]
    pairs = []
    for i, bead in enumerate(align(src_plain, tgt_plain)):
        pairs.append(
            {
                "index": i,
                "src": bead.src,
                "tgt": bead.tgt,
                "source": escape(" ".join(src_plain[k] for k in bead.src)),
                "target": escape(" ".join(tgt_plain[k] for k in bead.tgt)),
                "confidence": bead.confidence,
                "accepted": bool(bead.src and bead.tgt and bead.confidence >= 0.5),
            }
        )
    a = TmAlignment(
        org_id=p.org_id,
        source_lang=source_lang,
        target_lang=target_lang,
        source_filename=(source_file.filename or "source")[:400],
        target_filename=(target_file.filename or "target")[:400],
        content_type=content_type or "general",
        pairs=pairs,
        status="review",
        committed_count=0,
        created_by=actor_of(p),
    )
    db.add(a)
    db.flush()
    return alignment_view(a)


def _get_alignment(db: Any, org_id: str, alignment_id: str) -> TmAlignment:
    a = db.execute(
        select(TmAlignment)
        .where(TmAlignment.id == alignment_id, TmAlignment.org_id == org_id)
        .with_for_update()
    ).scalar_one_or_none()
    if a is None:
        raise NotFound("alignment not found")
    return a


@router.get("/tm/align/{alignment_id}")
def get_alignment(alignment_id: str, p: Customer, db: DB) -> dict[str, Any]:
    return alignment_view(_get_alignment(db, p.org_id, alignment_id))


class PairEdit(BaseModel):
    index: int = Field(ge=0)
    accepted: bool
    source: str | None = Field(default=None, max_length=100_000)
    target: str | None = Field(default=None, max_length=100_000)


class CommitIn(BaseModel):
    rights_confirmed: bool = False
    pairs: list[PairEdit] | None = Field(default=None, max_length=100_000)


@router.post("/tm/align/{alignment_id}/commit")
def commit_alignment(alignment_id: str, body: CommitIn, p: PM, db: DB) -> dict[str, Any]:
    """Store the accepted pairs (with the reviewer's edits) in the TM, like a TMX import."""
    if not body.rights_confirmed:
        raise RightsNotConfirmed(
            "confirm that your organization owns the rights to these documents (R-TM-01)"
        )
    a = _get_alignment(db, p.org_id, alignment_id)
    if a.status == "committed":
        raise Conflict("this alignment was already stored in the TM")
    pairs = [dict(x) for x in a.pairs or []]
    by_index = {x["index"]: x for x in pairs}
    for edit in body.pairs or []:
        row = by_index.get(edit.index)
        if row is None:
            raise Invalid(f"pair {edit.index} does not exist")
        row["accepted"] = edit.accepted
        if edit.source is not None:
            row["source"] = edit.source
        if edit.target is not None:
            row["target"] = edit.target
    chosen = [(x["source"], x["target"]) for x in pairs if x["accepted"] and x["source"] and x["target"]]
    result = tm.import_pairs(
        db, p.org_id, a.source_lang, a.target_lang, chosen, actor_of(p), content_type=a.content_type
    )
    a.pairs = pairs
    a.status = "committed"
    a.committed_count = result["imported"]
    a.committed_at = utcnow()
    db.flush()
    return {**result, "alignment": alignment_view(a)}


# --------------------------------------------------------------------------- term extraction


@router.post("/glossaries/{glossary_id}/extract")
def extract_terms(
    glossary_id: str,
    p: PM,
    db: DB,
    source_lang: Annotated[str | None, Form(max_length=16)] = None,
    target_lang: Annotated[str | None, Form(max_length=16)] = None,
    job_id: Annotated[str | None, Form(max_length=40)] = None,
    file: Annotated[UploadFile | None, File()] = None,
    min_freq: Annotated[int, Form(ge=1, le=100)] = 2,
    limit: Annotated[int, Form(ge=1, le=500)] = 50,
) -> dict[str, Any]:
    """Term candidates from a job or an uploaded file: frequent n-grams grouped by lemma,
    stopwords removed, terms already in the glossary skipped, with target candidates from
    the job's translations and the TM. Accept with POST /glossaries/{id}/extract/accept."""
    g = get_glossary(db, p, glossary_id)
    parallel: list[tuple[str, str]] = []
    if job_id:
        job = get_job(db, p, job_id)
        sl, tl = job.source_lang, job.target_lang
        segs = list(
            db.execute(select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)).scalars()
        )
        sources = [s.source_plain for s in segs]
        parallel = [(s.source_plain, tm.tagged_plain(s.target_tagged)) for s in segs if s.target_tagged]
        name = db.get(FileAsset, job.file_id)
        origin = {"job_id": job.id, "filename": name.filename if name else None}
    elif file is not None:
        if not source_lang:
            raise Invalid("source_lang is required with a file")
        try:
            sources = [
                tm.tagged_plain(s)
                for s in tmtools.document_sentences(file.filename or "file", _read(file), source_lang)
            ]
        except FormatError as e:
            raise Invalid(str(e)) from None
        sl, tl = source_lang, target_lang or ""
        origin = {"job_id": None, "filename": file.filename}
    else:
        raise Invalid("give a job_id or upload a file")
    if tl:
        parallel += tmtools.tm_parallel(db, p.org_id, sl, tl)
    existing = {
        t.source_term
        for t in db.execute(select(Term).where(Term.glossary_id == g.id, Term.valid_to.is_(None))).scalars()
    }
    cands = tmtools.extract_terms(
        sources, sl, target_lang=tl, parallel=parallel, existing=existing, min_freq=min_freq, limit=limit
    )
    return {"source_lang": sl, "target_lang": tl, **origin, "items": cands}


class AcceptTerm(BaseModel):
    source_term: str = Field(min_length=1, max_length=500)
    target_term: str | None = Field(default=None, max_length=500)
    kind: Literal["mandatory", "preferred", "forbidden", "do_not_translate"] = "preferred"
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    note: str = Field(default="", max_length=2000)


class AcceptIn(BaseModel):
    terms: list[AcceptTerm] = Field(min_length=1, max_length=500)


@router.post("/glossaries/{glossary_id}/extract/accept", status_code=201)
def accept_terms(glossary_id: str, body: AcceptIn, p: PM, db: DB) -> dict[str, Any]:
    g = get_glossary(db, p, glossary_id)
    added = []
    for t in body.terms:
        if t.kind in ("mandatory", "preferred") and not (t.target_term or "").strip():
            raise Invalid(f"'{t.source_term}' needs a target term to be {t.kind}")
        try:
            term = gl.add_term(
                db,
                g.id,
                t.source_lang,
                t.target_lang,
                t.source_term.strip(),
                (t.target_term or "").strip() or None,
                t.kind,
                note=t.note or "added from term extraction",
            )
        except ValueError as e:
            raise Invalid(str(e)) from None
        added.append(term_view(term))
    return {"items": added, "next_offset": None}


# --------------------------------------------------------------------------- TM QA


@router.get("/tm/qa")
def tm_qa(
    p: Customer,
    db: DB,
    source_lang: Annotated[str, Query(min_length=2, max_length=16)],
    target_lang: Annotated[str, Query(min_length=2, max_length=16)],
    glossary_id: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Inconsistent translations of the same source, and (with glossary_id) entries whose
    target breaks a current term of that glossary."""
    out: dict[str, Any] = {
        "inconsistent": tmtools.inconsistencies(db, p.org_id, source_lang, target_lang, limit),
        "glossary_violations": [],
    }
    if glossary_id:
        g = get_glossary(db, p, glossary_id)
        out["glossary_violations"] = tmtools.glossary_violations(
            db, p.org_id, g.id, source_lang, target_lang
        )[:limit]
    return out
