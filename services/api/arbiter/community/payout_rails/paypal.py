"""PayPal Payouts API rail (D-052).

    POST /v1/oauth2/token            grant_type=client_credentials, HTTP basic client id:secret
    POST /v1/payments/payouts        {sender_batch_header: {sender_batch_id, email_subject},
                                      items: [{recipient_type: EMAIL, amount: {value, currency},
                                               receiver, sender_item_id, note}]}
                                     -> 201 {batch_header: {payout_batch_id, batch_status}}
    GET  /v1/payments/payouts/{id}   items[].transaction_status

Base https://api-m.paypal.com, sandbox https://api-m.sandbox.paypal.com. One payout per
batch: sender_batch_id = our payout idempotency key, so PayPal itself refuses a second batch
with the same id (it never pays twice). Status mapping: SUCCESS -> settled; FAILED, RETURNED,
BLOCKED, REFUNDED, REVERSED, DENIED -> failed; everything else (PENDING, UNCLAIMED, ONHOLD) ->
pending, polled again by refresh_pending.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from arbiter.billing.providers.base import http_client
from arbiter.config import get_settings

BASE_URLS = {"sandbox": "https://api-m.sandbox.paypal.com", "production": "https://api-m.paypal.com"}
FAILED = {"FAILED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED", "DENIED"}


class PayPalRail:
    name = "paypal"

    def __init__(
        self, client_id: str | None = None, secret: str | None = None, environment: str | None = None
    ):
        s = get_settings()
        self.client_id = s.paypal_client_id if client_id is None else client_id
        self.secret = s.paypal_client_secret if secret is None else secret
        self.base_url = BASE_URLS[environment or s.paypal_environment]
        self._token: str | None = None

    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    def _auth(self) -> str:
        if self._token:
            return self._token
        with http_client(self.base_url) as c:
            r = c.post(
                "/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.secret),
                headers={"Accept": "application/json"},
            )
        if r.status_code >= 400:
            raise RuntimeError(f"paypal oauth: HTTP {r.status_code}")
        self._token = str(r.json()["access_token"])
        return self._token

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        with http_client(self.base_url, {"Authorization": f"Bearer {self._auth()}"}) as c:
            return c.request(method, path, json=body)

    def send(
        self,
        *,
        idempotency_key: str,
        reviewer_id: str,
        amount: Decimal,
        currency: str,
        method: str,
        details: dict[str, Any],
    ):  # noqa: ANN201  (PayoutResult, imported lazily to avoid a cycle)
        from arbiter.community.payouts import PayoutResult

        if not self.configured():
            return PayoutResult("failed", None, "PayPal payouts are not configured")
        email = str(details.get("email") or "").strip()
        if "@" not in email:
            return PayoutResult("failed", None, "PayPal email missing in payout details")
        body = {
            "sender_batch_header": {
                "sender_batch_id": idempotency_key[:127],
                "email_subject": "You have a payout",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {"value": str(amount.quantize(Decimal("0.01"))), "currency": currency.upper()},
                    "receiver": email,
                    "sender_item_id": idempotency_key[:63],
                    "note": "Review work payout",
                }
            ],
        }
        try:
            r = self._call("POST", "/v1/payments/payouts", body)
        except (httpx.HTTPError, RuntimeError) as e:
            return PayoutResult("failed", None, f"paypal: {e}"[:500])
        if r.status_code >= 400:
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            name = str(data.get("name") or "")
            if "DUPLICATE" in name or "ALREADY" in name:
                # Sent before under this key: PayPal holds it; operator checks the dashboard.
                return PayoutResult(
                    "pending", f"paypal-dup:{idempotency_key}", "duplicate batch id at PayPal"
                )
            return PayoutResult("failed", None, f"paypal: HTTP {r.status_code} {name}"[:500])
        batch = r.json().get("batch_header") or {}
        return PayoutResult("pending", f"paypal:{batch.get('payout_batch_id')}")

    def poll(self, provider_ref: str):  # noqa: ANN201
        from arbiter.community.payouts import PayoutResult

        if not provider_ref.startswith("paypal:"):
            return PayoutResult("pending", provider_ref)
        batch_id = provider_ref.split(":", 1)[1]
        r = self._call("GET", f"/v1/payments/payouts/{batch_id}")
        if r.status_code >= 400:
            return PayoutResult("pending", provider_ref, f"paypal status: HTTP {r.status_code}")
        items = r.json().get("items") or []
        status = str((items[0] if items else {}).get("transaction_status") or "PENDING").upper()
        if status == "SUCCESS":
            return PayoutResult("settled", provider_ref)
        if status in FAILED:
            return PayoutResult("failed", provider_ref, f"paypal: {status}")
        return PayoutResult("pending", provider_ref)
