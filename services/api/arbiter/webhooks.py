"""Outgoing webhooks: signed, retried through the work queue, auto-disabled when dead.

Signature: header `Arbiter-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`.
Receivers dedupe on `event_id` because delivery is at-least-once.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
import orjson
from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.config import get_settings
from arbiter.errors import Invalid
from arbiter.models import Webhook, WebhookDelivery, new_id, utcnow
from arbiter.pipeline.queue import enqueue

EVENTS = ("job.delivered", "job.failed", "job.needs_attention", "quote.expired")

# Tests swap this for an httpx.MockTransport.
transport: httpx.BaseTransport | None = None


def check_url(url: str) -> str:
    """Webhook URLs: https outside dev/test, never localhost or a private/link-local IP literal."""
    url = url.strip()
    parts = urlsplit(url)
    lenient = get_settings().env in ("dev", "test")
    allowed = ("https", "http") if lenient else ("https",)
    if parts.scheme not in allowed or not parts.hostname:
        raise Invalid("webhook URL must be an https:// URL")
    if parts.username or parts.password:
        raise Invalid("webhook URL must not contain credentials")
    if not lenient:
        host = parts.hostname.lower()
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
            raise Invalid("webhook URL must be a public address")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and not ip.is_global:
            raise Invalid("webhook URL must be a public address")
    return url


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def emit(session: Session, org_id: str, event: str, data: dict[str, Any]) -> int:
    """Queue one delivery per active webhook subscribed to the event. Returns how many."""
    hooks = session.execute(
        select(Webhook).where(Webhook.org_id == org_id, Webhook.active.is_(True))
    ).scalars()
    n = 0
    event_id = new_id("evt")
    for hook in hooks:
        if event not in (hook.events or []):
            continue
        d = WebhookDelivery(
            webhook_id=hook.id,
            event=event,
            event_id=event_id,
            payload={"id": event_id, "type": event, "created_at": utcnow().isoformat(), "data": data},
        )
        session.add(d)
        session.flush()
        enqueue(session, "webhook.deliver", {"delivery_id": d.id}, idempotency_key=f"whd:{d.id}")
        n += 1
    return n


def deliver(session: Session, delivery_id: str) -> None:
    """One attempt. Raises on failure so the queue retries with backoff."""
    d = session.get(WebhookDelivery, delivery_id)
    if d is None or d.status == "delivered":
        return
    hook = session.get(Webhook, d.webhook_id)
    if hook is None or not hook.active:
        d.status = "failed"
        return
    settings = get_settings()
    body = orjson.dumps(d.payload)
    d.attempts += 1
    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            r = client.post(
                hook.url,
                content=body,
                headers={"Content-Type": "application/json", "Arbiter-Signature": sign(hook.secret, body)},
            )
        d.response_code = r.status_code
        ok = 200 <= r.status_code < 300
        err = None if ok else f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        ok, err = False, type(e).__name__
    if ok:
        d.status = "delivered"
        d.delivered_at = utcnow()
        hook.consecutive_failures = 0
        return
    d.last_error = err
    hook.consecutive_failures += 1
    if hook.consecutive_failures >= settings.webhook_disable_after_consecutive_failures:
        hook.active = False
        hook.disabled_reason = f"disabled after {hook.consecutive_failures} consecutive failures"
    if d.attempts >= settings.webhook_max_attempts:
        d.status = "failed"
        return
    raise RuntimeError(f"webhook delivery failed: {err}")
