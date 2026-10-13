"""The vendor workbench (module pm): no login, the signed link in the offer e-mail is the key.

GET  /vendor-portal/{token}                       the offer or the work: job, fee, segments
POST /vendor-portal/{token}/accept                 first to accept wins; issues the PO
POST /vendor-portal/{token}/decline                {reason?}; the next vendor gets the offer
POST /vendor-portal/{token}/segments/{segment_id}  {decision accept|edit, target_tagged?, errors?}
POST /vendor-portal/{token}/complete               the step is done (nothing left)
GET  /vendor-portal/{token}/po.pdf                 the purchase order
POST /vendor-portal/{token}/invoice                multipart: number, file (approved work only)

A bad, expired or revoked token, or an org without the pm module, is a 404. The token only
opens its own assignment: one job, one step, the segments routed to it.
"""

from __future__ import annotations

import posixpath
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from arbiter.agency import assignments, procurement
from arbiter.agency.vendor_schemas import VendorSubmitIn
from arbiter.api.deps import DB
from arbiter.api.routes.jobs import attachment
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import Organization, PurchaseOrder, VendorAssignment
from arbiter.platform.modules import org_has_module

router = APIRouter(tags=["vendor-portal"])


def _open(db: DB, token: str, *, lock: bool = False) -> VendorAssignment:
    a = assignments.from_token(db, token, lock=lock)
    org = db.get(Organization, a.org_id)
    if org is None or not org_has_module(org, "pm"):
        raise NotFound("this link is not valid or has expired")
    return a


class DeclineIn(BaseModel):
    reason: str = Field(default="", max_length=2000)


@router.get("/vendor-portal/{token}")
def portal(token: str, db: DB) -> dict[str, Any]:
    return assignments.portal_view(db, _open(db, token))


@router.post("/vendor-portal/{token}/accept")
def accept(token: str, db: DB) -> dict[str, Any]:
    a = _open(db, token, lock=True)
    if a.assignee_kind != "vendor":
        raise Conflict("this assignment does not need accepting")
    assignments.accept(db, a)
    return assignments.portal_view(db, a)


@router.post("/vendor-portal/{token}/decline")
def decline(token: str, db: DB, body: DeclineIn | None = None) -> dict[str, Any]:
    a = _open(db, token, lock=True)
    assignments.decline(db, a, body.reason if body else "")
    return assignments.portal_view(db, a)


@router.post("/vendor-portal/{token}/segments/{segment_id}")
def submit(token: str, segment_id: str, body: VendorSubmitIn, db: DB) -> dict[str, Any]:
    a = _open(db, token, lock=True)
    return assignments.submit_segment(db, a, segment_id, body)


@router.post("/vendor-portal/{token}/complete")
def complete(token: str, db: DB) -> dict[str, Any]:
    a = _open(db, token, lock=True)
    assignments.complete(db, a)
    return assignments.portal_view(db, a)


@router.get("/vendor-portal/{token}/po.pdf")
def po_pdf(token: str, db: DB) -> Response:
    a = _open(db, token)
    po = db.execute(select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)).scalar_one_or_none()
    if po is None:
        raise NotFound("there is no purchase order for this assignment yet")
    return Response(
        procurement.po_pdf(db, po),
        media_type="application/pdf",
        headers={"Content-Disposition": attachment(f"{po.number}.pdf")},
    )


@router.post("/vendor-portal/{token}/invoice", status_code=201)
def invoice(
    token: str,
    db: DB,
    file: Annotated[UploadFile, File()],
    number: Annotated[str, Form(min_length=1, max_length=60)],
) -> dict[str, Any]:
    a = _open(db, token, lock=True)
    if a.vendor_id is None:
        raise Conflict("internal assignments are not invoiced")
    if a.status != "approved":
        raise Conflict("you can invoice this job once the project manager has approved the work")
    name = posixpath.basename((file.filename or "").replace("\\", "/")).strip()
    if not name:
        raise Invalid("the upload has no file name")
    inv = procurement.upload_invoice(
        db,
        a.org_id,
        a.vendor_id,
        number=number,
        assignment_ids=[a.id],
        filename=name,
        data=file.file.read(procurement.UPLOAD_MAX_BYTES + 1),
    )
    return {
        "id": inv.id,
        "number": inv.number,
        "total": str(inv.total),
        "currency": inv.currency,
        "status": inv.status,
    }
