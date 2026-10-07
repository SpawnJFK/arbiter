"""State machines from the rulebook.

A transition that is not listed here does not exist. Attempting one raises
IllegalTransition, which is a bug in the caller, never a system state.
"""

from __future__ import annotations

from enum import StrEnum


class IllegalTransition(Exception):
    def __init__(self, machine: str, src: str, dst: str) -> None:
        super().__init__(f"{machine}: illegal transition {src} -> {dst}")
        self.machine, self.src, self.dst = machine, src, dst


class SegmentState(StrEnum):
    pending = "pending"
    translated = "translated"
    auto_approved = "auto_approved"
    needs_review = "needs_review"
    in_review = "in_review"
    reviewed = "reviewed"
    delivered = "delivered"


class JobState(StrEnum):
    draft = "draft"
    quoted = "quoted"
    cancelled = "cancelled"
    running = "running"
    review = "review"
    ready = "ready"
    merging = "merging"
    failed = "failed"
    delivered = "delivered"
    settled = "settled"
    disputed = "disputed"


class TaskState(StrEnum):
    queued = "queued"
    offered = "offered"
    held = "held"
    submitted = "submitted"
    accepted = "accepted"
    rejected = "rejected"
    disputed = "disputed"
    payable = "payable"


class PayoutState(StrEnum):
    payable = "payable"
    accrued = "accrued"
    sent = "sent"
    settled = "settled"
    failed = "failed"
    blocked = "blocked"


S, J, T, P = SegmentState, JobState, TaskState, PayoutState

SEGMENT_TRANSITIONS: dict[SegmentState, set[SegmentState]] = {
    S.pending: {S.translated, S.auto_approved},
    S.translated: {S.auto_approved, S.needs_review, S.translated},
    S.needs_review: {S.in_review, S.reviewed},  # reviewed directly only via editor on ai_review tier
    S.in_review: {S.reviewed, S.needs_review},
    S.auto_approved: {S.delivered},
    S.reviewed: {S.delivered},
    S.delivered: {S.needs_review},  # the only backwards transition: accepted complaint
}

JOB_TRANSITIONS: dict[JobState, set[JobState]] = {
    J.draft: {J.quoted, J.cancelled},
    J.quoted: {J.running, J.cancelled},
    J.running: {J.review, J.ready, J.failed, J.cancelled},
    J.review: {J.ready, J.failed, J.cancelled},
    J.ready: {J.merging},
    J.merging: {J.delivered, J.failed},
    J.failed: {J.running, J.review, J.merging},  # a human fixes the cause and resumes
    J.delivered: {J.settled, J.disputed},
    J.settled: {J.disputed},
    J.disputed: {J.review},  # the only backwards transition for jobs
    J.cancelled: set(),
}

TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    T.queued: {T.offered},
    T.offered: {T.queued, T.held},
    T.held: {T.submitted, T.queued},
    T.submitted: {T.accepted, T.rejected},
    T.rejected: {T.disputed},
    T.disputed: {T.accepted, T.rejected},
    T.accepted: {T.payable},
    T.payable: set(),
}

PAYOUT_TRANSITIONS: dict[PayoutState, set[PayoutState]] = {
    P.payable: {P.accrued},
    P.accrued: {P.sent, P.blocked},
    P.sent: {P.settled, P.failed},
    P.failed: {P.accrued},
    P.blocked: {P.accrued},
    P.settled: set(),
}

_MACHINES = {
    "segment": SEGMENT_TRANSITIONS,
    "job": JOB_TRANSITIONS,
    "task": TASK_TRANSITIONS,
    "payout": PAYOUT_TRANSITIONS,
}


def can(machine: str, src: str, dst: str) -> bool:
    table = _MACHINES[machine]
    return any(str(k) == src and dst in {str(v) for v in vs} for k, vs in table.items())


def assert_transition(machine: str, src: str, dst: str) -> None:
    if not can(machine, src, dst):
        raise IllegalTransition(machine, src, dst)


def transition(obj: object, machine: str, dst: str) -> None:
    """The only way code changes a `state` column: validate, then assign."""
    src = str(obj.state)  # type: ignore[attr-defined]
    if src == str(dst):
        return
    assert_transition(machine, src, str(dst))
    obj.state = str(dst)  # type: ignore[attr-defined]
