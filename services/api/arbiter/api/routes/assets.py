"""Linguistic assets: glossaries and terms, translation memory, term questions.

Reads are open to every customer role; changes need a PM (or an API key).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Header, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from lxml import etree
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from arbiter.api.deps import DB, PM, Customer, Paging, Principal, listing
from arbiter.api.routes.jobs import actor_of, attachment
from arbiter.api.routes.projects import idempotent_replay, idempotent_store
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.linguistic import glossary as gl
from arbiter.linguistic import tm
from arbiter.models import Glossary, Term, TermQuestion

router = APIRouter(tags=["assets"])

MAX_ASSET_BYTES = 100 * 1024 * 1024
TermKind = Literal["mandatory", "preferred", "forbidden", "do_not_translate"]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _read(upload: UploadFile) -> bytes:
    data = upload.file.read(MAX_ASSET_BYTES + 1)
    if len(data) > MAX_ASSET_BYTES:
        raise Invalid("the file is larger than the 100 MB limit for glossary and TM imports")
    if not data.strip():
        raise Invalid("the file is empty")
    return data


def _ext(upload: UploadFile) -> str:
    name = (upload.filename or "").lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


# --------------------------------------------------------------------------- glossaries


def glossary_view(g: Glossary, term_count: int) -> dict[str, Any]:
    return {
        "id": g.id,
        "name": g.name,
        "content_type": g.content_type,
        "version": g.version,
        "term_count": term_count,
        "created_at": _iso(g.created_at),
    }


def term_view(t: Term) -> dict[str, Any]:
    return {
        "id": t.id,
        "glossary_id": t.glossary_id,
        "source_lang": t.source_lang,
        "target_lang": t.target_lang,
        "source_term": t.source_term,
        "target_term": t.target_term,
        "kind": t.kind,
        "case_sensitive": t.case_sensitive,
        "note": t.note,
        "valid_from": t.valid_from,
        "valid_to": t.valid_to,
    }


def _term_counts(db: Session, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(Term.glossary_id, func.count())
        .where(Term.glossary_id.in_(ids), Term.valid_to.is_(None))
        .group_by(Term.glossary_id)
    ).all()
    return {gid: int(n) for gid, n in rows}


def get_glossary(db: Session, p: Principal, glossary_id: str) -> Glossary:
    g = db.get(Glossary, glossary_id)
    if g is None or g.org_id != p.org_id:
        raise NotFound("glossary not found")
    return g


def _get_term(db: Session, p: Principal, term_id: str) -> Term:
    t = db.get(Term, term_id)
    g = db.get(Glossary, t.glossary_id) if t is not None else None
    if t is None or g is None or g.org_id != p.org_id:
        raise NotFound("term not found")
    if t.valid_to is not None:
        raise Conflict("this term was retired or replaced by a newer version")
    return t


class GlossaryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_type: str | None = Field(default=None, max_length=60)


@router.get("/glossaries")
def list_glossaries(p: Customer, db: DB, pg: Paging) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(Glossary)
            .where(Glossary.org_id == p.org_id)
            .order_by(Glossary.name, Glossary.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    page = listing(rows, pg)
    counts = _term_counts(db, [g.id for g in page["items"]])
    page["items"] = [glossary_view(g, counts.get(g.id, 0)) for g in page["items"]]
    return page


@router.post("/glossaries", status_code=201)
def create_glossary(
    body: GlossaryIn, p: PM, db: DB, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    payload = body.model_dump(mode="json")
    replay = idempotent_replay(db, p, "glossaries", idempotency_key, payload)
    if replay is not None:
        return replay
    g = gl.create_glossary(db, p.org_id, body.name.strip(), (body.content_type or "").strip() or None)
    out = glossary_view(g, 0)
    idempotent_store(db, p, "glossaries", idempotency_key, payload, 201, out)
    return JSONResponse(out, status_code=201)


@router.get("/glossaries/{glossary_id}/terms")
def list_terms(
    glossary_id: str,
    p: Customer,
    db: DB,
    pg: Paging,
    q: str | None = None,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> dict[str, Any]:
    g = get_glossary(db, p, glossary_id)
    stmt = select(Term).where(Term.glossary_id == g.id, Term.valid_to.is_(None))
    if q and q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(Term.source_term.ilike(like, escape="\\"), Term.target_term.ilike(like, escape="\\"))
        )
    if source_lang:
        stmt = stmt.where(gl._lang_matches(Term.source_lang, source_lang))
    if target_lang:
        stmt = stmt.where(gl._lang_matches(Term.target_lang, target_lang))
    rows = list(
        db.execute(stmt.order_by(Term.source_term, Term.id).offset(pg.offset).limit(pg.limit + 1)).scalars()
    )
    return listing([term_view(t) for t in rows], pg)


class TermIn(BaseModel):
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    source_term: str = Field(min_length=1, max_length=500)
    target_term: str | None = Field(default=None, max_length=500)
    kind: TermKind = "mandatory"
    case_sensitive: bool = False
    note: str = Field(default="", max_length=2000)


@router.post("/glossaries/{glossary_id}/terms", status_code=201)
def add_term(glossary_id: str, body: TermIn, p: PM, db: DB) -> dict[str, Any]:
    """R-GL-11: every change bumps the glossary version; running jobs keep theirs."""
    g = get_glossary(db, p, glossary_id)
    try:
        t = gl.add_term(
            db,
            g.id,
            body.source_lang,
            body.target_lang,
            body.source_term,
            body.target_term,
            body.kind,
            case_sensitive=body.case_sensitive,
            note=body.note,
        )
    except ValueError as e:
        raise Invalid(str(e)) from None
    return term_view(t)


class TermPatch(BaseModel):
    source_lang: str | None = Field(default=None, min_length=2, max_length=16)
    target_lang: str | None = Field(default=None, min_length=2, max_length=16)
    source_term: str | None = Field(default=None, min_length=1, max_length=500)
    target_term: str | None = Field(default=None, max_length=500)
    kind: TermKind | None = None
    case_sensitive: bool | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.patch("/terms/{term_id}")
def update_term(term_id: str, body: TermPatch, p: PM, db: DB) -> dict[str, Any]:
    """Closes the current row and returns its successor (new id, R-GL-11 history kept)."""
    t = _get_term(db, p, term_id)
    changes = body.model_dump(exclude_unset=True)
    for k in ("source_lang", "target_lang", "source_term", "kind", "case_sensitive", "note"):
        if k in changes and changes[k] is None:
            del changes[k]
    if not changes:
        return term_view(t)
    try:
        new = gl.update_term(db, t.id, **changes)
    except ValueError as e:
        raise Invalid(str(e)) from None
    return term_view(new)


@router.delete("/terms/{term_id}", status_code=204)
def delete_term(term_id: str, p: PM, db: DB) -> Response:
    t = _get_term(db, p, term_id)
    gl.retire_term(db, t.id)
    return Response(status_code=204)


def _tbx_lang(data: bytes) -> str | None:
    """Source language of a TBX file when the form does not say: the root xml:lang."""
    try:
        root = etree.fromstring(data, gl._secure_parser())
    except etree.XMLSyntaxError:
        return None
    lang = root.get("{http://www.w3.org/XML/1998/namespace}lang")
    return lang.strip() if lang else None


@router.post("/glossaries/{glossary_id}/import")
def import_glossary(
    glossary_id: str,
    p: PM,
    db: DB,
    file: Annotated[UploadFile, File()],
    source_lang: Annotated[str | None, Form(max_length=16)] = None,
    target_lang: Annotated[str | None, Form(max_length=16)] = None,
) -> dict[str, Any]:
    """CSV/TSV (header names are tolerant; languages from columns or the form fields) or TBX.

    TBX source language: the `source_lang` form field, else the file's root xml:lang.
    """
    g = get_glossary(db, p, glossary_id)
    ext = _ext(file)
    data = _read(file)
    if ext in ("csv", "tsv", "txt"):
        return gl.import_csv(db, g.id, data, source_lang=source_lang or None, target_lang=target_lang or None)
    if ext in ("tbx", "xml"):
        sl = (source_lang or "").strip() or _tbx_lang(data)
        if not sl:
            raise Invalid("source_lang is required for this TBX file (no xml:lang on the root element)")
        targets = [target_lang] if target_lang else None
        return gl.import_tbx(db, g.id, data, source_lang=sl, target_langs=targets)
    raise Invalid("glossary import accepts .csv, .tsv or .tbx files")


@router.get("/glossaries/{glossary_id}/export")
def export_glossary(
    glossary_id: str, p: Customer, db: DB, format: Annotated[Literal["csv", "tbx"], Query()] = "csv"
) -> Response:
    g = get_glossary(db, p, glossary_id)
    base = "".join(c if c.isalnum() or c in "-_" else "_" for c in g.name)[:80] or "glossary"
    if format == "tbx":
        return Response(
            gl.export_tbx(db, g.id),
            media_type="application/x-tbx+xml",
            headers={"Content-Disposition": attachment(f"{base}.tbx")},
        )
    return Response(
        gl.export_csv(db, g.id).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": attachment(f"{base}.csv")},
    )


# --------------------------------------------------------------------------- translation memory


class RightsNotConfirmed(Invalid):
    code = "rights_not_confirmed"


@router.post("/tm/import")
def import_tm(
    p: PM,
    db: DB,
    file: Annotated[UploadFile, File()],
    rights_confirmed: Annotated[bool, Form()] = False,
    source_lang: Annotated[str | None, Form(max_length=16)] = None,
    content_type: Annotated[str, Form(max_length=60)] = "general",
) -> dict[str, Any]:
    """R-TM-01: we only learn from TM the client owns, so the uploader confirms the rights;
    the confirming user (or API key) is stored on every imported entry."""
    if not rights_confirmed:
        raise RightsNotConfirmed(
            "confirm that your organization owns the rights to this translation memory (R-TM-01)"
        )
    if _ext(file) not in ("tmx", "xml"):
        raise Invalid("TM import accepts .tmx files")
    data = _read(file)
    return tm.import_tmx(
        db,
        p.org_id,
        data,
        actor_of(p),
        content_type=content_type or "general",
        source_lang=source_lang or None,
    )


@router.get("/tm/search")
def search_tm(
    p: Customer,
    db: DB,
    q: Annotated[str, Query(min_length=1, max_length=5000)],
    source_lang: Annotated[str, Query(min_length=2, max_length=16)],
    target_lang: Annotated[str, Query(min_length=2, max_length=16)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
    matches = tm.lookup(db, p.org_id, source_lang, target_lang, q, None, limit=limit)
    items = [
        {
            "entry_id": m.entry_id,
            "kind": m.kind,
            "score": m.score,
            "source_tagged": m.source_tagged,
            "target_tagged": m.target_tagged,
        }
        for m in matches
    ]
    return {"items": items, "next_offset": None}


@router.get("/tm/export")
def export_tm(
    p: Customer,
    db: DB,
    source_lang: Annotated[str, Query(min_length=2, max_length=16)],
    target_lang: Annotated[str, Query(min_length=2, max_length=16)],
) -> Response:
    data = tm.export_tmx(db, p.org_id, source_lang, target_lang)
    return Response(
        data,
        media_type="application/x-tmx+xml",
        headers={"Content-Disposition": attachment(f"tm-{source_lang}-{target_lang}.tmx")},
    )


# --------------------------------------------------------------------------- term questions


def question_view(tq: TermQuestion) -> dict[str, Any]:
    return {
        "id": tq.id,
        "source_term": tq.source_term,
        "source_lang": tq.source_lang,
        "target_lang": tq.target_lang,
        "options": list(tq.options or []),
        "status": tq.status,
        "answer": tq.answer,
        "job_id": tq.job_id,
        "segment_id": tq.segment_id,
        "created_at": _iso(tq.created_at),
    }


@router.get("/term-questions")
def list_questions(
    p: Customer,
    db: DB,
    pg: Paging,
    status: Literal["open", "answered", "dismissed"] | None = None,
) -> dict[str, Any]:
    stmt = select(TermQuestion).where(TermQuestion.org_id == p.org_id)
    if status:
        stmt = stmt.where(TermQuestion.status == status)
    rows = list(
        db.execute(
            stmt.order_by(TermQuestion.created_at.desc(), TermQuestion.id.desc())
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([question_view(r) for r in rows], pg)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=500)
    add_to_glossary_id: str | None = Field(default=None, max_length=40)


@router.post("/term-questions/{question_id}/answer")
def answer_question(question_id: str, body: AnswerIn, p: PM, db: DB) -> dict[str, Any]:
    """R-TM-06: the answer can become a mandatory term so the question is not asked again."""
    tq = db.execute(
        select(TermQuestion).where(TermQuestion.id == question_id).with_for_update()
    ).scalar_one_or_none()
    if tq is None or tq.org_id != p.org_id:
        raise NotFound("term question not found")
    if tq.status != "open":
        raise Conflict(f"this question is already {tq.status}")
    answer = body.answer.strip()
    if not answer:
        raise Invalid("answer is empty")
    if body.add_to_glossary_id:
        g = get_glossary(db, p, body.add_to_glossary_id)
        try:
            gl.add_term(db, g.id, tq.source_lang, tq.target_lang, tq.source_term, answer, "mandatory")
        except ValueError as e:
            raise Invalid(str(e)) from None
    tq.answer = answer
    tq.status = "answered"
    tq.meta = {**(tq.meta or {}), "answered_by": actor_of(p), "glossary_id": body.add_to_glossary_id}
    db.flush()
    return question_view(tq)
