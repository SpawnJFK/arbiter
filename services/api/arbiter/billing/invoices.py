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
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from arbiter.billing.ledger import money
from arbiter.community.errors import Invalid, NotFound
from arbiter.config import get_settings
from arbiter.models import Invoice, Organization, UsageRecord

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
        select(Invoice).where(Invoice.org_id == org_id, Invoice.period == period, Invoice.status != "void")
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
    }


def list_invoices(session: Session, org_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Invoice)
        .where(Invoice.org_id == org_id)
        .order_by(Invoice.period.desc(), Invoice.created_at.desc())
    ).scalars()
    return [invoice_view(i) for i in rows]
