"""Monthly invoices built from usage records.

* one invoice per org and period (YYYY-MM), idempotent: building again returns the same one
* lines grouped by unit and job: {type: "usage", unit, job_id, quantity, amount}
* number ARB-YYYYMM-<seq>, seq counts invoices of that period across all orgs, 4 digits,
  allocated under a transaction-scoped advisory lock so numbers never collide or skip
* VAT (starting rule, needs the legal and tax review before launch):
    - org.settings has a vat_id, the org country (org.settings["country"]) is known and
      differs from the seller country -> tax 0 with note "Reverse charge" (EU B2B rule)
    - otherwise tax = subtotal * VAT rate (default 0; configured via ARBITER_VAT_RATE)
  The seller country comes from ARBITER_SELLER_COUNTRY (empty = unknown -> no reverse
  charge decision, the default rate applies and the note says so).
* the tax decision is stored as a final line {type: "tax", rate, amount, note}, because the
  invoices table has no notes column; invoice_view splits it out again.

Provider-issued documents (D-074): while Paddle is the merchant of record it sells to the
customer, charges VAT / sales tax and issues the tax invoice. We must not issue a second tax
invoice for the same sale, so for paddle (and later stripe) payments the invoices table keeps
a RECORD (kind, provider, provider_ref, provider_invoice_number, totals as reported) and the
document link is fetched fresh from the provider (`document_url`). Only the manual provider
(bank transfer, enterprise terms, PO) issues our own numbered invoice and PDF
(`issue_invoice`, `invoice_pdf`), with the D-029 tax rule.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from arbiter.billing.ledger import money
from arbiter.community.errors import Invalid, NotFound
from arbiter.config import get_settings
from arbiter.models import Invoice, Organization, UsageRecord, utcnow

CENT = Decimal("0.01")
_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
REVERSE_CHARGE_NOTE = "Reverse charge: VAT to be accounted for by the recipient."
NO_TAX_CONFIG_NOTE = "VAT not configured (legal and tax review before launch)."


def seller_country() -> str:
    return get_settings().seller_country.upper()


def vat_rate() -> Decimal:
    raw = get_settings().vat_rate or "0"
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        raise ValueError("ARBITER_VAT_RATE must be a decimal like 0.20") from None


def tax_for(org: Organization, subtotal: Decimal) -> tuple[Decimal, Decimal, str]:
    """(rate, tax, note) for this org."""
    settings = org.settings or {}
    vat_id = str(settings.get("vat_id") or "").strip()
    country = str(settings.get("country") or "").strip().upper()
    seller = seller_country()
    if vat_id and country and seller and country != seller:
        return Decimal("0"), Decimal("0.00"), REVERSE_CHARGE_NOTE
    rate = vat_rate()
    tax = (subtotal * rate).quantize(CENT, rounding=ROUND_HALF_UP)
    note = "" if seller else NO_TAX_CONFIG_NOTE
    return rate, tax, note


def _next_number(session: Session, period: str) -> str:
    prefix = f"ARB-{period.replace('-', '')}-"
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"invoice-number:{prefix}"})
    count = session.execute(select(func.count()).where(Invoice.number.like(f"{prefix}%"))).scalar_one()
    return f"{prefix}{count + 1:04d}"


def build_invoice(session: Session, org_id: str, period: str) -> Invoice:
    """Build (or return the existing) invoice of an org for a period from its usage records."""
    if not _PERIOD.match(period or ""):
        raise Invalid("period must be YYYY-MM")
    org = session.get(Organization, org_id)
    if org is None:
        raise NotFound("organization not found")
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"invoice:{org_id}:{period}"})
    existing = session.execute(
        select(Invoice).where(
            Invoice.org_id == org_id,
            Invoice.period == period,
            Invoice.kind == "usage",
            Invoice.status != "void",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    records = session.execute(
        select(UsageRecord)
        .where(UsageRecord.org_id == org_id, UsageRecord.period == period)
        .order_by(UsageRecord.created_at)
    ).scalars()
    groups: dict[tuple[str, str | None], list[Decimal]] = defaultdict(lambda: [Decimal("0"), Decimal("0")])
    for r in records:
        g = groups[(r.unit, r.job_id)]
        g[0] += Decimal(r.quantity)
        g[1] += Decimal(r.amount)
    if not groups:
        raise Invalid("no usage in this period")
    lines: list[dict[str, Any]] = []
    subtotal = Decimal("0")
    for (unit, job_id), (qty, amount) in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        amt = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        subtotal += amt
        lines.append(
            {
                "type": "usage",
                "unit": unit,
                "job_id": job_id,
                "quantity": format(qty.normalize(), "f"),
                "amount": money(amt),
            }
        )
    rate, tax, note = tax_for(org, subtotal)
    lines.append({"type": "tax", "rate": str(rate), "amount": money(tax), "note": note})
    inv = Invoice(
        org_id=org_id,
        number=_next_number(session, period),
        period=period,
        lines=lines,
        subtotal=subtotal,
        tax=tax,
        total=subtotal + tax,
        currency=get_settings().currency,
        status="draft",
    )
    session.add(inv)
    session.flush()
    return inv


def invoice_view(inv: Invoice) -> dict[str, Any]:
    usage_lines = [ln for ln in inv.lines or [] if ln.get("type") != "tax"]
    tax_line = next((ln for ln in inv.lines or [] if ln.get("type") == "tax"), None)
    own = inv.provider == "internal"
    return {
        "id": inv.id,
        "number": inv.number,
        "period": inv.period,
        "lines": usage_lines,
        "subtotal": money(inv.subtotal),
        "tax": money(inv.tax),
        "tax_rate": tax_line.get("rate") if tax_line else "0",
        "tax_note": tax_line.get("note", "") if tax_line else "",
        "total": money(inv.total),
        "currency": inv.currency,
        "status": inv.status,
        "issued_at": inv.issued_at.isoformat() if inv.issued_at else None,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "kind": inv.kind,
        "provider": inv.provider,
        "provider_ref": inv.provider_ref,
        "provider_invoice_number": inv.provider_invoice_number,
        # Our PDF for our own invoices; for provider records a redirect to a fresh provider link.
        "document_url": (
            f"/billing/invoices/{inv.id}/document" if (inv.status in ("issued", "paid") or not own) else None
        ),
        "issued_by": "us" if own else inv.provider,
        "due_at": inv.due_at.isoformat() if inv.due_at else None,
        "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
    }


def list_invoices(session: Session, org_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Invoice)
        .where(Invoice.org_id == org_id)
        .order_by(Invoice.period.desc(), Invoice.created_at.desc())
    ).scalars()
    return [invoice_view(i) for i in rows]


# ------------------------------------------------------------------ own invoices (manual provider)


def payment_terms_days(org: Organization) -> int:
    raw = ((org.settings or {}).get("billing") or {}).get("payment_terms_days", 14)
    try:
        return max(0, min(int(raw), 120))
    except (TypeError, ValueError):
        return 14


def issue_invoice(
    session: Session,
    org: Organization,
    *,
    kind: str,
    lines: list[dict[str, Any]],
    currency: str,
) -> Invoice:
    """Issue OUR invoice (manual provider): numbered, taxed by D-029, due after the org terms.

    Each line: {type, description, quantity, unit_amount, amount, ...meta}; amounts Decimal or
    decimal strings. Stored with money as strings.
    """
    if not lines:
        raise Invalid("an invoice needs at least one line")
    period = utcnow().strftime("%Y-%m")
    stored: list[dict[str, Any]] = []
    subtotal = Decimal("0")
    for ln in lines:
        amount = Decimal(str(ln["amount"])).quantize(CENT, rounding=ROUND_HALF_UP)
        subtotal += amount
        out = {**ln, "amount": money(amount)}
        if "unit_amount" in ln:
            out["unit_amount"] = str(Decimal(str(ln["unit_amount"])))
        if "quantity" in ln:
            out["quantity"] = format(Decimal(str(ln["quantity"])).normalize(), "f")
        stored.append(out)
    rate, tax, note = tax_for(org, subtotal)
    po = str(((org.settings or {}).get("billing") or {}).get("po_number") or "")
    stored.append({"type": "tax", "rate": str(rate), "amount": money(tax), "note": note, "po_number": po})
    now = utcnow()
    inv = Invoice(
        org_id=org.id,
        number=_next_number(session, period),
        period=period,
        lines=stored,
        subtotal=subtotal,
        tax=tax,
        total=subtotal + tax,
        currency=currency.upper(),
        status="issued",
        issued_at=now,
        due_at=now + timedelta(days=payment_terms_days(org)),
        kind=kind,
        provider="internal",
    )
    session.add(inv)
    session.flush()
    return inv


def invoice_pdf(inv: Invoice, org: Organization) -> bytes:
    """PDF of one of OUR invoices (reportlab). Seller details come from ARBITER_SELLER_* settings."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    s = get_settings()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    y = height - 60

    def line(text_: str, size: int = 10, dy: int = 15, x: int = 50) -> None:
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(x, y, text_[:110])
        y -= dy

    line(f"Invoice {inv.number}", 16, 24)
    line(f"Issued: {inv.issued_at.date().isoformat() if inv.issued_at else '-'}")
    line(f"Due: {inv.due_at.date().isoformat() if inv.due_at else '-'}")
    line(f"Status: {inv.status}", dy=24)
    line("Seller", 11)
    for part in (s.seller_name or "(seller name not configured)", s.seller_address, s.seller_vat_id):
        if part:
            line(part)
    y -= 9
    line("Bill to", 11)
    line(org.name)
    settings = org.settings or {}
    for part in (settings.get("billing_address"), settings.get("vat_id")):
        if part:
            line(str(part))
    tax_line = next((ln for ln in inv.lines or [] if ln.get("type") == "tax"), {})
    if tax_line.get("po_number"):
        line(f"PO number: {tax_line['po_number']}")
    y -= 9
    line("Description                                              Qty        Unit         Amount", 9)
    for ln in inv.lines or []:
        if ln.get("type") == "tax":
            continue
        desc = str(ln.get("description") or ln.get("unit") or ln.get("type"))
        c.setFont("Helvetica", 9)
        c.drawString(50, y, desc[:60])
        c.drawRightString(370, y, str(ln.get("quantity", "")))
        c.drawRightString(450, y, str(ln.get("unit_amount", "")))
        c.drawRightString(540, y, f"{ln.get('amount', '')} {inv.currency}")
        y -= 13
    y -= 8
    c.setFont("Helvetica", 10)
    c.drawRightString(540, y, f"Subtotal {money(inv.subtotal)} {inv.currency}")
    y -= 14
    c.drawRightString(540, y, f"Tax ({tax_line.get('rate', '0')}) {money(inv.tax)} {inv.currency}")
    y -= 14
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(540, y, f"Total {money(inv.total)} {inv.currency}")
    y -= 24
    if tax_line.get("note"):
        line(str(tax_line["note"]), 9)
    if s.seller_iban:
        line(f"Bank transfer: IBAN {s.seller_iban}" + (f", BIC {s.seller_bic}" if s.seller_bic else ""), 9)
        line(f"Payment reference: {inv.number}", 9)
    c.showPage()
    c.save()
    return buf.getvalue()
