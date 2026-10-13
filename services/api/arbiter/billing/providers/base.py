"""Payment provider adapter interface (D-051).

Our database is the source of truth for plans, subscriptions, entitlements, usage, credits
and invoice records. A provider adapter only does what needs the provider:

    create_checkout          hosted checkout URL for a plan (subscription)
    create_credit_checkout   hosted checkout URL for a one-time credit pack
    customer_portal_url      hosted page where the customer manages payment methods
    cancel                   cancel a subscription (at period end or now)
    add_charge               one-time charge on a subscription (overage at period close)
    report_usage             metered usage, for providers that bill meters (Stripe); Paddle
                             returns False because overage is sent as a one-time charge
    parse_webhook            verify the signature and normalise the event
    invoice_document_url     fresh link to the provider's invoice / receipt PDF

Adapters never touch the database except `manual`, which issues our own invoices. They raise
ProviderError on any provider failure and InvalidSignature on a bad webhook signature.
HTTP goes through `http_client()`; tests set `transport` to an httpx.MockTransport.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import httpx

from arbiter.errors import ServiceError

# Tests swap this for an httpx.MockTransport. Never a real network call in tests.
transport: httpx.BaseTransport | None = None

ZERO_DECIMAL_CURRENCIES = frozenset({"JPY", "KRW", "VND", "CLP", "ISK", "HUF", "TWD", "UGX"})


class ProviderError(ServiceError):
    code = "payment_provider_error"
    status = 502


class ProviderNotConfigured(ServiceError):
    code = "payment_provider_not_configured"
    status = 503


class InvalidSignature(ServiceError):
    code = "invalid_signature"
    status = 400


def http_client(base_url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers=headers or {}, timeout=timeout, transport=transport)


def to_minor(amount: Decimal, currency: str) -> str:
    """Decimal -> lowest denomination as a string ("49.00" EUR -> "4900")."""
    if not isinstance(amount, Decimal):
        raise TypeError("amounts must be Decimal")
    exp = 0 if currency.upper() in ZERO_DECIMAL_CURRENCIES else 2
    return str(int((amount * (10**exp)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def from_minor(value: Any, currency: str) -> Decimal:
    exp = 0 if currency.upper() in ZERO_DECIMAL_CURRENCIES else 2
    return (Decimal(str(value or 0)) / (10**exp)).quantize(Decimal("0.01"))


def parse_time(value: Any) -> datetime | None:
    """ISO 8601 string or unix seconds -> aware datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(int(value), tz=UTC)
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ------------------------------------------------------------------ requests and results


@dataclass
class CheckoutRequest:
    org_id: str
    org_name: str
    email: str
    plan_key: str
    plan_name: str
    interval: str  # month | year
    currency: str
    seats: int
    extra_seats: int
    base_price: Decimal
    seat_price: Decimal
    provider_price_ids: dict[str, str]  # "month:EUR" -> price id, "seat:month:EUR" -> price id
    customer_id: str | None
    success_url: str
    cancel_url: str


@dataclass
class CreditCheckoutRequest:
    org_id: str
    org_name: str
    email: str
    pack_key: str
    pack_name: str
    credit_amount: Decimal
    price: Decimal
    currency: str
    customer_id: str | None
    success_url: str
    cancel_url: str


@dataclass
class CheckoutResult:
    url: str
    provider_ref: str | None = None
    customer_id: str | None = None


@dataclass
class ChargeLine:
    description: str
    quantity: Decimal
    unit_amount: Decimal
    amount: Decimal


@dataclass
class ChargeResult:
    provider_ref: str | None
    status: str  # scheduled | issued | paid
    url: str | None = None


# ------------------------------------------------------------------ normalised webhook events


@dataclass
class SubscriptionUpdate:
    provider_subscription_id: str
    status: str  # trialing | active | past_due | paused | canceled | incomplete
    provider_customer_id: str | None = None
    org_id: str | None = None
    plan_key: str | None = None
    price_ids: list[str] = field(default_factory=list)
    interval: str | None = None
    currency: str | None = None
    seats: int | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    cancel_at: datetime | None = None
    canceled_at: datetime | None = None


@dataclass
class PaymentRecord:
    provider_ref: str  # transaction / invoice / checkout id at the provider
    status: str  # paid | failed
    kind: str  # subscription | credit_pack | overage | other
    org_id: str | None = None
    provider_customer_id: str | None = None
    provider_subscription_id: str | None = None
    currency: str = "EUR"
    subtotal: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    invoice_number: str | None = None
    invoice_url: str | None = None
    pack_key: str | None = None
    invoice_id: str | None = None  # our invoice this payment settles (overage charges)
    lines: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RefundRecord:
    provider_ref: str  # the original transaction / charge
    amount: Decimal
    currency: str
    refund_ref: str


@dataclass
class ProviderEvent:
    provider: str
    event_id: str
    event_type: str
    occurred_at: datetime | None
    raw: dict[str, Any]
    subscription: SubscriptionUpdate | None = None
    payment: PaymentRecord | None = None
    refund: RefundRecord | None = None


class BillingProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    def ensure_customer(
        self, *, org_id: str, name: str, email: str, existing_id: str | None
    ) -> str | None: ...

    def create_checkout(self, req: CheckoutRequest) -> CheckoutResult: ...

    def create_credit_checkout(self, req: CreditCheckoutRequest) -> CheckoutResult: ...

    def customer_portal_url(
        self, *, customer_id: str, subscription_id: str | None, return_url: str
    ) -> str: ...

    def cancel(self, *, subscription_id: str, immediately: bool = False) -> None: ...

    def add_charge(
        self,
        *,
        subscription_id: str | None,
        customer_id: str | None,
        lines: list[ChargeLine],
        currency: str,
        idempotency_key: str,
        custom_data: dict[str, str],
    ) -> ChargeResult: ...

    def report_usage(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
        unit: str,
        quantity: Decimal,
        idempotency_key: str,
    ) -> bool: ...

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent: ...

    def invoice_document_url(self, provider_ref: str) -> str | None: ...
