"""Provider adapters over httpx.MockTransport and signed webhook fixtures (D-072)."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
from bill_helpers import make_org
from billing_fixtures import (
    PADDLE_SECRET,
    paddle_signed,
    paddle_subscription_event,
    paddle_transaction_event,
    stripe_signed,
)

from arbiter.billing.providers import default_provider, provider_for
from arbiter.billing.providers.base import (
    ChargeLine,
    CheckoutRequest,
    CreditCheckoutRequest,
    InvalidSignature,
    ProviderError,
    from_minor,
    to_minor,
)
from arbiter.billing.providers.paddle import PaddleProvider
from arbiter.billing.providers.stripe import StripeProvider, form_encode


def _req(**kw) -> CheckoutRequest:
    base = dict(
        org_id="org_1",
        org_name="Acme",
        email="pm@example.test",
        plan_key="team",
        plan_name="Team",
        interval="month",
        currency="EUR",
        seats=7,
        extra_seats=2,
        base_price=Decimal("199.00"),
        seat_price=Decimal("19.00"),
        provider_price_ids={},
        customer_id="ctm_1",
        success_url="http://web/ok",
        cancel_url="http://web/no",
    )
    base.update(kw)
    return CheckoutRequest(**base)


def test_minor_units():
    assert to_minor(Decimal("49.00"), "EUR") == "4900"
    assert to_minor(Decimal("0.125"), "USD") == "13"
    assert to_minor(Decimal("1200"), "JPY") == "1200"
    assert from_minor("23900", "EUR") == Decimal("239.00")
    with pytest.raises(TypeError):
        to_minor(49.0, "EUR")  # type: ignore[arg-type]


def test_paddle_checkout_non_catalog_and_catalog_prices(paddle_env, mock_http):
    rec = mock_http(
        {
            ("POST", "/transactions"): (
                201,
                {
                    "data": {
                        "id": "txn_1",
                        "customer_id": "ctm_1",
                        "checkout": {"url": "http://localhost:3000/checkout/paddle?_ptxn=txn_1"},
                    }
                },
            )
        }
    )
    res = PaddleProvider().create_checkout(_req())
    assert res.url.endswith("_ptxn=txn_1") and res.provider_ref == "txn_1"
    method, path, body = rec.calls[0]
    assert (method, path) == ("POST", "/transactions")
    assert body["custom_data"] == {
        "org_id": "org_1",
        "kind": "subscription",
        "plan": "team",
        "seats": "7",
        "interval": "month",
    }
    base, seats = body["items"]
    assert base["price"]["unit_price"] == {"amount": "19900", "currency_code": "EUR"}
    assert base["price"]["billing_cycle"] == {"interval": "month", "frequency": 1}
    assert base["price"]["product"]["tax_category"] == "saas"
    assert seats["quantity"] == 2 and seats["price"]["unit_price"]["amount"] == "1900"
    assert body["checkout"]["url"].endswith("/checkout/paddle")

    PaddleProvider().create_checkout(
        _req(provider_price_ids={"month:EUR": "pri_team", "seat:month:EUR": "pri_seat"})
    )
    body = rec.calls[1][2]
    assert body["items"] == [{"price_id": "pri_team", "quantity": 1}, {"price_id": "pri_seat", "quantity": 2}]


def test_paddle_portal_cancel_charge_and_errors(paddle_env, mock_http):
    rec = mock_http(
        {
            ("POST", "/customers/ctm_1/portal-sessions"): (
                201,
                {"data": {"urls": {"general": {"overview": "https://portal/x"}}}},
            ),
            ("POST", "/subscriptions/sub_1/cancel"): (200, {"data": {"id": "sub_1"}}),
            ("POST", "/subscriptions/sub_1/charge"): (200, {"data": {"id": "sub_1"}}),
            ("POST", "/customers"): (201, {"data": {"id": "ctm_new"}}),
            ("GET", "/transactions/txn_9/invoice"): (200, {"data": {"url": "https://pdf/txn_9"}}),
            ("POST", "/transactions"): (400, {"error": {"detail": "bad request"}}),
        }
    )
    p = PaddleProvider()
    assert (
        p.customer_portal_url(customer_id="ctm_1", subscription_id="sub_1", return_url="x")
        == "https://portal/x"
    )
    assert rec.calls[-1][2] == {"subscription_ids": ["sub_1"]}
    p.cancel(subscription_id="sub_1")
    assert rec.calls[-1][2] == {"effective_from": "next_billing_period"}
    res = p.add_charge(
        subscription_id="sub_1",
        customer_id="ctm_1",
        lines=[ChargeLine("Overage words 2030-01", Decimal("1000"), Decimal("0.012"), Decimal("12.00"))],
        currency="EUR",
        idempotency_key="overage:org_1:2030-01",
        custom_data={"org_id": "org_1", "kind": "overage", "invoice_id": "inv_1"},
    )
    assert res.status == "scheduled"
    charge = rec.calls[-1][2]
    assert charge["effective_from"] == "immediately"
    assert charge["items"][0]["price"]["unit_price"]["amount"] == "1200"
    assert charge["items"][0]["price"]["custom_data"]["invoice_id"] == "inv_1"
    assert "billing_cycle" not in charge["items"][0]["price"]
    assert (
        p.ensure_customer(org_id="org_1", name="Acme", email="a@example.test", existing_id=None) == "ctm_new"
    )
    assert (
        p.ensure_customer(org_id="org_1", name="Acme", email="a@example.test", existing_id="ctm_1") == "ctm_1"
    )
    assert p.invoice_document_url("txn_9") == "https://pdf/txn_9"
    assert (
        p.report_usage(
            customer_id="c", subscription_id="s", unit="word", quantity=Decimal(1), idempotency_key="k"
        )
        is False
    )
    with pytest.raises(ProviderError):
        p.create_credit_checkout(
            CreditCheckoutRequest(
                "org_1",
                "Acme",
                "a@example.test",
                "credits_50",
                "Small",
                Decimal("50"),
                Decimal("50"),
                "EUR",
                None,
                "",
                "",
            )
        )
    with pytest.raises(ProviderError):
        p.add_charge(
            subscription_id=None,
            customer_id="c",
            lines=[],
            currency="EUR",
            idempotency_key="k",
            custom_data={},
        )


def test_paddle_signature_verification(paddle_env):
    p = PaddleProvider()
    payload = paddle_subscription_event("evt_1", "org_1")
    body, headers = paddle_signed(payload)
    ev = p.parse_webhook(headers, body)
    assert ev.event_id == "evt_1" and ev.subscription is not None
    s = ev.subscription
    assert (s.provider_subscription_id, s.status, s.plan_key, s.seats, s.interval) == (
        "sub_01test",
        "active",
        "team",
        5,
        "month",
    )
    assert s.period_end is not None and s.period_end.month == 2

    with pytest.raises(InvalidSignature):
        p.parse_webhook(headers, body.replace(b"team", b"business"))  # tampered body
    _, wrong = paddle_signed(payload, secret="other")
    with pytest.raises(InvalidSignature):
        p.parse_webhook(wrong, body)
    old_body, old = paddle_signed(payload, ts=int(time.time()) - 3600)
    with pytest.raises(InvalidSignature):
        p.parse_webhook(old, old_body)  # replay outside tolerance
    with pytest.raises(InvalidSignature):
        p.parse_webhook({"Paddle-Signature": "garbage"}, body)
    # Secret rotation: several h1 values, one matches.
    good = headers["Paddle-Signature"]
    rotated = {"paddle-signature": good.replace("h1=", "h1=deadbeef;h1=")}
    assert p.parse_webhook(rotated, body).event_id == "evt_1"
    assert PADDLE_SECRET  # fixture constant used by paddle_signed


def test_paddle_parses_transactions_and_refunds(paddle_env):
    p = PaddleProvider()
    body, h = paddle_signed(
        paddle_transaction_event(
            "evt_t", "org_1", kind="credit_pack", pack="credits_50", total="5000", tax="0", sub_id=None
        )
    )
    pay = p.parse_webhook(h, body).payment
    assert pay is not None
    assert (pay.kind, pay.pack_key, pay.total, pay.status, pay.invoice_number) == (
        "credit_pack",
        "credits_50",
        Decimal("50.00"),
        "paid",
        "325-10001",
    )
    refund = {
        "event_id": "evt_r",
        "event_type": "adjustment.created",
        "data": {
            "id": "adj_1",
            "action": "refund",
            "status": "approved",
            "transaction_id": "txn_01test",
            "currency_code": "EUR",
            "totals": {"total": "2000"},
        },
    }
    body, h = paddle_signed(refund)
    ev = p.parse_webhook(h, body)
    assert ev.refund is not None and ev.refund.amount == Decimal("20.00")
    pending = {**refund, "event_id": "evt_r2", "data": {**refund["data"], "status": "pending_approval"}}
    body, h = paddle_signed(pending)
    assert p.parse_webhook(h, body).refund is None


def test_stripe_disabled_unless_configured_then_same_interface(db, stripe_env, mock_http):
    org = make_org(db)
    assert StripeProvider(secret_key="", webhook_secret="").configured() is False
    rec = mock_http(
        {
            ("POST", "/v1/checkout/sessions"): (
                200,
                {"id": "cs_1", "url": "https://checkout.stripe/cs_1", "customer": "cus_1"},
            ),
            ("POST", "/v1/billing_portal/sessions"): (200, {"url": "https://billing.stripe/p"}),
            ("POST", "/v1/invoiceitems"): (200, {"id": "ii_1"}),
            ("POST", "/v1/billing/meter_events"): (200, {"identifier": "k"}),
            ("POST", "/v1/subscriptions/sub_s"): (200, {"id": "sub_s"}),
        }
    )
    s = StripeProvider()
    assert s.configured()
    res = s.create_checkout(_req(customer_id=None))
    assert res.url == "https://checkout.stripe/cs_1"
    sent = dict(form_encode({"a": {"b": [{"c": 1}]}}))
    assert sent == {"a[b][0][c]": "1"}
    assert "mode=subscription" in rec.calls[0][2] and "metadata%5Borg_id%5D=org_1" in rec.calls[0][2]
    assert (
        s.customer_portal_url(customer_id="cus_1", subscription_id=None, return_url="http://x")
        == "https://billing.stripe/p"
    )
    s.cancel(subscription_id="sub_s")
    assert "cancel_at_period_end=true" in rec.calls[-1][2]
    assert (
        s.add_charge(
            subscription_id="sub_s",
            customer_id="cus_1",
            lines=[ChargeLine("x", Decimal(1), Decimal("5"), Decimal("5"))],
            currency="EUR",
            idempotency_key="k",
            custom_data={},
        ).provider_ref
        == "ii_1"
    )
    assert s.report_usage(
        customer_id="cus_1", subscription_id=None, unit="word", quantity=Decimal("1500"), idempotency_key="u1"
    )

    event = {
        "id": "evt_s1",
        "type": "customer.subscription.updated",
        "created": 1893456000,
        "data": {
            "object": {
                "id": "sub_s",
                "status": "unpaid",
                "customer": "cus_1",
                "currency": "eur",
                "metadata": {"org_id": org.id, "plan": "team", "seats": "6"},
                "items": {
                    "data": [
                        {
                            "price": {"id": "price_1", "recurring": {"interval": "year"}},
                            "current_period_start": 1893456000,
                            "current_period_end": 1924992000,
                        }
                    ]
                },
            }
        },
    }
    body, h = stripe_signed(event)
    ev = s.parse_webhook(h, body)
    assert (
        ev.subscription is not None
        and ev.subscription.status == "past_due"
        and ev.subscription.interval == "year"
    )
    with pytest.raises(InvalidSignature):
        s.parse_webhook(h, body + b" ")
    # The registry never picks Stripe on auto, and falls back to manual without Paddle keys.
    assert default_provider(db, org).name == "manual"
    org.settings = {"billing": {"provider": "stripe"}}
    assert default_provider(db, org).name == "stripe"
    assert provider_for("manual", db).name == "manual"
