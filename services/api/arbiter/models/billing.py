"""Subscription billing and payout rails (migration 0010, decisions D-072 and D-073).

Our database is the source of truth for plans, subscriptions, entitlements, credits and
usage. Payment providers (Paddle now, Stripe later, manual bank transfer) sit behind thin
adapters in arbiter.billing.providers and only report back through signed webhooks, which
are stored once in billing_events (idempotent processing).

Money columns are Numeric and read as Decimal. Prices inside JSON are decimal strings.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column, utcnow


class Plan(Base):
    """A sellable plan. Editable data (admin plans editor), seeded with starter plans.

    prices / seat_prices: {"month": {"EUR": "49.00", "USD": "55.00"}, "year": {...}}
    included:             {"word": "50000", "ai_unit": "500"} per billing month
    overage:              {"EUR": {"word": "0.0150", "ai_unit": "0.0400"}, ...}
    provider_prices:      {"paddle": {"month:EUR": "pri_..."}, "stripe": {...}}
    """

    __tablename__ = "plans"

    id: Mapped[str] = id_column("pln")
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    modules: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Paid add-ons the plan includes (platform.modules.ADDONS keys), written to
    # org.settings["addons"] by billing.entitlements (migration 0011).
    addons: Mapped[list[str]] = mapped_column(JSON, default=list)
    prices: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    seat_prices: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    included: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    overage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    seats_included: Mapped[int] = mapped_column(Integer, default=1)
    max_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval: Mapped[str] = mapped_column(String(10), default="month")  # default interval offered
    custom: Mapped[bool] = mapped_column(Boolean, default=False)  # priced by contract (contact us)
    public: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    provider_prices: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CreditPack(Base):
    """Prepaid credit pack: pay `price`, receive `credit_amount` of wallet credit (same currency)."""

    __tablename__ = "credit_packs"

    id: Mapped[str] = id_column("cpk")
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    valid_days: Mapped[int] = mapped_column(Integer, default=365)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at_column()


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = id_column("sub")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    plan_key: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(20))  # paddle | stripe | manual | admin
    provider_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    provider_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # incomplete | trialing | active | past_due | paused | canceled
    status: Mapped[str] = mapped_column(String(20), default="incomplete")
    interval: Mapped[str] = mapped_column(String(10), default="month")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    seats: Mapped[int] = mapped_column(Integer, default=1)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BillingCustomer(Base):
    """The org's customer record at a payment provider."""

    __tablename__ = "billing_customers"
    __table_args__ = (
        UniqueConstraint("org_id", "provider"),
        UniqueConstraint("provider", "provider_customer_id"),
    )

    id: Mapped[str] = id_column("bcu")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    provider: Mapped[str] = mapped_column(String(20))
    provider_customer_id: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = created_at_column()


class CreditLedgerEntry(Base):
    """Prepaid credit wallet movements, one row per lot movement.

    Lots are the `purchase`, `grant` rows (positive, with expires_at). `consumption`, `expiry`
    and `refund` rows are negative and point at the lot they draw from (lot_id). Every row
    is mirrored by a double-entry txn in ledger_entries (txn_id) on `org:<id>:credits`, so the
    wallet balance equals that ledger account balance.
    """

    __tablename__ = "credit_ledger"
    __table_args__ = (Index("ix_credit_ledger_org", "org_id", "created_at"),)

    id: Mapped[str] = id_column("crd")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(20))  # purchase | grant | consumption | expiry | refund
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 5))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    lot_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    txn_id: Mapped[str] = mapped_column(String(40))
    ref: Mapped[str] = mapped_column(String(120), default="")
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = created_at_column()


class BillingEvent(Base):
    """Every provider webhook, stored once (provider, event_id) before it is applied."""

    __tablename__ = "billing_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)

    id: Mapped[str] = id_column("bev")
    provider: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="received")  # processed | ignored | failed
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    received_at: Mapped[datetime] = created_at_column()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PayoutAccount(Base):
    """A payee's account on a payout rail and its onboarding status.

    payee_kind is "reviewer" (reviewer_profiles.id) or "vendor" (Agency OS vendors, later).
    status: pending (registration link issued, not finished) | active | rejected
    """

    __tablename__ = "payout_accounts"
    __table_args__ = (UniqueConstraint("payee_kind", "payee_id", "method"),)

    id: Mapped[str] = id_column("pac")
    payee_kind: Mapped[str] = mapped_column(String(20))
    payee_id: Mapped[str] = mapped_column(String(40), index=True)
    method: Mapped[str] = mapped_column(String(20))  # payoneer | paypal | sepa | wise
    status: Mapped[str] = mapped_column(String(20), default="pending")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider_payee_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onboarding_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PayoutBatch(Base):
    """A bank transfer file (SEPA pain.001, CSV or Wise batch CSV) for manual upload."""

    __tablename__ = "payout_batches"

    id: Mapped[str] = id_column("pbt")
    method: Mapped[str] = mapped_column(String(20))  # sepa | wise
    format: Mapped[str] = mapped_column(String(20))  # pain001 | csv | wise_csv
    payout_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    storage_key: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at_column()
