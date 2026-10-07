"""Reviewer balances and payouts.

The ledger is the only source of truth for what a reviewer is owed (balance = sum of
`reviewer:<id>:payable`). A payout is a ledger movement, never a column update:

  run_payouts   reviewer payable -> platform:payouts_in_transit, Payout state accrued
                (balance >= payout_threshold and complete tax info; otherwise blocked)
  send_payouts  accrued -> sent through a PayoutProvider, then
                settled: in_transit -> platform:cash
                failed : in_transit -> reviewer payable (reversal, money is owed again);
                         the next run_payouts moves it back to accrued and re-sends it
                         with the SAME idempotency key, so the provider never pays twice.

Blocked payouts (tax info incomplete, required for DAC7-style platform reporting) carry no
ledger movement: the money stays in the reviewer's payable balance. One blocked payout per
reviewer at most; it is re-evaluated on every run and moves to accrued once the info is there.

Idempotency: Payout.idempotency_key = "payout:<reviewer>:<yyyy-mm-dd>" (unique), so running
twice the same day creates nothing new, and the provider receives that key on every send.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.billing import ledger
from arbiter.community.profiles import tax_info_complete
from arbiter.community.transitions import move
from arbiter.config import get_settings
from arbiter.models import LedgerEntry, Payout, ReviewerProfile, ReviewTask, utcnow

CENT = Decimal("0.01")


# ------------------------------------------------------------------ provider


@dataclass
class PayoutResult:
    status: Literal["settled", "failed", "pending"]
    provider_ref: str | None = None
    reason: str | None = None


class PayoutProvider(Protocol):
    name: str

    def send(
        self,
        *,
        idempotency_key: str,
        reviewer_id: str,
        amount: Decimal,
        currency: str,
        method: str,
        details: dict[str, Any],
    ) -> PayoutResult: ...


@dataclass
class MockPayoutProvider:
    """In-memory provider for dev and tests. Deduplicates on idempotency_key like real ones."""

    name: str = "mock"
    fail_reviewers: set[str] = field(default_factory=set)
    pending: bool = False
    calls: list[str] = field(default_factory=list)
    _results: dict[str, PayoutResult] = field(default_factory=dict)

    def send(
        self,
        *,
        idempotency_key: str,
        reviewer_id: str,
        amount: Decimal,
        currency: str,
        method: str,
        details: dict[str, Any],
    ) -> PayoutResult:
        self.calls.append(idempotency_key)
        if idempotency_key in self._results and self._results[idempotency_key].status != "failed":
            return self._results[idempotency_key]
        if reviewer_id in self.fail_reviewers:
            res = PayoutResult("failed", None, "mock: payout rejected by provider")
        elif self.pending:
            res = PayoutResult("pending", f"mock-{idempotency_key}")
        else:
            res = PayoutResult("settled", f"mock-{idempotency_key}")
        self._results[idempotency_key] = res
        return res


# ------------------------------------------------------------------ balances and views


def balance(session: Session, reviewer_id: str) -> Decimal:
    return ledger.account_balance(session, ledger.reviewer_account(reviewer_id))


def _sum_payouts(session: Session, reviewer_id: str, states: tuple[str, ...]) -> Decimal:
    v = session.execute(
        select(func.coalesce(func.sum(Payout.amount), 0)).where(
            Payout.reviewer_id == reviewer_id, Payout.state.in_(states)
        )
    ).scalar_one()
    return Decimal(v)


def payout_view(p: Payout) -> dict[str, Any]:
    return {
        "id": p.id,
        "reviewer_id": p.reviewer_id,
        "amount": ledger.money(p.amount),
        "currency": p.currency,
        "state": p.state,
        "method": p.method,
        "provider_ref": p.provider_ref,
        "failure_reason": p.failure_reason,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "sent_at": p.sent_at.isoformat() if p.sent_at else None,
    }


def earnings_view(session: Session, profile: ReviewerProfile, limit: int = 100) -> dict[str, Any]:
    """GET /reviewer/earnings -> {balance, pending, paid, entries[]} (+ disputable tasks)."""
    entries = session.execute(
        select(LedgerEntry)
        .where(LedgerEntry.account == ledger.reviewer_account(profile.id))
        .order_by(LedgerEntry.created_at.desc())
        .limit(limit)
    ).scalars()
    rejected = session.execute(
        select(ReviewTask)
        .where(ReviewTask.reviewer_id == profile.id, ReviewTask.state.in_(("rejected", "disputed")))
        .order_by(ReviewTask.submitted_at.desc())
        .limit(limit)
    ).scalars()
    return {
        "currency": get_settings().currency,
        "balance": ledger.money(balance(session, profile.id)),
        "pending": ledger.money(_sum_payouts(session, profile.id, ("accrued", "sent"))),
        "paid": ledger.money(_sum_payouts(session, profile.id, ("settled",))),
        "payout_threshold": ledger.money(profile.payout_threshold),
        "entries": [
            {
                "id": e.id,
                "kind": e.kind,
                "amount": ledger.money(e.amount),
                "currency": e.currency,
                "ref": e.ref,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "rejected_tasks": [
            {
                "task_id": t.id,
                "state": t.state,
                "submitted_at": t.submitted_at.isoformat() if t.submitted_at else None,
            }
            for t in rejected
        ],
    }


def list_payouts(session: Session, state: str | None = None) -> list[dict[str, Any]]:
    stmt = select(Payout).order_by(Payout.created_at.desc())
    if state:
        stmt = stmt.where(Payout.state == state)
    return [payout_view(p) for p in session.execute(stmt).scalars()]


# ------------------------------------------------------------------ run and send


def _accrue(session: Session, p: Payout, amount: Decimal) -> None:
    p.amount = amount
    ledger.post(
        session,
        credit=ledger.IN_TRANSIT,
        debit=ledger.reviewer_account(p.reviewer_id),
        amount=amount,
        kind="payout",
        ref=p.id,
        currency=p.currency,
    )


def run_payouts(
    session: Session, *, provider: PayoutProvider | None = None, today: date | None = None
) -> dict[str, Any]:
    """POST /admin/payouts/run -> {created, total, blocked, retried, payouts[]}.

    With a provider, also sends what was accrued (send_payouts) and returns its summary.
    """
    day = (today or utcnow().date()).isoformat()
    cur = get_settings().currency
    created: list[Payout] = []
    retried = 0
    blocked = 0

    profiles = list(session.execute(select(ReviewerProfile).order_by(ReviewerProfile.id)).scalars())
    for profile in profiles:
        complete = tax_info_complete(profile)
        # 1) failed payouts: money is back in the balance; re-accrue under the same key.
        failed = session.execute(
            select(Payout).where(Payout.reviewer_id == profile.id, Payout.state == "failed").with_for_update()
        ).scalars()
        for p in failed:
            if complete and balance(session, profile.id) >= p.amount > 0:
                move(p, "payout", "accrued")
                p.failure_reason = None
                _accrue(session, p, Decimal(p.amount))
                retried += 1

        bal = balance(session, profile.id).quantize(CENT)
        existing_blocked = session.execute(
            select(Payout)
            .where(Payout.reviewer_id == profile.id, Payout.state == "blocked")
            .with_for_update()
        ).scalar_one_or_none()
        if existing_blocked is not None:
            if complete and bal > 0:
                move(existing_blocked, "payout", "accrued")
                existing_blocked.failure_reason = None
                existing_blocked.method = profile.payout_method
                _accrue(session, existing_blocked, bal)
                created.append(existing_blocked)
            else:
                existing_blocked.amount = max(bal, Decimal("0"))
                blocked += 1
            continue

        if bal <= 0 or bal < Decimal(profile.payout_threshold):
            continue
        key = f"payout:{profile.id}:{day}"
        if session.execute(select(Payout.id).where(Payout.idempotency_key == key)).first() is not None:
            continue
        p = Payout(
            reviewer_id=profile.id,
            amount=bal,
            currency=cur,
            state="accrued",
            method=profile.payout_method,
            idempotency_key=key,
        )
        session.add(p)
        session.flush()
        if not complete:
            move(p, "payout", "blocked")
            p.failure_reason = "tax information incomplete (required for platform reporting)"
            blocked += 1
            continue
        _accrue(session, p, bal)
        created.append(p)

    session.flush()
    out: dict[str, Any] = {
        "created": len(created),
        "total": ledger.money(sum((p.amount for p in created), Decimal("0"))),
        "blocked": blocked,
        "retried": retried,
        "payouts": [payout_view(p) for p in created],
    }
    if provider is not None:
        out["send"] = send_payouts(session, provider)
    return out


def complete_payout(session: Session, p: Payout, *, ok: bool, reason: str | None = None) -> None:
    """A sent payout is confirmed (settled) or rejected (failed) by the provider."""
    if ok:
        move(p, "payout", "settled")
        ledger.post(
            session, credit=ledger.CASH, debit=ledger.IN_TRANSIT, amount=p.amount, kind="payout", ref=p.id
        )
    else:
        move(p, "payout", "failed")
        p.failure_reason = (reason or "provider failure")[:500]
        ledger.post(
            session,
            credit=ledger.reviewer_account(p.reviewer_id),
            debit=ledger.IN_TRANSIT,
            amount=p.amount,
            kind="adjustment",
            ref=p.id,
        )
    session.flush()


def send_payouts(session: Session, provider: PayoutProvider) -> dict[str, int]:
    """Send every accrued payout. Safe to retry: the provider dedups on idempotency_key."""
    rows = list(
        session.execute(
            select(Payout)
            .where(Payout.state == "accrued")
            .order_by(Payout.created_at)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    summary = {"sent": 0, "settled": 0, "failed": 0, "pending": 0}
    for p in rows:
        profile = session.get(ReviewerProfile, p.reviewer_id)
        assert profile is not None
        res = provider.send(
            idempotency_key=p.idempotency_key,
            reviewer_id=p.reviewer_id,
            amount=Decimal(p.amount),
            currency=p.currency,
            method=p.method or profile.payout_method,
            details=dict(profile.payout_details or {}),
        )
        move(p, "payout", "sent")
        p.sent_at = utcnow()
        p.provider_ref = res.provider_ref
        summary["sent"] += 1
        if res.status == "settled":
            complete_payout(session, p, ok=True)
            summary["settled"] += 1
        elif res.status == "failed":
            complete_payout(session, p, ok=False, reason=res.reason)
            summary["failed"] += 1
        else:
            summary["pending"] += 1
    session.flush()
    return summary
