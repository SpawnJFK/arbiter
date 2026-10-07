"""Request bodies of the Agency OS endpoints (pydantic v2).

The assistant validates every proposed action's `data` with these same models, so a plan
can only contain what a hand-made API request could.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Tier = Literal["auto", "ai_review", "hybrid", "full"]
AccountKind = Literal["client", "prospect"]
DealStage = Literal["lead", "qualified", "proposal", "negotiation", "won", "lost"]
ActivityKind = Literal["note", "call", "email", "meeting", "task"]
StepKind = Literal[
    "tm",
    "mt",
    "translation_senate",
    "qe",
    "senate",
    "ai_review",
    "human_review",
    "second_review",
    "client_review",
    "delivery",
]
WidgetType = Literal["kpi", "bar", "line", "table", "pipeline"]
WidgetSize = Literal["s", "m", "l"]
TmWeightKey = Literal["context", "exact", "fuzzy_95", "fuzzy_85", "fuzzy_75", "new", "repetition"]

Money = Decimal  # pydantic parses "12.40", 12.4 and 12 alike; serialised back as a string


def _utc(v: datetime | None) -> datetime | None:
    """Naive times are read as UTC (the contract says times are ISO 8601 UTC)."""
    if v is not None and v.tzinfo is None:
        return v.replace(tzinfo=UTC)
    return v


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- CRM


class AccountIn(_In):
    name: str = Field(min_length=1, max_length=200)
    kind: AccountKind = "client"
    industry: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    vat_id: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    default_tier: Tier | None = None
    workflow_template_id: str | None = Field(default=None, max_length=40)
    price_list_id: str | None = Field(default=None, max_length=40)
    notes: str = Field(default="", max_length=20_000)


class AccountPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: AccountKind | None = None
    status: Literal["active", "archived"] | None = None
    industry: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    vat_id: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    default_tier: Tier | None = None
    workflow_template_id: str | None = Field(default=None, max_length=40)
    price_list_id: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=20_000)


class ContactIn(_In):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    role: str | None = Field(default=None, max_length=120)
    is_primary: bool = False


class ContactPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    role: str | None = Field(default=None, max_length=120)
    is_primary: bool | None = None


class DealIn(_In):
    account_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    value: Money = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    stage: DealStage = "lead"
    expected_close: date | None = None
    quote_id: str | None = Field(default=None, max_length=40)


class DealPatch(_In):
    stage: DealStage | None = None
    value: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    expected_close: date | None = None
    lost_reason: str | None = Field(default=None, max_length=500)


class ActivityIn(_In):
    account_id: str = Field(min_length=1, max_length=40)
    deal_id: str | None = Field(default=None, max_length=40)
    kind: ActivityKind
    body: str = Field(min_length=1, max_length=20_000)
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def due_utc(cls, v: datetime | None) -> datetime | None:
        return _utc(v)


class ActivityPatch(_In):
    done: bool | None = None
    body: str | None = Field(default=None, min_length=1, max_length=20_000)
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def due_utc(cls, v: datetime | None) -> datetime | None:
        return _utc(v)


# --------------------------------------------------------------------------- price lists


class RateIn(_In):
    source_lang: str | None = Field(default=None, min_length=2, max_length=16)
    target_lang: str | None = Field(default=None, min_length=2, max_length=16)
    tier: Tier
    per_word: Money = Field(ge=0, max_digits=10, decimal_places=5)


class PriceListIn(_In):
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    rates: list[RateIn] = Field(min_length=1, max_length=500)
    tm_weights: dict[TmWeightKey, Decimal] | None = None
    minimum_charge: Money | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class PriceListPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    rates: list[RateIn] | None = Field(default=None, min_length=1, max_length=500)
    tm_weights: dict[TmWeightKey, Decimal] | None = None
    minimum_charge: Money | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


# --------------------------------------------------------------------------- workflows


class StepIn(_In):
    kind: StepKind
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowIn(_In):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    content_type: str | None = Field(default=None, max_length=60)
    tier: Tier
    steps: list[StepIn] = Field(min_length=1, max_length=20)
    is_default: bool = False


class WorkflowPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    content_type: str | None = Field(default=None, max_length=60)
    tier: Tier | None = None
    steps: list[StepIn] | None = Field(default=None, min_length=1, max_length=20)
    is_default: bool | None = None


# --------------------------------------------------------------------------- dashboards


class WidgetIn(_In):
    id: str | None = Field(default=None, min_length=1, max_length=40)
    type: WidgetType
    metric: str = Field(min_length=1, max_length=60)
    title: str | None = Field(default=None, max_length=120)
    size: WidgetSize = "m"


class DashboardIn(_In):
    name: str = Field(min_length=1, max_length=200)
    widgets: list[WidgetIn] = Field(default_factory=list, max_length=40)


class DashboardPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    widgets: list[WidgetIn] | None = Field(default=None, max_length=40)
