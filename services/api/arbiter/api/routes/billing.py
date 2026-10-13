"""Customer billing: plans, subscription, checkout, portal, credits, invoice documents (D-051).

Reads are open to every customer role; writes need the permission `billing.manage`
(pm and admin roles by default). GET /billing/plans is public: the pricing page renders it.

Provider webhooks are mounted WITHOUT the /v1 prefix (see `webhook_router` and app.py):
POST /webhooks/paddle and POST /webhooks/stripe, public, signature-checked, idempotent.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from arbiter.api.deps import DB, Customer, Principal, require_permission
from arbiter.api.routes.jobs import attachment
from arbiter.billing import catalog, credits, fees, subscriptions
from arbiter.billing.invoices import invoice_pdf
from arbiter.billing.providers import provider_for
from arbiter.db import session_factory
from arbiter.errors import Invalid, NotFound
from arbiter.models import Invoice, Organization

router = APIRouter(tags=["billing"])
webhook_router = APIRouter(tags=["billing-webhooks"])

BillingManager = Annotated[Principal, require_permission("billing.manage")]


def _email(p: Principal) -> str:
    if p.user is None or not p.user.email:
        raise Invalid("checkout needs a signed-in user (not an API key)")
    return p.user.email


@router.get("/billing/plans")
def plans(db: DB) -> dict[str, Any]:
    """Public catalog for the pricing page and the billing page."""
    default, maximum = fees.fee_bounds()
    items = [catalog.plan_view(p) for p in catalog.list_plans(db)]
    return {
        "items": items,
        "credit_packs": [catalog.pack_view(k) for k in catalog.list_packs(db)],
        "currencies": sorted({c for i in items for c in i["currencies"]}),
        "platform_fee": {"default_percent": str(default), "max_percent": str(maximum)},
    }


@router.get("/billing/subscription")
def subscription(p: Customer, db: DB) -> dict[str, Any]:
    org = p.org
    assert org is not None
    return subscriptions.subscription_view(db, org)


class CheckoutIn(BaseModel):
    plan: str = Field(min_length=1, max_length=40)
    seats: int | None = Field(default=None, ge=1, le=10_000)
    interval: Literal["month", "year"] = "month"
    currency: str | None = Field(default=None, min_length=3, max_length=3)


@router.post("/billing/checkout")
def checkout(body: CheckoutIn, p: BillingManager, db: DB) -> dict[str, Any]:
    org = p.org
    if org is None:
        raise Invalid("checkout needs an organization account")
    return subscriptions.start_checkout(
        db,
        org,
        _email(p),
        plan_key=body.plan,
        seats=body.seats,
        interval=body.interval,
        currency=body.currency,
    )


@router.post("/billing/portal")
def portal(p: BillingManager, db: DB) -> dict[str, Any]:
    org = p.org
    if org is None:
        raise Invalid("needs an organization account")
    return subscriptions.portal_url(db, org)


class CancelIn(BaseModel):
    immediately: bool = False


@router.post("/billing/subscription/cancel")
def cancel(body: CancelIn, p: BillingManager, db: DB) -> dict[str, Any]:
    org = p.org
    if org is None:
        raise Invalid("needs an organization account")
    subscriptions.cancel(db, org, immediately=body.immediately)
    return subscriptions.subscription_view(db, org)


@router.get("/billing/credits")
def credit_wallet(p: Customer, db: DB) -> dict[str, Any]:
    out = credits.credits_view(db, p.org_id)
    out["packs"] = [catalog.pack_view(k) for k in catalog.list_packs(db)]
    return out


class CreditCheckoutIn(BaseModel):
    pack: str = Field(min_length=1, max_length=40)


@router.post("/billing/credits/checkout")
def credit_checkout(body: CreditCheckoutIn, p: BillingManager, db: DB) -> dict[str, Any]:
    org = p.org
    if org is None:
        raise Invalid("needs an organization account")
    return subscriptions.start_credit_checkout(db, org, _email(p), pack_key=body.pack)


@router.get("/billing/invoices/{invoice_id}/document", response_model=None)
def invoice_document(invoice_id: str, p: Customer, db: DB) -> Response | dict[str, Any]:
    """Our invoice -> the PDF. A provider record -> {url} of a fresh provider document link."""
    inv = db.get(Invoice, invoice_id)
    if inv is None or inv.org_id != p.org_id:
        raise NotFound("invoice not found")
    if inv.provider == "internal":
        if inv.status not in ("issued", "paid"):
            raise NotFound("this invoice has no document yet")
        org = db.get(Organization, inv.org_id)
        assert org is not None
        return Response(
            invoice_pdf(inv, org),
            media_type="application/pdf",
            headers={"Content-Disposition": attachment(f"{inv.number}.pdf")},
        )
    url = inv.provider_url
    if inv.provider_ref and not url:
        url = provider_for(inv.provider, db).invoice_document_url(inv.provider_ref)
    if not url:
        raise NotFound("the provider has no document for this payment yet")
    return {"url": url, "provider": inv.provider}


# ------------------------------------------------------------------ provider webhooks (no /v1)


def _process(provider: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
    """One transaction: the event row (also a failed one) is committed with what it applied."""
    session = session_factory()()
    try:
        out = subscriptions.process_webhook(session, provider, headers, body)
        session.commit()
        return out
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def _webhook(provider: str, request: Request) -> JSONResponse:
    body = await request.body()
    out = await run_in_threadpool(_process, provider, dict(request.headers), body)
    return JSONResponse(out, status_code=200 if out.get("ok") else 500)


@webhook_router.post("/webhooks/paddle")
async def paddle_webhook(request: Request) -> JSONResponse:
    return await _webhook("paddle", request)


@webhook_router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> JSONResponse:
    return await _webhook("stripe", request)
