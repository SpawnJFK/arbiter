"""Usage to charge at period end (D-074).

For every org with a current subscription on a priced (not custom) plan:

    used      = usage records of the period per metered unit (word, ai_unit)
    included  = plan.included[unit] (per billing month, also for yearly plans)
    overage   = max(0, used - included) * plan.overage[currency][unit]   per unit
    credits   = prepaid credit spent first (billing.credits.consume)
    due       = overage total - credits

and one invoice record of kind "overage" per org and period, which is also the idempotency
anchor: closing the same period again returns the existing record and moves nothing.

    due == 0  -> record status paid (fully covered by credit) or nothing at all (no overage)
    due > 0   -> the subscription's provider charges it: paddle/stripe add_charge (one-time
                 charge on the subscription, custom_data invoice_id so the provider's payment
                 webhook settles this record), manual/admin -> our own issued invoice.

A plan unit without an overage rate in the subscription currency is not charged (reported
as `unpriced` so the admin sees it).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from arbiter.billing import catalog, credits, entitlements
from arbiter.billing.invoices import invoice_view
from arbiter.billing.ledger import money
from arbiter.billing.providers import provider_for
from arbiter.billing.providers.base import ChargeLine
from arbiter.errors import Invalid
from arbiter.models import Invoice, Organization, Plan, Subscription, UsageRecord, utcnow

CENT = Decimal("0.01")
_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def overage_lines(
    session: Session, org_id: str, plan: Plan, currency: str, period: str
) -> tuple[list[dict], list[str]]:
    used = dict(
        session.execute(
            select(UsageRecord.unit, func.sum(UsageRecord.quantity))
            .where(UsageRecord.org_id == org_id, UsageRecord.period == period)
            .group_by(UsageRecord.unit)
        ).all()
    )
    lines: list[dict[str, Any]] = []
    unpriced: list[str] = []
    for unit in catalog.METERED_UNITS:
        u = Decimal(used.get(unit) or 0)
        inc = catalog.included(plan, unit)
        over = u - inc
        if over <= 0:
            continue
        rate = catalog.overage_rate(plan, unit, currency)
        if rate is None:
            unpriced.append(unit)
            continue
        amount = (over * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        if amount <= 0:
            continue
        lines.append(
            {
                "type": "overage",
                "unit": unit,
                "description": f"Overage {unit.replace('_', ' ')}s {period}",
                "used": format(u.normalize(), "f"),
                "included": format(inc.normalize(), "f"),
                "quantity": over,
                "unit_amount": rate,
                "amount": amount,
            }
        )
    return lines, unpriced


def close_org_period(session: Session, org: Organization, period: str) -> dict[str, Any]:
    if not _PERIOD.match(period or ""):
        raise Invalid("period must be YYYY-MM")
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"overage:{org.id}:{period}"})
    existing = session.execute(
        select(Invoice).where(
            Invoice.org_id == org.id,
            Invoice.period == period,
            Invoice.kind == "overage",
            Invoice.status != "void",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"org_id": org.id, "status": "already_closed", "invoice": invoice_view(existing)}
    sub: Subscription | None = entitlements.current_subscription(session, org.id)
    if sub is None:
        return {"org_id": org.id, "status": "no_subscription"}
    plan = session.execute(select(Plan).where(Plan.key == sub.plan_key)).scalar_one_or_none()
    if plan is None or plan.custom:
        return {"org_id": org.id, "status": "contract_plan"}
    lines, unpriced = overage_lines(session, org.id, plan, sub.currency, period)
    if not lines:
        return {"org_id": org.id, "status": "no_overage", "unpriced": unpriced}
    total = sum((ln["amount"] for ln in lines), Decimal("0"))
    covered = credits.consume(
        session,
        org.id,
        total,
        idempotency_key=f"overage:{org.id}:{period}",
        ref=f"overage {period}",
        currency=sub.currency,
    )
    due = total - covered
    stored = [
        {
            **ln,
            "quantity": format(ln["quantity"].normalize(), "f"),
            "unit_amount": str(ln["unit_amount"]),
            "amount": money(ln["amount"]),
        }
        for ln in lines
    ]
    if covered > 0:
        stored.append(
            {"type": "credits_applied", "description": "Prepaid credit applied", "amount": money(-covered)}
        )
    if covered > 0:
        charge_lines = [ChargeLine(f"Usage overage {period} after prepaid credit", Decimal(1), due, due)]
    else:
        charge_lines = [
            ChargeLine(ln["description"], ln["quantity"], ln["unit_amount"], ln["amount"]) for ln in lines
        ]
    summary = {"org_id": org.id, "covered_by_credit": money(covered), "due": money(due), "unpriced": unpriced}
    prov = provider_for(sub.provider, session) if due > 0 else None
    custom = {"org_id": org.id, "kind": "overage", "period": period}
    if prov is not None and prov.name == "manual":
        # Our own taxed invoice for the charge (manual / admin subscriptions); it is the record.
        res = prov.add_charge(
            subscription_id=None,
            customer_id=None,
            lines=charge_lines,
            currency=sub.currency,
            idempotency_key=f"overage:{org.id}:{period}",
            custom_data=custom,
        )
        charged = session.get(Invoice, res.provider_ref)
        assert charged is not None
        charged.period = period
        charged.lines = [*stored, *[ln for ln in charged.lines if ln.get("type") == "tax"]]
        session.flush()
        return {**summary, "status": "charged", "invoice": invoice_view(charged)}
    now = utcnow()
    inv = Invoice(
        org_id=org.id,
        number=f"OVR-{period.replace('-', '')}-{org.id[-12:]}"[:40],
        period=period,
        lines=stored
        + [{"type": "tax", "rate": "", "amount": "0.00", "note": "Tax is added by the charging provider."}],
        subtotal=total,
        tax=Decimal("0"),
        total=due,
        currency=sub.currency,
        status="paid" if due <= 0 else "issued",
        issued_at=now,
        paid_at=now if due <= 0 else None,
        kind="overage",
        provider="internal" if prov is None else prov.name,
    )
    session.add(inv)
    session.flush()
    if prov is not None:
        res = prov.add_charge(
            subscription_id=sub.provider_subscription_id,
            customer_id=sub.provider_customer_id,
            lines=charge_lines,
            currency=sub.currency,
            idempotency_key=f"overage:{org.id}:{period}",
            custom_data={**custom, "invoice_id": inv.id},
        )
        inv.provider_ref = res.provider_ref
        session.flush()
    return {**summary, "status": "charged" if due > 0 else "covered_by_credit", "invoice": invoice_view(inv)}


def close_period(session: Session, period: str) -> dict[str, Any]:
    """Every org with a current subscription. Expires credit lots first."""
    expired = credits.expire_lots(session)
    org_ids = list(
        session.execute(
            select(Subscription.org_id)
            .where(Subscription.status.in_(entitlements.ACTIVE_STATUSES))
            .distinct()
        ).scalars()
    )
    results = []
    for org_id in sorted(org_ids):
        org = session.get(Organization, org_id)
        if org is not None:
            results.append(close_org_period(session, org, period))
    return {"period": period, "expired_lots": expired, "orgs": results}
