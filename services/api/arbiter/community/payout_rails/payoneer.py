"""Payoneer Mass Payouts rail, API v4 style (D-073). Mocked in tests; verify against the
program's API reference with the sandbox credentials before the first live payout (P03).

    POST {login}/api/v2/oauth2/token                       client_credentials (basic auth)
    POST /v4/programs/{program}/payees/registration-link   {payee_id, redirect_url}
                                                           -> result.registration_link
    GET  /v4/programs/{program}/payees/{payee}/status      -> result.status.description
                                                              ("Active" when onboarded)
    POST /v4/programs/{program}/masspayouts                {Payments: [{client_reference_id,
                                                             payee_id, amount, currency,
                                                             description}]}
    GET  /v4/programs/{program}/payouts/{client_ref}/status -> result.status

Hosts: api.sandbox.payoneer.com / login.sandbox.payoneer.com, api.payoneer.com /
login.payoneer.com. A payee must finish Payoneer's registration (onboarding link) before a
payout can be sent. client_reference_id = our payout idempotency key: a duplicate is
reported by Payoneer and treated as "already submitted", then polled.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from arbiter.billing.providers.base import http_client
from arbiter.config import get_settings

HOSTS = {
    "sandbox": ("https://api.sandbox.payoneer.com", "https://login.sandbox.payoneer.com"),
    "production": ("https://api.payoneer.com", "https://login.payoneer.com"),
}
SETTLED = {"transferred", "completed", "paid"}
FAILED = {"cancelled", "canceled", "failed", "declined", "returned"}


class PayoneerRail:
    name = "payoneer"

    def __init__(
        self,
        client_id: str | None = None,
        secret: str | None = None,
        program_id: str | None = None,
        environment: str | None = None,
    ):
        s = get_settings()
        self.client_id = s.payoneer_client_id if client_id is None else client_id
        self.secret = s.payoneer_client_secret if secret is None else secret
        self.program_id = s.payoneer_program_id if program_id is None else program_id
        self.api, self.login = HOSTS[environment or s.payoneer_environment]
        self._token: str | None = None

    def configured(self) -> bool:
        return bool(self.client_id and self.secret and self.program_id)

    def _auth(self) -> str:
        if self._token:
            return self._token
        with http_client(self.login) as c:
            r = c.post(
                "/api/v2/oauth2/token",
                data={"grant_type": "client_credentials", "scope": "read write"},
                auth=(self.client_id, self.secret),
            )
        if r.status_code >= 400:
            raise RuntimeError(f"payoneer oauth: HTTP {r.status_code}")
        self._token = str(r.json()["access_token"])
        return self._token

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        with http_client(self.api, {"Authorization": f"Bearer {self._auth()}"}) as c:
            return c.request(method, f"/v4/programs/{self.program_id}{path}", json=body)

    # ------------------------------------------------------------ onboarding

    def registration_link(self, payee_id: str, redirect_url: str) -> str:
        r = self._call(
            "POST", "/payees/registration-link", {"payee_id": payee_id, "redirect_url": redirect_url}
        )
        if r.status_code >= 400:
            raise RuntimeError(f"payoneer registration link: HTTP {r.status_code}")
        return str((r.json().get("result") or {}).get("registration_link") or "")

    def payee_status(self, payee_id: str) -> str:
        """active | pending | rejected"""
        r = self._call("GET", f"/payees/{payee_id}/status")
        if r.status_code == 404:
            return "pending"
        if r.status_code >= 400:
            raise RuntimeError(f"payoneer payee status: HTTP {r.status_code}")
        desc = str(((r.json().get("result") or {}).get("status") or {}).get("description") or "").lower()
        if desc == "active":
            return "active"
        if desc in ("declined", "rejected", "inactive", "blocked"):
            return "rejected"
        return "pending"

    # ------------------------------------------------------------ payouts

    def send(
        self,
        *,
        idempotency_key: str,
        reviewer_id: str,
        amount: Decimal,
        currency: str,
        method: str,
        details: dict[str, Any],
    ):  # noqa: ANN201
        from arbiter.community.payouts import PayoutResult

        if not self.configured():
            return PayoutResult("failed", None, "Payoneer payouts are not configured")
        payee = str(details.get("payee_id") or reviewer_id)
        body = {
            "Payments": [
                {
                    "client_reference_id": idempotency_key[:100],
                    "payee_id": payee,
                    "amount": str(amount.quantize(Decimal("0.01"))),
                    "currency": currency.upper(),
                    "description": "Review work payout",
                }
            ]
        }
        try:
            r = self._call("POST", "/masspayouts", body)
        except (httpx.HTTPError, RuntimeError) as e:
            return PayoutResult("failed", None, f"payoneer: {e}"[:500])
        if r.status_code >= 400:
            text = r.text.lower()
            if "duplicate" in text or "already exists" in text:
                return PayoutResult("pending", f"payoneer:{idempotency_key}")
            return PayoutResult("failed", None, f"payoneer: HTTP {r.status_code}")
        return PayoutResult("pending", f"payoneer:{idempotency_key}")

    def poll(self, provider_ref: str):  # noqa: ANN201
        from arbiter.community.payouts import PayoutResult

        if not provider_ref.startswith("payoneer:"):
            return PayoutResult("pending", provider_ref)
        ref = provider_ref.split(":", 1)[1]
        r = self._call("GET", f"/payouts/{ref}/status")
        if r.status_code >= 400:
            return PayoutResult("pending", provider_ref, f"payoneer status: HTTP {r.status_code}")
        result = r.json().get("result") or {}
        status = str(result.get("status") or "").lower()
        if status in SETTLED:
            return PayoutResult("settled", provider_ref)
        if status in FAILED:
            return PayoutResult("failed", provider_ref, f"payoneer: {result.get('reason') or status}"[:500])
        return PayoutResult("pending", provider_ref)
