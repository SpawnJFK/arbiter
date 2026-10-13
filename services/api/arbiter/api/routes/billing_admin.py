"""Platform-operator billing: plans editor, org subscription overrides, credit grants, period
close, manual invoices, billing events, bank payout batches and payout confirmation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from arbiter.api.deps import DB, Admin, Paging, listing
from arbiter.api.routes.jobs import attachment
from arbiter.billing import catalog, credits, period_close, subscriptions
from arbiter.billing.invoices import invoice_view
from arbiter.billing.providers import provider_status
from arbiter.billing.usage import current_period
from arbiter.community import payout_batches, payouts
from arbiter.errors import Invalid, NotFound
from arbiter.models import BillingEvent, Invoice, Organization, PayoutBatch

router = APIRouter(prefix="/admin", tags=["admin-billing"])


def _org(db: Any, org_id: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFound("organization not found")
    return org


# ------------------------------------------------------------------ plans


@router.get("/plans")
def admin_plans(_: Admin, db: DB) -> dict[str, Any]:
    return {
        "items": [catalog.plan_view(p, admin=True) for p in catalog.list_plans(db, include_hidden=True)],
        "credit_packs": [catalog.pack_view(k) for k in catalog.list_packs(db)],
        "providers": provider_status(),
    }


class PlanIn(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    modules: list[str] = Field(default_factory=list, max_length=20)
    addons: list[str] = Field(default_factory=list, max_length=20)
    prices: dict[str, dict[str, str]] = Field(default_factory=dict)
    seat_prices: dict[str, dict[str, str]] = Field(default_factory=dict)
    included: dict[str, str] = Field(default_factory=dict)
    overage: dict[str, dict[str, str]] = Field(default_factory=dict)
    seats_included: int = Field(default=1, ge=0, le=100_000)
    max_seats: int | None = Field(default=None, ge=0, le=100_000)
    interval: Literal["month", "year"] = "month"
    custom: bool = False
    public: bool = True
    active: bool = True
    sort: int = Field(default=0, ge=0, le=100_000)
    provider_prices: dict[str, dict[str, str]] = Field(default_factory=dict)


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    modules: list[str] | None = Field(default=None, max_length=20)
    addons: list[str] | None = Field(default=None, max_length=20)
    prices: dict[str, dict[str, str]] | None = None
    seat_prices: dict[str, dict[str, str]] | None = None
    included: dict[str, str] | None = None
    overage: dict[str, dict[str, str]] | None = None
    seats_included: int | None = Field(default=None, ge=0, le=100_000)
    max_seats: int | None = Field(default=None, ge=0, le=100_000)
    interval: Literal["month", "year"] | None = None
    custom: bool | None = None
    public: bool | None = None
    active: bool | None = None
    sort: int | None = Field(default=None, ge=0, le=100_000)
    provider_prices: dict[str, dict[str, str]] | None = None


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, _: Admin, db: DB) -> dict[str, Any]:
    return catalog.plan_view(catalog.create_plan(db, body.model_dump()), admin=True)


@router.patch("/plans/{key}")
def update_plan(key: str, body: PlanPatch, _: Admin, db: DB) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    return catalog.plan_view(catalog.update_plan(db, key, data), admin=True)


# ------------------------------------------------------------------ org subscription and credits


@router.get("/orgs/{org_id}/subscription")
def org_subscription(org_id: str, _: Admin, db: DB) -> dict[str, Any]:
    return subscriptions.subscription_view(db, _org(db, org_id), admin=True)


class OverrideIn(BaseModel):
    plan: str | None = Field(default=None, max_length=40)
    status: Literal["incomplete", "trialing", "active", "past_due", "paused", "canceled"] | None = None
    seats: int | None = Field(default=None, ge=1, le=100_000)
    interval: Literal["month", "year"] | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period_end: datetime | None = None
    modules_add: list[str] | None = Field(default=None, max_length=20)
    modules_remove: list[str] | None = Field(default=None, max_length=20)
    addons_add: list[str] | None = Field(default=None, max_length=20)
    addons_remove: list[str] | None = Field(default=None, max_length=20)
    platform_fee_percent: str | None = Field(default=None, max_length=10)
    payment_terms_days: int | None = Field(default=None, ge=0, le=120)
    po_number: str | None = Field(default=None, max_length=60)
    provider: Literal["paddle", "stripe", "manual", ""] | None = None
    note: str = Field(default="", max_length=500)


@router.post("/orgs/{org_id}/subscription")
def override_subscription(org_id: str, body: OverrideIn, _: Admin, db: DB) -> dict[str, Any]:
    if body.period_end is not None and body.period_end.tzinfo is None:
        raise Invalid("period_end needs a timezone (ISO 8601 with offset)")
    return subscriptions.admin_override(db, _org(db, org_id), body.model_dump(exclude_unset=True))


class GrantIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    valid_days: int = Field(default=365, ge=1, le=3650)
    note: str = Field(default="", max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=100)


@router.post("/orgs/{org_id}/credits", status_code=201)
def grant_credits(org_id: str, body: GrantIn, _: Admin, db: DB) -> dict[str, Any]:
    org = _org(db, org_id)
    credits.add_lot(
        db,
        org.id,
        body.amount,
        kind="grant",
        idempotency_key=f"grant:{org.id}:{body.idempotency_key}",
        valid_days=body.valid_days,
        ref=body.note or "admin grant",
    )
    return credits.credits_view(db, org.id)


# ------------------------------------------------------------------ period close and invoices


class CloseIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    org_id: str | None = None


@router.post("/billing/close-period")
def close_period(body: CloseIn, _: Admin, db: DB) -> dict[str, Any]:
    if body.period >= current_period():
        raise Invalid("only a finished period can be closed")
    if body.org_id:
        return {
            "period": body.period,
            "orgs": [period_close.close_org_period(db, _org(db, body.org_id), body.period)],
        }
    return period_close.close_period(db, body.period)


@router.get("/invoices")
def admin_invoices(
    _: Admin,
    db: DB,
    pg: Paging,
    status: Literal["draft", "issued", "paid", "void", "refunded"] | None = Query(None),
) -> dict[str, Any]:
    stmt = select(Invoice).order_by(Invoice.created_at.desc(), Invoice.id.desc())
    if status:
        stmt = stmt.where(Invoice.status == status)
    rows = list(db.execute(stmt.offset(pg.offset).limit(pg.limit + 1)).scalars())
    return listing([{**invoice_view(i), "org_id": i.org_id} for i in rows], pg)


@router.post("/invoices/{invoice_id}/mark-paid")
def mark_paid(invoice_id: str, _: Admin, db: DB) -> dict[str, Any]:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("invoice not found")
    return invoice_view(subscriptions.invoice_paid(db, inv))


@router.get("/billing/events")
def billing_events(
    _: Admin,
    db: DB,
    pg: Paging,
    status: Literal["received", "processed", "ignored", "failed"] | None = Query(None),
) -> dict[str, Any]:
    stmt = select(BillingEvent).order_by(BillingEvent.received_at.desc(), BillingEvent.id.desc())
    if status:
        stmt = stmt.where(BillingEvent.status == status)
    rows = list(db.execute(stmt.offset(pg.offset).limit(pg.limit + 1)).scalars())
    items = [
        {
            "id": e.id,
            "provider": e.provider,
            "event_id": e.event_id,
            "event_type": e.event_type,
            "status": e.status,
            "error": e.error,
            "received_at": e.received_at.isoformat(),
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
        }
        for e in rows
    ]
    return listing(items, pg)


# ------------------------------------------------------------------ payout rails


class BatchIn(BaseModel):
    format: Literal["pain001", "csv", "wise_csv"]


@router.post("/payouts/bank-batch", status_code=201)
def bank_batch(body: BatchIn, _: Admin, db: DB) -> dict[str, Any]:
    return payout_batches.build_batch(db, body.format)


@router.get("/payout-batches")
def list_batches(_: Admin, db: DB, pg: Paging) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(PayoutBatch).order_by(PayoutBatch.created_at.desc()).offset(pg.offset).limit(pg.limit + 1)
        ).scalars()
    )
    return listing([payout_batches.batch_view(b) for b in rows], pg)


@router.get("/payout-batches/{batch_id}/file")
def batch_file(batch_id: str, _: Admin, db: DB) -> Response:
    data, media, name = payout_batches.batch_file(db, batch_id)
    return Response(data, media_type=media, headers={"Content-Disposition": attachment(name)})


@router.post("/payout-batches/{batch_id}/settle")
def settle_batch(batch_id: str, _: Admin, db: DB) -> dict[str, Any]:
    return payout_batches.settle_batch(db, batch_id)


class CompleteIn(BaseModel):
    ok: bool
    reason: str | None = Field(default=None, max_length=500)


@router.post("/payouts/{payout_id}/complete")
def complete_payout(payout_id: str, body: CompleteIn, _: Admin, db: DB) -> dict[str, Any]:
    return payout_batches.complete(db, payout_id, ok=body.ok, reason=body.reason)


@router.post("/payouts/refresh")
def refresh_payouts(_: Admin, db: DB) -> dict[str, Any]:
    from arbiter.api.routes.admin import payout_provider

    provider = payout_provider()
    return payouts.refresh_pending(db, provider)
