"""Engine credential resolution (D-056).

Order for one call, per provider:

    1. the org's own key (BYOK, scope "org", enabled, newest first)
    2. a platform key stored in the database (scope "platform", enabled, newest first)
    3. the environment (ARBITER_<PROVIDER>_API_KEY etc.), the behaviour before this module

openai_compatible is different: every credential is its own engine (`compat:<id>`), because
an org may run several endpoints (a vLLM box, Mistral, a hosted fine-tune) side by side.

Secrets are decrypted only here, only when a client is built, and never leave the process.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from arbiter import crypto
from arbiter.config import Settings
from arbiter.models import EngineCredential

Source = Literal["org", "platform", "env"]


@dataclass(frozen=True)
class ResolvedCredential:
    provider: str
    secret: str
    config: dict[str, Any] = field(default_factory=dict)
    source: Source = "env"
    credential_id: str | None = None

    def secret_json(self) -> dict[str, Any]:
        try:
            value = json.loads(self.secret) if self.secret else {}
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}


def hint_for(provider: str, secret: str) -> str:
    """Last 4 characters of the part of the secret a human recognises."""
    if provider == "bedrock":
        try:
            return crypto.hint(str(json.loads(secret).get("secret_access_key", "")))
        except (ValueError, AttributeError):
            return crypto.hint(secret)
    if provider == "vertex":
        try:
            return crypto.hint(str(json.loads(secret).get("private_key_id", "")))
        except (ValueError, AttributeError):
            return ""
    return crypto.hint(secret)


def _env(provider: str, s: Settings) -> ResolvedCredential | None:
    simple = {
        "anthropic": (s.anthropic_api_key, {"model": s.anthropic_model}),
        "openai": (s.openai_api_key, {"model": s.openai_model}),
        "deepl": (s.deepl_api_key, {}),
        "google": (s.google_api_key, {}),
        "together": (s.together_api_key, {}),
        "fireworks": (s.fireworks_api_key, {"account_id": s.fireworks_account_id}),
    }
    if provider in simple:
        key, config = simple[provider]
        return ResolvedCredential(provider, key, config, "env") if key else None
    if provider == "bedrock":
        if not (s.aws_access_key_id and s.aws_secret_access_key):
            return None
        secret = json.dumps(
            {"access_key_id": s.aws_access_key_id, "secret_access_key": s.aws_secret_access_key}
        )
        return ResolvedCredential(
            provider, secret, {"model": s.bedrock_model, "aws_region": s.bedrock_region}, "env"
        )
    if provider == "vertex":
        if not s.vertex_service_account_json:
            return None
        config = {"model": s.vertex_model, "project": s.vertex_project, "location": s.vertex_location}
        return ResolvedCredential(provider, s.vertex_service_account_json, config, "env")
    return None


def _row(cred: EngineCredential, s: Settings | None) -> ResolvedCredential:
    source: Source = "org" if cred.scope == "org" else "platform"
    return ResolvedCredential(
        cred.provider, crypto.decrypt(cred.secret_encrypted, s), dict(cred.config or {}), source, cred.id
    )


def resolve(
    session: Session | None, org_id: str | None, provider: str, settings: Settings
) -> ResolvedCredential | None:
    if session is not None:
        q = select(EngineCredential).where(
            EngineCredential.provider == provider, EngineCredential.enabled.is_(True)
        )
        if org_id:
            q = q.where(
                or_(
                    (EngineCredential.scope == "org") & (EngineCredential.org_id == org_id),
                    EngineCredential.scope == "platform",
                )
            )
        else:
            q = q.where(EngineCredential.scope == "platform")
        rows = session.execute(q.order_by(EngineCredential.created_at.desc())).scalars().all()
        for scope in ("org", "platform"):
            for cred in rows:
                if cred.scope == scope:
                    return _row(cred, settings)
    return _env(provider, settings)


def by_id(
    session: Session, credential_id: str, org_id: str | None, settings: Settings
) -> ResolvedCredential | None:
    """A specific credential the org may use (its own or a platform one)."""
    cred = session.get(EngineCredential, credential_id)
    if cred is None or not cred.enabled:
        return None
    if cred.scope == "org" and cred.org_id != org_id:
        return None
    return _row(cred, settings)


def compat_credentials(session: Session, org_id: str | None) -> list[EngineCredential]:
    """Enabled openai_compatible credentials visible to the org (its own first)."""
    q = select(EngineCredential).where(
        EngineCredential.provider == "openai_compatible", EngineCredential.enabled.is_(True)
    )
    if org_id:
        q = q.where(
            or_(
                (EngineCredential.scope == "org") & (EngineCredential.org_id == org_id),
                EngineCredential.scope == "platform",
            )
        )
    else:
        q = q.where(EngineCredential.scope == "platform")
    rows = list(session.execute(q.order_by(EngineCredential.created_at)).scalars())
    return sorted(rows, key=lambda c: 0 if c.scope == "org" else 1)


def source_of(session: Session | None, org_id: str | None, provider: str, settings: Settings) -> str:
    """'org' | 'platform' | 'env' | 'none' without decrypting anything."""
    if session is not None:
        q = select(EngineCredential.scope, EngineCredential.org_id).where(
            EngineCredential.provider == provider, EngineCredential.enabled.is_(True)
        )
        scopes = {(sc, oid) for sc, oid in session.execute(q).all()}
        if org_id and ("org", org_id) in scopes:
            return "org"
        if any(sc == "platform" for sc, _ in scopes):
            return "platform"
    return "env" if _env(provider, settings) else "none"
