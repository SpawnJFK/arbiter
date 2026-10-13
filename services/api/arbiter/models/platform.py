"""Platform tables: custom roles, team invites, the audit log and per-org SSO (OpenID Connect).

The audit log is append-only like provenance: a database trigger rejects UPDATE and DELETE,
so the history of who changed what in an organization cannot be rewritten after the fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column, utcnow

AUDIT_APPEND_ONLY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_no_update ON audit_events;
CREATE TRIGGER audit_no_update
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_append_only();
"""


class Role(Base):
    """A custom role inside one organization. `base_role` (pm | client) decides which coarse
    route guards apply; `permissions` ("<area>.<action>" patterns) replace the built-in
    permission set of that base role for fine-grained checks."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    id: Mapped[str] = id_column("rol")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), default="")
    base_role: Mapped[str] = mapped_column(String(20), default="client")  # pm | client
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = created_at_column()


class UserInvite(Base):
    """One-time set-password token for an invited team member. Only the SHA-256 is stored."""

    __tablename__ = "user_invites"

    id: Mapped[str] = id_column("inv")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_org_at", "org_id", "at"),)

    id: Mapped[str] = id_column("aud")
    # No FK on purpose: the audit trail outlives deleted objects. Null = platform-level event.
    org_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(12))  # user | api_key | system
    actor_id: Mapped[str] = mapped_column(String(40), default="")
    actor_label: Mapped[str] = mapped_column(String(320), default="")  # email or key name
    action: Mapped[str] = mapped_column(String(60), index=True)  # e.g. org.updated, role.created
    target_type: Mapped[str] = mapped_column(String(40), default="")
    target_id: Mapped[str] = mapped_column(String(80), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(400), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = created_at_column()


class SsoConfig(Base):
    """OpenID Connect identity provider of one organization. The client secret is stored
    encrypted with ARBITER_SECRETS_KEY (arbiter.platform.secrets)."""

    __tablename__ = "sso_configs"

    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    issuer: Mapped[str] = mapped_column(String(500))
    client_id: Mapped[str] = mapped_column(String(300))
    client_secret_enc: Mapped[str] = mapped_column(Text, default="")
    default_role: Mapped[str] = mapped_column(String(20), default="client")  # pm | client
    default_role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id"), nullable=True)
    # When true, password login is refused for every member of the org (SSO only).
    enforce_sso: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SsoDomain(Base):
    """An email domain routed to an org's IdP. A domain belongs to one org at most and is used
    for SSO only after the org proved control of it (DNS TXT record or platform admin)."""

    __tablename__ = "sso_domains"

    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    verification_token: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class SsoState(Base):
    """One SSO login attempt: state, nonce and PKCE verifier, single use, short-lived."""

    __tablename__ = "sso_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    next_path: Mapped[str] = mapped_column(String(500), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
