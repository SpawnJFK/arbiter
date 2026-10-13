"""Audit log: who changed what, from where, in which organization.

`audit(db, principal, action, target_type, target_id, data)` adds one append-only row to
audit_events in the caller's session, so the event commits or rolls back together with the
change it describes. The client IP and user agent come from a request-scoped context that
`AuditContextMiddleware` fills; outside a request (CLI, worker) they stay empty.

Action names are "<area>.<verb>" in the past tense: org.updated, api_key.created,
role.deleted, user.invited, module.changed, sso.updated, project.created, job.cancelled...
`data` never holds secrets: keys named like a secret are replaced before the row is written.
"""

from __future__ import annotations

import contextvars
import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from arbiter.config import get_settings
from arbiter.models import AuditEvent

_SECRET_HINTS = ("secret", "password", "token", "api_key", "private_key")


@dataclass(frozen=True)
class RequestInfo:
    ip: str = ""
    user_agent: str = ""


_EMPTY = RequestInfo()
_request_info: contextvars.ContextVar[RequestInfo | None] = contextvars.ContextVar(
    "arbiter_audit_request", default=None
)


def request_info() -> RequestInfo:
    return _request_info.get() or _EMPTY


class AuditContextMiddleware:
    """Pure ASGI middleware: records client IP and user agent for audit rows of this request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client = scope.get("client")
        ip = client[0] if client else ""
        if get_settings().trust_proxy_headers and headers.get("x-forwarded-for"):
            ip = headers["x-forwarded-for"].split(",")[0].strip()
        token = _request_info.set(RequestInfo(ip=ip[:64], user_agent=headers.get("user-agent", "")[:400]))
        try:
            await self.app(scope, receive, send)
        finally:
            _request_info.reset(token)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if any(h in str(k).lower() for h in _SECRET_HINTS) else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_scrub(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)  # Decimal, datetime... stay readable, never float-converted


def as_actor(user: Any, org: Any = None) -> Any:
    """A principal-like object for events without a request principal (login, register)."""
    from types import SimpleNamespace

    return SimpleNamespace(user=user, api_key=None, org=org)


def _actor(principal: Any) -> tuple[str, str, str]:
    if principal is None:
        return "system", "", ""
    key = getattr(principal, "api_key", None)
    if key is not None:
        return "api_key", key.id, key.name
    user = getattr(principal, "user", None)
    if user is not None:
        return "user", user.id, user.email
    return "system", "", ""


def audit(
    db: Session,
    principal: Any,
    action: str,
    target_type: str = "",
    target_id: str = "",
    data: dict[str, Any] | None = None,
    *,
    org_id: str | None = None,
) -> AuditEvent:
    """Append one audit event. `org_id` defaults to the principal's organization."""
    if org_id is None and principal is not None:
        org = getattr(principal, "org", None)
        org_id = org.id if org is not None else None
    actor_type, actor_id, actor_label = _actor(principal)
    info = request_info()
    ev = AuditEvent(
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label[:320],
        action=action,
        target_type=target_type,
        target_id=str(target_id)[:80],
        ip=info.ip,
        user_agent=info.user_agent,
        data=_scrub(data or {}),
    )
    db.add(ev)
    return ev


def event_view(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "at": e.at.isoformat(),
        "actor": {"type": e.actor_type, "id": e.actor_id, "label": e.actor_label},
        "action": e.action,
        "target": {"type": e.target_type, "id": e.target_id},
        "ip": e.ip,
        "user_agent": e.user_agent,
        "data": e.data,
    }


def query(
    org_id: str,
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[AuditEvent]]:
    """Newest first. `action` ending in "." or "*" matches a prefix (e.g. "user.")."""
    q = select(AuditEvent).where(AuditEvent.org_id == org_id)
    if actor:
        q = q.where((AuditEvent.actor_id == actor) | (AuditEvent.actor_label == actor))
    if action:
        if action.endswith(("*", ".")):
            q = q.where(AuditEvent.action.startswith(action.rstrip("*"), autoescape=True))
        else:
            q = q.where(AuditEvent.action == action)
    if since:
        q = q.where(AuditEvent.at >= since)
    if until:
        q = q.where(AuditEvent.at < until)
    return q.order_by(AuditEvent.at.desc(), AuditEvent.id.desc())


CSV_COLUMNS = (
    "at",
    "actor_type",
    "actor_id",
    "actor_label",
    "action",
    "target_type",
    "target_id",
    "ip",
    "user_agent",
    "data",
)


def to_csv(events: Iterable[AuditEvent]) -> str:
    import json

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for e in events:
        row = [
            e.at.isoformat(),
            e.actor_type,
            e.actor_id,
            e.actor_label,
            e.action,
            e.target_type,
            e.target_id,
            e.ip,
            e.user_agent,
            json.dumps(e.data, sort_keys=True, ensure_ascii=False),
        ]
        # CSV injection guard: a cell starting with = + - @ is opened as a formula by spreadsheets.
        w.writerow([f"'{c}" if c[:1] in ("=", "+", "-", "@") else c for c in row])
    return buf.getvalue()
