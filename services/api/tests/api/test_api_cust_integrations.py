"""Webhooks over HTTP: validation, secret shown once, job.delivered delivered (mock transport)."""

from __future__ import annotations

import httpx
from api_helpers import client, register
from sqlalchemy import select
from test_api_cust_helpers import drain, order

from arbiter import webhooks
from arbiter.models import WebhookDelivery


def test_webhook_created_and_job_delivered_sent(db, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(handler))
    c = client()
    h = register(c)
    bad = c.post(
        "/v1/webhooks", headers=h, json={"url": "https://hooks.example.com/a", "events": ["job.nope"]}
    )
    assert bad.status_code == 422
    bad = c.post("/v1/webhooks", headers=h, json={"url": "ftp://example.com/a", "events": ["job.delivered"]})
    assert bad.status_code == 422

    r = c.post(
        "/v1/webhooks", headers=h, json={"url": "https://hooks.example.com/a", "events": ["job.delivered"]}
    )
    assert r.status_code == 201, r.text
    hook = r.json()
    assert len(hook["secret"]) == 48 and hook["active"] is True
    listed = c.get("/v1/webhooks", headers=h).json()["items"]
    assert listed[0]["id"] == hook["id"] and "secret" not in listed[0]

    prj = order(c, h)
    drain()
    db.expire_all()
    deliveries = db.execute(select(WebhookDelivery)).scalars().all()
    assert [d.event for d in deliveries] == ["job.delivered"]
    assert deliveries[0].status == "delivered"
    assert deliveries[0].payload["data"]["job_id"] == prj["jobs"][0]["id"]
    assert seen and seen[0].headers["Arbiter-Signature"].startswith("t=")

    assert c.delete(f"/v1/webhooks/{hook['id']}", headers=h).status_code == 204
    assert c.get("/v1/webhooks", headers=h).json()["items"] == []
    other = register(c, email="o@example.com", org="Other")
    assert c.delete(f"/v1/webhooks/{hook['id']}", headers=other).status_code == 404


def test_webhook_url_rules_outside_dev(db, monkeypatch):
    from arbiter.config import get_settings

    c = client()
    h = register(c)
    monkeypatch.setattr(get_settings(), "env", "prod")
    for url in (
        "http://hooks.example.com/a",
        "https://localhost/a",
        "https://10.0.0.5/a",
        "https://169.254.169.254/x",
    ):
        r = c.post("/v1/webhooks", headers=h, json={"url": url, "events": ["job.failed"]})
        assert r.status_code == 422, url
    r = c.post(
        "/v1/webhooks", headers=h, json={"url": "https://hooks.example.com/a", "events": ["job.failed"]}
    )
    assert r.status_code == 201
