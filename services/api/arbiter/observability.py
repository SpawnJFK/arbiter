"""Observability: PostHog (errors + LLM usage), OpenTelemetry traces, worker heartbeat.

Every part is off unless its setting is present, and nothing here ever sends request
bodies, segment text, prompts or file content:

* PostHog (ARBITER_POSTHOG_KEY, EU host by default): `capture_exception()` for unhandled
  errors in the API and the worker (exception type, message and stack only), and
  `llm_usage()` for each model call (engine, model, tokens, cost, latency, hashed org id).
  The client runs in privacy mode so its own AI helpers never attach content either.
* OpenTelemetry (ARBITER_OTEL_ENDPOINT): OTLP/HTTP traces for FastAPI and SQLAlchemy.
  SQL statements are traced without parameter values.
* Heartbeat (ARBITER_HEARTBEAT_URL): the worker pings an uptime monitor every
  ARBITER_HEARTBEAT_INTERVAL_SECONDS while its loop is alive.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import httpx

from arbiter.config import Settings, get_settings

log = logging.getLogger("arbiter.observability")

# The org a unit of work belongs to (set by the worker per job, by the API per request).
current_org: contextvars.ContextVar[str | None] = contextvars.ContextVar("arbiter_org", default=None)

_client: Any = None
_client_key: str | None = None
# Tests replace the sink to see exactly what would be sent.
sink: Callable[[str, dict[str, Any]], None] | None = None


def hash_org(org_id: str | None) -> str | None:
    """Stable pseudonymous id for an org: PostHog never receives the raw id."""
    if not org_id:
        return None
    return hashlib.sha256(f"arbiter-org:{org_id}".encode()).hexdigest()[:16]


def _posthog(settings: Settings | None = None) -> Any:
    global _client, _client_key
    s = settings or get_settings()
    if not s.posthog_key or s.is_test:
        return None
    if _client is None or _client_key != s.posthog_key:
        from posthog import Posthog

        _client = Posthog(
            s.posthog_key,
            host=s.posthog_host,
            privacy_mode=True,
            disable_geoip=True,
            enable_exception_autocapture=False,
            capture_exception_code_variables=False,
        )
        _client_key = s.posthog_key
    return _client


def enabled() -> bool:
    return sink is not None or _posthog() is not None


@contextmanager
def org_context(org_id: str | None) -> Iterator[None]:
    token = current_org.set(org_id)
    try:
        yield
    finally:
        current_org.reset(token)


def _base_props(component: str) -> dict[str, Any]:
    s = get_settings()
    props: dict[str, Any] = {
        "component": component,
        "env": s.env,
        "release": s.version,
        "commit": s.git_sha,
        "$process_person_profile": False,
    }
    org = hash_org(current_org.get())
    if org:
        props["org_hash"] = org
        props["$groups"] = {"organization": org}
    return props


def _emit(event: str, distinct_id: str, props: dict[str, Any]) -> None:
    if sink is not None:
        sink(event, {"distinct_id": distinct_id, **props})
        return
    client = _posthog()
    if client is None:
        return
    try:
        client.capture(event, distinct_id=distinct_id, properties=props)
    except Exception:  # noqa: BLE001  (telemetry never breaks the product)
        log.debug("posthog capture failed", exc_info=True)


def capture_exception(exc: BaseException, component: str, extra: dict[str, Any] | None = None) -> None:
    """Report an unhandled error: type, message (truncated) and stack frames only."""
    if not enabled():
        return
    frames = traceback.extract_tb(exc.__traceback__)[-15:]
    props = _base_props(component)
    props.update(
        {
            "$exception_list": [
                {
                    "type": type(exc).__name__,
                    "value": str(exc)[:500],
                    "mechanism": {"handled": False, "type": "generic"},
                    "stacktrace": {
                        "type": "raw",
                        "frames": [
                            {
                                "filename": f.filename.rsplit("site-packages/", 1)[-1],
                                "function": f.name,
                                "lineno": f.lineno,
                                "in_app": "site-packages" not in f.filename,
                                "platform": "python",
                            }
                            for f in frames
                        ],
                    },
                }
            ],
            "$exception_type": type(exc).__name__,
            "$exception_message": str(exc)[:500],
        }
    )
    for k, v in (extra or {}).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            props[k] = v
    _emit("$exception", hash_org(current_org.get()) or f"server:{component}", props)


def llm_usage(
    *,
    engine: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: Decimal,
    currency: str,
    latency_s: float,
    kind: str,
    error: str | None = None,
) -> None:
    """One `$ai_generation` event per model call. Never includes prompt or output text."""
    if not enabled():
        return
    props = _base_props("engine")
    props.update(
        {
            "$ai_provider": engine,
            "$ai_model": model,
            "$ai_input_tokens": int(input_tokens),
            "$ai_output_tokens": int(output_tokens),
            "$ai_latency": round(float(latency_s), 4),
            "$ai_is_error": error is not None,
            "arbiter_call_kind": kind,  # llm | mt
            "arbiter_cost": str(cost),
            "arbiter_cost_currency": currency,
        }
    )
    if error:
        props["$ai_error"] = error[:300]
    _emit("$ai_generation", hash_org(current_org.get()) or "server:engine", props)


def shutdown() -> None:
    if _client is not None:
        try:
            _client.shutdown()
        except Exception:  # noqa: BLE001
            log.debug("posthog shutdown failed", exc_info=True)


# --------------------------------------------------------------------------- engine wrappers


class ObservedLlm:
    """LlmClient wrapper that reports usage after each call (no text)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = inner.name

    @property
    def inner(self) -> Any:
        return self._inner

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    def available(self) -> bool:
        return self._inner.available()

    def complete_json(self, system: str, user: str, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        try:
            data, usage, model = self._inner.complete_json(system, user, **kwargs)
        except Exception as e:
            llm_usage(
                engine=self.name,
                model=str(getattr(self._inner, "model", "") or ""),
                input_tokens=0,
                output_tokens=0,
                cost=Decimal("0"),
                currency=get_settings().currency,
                latency_s=time.perf_counter() - t0,
                kind="llm",
                error=type(e).__name__,
            )
            raise
        llm_usage(
            engine=self.name,
            model=str(model),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost=usage.cost,
            currency=get_settings().currency,
            latency_s=time.perf_counter() - t0,
            kind="llm",
        )
        return data, usage, model


class ObservedMt:
    """MtEngine wrapper: one usage event per batch (characters counted as input)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = inner.name
        self.supports_glossary = getattr(inner, "supports_glossary", False)

    @property
    def inner(self) -> Any:
        return self._inner

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    def available(self) -> bool:
        return self._inner.available()

    def translate(self, requests: list[Any]) -> list[Any]:
        t0 = time.perf_counter()
        results = self._inner.translate(requests)
        tokens_in = sum(r.usage.input_tokens or r.usage.characters for r in results)
        tokens_out = sum(r.usage.output_tokens for r in results)
        cost = sum((r.usage.cost for r in results), Decimal("0"))
        errors = [r.error for r in results if getattr(r, "error", None)]
        llm_usage(
            engine=self.name,
            model=str(getattr(self._inner, "model", "") or self.name),
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost=cost,
            currency=get_settings().currency,
            latency_s=time.perf_counter() - t0,
            kind="mt",
            error=errors[0] if errors else None,
        )
        return results


# --------------------------------------------------------------------------- tracing


_tracing_ready = False


def _otel_headers(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(","):
        k, sep, v = part.partition("=")
        if sep and k.strip():
            out[k.strip()] = v.strip()
    return out


def setup_tracing(service: str, app: Any | None = None, engine: Any | None = None) -> bool:
    """OTLP/HTTP tracing for FastAPI and SQLAlchemy. No-op (False) without ARBITER_OTEL_ENDPOINT."""
    global _tracing_ready
    s = get_settings()
    if not s.otel_endpoint or s.is_test:
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if not _tracing_ready:
        resource = Resource.create(
            {
                "service.name": s.otel_service_name or service,
                "service.version": s.version,
                "deployment.environment": s.env,
                "vcs.commit": s.git_sha,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=s.otel_endpoint.rstrip("/") + "/v1/traces", headers=_otel_headers(s.otel_headers)
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracing_ready = True
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=False)
    return True


# --------------------------------------------------------------------------- heartbeat


class Heartbeat:
    """Pings ARBITER_HEARTBEAT_URL at most every interval seconds. Failures only log."""

    def __init__(
        self,
        url: str,
        interval: float,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.interval = max(5.0, float(interval))
        self._transport = transport
        self._clock = clock
        self._last: float | None = None
        self.sent = 0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Heartbeat | None:
        s = settings or get_settings()
        if not s.heartbeat_url:
            return None
        return cls(s.heartbeat_url, s.heartbeat_interval_seconds)

    def maybe_beat(self) -> bool:
        now = self._clock()
        if self._last is not None and now - self._last < self.interval:
            return False
        self._last = now
        try:
            with httpx.Client(timeout=5.0, transport=self._transport) as c:
                c.get(self.url)
            self.sent += 1
            return True
        except httpx.HTTPError as e:
            log.warning("heartbeat ping failed: %s", type(e).__name__)
            return False
