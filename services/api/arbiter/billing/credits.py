"""Prepaid credit wallet (D-074).

A credit is money the customer paid in advance (a credit pack bought through the payment
provider) or was granted by the platform admin. It is spent on usage charges (overage at
period close) before anything is charged to the payment method.

Bookkeeping, two layers that always agree:
  * credit_ledger rows per lot: purchase / grant rows are lots (positive, with expires_at);
    consumption / expiry / refund rows are negative and name the lot they draw from.
  * the double-entry ledger (billing.ledger): every row is one txn on `org:<id>:credits`.
    purchase:    credits   <- platform:provider_clearing  (the provider holds the money)
    grant:       credits   <- platform:promotions
    consumption: platform:revenue:usage     <- credits
    expiry:      platform:revenue:breakage  <- credits
    refund:      platform:provider_clearing <- credits

Spending order: the lot that expires first, then the oldest. Every movement carries an
idempotency key, so a retried webhook or period close never moves credit twice.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from arbiter.billing import ledger
from arbiter.config import get_settings
from arbiter.errors import Invalid
from arbiter.models import CreditLedgerEntry, utcnow

PROMOTIONS = "platform:promotions"
LOT_KINDS = ("purchase", "grant")


def _lock(session: Session, org_id: str) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"credits:{org_id}"})


def _by_key(session: Session, key: str) -> CreditLedgerEntry | None:
    return session.execute(
        select(CreditLedgerEntry).where(CreditLedgerEntry.idempotency_key == key)
    ).scalar_one_or_none()


def balance(session: Session, org_id: str) -> Decimal:
    return ledger.account_balance(session, ledger.credits_account(org_id))


def add_lot(
    session: Session,
    org_id: str,
    amount: Decimal,
    *,
    kind: str,
    idempotency_key: str,
    currency: str | None = None,
    valid_days: int | None = 365,
    ref: str = "",
) -> CreditLedgerEntry:
    """A purchase or grant. Same key again returns the first lot unchanged."""
    if kind not in LOT_KINDS:
        raise ValueError(f"lot kind must be one of {LOT_KINDS}")
    if not isinstance(amount, Decimal) or amount <= 0:
        raise Invalid("credit amount must be a positive decimal")
    existing = _by_key(session, idempotency_key)
    if existing is not None:
        return existing
    _lock(session, org_id)
    cur = (currency or get_settings().currency).upper()
    txn = ledger.post(
        session,
        credit=ledger.credits_account(org_id),
        debit=ledger.PROVIDER_CLEARING if kind == "purchase" else PROMOTIONS,
        amount=amount,
        kind=f"credit_{kind}",
        ref=ref[:80],
        currency=cur,
    )
    lot = CreditLedgerEntry(
        org_id=org_id,
        kind=kind,
        amount=amount,
        currency=cur,
        expires_at=utcnow() + timedelta(days=valid_days) if valid_days else None,
        txn_id=txn,
        ref=ref[:120],
        idempotency_key=idempotency_key,
    )
    session.add(lot)
    session.flush()
    return lot


def lot_remaining(session: Session, lot: CreditLedgerEntry) -> Decimal:
    drawn = session.execute(
        select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(CreditLedgerEntry.lot_id == lot.id)
    ).scalar_one()
    return Decimal(lot.amount) + Decimal(drawn)


def _open_lots(
    session: Session, org_id: str, now: datetime, currency: str | None = None
) -> list[tuple[CreditLedgerEntry, Decimal]]:
    stmt = select(CreditLedgerEntry).where(
        CreditLedgerEntry.org_id == org_id,
        CreditLedgerEntry.kind.in_(LOT_KINDS),
    )
    if currency:
        stmt = stmt.where(CreditLedgerEntry.currency == currency.upper())
    lots = list(
        session.execute(
            stmt.order_by(
                CreditLedgerEntry.expires_at.asc().nulls_last(),
                CreditLedgerEntry.created_at,
                CreditLedgerEntry.id,
            )
        ).scalars()
    )
    out = []
    for lot in lots:
        if lot.expires_at is not None and lot.expires_at <= now:
            continue
        rem = lot_remaining(session, lot)
        if rem > 0:
            out.append((lot, rem))
    return out


def _draw(
    session: Session, lot: CreditLedgerEntry, amount: Decimal, *, kind: str, key: str, ref: str
) -> CreditLedgerEntry:
    credit = {
        "consumption": ledger.REVENUE_USAGE,
        "expiry": ledger.REVENUE_BREAKAGE,
        "refund": ledger.PROVIDER_CLEARING,
    }[kind]
    txn = ledger.post(
        session,
        credit=credit,
        debit=ledger.credits_account(lot.org_id),
        amount=amount,
        kind=f"credit_{kind}",
        ref=ref[:80],
        currency=lot.currency,
    )
    row = CreditLedgerEntry(
        org_id=lot.org_id,
        kind=kind,
        amount=-amount,
        currency=lot.currency,
        lot_id=lot.id,
        txn_id=txn,
        ref=ref[:120],
        idempotency_key=key,
    )
    session.add(row)
    session.flush()
    return row


def consume(
    session: Session,
    org_id: str,
    amount: Decimal,
    *,
    idempotency_key: str,
    ref: str = "",
    currency: str | None = None,
    now: datetime | None = None,
) -> Decimal:
    """Spend up to `amount` from the wallet. Returns what was actually covered.

    Idempotent per key: a second call returns what the first one consumed.
    """
    if not isinstance(amount, Decimal):
        raise TypeError("credit amounts must be Decimal")
    _lock(session, org_id)
    done = session.execute(
        select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(
            CreditLedgerEntry.org_id == org_id,
            CreditLedgerEntry.kind == "consumption",
            CreditLedgerEntry.idempotency_key.like(f"{idempotency_key}:%"),
        )
    ).scalar_one()
    if Decimal(done) != 0:
        return -Decimal(done)
    if amount <= 0:
        return Decimal("0")
    left = amount
    for lot, rem in _open_lots(session, org_id, now or utcnow(), currency):
        if left <= 0:
            break
        take = min(rem, left)
        _draw(session, lot, take, kind="consumption", key=f"{idempotency_key}:{lot.id}", ref=ref)
        left -= take
    return amount - left


def expire_lots(session: Session, now: datetime | None = None) -> int:
    """Lots past expires_at with credit left: the rest becomes breakage. Returns lots expired."""
    now = now or utcnow()
    lots = list(
        session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.kind.in_(LOT_KINDS),
                CreditLedgerEntry.expires_at.is_not(None),
                CreditLedgerEntry.expires_at <= now,
            )
        ).scalars()
    )
    n = 0
    for lot in lots:
        key = f"expiry:{lot.id}"
        if _by_key(session, key) is not None:
            continue
        _lock(session, lot.org_id)
        rem = lot_remaining(session, lot)
        if rem > 0:
            _draw(session, lot, rem, kind="expiry", key=key, ref=lot.ref or lot.id)
            n += 1
    return n


def refund_lot(
    session: Session, lot: CreditLedgerEntry, amount: Decimal | None, *, idempotency_key: str, ref: str = ""
) -> Decimal:
    """Refund unused credit of one lot (provider refund of a pack). Returns the amount refunded."""
    existing = _by_key(session, idempotency_key)
    if existing is not None:
        return -Decimal(existing.amount)
    _lock(session, lot.org_id)
    rem = lot_remaining(session, lot)
    take = rem if amount is None else min(rem, amount)
    if take <= 0:
        return Decimal("0")
    _draw(session, lot, take, kind="refund", key=idempotency_key, ref=ref or lot.ref)
    return take


def find_lot_by_ref(session: Session, org_id: str, ref: str) -> CreditLedgerEntry | None:
    return session.execute(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.org_id == org_id,
            CreditLedgerEntry.kind == "purchase",
            CreditLedgerEntry.ref == ref,
        )
    ).scalar_one_or_none()


def credits_view(session: Session, org_id: str, limit: int = 50) -> dict[str, Any]:
    now = utcnow()
    lots = [
        {
            "id": lot.id,
            "kind": lot.kind,
            "amount": ledger.money(lot.amount),
            "remaining": ledger.money(rem),
            "currency": lot.currency,
            "expires_at": lot.expires_at.isoformat() if lot.expires_at else None,
            "ref": lot.ref,
            "created_at": lot.created_at.isoformat() if lot.created_at else None,
        }
        for lot, rem in _open_lots(session, org_id, now)
    ]
    entries = session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.org_id == org_id)
        .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
        .limit(limit)
    ).scalars()
    return {
        "balance": ledger.money(balance(session, org_id)),
        "currency": get_settings().currency,
        "lots": lots,
        "entries": [
            {
                "id": e.id,
                "kind": e.kind,
                "amount": ledger.money(e.amount),
                "currency": e.currency,
                "lot_id": e.lot_id,
                "ref": e.ref,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }
