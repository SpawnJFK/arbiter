"""Agency OS: CRM, price lists, workflow templates, dashboards and the AI assistant.

The business layer an agency or localization team runs on (the part Plunet-like systems
cover). Every table carries org_id and every query on it is scoped by org (tenancy rule).
Money columns are Numeric; per-word rates inside a price list are decimal strings in JSON.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column, utcnow


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PriceList(Base):
    """Client price list. rates: [{source_lang?, target_lang?, tier, per_word: "0.08"}]."""

    __tablename__ = "price_lists"

    id: Mapped[str] = id_column("prl")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    rates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Contract keys: context, exact, fuzzy_95, fuzzy_85, fuzzy_75, new, repetition (decimal strings).
    tm_weights: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    minimum_charge: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class WorkflowTemplate(Base):
    """A reusable pipeline definition. Jobs freeze a snapshot of it (job.workflow)."""

    __tablename__ = "workflow_templates"

    id: Mapped[str] = id_column("wfl")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tier: Mapped[str] = mapped_column(String(20))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    preset_key: Mapped[str | None] = mapped_column(String(40), nullable=True)  # built-in presets
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class CrmAccount(Base):
    __tablename__ = "crm_accounts"
    __table_args__ = (Index("ix_crm_accounts_org_name", "org_id", "name"),)

    id: Mapped[str] = id_column("acc")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="client")  # client | prospect
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived
    industry: Mapped[str | None] = mapped_column(String(80), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    vat_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    default_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    workflow_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_templates.id"), nullable=True
    )
    price_list_id: Mapped[str | None] = mapped_column(ForeignKey("price_lists.id"), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class CrmContact(Base):
    __tablename__ = "crm_contacts"

    id: Mapped[str] = id_column("con")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("crm_accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_column()


class CrmDeal(Base):
    __tablename__ = "crm_deals"
    __table_args__ = (Index("ix_crm_deals_org_stage", "org_id", "stage"),)

    id: Mapped[str] = id_column("deal")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("crm_accounts.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    # lead | qualified | proposal | negotiation | won | lost
    stage: Mapped[str] = mapped_column(String(20), default="lead")
    expected_close: Mapped[date | None] = mapped_column(Date, nullable=True)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class CrmActivity(Base):
    __tablename__ = "crm_activities"

    id: Mapped[str] = id_column("act")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("crm_accounts.id", ondelete="CASCADE"), index=True)
    deal_id: Mapped[str | None] = mapped_column(
        ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20))  # note | call | email | meeting | task
    body: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Dashboard(Base):
    """widgets: [{id, type, metric, title?, size?}] (validated in arbiter.agency.dashboards)."""

    __tablename__ = "dashboards"

    id: Mapped[str] = id_column("dsh")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    widgets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class AssistantThread(Base):
    __tablename__ = "assistant_threads"

    id: Mapped[str] = id_column("ath")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class AssistantMessage(Base):
    """One turn. An assistant turn carries a plan (actions) that a human applies.

    applied: indices of plan actions already executed; results: index -> {id} of what each
    applied action created, so applying twice is a no-op and later actions can reference
    earlier ones ("@<index>").
    """

    __tablename__ = "assistant_messages"
    __table_args__ = (Index("ix_assistant_messages_thread", "thread_id", "created_at"),)

    id: Mapped[str] = id_column("amsg")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("assistant_threads.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    applied: Mapped[list[int]] = mapped_column(JSON, default=list)
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
