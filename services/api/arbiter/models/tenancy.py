"""Organizations, users and API keys.

An Organization is a paying customer (a company localizing its product) or an agency
running the platform under its own brand (white-label, phase P08). Reviewers are users
with role "reviewer"; they do not belong to a customer organization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = id_column("org")
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="client")  # client | agency
    # A regulated vertical (medical devices, legal, finance...) can never use the tiers
    # without a human reviewer (rule R-SEG-12), whatever the client selects.
    regulated: Mapped[bool] = mapped_column(Boolean, default=False)
    vertical: Mapped[str] = mapped_column(String(60), default="software")
    plan: Mapped[str] = mapped_column(String(20), default="solo")  # solo | agency | platform
    default_tier: Mapped[str] = mapped_column(String(20), default="hybrid")
    # What happens when no reviewer is available before the deadline: wait | ai_fallback | partial.
    # Silent substitution of AI for a paid human review does not exist as an option.
    no_reviewer_policy: Mapped[str] = mapped_column(String(20), default="wait")
    # AI/LLM subprocessors are opt-in per organization (the Crowdin pattern).
    ai_subprocessors_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    data_retention_days: Mapped[int] = mapped_column(default=90)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at_column()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = id_column("usr")
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # admin | pm | client | reviewer
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("prefix"),)

    id: Mapped[str] = id_column("key")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in UI, used for lookup
    secret_hash: Mapped[str] = mapped_column(String(200))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = created_at_column()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
