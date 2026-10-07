"""Double-entry ledger helpers.

Sign convention: every movement is two rows with the same txn_id and amounts that sum to
zero. The account that RECEIVES value (a liability that grows, money owed to someone) gets
the positive row, the account it comes from gets the negative row. So the balance of
`reviewer:<id>:payable` is what the platform owes that reviewer.

Accounts used here:
  reviewer:<id>:payable          owed to a reviewer (review pay credited, payouts debited)
  platform:review_cost           expense side of review pay
  platform:payouts_in_transit    payout accrued or sent, not yet confirmed by the provider
  platform:cash                  money that actually left the platform
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.config import get_settings
from arbiter.models import LedgerEntry, new_id

REVIEW_COST = "platform:review_cost"
IN_TRANSIT = "platform:payouts_in_transit"
CASH = "platform:cash"


def reviewer_account(reviewer_id: str) -> str:
    return f"reviewer:{reviewer_id}:payable"


def post(
    session: Session,
    *,
    credit: str,
    debit: str,
    amount: Decimal,
    kind: str,
    ref: str = "",
    currency: str | None = None,
) -> str:
    """Move `amount` from `debit` to `credit`. Returns the txn id. Flushes."""
    if not isinstance(amount, Decimal):
        raise TypeError("ledger amounts must be Decimal")
    if amount <= 0:
        raise ValueError("ledger amount must be positive")
    cur = currency or get_settings().currency
    txn = new_id("txn")
    session.add_all(
        [
            LedgerEntry(txn_id=txn, account=credit, amount=amount, currency=cur, kind=kind, ref=ref),
            LedgerEntry(txn_id=txn, account=debit, amount=-amount, currency=cur, kind=kind, ref=ref),
        ]
    )
    session.flush()
    return txn


def account_balance(session: Session, account: str) -> Decimal:
    total = session.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.account == account)
    ).scalar_one()
    return Decimal(total)


def money(value: Decimal | int | str, places: str = "0.01") -> str:
    """Decimal -> contract money string ("12.40")."""
    return str(Decimal(value).quantize(Decimal(places)))
