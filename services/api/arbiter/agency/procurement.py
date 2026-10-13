"""Purchase orders and vendor invoices (module pm): the agency's accounts payable to its own vendors.

  * A purchase order is issued when a vendor accepts an assignment (one PO per assignment),
    numbered per org and year from the number series: PO-2026-0001. The PDF is rendered on
    request (reportlab, like the evidence pack). status: issued -> invoiced | cancelled.
  * A vendor invoice covers one or more approved assignments of one vendor in one currency:
      upload  the vendor uploads its own invoice from the workbench (self-invoice) or the PM
              uploads it; number = the vendor's own invoice number
      auto    POST /vendor-invoices/auto builds one invoice per vendor and currency from every
              approved, not yet invoiced assignment (number VI-2026-0001 from the org series)
    status: received -> approved -> paid, or rejected (the assignments become approved again,
    so they can be invoiced anew). Covered assignments move to `invoiced` and their POs too.
  * Payables report per month (by vendor and currency): accrued (approved, not invoiced),
    invoiced and open (received or approved), paid in the month. CSV export for accounting.
This is the agency's own money: none of it touches the platform ledger (arbiter.billing.ledger),
which is the reviewer marketplace's.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.agency import vendors as vnd
from arbiter.agency.common import iso, money
from arbiter.domain.states import transition_status
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import (
    Job,
    Organization,
    PurchaseOrder,
    Vendor,
    VendorAssignment,
    VendorInvoice,
    utcnow,
)

CENT = Decimal("0.01")
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_TYPES = (".pdf", ".png", ".jpg", ".jpeg", ".xml", ".txt", ".docx", ".xlsx")


def _period(dt: Any) -> str:
    return dt.strftime("%Y-%m")


# --------------------------------------------------------------------------- purchase orders


def issue_po(session: Session, a: VendorAssignment) -> PurchaseOrder:
    """One PO per accepted vendor assignment (idempotent)."""
    existing = session.execute(
        select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    assert a.vendor_id is not None
    job = session.get(Job, a.job_id)
    assert job is not None
    step = a.step.replace("_", " ")
    lines = [
        {
            "description": f"{a.service.capitalize()} ({step}), job {job.id}, {job.source_lang} > {job.target_lang}",
            "quantity": str(a.quantity),
            "unit": a.unit,
            "rate": str(Decimal(a.rate).normalize()),
            "amount": money(a.amount),
        }
    ]
    po = PurchaseOrder(
        org_id=a.org_id,
        number=vnd.next_number(session, a.org_id, "po", "PO"),
        vendor_id=a.vendor_id,
        assignment_id=a.id,
        job_id=a.job_id,
        lines=lines,
        total=Decimal(a.amount).quantize(CENT),
        currency=a.currency,
        status="issued",
        due_at=a.due_at,
    )
    session.add(po)
    session.flush()
    return po


def cancel_po_for(session: Session, a: VendorAssignment) -> None:
    po = session.execute(
        select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)
    ).scalar_one_or_none()
    if po is not None and po.status == "issued":
        transition_status(po, "purchase_order", "cancelled")


def get_po(session: Session, org_id: str, po_id: str) -> PurchaseOrder:
    po = session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.org_id == org_id)
    ).scalar_one_or_none()
    if po is None:
        raise NotFound("purchase order not found")
    return po


def po_view(session: Session, po: PurchaseOrder) -> dict[str, Any]:
    v = session.get(Vendor, po.vendor_id)
    return {
        "id": po.id,
        "number": po.number,
        "vendor_id": po.vendor_id,
        "vendor_name": v.name if v else None,
        "assignment_id": po.assignment_id,
        "job_id": po.job_id,
        "lines": [dict(x) for x in po.lines or []],
        "total": money(po.total),
        "currency": po.currency,
        "status": po.status,
        "due_at": iso(po.due_at),
        "issued_at": iso(po.issued_at),
        "vendor_invoice_id": po.vendor_invoice_id,
    }


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def po_pdf(session: Session, po: PurchaseOrder) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    org = session.get(Organization, po.org_id)
    v = session.get(Vendor, po.vendor_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"Purchase order {po.number}")
    st = getSampleStyleSheet()
    vendor_lines = [
        v.legal_name or v.name if v else "",
        (v.address or "") if v else "",
        f"Tax ID: {v.tax_id}" if v and v.tax_id else "",
        f"IBAN: {v.iban}" if v and v.iban else "",
        v.email or "" if v else "",
    ]
    story: list[Any] = [
        Paragraph(f"Purchase order {_esc(po.number)}", st["Title"]),
        Paragraph(f"Issued by: {_esc(org.name if org else '')}", st["BodyText"]),
        Paragraph(f"Issued on: {po.issued_at:%Y-%m-%d}", st["BodyText"]),
        Paragraph(f"Due: {po.due_at:%Y-%m-%d %H:%M} UTC" if po.due_at else "Due: as agreed", st["BodyText"]),
        Spacer(1, 8),
        Paragraph("Vendor", st["Heading3"]),
        *[Paragraph(_esc(x), st["BodyText"]) for x in vendor_lines if x],
        Spacer(1, 8),
    ]
    rows: list[list[Any]] = [["Description", "Quantity", "Unit", "Rate", "Amount"]]
    for line in po.lines or []:
        rows.append(
            [
                Paragraph(_esc(str(line.get("description", ""))), st["BodyText"]),
                line.get("quantity", ""),
                line.get("unit", ""),
                line.get("rate", ""),
                f"{line.get('amount', '')} {po.currency}",
            ]
        )
    rows.append(["", "", "", "Total", f"{money(po.total)} {po.currency}"])
    table = Table(rows, colWidths=[220, 60, 50, 60, 90])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -2), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (3, -1), (-1, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [
        table,
        Spacer(1, 12),
        Paragraph(
            f"Please quote {_esc(po.number)} on your invoice. Payment terms: "
            f"{v.payment_terms_days if v else 30} days from an approved invoice.",
            st["BodyText"],
        ),
    ]
    doc.build(story)
    return buf.getvalue()


# --------------------------------------------------------------------------- vendor invoices


def get_invoice(session: Session, org_id: str, inv_id: str, *, lock: bool = False) -> VendorInvoice:
    q = select(VendorInvoice).where(VendorInvoice.id == inv_id, VendorInvoice.org_id == org_id)
    if lock:
        q = q.with_for_update()
    inv = session.execute(q).scalar_one_or_none()
    if inv is None:
        raise NotFound("vendor invoice not found")
    return inv


def _lines_for(session: Session, assignments: list[VendorAssignment]) -> list[dict[str, Any]]:
    out = []
    for a in assignments:
        po = session.execute(
            select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)
        ).scalar_one_or_none()
        out.append(
            {
                "assignment_id": a.id,
                "job_id": a.job_id,
                "po_number": po.number if po else None,
                "description": f"{a.service} ({a.step.replace('_', ' ')}) job {a.job_id}",
                "quantity": str(a.quantity),
                "unit": a.unit,
                "rate": str(Decimal(a.rate).normalize()),
                "amount": money(a.amount),
            }
        )
    return out


def _mark_invoiced(session: Session, inv: VendorInvoice, assignments: list[VendorAssignment]) -> None:
    for a in assignments:
        transition_status(a, "assignment", "invoiced")
        po = session.execute(
            select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)
        ).scalar_one_or_none()
        if po is not None and po.status == "issued":
            transition_status(po, "purchase_order", "invoiced")
            po.vendor_invoice_id = inv.id


def _approved_for(
    session: Session, org_id: str, vendor_id: str, ids: list[str] | None = None
) -> list[VendorAssignment]:
    q = select(VendorAssignment).where(
        VendorAssignment.org_id == org_id,
        VendorAssignment.vendor_id == vendor_id,
        VendorAssignment.status == "approved",
    )
    if ids is not None:
        q = q.where(VendorAssignment.id.in_(ids))
    return list(session.execute(q.order_by(VendorAssignment.approved_at).with_for_update()).scalars())


def _check_file(filename: str, data: bytes) -> None:
    if not data:
        raise Invalid("the invoice file is empty")
    if len(data) > UPLOAD_MAX_BYTES:
        raise Invalid("the invoice file is larger than 10 MB")
    if not filename.lower().endswith(UPLOAD_TYPES):
        raise Invalid(f"the invoice file must be one of {', '.join(UPLOAD_TYPES)}")


def upload_invoice(
    session: Session,
    org_id: str,
    vendor_id: str,
    *,
    number: str,
    assignment_ids: list[str],
    filename: str,
    data: bytes,
    total: Decimal | None = None,
    note: str = "",
) -> VendorInvoice:
    """A vendor's own invoice (from the workbench or uploaded by the PM) for approved assignments."""
    from arbiter import storage

    number = number.strip()
    if not number or len(number) > 60:
        raise Invalid("the invoice number is required (at most 60 characters)")
    _check_file(filename, data)
    vendor = vnd.get_vendor(session, org_id, vendor_id)
    assignments = _approved_for(session, org_id, vendor.id, assignment_ids)
    if not assignment_ids or len(assignments) != len(set(assignment_ids)):
        raise Conflict("an invoice can only cover this vendor's approved, not yet invoiced assignments")
    currencies = {a.currency for a in assignments}
    if len(currencies) != 1:
        raise Invalid("one invoice covers one currency")
    expected = sum((Decimal(a.amount) for a in assignments), Decimal("0")).quantize(CENT)
    if total is not None and total.quantize(CENT) != expected:
        raise Invalid(
            "the invoice total does not match the approved purchase orders",
            {"expected": money(expected), "given": money(total)},
        )
    dup = session.execute(
        select(VendorInvoice).where(
            VendorInvoice.org_id == org_id,
            VendorInvoice.vendor_id == vendor.id,
            VendorInvoice.number == number,
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise Conflict("this vendor already has an invoice with that number")
    now = utcnow()
    inv = VendorInvoice(
        org_id=org_id,
        vendor_id=vendor.id,
        number=number,
        source="upload",
        period=_period(now),
        assignment_ids=[a.id for a in assignments],
        lines=_lines_for(session, assignments),
        total=expected,
        currency=currencies.pop(),
        status="received",
        filename=filename[:400],
        note=note[:2000],
        due_date=(now + timedelta(days=vendor.payment_terms_days)).date(),
    )
    session.add(inv)
    session.flush()
    inv.storage_key = storage.make_key(org_id, "vendor-invoices", inv.id, filename)
    storage.put(inv.storage_key, data)
    _mark_invoiced(session, inv, assignments)
    session.flush()
    return inv


def auto_invoice(
    session: Session, org_id: str, *, vendor_id: str | None = None, period: str | None = None
) -> list[VendorInvoice]:
    """One invoice per vendor and currency from approved, not yet invoiced assignments
    (approved in `period` when given)."""
    q = select(VendorAssignment).where(
        VendorAssignment.org_id == org_id,
        VendorAssignment.status == "approved",
        VendorAssignment.vendor_id.is_not(None),
    )
    if vendor_id:
        vnd.get_vendor(session, org_id, vendor_id)
        q = q.where(VendorAssignment.vendor_id == vendor_id)
    rows = [
        a
        for a in session.execute(q.order_by(VendorAssignment.approved_at).with_for_update()).scalars()
        if period is None or (a.approved_at and _period(a.approved_at) == period)
    ]
    groups: dict[tuple[str, str], list[VendorAssignment]] = defaultdict(list)
    for a in rows:
        assert a.vendor_id is not None
        groups[(a.vendor_id, a.currency)].append(a)
    now = utcnow()
    out: list[VendorInvoice] = []
    for (vid, cur), items in sorted(groups.items()):
        vendor = session.get(Vendor, vid)
        assert vendor is not None
        inv = VendorInvoice(
            org_id=org_id,
            vendor_id=vid,
            number=vnd.next_number(session, org_id, "vinv", "VI"),
            source="auto",
            period=period or _period(now),
            assignment_ids=[a.id for a in items],
            lines=_lines_for(session, items),
            total=sum((Decimal(a.amount) for a in items), Decimal("0")).quantize(CENT),
            currency=cur,
            status="received",
            note="Generated from approved assignments.",
            due_date=(now + timedelta(days=vendor.payment_terms_days)).date(),
        )
        session.add(inv)
        session.flush()
        _mark_invoiced(session, inv, items)
        out.append(inv)
    session.flush()
    return out


def set_invoice_status(session: Session, inv: VendorInvoice, status: str, note: str = "") -> VendorInvoice:
    if inv.status == status:
        return inv
    transition_status(inv, "vendor_invoice", status)
    now = utcnow()
    if status == "approved":
        inv.approved_at = now
    elif status == "paid":
        inv.paid_at = now
    elif status == "rejected":
        # The work stays approved: the assignments can be invoiced again (corrected invoice).
        for a in session.execute(
            select(VendorAssignment).where(VendorAssignment.id.in_(list(inv.assignment_ids or [])))
        ).scalars():
            if a.status == "invoiced":
                transition_status(a, "assignment", "approved")
            po = session.execute(
                select(PurchaseOrder).where(PurchaseOrder.assignment_id == a.id)
            ).scalar_one_or_none()
            if po is not None and po.status == "invoiced":
                transition_status(po, "purchase_order", "issued")
                po.vendor_invoice_id = None
    if note:
        inv.note = (inv.note + "\n" + note).strip()[:2000]
    session.flush()
    return inv


def invoice_view(session: Session, inv: VendorInvoice) -> dict[str, Any]:
    v = session.get(Vendor, inv.vendor_id)
    return {
        "id": inv.id,
        "vendor_id": inv.vendor_id,
        "vendor_name": v.name if v else None,
        "number": inv.number,
        "source": inv.source,
        "period": inv.period,
        "assignment_ids": list(inv.assignment_ids or []),
        "lines": [dict(x) for x in inv.lines or []],
        "total": money(inv.total),
        "currency": inv.currency,
        "status": inv.status,
        "filename": inv.filename,
        "has_file": bool(inv.storage_key),
        "note": inv.note,
        "due_date": iso(inv.due_date),
        "received_at": iso(inv.received_at),
        "approved_at": iso(inv.approved_at),
        "paid_at": iso(inv.paid_at),
    }


# --------------------------------------------------------------------------- payables & export


def payables(session: Session, org_id: str, period: str) -> dict[str, Any]:
    """Per vendor and currency for one month (YYYY-MM):
    accrued = approved in the month, not invoiced yet; invoiced = invoices of the month still
    open (received or approved); paid = invoices paid in the month."""
    rows: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(
        lambda: {"accrued": Decimal("0"), "invoiced": Decimal("0"), "paid": Decimal("0")}
    )
    for a in session.execute(
        select(VendorAssignment).where(
            VendorAssignment.org_id == org_id,
            VendorAssignment.status == "approved",
            VendorAssignment.vendor_id.is_not(None),
        )
    ).scalars():
        if a.approved_at and _period(a.approved_at) == period:
            assert a.vendor_id is not None
            rows[(a.vendor_id, a.currency)]["accrued"] += Decimal(a.amount)
    for inv in session.execute(select(VendorInvoice).where(VendorInvoice.org_id == org_id)).scalars():
        if inv.status in ("received", "approved") and inv.period == period:
            rows[(inv.vendor_id, inv.currency)]["invoiced"] += Decimal(inv.total)
        if inv.status == "paid" and inv.paid_at and _period(inv.paid_at) == period:
            rows[(inv.vendor_id, inv.currency)]["paid"] += Decimal(inv.total)
    names = {v.id: v.name for v in session.execute(select(Vendor).where(Vendor.org_id == org_id)).scalars()}
    items = []
    totals: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"accrued": Decimal("0"), "invoiced": Decimal("0"), "paid": Decimal("0")}
    )
    for (vid, cur), vals in sorted(rows.items(), key=lambda kv: (names.get(kv[0][0], ""), kv[0][1])):
        items.append(
            {
                "vendor_id": vid,
                "vendor_name": names.get(vid),
                "currency": cur,
                "accrued": money(vals["accrued"]),
                "invoiced": money(vals["invoiced"]),
                "paid": money(vals["paid"]),
                "open": money(vals["accrued"] + vals["invoiced"]),
            }
        )
        for k in ("accrued", "invoiced", "paid"):
            totals[cur][k] += vals[k]
    return {
        "period": period,
        "items": items,
        "totals": [
            {
                "currency": cur,
                "accrued": money(t["accrued"]),
                "invoiced": money(t["invoiced"]),
                "paid": money(t["paid"]),
                "open": money(t["accrued"] + t["invoiced"]),
            }
            for cur, t in sorted(totals.items())
        ],
    }


