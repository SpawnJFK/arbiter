"""Paddle Billing (API v1) adapter. Paddle is the merchant of record (D-051).

Endpoints used (base https://api.paddle.com, sandbox https://sandbox-api.paddle.com,
`Authorization: Bearer <api key>`):

    POST /customers                               {email, name, custom_data}
    POST /transactions                            checkout: items + customer_id + custom_data,
                                                  response data.checkout.url (our /checkout/paddle
                                                  page + ?_ptxn=..., which opens Paddle.js)
    POST /customers/{id}/portal-sessions          {subscription_ids} -> data.urls.general.overview
    POST /subscriptions/{id}/cancel               {effective_from: next_billing_period|immediately}
    POST /subscriptions/{id}/charge               one-time charge (overage) with custom line items
    GET  /transactions/{id}/invoice               data.url, a short-lived PDF link

Items: a plan with a Paddle price id for "interval:CUR" (plan.provider_prices["paddle"]) is
sold by that id; otherwise a non-catalog price is sent (unit_price in the lowest
denomination as a string, billing_cycle for recurring, product {name, tax_category saas}).

Webhooks: header `Paddle-Signature: ts=<unix>;h1=<hex>` where h1 = HMAC-SHA256(secret,
"<ts>:<raw body>"). More than one h1 may be present while a secret is rotated. Events used:
subscription.created|updated|activated|canceled|past_due|paused|resumed|trialing,
transaction.completed, transaction.payment_failed, adjustment.created|updated (refunds).

Paddle has no metered billing: overage is sent as a one-time charge at period close
(report_usage returns False). Paddle has no Idempotency-Key header; period close is made
idempotent on our side (one overage invoice record per org and period, D-053).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from arbiter.billing.providers.base import (
    ChargeLine,
    ChargeResult,
    CheckoutRequest,
    CheckoutResult,
    CreditCheckoutRequest,
    InvalidSignature,
    PaymentRecord,
    ProviderError,
    ProviderEvent,
    ProviderNotConfigured,
    RefundRecord,
    SubscriptionUpdate,
    from_minor,
    http_client,
    parse_time,
    to_minor,
)
from arbiter.config import get_settings

BASE_URLS = {"sandbox": "https://sandbox-api.paddle.com", "production": "https://api.paddle.com"}
# Paddle SDKs default to 5 s; we allow 300 s of clock skew because a replay inside the window is
# harmless: billing_events stores each event_id once (D-051).
SIGNATURE_TOLERANCE_S = 300
SUBSCRIPTION_STATUS = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "paused": "paused",
    "canceled": "canceled",
}


class PaddleProvider:
    name = "paddle"

    def __init__(
        self, api_key: str | None = None, webhook_secret: str | None = None, environment: str | None = None
    ) -> None:
        s = get_settings()
        self.api_key = s.paddle_api_key if api_key is None else api_key
        self.webhook_secret = s.paddle_webhook_secret if webhook_secret is None else webhook_secret
        self.base_url = BASE_URLS[environment or s.paddle_environment]
        # Our page that loads Paddle.js and opens the overlay for ?_ptxn=<transaction id>.
        # Its domain must be approved in Paddle (Checkout settings).
        self.checkout_page = f"{s.web_base_url.rstrip('/')}/checkout/paddle"

    # ------------------------------------------------------------ plumbing

    def configured(self) -> bool:
        return bool(self.api_key and self.webhook_secret)

    def _client(self) -> httpx.Client:
        if not self.api_key:
            raise ProviderNotConfigured("Paddle is not configured (ARBITER_PADDLE_API_KEY)")
        return http_client(
            self.base_url, {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            with self._client() as c:
                resp = c.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"paddle: network error: {e}") from e
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("detail", "")
            except ValueError:
                detail = resp.text[:200]
            raise ProviderError(f"paddle: HTTP {resp.status_code}: {detail}"[:500])
        try:
            return resp.json().get("data") or {}
        except ValueError as e:
            raise ProviderError("paddle: response is not JSON") from e

    # ------------------------------------------------------------ customers and checkout

    def ensure_customer(self, *, org_id: str, name: str, email: str, existing_id: str | None) -> str | None:
        if existing_id:
            return existing_id
        data = self._call(
            "POST", "/customers", {"email": email, "name": name, "custom_data": {"org_id": org_id}}
        )
        return str(data["id"])

    @staticmethod
    def _non_catalog(
        name: str,
        description: str,
        amount: Decimal,
        currency: str,
        *,
        interval: str | None,
        custom_data: dict[str, str],
    ) -> dict[str, Any]:
        price: dict[str, Any] = {
            "name": name[:50],  # Paddle limits: name 1-50, description 2-200
            "description": description[:200],
            "unit_price": {"amount": to_minor(amount, currency), "currency_code": currency.upper()},
            "product": {"name": name[:200], "tax_category": "saas"},
            "custom_data": custom_data,
        }
        if interval:
            price["billing_cycle"] = {"interval": interval, "frequency": 1}
        return price

    def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        custom = {
            "org_id": req.org_id,
            "kind": "subscription",
            "plan": req.plan_key,
            "seats": str(req.seats),
            "interval": req.interval,
        }
        items: list[dict[str, Any]] = []
        base_id = req.provider_price_ids.get(f"{req.interval}:{req.currency}")
        if base_id:
            items.append({"price_id": base_id, "quantity": 1})
        else:
            items.append(
                {
                    "quantity": 1,
                    "price": self._non_catalog(
                        f"{req.plan_name} plan",
                        f"{req.plan_name} plan, billed every {req.interval}",
                        req.base_price,
                        req.currency,
                        interval=req.interval,
                        custom_data={"plan": req.plan_key, "line": "base"},
                    ),
                }
            )
        if req.extra_seats > 0 and req.seat_price > 0:
            seat_id = req.provider_price_ids.get(f"seat:{req.interval}:{req.currency}")
            if seat_id:
                items.append({"price_id": seat_id, "quantity": req.extra_seats})
            else:
                items.append(
                    {
                        "quantity": req.extra_seats,
                        "price": self._non_catalog(
                            f"{req.plan_name} extra seat",
                            "Additional seat",
                            req.seat_price,
                            req.currency,
                            interval=req.interval,
                            custom_data={"plan": req.plan_key, "line": "seat"},
                        ),
                    }
                )
        body: dict[str, Any] = {
            "items": items,
            "currency_code": req.currency.upper(),
            "collection_mode": "automatic",
            "custom_data": custom,
            "checkout": {"url": self.checkout_page},
        }
        if req.customer_id:
            body["customer_id"] = req.customer_id
        data = self._call("POST", "/transactions", body)
        url = (data.get("checkout") or {}).get("url")
        if not url:
            raise ProviderError(
                "paddle: no checkout URL (set a default payment link in Paddle checkout settings)"
            )
        return CheckoutResult(url=url, provider_ref=data.get("id"), customer_id=data.get("customer_id"))

    def create_credit_checkout(self, req: CreditCheckoutRequest) -> CheckoutResult:
        custom = {"org_id": req.org_id, "kind": "credit_pack", "pack": req.pack_key}
        body: dict[str, Any] = {
            "items": [
                {
                    "quantity": 1,
                    "price": self._non_catalog(
                        f"Prepaid credit: {req.pack_name}",
                        f"{req.credit_amount} {req.currency} of prepaid usage credit",
                        req.price,
                        req.currency,
                        interval=None,
                        custom_data={"pack": req.pack_key, "line": "credit_pack"},
                    ),
                }
            ],
            "currency_code": req.currency.upper(),
            "collection_mode": "automatic",
            "custom_data": custom,
            "checkout": {"url": self.checkout_page},
        }
        if req.customer_id:
            body["customer_id"] = req.customer_id
        data = self._call("POST", "/transactions", body)
        url = (data.get("checkout") or {}).get("url")
        if not url:
            raise ProviderError(
                "paddle: no checkout URL (set a default payment link in Paddle checkout settings)"
            )
        return CheckoutResult(url=url, provider_ref=data.get("id"), customer_id=data.get("customer_id"))

    def customer_portal_url(self, *, customer_id: str, subscription_id: str | None, return_url: str) -> str:
        body = {"subscription_ids": [subscription_id] if subscription_id else []}
        data = self._call("POST", f"/customers/{customer_id}/portal-sessions", body)
        url = ((data.get("urls") or {}).get("general") or {}).get("overview")
        if not url:
            raise ProviderError("paddle: portal session has no URL")
        return str(url)

    def cancel(self, *, subscription_id: str, immediately: bool = False) -> None:
        self._call(
            "POST",
            f"/subscriptions/{subscription_id}/cancel",
            {"effective_from": "immediately" if immediately else "next_billing_period"},
        )

    def add_charge(
        self,
        *,
        subscription_id: str | None,
        customer_id: str | None,
        lines: list[ChargeLine],
        currency: str,
        idempotency_key: str,
        custom_data: dict[str, str],
    ) -> ChargeResult:
        if not subscription_id:
            raise ProviderError("paddle: a one-time charge needs an active subscription")
        items = []
        for ln in lines:
            # Paddle quantities are integers: send the line total as one unit.
            items.append(
                {
                    "quantity": 1,
                    "price": self._non_catalog(
                        ln.description[:150],
                        f"{ln.description} ({ln.quantity} x {ln.unit_amount})"[:250],
                        ln.amount,
                        currency,
                        interval=None,
                        custom_data={**custom_data, "key": idempotency_key},
                    ),
                }
            )
        self._call(
            "POST",
            f"/subscriptions/{subscription_id}/charge",
            {"effective_from": "immediately", "items": items},
        )
        return ChargeResult(provider_ref=f"{subscription_id}:{idempotency_key}"[:120], status="scheduled")

    def report_usage(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
        unit: str,
        quantity: Decimal,
        idempotency_key: str,
    ) -> bool:
        return False  # no meters at Paddle; overage goes out as a one-time charge

    def invoice_document_url(self, provider_ref: str) -> str | None:
        data = self._call("GET", f"/transactions/{provider_ref}/invoice")
        return data.get("url")

    # ------------------------------------------------------------ webhooks

    def verify_signature(self, header: str, body: bytes, now: float | None = None) -> None:
        if not self.webhook_secret:
            raise ProviderNotConfigured("Paddle webhook secret is not configured")
        parts: dict[str, list[str]] = {}
        for piece in (header or "").split(";"):
            k, _, v = piece.strip().partition("=")
            if k and v:
                parts.setdefault(k, []).append(v)
        ts = (parts.get("ts") or [""])[0]
        if not ts.isdigit() or not parts.get("h1"):
            raise InvalidSignature("malformed Paddle-Signature header")
        if abs((now or time.time()) - int(ts)) > SIGNATURE_TOLERANCE_S:
            raise InvalidSignature("Paddle-Signature timestamp outside tolerance")
        expected = hmac.new(
            self.webhook_secret.encode(), f"{ts}:".encode() + body, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(expected, h) for h in parts["h1"]):
            raise InvalidSignature("Paddle-Signature does not match")

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        header = next((v for k, v in headers.items() if k.lower() == "paddle-signature"), "")
        self.verify_signature(header, body)
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise InvalidSignature("webhook body is not JSON") from e
        etype = str(payload.get("event_type") or "")
        data = payload.get("data") or {}
        ev = ProviderEvent(
            provider=self.name,
            event_id=str(payload.get("event_id") or payload.get("notification_id") or ""),
            event_type=etype,
            occurred_at=parse_time(payload.get("occurred_at")),
            raw=payload,
        )
        if not ev.event_id:
            raise InvalidSignature("webhook has no event_id")
        if etype.startswith("subscription."):
            ev.subscription = self._subscription(data)
        elif etype in ("transaction.completed", "transaction.payment_failed"):
            ev.payment = self._payment(data, "paid" if etype == "transaction.completed" else "failed")
        elif (
            etype in ("adjustment.created", "adjustment.updated")
            and data.get("action") == "refund"
            and data.get("status") == "approved"
        ):
            cur = str(data.get("currency_code") or "EUR")
            total = (data.get("totals") or {}).get("total", 0)
            ev.refund = RefundRecord(
                provider_ref=str(data.get("transaction_id") or ""),
                amount=from_minor(total, cur),
                currency=cur,
                refund_ref=str(data.get("id") or ""),
            )
        return ev

    @staticmethod
    def _subscription(d: dict[str, Any]) -> SubscriptionUpdate:
        custom = d.get("custom_data") or {}
        items = d.get("items") or []
        price_ids = [str((i.get("price") or {}).get("id")) for i in items if (i.get("price") or {}).get("id")]
        plan_key = custom.get("plan")
        interval = None
        for i in items:
            price = i.get("price") or {}
            plan_key = plan_key or (price.get("custom_data") or {}).get("plan")
            interval = interval or (price.get("billing_cycle") or {}).get("interval")
        period = d.get("current_billing_period") or {}
        scheduled = d.get("scheduled_change") or {}
        seats = custom.get("seats")
        return SubscriptionUpdate(
            provider_subscription_id=str(d.get("id")),
            status=SUBSCRIPTION_STATUS.get(str(d.get("status")), "incomplete"),
            provider_customer_id=d.get("customer_id"),
            org_id=custom.get("org_id"),
            plan_key=plan_key,
            price_ids=price_ids,
            interval=interval or custom.get("interval"),
            currency=d.get("currency_code"),
            seats=int(seats) if str(seats or "").isdigit() else None,
            period_start=parse_time(period.get("starts_at")),
            period_end=parse_time(period.get("ends_at")),
            cancel_at=parse_time(scheduled.get("effective_at"))
            if scheduled.get("action") == "cancel"
            else None,
            canceled_at=parse_time(d.get("canceled_at")),
        )

    @staticmethod
    def _payment(d: dict[str, Any], status: str) -> PaymentRecord:
        custom = d.get("custom_data") or {}
        cur = str(d.get("currency_code") or "EUR")
        totals = (d.get("details") or {}).get("totals") or {}
        item_custom: dict[str, Any] = {}
        lines = []
        for it in d.get("items") or []:
            price = it.get("price") or {}
            item_custom = {**(price.get("custom_data") or {}), **item_custom}
            lines.append(
                {
                    "type": "provider_item",
                    "description": price.get("description") or price.get("name") or "",
                    "quantity": str(it.get("quantity") or 1),
                    "price_id": price.get("id"),
                }
            )
        kind = custom.get("kind") or item_custom.get("kind")
        if not kind:
            if item_custom.get("pack"):
                kind = "credit_pack"
            elif d.get("subscription_id"):
                kind = "subscription"
            else:
                kind = "other"
        return PaymentRecord(
            provider_ref=str(d.get("id")),
            status=status,
            kind=kind,
            org_id=custom.get("org_id") or item_custom.get("org_id"),
            provider_customer_id=d.get("customer_id"),
            provider_subscription_id=d.get("subscription_id"),
            currency=cur,
            subtotal=from_minor(totals.get("subtotal"), cur),
            tax=from_minor(totals.get("tax"), cur),
            total=from_minor(totals.get("total"), cur),
            invoice_number=d.get("invoice_number"),
            pack_key=custom.get("pack") or item_custom.get("pack"),
            invoice_id=custom.get("invoice_id") or item_custom.get("invoice_id"),
            lines=lines,
        )
