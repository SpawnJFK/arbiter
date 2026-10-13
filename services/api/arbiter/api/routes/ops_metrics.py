"""Operational metrics for the platform admin and the uptime monitor.

GET /v1/admin/metrics/queue: work queue depth by status and kind, the age of the oldest
ready item and the number of dead items. Admin only; no customer data in the answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from arbiter.api.deps import DB, Admin
from arbiter.models import EmailMessage, WorkItem, utcnow

router = APIRouter(prefix="/admin/metrics", tags=["admin"])


@router.get("/queue")
def queue_metrics(_: Admin, db: DB) -> dict[str, Any]:
    now = utcnow()
    rows = db.execute(
        select(WorkItem.kind, WorkItem.status, func.count()).group_by(WorkItem.kind, WorkItem.status)
    ).all()
    totals = {"ready": 0, "running": 0, "done": 0, "dead": 0}
    by_kind: dict[str, dict[str, int]] = {}
    for kind, status, n in rows:
        totals[status] = totals.get(status, 0) + int(n)
        by_kind.setdefault(kind, {"ready": 0, "running": 0, "done": 0, "dead": 0})[status] = int(n)
    due = db.execute(
        select(func.count(), func.min(WorkItem.run_at)).where(
            WorkItem.status == "ready", WorkItem.run_at <= now
        )
    ).one()
    oldest = due[1]
    expired_leases = db.execute(
        select(func.count()).where(WorkItem.status == "running", WorkItem.locked_until < now)
    ).scalar_one()
    email_rows = db.execute(select(EmailMessage.status, func.count()).group_by(EmailMessage.status)).all()
    return {
        "at": now.isoformat(),
        "totals": totals,
        "due_now": int(due[0]),
        "oldest_due_age_seconds": round((now - oldest).total_seconds(), 1) if oldest else 0.0,
        "expired_leases": int(expired_leases),
        "by_kind": dict(sorted(by_kind.items())),
        "emails": {status: int(n) for status, n in email_rows},
    }
