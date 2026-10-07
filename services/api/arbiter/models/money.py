"""Money: quotes, usage, invoices, reviewer payouts and the double-entry ledger.

All amounts are Decimal, never float. The ledger is the single source of truth for
reviewer balances: a payout is a ledger movement, not a column update.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = id_column("quo")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    file_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_lang: Mapped[str] = mapped_column(String(16))
    target_langs: Mapped[list[str]] = mapped_column(JSON)
    content_type: Mapped[str] = mapped_column(String(60), default="general")
    word_count: Mapped[int] = mapped_column(default=0)
    # Per tier: {"auto": {"price": "12.40", "est_auto_rate": 0.71, "eta_hours": 0.2}, ...}
    tiers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # TM bands, repetitions
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | accepted | expired
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_org_period", "org_id", "period"),)

    id: Mapped[str] = id_column("use")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    unit: Mapped[str] = mapped_column(String(20))  # word | ai_unit | review_decision | storage_gb
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0"))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = created_at_column()


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = id_column("inv")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    number: Mapped[str] = mapped_column(String(40), unique=True)
    period: Mapped[str] = mapped_column(String(7))
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | issued | paid | void
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[str] = id_column("pay")
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("reviewer_profiles.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    state: Mapped[str] = mapped_column(String(20), default="accrued")
    method: Mapped[str] = mapped_column(String(20), default="")
    provider_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # A payout is sent at most once, even if the worker retries after a crash.
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LedgerEntry(Base):
    """Double entry: every movement is two rows with opposite signs and the same txn_id.

    Accounts: reviewer:<id>:payable, platform:cash, platform:review_cost, client:<org>:receivable.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_ledger_account", "account", "created_at"),)

    id: Mapped[str] = id_column("led")
    txn_id: Mapped[str] = mapped_column(String(40), index=True)
    account: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 5))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    kind: Mapped[str] = mapped_column(String(30))  # review_pay | payout | adjustment | clawback
    ref: Mapped[str] = mapped_column(String(80), default="")  # task id, payout id...
    created_at: Mapped[datetime] = created_at_column()
