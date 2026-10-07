"""Webhooks, usage and invoices.

Webhook URLs must be https outside dev/test, and may not point at localhost or a private
or link-local IP literal (the worker would otherwise call into our own network). The
signing secret is shown once, on create.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from arbiter import webhooks
from arbiter.api.deps import DB, PM, Customer, Paging, listing
from arbiter.api.routes.projects import idempotent_replay, idempotent_store
from arbiter.billing.invoices import list_invoices
from arbiter.billing.usage import usage_view
from arbiter.errors import Invalid, NotFound
from arbiter.models import Webhook

router = APIRouter(tags=["integrations"])

_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def webhook_view(h: Webhook, *, with_secret: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": h.id,
        "url": h.url,
        "events": list(h.events or []),
        "active": h.active,
        "disabled_reason": h.disabled_reason,
        "created_at": _iso(h.created_at),
    }
    if with_secret:
        out["secret"] = h.secret
    return out


_check_url = webhooks.check_url


class WebhookIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    events: list[str] = Field(min_length=1, max_length=20)


@router.get("/webhooks")
def list_webhooks(p: PM, db: DB) -> dict[str, Any]:
    rows = db.execute(
        select(Webhook).where(Webhook.org_id == p.org_id).order_by(Webhook.created_at, Webhook.id)
    ).scalars()
    return {"items": [webhook_view(h) for h in rows], "next_offset": None}


@router.post("/webhooks", status_code=201)
def create_webhook(
    body: WebhookIn, p: PM, db: DB, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    payload = body.model_dump(mode="json")
    replay = idempotent_replay(db, p, "webhooks", idempotency_key, payload)
    if replay is not None:
        return replay
    events = list(dict.fromkeys(e.strip() for e in body.events))
    unknown = [e for e in events if e not in webhooks.EVENTS]
    if unknown:
        raise Invalid(
            f"unknown event(s): {', '.join(unknown)}", {"allowed": list(webhooks.EVENTS), "unknown": unknown}
        )
    h = Webhook(org_id=p.org_id, url=_check_url(body.url), secret=secrets.token_hex(24), events=events)
    db.add(h)
    db.flush()
    out = webhook_view(h, with_secret=True)
    idempotent_store(db, p, "webhooks", idempotency_key, payload, 201, out)
    return JSONResponse(out, status_code=201)


@router.delete("/webhooks/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: str, p: PM, db: DB) -> Response:
    h = db.get(Webhook, webhook_id)
    if h is None or h.org_id != p.org_id:
        raise NotFound("webhook not found")
    db.delete(h)
    return Response(status_code=204)


@router.get("/usage")
def usage(p: Customer, db: DB, period: Annotated[str | None, Query()] = None) -> dict[str, Any]:
    if period is not None and not _PERIOD.match(period):
        raise Invalid("period must be YYYY-MM")
    return usage_view(db, p.org_id, period)


@router.get("/invoices")
def invoices(p: Customer, db: DB, pg: Paging) -> dict[str, Any]:
    rows = list_invoices(db, p.org_id)
    return listing(rows[pg.offset : pg.offset + pg.limit + 1], pg)
