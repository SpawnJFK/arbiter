"""Platform fee on human review and vendor work (D-073).

The customer pays the human work (reviewer pay, vendor cost) plus a platform fee: a percent
of that work, configurable per organization, default 5 %, allowed range 0 to 8 % (the
marketplace pattern where the fee is charged to the paying side and shown up front).

    org.settings["billing"]["platform_fee_percent"] = "5"   (decimal string)

Where it shows and lands:
  * quotes: every tier with human work (hybrid, full) carries
    {"platform_fee": {"percent", "estimate", "basis_estimate"}} and "total_estimate"
    (price + fee estimate). The basis is estimated from review words and the reviewer pay
    rate, so the quote says "estimate".
  * at the moment the human work is credited (community.pay.credit_task, later vendor
    bills), `charge_fee` books the actual fee: ledger platform:revenue:platform_fee <-
    org:<id>:receivable, plus a usage record (unit platform_fee) so it appears on the
    period's usage and invoice.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.billing import ledger, usage
from arbiter.config import get_settings
from arbiter.errors import Invalid
from arbiter.models import Organization, UsageRecord

CENT = Decimal("0.01")
HUMAN_TIERS = ("hybrid", "full")


def fee_bounds() -> tuple[Decimal, Decimal]:
    s = get_settings()
    return Decimal(s.platform_fee_percent_default), Decimal(s.platform_fee_percent_max)


def validate_percent(value: Any) -> Decimal:
    _, maximum = fee_bounds()
    if isinstance(value, float):
        raise Invalid("platform_fee_percent must be a decimal string")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Invalid("platform_fee_percent must be a decimal string") from None
    if not d.is_finite() or d < 0 or d > maximum:
        raise Invalid(f"platform_fee_percent must be between 0 and {maximum}")
    return d


def platform_fee_percent(org: Organization | None) -> Decimal:
    default, _ = fee_bounds()
    if org is None:
        return default
    raw = ((org.settings or {}).get("billing") or {}).get("platform_fee_percent")
    if raw is None:
        return default
    try:
        return validate_percent(raw)
    except Invalid:
        return default


def set_platform_fee_percent(org: Organization, value: Any) -> Decimal:
    pct = validate_percent(value)
    settings = dict(org.settings or {})
    billing = dict(settings.get("billing") or {})
    billing["platform_fee_percent"] = str(pct)
    settings["billing"] = billing
    org.settings = settings
    return pct


def fee_for(base: Decimal, percent: Decimal) -> Decimal:
    if not isinstance(base, Decimal):
        raise TypeError("fee base must be Decimal")
    return (base * percent / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def quote_fee(org: Organization, human_cost_estimate: Decimal) -> dict[str, str]:
    pct = platform_fee_percent(org)
    return {
        "percent": str(pct),
        "basis_estimate": ledger.money(human_cost_estimate),
        "estimate": ledger.money(fee_for(human_cost_estimate, pct)),
    }


def charge_fee(
    session: Session,
    org: Organization,
    base: Decimal,
    *,
    ref: str,
    job_id: str | None = None,
    kind: str = "review",
) -> Decimal:
    """Book the platform fee on `base` of human work. Idempotent per ref. Returns the fee."""
    pct = platform_fee_percent(org)
    fee = fee_for(base, pct)
    if fee <= 0:
        return Decimal("0.00")
    key = f"platform_fee:{kind}:{ref}"
    if session.execute(select(UsageRecord.id).where(UsageRecord.idempotency_key == key)).first() is not None:
        return fee
    usage.record(
        session,
        org.id,
        job_id,
        "platform_fee",
        base,
        fee,
        key,
        {"percent": str(pct), "kind": kind, "ref": ref},
    )
    ledger.post(
        session,
        credit=ledger.REVENUE_PLATFORM_FEE,
        debit=ledger.receivable_account(org.id),
        amount=fee,
        kind="platform_fee",
        ref=ref[:80],
        currency=get_settings().currency,
    )
    return fee
