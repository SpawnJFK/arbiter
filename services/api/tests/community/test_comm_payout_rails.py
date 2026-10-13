"""Payout rails: Payoneer onboarding, PayPal batch, bank files, minimums per method (D-073).

Provider HTTP goes to an httpx.MockTransport; nothing leaves the machine.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from comm_helpers import make_reviewer

from arbiter import storage
from arbiter.billing import ledger
from arbiter.billing.providers import base as provider_base
from arbiter.community import payout_accounts, payout_batches, payouts
from arbiter.community.payout_rails import RailRouter
from arbiter.community.payout_rails.bank import BankRail, iban_valid
from arbiter.community.payout_rails.payoneer import PayoneerRail
from arbiter.community.payout_rails.paypal import PayPalRail
from arbiter.config import get_settings
from arbiter.errors import Conflict, Invalid
from arbiter.models import LedgerEntry, Payout

IBAN_OK = "DE89370400440532013000"


class Http:
    def __init__(self, routes):
        self.routes = routes
        self.calls: list[tuple[str, str, object]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = req.content.decode() if req.content else None
        if body and req.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(body)
        self.calls.append((req.method, f"{req.url.host}{req.url.path}", body))
        for (m, p), (status, payload) in self.routes.items():
            if req.method == m and f"{req.url.host}{req.url.path}" == p:
                return httpx.Response(status, json=payload)
        return httpx.Response(404, json={"error": "no mock"})


@pytest.fixture
def http():
    def install(routes):
        h = Http(routes)
        provider_base.transport = httpx.MockTransport(h)
        return h

    yield install
    provider_base.transport = None


def _credit(db, reviewer_id: str, amount: str) -> None:
    ledger.post(
        db,
        credit=ledger.reviewer_account(reviewer_id),
        debit=ledger.REVIEW_COST,
        amount=Decimal(amount),
        kind="review_pay",
        ref="t",
    )


def _ledger_sum(db) -> Decimal:
    return sum((e.amount for e in db.query(LedgerEntry)), Decimal("0"))


def test_iban_and_detail_validation(db):
    assert iban_valid(IBAN_OK) and iban_valid("de89 3704 0044 0532 0130 00")
    assert not iban_valid("DE89370400440532013001") and not iban_valid("XX00 TEST")
    r = make_reviewer(db)
    with pytest.raises(Invalid):
        payout_accounts.setup(db, r, "paypal", {"email": "not-an-email"})
    with pytest.raises(Invalid):
        payout_accounts.setup(db, r, "sepa", {"iban": "DE00123", "account_holder": "A"})
    with pytest.raises(Invalid):
        payout_accounts.setup(db, r, "payoneer", {})  # no Payoneer keys configured
    v = payout_accounts.setup(
        db, r, "sepa", {"iban": IBAN_OK.lower(), "bic": "COBADEFFXXX", "account_holder": "Ana Test"}
    )
    assert v["status"] == "active" and v["details"]["iban"] == "DE89...3000"  # masked
    assert r.payout_method == "sepa" and r.payout_details["iban"] == IBAN_OK
    view = payout_accounts.methods_view(db, r)
    sepa = next(i for i in view["items"] if i["method"] == "sepa")
    assert sepa["selected"] and sepa["available"] and sepa["minimum_payout"] == "0.00"


def test_payoneer_onboarding_blocks_until_active_then_pays(db, http):
    h = http(
        {
            ("POST", "login.sandbox.payoneer.com/api/v2/oauth2/token"): (200, {"access_token": "tok"}),
            ("POST", "api.sandbox.payoneer.com/v4/programs/prg_1/payees/registration-link"): (
                200,
                {"result": {"registration_link": "https://payouts.sandbox.payoneer.com/reg/abc"}},
            ),
        }
    )
    rail = PayoneerRail("cid", "secret", "prg_1", "sandbox")
    rails = RailRouter(
        {"payoneer": rail, "paypal": PayPalRail("", ""), "sepa": BankRail(), "wise": BankRail()}
    )
    r = make_reviewer(db, threshold="10")
    v = payout_accounts.setup(db, r, "payoneer", {}, rails=rails)
    assert v["status"] == "pending" and v["onboarding_url"].endswith("/reg/abc")
    assert h.calls[1][2] == {"payee_id": r.id, "redirect_url": "http://localhost:3000/reviewer/payouts"}

    _credit(db, r.id, "30.00")
    out = payouts.run_payouts(db)
    assert out["blocked"] == 1 and out["created"] == 0
    p = db.query(Payout).filter_by(reviewer_id=r.id).one()
    assert "onboarding" in p.failure_reason

    h.routes[("GET", f"api.sandbox.payoneer.com/v4/programs/prg_1/payees/{r.id}/status")] = (
        200,
        {"result": {"status": {"type": 1, "description": "Active"}}},
    )
    assert payout_accounts.refresh(db, r, "payoneer", rails=rails)["status"] == "active"
    h.routes[("POST", "api.sandbox.payoneer.com/v4/programs/prg_1/masspayouts")] = (
        200,
        {"result": "Payments Created"},
    )
    out = payouts.run_payouts(db, provider=rails)
    assert out["created"] == 1 and out["send"]["pending"] == 1
    sent = h.calls[-1][2]["Payments"][0]
    assert (
        sent["payee_id"] == r.id
        and sent["amount"] == "30.00"
        and sent["client_reference_id"] == p.idempotency_key
    )

    h.routes[("GET", f"api.sandbox.payoneer.com/v4/programs/prg_1/payouts/{p.idempotency_key}/status")] = (
        200,
        {"result": {"status": "Transferred"}},
    )
    assert payouts.refresh_pending(db, rails) == {"checked": 1, "settled": 1, "failed": 0, "pending": 0}
    assert p.state == "settled" and ledger.account_balance(db, ledger.CASH) == Decimal("30.00")
    assert _ledger_sum(db) == 0


def test_paypal_batch_failure_reverses_and_minimum_per_method(db, http):
    h = http(
        {
            ("POST", "api-m.sandbox.paypal.com/v1/oauth2/token"): (200, {"access_token": "pp"}),
            ("POST", "api-m.sandbox.paypal.com/v1/payments/payouts"): (
                201,
                {"batch_header": {"payout_batch_id": "PB1", "batch_status": "PENDING"}},
            ),
            ("GET", "api-m.sandbox.paypal.com/v1/payments/payouts/PB1"): (
                200,
                {"items": [{"transaction_status": "RETURNED"}]},
            ),
        }
    )
    pp = PayPalRail("cid", "secret", "sandbox")
    rails = RailRouter(
        {"payoneer": PayoneerRail("", "", ""), "paypal": pp, "sepa": BankRail(), "wise": BankRail()}
    )
    r = make_reviewer(db, threshold="1")
    payout_accounts.setup(db, r, "paypal", {"email": "ana@example.test"})
    _credit(db, r.id, "3.00")
    assert payout_accounts.effective_threshold(r) == Decimal("5.00")  # PayPal minimum beats the profile
    assert payouts.run_payouts(db, provider=rails)["created"] == 0
    _credit(db, r.id, "4.00")
    out = payouts.run_payouts(db, provider=rails)
    assert out["created"] == 1 and out["send"]["pending"] == 1
    body = h.calls[-1][2]
    p = db.query(Payout).one()
    assert body["sender_batch_header"]["sender_batch_id"] == p.idempotency_key
    assert body["items"][0] == {
        "recipient_type": "EMAIL",
        "amount": {"value": "7.00", "currency": "EUR"},
        "receiver": "ana@example.test",
        "sender_item_id": p.idempotency_key,
        "note": "Review work payout",
    }
    assert p.provider_ref == "paypal:PB1"
    assert payouts.refresh_pending(db, rails)["failed"] == 1
    assert p.state == "failed" and payouts.balance(db, r.id) == Decimal("7.00")  # money owed again
    assert _ledger_sum(db) == 0


def test_bank_batch_pain001_csv_and_settle(db, monkeypatch, tmp_path):
    monkeypatch.setenv("ARBITER_PAYOUT_DEBTOR_NAME", "Platform Operator Test")
    monkeypatch.setenv("ARBITER_PAYOUT_DEBTOR_IBAN", "NL91ABNA0417164300")
    monkeypatch.setenv("ARBITER_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        rails = RailRouter(
            {
                "payoneer": PayoneerRail("", "", ""),
                "paypal": PayPalRail("", ""),
                "sepa": BankRail(),
                "wise": BankRail(),
            }
        )
        a = make_reviewer(db, threshold="1")
        payout_accounts.setup(db, a, "sepa", {"iban": IBAN_OK, "account_holder": "Ana & Co <Test>"})
        b = make_reviewer(db, threshold="1")
        b.payout_details = {"iban": "bad"}
        _credit(db, a.id, "12.50")
        _credit(db, b.id, "8.00")
        out = payouts.run_payouts(db, provider=rails)
        assert out["send"] == {"sent": 2, "settled": 0, "failed": 1, "pending": 1}  # b: invalid IBAN
        with pytest.raises(Invalid):
            payout_batches.build_batch(db, "pdf")
        batch = payout_batches.build_batch(db, "pain001")
        assert batch["item_count"] == 1 and batch["total"] == "12.50"
        data, media, name = payout_batches.batch_file(db, batch["id"])
        xml = data.decode()
        assert media == "application/xml" and name.endswith(".xml")
        assert "pain.001.001.09" in xml and IBAN_OK in xml and "<CtrlSum>12.50</CtrlSum>" in xml
        assert "Ana &amp; Co &lt;Test&gt;" in xml and "NL91ABNA0417164300" in xml
        with pytest.raises(Conflict):
            payout_batches.build_batch(db, "csv")  # nothing left to batch
        assert payouts.refresh_pending(db, rails)["checked"] == 0  # bank payouts are not polled
        res = payout_batches.settle_batch(db, batch["id"])
        assert res["settled"] == 1
        pa = db.query(Payout).filter_by(reviewer_id=a.id).one()
        assert pa.state == "settled"
        assert storage.get(_key(db, batch["id"])) == data
        assert _ledger_sum(db) == 0
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def _key(db, batch_id: str) -> str:
    from arbiter.models import PayoutBatch

    return db.get(PayoutBatch, batch_id).storage_key


def test_reviewer_payout_method_api(db):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
    from api_helpers import client

    c = client()
    r = c.post(
        "/v1/reviewers/apply",
        json={
            "name": "Ana Test",
            "email": "ana-rails@example.com",
            "password": "long enough pw",
            "country": "RS",
            "pairs": [{"source_lang": "en", "target_lang": "sr"}],
            "domains": ["software"],
        },
    )
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    view = c.get("/v1/reviewer/payout-methods", headers=h).json()
    assert [i["method"] for i in view["items"]] == ["payoneer", "paypal", "sepa", "wise"]
    assert view["selected"] is None
    assert c.post("/v1/reviewer/payout-accounts", json={"method": "cash"}, headers=h).status_code == 422
    r = c.post(
        "/v1/reviewer/payout-accounts",
        json={"method": "wise", "details": {"email": "ana@example.test", "account_holder": "Ana"}},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert c.get("/v1/reviewer/me", headers=h).json()["payout_method"] == "wise"
    assert c.post("/v1/reviewer/payout-accounts/wise/refresh", headers=h).status_code == 200
    assert c.post("/v1/reviewer/payout-accounts/paypal/refresh", headers=h).status_code == 404
