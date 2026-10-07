"""Usage metering: idempotent usage records per org and month.

Units: word | ai_unit | review_decision | storage_gb.

AI units normalise model work across providers so the client sees one number. Per segment
(starting values, roughly proportional to tokens spent per step with the default models):

    qe           0.05   one QE judge call
    ai_reviewer  0.15   AI editor pass on a segment below threshold
    translation  0.25   LLM translation of a segment
    senate       0.40   full council (all roles) on a borderline segment
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arbiter.billing.ledger import money
from arbiter.community.errors import Invalid
from arbiter.config import get_settings
from arbiter.models import UsageRecord, utcnow

UNITS = ("word", "ai_unit", "review_decision", "storage_gb")
AI_UNITS_PER_SEGMENT: dict[str, Decimal] = {
    "qe": Decimal("0.05"),
    "ai_reviewer": Decimal("0.15"),
    "translation": Decimal("0.25"),
    "senate": Decimal("0.40"),
}


def ai_units(step: str, segments: int = 1) -> Decimal:
    """AI units for `segments` segments of one pipeline step."""
    if step not in AI_UNITS_PER_SEGMENT:
        raise ValueError(f"unknown AI step {step}")
    return AI_UNITS_PER_SEGMENT[step] * segments


def current_period() -> str:
    return utcnow().strftime("%Y-%m")


def record(
    session: Session,
    org_id: str,
    job_id: str | None,
    unit: str,
    quantity: Decimal | int | str,
    amount: Decimal | int | str,
    idempotency_key: str,
    meta: dict[str, Any] | None = None,
    *,
    period: str | None = None,
) -> UsageRecord:
    """Record usage once. A second call with the same key returns the first record unchanged."""
    if unit not in UNITS:
        raise Invalid(f"unit must be one of {', '.join(UNITS)}")
    if not idempotency_key:
        raise Invalid("idempotency_key is required")
    if isinstance(quantity, float) or isinstance(amount, float):
        raise TypeError("usage quantity and amount must be Decimal, never float")
    existing = session.execute(
        select(UsageRecord).where(UsageRecord.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    rec = UsageRecord(
        org_id=org_id,
        job_id=job_id,
        period=period or current_period(),
        unit=unit,
        quantity=Decimal(quantity),
        amount=Decimal(amount),
        meta=dict(meta or {}),
        idempotency_key=idempotency_key,
    )
    try:
        with session.begin_nested():
            session.add(rec)
            session.flush()
    except IntegrityError:
        # A concurrent writer won the race on the unique key: return its row.
        return session.execute(
            select(UsageRecord).where(UsageRecord.idempotency_key == idempotency_key)
        ).scalar_one()
    return rec


def usage_view(session: Session, org_id: str, period: str | None = None) -> dict[str, Any]:
    """GET /usage?period=YYYY-MM -> {period, words, ai_units, review_decisions, amount}."""
    period = period or current_period()
    rows = session.execute(
        select(UsageRecord.unit, func.sum(UsageRecord.quantity), func.sum(UsageRecord.amount))
        .where(UsageRecord.org_id == org_id, UsageRecord.period == period)
        .group_by(UsageRecord.unit)
    ).all()
    qty = {u: Decimal(q or 0) for u, q, _ in rows}
    amount = sum((Decimal(a or 0) for _, _, a in rows), Decimal("0"))
    return {
        "period": period,
        "words": int(qty.get("word", Decimal("0"))),
        "ai_units": str(qty.get("ai_unit", Decimal("0")).quantize(Decimal("0.01"))),
        "review_decisions": int(qty.get("review_decision", Decimal("0"))),
        "storage_gb": str(qty.get("storage_gb", Decimal("0")).quantize(Decimal("0.01"))),
        "amount": money(amount),
        "currency": get_settings().currency,
    }
