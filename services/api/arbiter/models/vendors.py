"""Agency vendors (module pm): an agency's OWN external translators, reviewers and partner
agencies, their availability, the assignments of human steps to them, purchase orders and
vendor invoices.

This is separate from the platform reviewer marketplace (models/reviewers.py): a vendor
belongs to one organization and is paid by that organization, not through the platform
ledger. Every table carries org_id and every query on it is scoped by org (tenancy rule).
Money columns are Numeric; rates inside JSON are decimal strings.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Vendor(Base):
    """An agency's own linguist or partner company.

    pairs:  [{source_lang, target_lang, services: [translation|review|post-edit|dtp]}]
    rates:  [{source_lang?, target_lang?, service, unit (word|hour|page|minimum), rate: "0.06",
              currency: "EUR"}]
    working_days: weekdays the vendor works, 0 = Monday ... 6 = Sunday.
    capacity_words_per_day: what the vendor delivers on a working day (planner input).
    """

    __tablename__ = "vendors"
    __table_args__ = (Index("ix_vendors_org_name", "org_id", "name"),)

    id: Mapped[str] = id_column("vnd")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="person")  # person | company
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | inactive | blocked
    pairs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    rates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)  # 0.00 .. 5.00
    notes: Mapped[str] = mapped_column(Text, default="")
    # Tax and payment (needed on POs and for the accounting export).
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # bank | paypal | wise
    iban: Mapped[str | None] = mapped_column(String(64), nullable=True)
    swift: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    # Availability.
    capacity_words_per_day: Mapped[int] = mapped_column(Integer, default=2500)
    working_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])
    timezone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Documents.
    nda_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    nda_signed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class VendorAbsence(Base):
    """A period the vendor does not work (holiday, sick leave). Inclusive date range."""

    __tablename__ = "vendor_absences"

    id: Mapped[str] = id_column("vab")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = created_at_column()


class VendorDocument(Base):
    """A document on file for a vendor (NDA, contract, certificate). The file itself is optional."""

    __tablename__ = "vendor_documents"

    id: Mapped[str] = id_column("vdc")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="nda")  # nda | contract | certificate | other
    title: Mapped[str] = mapped_column(String(200))
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    signed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(400), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class VendorAssignment(Base):
    """Who does a human step (human_review | second_review) of a job.

    assignee_kind: vendor (own external vendor, offered and paid) | internal (a user of the org).
    An offer to a ranked list is one offer_group: rows share offer_group, rank orders them.
    status (arbiter.domain.states "assignment"): pending (later in a sequential list) ->
    offered -> accepted -> in_progress -> delivered -> approved -> invoiced; off ramps:
    declined, expired (offer timeout), withdrawn (someone else won or the PM changed the
    route), cancelled. The vendor works through a no-login link signed with token_nonce.
    """

    __tablename__ = "vendor_assignments"
    __table_args__ = (
        Index("ix_vendor_assignments_job_step", "job_id", "step"),
        Index("ix_vendor_assignments_vendor_status", "vendor_id", "status"),
    )

    id: Mapped[str] = id_column("vas")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    step: Mapped[str] = mapped_column(String(30), default="human_review")
    service: Mapped[str] = mapped_column(String(20), default="review")
    assignee_kind: Mapped[str] = mapped_column(String(20), default="vendor")  # vendor | internal
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    offer_group: Mapped[str] = mapped_column(String(40), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    strategy: Mapped[str] = mapped_column(String(20), default="sequential")  # sequential | broadcast
    words: Mapped[int] = mapped_column(Integer, default=0)
    words_done: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(20), default="word")
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_timeout_minutes: Mapped[int] = mapped_column(Integer, default=240)
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_nonce: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # Notifications sent or logged: [{at, to, subject, channel: email|log}].
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = _updated_at()


class NumberSeries(Base):
    """Per-org, per-kind, per-year document counter (PO-2026-0001). Row-locked on use."""

    __tablename__ = "number_series"
    __table_args__ = (UniqueConstraint("org_id", "kind", "year"),)

    id: Mapped[str] = id_column("nsr")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # po | vinv
    year: Mapped[int] = mapped_column(Integer)
    last: Mapped[int] = mapped_column(Integer, default=0)


class PurchaseOrder(Base):
    """Generated when a vendor accepts an assignment. lines: [{description, quantity, unit,
    rate, amount}] with decimal strings. status: issued -> invoiced | cancelled."""

    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("org_id", "number"),)

    id: Mapped[str] = id_column("po")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    number: Mapped[str] = mapped_column(String(40))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("vendor_assignments.id"), unique=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(20), default="issued")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime] = created_at_column()
    vendor_invoice_id: Mapped[str | None] = mapped_column(String(40), nullable=True)


class VendorInvoice(Base):
    """A vendor's invoice to the agency: uploaded by the vendor (self-invoice) or generated
    from approved assignments. status: received -> approved -> paid, or rejected."""

    __tablename__ = "vendor_invoices"
    __table_args__ = (
        UniqueConstraint("org_id", "vendor_id", "number"),
        Index("ix_vendor_invoices_org_period", "org_id", "period"),
    )

    id: Mapped[str] = id_column("vin")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    number: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(20), default="auto")  # auto | upload
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    assignment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(20), default="received")
    filename: Mapped[str | None] = mapped_column(String(400), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_at: Mapped[datetime] = created_at_column()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