CSV_COLUMNS = [
    "invoice_number",
    "source",
    "status",
    "period",
    "received_at",
    "due_date",
    "paid_at",
    "vendor_name",
    "vendor_legal_name",
    "vendor_tax_id",
    "vendor_iban",
    "po_numbers",
    "currency",
    "total",
]


def export_csv(session: Session, org_id: str, period: str | None = None) -> bytes:
    """Accounting export: one row per vendor invoice (amounts as decimal strings)."""
    q = select(VendorInvoice).where(VendorInvoice.org_id == org_id)
    if period:
        q = q.where(VendorInvoice.period == period)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for inv in session.execute(q.order_by(VendorInvoice.received_at, VendorInvoice.id)).scalars():
        v = session.get(Vendor, inv.vendor_id)
        pos = sorted({str(x.get("po_number")) for x in inv.lines or [] if x.get("po_number")})
        w.writerow(
            [
                inv.number,
                inv.source,
                inv.status,
                inv.period,
                iso(inv.received_at),
                iso(inv.due_date) or "",
                iso(inv.paid_at) or "",
                v.name if v else "",
                (v.legal_name or "") if v else "",
                (v.tax_id or "") if v else "",
                (v.iban or "") if v else "",
                " ".join(pos),
                inv.currency,
                money(inv.total),
            ]
        )
    return buf.getvalue().encode("utf-8")
