"""Stripe adapter, same interface as Paddle. DISABLED unless configured (D-072).

Stripe becomes the second rail once a company exists in a Stripe-supported country. Until
then `configured()` is False and the registry never picks it.

API (https://api.stripe.com, form-encoded bodies, `Authorization: Bearer <secret key>`,
`Idempotency-Key` on every POST):

    POST /v1/customers                     email, name, metadata[org_id]
    POST /v1/checkout/sessions             mode=subscription|payment, line_items, metadata,
                                           subscription_data[metadata], success_url, cancel_url
    POST /v1/billing_portal/sessions       customer, return_url -> url
    POST /v1/subscriptions/{id}            cancel_at_period_end=true   (DELETE = cancel now)
    POST /v1/invoiceitems                  one-time charge added to the next invoice
    POST /v1/billing/meter_events          event_name, payload[stripe_customer_id], payload[value]
    GET  /v1/invoices/{id}                 invoice_pdf / hosted_invoice_url

Webhooks: `Stripe-Signature: t=<unix>,v1=<hex>`, v1 = HMAC-SHA256(secret, "<t>.<raw body>").
Events used: customer.subscription.created|updated|deleted, invoice.paid,
invoice.payment_failed, checkout.session.completed (credit packs), charge.refunded.
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

BASE_URL = "https://api.stripe.com"
SIGNATURE_TOLERANCE_S = 300
STATUS = {
    "active": "active",
    "trialing": "trialing",
    "past_due": "past_due",
    "unpaid": "past_due",
    "paused": "paused",
    "canceled": "canceled",
    "incomplete": "incomplete",
    "incomplete_expired": "canceled",
}


def _flatten(prefix: str, value: Any, out: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]" if prefix else str(k), v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out.append((prefix, "true" if value else "false"))
    elif value is not None:
        out.append((prefix, str(value)))


def form_encode(data: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    _flatten("", data, out)
    return out


class StripeProvider:
    name = "stripe"

    def __init__(self, secret_key: str | None = None, webhook_secret: str | None = None) -> None:
        s = get_settings()
        self.secret_key = s.stripe_secret_key if secret_key is None else secret_key
        self.webhook_secret = s.stripe_webhook_secret if webhook_secret is None else webhook_secret

    def configured(self) -> bool:
        return bool(self.secret_key and self.webhook_secret)

    def _call(
        self, method: str, path: str, data: dict[str, Any] | None = None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        if not self.secret_key:
            raise ProviderNotConfigured("Stripe is not configured (ARBITER_STRIPE_SECRET_KEY)")
        headers = {"Authorization": f"Bearer {self.secret_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:255]
        try:
            with http_client(BASE_URL, headers) as c:
                resp = c.request(method, path, data=dict(form_encode(data or {})) if data else None)
        except httpx.HTTPError as e:
            raise ProviderError(f"stripe: network error: {e}") from e
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message", "")
            except ValueError:
                msg = resp.text[:200]
            raise ProviderError(f"stripe: HTTP {resp.status_code}: {msg}"[:500])
        try:
            return resp.json()
        except ValueError as e:
            raise ProviderError("stripe: response is not JSON") from e

    def ensure_customer(self, *, org_id: str, name: str, email: str, existing_id: str | None) -> str | None:
        if existing_id:
            return existing_id
        data = self._call(
            "POST",
            "/v1/customers",
            {"email": email, "name": name, "metadata": {"org_id": org_id}},
            idempotency_key=f"customer:{org_id}",
        )
        return str(data["id"])

    def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        meta = {"org_id": req.org_id, "kind": "subscription", "plan": req.plan_key, "seats": str(req.seats)}
        line_items: list[dict[str, Any]] = []
        base_id = req.provider_price_ids.get(f"{req.interval}:{req.currency}")
        if base_id:
            line_items.append({"price": base_id, "quantity": 1})
        else:
            line_items.append(
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": req.currency.lower(),
                        "unit_amount": to_minor(req.base_price, req.currency),
                        "recurring": {"interval": req.interval},
                        "product_data": {"name": f"{req.plan_name} plan"},
                    },
                }
            )
        if req.extra_seats > 0 and req.seat_price > 0:
            line_items.append(
                {
                    "quantity": req.extra_seats,
                    "price_data": {
                        "currency": req.currency.lower(),
                        "unit_amount": to_minor(req.seat_price, req.currency),
                        "recurring": {"interval": req.interval},
                        "product_data": {"name": f"{req.plan_name} extra seat"},
                    },
                }
            )
        body: dict[str, Any] = {
            "mode": "subscription",
            "line_items": line_items,
            "client_reference_id": req.org_id,
            "metadata": meta,
            "subscription_data": {"metadata": meta},
            "success_url": req.success_url,
            "cancel_url": req.cancel_url,
        }
        if req.customer_id:
            body["customer"] = req.customer_id
        else:
            body["customer_email"] = req.email
        data = self._call(
            "POST", "/v1/checkout/sessions", body, idempotency_key=f"checkout:{req.org_id}:{time.time_ns()}"
        )
        return CheckoutResult(
            url=str(data["url"]), provider_ref=data.get("id"), customer_id=data.get("customer")
        )

    def create_credit_checkout(self, req: CreditCheckoutRequest) -> CheckoutResult:
        meta = {"org_id": req.org_id, "kind": "credit_pack", "pack": req.pack_key}
        body: dict[str, Any] = {
            "mode": "payment",
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": req.currency.lower(),
                        "unit_amount": to_minor(req.price, req.currency),
                        "product_data": {"name": f"Prepaid credit: {req.pack_name}"},
                    },
                }
            ],
            "client_reference_id": req.org_id,
            "metadata": meta,
            "payment_intent_data": {"metadata": meta},
            "success_url": req.success_url,
            "cancel_url": req.cancel_url,
        }
        if req.customer_id:
            body["customer"] = req.customer_id
        data = self._call(
            "POST", "/v1/checkout/sessions", body, idempotency_key=f"credits:{req.org_id}:{time.time_ns()}"
        )
        return CheckoutResult(
            url=str(data["url"]), provider_ref=data.get("id"), customer_id=data.get("customer")
        )

    def customer_portal_url(self, *, customer_id: str, subscription_id: str | None, return_url: str) -> str:
        data = self._call(
            "POST", "/v1/billing_portal/sessions", {"customer": customer_id, "return_url": return_url}
        )
        return str(data["url"])

    def cancel(self, *, subscription_id: str, immediately: bool = False) -> None:
        if immediately:
            self._call("DELETE", f"/v1/subscriptions/{subscription_id}")
        else:
            self._call("POST", f"/v1/subscriptions/{subscription_id}", {"cancel_at_period_end": True})

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
        if not customer_id:
            raise ProviderError("stripe: a charge needs a customer")
        ref = None
        for i, ln in enumerate(lines):
            body: dict[str, Any] = {
                "customer": customer_id,
                "amount": to_minor(ln.amount, currency),
                "currency": currency.lower(),
                "description": ln.description[:250],
                "metadata": {**custom_data, "key": idempotency_key},
            }
            if subscription_id:
                body["subscription"] = subscription_id
            data = self._call("POST", "/v1/invoiceitems", body, idempotency_key=f"{idempotency_key}:{i}")
            ref = ref or data.get("id")
        return ChargeResult(provider_ref=ref, status="scheduled")

    def report_usage(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
        unit: str,
        quantity: Decimal,
        idempotency_key: str,
    ) -> bool:
        self._call(
            "POST",
            "/v1/billing/meter_events",
            {
                "event_name": f"arbiter_{unit}",
                "identifier": idempotency_key,
                "payload": {"stripe_customer_id": customer_id, "value": format(quantity.normalize(), "f")},
            },
            idempotency_key=idempotency_key,
        )
        return True

    def invoice_document_url(self, provider_ref: str) -> str | None:
        if not provider_ref.startswith("in_"):
            return None
        data = self._call("GET", f"/v1/invoices/{provider_ref}")
        return data.get("invoice_pdf") or data.get("hosted_invoice_url")

    # ------------------------------------------------------------ webhooks

    def verify_signature(self, header: str, body: bytes, now: float | None = None) -> None:
        if not self.webhook_secret:
            raise ProviderNotConfigured("Stripe webhook secret is not configured")
        t = ""
        v1: list[str] = []
        for piece in (header or "").split(","):
            k, _, v = piece.strip().partition("=")
            if k == "t":
                t = v
            elif k == "v1":
                v1.append(v)
        if not t.isdigit() or not v1:
            raise InvalidSignature("malformed Stripe-Signature header")
        if abs((now or time.time()) - int(t)) > SIGNATURE_TOLERANCE_S:
            raise InvalidSignature("Stripe-Signature timestamp outside tolerance")
        expected = hmac.new(self.webhook_secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, s) for s in v1):
            raise InvalidSignature("Stripe-Signature does not match")

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        header = next((v for k, v in headers.items() if k.lower() == "stripe-signature"), "")
        self.verify_signature(header, body)
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise InvalidSignature("webhook body is not JSON") from e
        etype = str(payload.get("type") or "")
        obj = (payload.get("data") or {}).get("object") or {}
        ev = ProviderEvent(
            provider=self.name,
            event_id=str(payload.get("id") or ""),
            event_type=etype,
            occurred_at=parse_time(payload.get("created")),
            raw=payload,
        )
        if not ev.event_id:
            raise InvalidSignature("webhook has no id")
        if etype.startswith("customer.subscription."):
            ev.subscription = self._subscription(obj, deleted=etype.endswith(".deleted"))
        elif etype in ("invoice.paid", "invoice.payment_failed"):
            ev.payment = self._invoice(obj, "paid" if etype == "invoice.paid" else "failed")
        elif etype == "checkout.session.completed" and obj.get("mode") == "payment":
            meta = obj.get("metadata") or {}
            cur = str(obj.get("currency") or "eur").upper()
            ev.payment = PaymentRecord(
                provider_ref=str(obj.get("payment_intent") or obj.get("id")),
                status="paid" if obj.get("payment_status") == "paid" else "failed",
                kind=meta.get("kind") or "other",
                org_id=meta.get("org_id") or obj.get("client_reference_id"),
                provider_customer_id=obj.get("customer"),
                currency=cur,
                subtotal=from_minor(obj.get("amount_subtotal"), cur),
                tax=from_minor((obj.get("total_details") or {}).get("amount_tax"), cur),
                total=from_minor(obj.get("amount_total"), cur),
                pack_key=meta.get("pack"),
            )
        elif etype == "charge.refunded":
            cur = str(obj.get("currency") or "eur").upper()
            ev.refund = RefundRecord(
                provider_ref=str(obj.get("payment_intent") or obj.get("id")),
                amount=from_minor(obj.get("amount_refunded"), cur),
                currency=cur,
                refund_ref=str(obj.get("id")),
            )
        return ev

    @staticmethod
    def _subscription(o: dict[str, Any], *, deleted: bool) -> SubscriptionUpdate:
        meta = o.get("metadata") or {}
        items = ((o.get("items") or {}).get("data")) or []
        first = items[0] if items else {}
        price = first.get("price") or {}
        seats = meta.get("seats")
        return SubscriptionUpdate(
            provider_subscription_id=str(o.get("id")),
            status="canceled" if deleted else STATUS.get(str(o.get("status")), "incomplete"),
            provider_customer_id=o.get("customer"),
            org_id=meta.get("org_id"),
            plan_key=meta.get("plan"),
            price_ids=[
                str((i.get("price") or {}).get("id")) for i in items if (i.get("price") or {}).get("id")
            ],
            interval=(price.get("recurring") or {}).get("interval"),
            currency=str(o.get("currency") or "").upper() or None,
            seats=int(seats) if str(seats or "").isdigit() else None,
            period_start=parse_time(first.get("current_period_start") or o.get("current_period_start")),
            period_end=parse_time(first.get("current_period_end") or o.get("current_period_end")),
            cancel_at=parse_time(o.get("cancel_at")),
            canceled_at=parse_time(o.get("canceled_at")),
        )

    @staticmethod
    def _invoice(o: dict[str, Any], status: str) -> PaymentRecord:
        cur = str(o.get("currency") or "eur").upper()
        meta = o.get("metadata") or {}
        sub_meta = ((o.get("subscription_details") or {}).get("metadata")) or {}
        lines = [
            {
                "type": "provider_item",
                "description": ln.get("description") or "",
                "quantity": str(ln.get("quantity") or 1),
            }
            for ln in ((o.get("lines") or {}).get("data") or [])
        ]
        return PaymentRecord(
            provider_ref=str(o.get("id")),
            status=status,
            kind=meta.get("kind") or ("subscription" if o.get("subscription") else "other"),
            org_id=meta.get("org_id") or sub_meta.get("org_id"),
            provider_customer_id=o.get("customer"),
            provider_subscription_id=o.get("subscription"),
            currency=cur,
            subtotal=from_minor(o.get("subtotal"), cur),
            tax=from_minor(o.get("tax"), cur),
            total=from_minor(o.get("total"), cur),
            invoice_number=o.get("number"),
            invoice_url=o.get("hosted_invoice_url"),
            lines=lines,
        )
