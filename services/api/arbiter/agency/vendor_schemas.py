"""Request bodies of the vendor management endpoints (module pm, pydantic v2).

The assistant validates its create_assignment and draft_quote actions with these models,
so a plan can only contain what a hand-made API request could.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from arbiter.agency.schemas import Tier

VendorKind = Literal["person", "company"]
VendorStatus = Literal["active", "inactive", "blocked"]
Service = Literal["translation", "review", "post-edit", "dtp"]
RateUnit = Literal["word", "hour", "page", "minimum"]
HumanStep = Literal["human_review", "second_review"]
Strategy = Literal["sequential", "broadcast"]
SERVICES: tuple[str, ...] = ("translation", "review", "post-edit", "dtp")
UNITS: tuple[str, ...] = ("word", "hour", "page", "minimum")
# The pipeline step a vendor does maps to the service whose rate applies by default.
STEP_SERVICE = {"human_review": "review", "second_review": "review"}


def _utc(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        return v.replace(tzinfo=UTC)
    return v


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PairIn(_In):
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    services: list[Service] = Field(default_factory=lambda: ["translation", "review"], min_length=1)


class VendorRateIn(_In):
    source_lang: str | None = Field(default=None, min_length=2, max_length=16)
    target_lang: str | None = Field(default=None, min_length=2, max_length=16)
    service: Service = "translation"
    unit: RateUnit = "word"
    rate: Decimal = Field(ge=0, max_digits=12, decimal_places=5)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class VendorIn(_In):
    name: str = Field(min_length=1, max_length=200)
    kind: VendorKind = "person"
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    status: VendorStatus = "active"
    pairs: list[PairIn] = Field(default_factory=list, max_length=200)
    domains: list[str] = Field(default_factory=list, max_length=50)
    rates: list[VendorRateIn] = Field(default_factory=list, max_length=500)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    rating: Decimal | None = Field(default=None, ge=0, le=5, max_digits=3, decimal_places=2)
    notes: str = Field(default="", max_length=20_000)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)
    payment_method: Literal["bank", "paypal", "wise", "other"] | None = None
    iban: str | None = Field(default=None, max_length=64)
    swift: str | None = Field(default=None, max_length=20)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    capacity_words_per_day: int = Field(default=2500, ge=0, le=1_000_000)
    working_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], max_length=7)
    timezone: str | None = Field(default=None, max_length=60)
    nda_signed: bool = False
    nda_signed_at: date | None = None

    @field_validator("working_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("working_days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(v))


class VendorPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: VendorKind | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    status: VendorStatus | None = None
    pairs: list[PairIn] | None = Field(default=None, max_length=200)
    domains: list[str] | None = Field(default=None, max_length=50)
    rates: list[VendorRateIn] | None = Field(default=None, max_length=500)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    rating: Decimal | None = Field(default=None, ge=0, le=5, max_digits=3, decimal_places=2)
    notes: str | None = Field(default=None, max_length=20_000)
    legal_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)
    payment_method: Literal["bank", "paypal", "wise", "other"] | None = None
    iban: str | None = Field(default=None, max_length=64)
    swift: str | None = Field(default=None, max_length=20)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    capacity_words_per_day: int | None = Field(default=None, ge=0, le=1_000_000)
    working_days: list[int] | None = Field(default=None, max_length=7)
    timezone: str | None = Field(default=None, max_length=60)
    nda_signed: bool | None = None
    nda_signed_at: date | None = None

    @field_validator("working_days")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and any(d < 0 or d > 6 for d in v):
            raise ValueError("working_days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(v)) if v is not None else None


class AbsenceIn(_In):
    start_date: date
    end_date: date
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _order(self) -> AbsenceIn:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class DocumentIn(_In):
    kind: Literal["nda", "contract", "certificate", "other"] = "nda"
    title: str = Field(min_length=1, max_length=200)
    signed: bool = False
    signed_at: date | None = None
    valid_until: date | None = None


class AssignmentIn(_In):
    """POST /jobs/{id}/assignments. mode marketplace puts the step back on the reviewer
    marketplace (the default route); vendor offers to vendor_ids in rank order; internal
    assigns an org user directly."""

    step: HumanStep = "human_review"
    mode: Literal["marketplace", "vendor", "internal"] = "vendor"
    vendor_ids: list[str] = Field(default_factory=list, max_length=10)
    user_id: str | None = Field(default=None, max_length=40)
    strategy: Strategy = "sequential"
    offer_timeout_minutes: int = Field(default=240, ge=5, le=7 * 24 * 60)
    due_at: datetime | None = None
    words: int | None = Field(default=None, ge=0, le=10_000_000)
    service: Service | None = None
    rate: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=5)
    unit: RateUnit | None = None
    quantity: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    note: str = Field(default="", max_length=5000)

    _due = field_validator("due_at")(_utc)

    @model_validator(mode="after")
    def _who(self) -> AssignmentIn:
        if self.mode == "vendor" and not self.vendor_ids:
            raise ValueError("mode vendor needs at least one vendor id")
        if self.mode == "vendor" and len(set(self.vendor_ids)) != len(self.vendor_ids):
            raise ValueError("vendor_ids must not repeat")
        if self.mode == "internal" and not self.user_id:
            raise ValueError("mode internal needs user_id")
        return self


class CreateAssignmentData(AssignmentIn):
    """The assistant's create_assignment action: the same body plus the job id."""

    job_id: str = Field(min_length=1, max_length=40)


class DraftQuoteData(_In):
    """The assistant's draft_quote action: a priced proposal for a client from its price list.
    Applied as a CRM deal in stage proposal (and a real quote when a file_id is given)."""

    account_id: str = Field(min_length=1, max_length=40)
    source_lang: str = Field(min_length=2, max_length=16)
    target_langs: list[str] = Field(min_length=1, max_length=20)
    words: int = Field(ge=1, le=10_000_000)
    tier: Tier = "full"
    file_id: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=300)


class VendorSubmitIn(_In):
    """The vendor workbench: one decision on one segment."""

    decision: Literal["accept", "edit"]
    target_tagged: str | None = Field(default=None, max_length=100_000)
    errors: list[dict[str, object]] | None = None
    comment: str = Field(default="", max_length=5000)


class AutoInvoiceIn(_In):
    vendor_id: str | None = Field(default=None, max_length=40)
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class InvoiceStatusIn(_In):
    note: str = Field(default="", max_length=2000)
