"""Durable work queue on Postgres (D-002).

enqueue() runs inside the caller's transaction, so "change state + schedule next step"
commits or rolls back together. claim() uses FOR UPDATE SKIP LOCKED so any number of
workers can poll the same table without double-processing. A claimed item carries a
lease (locked_until); if a worker dies mid-step the lease expires and another worker
picks it up, which is why every step handler must be idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from arbiter.models import WorkItem, new_id, utcnow

LEASE = timedelta(minutes=10)


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    run_at: datetime | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 8,
) -> None:
    """Schedule a step. Same idempotency_key twice = one item (retries, double clicks)."""
    stmt = (
        insert(WorkItem)
        .values(
            id=new_id("wrk"),
            kind=kind,
            payload=payload,
            status="ready",
            run_at=run_at or utcnow(),
            attempts=0,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    session.execute(stmt)


def claim(session: Session, worker_id: str, *, kinds: list[str] | None = None) -> WorkItem | None:
    now = utcnow()
    q = (
        select(WorkItem)
        .where(
            WorkItem.run_at <= now,
            or_(
                WorkItem.status == "ready",
                (WorkItem.status == "running") & (WorkItem.locked_until < now),  # abandoned lease
            ),
        )
        .order_by(WorkItem.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if kinds:
        q = q.where(WorkItem.kind.in_(kinds))
    item = session.execute(q).scalar_one_or_none()
    if item is None:
        return None
    item.status = "running"
    item.locked_by = worker_id
    item.locked_until = now + LEASE
    item.attempts += 1
    session.flush()
    return item


def complete(item: WorkItem) -> None:
    item.status = "done"
    item.finished_at = utcnow()
    item.locked_by = None
    item.locked_until = None


def fail(item: WorkItem, error: str) -> bool:
    """Record a failure. Returns True when the item is dead (no attempts left)."""
    item.last_error = error[:4000]
    item.locked_by = None
    item.locked_until = None
    if item.attempts >= item.max_attempts:
        item.status = "dead"
        item.finished_at = utcnow()
        return True
    item.status = "ready"
    # exponential backoff: 5s, 10s, 20s ... capped at 30 min
    item.run_at = utcnow() + timedelta(seconds=min(5 * 2 ** (item.attempts - 1), 1800))
    return False
