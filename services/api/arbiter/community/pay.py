"""Reviewer pay per task.

Formula (starting values, to be tuned against real throughput and the market):

    pay = max(MIN_PER_TASK, BASE[decision] + words * PER_WORD[decision] * LEVEL_MULT[level])
    rounded half-up to the cent

    decision   BASE     PER_WORD (EUR)
    accept     0.00     0.004
    edit       0.01     0.012
    escalate   0        0         (an escalation is not paid; it is not a review)
    skip       0        0

    LEVEL_MULT: candidate 1.0, reviewer 1.0, senior 1.25, domain_expert 1.5

MIN_PER_TASK (0.02) applies only to paid decisions. Per-task amounts are rounded to the
cent at the source, so every ledger movement and payout is in whole cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from arbiter.billing import ledger
from arbiter.community.transitions import move
from arbiter.config import get_settings
from arbiter.domain.states import assert_transition
from arbiter.models import Job, ReviewTask

CENT = Decimal("0.01")
MIN_PER_TASK = Decimal("0.02")
BASE: dict[str, Decimal] = {
    "accept": Decimal("0"),
    "edit": Decimal("0.01"),
    "escalate": Decimal("0"),
    "skip": Decimal("0"),
}
PER_WORD: dict[str, Decimal] = {
    "accept": Decimal("0.004"),
    "edit": Decimal("0.012"),
    "escalate": Decimal("0"),
    "skip": Decimal("0"),
}
LEVEL_MULT: dict[str, Decimal] = {
    "candidate": Decimal("1.0"),
    "reviewer": Decimal("1.0"),
    "senior": Decimal("1.25"),
    "domain_expert": Decimal("1.5"),
}
PAID_DECISIONS = ("accept", "edit")


def task_pay(decision: str, words: int, level: str) -> Decimal:
    """Pay for one decision on a segment of `words` words by a reviewer at `level`."""
    if decision not in PAID_DECISIONS:
        return Decimal("0.00")
    raw = BASE[decision] + Decimal(max(words, 0)) * PER_WORD[decision] * LEVEL_MULT.get(level, Decimal("1"))
    return max(MIN_PER_TASK, raw).quantize(CENT, rounding=ROUND_HALF_UP)


def credit_task(session: Session, task: ReviewTask) -> None:
    """accepted -> payable: credit the reviewer, debit platform review cost, add to job cost.

    Must be called on an `accepted` task. A zero amount moves the state but writes no ledger rows.
    """
    assert_transition("task", task.state, "payable")
    amount = Decimal(task.pay_amount or 0).quantize(CENT)
    if amount > 0:
        assert task.reviewer_id is not None
        ledger.post(
            session,
            credit=ledger.reviewer_account(task.reviewer_id),
            debit=ledger.REVIEW_COST,
            amount=amount,
            kind="review_pay",
            ref=task.id,
            currency=get_settings().currency,
        )
        job = session.get(Job, task.job_id)
        if job is not None:
            job.cost_reviewers = Decimal(job.cost_reviewers or 0) + amount
    move(task, "task", "payable")
    session.flush()
