"""Billing over HTTP: plans, checkout (manual and Paddle), webhooks, credits, admin (D-051..D-053)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from billing_fixtures import paddle_signed, paddle_subscription_event, paddle_transaction_event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from api_helpers import client, register  # noqa: E402

from arbiter.api import security  # noqa: E402
from arbiter.billing import catalog, credits, usage  # noqa: E402
from arbiter.cli import create_admin  # noqa: E402
from arbiter.models import BillingEvent, Invoice, Organization, Subscription, User  # noqa: E402


def _admin(c, db) -> dict[str, str]:
    create_admin(db, "ops@example.com", "admin-password-1")
    db.commit()
    r = c.post("/v1/auth/login", json={"email": "ops@example.com", "password": "admin-password-1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _org_id(c, h) -> str:
    return c.get("/v1/me", headers=h).json()["org"]["id"]


def _client_user(c, db, org_id: str) -> dict[str, str]:
    db.add(
        User(
            email="client@example.com",
            name="Client",
            password_hash=security.hash_password("client-password-1"),
            role="client",
            org_id=org_id,
        )
    )
    db.commit()
    r = c.post("/v1/auth/login", json={"email": "client@example.com", "password": "client-password-1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_public_plans_and_manual_checkout_until_admin_marks_paid(db):
    catalog.seed_starter_catalog(db)
    db.commit()
    c = client()
    plans = c.get("/v1/billing/plans").json()  # public, no token
    assert [p["key"] for p in plans["items"]] == ["starter", "team", "business", "enterprise"]
    assert plans["platform_fee"] == {"default_percent": "5", "max_percent": "8"}
    assert plans["credit_packs"][1] == {
        "key": "credits_200",
        "name": "Medium",
        "credit_amount": "210.00",
        "price": "200.00",
        "currency": "EUR",
        "valid_days": 365,
    }

    h = register(c)
    org_id = _org_id(c, h)
    assert (
        c.post("/v1/billing/checkout", json={"plan": "enterprise"}, headers=h).status_code == 422
    )  # contract
    assert c.post("/v1/billing/checkout", json={"plan": "team", "seats": 999}, headers=h).status_code == 422
    r = c.post("/v1/billing/checkout", json={"plan": "team", "seats": 7}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["provider"] == "manual" and "invoice=" in out["url"]
    inv_id = out["provider_ref"]

    sub = c.get("/v1/billing/subscription", headers=h).json()
    assert sub["subscription"] is None and sub["pending"]["status"] == "incomplete"
    invoices = c.get("/v1/invoices", headers=h).json()["items"]
    assert invoices[0]["kind"] == "subscription" and invoices[0]["issued_by"] == "us"
    assert invoices[0]["total"] == "237.00"  # 199 + 2 extra seats * 19, VAT not configured
    pdf = c.get(f"/v1/billing/invoices/{inv_id}/document", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    admin = _admin(c, db)
    paid = c.post(f"/v1/admin/invoices/{inv_id}/mark-paid", headers=admin)
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    sub = c.get("/v1/billing/subscription", headers=h).json()
    assert sub["subscription"]["status"] == "active" and sub["subscription"]["seats"] == 7
    assert sub["plan"]["key"] == "team"
    assert sub["modules"] == ["ai", "community", "pm", "tms"]
    assert {m["unit"] for m in sub["meters"]} == {"word", "ai_unit"}
    # The engine module is not in Team: its routes would now answer module_disabled.
    org = db.get(Organization, org_id)
    db.refresh(org)
    assert org.settings["modules"] == ["tms", "ai", "pm", "community"]

    # Credits by bank transfer: invoice, then admin marks paid -> lot.
    r = c.post("/v1/billing/credits/checkout", json={"pack": "credits_200"}, headers=h)
    assert r.status_code == 200
    c.post(f"/v1/admin/invoices/{r.json()['provider_ref']}/mark-paid", headers=admin)
    wallet = c.get("/v1/billing/credits", headers=h).json()
    assert wallet["balance"] == "210.00" and len(wallet["packs"]) == 3


def test_billing_permissions(db):
    catalog.seed_starter_catalog(db)
    db.commit()
    c = client()
    h = register(c)
    ch = _client_user(c, db, _org_id(c, h))
    assert c.get("/v1/billing/subscription", headers=ch).status_code == 200  # reads: any customer role
    for path, body in (
        ("/v1/billing/checkout", {"plan": "team"}),
        ("/v1/billing/portal", None),
        ("/v1/billing/credits/checkout", {"pack": "credits_50"}),
        ("/v1/billing/subscription/cancel", {}),
    ):
        assert c.post(path, json=body, headers=ch).status_code == 403, path
    assert c.get("/v1/admin/plans", headers=h).status_code == 403
    assert c.post("/v1/admin/orgs/org_x/subscription", json={}, headers=h).status_code == 403


def test_paddle_checkout_webhooks_invoices_credits_refund_portal_cancel(db, paddle_env, mock_http):
    catalog.seed_starter_catalog(db)
    db.commit()
    rec = mock_http(
        {
            ("POST", "/customers"): (201, {"data": {"id": "ctm_01test"}}),
            ("POST", "/transactions"): (
                201,
                {
                    "data": {
                        "id": "txn_ck",
                        "customer_id": "ctm_01test",
                        "checkout": {"url": "http://localhost:3000/checkout/paddle?_ptxn=txn_ck"},
                    }
                },
            ),
            ("GET", "/transactions/txn_01test/invoice"): (
                200,
                {"data": {"url": "https://paddle.pdf/txn_01test"}},
            ),
            ("POST", "/customers/ctm_01test/portal-sessions"): (
                201,
                {"data": {"urls": {"general": {"overview": "https://customer-portal.paddle.com/x"}}}},
            ),
            ("POST", "/subscriptions/sub_01test/cancel"): (200, {"data": {"id": "sub_01test"}}),
        }
    )
    c = client()
    h = register(c)
    org_id = _org_id(c, h)
    r = c.post("/v1/billing/checkout", json={"plan": "team", "interval": "month"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "url": "http://localhost:3000/checkout/paddle?_ptxn=txn_ck",
        "provider": "paddle",
        "provider_ref": "txn_ck",
    }
    assert rec.paths()[:2] == ["POST /customers", "POST /transactions"]
    assert c.get("/v1/billing/subscription", headers=h).json()["subscription"] is None  # not paid yet

    # Bad signature: 400, nothing stored.
    body, headers = paddle_signed(paddle_subscription_event("evt_1", org_id))
    bad = dict(headers, **{"Paddle-Signature": headers["Paddle-Signature"][:-4] + "0000"})
    assert c.post("/webhooks/paddle", content=body, headers=bad).status_code == 400
    assert db.query(BillingEvent).count() == 0

    r = c.post("/webhooks/paddle", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "processed"
    again = c.post("/webhooks/paddle", content=body, headers=headers)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    sub = c.get("/v1/billing/subscription", headers=h).json()
    assert sub["subscription"]["provider"] == "paddle" and sub["subscription"]["status"] == "active"
    assert sub["subscription"]["seats"] == 5 and sub["modules"] == ["ai", "community", "pm", "tms"]
    assert db.query(Subscription).count() == 1

    # Payment record: Paddle issued the tax invoice; we keep references and fetch the PDF link.
    body, headers = paddle_signed(paddle_transaction_event("evt_2", org_id))
    assert c.post("/webhooks/paddle", content=body, headers=headers).json()["status"] == "processed"
    inv = c.get("/v1/invoices", headers=h).json()["items"][0]
    assert inv["provider"] == "paddle" and inv["issued_by"] == "paddle" and inv["status"] == "paid"
    assert (inv["provider_ref"], inv["provider_invoice_number"], inv["total"], inv["tax"]) == (
        "txn_01test",
        "325-10001",
        "239.00",
        "39.00",
    )
    doc = c.get(f"/v1/billing/invoices/{inv['id']}/document", headers=h)
    assert doc.json() == {"url": "https://paddle.pdf/txn_01test", "provider": "paddle"}

    # Credit pack paid through Paddle -> lot; refund of the pack -> unused credit refunded.
    body, headers = paddle_signed(
        paddle_transaction_event(
            "evt_3",
            org_id,
            txn_id="txn_cp",
            kind="credit_pack",
            pack="credits_50",
            total="5000",
            tax="0",
            sub_id=None,
        )
    )
    assert c.post("/webhooks/paddle", content=body, headers=headers).status_code == 200
    assert c.get("/v1/billing/credits", headers=h).json()["balance"] == "50.00"
    credits.consume(db, org_id, Decimal("30.00"), idempotency_key="spend")
    db.commit()
    refund = {
        "event_id": "evt_4",
        "event_type": "adjustment.created",
        "data": {
            "id": "adj_1",
            "action": "refund",
            "status": "approved",
            "transaction_id": "txn_cp",
            "currency_code": "EUR",
            "totals": {"total": "5000"},
        },
    }
    body, headers = paddle_signed(refund)
    assert c.post("/webhooks/paddle", content=body, headers=headers).status_code == 200
    assert c.get("/v1/billing/credits", headers=h).json()["balance"] == "0.00"  # only the unused 20 refunded
    assert db.query(Invoice).filter_by(provider_ref="txn_cp").one().status == "refunded"

    # Portal and cancel go to Paddle; the cancellation lands with the next webhook.
    assert c.post("/v1/billing/portal", headers=h).json()["url"] == "https://customer-portal.paddle.com/x"
    assert c.post("/v1/billing/subscription/cancel", json={}, headers=h).status_code == 200
    assert rec.calls[-1][2] == {"effective_from": "next_billing_period"}
    body, headers = paddle_signed(
        paddle_subscription_event(
            "evt_5", org_id, event_type="subscription.updated", scheduled_cancel="2030-02-01T00:00:00Z"
        )
    )
    c.post("/webhooks/paddle", content=body, headers=headers)
    assert (
        c.get("/v1/billing/subscription", headers=h)
        .json()["subscription"]["cancel_at"]
        .startswith("2030-02-01")
    )
    body, headers = paddle_signed(
        paddle_subscription_event("evt_6", org_id, event_type="subscription.canceled", status="canceled")
    )
    c.post("/webhooks/paddle", content=body, headers=headers)
    sub = c.get("/v1/billing/subscription", headers=h).json()
    assert sub["subscription"] is None and sub["modules"] == []

    # An event for an org we do not know is acknowledged and ignored.
    body, headers = paddle_signed(
        paddle_subscription_event("evt_7", "org_unknown", sub_id="sub_other", customer="ctm_other")
    )
    r = c.post("/webhooks/paddle", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def test_failed_webhook_is_stored_and_retried(db, paddle_env):
    catalog.seed_starter_catalog(db)
    db.commit()
    c = client()
    h = register(c)
    org_id = _org_id(c, h)
    body, headers = paddle_signed(
        paddle_transaction_event(
            "evt_f",
            org_id,
            txn_id="txn_f",
            kind="credit_pack",
            pack="credits_999",
            total="100",
            tax="0",
            sub_id=None,
        )
    )
    r = c.post("/webhooks/paddle", content=body, headers=headers)
    assert r.status_code == 500 and r.json()["status"] == "failed"
    ev = db.query(BillingEvent).filter_by(event_id="evt_f").one()
    assert ev.status == "failed" and "credit pack" in ev.error
    assert db.query(Invoice).count() == 0  # the half-applied change was rolled back
    # The operator adds the missing pack; Paddle retries the same event and it applies.
    catalog.seed_starter_catalog(db)
    from arbiter.models import CreditPack

    db.add(CreditPack(key="credits_999", name="Test", credit_amount=Decimal("1.00"), price=Decimal("1.00")))
    db.commit()
    r = c.post("/webhooks/paddle", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert c.get("/v1/billing/credits", headers=h).json()["balance"] == "1.00"


def test_period_close_overage_credit_first_then_paddle_charge(db, paddle_env, mock_http):
    catalog.seed_starter_catalog(db)
    db.commit()
    rec = mock_http({("POST", "/subscriptions/sub_01test/charge"): (200, {"data": {"id": "sub_01test"}})})
    c = client()
    h = register(c)
    org_id = _org_id(c, h)
    body, headers = paddle_signed(paddle_subscription_event("evt_s", org_id, plan="starter"))
    c.post("/webhooks/paddle", content=body, headers=headers)
    # Starter includes 50 000 words and 500 AI units; 60 000 words and 600 units were used.
    usage.record(db, org_id, None, "word", 60_000, Decimal("0"), "w1", period="2025-12")
    usage.record(db, org_id, None, "ai_unit", Decimal("600"), Decimal("0"), "a1", period="2025-12")
    credits.add_lot(db, org_id, Decimal("100.00"), kind="grant", idempotency_key="g1", ref="promo")
    db.commit()
    admin = _admin(c, db)
    assert (
        c.post("/v1/admin/billing/close-period", json={"period": "2999-01"}, headers=admin).status_code == 422
    )
    r = c.post("/v1/admin/billing/close-period", json={"period": "2025-12"}, headers=admin)
    assert r.status_code == 200, r.text
    res = next(o for o in r.json()["orgs"] if o["org_id"] == org_id)
    # 10 000 words * 0.015 = 150.00, 100 units * 0.04 = 4.00 -> 154.00; 100.00 credit first.
    assert (res["status"], res["covered_by_credit"], res["due"]) == ("charged", "100.00", "54.00")
    charge = rec.calls[-1][2]
    assert charge["items"][0]["price"]["unit_price"]["amount"] == "5400"
    inv_id = res["invoice"]["id"]
    assert charge["items"][0]["price"]["custom_data"]["invoice_id"] == inv_id
    # Closing again moves nothing.
    again = c.post(
        "/v1/admin/billing/close-period", json={"period": "2025-12", "org_id": org_id}, headers=admin
    )
    assert again.json()["orgs"][0]["status"] == "already_closed"
    assert len([x for x in rec.calls if x[1].endswith("/charge")]) == 1
    assert c.get("/v1/billing/credits", headers=h).json()["balance"] == "0.00"
    # Paddle's payment of the charge settles our overage record.
    body, headers = paddle_signed(
        paddle_transaction_event(
            "evt_ch", org_id, txn_id="txn_ch", kind="overage", total="6534", tax="1134", invoice_id=inv_id
        )
    )
    c.post("/webhooks/paddle", content=body, headers=headers)
    inv = db.get(Invoice, inv_id)
    db.refresh(inv)
    assert inv.status == "paid" and inv.provider_ref == "txn_ch" and inv.kind == "overage"


def test_admin_plans_editor_and_org_override(db):
    catalog.seed_starter_catalog(db)
    db.commit()
    c = client()
    h = register(c)
    org_id = _org_id(c, h)
    admin = _admin(c, db)
    plans = c.get("/v1/admin/plans", headers=admin).json()
    assert plans["providers"]["paddle"]["configured"] is False and plans["providers"]["manual"]["configured"]
    r = c.post(
        "/v1/admin/plans",
        headers=admin,
        json={
            "key": "agency",
            "name": "Agency",
            "modules": ["pm"],
            "prices": {"month": {"EUR": "99.00"}},
            "included": {"word": "10000"},
            "overage": {"EUR": {"word": "0.02"}},
            "public": False,
        },
    )
    assert r.status_code == 201, r.text
    assert c.post("/v1/admin/plans", headers=admin, json={"key": "agency", "name": "Dup"}).status_code == 409
    assert "agency" not in [p["key"] for p in c.get("/v1/billing/plans").json()["items"]]  # hidden
    r = c.patch(
        "/v1/admin/plans/agency", headers=admin, json={"public": True, "prices": {"month": {"EUR": "89"}}}
    )
    assert r.json()["prices"] == {"month": {"EUR": "89.00"}} and r.json()["public"] is True
    assert c.patch("/v1/admin/plans/agency", headers=admin, json={"modules": ["bogus"]}).status_code == 422

    r = c.post(
        f"/v1/admin/orgs/{org_id}/subscription",
        headers=admin,
        json={
            "plan": "enterprise",
            "seats": 80,
            "modules_remove": ["strings"],
            "platform_fee_percent": "3",
            "payment_terms_days": 30,
            "po_number": "PO-123",
            "provider": "manual",
            "note": "contract",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["subscription"]["provider"] == "admin" and out["subscription"]["seats"] == 80
    assert "strings" not in out["modules"] and "engine" in out["modules"]
    assert (
        out["platform_fee_percent"] == "3"
        and out["payment_terms_days"] == 30
        and out["po_number"] == "PO-123"
    )
    assert out["provider"] == "manual"
    bad = c.post(f"/v1/admin/orgs/{org_id}/subscription", headers=admin, json={"platform_fee_percent": "12"})
    assert bad.status_code == 422
    grant = c.post(
        f"/v1/admin/orgs/{org_id}/credits",
        headers=admin,
        json={"amount": "25.00", "idempotency_key": "welcome-1"},
    )
    assert grant.status_code == 201 and grant.json()["balance"] == "25.00"
    c.post(
        f"/v1/admin/orgs/{org_id}/credits",
        headers=admin,
        json={"amount": "25.00", "idempotency_key": "welcome-1"},
    )
    assert c.get("/v1/billing/credits", headers=h).json()["balance"] == "25.00"  # granted once
    r = c.post(f"/v1/admin/orgs/{org_id}/subscription", headers=admin, json={"status": "canceled"})
    assert r.json()["subscription"] is None
    assert c.get("/v1/admin/billing/events", headers=admin).status_code == 200


def test_period_close_manual_subscription_issues_our_invoice(db):
    catalog.seed_starter_catalog(db)
    db.commit()
    c = client()
    h = register(c)
    org_id = _org_id(c, h)
    admin = _admin(c, db)
    c.post(f"/v1/admin/orgs/{org_id}/subscription", headers=admin, json={"plan": "starter"})
    usage.record(db, org_id, None, "word", 51_000, Decimal("0"), "mw1", period="2025-11")
    db.commit()
    r = c.post("/v1/admin/billing/close-period", json={"period": "2025-11", "org_id": org_id}, headers=admin)
    res = r.json()["orgs"][0]
    assert res["status"] == "charged" and res["due"] == "15.00"  # 1 000 words * 0.015
    inv = res["invoice"]
    assert inv["issued_by"] == "us" and inv["number"].startswith("ARB-") and inv["kind"] == "overage"
    assert inv["period"] == "2025-11" and inv["total"] == "15.00" and inv["status"] == "issued"
    assert inv["lines"][0]["unit"] == "word" and inv["lines"][0]["included"] == "50000"
    again = c.post(
        "/v1/admin/billing/close-period", json={"period": "2025-11", "org_id": org_id}, headers=admin
    )
    assert again.json()["orgs"][0]["status"] == "already_closed"
    assert c.post(f"/v1/admin/invoices/{inv['id']}/mark-paid", headers=admin).json()["status"] == "paid"
