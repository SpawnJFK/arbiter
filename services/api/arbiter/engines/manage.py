"""Credential, route and budget management shared by /v1/engines (org) and /v1/admin/engines
(platform). Routes stay thin; every rule is here.

Credentials: validated against the catalog, encrypted before the row is written, never
returned (only `secret_hint`, the last 4 characters). Changing the secret means sending a
new one; PATCH without `secret` keeps the stored value.
"""

from __future__ import annotations

import ipaddress
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter import crypto
from arbiter.config import get_settings
from arbiter.contracts import EngineError
from arbiter.engines import budgets, probe
from arbiter.engines.catalog import PROVIDERS
from arbiter.engines.credentials import _row, hint_for
from arbiter.engines.routing import PURPOSES
from arbiter.errors import Invalid, NotFound, ServiceError
from arbiter.models import EngineBudget, EngineCredential, EngineRoute, utcnow

REGIONS = ("eu", "us", "global")


class SecretsNotConfigured(ServiceError):
    code = "secrets_unavailable"
    status = 503


def _encrypt(value: str) -> str:
    try:
        return crypto.encrypt(value)
    except crypto.SecretsUnavailable as e:
        raise SecretsNotConfigured(str(e)) from e


# ------------------------------------------------------------------ credentials


def credential_view(c: EngineCredential) -> dict[str, Any]:
    return {
        "id": c.id,
        "scope": c.scope,
        "provider": c.provider,
        "label": c.label,
        "secret_hint": c.secret_hint,
        "config": c.config or {},
        "enabled": c.enabled,
        "engine": f"compat:{c.id}" if c.provider == "openai_compatible" else c.provider,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "last_tested_at": c.last_tested_at.isoformat() if c.last_tested_at else None,
        "last_test_ok": c.last_test_ok,
        "last_test_error": c.last_test_error,
    }


