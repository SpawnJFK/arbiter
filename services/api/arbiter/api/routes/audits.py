"""Quality auditor (module auditor): standalone QA/LQA of bilingual files from any tool.

Creating an audit stores the upload and queues it on the worker (audit.parse, audit.check
in batches, audit.finish); the client polls GET /audits/{id} for progress.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from sqlalchemy import func, select

from arbiter import storage
from arbiter.api.deps import DB, PM, Customer, Paging, listing, require_module
from arbiter.api.routes.assets import get_glossary
from arbiter.api.routes.jobs import actor_of, attachment
from arbiter.auditor import bilingual, report, service
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.fileproc.registry import get_handler
from arbiter.models import Audit, AuditSegment, new_id
from arbiter.pipeline.queue import enqueue

router = APIRouter(tags=["auditor"], dependencies=[require_module("auditor")])

MAX_BYTES = 200 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SEVERITIES = ("none", "neutral", "minor", "major", "critical")


def audit_view(a: Audit) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "source_lang": a.source_lang,
        "target_lang": a.target_lang,
        "input_format": a.input_format,
        "filename": a.filename,
        "target_filename": a.target_filename,
        "glossary_id": a.glossary_id,
        "settings": dict(a.settings or {}),
        "state": a.state,
        "progress": round(a.progress or 0.0, 4),
        "segments_total": a.segments_total,
        "segments_done": a.segments_done,
        "word_count": a.word_count,
        "mqm_score": a.mqm_score,
        "verdict": a.verdict,
        "ai_units": str((a.ai_units or Decimal("0")).quantize(Decimal("0.01"))),
        "summary": dict(a.summary or {}),
        "error": a.error,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "started_at": a.started_at.isoformat() if a.started_at else None,
        "finished_at": a.finished_at.isoformat() if a.finished_at else None,
    }


def segment_view(s: AuditSegment) -> dict[str, Any]:
    return {
        "id": s.id,
        "seq": s.seq,
        "ref": s.unit_id,
        "source_tagged": s.source_tagged,
        "target_tagged": s.target_tagged,
        "word_count": s.word_count,
        "issues": list(s.issues or []),
        "mqm_errors": list(s.mqm_errors or []),
        "ai_checked": s.ai_checked,
        "score": s.score,
        "max_severity": s.max_severity,
        "dimensions": list(s.dimensions or []),
    }


def _read(upload: UploadFile) -> bytes:
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise Invalid("the file is larger than the 200 MB limit for audits")
    if not data.strip():
        raise Invalid("the file is empty")
    return data


def _get(db: Any, org_id: str, audit_id: str, *, lock: bool = False) -> Audit:
    q = select(Audit).where(Audit.id == audit_id, Audit.org_id == org_id)
    if lock:
        q = q.with_for_update()
    a = db.execute(q).scalar_one_or_none()
    if a is None:
        raise NotFound("audit not found")
    return a


@router.post("/audits", status_code=201)
def create_audit(
    p: PM,
    db: DB,
    file: Annotated[UploadFile, File()],
    source_lang: Annotated[str, Form(min_length=2, max_length=16)],
    target_lang: Annotated[str, Form(min_length=2, max_length=16)],
    target_file: Annotated[UploadFile | None, File()] = None,
    name: Annotated[str | None, Form(max_length=200)] = None,
    glossary_id: Annotated[str | None, Form(max_length=40)] = None,
    ai_mode: Annotated[Literal["none", "sample", "full"], Form()] = "none",
    ai_sample_pct: Annotated[float, Form(ge=0.5, le=100)] = 10.0,
    threshold: Annotated[float | None, Form(ge=0, le=100)] = None,
    consistency: Annotated[bool, Form()] = True,
    content_type: Annotated[str, Form(max_length=60)] = "general",
) -> dict[str, Any]:
    """Upload a bilingual file (XLIFF 1.2/2.x, TMX, CSV, XLSX), or a source document plus
    target_file (any supported format; aligned sentence by sentence), and queue the audit."""
    filename = file.filename or "upload"
    data = _read(file)
    tname: str | None = None
    tdata: bytes | None = None
    if target_file is not None and (target_file.filename or ""):
        tname = target_file.filename or "target"
        tdata = _read(target_file)
        get_handler(filename)  # FormatError -> 422 unsupported_file
        get_handler(tname)
        fmt = "pair"
    else:
        fmt = bilingual.detect_format(filename) or ""
        if not fmt:
            raise Invalid(
                "upload an XLIFF, TMX, bilingual CSV or XLSX file, or a source document with its translation"
            )
    if glossary_id:
        get_glossary(db, p, glossary_id)
    audit_id = new_id("aud")
    key = storage.make_key(p.org_id, "audit", audit_id, filename)
    storage.put(key, data)
    tkey = None
    if tdata is not None and tname is not None:
        tkey = storage.make_key(p.org_id, "audit", audit_id, f"target-{tname}")
        storage.put(tkey, tdata)
    a = Audit(
        id=audit_id,
        org_id=p.org_id,
        name=(name or filename).strip()[:200] or filename,
        source_lang=source_lang,
        target_lang=target_lang,
        input_format=fmt,
        filename=filename[:400],
        storage_key=key,
        target_filename=tname[:400] if tname else None,
        target_storage_key=tkey,
        glossary_id=glossary_id or None,
        settings={
            "ai_mode": ai_mode,
            "ai_sample_pct": ai_sample_pct,
            "threshold": threshold,
            "consistency": consistency,
            "content_type": content_type or "general",
        },
        state="queued",
        progress=0.0,
        summary={"attempt": 0},
        ai_units=Decimal("0"),
        created_by=actor_of(p),
    )
    db.add(a)
    db.flush()
    enqueue(db, "audit.parse", {"audit_id": a.id}, idempotency_key=f"{a.id}:0:parse")
    return audit_view(a)


@router.get("/audits")
def list_audits(p: Customer, db: DB, pg: Paging) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(Audit)
            .where(Audit.org_id == p.org_id)
            .order_by(Audit.created_at.desc(), Audit.id.desc())
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    page = listing(rows, pg)
    page["items"] = [audit_view(a) for a in page["items"]]
    return page


@router.get("/audits/{audit_id}")
def get_audit(audit_id: str, p: Customer, db: DB) -> dict[str, Any]:
    return audit_view(_get(db, p.org_id, audit_id))


@router.get("/audits/{audit_id}/segments")
def audit_segments(
    audit_id: str,
    p: Customer,
    db: DB,
    pg: Paging,
    severity: Annotated[str | None, Query(max_length=60)] = None,
    min_severity: Literal["neutral", "minor", "major", "critical"] | None = None,
    dimension: Annotated[str | None, Query(max_length=60)] = None,
    code: Annotated[str | None, Query(max_length=60)] = None,
    with_issues: bool = False,
) -> dict[str, Any]:
    """Audited segments, paged. Filters: severity (comma list of max severities), min_severity,
    dimension, code (an issue code), with_issues."""
    a = _get(db, p.org_id, audit_id)
    q = select(AuditSegment).where(AuditSegment.audit_id == a.id)
    sev_list = [s for s in (severity or "").split(",") if s]
    if any(s not in SEVERITIES for s in sev_list):
        raise Invalid(f"severity must be among {', '.join(SEVERITIES)}")
    if sev_list:
        q = q.where(AuditSegment.max_severity.in_(sev_list))
    if min_severity:
        q = q.where(AuditSegment.max_severity.in_(SEVERITIES[SEVERITIES.index(min_severity) :]))
    if with_issues:
        q = q.where(AuditSegment.max_severity != "none")
    rows = list(db.execute(q.order_by(AuditSegment.seq)).scalars())
    if dimension:
        rows = [s for s in rows if dimension in (s.dimensions or [])]
    if code:
        rows = [s for s in rows if any(i.get("code") == code for i in s.issues or [])]
    total = len(rows)
    page = listing(rows[pg.offset : pg.offset + pg.limit + 1], pg)
    page["items"] = [segment_view(s) for s in page["items"]]
    page["total"] = total
    return page


def _segments(db: Any, audit: Audit) -> list[AuditSegment]:
    return list(
        db.execute(
            select(AuditSegment).where(AuditSegment.audit_id == audit.id).order_by(AuditSegment.seq)
        ).scalars()
    )


def _done(a: Audit) -> None:
    if a.state != "done":
        raise Conflict(f"the report is available once the audit is done (state {a.state})")


@router.get("/audits/{audit_id}/report.pdf")
def report_pdf(audit_id: str, p: Customer, db: DB) -> Response:
    a = _get(db, p.org_id, audit_id)
    _done(a)
    data = report.to_pdf(a, _segments(db, a))
    return Response(
        data, media_type="application/pdf", headers={"Content-Disposition": attachment(f"audit-{a.id}.pdf")}
    )


@router.get("/audits/{audit_id}/report.xlsx")
def report_xlsx(audit_id: str, p: Customer, db: DB) -> Response:
    a = _get(db, p.org_id, audit_id)
    _done(a)
    data = report.to_xlsx(a, _segments(db, a))
    return Response(data, media_type=XLSX, headers={"Content-Disposition": attachment(f"audit-{a.id}.xlsx")})


@router.get("/audits/{audit_id}/annotated.xlf")
def annotated(audit_id: str, p: Customer, db: DB) -> Response:
    """The XLIFF with every finding as a note on its unit (a fresh XLIFF 2.1 for other inputs)."""
    a = _get(db, p.org_id, audit_id)
    _done(a)
    try:
        original = storage.get(a.storage_key) if a.input_format == "xliff" else None
    except FileNotFoundError:
        original = None
    data = report.annotated_xliff(a, original, _segments(db, a))
    base = a.filename.rsplit(".", 1)[0] if a.input_format == "xliff" else a.filename
    return Response(
        data,
        media_type="application/xliff+xml",
        headers={"Content-Disposition": attachment(f"{base}.audited.xlf")},
    )


@router.post("/audits/{audit_id}/retry")
def retry(audit_id: str, p: PM, db: DB) -> dict[str, Any]:
    a = _get(db, p.org_id, audit_id, lock=True)
    if a.state != "failed":
        raise Conflict(f"only a failed audit can be retried (state {a.state})")
    service.retry(db, a)
    db.flush()
    return audit_view(a)


@router.get("/audits/{audit_id}/stats")
def stats(audit_id: str, p: Customer, db: DB) -> dict[str, Any]:
    """Counts per max severity, for the report filters."""
    a = _get(db, p.org_id, audit_id)
    rows = db.execute(
        select(AuditSegment.max_severity, func.count())
        .where(AuditSegment.audit_id == a.id)
        .group_by(AuditSegment.max_severity)
    ).all()
    return {"by_max_severity": {s: int(n) for s, n in rows}}
