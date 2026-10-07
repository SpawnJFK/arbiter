"""Price lists: rate lookup order, CRUD, quotes with an account's price list."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from agency_helpers import client, project, quote, register, upload

from arbiter.agency import pricelists
from arbiter.models import PriceList

RATES = [
    {"source_lang": "en", "target_lang": "de", "tier": "hybrid", "per_word": "0.10"},
    {"target_lang": "de", "tier": "hybrid", "per_word": "0.09"},
    {"tier": "hybrid", "per_word": "0.08"},
    {"source_lang": "fr", "tier": "auto", "per_word": "0.01"},
]


def test_rate_lookup_order_pair_target_tier_org_default():
    pl = PriceList(name="t", currency="EUR", rates=pricelists._rates([pricelists.RateIn(**r) for r in RATES]))
    assert pricelists.rate_for(pl, "en", "de", "hybrid") == (Decimal("0.1"), "pair")
    assert pricelists.rate_for(pl, "fr", "de", "hybrid") == (Decimal("0.09"), "target")
    assert pricelists.rate_for(pl, "EN", "DE", "hybrid") == (Decimal("0.1"), "pair")
    assert pricelists.rate_for(pl, "en", "sr", "hybrid") == (Decimal("0.08"), "tier")
    assert pricelists.rate_for(pl, "fr", "sr", "auto") == (Decimal("0.01"), "tier")
    rate, rule = pricelists.rate_for(pl, "en", "sr", "auto")
    assert rule == "org_default" and rate == Decimal("0.02")
    assert pricelists.rate_for(pl, "en", "sr", "full")[1] == "org_default"


def test_price_list_crud_and_validation(db):
    c = client()
    h = register(c)
    r = c.post(
        "/v1/price-lists",
        headers=h,
        json={
            "name": "Standard",
            "currency": "usd",
            "rates": RATES,
            "tm_weights": {"exact": "0.2", "fuzzy_95": 0.4},
            "minimum_charge": "25",
        },
    )
    assert r.status_code == 201, r.text
    pl = r.json()
    assert pl["currency"] == "USD" and pl["minimum_charge"] == "25.00"
    assert pl["rates"][0] == {"source_lang": "en", "target_lang": "de", "tier": "hybrid", "per_word": "0.1"}
    assert pl["tm_weights"] == {"exact": "0.2", "fuzzy_95": "0.4"}
    bad = [
        {"name": "x", "rates": []},
        {"name": "x", "rates": [{"tier": "gold", "per_word": "0.1"}]},
        {"name": "x", "rates": [{"tier": "full", "per_word": "-1"}]},
        {"name": "x", "rates": [{"tier": "full", "per_word": "0.1"}, {"tier": "full", "per_word": "0.2"}]},
        {"name": "x", "rates": [{"tier": "full", "per_word": "0.1"}], "tm_weights": {"fuzzy_50": "1"}},
    ]
    for body in bad:
        assert c.post("/v1/price-lists", headers=h, json=body).status_code == 422, body
    r = c.patch(f"/v1/price-lists/{pl['id']}", headers=h, json={"name": "Std 2026", "minimum_charge": None})
    assert r.json()["name"] == "Std 2026" and r.json()["minimum_charge"] is None
    assert [x["name"] for x in c.get("/v1/price-lists", headers=h).json()["items"]] == ["Std 2026"]
    assert c.delete(f"/v1/price-lists/{pl['id']}", headers=h).json()["archived"] is True
    assert c.get("/v1/price-lists", headers=h).json()["items"] == []
    assert len(c.get("/v1/price-lists?include_archived=true", headers=h).json()["items"]) == 1
    hb = register(c, "b@example.com", "Other")
    assert c.get(f"/v1/price-lists/{pl['id']}", headers=hb).status_code == 404


def test_quote_uses_account_price_list(db):
    c = client()
    h = register(c)
    pl = c.post(
        "/v1/price-lists",
        headers=h,
        json={
            "name": "Client rates",
            "currency": "USD",
            "rates": [
                {"tier": "full", "per_word": "0.30"},
                {"target_lang": "sr", "tier": "hybrid", "per_word": "0.25"},
            ],
            "tm_weights": {"new": "1.0"},
        },
    ).json()
    acc = c.post("/v1/crm/accounts", headers=h, json={"name": "Acme", "price_list_id": pl["id"]}).json()
    f = upload(c, h)
    plain = quote(c, h, f["id"])
    q = quote(c, h, f["id"], account_id=acc["id"])
    assert q["currency"] == "USD" and q["account_id"] == acc["id"] and q["price_list_id"] == pl["id"]
    assert plain["currency"] == "EUR" and plain["account_id"] is None
    ww = Decimal(q["analysis"]["weighted_words"])
    expect_full = max(Decimal("5.00"), (ww * Decimal("0.30")).quantize(Decimal("0.01"), ROUND_HALF_UP))
    assert q["tiers"]["full"]["price"] == str(expect_full)
    assert q["tiers"]["full"]["rate_per_word"] == "0.3"
    assert q["tiers"]["hybrid"]["rates_by_lang"]["sr"] == {"per_word": "0.25", "rule": "target"}
    # no auto rate in the price list -> org default for that tier
    assert q["tiers"]["auto"]["price"] == plain["tiers"]["auto"]["price"]
    assert q["tiers"]["auto"]["rates_by_lang"]["sr"]["rule"] == "org_default"
    assert q["tiers"]["full"]["price"] != plain["tiers"]["full"]["price"]

    # the project inherits the account from the quote
    prj = project(c, h, q["id"], tier="full")
    assert prj["account_id"] == acc["id"]
    assert prj["jobs"][0]["account_id"] == acc["id"]
    assert prj["jobs"][0]["revenue"] == q["tiers"]["full"]["price"]
    detail = c.get(f"/v1/crm/accounts/{acc['id']}", headers=h).json()
    assert detail["stats"]["projects"] == 1 and detail["stats"]["jobs_active"] == 1


def test_quote_minimum_charge_and_foreign_account(db):
    c = client()
    h = register(c)
    pl = c.post(
        "/v1/price-lists",
        headers=h,
        json={"name": "Min", "rates": [{"tier": "full", "per_word": "0.01"}], "minimum_charge": "50"},
    ).json()
    acc = c.post("/v1/crm/accounts", headers=h, json={"name": "Acme", "price_list_id": pl["id"]}).json()
    f = upload(c, h)
    q = quote(c, h, f["id"], account_id=acc["id"])
    assert q["tiers"]["full"]["price"] == "50.00"
    hb = register(c, "b@example.com", "Other")
    fb = upload(c, hb)
    r = c.post(
        "/v1/quotes", headers=hb, json={"file_id": fb["id"], "target_langs": ["sr"], "account_id": acc["id"]}
    )
    assert r.status_code == 404
