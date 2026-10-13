"""Observability: healthz identity, exception capture, LLM usage events (no text), heartbeat,
queue metrics, tracing off by default."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from api_helpers import client, register
from fastapi.testclient import TestClient
from test_api_cust_helpers import order

from arbiter import observability
from arbiter.api import security
from arbiter.api.app import create_app
from arbiter.config import get_settings
from arbiter.contracts import EngineError, Usage
from arbiter.engines.mock import MockLlm
from arbiter.models import User


@pytest.fixture
def events():
    seen: list[tuple[str, dict]] = []
    observability.sink = lambda event, props: seen.append((event, props))
    try:
        yield seen
    finally:
        observability.sink = None


def test_healthz_reports_commit_and_version(monkeypatch):
    monkeypatch.setenv("ARBITER_GIT_SHA", "abc1234def")
    monkeypatch.setenv("ARBITER_VERSION", "1.2.3")
    get_settings.cache_clear()
    try:
        body = TestClient(create_app()).get("/healthz").json()
    finally:
        get_settings.cache_clear()
    assert body == {"ok": True, "commit": "abc1234def", "version": "1.2.3"}


def test_unhandled_error_is_captured_without_request_body(events):
    app = create_app()

    @app.post("/boom")
    def boom(payload: dict) -> dict:
        raise RuntimeError("kaput")

    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/boom", json={"secret": "segment text here"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert "kaput" not in r.text
    (event, props) = events[-1]
    assert event == "$exception" and props["$exception_type"] == "RuntimeError"
    assert props["component"] == "api" and props["$exception_list"][0]["stacktrace"]["frames"]
    assert "segment text here" not in repr(props)


class _StubLlm:
    name = "stub-llm"
    model = "stub-1"

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, **kwargs):
        return {"ok": True}, Usage(input_tokens=120, output_tokens=30, cost=Decimal("0.0042")), "stub-1"


def test_llm_wrapper_reports_usage_but_never_text(events):
    llm = observability.ObservedLlm(_StubLlm())
    with observability.org_context("org_123"):
        data, usage, model = llm.complete_json("SYSTEM PROMPT TEXT", "USER SEGMENT TEXT", schema_hint="x")
    assert data == {"ok": True} and model == "stub-1" and usage.input_tokens == 120
    event, props = events[-1]
    assert event == "$ai_generation" and props["$ai_provider"] == "stub-llm"
    assert props["$ai_model"] == "stub-1" and props["$ai_input_tokens"] == 120
    assert props["$ai_output_tokens"] == 30 and props["arbiter_cost"] == "0.0042"
    assert props["arbiter_call_kind"] == "llm" and props["$ai_latency"] >= 0
    assert props["org_hash"] == observability.hash_org("org_123") != "org_123"
    assert props["distinct_id"] == props["org_hash"]
    dumped = repr(props)
    assert "SEGMENT" not in dumped and "PROMPT" not in dumped and "org_123" not in dumped

    failing = observability.ObservedLlm(MockLlm())
    with pytest.raises(EngineError):
        failing.complete_json("SYSTEM PROMPT TEXT", "not json SEGMENT")
    event, props = events[-1]
    assert props["$ai_is_error"] is True and props["$ai_error"] == "EngineError"
    assert "SEGMENT" not in repr(props)


def test_llm_usage_disabled_without_key_or_sink():
    assert observability.sink is None and not observability.enabled()
    observability.llm_usage(
        engine="x",
        model="y",
        input_tokens=1,
        output_tokens=1,
        cost=Decimal("0"),
        currency="EUR",
        latency_s=0.1,
        kind="llm",
    )  # no client, no error


def test_worker_capture_on_failed_step_has_kind_and_org(db, events, monkeypatch):
    from arbiter.pipeline import orchestrator

    def broken(session, job_id):
        raise RuntimeError("step exploded")

    monkeypatch.setitem(orchestrator.HANDLERS, "job.translate", broken)
    c = client()
    h = register(c)
    order(c, h, "auto")
    from arbiter.pipeline.worker import run_until_idle

    run_until_idle(max_items=20)
    caught = [p for e, p in events if e == "$exception" and p.get("work_kind") == "job.translate"]
    assert caught and caught[0]["component"] == "worker" and caught[0]["org_hash"]


def test_heartbeat_interval_and_failures():
    hits: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(str(req.url))
        return httpx.Response(200)

    now = [1000.0]
    hb = observability.Heartbeat(
        "https://uptime.example.com/hb/abc", 60, transport=httpx.MockTransport(handler), clock=lambda: now[0]
    )
    assert hb.maybe_beat() and not hb.maybe_beat()
    now[0] += 61
    assert hb.maybe_beat() and hits == ["https://uptime.example.com/hb/abc"] * 2

    def down(req):
        raise httpx.ConnectError("down")

    hb2 = observability.Heartbeat("https://x.example.com", 60, transport=httpx.MockTransport(down))
    assert hb2.maybe_beat() is False
    assert observability.Heartbeat.from_settings() is None  # unset in tests


def test_tracing_is_a_noop_without_endpoint():
    assert observability.setup_tracing("arbiter-api") is False


def test_queue_metrics_admin_only(db):
    c = client()
    h = register(c)
    order(c, h, "auto")
    assert c.get("/v1/admin/metrics/queue", headers=h).status_code == 403
    u = User(
        email="root@example.com", name="Root", password_hash=security.hash_password("x-123456"), role="admin"
    )
    db.add(u)
    db.commit()
    ha = {"Authorization": f"Bearer {security.issue_token(u.id, 'admin', None)}"}
    m = c.get("/v1/admin/metrics/queue", headers=ha).json()
    assert m["totals"]["ready"] >= 1 and m["due_now"] >= 1
    assert "job.prepare" in m["by_kind"] or m["by_kind"]
    assert m["oldest_due_age_seconds"] >= 0 and m["expired_leases"] == 0


def test_posthog_client_is_eu_privacy_mode_and_off_in_test():
    from arbiter.config import Settings

    assert observability._posthog(Settings(env="test", posthog_key="phc_test")) is None
    client_ = observability._posthog(Settings(env="dev", posthog_key="phc_test"))
    try:
        assert client_.privacy_mode is True and client_.host == "https://eu.i.posthog.com"
    finally:
        client_.shutdown()
        observability._client = None
        observability._client_key = None
