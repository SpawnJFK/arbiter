"""Billing test fixtures: provider env, a recording httpx.MockTransport, signed webhook bodies.

Never a real network call: every provider request goes to the MockTransport handler.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from arbiter.billing.providers import base as provider_base
from arbiter.config import get_settings

PADDLE_SECRET = "pdl_ntfset_test_secret"
STRIPE_SECRET = "whsec_test_secret"


class Recorder:
    """MockTransport handler: answers from `routes` {(method, path): response or callable}."""

    def __init__(self, routes: dict[tuple[str, str], Any] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Any = None
        if request.content:
            ctype = request.headers.get("content-type", "")
            body = json.loads(request.content) if "json" in ctype else request.content.decode()
        self.calls.append((request.method, request.url.path, body))
        for (method, path), resp in self.routes.items():
            if request.method == method and (
                request.url.path == path or path.endswith("*") and request.url.path.startswith(path[:-1])
            ):
                if callable(resp):
                    resp = resp(request)
                if isinstance(resp, httpx.Response):
                    return resp
                status, payload = resp
                return httpx.Response(status, json=payload)
        return httpx.Response(
            404, json={"error": {"detail": f"no mock for {request.method} {request.url.path}"}}
        )

    def paths(self) -> list[str]:
        return [f"{m} {p}" for m, p, _ in self.calls]


@pytest.fixture
def mock_http() -> Iterator[Callable[[dict], Recorder]]:
    def install(routes: dict) -> Recorder:
        rec = Recorder(routes)
        provider_base.transport = httpx.MockTransport(rec)
        return rec

    yield install
    provider_base.transport = None


@pytest.fixture
def paddle_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ARBITER_PADDLE_API_KEY", "pdl_sdbx_apikey_test")
    monkeypatch.setenv("ARBITER_PADDLE_WEBHOOK_SECRET", PADDLE_SECRET)
    monkeypatch.setenv("ARBITER_BILLING_PROVIDER", "auto")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def stripe_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ARBITER_STRIPE_SECRET_KEY", "sk_test_key")
    monkeypatch.setenv("ARBITER_STRIPE_WEBHOOK_SECRET", STRIPE_SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def paddle_signed(
    payload: dict[str, Any], secret: str = PADDLE_SECRET, ts: int | None = None
) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    t = ts or int(time.time())
    h1 = hmac.new(secret.encode(), f"{t}:".encode() + body, hashlib.sha256).hexdigest()
    return body, {"Paddle-Signature": f"ts={t};h1={h1}", "Content-Type": "application/json"}


def stripe_signed(
    payload: dict[str, Any], secret: str = STRIPE_SECRET, ts: int | None = None
) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    t = ts or int(time.time())
    v1 = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {"Stripe-Signature": f"t={t},v1={v1}", "Content-Type": "application/json"}


def paddle_subscription_event(
    event_id: str,
    org_id: str,
    *,
    sub_id: str = "sub_01test",
    status: str = "active",
    plan: str = "team",
    event_type: str = "subscription.activated",
    customer: str = "ctm_01test",
    seats: str = "5",
    scheduled_cancel: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2030-01-01T10:00:00.000000Z",
        "notification_id": f"ntf_{event_id}",
        "data": {
            "id": sub_id,
            "status": status,
            "customer_id": customer,
            "currency_code": "EUR",
            "custom_data": {"org_id": org_id, "plan": plan, "seats": seats},
            "items": [
                {
                    "quantity": 1,
                    "price": {"id": "pri_01base", "billing_cycle": {"interval": "month", "frequency": 1}},
                }
            ],
            "current_billing_period": {
                "starts_at": "2030-01-01T00:00:00Z",
                "ends_at": "2030-02-01T00:00:00Z",
            },
            "scheduled_change": (
                {"action": "cancel", "effective_at": scheduled_cancel} if scheduled_cancel else None
            ),
        },
    }


def paddle_transaction_event(
    event_id: str,
    org_id: str,
    *,
    txn_id: str = "txn_01test",
    kind: str = "subscription",
    pack: str | None = None,
    total: str = "23900",
    tax: str = "3900",
    sub_id: str | None = "sub_01test",
    invoice_id: str | None = None,
) -> dict[str, Any]:
    custom: dict[str, Any] = {"org_id": org_id, "kind": kind}
    if pack:
        custom["pack"] = pack
    if invoice_id:
        custom["invoice_id"] = invoice_id
    return {
        "event_id": event_id,
        "event_type": "transaction.completed",
        "occurred_at": "2030-01-01T10:05:00Z",
        "data": {
            "id": txn_id,
            "status": "completed",
            "customer_id": "ctm_01test",
            "subscription_id": sub_id,
            "currency_code": "EUR",
            "invoice_number": "325-10001",
            "custom_data": custom,
            "items": [{"quantity": 1, "price": {"id": "pri_x", "description": "Team plan"}}],
            "details": {
                "totals": {
                    "subtotal": str(int(total) - int(tax)),
                    "tax": tax,
                    "total": total,
                }
            },
        },
    }
