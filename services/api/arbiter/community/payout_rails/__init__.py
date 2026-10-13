"""Payout rails behind community.payouts.PayoutProvider (D-052).

RailRouter is a PayoutProvider that sends each payout through the rail of the payee's
payout method:

    payoneer -> PayoneerRail   (Mass Payouts API, payee must finish Payoneer onboarding)
    paypal   -> PayPalRail     (Payouts API batch, OAuth client credentials)
    sepa     -> BankRail       (SEPA pain.001 / CSV batch file, admin confirms)
    wise     -> BankRail       (Wise batch CSV, admin confirms)

Every rail returns pending (or failed) on send; `poll` turns pending into settled/failed
(community.payouts.refresh_pending). Rails dedupe on the payout idempotency key.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from arbiter.community.payout_rails.bank import BankRail
from arbiter.community.payout_rails.payoneer import PayoneerRail
from arbiter.community.payout_rails.paypal import PayPalRail

METHODS = ("payoneer", "paypal", "sepa", "wise")


class RailRouter:
    name = "rails"

    def __init__(self, rails: dict[str, Any] | None = None) -> None:
        bank = BankRail()
        self.rails: dict[str, Any] = rails or {
            "payoneer": PayoneerRail(),
            "paypal": PayPalRail(),
            "sepa": bank,
            "wise": bank,
        }

    def rail(self, method: str) -> Any | None:
        return self.rails.get(method)

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

        rail = self.rail(method)
        if rail is None:
            return PayoutResult("failed", None, f"no payout rail for method {method!r}")
        return rail.send(
            idempotency_key=idempotency_key,
            reviewer_id=reviewer_id,
            amount=amount,
            currency=currency,
            method=method,
            details=details,
        )

    def poll(self, provider_ref: str, method: str):  # noqa: ANN201
        from arbiter.community.payouts import PayoutResult

        rail = self.rail(method)
        if rail is None:
            return PayoutResult("pending", provider_ref)
        return rail.poll(provider_ref)

    def configured_methods(self) -> list[str]:
        return [m for m in METHODS if self.rails.get(m) is not None and self.rails[m].configured()]


def any_api_rail_configured() -> bool:
    return PayoneerRail().configured() or PayPalRail().configured()
