"""Engine credentials, routing rules, budgets and own models (migration 0006).

engine_credentials  provider keys stored encrypted (arbiter.platform.secrets). scope "platform"
                    (org_id NULL, set by the platform admin) or "org" (BYOK). The secret is
                    never returned after save; `secret_hint` holds the last 4 characters.
engine_routes       ordered engine lists per pair / content type / purpose. org_id NULL =
                    platform default. Precedence lives in arbiter.engines.routing.
engine_budgets      monthly cost cap per org and provider, with the running spend for the
                    current period (YYYY-MM, UTC). Checked before every engine call.
training_jobs       LoRA fine-tunes of open-weight models on one org's approved segments.
custom_models       an org's own model, served through an OpenAI-compatible endpoint and
                    registered as engine `custom:<id>`; it competes on the scoreboard.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column, utcnow


class EngineCredential(Base):
    __tablename__ = "engine_credentials"
    __table_args__ = (Index("ix_engine_credentials_scope_provider", "scope", "org_id", "provider"),)

    id: Mapped[str] = id_column("ecr")
    scope: Mapped[str] = mapped_column(String(10))  # platform | org
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120), default="")
    secret_encrypted: Mapped[str] = mapped_column(Text)
    secret_hint: Mapped[str] = mapped_column(String(12), default="")
    # model, region, endpoint (base_url), project, location, prices...: never secret.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class EngineRoute(Base):
    __tablename__ = "engine_routes"

    id: Mapped[str] = id_column("ert")
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # NULL = any. A rule matches when every non-NULL field equals the job's value.
    source_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    purpose: Mapped[str] = mapped_column(String(10), default="mt")  # mt | judge | senate | editor
    engines: Mapped[list[str]] = mapped_column(JSON, default=list)  # ordered engine names
    # True: after the listed engines the router may fall back to other available engines.
    fallback: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EngineBudget(Base):
    __tablename__ = "engine_budgets"
    __table_args__ = (UniqueConstraint("org_id", "provider"),)

    id: Mapped[str] = id_column("ebu")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    monthly_cap: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    period: Mapped[str] = mapped_column(String(7), default="")  # YYYY-MM the spend belongs to
    spent: Mapped[Decimal] = mapped_column(Numeric(16, 6), default=Decimal("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id: Mapped[str] = id_column("trn")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    domain: Mapped[str] = mapped_column(String(60), default="general")
    provider: Mapped[str] = mapped_column(String(40))  # together | fireworks | manual
    base_model: Mapped[str] = mapped_column(String(200))
    # created -> running -> evaluating -> ready; exported (manual); failed; cancelled.
    state: Mapped[str] = mapped_column(String(20), default="created", index=True)
    dataset_stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    train_storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    validation_storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    result_model_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(400), nullable=True)
    custom_model_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    polls: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomModel(Base):
    __tablename__ = "custom_models"

    id: Mapped[str] = id_column("cmd")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    training_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    source_lang: Mapped[str] = mapped_column(String(16))
    target_lang: Mapped[str] = mapped_column(String(16))
    domain: Mapped[str] = mapped_column(String(60), default="general")
    base_model: Mapped[str] = mapped_column(String(200), default="")
    provider_model_id: Mapped[str] = mapped_column(String(300))  # model name at the endpoint
    endpoint: Mapped[str] = mapped_column(String(400))  # OpenAI-compatible base URL
    # The key for the endpoint: an engine credential of this org (or platform) by id.
    credential_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    region: Mapped[str] = mapped_column(String(10), default="global")  # eu | us | global
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    eval_mean_qe: Mapped[float | None] = mapped_column(nullable=True)
    eval_segments: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at_column()
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def engine_name(self) -> str:
        return f"custom:{self.id}"