def check_endpoint(url: str, *, allow_private: bool) -> str:
    """OpenAI-compatible base URL. Org keys must point at a public https host (the API
    calls it from inside our network); the platform admin may use a private host (a
    self-hosted vLLM next to the API)."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    lenient = get_settings().env in ("dev", "test")
    if parts.scheme not in (("https", "http") if lenient or allow_private else ("https",)):
        raise Invalid("endpoint must be an https:// URL")
    if not parts.hostname or parts.username or parts.password:
        raise Invalid("endpoint must be a URL without credentials")
    if not allow_private and not lenient:
        host = parts.hostname.lower()
        if host == "localhost" or host.endswith((".localhost", ".internal", ".local")):
            raise Invalid("endpoint must be a public address")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and not ip.is_global:
            raise Invalid("endpoint must be a public address")
    return url


def _secret(provider: str, secret: dict[str, str] | str) -> str:
    fields = PROVIDERS[provider]["secret_fields"]
    if isinstance(secret, str):
        value = secret.strip()
    elif fields == ["api_key"]:
        value = str(secret.get("api_key", "")).strip()
    elif fields == ["service_account_json"]:
        value = str(secret.get("service_account_json", "")).strip()
    else:
        value = json.dumps({k: str(secret.get(k, "")).strip() for k in fields}, sort_keys=True)
    if provider == "vertex":
        try:
            sa = json.loads(value)
        except ValueError as e:
            raise Invalid("service account must be the JSON key file content") from e
        if not isinstance(sa, dict) or not sa.get("client_email") or not sa.get("private_key"):
            raise Invalid("service account JSON needs client_email and private_key")
    elif provider == "bedrock":
        keys = json.loads(value) if value.startswith("{") else {}
        if not keys.get("access_key_id") or not keys.get("secret_access_key"):
            raise Invalid("AWS access key id and secret access key are required")
    elif not value and provider != "openai_compatible":  # a self-hosted endpoint may have no key
        raise Invalid("secret is required")
    return value


def _config(provider: str, config: dict[str, Any], *, allow_private: bool) -> dict[str, Any]:
    allowed = set(PROVIDERS[provider]["config_fields"])
    unknown = set(config) - allowed
    if unknown:
        raise Invalid(f"unknown config fields for {provider}: {', '.join(sorted(unknown))}")
    out = {k: v for k, v in config.items() if v not in (None, "")}
    if provider == "openai_compatible":
        if not out.get("endpoint") or not out.get("model"):
            raise Invalid("an OpenAI-compatible endpoint needs endpoint and model")
        out["endpoint"] = check_endpoint(str(out["endpoint"]), allow_private=allow_private)
        out["region"] = str(out.get("region") or "global")
        if out["region"] not in REGIONS:
            raise Invalid("region must be eu, us or global")
        for k in ("price_in_per_m", "price_out_per_m"):
            if k in out:
                try:
                    out[k] = str(Decimal(str(out[k])))
                except InvalidOperation as e:
                    raise Invalid(f"{k} must be a decimal number") from e
    if provider == "vertex" and out.get("endpoint"):
        out["endpoint"] = check_endpoint(str(out["endpoint"]), allow_private=False)
    if provider == "vertex" and out.get("location") and not str(out["location"]).replace("-", "").isalnum():
        raise Invalid("location must be a Vertex location such as eu or europe-west4")
    return out


def create_credential(
    session: Session,
    *,
    scope: str,
    org_id: str | None,
    provider: str,
    label: str,
    secret: dict[str, str] | str,
    config: dict[str, Any],
    enabled: bool,
    actor: str | None,
) -> EngineCredential:
    if provider not in PROVIDERS:
        raise Invalid(f"unknown provider {provider!r}")
    allow_private = scope == "platform"
    value = _secret(provider, secret)
    clean = _config(provider, config, allow_private=allow_private)
    cred = EngineCredential(
        scope=scope,
        org_id=org_id if scope == "org" else None,
        provider=provider,
        label=label or PROVIDERS[provider]["name"],
        secret_encrypted=_encrypt(value),
        secret_hint=hint_for(provider, value),
        config=clean,
        enabled=enabled,
        created_by=actor,
    )
    session.add(cred)
    session.flush()
    return cred


def get_credential(session: Session, cred_id: str, *, scope: str, org_id: str | None) -> EngineCredential:
    cred = session.get(EngineCredential, cred_id)
    if cred is None or cred.scope != scope or (scope == "org" and cred.org_id != org_id):
        raise NotFound("engine credential not found")
    return cred


def update_credential(session: Session, cred: EngineCredential, data: dict[str, Any]) -> EngineCredential:
    if data.get("label") is not None:
        cred.label = str(data["label"])
    if data.get("enabled") is not None:
        cred.enabled = bool(data["enabled"])
    if data.get("config") is not None:
        cred.config = _config(cred.provider, dict(data["config"]), allow_private=cred.scope == "platform")
    if data.get("secret") is not None:
        value = _secret(cred.provider, data["secret"])
        cred.secret_encrypted = _encrypt(value)
        cred.secret_hint = hint_for(cred.provider, value)
        cred.last_test_ok = None
        cred.last_tested_at = None
        cred.last_test_error = None
    cred.updated_at = utcnow()
    return cred


def list_credentials(session: Session, *, scope: str, org_id: str | None) -> list[EngineCredential]:
    q = select(EngineCredential).where(EngineCredential.scope == scope)
    q = q.where(EngineCredential.org_id == org_id) if scope == "org" else q
    return list(session.execute(q.order_by(EngineCredential.created_at)).scalars())


def test_credential(session: Session, cred: EngineCredential) -> dict[str, Any]:
    settings = get_settings()
    try:
        detail = probe.run_probe(cred.provider, _row(cred, settings), settings)
        ok, error = True, None
    except (EngineError, crypto.SecretsUnavailable) as e:
        ok, error, detail = False, str(e)[:500], ""
    cred.last_tested_at = utcnow()
    cred.last_test_ok = ok
    cred.last_test_error = error
    return {"ok": ok, "error": error, "detail": detail, "credential": credential_view(cred)}


# ------------------------------------------------------------------ routes


def route_view(r: EngineRoute) -> dict[str, Any]:
    return {
        "id": r.id,
        "scope": "org" if r.org_id else "platform",
        "source_lang": r.source_lang,
        "target_lang": r.target_lang,
        "content_type": r.content_type,
        "purpose": r.purpose,
        "engines": list(r.engines or []),
        "fallback": r.fallback,
        "enabled": r.enabled,
        "note": r.note,
    }


def _clean_route(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    if "purpose" in out and out["purpose"] not in PURPOSES:
        raise Invalid("purpose must be mt, judge, senate or editor")
    if "engines" in out:
        engines = [str(e).strip() for e in out["engines"] or [] if str(e).strip()]
        if not engines:
            raise Invalid("a route needs at least one engine")
        if len(engines) != len(set(engines)):
            raise Invalid("an engine appears twice in the route")
        out["engines"] = engines
    for k in ("source_lang", "target_lang", "content_type"):
        if k in out:
            out[k] = (str(out[k]).strip() or None) if out[k] is not None else None
    return out


def create_route(session: Session, org_id: str | None, data: dict[str, Any]) -> EngineRoute:
    clean = _clean_route({"purpose": "mt", **data})
    if "engines" not in clean:
        raise Invalid("a route needs at least one engine")
    route = EngineRoute(org_id=org_id, **clean)
    session.add(route)
    session.flush()
    return route


def get_route(session: Session, route_id: str, org_id: str | None) -> EngineRoute:
    r = session.get(EngineRoute, route_id)
    if r is None or r.org_id != org_id:
        raise NotFound("route not found")
    return r


def update_route(r: EngineRoute, data: dict[str, Any]) -> EngineRoute:
    for k, v in _clean_route(data).items():
        setattr(r, k, v)
    r.updated_at = utcnow()
    return r


def list_routes(session: Session, org_id: str | None) -> list[EngineRoute]:
    q = select(EngineRoute)
    q = q.where(EngineRoute.org_id == org_id) if org_id else q.where(EngineRoute.org_id.is_(None))
    return list(session.execute(q.order_by(EngineRoute.purpose, EngineRoute.created_at)).scalars())


# ------------------------------------------------------------------ budgets


def budget_view(b: EngineBudget) -> dict[str, Any]:
    spent = budgets.spent_this_month(b)
    return {
        "id": b.id,
        "provider": b.provider,
        "monthly_cap": str(Decimal(b.monthly_cap).quantize(Decimal("0.01"))),
        "currency": b.currency,
        "period": budgets.current_period(),
        "spent": str(spent.quantize(Decimal("0.01"))),
        "remaining": str(max(Decimal(b.monthly_cap) - spent, Decimal("0")).quantize(Decimal("0.01"))),
        "exceeded": b.enabled and spent >= Decimal(b.monthly_cap),
        "enabled": b.enabled,
    }


def upsert_budget(
    session: Session, org_id: str, provider: str, monthly_cap: Decimal, enabled: bool
) -> EngineBudget:
    if monthly_cap < 0:
        raise Invalid("monthly_cap must not be negative")
    b = budgets.get(session, org_id, provider)
    if b is None:
        b = EngineBudget(
            org_id=org_id,
            provider=provider,
            monthly_cap=monthly_cap,
            currency=get_settings().currency,
            period=budgets.current_period(),
            spent=Decimal("0"),
            enabled=enabled,
        )
        session.add(b)
    else:
        b.monthly_cap = monthly_cap
        b.enabled = enabled
    session.flush()
    return b
