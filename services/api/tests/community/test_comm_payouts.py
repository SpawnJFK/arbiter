from __future__ import annotations

from datetime import date
from decimal import Decimal

from comm_helpers import fill_tax, make_reviewer

from arbiter.billing import ledger
from arbiter.community import payouts
from arbiter.models import LedgerEntry, Payout


def _credit(db, reviewer_id: str, amount: str) -> None:
    ledger.post(
        db,
        credit=ledger.reviewer_account(reviewer_id),
        debit=ledger.REVIEW_COST,
        amount=Decimal(amount),
        kind="review_pay",
        ref="test",
    )


def _ledger_sum(db) -> Decimal:
    return sum((e.amount for e in db.query(LedgerEntry)), Decimal("0"))


def test_payout_blocked_without_tax_info_then_released(db):
    r = make_reviewer(db, tax=False, threshold="10")
    _credit(db, r.id, "25.00")
    out = payouts.run_payouts(db)
    assert out["created"] == 0 and out["blocked"] == 1
    p = db.query(Payout).filter_by(reviewer_id=r.id).one()
    assert p.state == "blocked" and "tax" in p.failure_reason
    assert payouts.balance(db, r.id) == Decimal("25.00")  # no ledger movement while blocked

    # A second run does not pile up blocked payouts.
    assert payouts.run_payouts(db, today=date(2030, 1, 2))["blocked"] == 1
    assert db.query(Payout).filter_by(reviewer_id=r.id).count() == 1

    fill_tax(db, r)
    out = payouts.run_payouts(db)
    assert out["created"] == 1 and out["total"] == "25.00"
    assert p.state == "accrued" and p.method == "sepa"
    assert payouts.balance(db, r.id) == 0
    assert ledger.account_balance(db, ledger.IN_TRANSIT) == Decimal("25.00")
    assert _ledger_sum(db) == 0


def test_payout_idempotent_on_retry_and_failure_reversal(db):
    r = make_reviewer(db, threshold="10")
    _credit(db, r.id, "12.34")
    day = date(2030, 1, 1)
    first = payouts.run_payouts(db, today=day)
    assert first["created"] == 1
    _credit(db, r.id, "20.00")
    assert payouts.run_payouts(db, today=day)["created"] == 0  # same day, same key: nothing new
    p = db.query(Payout).one()
    assert p.idempotency_key == f"payout:{r.id}:2030-01-01"

    provider = payouts.MockPayoutProvider(fail_reviewers={r.id})
    res = payouts.send_payouts(db, provider)
    assert res == {"sent": 1, "settled": 0, "failed": 1, "pending": 0}
    assert p.state == "failed"
    assert payouts.balance(db, r.id) == Decimal("32.34")  # reversed: owed again
    assert payouts.send_payouts(db, provider)["sent"] == 0  # failed payouts are not re-sent blindly

    # Next run re-accrues the same payout (same key), the provider now accepts it.
    again = payouts.run_payouts(db, today=date(2030, 1, 2))
    assert again["retried"] == 1 and again["created"] == 1  # the 20.00 is a new payout
    assert db.query(Payout).count() == 2 and p.state == "accrued"
    provider.fail_reviewers.clear()
    assert payouts.send_payouts(db, provider)["settled"] == 2
    assert p.state == "settled" and p.provider_ref == f"mock-{p.idempotency_key}"
    assert provider.calls[:2] == [p.idempotency_key, p.idempotency_key]
    assert provider.calls[2] == f"payout:{r.id}:2030-01-02"
    assert payouts.balance(db, r.id) == 0
    assert ledger.account_balance(db, ledger.CASH) == Decimal("32.34")
    assert _ledger_sum(db) == 0
    assert sorted(x["amount"] for x in payouts.list_payouts(db)) == ["12.34", "20.00"]


def test_pending_payout_completed_later(db):
    r = make_reviewer(db, threshold="1")
    _credit(db, r.id, "5.00")
    payouts.run_payouts(db)
    res = payouts.send_payouts(db, payouts.MockPayoutProvider(pending=True))
    assert res["pending"] == 1
    p = db.query(Payout).one()
    assert p.state == "sent"
    payouts.complete_payout(db, p, ok=True)
    assert p.state == "settled"
    view = payouts.earnings_view(db, r)
    assert view["paid"] == "5.00" and view["pending"] == "0.00"
