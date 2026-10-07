"""CRM over HTTP: accounts, contacts, deals (stage changes), activities, tenancy."""

from __future__ import annotations

from agency_helpers import client, register


def _account(c, h, name="Acme d.o.o.", **extra):
    r = c.post("/v1/crm/accounts", headers=h, json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_account_crud_detail_and_archive(db):
    c = client()
    h = register(c)
    acc = _account(c, h, industry="pharma", country="rs", currency="eur", notes="key client")
    assert acc["status"] == "active" and acc["kind"] == "client"
    assert acc["country"] == "RS" and acc["currency"] == "EUR"
    assert acc["contacts"] == [] and acc["deals"] == [] and acc["recent_activities"] == []
    assert acc["stats"] == {
        "projects": 0,
        "jobs_active": 0,
        "revenue_total": "0.00",
        "revenue_90d": "0.00",
        "margin_90d": "0.00",
    }
    _account(c, h, "Beta Pharma", kind="prospect")
    page = c.get("/v1/crm/accounts", headers=h).json()
    assert [a["name"] for a in page["items"]] == ["Acme d.o.o.", "Beta Pharma"] and page[
        "next_offset"
    ] is None
    assert [a["name"] for a in c.get("/v1/crm/accounts?kind=prospect", headers=h).json()["items"]] == [
        "Beta Pharma"
    ]
    assert [a["name"] for a in c.get("/v1/crm/accounts?q=acme", headers=h).json()["items"]] == ["Acme d.o.o."]

    r = c.patch(f"/v1/crm/accounts/{acc['id']}", headers=h, json={"vat_id": "RS123", "default_tier": "full"})
    assert r.status_code == 200 and r.json()["vat_id"] == "RS123" and r.json()["default_tier"] == "full"
    r = c.patch(f"/v1/crm/accounts/{acc['id']}", headers=h, json={"price_list_id": "prl_nope"})
    assert r.status_code == 422

    r = c.delete(f"/v1/crm/accounts/{acc['id']}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert [a["name"] for a in c.get("/v1/crm/accounts", headers=h).json()["items"]] == ["Beta Pharma"]
    assert len(c.get("/v1/crm/accounts?status=archived", headers=h).json()["items"]) == 1
    # archived accounts still resolve (history keeps pointing at them)
    assert c.get(f"/v1/crm/accounts/{acc['id']}", headers=h).status_code == 200


def test_r_seg_12_regulated_account_cannot_default_to_auto(db):
    c = client()
    h = register(c)
    assert c.patch("/v1/org", headers=h, json={"regulated": True}).status_code == 200
    r = c.post("/v1/crm/accounts", headers=h, json={"name": "Med", "default_tier": "auto"})
    assert r.status_code == 422


def test_contacts_primary_switch_and_delete(db):
    c = client()
    h = register(c)
    acc = _account(c, h)
    r1 = c.post(
        f"/v1/crm/accounts/{acc['id']}/contacts",
        headers=h,
        json={"name": "Ana", "email": "Ana@Acme.example", "is_primary": True},
    )
    assert r1.status_code == 201 and r1.json()["email"] == "ana@acme.example"
    r2 = c.post(
        f"/v1/crm/accounts/{acc['id']}/contacts", headers=h, json={"name": "Bojan", "is_primary": True}
    )
    contacts = c.get(f"/v1/crm/accounts/{acc['id']}/contacts", headers=h).json()["items"]
    assert [(x["name"], x["is_primary"]) for x in contacts] == [("Bojan", True), ("Ana", False)]
    assert (
        c.post(
            f"/v1/crm/accounts/{acc['id']}/contacts", headers=h, json={"name": "X", "email": "bad"}
        ).status_code
        == 422
    )
    r = c.patch(f"/v1/crm/contacts/{r1.json()['id']}", headers=h, json={"role": "Head of marketing"})
    assert r.json()["role"] == "Head of marketing"
    assert c.delete(f"/v1/crm/contacts/{r2.json()['id']}", headers=h).status_code == 204
    detail = c.get(f"/v1/crm/accounts/{acc['id']}", headers=h).json()
    assert [x["name"] for x in detail["contacts"]] == ["Ana"]


def test_deal_stage_changes(db):
    c = client()
    h = register(c)
    acc = _account(c, h)
    r = c.post(
        "/v1/crm/deals",
        headers=h,
        json={
            "account_id": acc["id"],
            "title": "Website localization",
            "value": "1200.5",
            "expected_close": "2026-12-01",
        },
    )
    assert r.status_code == 201, r.text
    deal = r.json()
    assert deal["stage"] == "lead" and deal["value"] == "1200.50" and deal["currency"] == "EUR"
    assert deal["account_name"] == "Acme d.o.o." and deal["closed_at"] is None

    for stage in ("qualified", "proposal", "negotiation"):
        assert (
            c.patch(f"/v1/crm/deals/{deal['id']}", headers=h, json={"stage": stage}).json()["stage"] == stage
        )
    lost = c.patch(
        f"/v1/crm/deals/{deal['id']}", headers=h, json={"stage": "lost", "lost_reason": "price"}
    ).json()
    assert lost["closed_at"] is not None and lost["lost_reason"] == "price"
    reopened = c.patch(f"/v1/crm/deals/{deal['id']}", headers=h, json={"stage": "proposal"}).json()
    assert reopened["closed_at"] is None and reopened["lost_reason"] is None
    won = c.patch(f"/v1/crm/deals/{deal['id']}", headers=h, json={"stage": "won", "value": 1500}).json()
    assert won["closed_at"] is not None and won["value"] == "1500.00"
    assert c.patch(f"/v1/crm/deals/{deal['id']}", headers=h, json={"stage": "signed"}).status_code == 422

    c.post("/v1/crm/deals", headers=h, json={"account_id": acc["id"], "title": "Docs", "value": "300"})
    assert [d["title"] for d in c.get("/v1/crm/deals?stage=won", headers=h).json()["items"]] == [
        "Website localization"
    ]
    assert len(c.get(f"/v1/crm/deals?account_id={acc['id']}", headers=h).json()["items"]) == 2
    assert len(c.get(f"/v1/crm/accounts/{acc['id']}", headers=h).json()["deals"]) == 2
    gone = c.delete(f"/v1/crm/deals/{deal['id']}", headers=h)
    assert gone.status_code == 200 and gone.json()["id"] == deal["id"]
    assert len(c.get("/v1/crm/deals", headers=h).json()["items"]) == 1


def test_activities_open_filter_and_done(db):
    c = client()
    h = register(c)
    acc = _account(c, h)
    deal = c.post(
        "/v1/crm/deals", headers=h, json={"account_id": acc["id"], "title": "T", "value": "1"}
    ).json()
    a1 = c.post(
        "/v1/crm/activities",
        headers=h,
        json={
            "account_id": acc["id"],
            "deal_id": deal["id"],
            "kind": "call",
            "body": "Call back",
            "due_at": "2026-10-10T09:00:00",
        },
    )
    assert a1.status_code == 201, a1.text
    assert a1.json()["due_at"].startswith("2026-10-10T09:00:00") and a1.json()["done"] is False
    c.post(
        "/v1/crm/activities",
        headers=h,
        json={"account_id": acc["id"], "kind": "note", "body": "Met at a fair"},
    )
    assert (
        c.post(
            "/v1/crm/activities", headers=h, json={"account_id": acc["id"], "kind": "fax", "body": "x"}
        ).status_code
        == 422
    )
    assert len(c.get("/v1/crm/activities?open=true", headers=h).json()["items"]) == 2
    done = c.patch(f"/v1/crm/activities/{a1.json()['id']}", headers=h, json={"done": True}).json()
    assert done["done"] is True and done["done_at"] is not None
    assert len(c.get("/v1/crm/activities?open=true", headers=h).json()["items"]) == 1
    assert len(c.get(f"/v1/crm/activities?deal_id={deal['id']}", headers=h).json()["items"]) == 1
    assert len(c.get(f"/v1/crm/accounts/{acc['id']}", headers=h).json()["recent_activities"]) == 2


def test_crm_tenancy(db):
    c = client()
    ha = register(c, "a@example.com", "Org A")
    hb = register(c, "b@example.com", "Org B")
    acc = _account(c, ha)
    contact = c.post(f"/v1/crm/accounts/{acc['id']}/contacts", headers=ha, json={"name": "Ana"}).json()
    deal = c.post(
        "/v1/crm/deals", headers=ha, json={"account_id": acc["id"], "title": "T", "value": "1"}
    ).json()
    act = c.post(
        "/v1/crm/activities", headers=ha, json={"account_id": acc["id"], "kind": "note", "body": "x"}
    ).json()
    assert c.get("/v1/crm/accounts", headers=hb).json()["items"] == []
    assert c.get("/v1/crm/deals", headers=hb).json()["items"] == []
    assert c.get("/v1/crm/activities", headers=hb).json()["items"] == []
    assert c.get(f"/v1/crm/accounts/{acc['id']}", headers=hb).status_code == 404
    assert c.patch(f"/v1/crm/accounts/{acc['id']}", headers=hb, json={"name": "X"}).status_code == 404
    assert c.delete(f"/v1/crm/accounts/{acc['id']}", headers=hb).status_code == 404
    assert c.get(f"/v1/crm/accounts/{acc['id']}/contacts", headers=hb).status_code == 404
    assert c.patch(f"/v1/crm/contacts/{contact['id']}", headers=hb, json={"name": "X"}).status_code == 404
    assert c.patch(f"/v1/crm/deals/{deal['id']}", headers=hb, json={"stage": "won"}).status_code == 404
    assert c.patch(f"/v1/crm/activities/{act['id']}", headers=hb, json={"done": True}).status_code == 404
    # B cannot attach its own records to A's account
    assert (
        c.post(
            "/v1/crm/deals", headers=hb, json={"account_id": acc["id"], "title": "T", "value": "1"}
        ).status_code
        == 404
    )
    assert (
        c.post(
            "/v1/crm/activities", headers=hb, json={"account_id": acc["id"], "kind": "note", "body": "x"}
        ).status_code
        == 404
    )


def test_crm_idempotency_key(db):
    c = client()
    h = register(c)
    hk = {**h, "Idempotency-Key": "acc-1"}
    r1 = c.post("/v1/crm/accounts", headers=hk, json={"name": "Acme"})
    r2 = c.post("/v1/crm/accounts", headers=hk, json={"name": "Acme"})
    assert r1.status_code == r2.status_code == 201 and r1.json()["id"] == r2.json()["id"]
    assert len(c.get("/v1/crm/accounts", headers=h).json()["items"]) == 1
    assert c.post("/v1/crm/accounts", headers=hk, json={"name": "Other"}).status_code == 409
