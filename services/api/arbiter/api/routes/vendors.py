"""Vendor management (module pm): vendors, assignments of human steps, purchase orders,
vendor invoices, payables, capacity planning and deadline risk.

Every route needs the pm module (404 `module_disabled` otherwise) and the pm role or an API
key; writes also need the permission `vendors.manage`. Every lookup is scoped by org: an
object of another org is a 404, never a 403.
"""

from __future__ import annotations

import posixpath
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Header, Query, Response, UploadFile
from sqlalchemy import func, select

from arbiter import storage
from arbiter.agency import assignments, capacity, procurement
from arbiter.agency import vendors as vnd
from arbiter.agency.vendor_schemas import (
    AbsenceIn,
    AssignmentIn,
    AutoInvoiceIn,
    DocumentIn,
    HumanStep,
    InvoiceStatusIn,
    VendorIn,
    VendorPatch,
)
from arbiter.api.deps import DB, PM, Paging, Principal, listing, require_module, require_permission
from arbiter.api.routes.jobs import attachment
from arbiter.api.routes.projects import idempotent_post
from arbiter.errors import Invalid, NotFound
from arbiter.models import (
    Job,
    PurchaseOrder,
    Vendor,
    VendorAbsence,
    VendorAssignment,
    VendorDocument,
    VendorInvoice,
    utcnow,
)

router = APIRouter(tags=["vendors"], dependencies=[require_module("pm")])
MANAGE = [require_permission("vendors.manage")]
IdemKey = Annotated[str | None, Header()]
Period = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")]


def _uid(p: Principal) -> str | None:
    return p.user.id if p.user is not None else None


def _filename(upload: UploadFile) -> str:
    name = posixpath.basename((upload.filename or "").replace("\\", "/")).strip()
    if not name:
        raise Invalid("the upload has no file name")
    return name


# --------------------------------------------------------------------------- vendors


@router.get("/vendors")
def list_vendors(
    p: PM,
    db: DB,
    pg: Paging,
    q: str | None = None,
    status: Literal["active", "inactive", "blocked"] | None = None,
    source_lang: str | None = None,
    target_lang: str | None = None,
    service: str | None = None,
) -> dict[str, Any]:
    stmt = select(Vendor).where(Vendor.org_id == p.org_id)
    if status:
        stmt = stmt.where(Vendor.status == status)
    if q and q.strip():
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Vendor.name.ilike(f"%{needle}%", escape="\\"))
    rows = list(db.execute(stmt.order_by(func.lower(Vendor.name), Vendor.id)).scalars())
    if source_lang or target_lang or service:
        rows = [v for v in rows if vnd.serves(v, source_lang or "", target_lang or "", service)]
    rows = rows[pg.offset : pg.offset + pg.limit + 1]
    load = dict(
        db.execute(
            select(VendorAssignment.vendor_id, func.count())
            .where(
                VendorAssignment.org_id == p.org_id,
                VendorAssignment.status.in_(("offered", "accepted", "in_progress")),
            )
            .group_by(VendorAssignment.vendor_id)
        ).all()
    )
    return listing([vnd.vendor_view(v, {"open_assignments": int(load.get(v.id, 0))}) for v in rows], pg)


@router.post("/vendors", status_code=201, dependencies=MANAGE)
def create_vendor(body: VendorIn, p: PM, db: DB, idempotency_key: IdemKey = None) -> Any:
    def make() -> dict[str, Any]:
        return vnd.vendor_view(vnd.create_vendor(db, p.org_id, body))

    return idempotent_post(db, p, "vendors", idempotency_key, body.model_dump(mode="json"), make)


