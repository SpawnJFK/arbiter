"""Disputes: a reviewer contests a rejected (failed control) task.

* only a `rejected` task of your own, within DISPUTE_WINDOW_DAYS (7) of submission
* a senior or admin decides within DECISION_HOURS (48): upheld -> task stays rejected and a
  dispute_lost score event; overturned -> task accepted -> payable, the reviewer is paid and a
  dispute_won event cancels the control_fail in the score
* expire(): an open dispute past its due time resolves in the reviewer's favour (status
  "expired", same effect as overturned). We promised an answer in 48 hours; when we miss it
  the cost of our delay is ours, not the reviewer's.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.community import pay, scoring
from arbiter.community.errors import Conflict, Invalid, NotFound
from arbiter.community.transitions import move
from arbiter.models import Dispute, ReviewerProfile, ReviewTask, utcnow

DISPUTE_WINDOW_DAYS = 7
DECISION_HOURS = 48
OUTCOMES = ("upheld", "overturned")


def dispute_view(d: Dispute) -> dict[str, Any]:
    return {
        "id": d.id,
        "task_id": d.task_id,
        "reviewer_id": d.reviewer_id,
        "reason": d.reason,
        "status": d.status,
        "decided_by": d.decided_by,
        "decision_note": d.decision_note,
        "due_at": d.due_at.isoformat(),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
    }


def open_dispute(session: Session, profile: ReviewerProfile, task_id: str, reason: str) -> dict[str, Any]:
    """POST /reviewer/disputes -> {id, due_at}."""
    if not (reason or "").strip():
        raise Invalid("a reason is required")
    task = session.get(ReviewTask, task_id, with_for_update=True)
    if task is None or task.reviewer_id != profile.id:
        raise NotFound("task not found")
    if task.state != "rejected":
        raise Conflict("only rejected tasks can be disputed")
    existing = session.execute(select(Dispute).where(Dispute.task_id == task.id)).scalar_one_or_none()
    if existing is not None:
        raise Conflict("this task was already disputed")
    now = utcnow()
    if task.submitted_at is None or now - task.submitted_at > timedelta(days=DISPUTE_WINDOW_DAYS):
        raise Conflict(f"disputes must be opened within {DISPUTE_WINDOW_DAYS} days")
    move(task, "task", "disputed")
    d = Dispute(
        task_id=task.id,
        reviewer_id=profile.id,
        reason=reason.strip()[:5000],
        status="open",
        due_at=now + timedelta(hours=DECISION_HOURS),
    )
    session.add(d)
    session.flush()
    return {"id": d.id, "due_at": d.due_at.isoformat(), "status": d.status}


def _resolve(session: Session, d: Dispute, *, overturn: bool, status: str, note: str, by: str | None) -> None:
    task = session.get(ReviewTask, d.task_id, with_for_update=True)
    profile = session.get(ReviewerProfile, d.reviewer_id)
    assert task is not None and profile is not None
    if overturn:
        move(task, "task", "accepted")
        pay.credit_task(session, task)
        pair = scoring.pair_for_task(session, profile.id, task)
        if pair is not None:
            pair.control_passed += 1
        scoring.record_event(session, profile, "dispute_won", task=task, note=note)
    else:
        move(task, "task", "rejected")
        scoring.record_event(session, profile, "dispute_lost", task=task, note=note)
    d.status = status
    d.decision_note = note
    d.decided_by = by
    d.decided_at = utcnow()
    session.flush()


def decide(session: Session, dispute_id: str, outcome: str, note: str, admin_user_id: str) -> dict[str, Any]:
    """POST /admin/disputes/{id}/decide."""
    if outcome not in OUTCOMES:
        raise Invalid("outcome must be upheld or overturned")
    d = session.get(Dispute, dispute_id, with_for_update=True)
    if d is None:
        raise NotFound("dispute not found")
    if d.status != "open":
        raise Conflict(f"dispute is already {d.status}")
    _resolve(session, d, overturn=outcome == "overturned", status=outcome, note=note or "", by=admin_user_id)
    return dispute_view(d)


def expire(session: Session, now: datetime | None = None) -> int:
    """Open disputes past due resolve in the reviewer's favour (see module docstring)."""
    now = now or utcnow()
    rows = list(
        session.execute(
            select(Dispute)
            .where(Dispute.status == "open", Dispute.due_at < now)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    for d in rows:
        _resolve(
            session,
            d,
            overturn=True,
            status="expired",
            note=f"Not decided within {DECISION_HOURS} hours; resolved in the reviewer's favour.",
            by=None,
        )
    return len(rows)


def list_disputes(session: Session, status: str | None = None) -> list[dict[str, Any]]:
    stmt = select(Dispute).order_by(Dispute.due_at)
    if status:
        stmt = stmt.where(Dispute.status == status)
    return [dispute_view(d) for d in session.execute(stmt).scalars()]
