"""Manual provider: bank transfer against OUR invoice; an admin marks it paid (D-072).

Used for enterprise deals (payment terms, PO numbers, bank transfer) and whenever no payment
provider is configured. "Checkout" issues an invoice (billing.invoices.issue_invoice) and
returns the billing page link that shows it with its PDF. Nothing is activated until
POST /v1/admin/invoices/{id}/mark-paid, which calls billing.subscriptions.invoice_paid.
There are no webhooks.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy.orm import Session

from arbiter.billing.invoices import issue_invoice
from arbiter.billing.providers.base import (
    ChargeLine,
    ChargeResult,
    CheckoutRequest,
    CheckoutResult,
    CreditCheckoutRequest,
    ProviderEvent,
)
from arbiter.config import get_settings
from arbiter.errors import Invalid, NotFound
from arbiter.models import Organization


class ManualProvider:
    name = "manual"

    def __init__(self, session: Session) -> None:
        self.session = session
        self.web = get_settings().web_base_url.rstrip("/")

    def configured(self) -> bool:
        return True

    def _org(self, org_id: str) -> Organization:
        org = self.session.get(Organization, org_id)
        if org is None:
            raise NotFound("organization not found")
        return org

    def ensure_customer(self, *, org_id: str, name: str, email: str, existing_id: str | None) -> str | None:
        return None

    def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        lines = [
            {
                "type": "subscription",
                "description": f"{req.plan_name} plan, 1 {req.interval}",
                "quantity": Decimal(1),
                "unit_amount": req.base_price,
                "amount": req.base_price,
                "plan": req.plan_key,
                "interval": req.interval,
                "seats": req.seats,
            }
        ]
        if req.extra_seats > 0 and req.seat_price > 0:
            lines.append(
                {
                    "type": "seats",
                    "description": f"{req.plan_name} extra seats, 1 {req.interval}",
                    "quantity": Decimal(req.extra_seats),
                    "unit_amount": req.seat_price,
                    "amount": req.seat_price * req.extra_seats,
                }
            )
        inv = issue_invoice(
            self.session, self._org(req.org_id), kind="subscription", lines=lines, currency=req.currency
        )
        return CheckoutResult(url=f"{self.web}/app/settings/billing?invoice={inv.id}", provider_ref=inv.id)

    def create_credit_checkout(self, req: CreditCheckoutRequest) -> CheckoutResult:
        lines = [
            {
                "type": "credit_pack",
                "description": f"Prepaid credit: {req.pack_name} ({req.credit_amount} {req.currency})",
                "quantity": Decimal(1),
                "unit_amount": req.price,
                "amount": req.price,
                "pack": req.pack_key,
            }
        ]
        inv = issue_invoice(
            self.session, self._org(req.org_id), kind="credit_pack", lines=lines, currency=req.currency
        )
        return CheckoutResult(url=f"{self.web}/app/settings/billing?invoice={inv.id}", provider_ref=inv.id)

    def customer_portal_url(self, *, customer_id: str, subscription_id: str | None, return_url: str) -> str:
        return f"{self.web}/app/settings/billing"

    def cancel(self, *, subscription_id: str, immediately: bool = False) -> None:
        return None  # local state only, handled by billing.subscriptions.cancel

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
        org_id = custom_data.get("org_id")
        if not org_id:
            raise Invalid("manual charge needs org_id")
        inv = issue_invoice(
            self.session,
            self._org(org_id),
            kind=custom_data.get("kind", "overage"),
            lines=[
                {
                    "type": custom_data.get("kind", "overage"),
                    "description": ln.description,
                    "quantity": ln.quantity,
                    "unit_amount": ln.unit_amount,
                    "amount": ln.amount,
                }
                for ln in lines
            ],
            currency=currency,
        )
        return ChargeResult(provider_ref=inv.id, status="issued")

    def report_usage(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
        unit: str,
        quantity: Decimal,
        idempotency_key: str,
    ) -> bool:
        return False

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        raise Invalid("the manual provider has no webhooks")

    def invoice_document_url(self, provider_ref: str) -> str | None:
        return None