@router.post("/vendors/import", dependencies=MANAGE)
def import_vendors(p: PM, db: DB, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    data = file.file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise Invalid("the CSV file is larger than 5 MB")
    return vnd.import_csv(db, p.org_id, data)


@router.get("/vendors/{vendor_id}")
def get_vendor(vendor_id: str, p: PM, db: DB) -> dict[str, Any]:
    v = vnd.get_vendor(db, p.org_id, vendor_id)
    absences = db.execute(
        select(VendorAbsence).where(VendorAbsence.vendor_id == v.id).order_by(VendorAbsence.start_date)
    ).scalars()
    docs = db.execute(
        select(VendorDocument).where(VendorDocument.vendor_id == v.id).order_by(VendorDocument.created_at)
    ).scalars()
    asgs = db.execute(
        select(VendorAssignment)
        .where(VendorAssignment.vendor_id == v.id)
        .order_by(VendorAssignment.created_at.desc())
        .limit(50)
    ).scalars()
    return vnd.vendor_view(
        v,
        {
            "absences": [vnd.absence_view(a) for a in absences],
            "documents": [vnd.document_view(d) for d in docs],
            "assignments": [assignments.assignment_view(db, a) for a in asgs],
        },
    )


@router.patch("/vendors/{vendor_id}", dependencies=MANAGE)
def patch_vendor(vendor_id: str, body: VendorPatch, p: PM, db: DB) -> dict[str, Any]:
    return vnd.vendor_view(vnd.update_vendor(db, vnd.get_vendor(db, p.org_id, vendor_id, lock=True), body))


@router.delete("/vendors/{vendor_id}", dependencies=MANAGE)
def deactivate_vendor(vendor_id: str, p: PM, db: DB) -> dict[str, Any]:
    """Vendors are never deleted (POs and invoices point at them): DELETE sets inactive."""
    v = vnd.get_vendor(db, p.org_id, vendor_id, lock=True)
    v.status = "inactive"
    v.updated_at = utcnow()
    db.flush()
    return vnd.vendor_view(v)


@router.post("/vendors/{vendor_id}/absences", status_code=201, dependencies=MANAGE)
def add_absence(vendor_id: str, body: AbsenceIn, p: PM, db: DB) -> dict[str, Any]:
    return vnd.absence_view(vnd.add_absence(db, vnd.get_vendor(db, p.org_id, vendor_id), body))


@router.delete("/vendors/{vendor_id}/absences/{absence_id}", status_code=204, dependencies=MANAGE)
def delete_absence(vendor_id: str, absence_id: str, p: PM, db: DB) -> Response:
    v = vnd.get_vendor(db, p.org_id, vendor_id)
    a = db.get(VendorAbsence, absence_id)
    if a is None or a.vendor_id != v.id:
        raise NotFound("absence not found")
    db.delete(a)
    return Response(status_code=204)


@router.post("/vendors/{vendor_id}/documents", status_code=201, dependencies=MANAGE)
def add_document(vendor_id: str, body: DocumentIn, p: PM, db: DB) -> dict[str, Any]:
    return vnd.document_view(vnd.add_document(db, vnd.get_vendor(db, p.org_id, vendor_id), body))


@router.delete("/vendors/{vendor_id}/documents/{document_id}", status_code=204, dependencies=MANAGE)
def delete_document(vendor_id: str, document_id: str, p: PM, db: DB) -> Response:
    v = vnd.get_vendor(db, p.org_id, vendor_id)
    d = db.get(VendorDocument, document_id)
    if d is None or d.vendor_id != v.id:
        raise NotFound("document not found")
    db.delete(d)
    return Response(status_code=204)


@router.get("/vendors/{vendor_id}/calendar")
def vendor_calendar(
    vendor_id: str, p: PM, db: DB, start: date | None = None, days: Annotated[int, Query(ge=1, le=62)] = 28
) -> dict[str, Any]:
    v = vnd.get_vendor(db, p.org_id, vendor_id)
    tl = capacity.timeline(db, p.org_id, start or utcnow().date(), days)
    row = next((r for r in tl["vendors"] if r["vendor_id"] == v.id), None)
    return {
        "vendor_id": v.id,
        "start": tl["start"],
        "days": row["days"] if row else [],
        "assignments": [a for a in tl["assignments"] if a["vendor_id"] == v.id],
    }


# --------------------------------------------------------------------------- assignments


def _job(db: DB, p: Principal, job_id: str) -> Job:
    job = db.execute(select(Job).where(Job.id == job_id, Job.org_id == p.org_id)).scalar_one_or_none()
    if job is None:
        raise NotFound("job not found")
    return job


@router.get("/jobs/{job_id}/assignments")
def job_assignments(job_id: str, p: PM, db: DB) -> dict[str, Any]:
    job = _job(db, p, job_id)
    rows = db.execute(
        select(VendorAssignment)
        .where(VendorAssignment.job_id == job.id)
        .order_by(VendorAssignment.created_at, VendorAssignment.rank)
    ).scalars()
    routes = {}
    for step in ("human_review", "second_review"):
        if not assignments.step_available(job, step):
            continue
        asg = assignments.route_for(db, job, step)
        routes[step] = {
            "mode": "marketplace" if asg is None else asg.assignee_kind,
            "assignment_id": asg.id if asg else None,
            "status": asg.status if asg else None,
        }
    return {
        "job_id": job.id,
        "routes": routes,
        "items": [assignments.assignment_view(db, a, with_link=True) for a in rows],
    }


@router.get("/jobs/{job_id}/assignment-suggestions")
def assignment_suggestions(job_id: str, p: PM, db: DB, step: HumanStep = "human_review") -> dict[str, Any]:
    job = _job(db, p, job_id)
    if not assignments.step_available(job, step):
        raise Invalid(f"this job has no {step} step (tier {job.tier})")
    return capacity.suggestions_for_job(db, job, step)


@router.post("/jobs/{job_id}/assignments", status_code=201, dependencies=MANAGE)
def create_assignment(job_id: str, body: AssignmentIn, p: PM, db: DB, idempotency_key: IdemKey = None) -> Any:
    org = p.org
    assert org is not None

    def make() -> dict[str, Any]:
        rows = assignments.create(db, org, job_id, body, _uid(p))
        return {
            "job_id": job_id,
            "step": body.step,
            "mode": body.mode,
            "items": [assignments.assignment_view(db, a, with_link=True) for a in rows],
        }

    payload = {"job_id": job_id, **body.model_dump(mode="json")}
    return idempotent_post(db, p, "assignments", idempotency_key, payload, make)


@router.get("/assignments")
def list_assignments(
    p: PM,
    db: DB,
    pg: Paging,
    status: str | None = None,
    vendor_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    stmt = select(VendorAssignment).where(VendorAssignment.org_id == p.org_id)
    if status:
        stmt = stmt.where(VendorAssignment.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    if vendor_id:
        stmt = stmt.where(VendorAssignment.vendor_id == vendor_id)
    if job_id:
        stmt = stmt.where(VendorAssignment.job_id == job_id)
    rows = list(
        db.execute(
            stmt.order_by(VendorAssignment.created_at.desc(), VendorAssignment.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([assignments.assignment_view(db, a) for a in rows], pg)


@router.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: str, p: PM, db: DB) -> dict[str, Any]:
    return assignments.assignment_view(
        db, assignments.get_assignment(db, p.org_id, assignment_id), with_link=True
    )


@router.post("/assignments/{assignment_id}/approve", dependencies=MANAGE)
def approve_assignment(assignment_id: str, p: PM, db: DB) -> dict[str, Any]:
    a = assignments.get_assignment(db, p.org_id, assignment_id, lock=True)
    return assignments.assignment_view(db, assignments.approve(db, a, _uid(p)))


class _Note(InvoiceStatusIn):
    pass


@router.post("/assignments/{assignment_id}/reopen", dependencies=MANAGE)
def reopen_assignment(assignment_id: str, p: PM, db: DB, body: _Note | None = None) -> dict[str, Any]:
    a = assignments.get_assignment(db, p.org_id, assignment_id, lock=True)
    return assignments.assignment_view(
        db, assignments.reopen(db, a, body.note if body else ""), with_link=True
    )


@router.post("/assignments/{assignment_id}/cancel", dependencies=MANAGE)
def cancel_assignment(assignment_id: str, p: PM, db: DB) -> dict[str, Any]:
    a = assignments.get_assignment(db, p.org_id, assignment_id, lock=True)
    return assignments.assignment_view(db, assignments.cancel(db, a))


# --------------------------------------------------------------------------- purchase orders


@router.get("/purchase-orders")
def list_pos(
    p: PM,
    db: DB,
    pg: Paging,
    vendor_id: str | None = None,
    status: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    stmt = select(PurchaseOrder).where(PurchaseOrder.org_id == p.org_id)
    if vendor_id:
        stmt = stmt.where(PurchaseOrder.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if job_id:
        stmt = stmt.where(PurchaseOrder.job_id == job_id)
    rows = list(
        db.execute(
            stmt.order_by(PurchaseOrder.issued_at.desc(), PurchaseOrder.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([procurement.po_view(db, po) for po in rows], pg)


@router.get("/purchase-orders/{po_id}")
def get_po(po_id: str, p: PM, db: DB) -> dict[str, Any]:
    return procurement.po_view(db, procurement.get_po(db, p.org_id, po_id))


@router.get("/purchase-orders/{po_id}/pdf")
def po_pdf(po_id: str, p: PM, db: DB) -> Response:
    po = procurement.get_po(db, p.org_id, po_id)
    return Response(
        procurement.po_pdf(db, po),
        media_type="application/pdf",
        headers={"Content-Disposition": attachment(f"{po.number}.pdf")},
    )


# --------------------------------------------------------------------------- vendor invoices


@router.get("/vendor-invoices")
def list_invoices(
    p: PM, db: DB, pg: Paging, vendor_id: str | None = None, status: str | None = None, period: Period = None
) -> dict[str, Any]:
    stmt = select(VendorInvoice).where(VendorInvoice.org_id == p.org_id)
    if vendor_id:
        stmt = stmt.where(VendorInvoice.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(VendorInvoice.status == status)
    if period:
        stmt = stmt.where(VendorInvoice.period == period)
    rows = list(
        db.execute(
            stmt.order_by(VendorInvoice.received_at.desc(), VendorInvoice.id)
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([procurement.invoice_view(db, i) for i in rows], pg)


@router.get("/vendor-invoices/export.csv")
def export_invoices(p: PM, db: DB, period: Period = None) -> Response:
    name = f"vendor-invoices-{period or 'all'}.csv"
    return Response(
        procurement.export_csv(db, p.org_id, period),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": attachment(name)},
    )


def _decimal(value: str | None, what: str) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value.strip().replace(",", "."))
    except InvalidOperation:
        raise Invalid(f"{what} must be a decimal number") from None


@router.post("/vendor-invoices", status_code=201, dependencies=MANAGE)
def upload_invoice(
    p: PM,
    db: DB,
    file: Annotated[UploadFile, File()],
    vendor_id: Annotated[str, Form(min_length=1, max_length=40)],
    number: Annotated[str, Form(min_length=1, max_length=60)],
    assignment_ids: Annotated[str, Form(min_length=1, max_length=4000)],
    total: Annotated[str | None, Form()] = None,
    note: Annotated[str, Form(max_length=2000)] = "",
) -> dict[str, Any]:
    data = file.file.read(procurement.UPLOAD_MAX_BYTES + 1)
    inv = procurement.upload_invoice(
        db,
        p.org_id,
        vendor_id,
        number=number,
        assignment_ids=[x.strip() for x in assignment_ids.split(",") if x.strip()],
        filename=_filename(file),
        data=data,
        total=_decimal(total, "total"),
        note=note,
    )
    return procurement.invoice_view(db, inv)


@router.post("/vendor-invoices/auto", dependencies=MANAGE)
def auto_invoices(p: PM, db: DB, body: AutoInvoiceIn | None = None) -> dict[str, Any]:
    body = body or AutoInvoiceIn()
    rows = procurement.auto_invoice(db, p.org_id, vendor_id=body.vendor_id, period=body.period)
    return {"items": [procurement.invoice_view(db, i) for i in rows]}


@router.get("/vendor-invoices/{invoice_id}")
def get_invoice(invoice_id: str, p: PM, db: DB) -> dict[str, Any]:
    return procurement.invoice_view(db, procurement.get_invoice(db, p.org_id, invoice_id))


@router.get("/vendor-invoices/{invoice_id}/file")
def invoice_file(invoice_id: str, p: PM, db: DB) -> Response:
    inv = procurement.get_invoice(db, p.org_id, invoice_id)
    if not inv.storage_key:
        raise NotFound("this invoice has no uploaded file")
    import mimetypes

    media = mimetypes.guess_type(inv.filename or "")[0] or "application/octet-stream"
    return Response(
        storage.get(inv.storage_key),
        media_type=media,
        headers={"Content-Disposition": attachment(inv.filename or f"{inv.number}.bin")},
    )


def _status(
    invoice_id: str, p: Principal, db: Any, status: str, body: InvoiceStatusIn | None
) -> dict[str, Any]:
    inv = procurement.get_invoice(db, p.org_id, invoice_id, lock=True)
    return procurement.invoice_view(
        db, procurement.set_invoice_status(db, inv, status, body.note if body else "")
    )


@router.post("/vendor-invoices/{invoice_id}/approve", dependencies=MANAGE)
def approve_invoice(invoice_id: str, p: PM, db: DB, body: InvoiceStatusIn | None = None) -> dict[str, Any]:
    return _status(invoice_id, p, db, "approved", body)


@router.post("/vendor-invoices/{invoice_id}/reject", dependencies=MANAGE)
def reject_invoice(invoice_id: str, p: PM, db: DB, body: InvoiceStatusIn | None = None) -> dict[str, Any]:
    return _status(invoice_id, p, db, "rejected", body)


@router.post("/vendor-invoices/{invoice_id}/pay", dependencies=MANAGE)
def pay_invoice(invoice_id: str, p: PM, db: DB, body: InvoiceStatusIn | None = None) -> dict[str, Any]:
    return _status(invoice_id, p, db, "paid", body)


@router.get("/payables")
def payables(p: PM, db: DB, period: Period = None) -> dict[str, Any]:
    return procurement.payables(db, p.org_id, period or utcnow().strftime("%Y-%m"))


# --------------------------------------------------------------------------- capacity & risk


@router.get("/capacity")
def capacity_planner(
    p: PM,
    db: DB,
    source_lang: Annotated[str, Query(min_length=2, max_length=16)],
    target_lang: Annotated[str, Query(min_length=2, max_length=16)],
    words: Annotated[int, Query(ge=1, le=10_000_000)],
    by: date | None = None,
    service: Literal["translation", "review", "post-edit", "dtp"] | None = None,
) -> dict[str, Any]:
    rows = capacity.planner(
        db, p.org_id, source_lang=source_lang, target_lang=target_lang, words=words, by=by, service=service
    )
    return {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "words": words,
        "by": by.isoformat() if by else None,
        "items": rows,
    }


@router.get("/pm/deadline-risk")
def deadline_risk(p: PM, db: DB, only_at_risk: bool = False) -> dict[str, Any]:
    return {"items": capacity.deadline_risk(db, p.org_id, only_at_risk=only_at_risk)}


@router.get("/pm/timeline")
def pm_timeline(
    p: PM, db: DB, start: date | None = None, days: Annotated[int, Query(ge=1, le=62)] = 14
) -> dict[str, Any]:
    return capacity.timeline(db, p.org_id, start or utcnow().date(), days)
