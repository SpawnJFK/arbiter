"""Subscriptions, checkout, provider webhooks and admin overrides (D-072, D-074).

Flow with Paddle (merchant of record):
  1. POST /billing/checkout -> start_checkout: validates plan/interval/currency/seats, makes
     sure the org has a provider customer, asks the adapter for a hosted checkout URL.
     Nothing changes in our database except the customer link: access starts only when the
     provider confirms payment.
  2. Paddle sends subscription.* and transaction.completed webhooks -> process_webhook:
     stored once in billing_events (provider, event_id unique), then applied:
       subscription.*        upsert our Subscription, recompute entitlements
       transaction.completed record of the provider's invoice (invoices table, provider refs);
                             a credit pack purchase adds a credit lot
       adjustment (refund)   refunds unused credit of a refunded pack
     Replays of the same event are acknowledged and not applied again.
Flow with the manual provider: checkout issues OUR invoice and a Subscription in status
`incomplete`; POST /admin/invoices/{id}/mark-paid -> invoice_paid activates it for one
interval (or adds the credit lot).
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arbiter.billing import catalog, credits, entitlements, fees
from arbiter.billing.ledger import money
from arbiter.billing.providers import default_provider, provider_for
from arbiter.billing.providers.base import (
    BillingProvider,
    CheckoutRequest,
    CreditCheckoutRequest,
    PaymentRecord,
    ProviderEvent,
    RefundRecord,
    SubscriptionUpdate,
)
from arbiter.billing.usage import current_period
from arbiter.config import get_settings
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import (
    BillingCustomer,
    BillingEvent,
    Invoice,
    Organization,
    Plan,
    Subscription,
    UsageRecord,
    User,
    utcnow,
)

log = logging.getLogger("arbiter.billing")
STATUSES = ("incomplete", "trialing", "active", "past_due", "paused", "canceled")


def add_interval(start: datetime, interval: str) -> datetime:
    months = 12 if interval == "year" else 1
    m = start.month - 1 + months
    year, month = start.year + m // 12, m % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


# ------------------------------------------------------------------ customers


def customer_id(session: Session, org_id: str, provider: str) -> str | None:
    return session.execute(
        select(BillingCustomer.provider_customer_id).where(
            BillingCustomer.org_id == org_id, BillingCustomer.provider == provider
        )
    ).scalar_one_or_none()


def link_customer(session: Session, org_id: str, provider: str, provider_customer_id: str | None) -> None:
    if not provider_customer_id or customer_id(session, org_id, provider):
        return
    try:
        with session.begin_nested():
            session.add(
                BillingCustomer(org_id=org_id, provider=provider, provider_customer_id=provider_customer_id)
            )
            session.flush()
    except IntegrityError:
        log.warning("billing customer %s/%s already linked", provider, provider_customer_id)


def org_for_customer(session: Session, provider: str, provider_customer_id: str | None) -> str | None:
    if not provider_customer_id:
        return None
    return session.execute(
        select(BillingCustomer.org_id).where(
            BillingCustomer.provider == provider, BillingCustomer.provider_customer_id == provider_customer_id
        )
    ).scalar_one_or_none()


# ------------------------------------------------------------------ checkout


def _web(path: str) -> str:
    return f"{get_settings().web_base_url.rstrip('/')}{path}"


def start_checkout(
    session: Session,
    org: Organization,
    email: str,
    *,
    plan_key: str,
    seats: int | None,
    interval: str,
    currency: str | None,
    provider: BillingProvider | None = None,
) -> dict[str, Any]:
    plan = catalog.get_plan(session, plan_key)
    if plan.custom:
        raise Invalid("this plan is priced by contract: contact us", {"plan": plan.key, "contact": True})
    if interval not in catalog.INTERVALS:
        raise Invalid(f"interval must be one of {', '.join(catalog.INTERVALS)}")
    cur = (currency or get_settings().currency).upper()
    base = catalog.plan_price(plan, interval, cur)
    if base is None:
        raise Invalid(
            f"plan {plan.key} has no {interval} price in {cur}", {"currencies": plan_currencies(plan)}
        )
    n_seats = seats or plan.seats_included
    if n_seats < 1 or (plan.max_seats is not None and n_seats > plan.max_seats):
        raise Invalid(f"seats must be between 1 and {plan.max_seats or 'unlimited'}")
    current = entitlements.current_subscription(session, org.id)
    if current is not None and current.provider in ("paddle", "stripe") and current.plan_key == plan.key:
        raise Conflict("this plan is already active: manage it in the customer portal")
    prov = provider or default_provider(session, org)
    cust = prov.ensure_customer(
        org_id=org.id, name=org.name, email=email, existing_id=customer_id(session, org.id, prov.name)
    )
    link_customer(session, org.id, prov.name, cust)
    extra = max(0, n_seats - plan.seats_included)
    req = CheckoutRequest(
        org_id=org.id,
        org_name=org.name,
        email=email,
        plan_key=plan.key,
        plan_name=plan.name,
        interval=interval,
        currency=cur,
        seats=n_seats,
        extra_seats=extra,
        base_price=base,
        seat_price=catalog.seat_price(plan, interval, cur),
        provider_price_ids=dict((plan.provider_prices or {}).get(prov.name) or {}),
        customer_id=cust,
        success_url=_web("/app/settings/billing?checkout=success"),
        cancel_url=_web("/app/settings/billing?checkout=cancelled"),
    )
    res = prov.create_checkout(req)
    link_customer(session, org.id, prov.name, res.customer_id)
    if prov.name == "manual":
        sub = Subscription(
            org_id=org.id,
            plan_key=plan.key,
            provider="manual",
            status="incomplete",
            interval=interval,
            currency=cur,
            seats=n_seats,
            meta={"invoice_id": res.provider_ref},
        )
        session.add(sub)
        session.flush()
    return {"url": res.url, "provider": prov.name, "provider_ref": res.provider_ref}


def plan_currencies(plan: Plan) -> list[str]:
    return sorted({c for by in (plan.prices or {}).values() for c in by})


def start_credit_checkout(
    session: Session, org: Organization, email: str, *, pack_key: str, provider: BillingProvider | None = None
) -> dict[str, Any]:
    pack = catalog.get_pack(session, pack_key)
    prov = provider or default_provider(session, org)
    cust = prov.ensure_customer(
        org_id=org.id, name=org.name, email=email, existing_id=customer_id(session, org.id, prov.name)
    )
    link_customer(session, org.id, prov.name, cust)
    res = prov.create_credit_checkout(
        CreditCheckoutRequest(
            org_id=org.id,
            org_name=org.name,
            email=email,
            pack_key=pack.key,
            pack_name=pack.name,
            credit_amount=Decimal(pack.credit_amount),
            price=Decimal(pack.price),
            currency=pack.currency,
            customer_id=cust,
            success_url=_web("/app/settings/billing?credits=success"),
            cancel_url=_web("/app/settings/billing?credits=cancelled"),
        )
    )
    link_customer(session, org.id, prov.name, res.customer_id)
    return {"url": res.url, "provider": prov.name, "provider_ref": res.provider_ref}


def portal_url(session: Session, org: Organization) -> dict[str, Any]:
    sub = entitlements.current_subscription(session, org.id) or entitlements.latest_subscription(
        session, org.id
    )
    name = sub.provider if sub is not None and sub.provider in ("paddle", "stripe") else None
    if name is None:
        return {"url": _web("/app/settings/billing"), "provider": "manual"}
    prov = provider_for(name, session)
    cust = customer_id(session, org.id, name) or (sub.provider_customer_id if sub else None)
    if not cust:
        raise Invalid("no customer record at the payment provider yet")
    url = prov.customer_portal_url(
        customer_id=cust,
        subscription_id=sub.provider_subscription_id if sub else None,
        return_url=_web("/app/settings/billing"),
    )
    return {"url": url, "provider": name}


def cancel(session: Session, org: Organization, *, immediately: bool = False) -> Subscription:
    sub = entitlements.current_subscription(session, org.id)
    if sub is None:
        raise NotFound("no active subscription")
    if sub.provider in ("paddle", "stripe") and sub.provider_subscription_id:
        provider_for(sub.provider, session).cancel(
            subscription_id=sub.provider_subscription_id, immediately=immediately
        )
        # The provider confirms with a subscription webhook; record the request meanwhile.
        sub.meta = {**(sub.meta or {}), "cancel_requested_at": utcnow().isoformat()}
        if not immediately:
            sub.cancel_at = sub.current_period_end
    elif immediately or sub.current_period_end is None:
        sub.status = "canceled"
        sub.canceled_at = utcnow()
    else:
        sub.cancel_at = sub.current_period_end
    sub.updated_at = utcnow()
    session.flush()
    entitlements.refresh(session, org)
    return sub


# ------------------------------------------------------------------ webhooks


def _plan_for(session: Session, provider: str, upd: SubscriptionUpdate) -> str | None:
    if upd.plan_key and session.execute(select(Plan.id).where(Plan.key == upd.plan_key)).first():
        return upd.plan_key
    if upd.price_ids:
        for plan in session.execute(select(Plan)).scalars():
            ids = set(((plan.provider_prices or {}).get(provider) or {}).values())
            if ids & set(upd.price_ids):
                return plan.key
    return None


def apply_subscription_update(session: Session, provider: str, upd: SubscriptionUpdate) -> str:
    sub = session.execute(
        select(Subscription).where(Subscription.provider_subscription_id == upd.provider_subscription_id)
    ).scalar_one_or_none()
    org_id = (
        (sub.org_id if sub else None)
        or upd.org_id
        or org_for_customer(session, provider, upd.provider_customer_id)
    )
    org = session.get(Organization, org_id) if org_id else None
    if org is None:
        return "ignored: unknown organization"
    plan_key = _plan_for(session, provider, upd) or (sub.plan_key if sub else None)
    if plan_key is None:
        return "ignored: unknown plan"
    if sub is None:
        sub = Subscription(
            org_id=org.id,
            plan_key=plan_key,
            provider=provider,
            provider_subscription_id=upd.provider_subscription_id,
            status=upd.status,
            interval=upd.interval or "month",
            currency=(upd.currency or get_settings().currency).upper(),
            seats=upd.seats or 1,
            meta={},
        )
        session.add(sub)
    sub.plan_key = plan_key
    sub.status = upd.status if upd.status in STATUSES else "incomplete"
    sub.provider_customer_id = upd.provider_customer_id or sub.provider_customer_id
    if upd.interval:
        sub.interval = upd.interval
    if upd.currency:
        sub.currency = upd.currency.upper()
    if upd.seats:
        sub.seats = upd.seats
    sub.current_period_start = upd.period_start or sub.current_period_start
    sub.current_period_end = upd.period_end or sub.current_period_end
    sub.cancel_at = upd.cancel_at
    sub.canceled_at = upd.canceled_at or (
        utcnow() if sub.status == "canceled" and not sub.canceled_at else sub.canceled_at
    )
    sub.updated_at = utcnow()
    session.flush()
    link_customer(session, org.id, provider, upd.provider_customer_id)
    if sub.status in entitlements.ACTIVE_STATUSES:
        # A new paid subscription replaces a manual / admin one of the same org.
        for other in session.execute(
            select(Subscription).where(
                Subscription.org_id == org.id,
                Subscription.id != sub.id,
                Subscription.provider.in_(("manual", "admin")),
                Subscription.status.in_(entitlements.ACTIVE_STATUSES + ("incomplete",)),
            )
        ).scalars():
            other.status = "canceled"
            other.canceled_at = utcnow()
            other.updated_at = utcnow()
    entitlements.refresh(session, org)
    return "applied"


def _record_number(provider: str, ref: str) -> str:
    return f"{provider.upper()}-{ref}"[:40]


def record_payment(session: Session, provider: str, pay: PaymentRecord, occurred_at: datetime | None) -> str:
    org_id = pay.org_id or org_for_customer(session, provider, pay.provider_customer_id)
    if not org_id and pay.provider_subscription_id:
        org_id = session.execute(
            select(Subscription.org_id).where(
                Subscription.provider_subscription_id == pay.provider_subscription_id
            )
        ).scalar_one_or_none()
    org = session.get(Organization, org_id) if org_id else None
    if org is None:
        return "ignored: unknown organization"
    inv = None
    if pay.invoice_id:
        inv = session.get(Invoice, pay.invoice_id)
        if inv is not None and inv.org_id != org.id:
            inv = None
    if inv is None:
        inv = session.execute(
            select(Invoice).where(Invoice.provider == provider, Invoice.provider_ref == pay.provider_ref)
        ).scalar_one_or_none()
    when = occurred_at or utcnow()
    if inv is None:
        inv = Invoice(
            org_id=org.id,
            number=_record_number(provider, pay.provider_ref),
            period=when.strftime("%Y-%m"),
            lines=[],
            subtotal=pay.subtotal,
            tax=pay.tax,
            total=pay.total,
            currency=pay.currency,
            status="issued",
            issued_at=when,
            kind=pay.kind if pay.kind in ("subscription", "credit_pack", "overage") else "subscription",
            provider=provider,
        )
        session.add(inv)
    inv.provider = provider
    inv.provider_ref = pay.provider_ref
    inv.provider_invoice_number = pay.invoice_number or inv.provider_invoice_number
    inv.provider_url = pay.invoice_url or inv.provider_url
    if pay.lines:
        inv.lines = pay.lines + [
            {"type": "tax", "rate": "", "amount": money(pay.tax), "note": f"Tax charged by {provider}"}
        ]
    inv.subtotal, inv.tax, inv.total, inv.currency = pay.subtotal, pay.tax, pay.total, pay.currency
    if pay.status == "paid":
        inv.status = "paid"
        inv.paid_at = when
    elif inv.status != "paid":
        inv.status = "issued"
    session.flush()
    if pay.status == "paid" and pay.kind == "credit_pack" and pay.pack_key:
        pack = catalog.get_pack(session, pay.pack_key)
        credits.add_lot(
            session,
            org.id,
            Decimal(pack.credit_amount),
            kind="purchase",
            idempotency_key=f"credit:{provider}:{pay.provider_ref}",
            currency=pack.currency,
            valid_days=pack.valid_days,
            ref=pay.provider_ref,
        )
    if pay.status == "failed" and pay.provider_subscription_id:
        sub = session.execute(
            select(Subscription).where(Subscription.provider_subscription_id == pay.provider_subscription_id)
        ).scalar_one_or_none()
        if sub is not None and sub.status == "active":
            sub.status = "past_due"
            sub.updated_at = utcnow()
            entitlements.refresh(session, org)
    return "applied"


def record_refund(session: Session, provider: str, ref: RefundRecord) -> str:
    inv = session.execute(
        select(Invoice).where(Invoice.provider == provider, Invoice.provider_ref == ref.provider_ref)
    ).scalar_one_or_none()
    if inv is None:
        return "ignored: unknown transaction"
    if inv.kind == "credit_pack":
        lot = credits.find_lot_by_ref(session, inv.org_id, ref.provider_ref)
        if lot is not None:
            credits.refund_lot(
                session,
                lot,
                ref.amount,
                idempotency_key=f"refund:{provider}:{ref.refund_ref}",
                ref=ref.refund_ref,
            )
    if ref.amount >= Decimal(inv.total):
        inv.status = "refunded"
    session.flush()
    return "applied"


def process_webhook(session: Session, provider_name: str, headers: Any, body: bytes) -> dict[str, Any]:
    """Verify, store once, apply. Raises InvalidSignature (400) before anything is stored."""
    prov = provider_for(provider_name, session)
    ev: ProviderEvent = prov.parse_webhook(headers, body)
    existing = session.execute(
        select(BillingEvent).where(BillingEvent.provider == ev.provider, BillingEvent.event_id == ev.event_id)
    ).scalar_one_or_none()
    if existing is not None and existing.status in ("processed", "ignored"):
        return {"ok": True, "duplicate": True, "status": existing.status}
    row = existing
    if row is None:
        row = BillingEvent(
            provider=ev.provider, event_id=ev.event_id, event_type=ev.event_type, payload=ev.raw
        )
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            # A concurrent delivery of the same event won the insert.
            return {"ok": True, "duplicate": True, "status": "in_progress"}
    try:
        with session.begin_nested():
            if ev.subscription is not None:
                result = apply_subscription_update(session, ev.provider, ev.subscription)
            elif ev.payment is not None:
                result = record_payment(session, ev.provider, ev.payment, ev.occurred_at)
            elif ev.refund is not None:
                result = record_refund(session, ev.provider, ev.refund)
            else:
                result = "ignored: event type not used"
    except Exception as e:  # noqa: BLE001
        # The savepoint rolled the half-applied change back. The event row stays (status
        # failed, error) and the route answers 500, so the provider retries; a retry of a
        # failed event is applied again.
        row.status = "failed"
        row.error = str(e)[:1000]
        session.flush()
        log.exception("billing webhook %s/%s failed", ev.provider, ev.event_id)
        return {"ok": False, "duplicate": False, "status": "failed", "error": row.error}
    row.status = "processed" if result == "applied" else "ignored"
    row.error = None if result == "applied" else result
    row.processed_at = utcnow()
    session.flush()
    return {"ok": True, "duplicate": False, "status": row.status, "result": result}


# ------------------------------------------------------------------ manual provider


def invoice_paid(session: Session, inv: Invoice) -> Invoice:
    """Admin confirms a bank transfer for one of OUR invoices."""
    if inv.provider != "internal":
        raise Invalid("only our own invoices are marked paid here; provider invoices settle by webhook")
    if inv.status == "paid":
        return inv
    if inv.status not in ("issued", "draft"):
        raise Conflict(f"invoice is {inv.status}")
    now = utcnow()
    inv.status = "paid"
    inv.paid_at = now
    org = session.get(Organization, inv.org_id)
    assert org is not None
    for ln in inv.lines or []:
        if ln.get("type") == "credit_pack" and ln.get("pack"):
            pack = catalog.get_pack(session, ln["pack"])
            credits.add_lot(
                session,
                org.id,
                Decimal(pack.credit_amount),
                kind="purchase",
                idempotency_key=f"credit:internal:{inv.id}",
                currency=pack.currency,
                valid_days=pack.valid_days,
                ref=inv.id,
            )
    if inv.kind == "subscription":
        subs = session.execute(select(Subscription).where(Subscription.org_id == org.id)).scalars()
        sub = next((s for s in subs if (s.meta or {}).get("invoice_id") == inv.id), None)
        if sub is not None:
            start = sub.current_period_end if sub.status == "active" and sub.current_period_end else now
            sub.status = "active"
            sub.current_period_start = start
            sub.current_period_end = add_interval(start, sub.interval)
            sub.updated_at = now
            for other in session.execute(
                select(Subscription).where(
                    Subscription.org_id == org.id,
                    Subscription.id != sub.id,
                    Subscription.provider.in_(("manual", "admin")),
                    Subscription.status.in_(entitlements.ACTIVE_STATUSES),
                )
            ).scalars():
                other.status = "canceled"
                other.canceled_at = now
                other.updated_at = now
            session.flush()
            entitlements.refresh(session, org)
    session.flush()
    return inv


# ------------------------------------------------------------------ admin override


def admin_override(session: Session, org: Organization, data: dict[str, Any]) -> dict[str, Any]:
    """POST /admin/orgs/{id}/subscription. Contract deals, comps and corrections.

    plan (+ seats, status, interval, currency, period_end) creates or updates the org's
    `admin` subscription; modules_add / modules_remove set entitlement overrides;
    platform_fee_percent, payment_terms_days, po_number, provider change the org's billing
    settings. A provider (paddle/stripe) subscription is never edited here: change it at the
    provider, the webhook updates us.
    """
    now = utcnow()
    if data.get("plan"):
        plan = catalog.get_plan(session, data["plan"], active_only=False)
        sub = session.execute(
            select(Subscription)
            .where(Subscription.org_id == org.id, Subscription.provider == "admin")
            .order_by(Subscription.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if sub is None or sub.status == "canceled":
            sub = Subscription(
                org_id=org.id,
                plan_key=plan.key,
                provider="admin",
                status="active",
                interval=data.get("interval") or "month",
                currency=(data.get("currency") or get_settings().currency).upper(),
                seats=data.get("seats") or plan.seats_included,
                current_period_start=now,
                meta={},
            )
            session.add(sub)
        sub.plan_key = plan.key
        if data.get("seats"):
            sub.seats = int(data["seats"])
        if data.get("status"):
            if data["status"] not in STATUSES:
                raise Invalid(f"status must be one of {', '.join(STATUSES)}")
            sub.status = data["status"]
            if sub.status == "canceled":
                sub.canceled_at = now
        if data.get("interval"):
            sub.interval = data["interval"]
        if "period_end" in data:
            sub.current_period_end = data["period_end"]
        sub.meta = {**(sub.meta or {}), "note": str(data.get("note") or "")[:500], "set_at": now.isoformat()}
        sub.updated_at = now
        session.flush()
    elif data.get("status") == "canceled":
        for sub in session.execute(
            select(Subscription).where(
                Subscription.org_id == org.id,
                Subscription.provider.in_(("admin", "manual")),
                Subscription.status != "canceled",
            )
        ).scalars():
            sub.status = "canceled"
            sub.canceled_at = now
            sub.updated_at = now
    if "modules_add" in data or "modules_remove" in data:
        entitlements.set_overrides(org, data.get("modules_add"), data.get("modules_remove"))
    if data.get("platform_fee_percent") is not None:
        fees.set_platform_fee_percent(org, data["platform_fee_percent"])
    billing_patch: dict[str, Any] = {}
    if data.get("payment_terms_days") is not None:
        billing_patch["payment_terms_days"] = int(data["payment_terms_days"])
    if data.get("po_number") is not None:
        billing_patch["po_number"] = str(data["po_number"])[:60]
    if "provider" in data:
        if data["provider"] not in (None, "", "paddle", "stripe", "manual"):
            raise Invalid("provider must be paddle, stripe, manual or empty")
        billing_patch["provider"] = data["provider"] or None
    if billing_patch:
        settings = dict(org.settings or {})
        settings["billing"] = {**(settings.get("billing") or {}), **billing_patch}
        org.settings = settings
    session.flush()
    entitlements.refresh(session, org)
    return subscription_view(session, org, admin=True)


# ------------------------------------------------------------------ views


def sub_view(sub: Subscription | None) -> dict[str, Any] | None:
    if sub is None:
        return None
    return {
        "id": sub.id,
        "plan": sub.plan_key,
        "provider": sub.provider,
        "provider_subscription_id": sub.provider_subscription_id,
        "status": sub.status,
        "interval": sub.interval,
        "currency": sub.currency,
        "seats": sub.seats,
        "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "cancel_at": sub.cancel_at.isoformat() if sub.cancel_at else None,
        "canceled_at": sub.canceled_at.isoformat() if sub.canceled_at else None,
    }


def meters(session: Session, org_id: str, plan: Plan | None, period: str) -> list[dict[str, Any]]:
    rows = dict(
        session.execute(
            select(UsageRecord.unit, func.sum(UsageRecord.quantity))
            .where(UsageRecord.org_id == org_id, UsageRecord.period == period)
            .group_by(UsageRecord.unit)
        ).all()
    )
    out = []
    for unit in catalog.METERED_UNITS:
        used = Decimal(rows.get(unit) or 0)
        inc = catalog.included(plan, unit) if plan is not None else Decimal("0")
        out.append(
            {
                "unit": unit,
                "used": format(used.normalize(), "f") if used else "0",
                "included": format(inc.normalize(), "f") if inc else "0",
                "overage": format(max(Decimal("0"), used - inc).normalize(), "f")
                if plan is not None
                else "0",
            }
        )
    return out


def subscription_view(session: Session, org: Organization, *, admin: bool = False) -> dict[str, Any]:
    sub = entitlements.current_subscription(session, org.id)
    pending = session.execute(
        select(Subscription)
        .where(Subscription.org_id == org.id, Subscription.status == "incomplete")
        .order_by(Subscription.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    plan = session.execute(select(Plan).where(Plan.key == sub.plan_key)).scalar_one_or_none() if sub else None
    seats_used = session.execute(
        select(func.count(User.id)).where(User.org_id == org.id, User.is_active.is_(True))
    ).scalar_one()
    period = current_period()
    from arbiter.platform.modules import org_modules

    out: dict[str, Any] = {
        "subscription": sub_view(sub),
        "pending": sub_view(pending),
        "plan": catalog.plan_view(plan) if plan is not None else None,
        "modules": sorted(org_modules(org)),
        "seats_used": int(seats_used),
        "period": period,
        "meters": meters(session, org.id, plan, period),
        "platform_fee_percent": str(fees.platform_fee_percent(org)),
        "credits_balance": money(credits.balance(session, org.id)),
        "currency": sub.currency if sub else get_settings().currency,
        "provider": default_provider(session, org).name,
    }
    if admin:
        billing = (org.settings or {}).get("billing") or {}
        out["org_id"] = org.id
        out["overrides"] = entitlements.overrides(org)
        out["payment_terms_days"] = billing.get("payment_terms_days", 14)
        out["po_number"] = billing.get("po_number", "")
        out["provider_override"] = billing.get("provider")
        out["history"] = [
            sub_view(s)
            for s in session.execute(
                select(Subscription)
                .where(Subscription.org_id == org.id)
                .order_by(Subscription.created_at.desc())
            ).scalars()
        ]
    return out
