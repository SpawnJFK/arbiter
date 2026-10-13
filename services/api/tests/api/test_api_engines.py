"""Engine endpoints: catalog, BYOK keys (encrypted, never returned), test probe, routes,
budgets, platform keys, org processing region and module / permission gates."""

from __future__ import annotations

import json

from api_helpers import client, register
from sqlalchemy import select

from arbiter.api import security
from arbiter.engines import probe
from arbiter.models import EngineCredential, Organization, User


def _admin(db) -> dict:
    u = User(
        email="root@example.com", name="Root", password_hash=security.hash_password("x-123456"), role="admin"
    )
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {security.issue_token(u.id, 'admin', None)}"}


def _client_user(db, org_id: str) -> dict:
    u = User(
        email="client@example.com",
        name="C",
        password_hash=security.hash_password("x-123456"),
        role="client",
        org_id=org_id,
    )
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {security.issue_token(u.id, 'client', org_id)}"}


def _org(c, h) -> dict:
    return c.get("/v1/org", headers=h).json()


def test_catalog_lists_providers_prices_and_configuration(db):
    c = client()
    h = register(c)
    r = c.get("/v1/engines/catalog", headers=h)
    assert r.status_code == 200
    items = {i["provider"]: i for i in r.json()["items"]}
    assert {"anthropic", "openai", "deepl", "google", "bedrock", "vertex", "openai_compatible"} <= set(items)
    assert items["bedrock"]["regions"] == ["eu", "us", "global"]
    assert items["deepl"]["capabilities"] == ["mt"] and items["deepl"]["glossary"] is False
    assert items["deepl"]["price"] == {"unit": "1M characters", "input": "25", "output": None}
    assert items["anthropic"]["model_prices"]["claude-opus-5-5"]["output"] == "25"
    assert items["anthropic"]["configured"] == "none"
    assert items["bedrock"]["secret_fields"] == ["access_key_id", "secret_access_key"]
    assert r.json()["processing_region"] == "global"


def test_byok_create_never_returns_secret_and_is_encrypted(db):
    c = client()
    h = register(c)
    r = c.post(
        "/v1/engines",
        headers=h,
        json={"provider": "anthropic", "label": "Our key", "secret": {"api_key": "sk-ant-secret-WXYZ"}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["secret_hint"] == "...WXYZ" and "sk-ant" not in json.dumps(body)
    assert body["scope"] == "org" and body["engine"] == "anthropic"
    row = db.execute(select(EngineCredential)).scalar_one()
    assert "sk-ant" not in row.secret_encrypted
    listing = c.get("/v1/engines", headers=h).json()["items"]
    assert len(listing) == 1 and "sk-ant" not in json.dumps(listing)
    cat = {i["provider"]: i for i in c.get("/v1/engines/catalog", headers=h).json()["items"]}
    assert cat["anthropic"]["configured"] == "org"
    # patch label and secret; secret change resets the test state
    r = c.patch(f"/v1/engines/{body['id']}", headers=h, json={"label": "New", "secret": "sk-ant-2-ABCD"})
    assert r.status_code == 200 and r.json()["secret_hint"] == "...ABCD" and r.json()["label"] == "New"
    # another org cannot see or touch it (404, not 403)
    h2 = register(c, email="other@example.com", org="Other")
    assert c.get("/v1/engines", headers=h2).json()["items"] == []
    assert c.patch(f"/v1/engines/{body['id']}", headers=h2, json={"label": "x"}).status_code == 404
    assert c.delete(f"/v1/engines/{body['id']}", headers=h2).status_code == 404
    assert c.delete(f"/v1/engines/{body['id']}", headers=h).status_code == 204
    assert c.get("/v1/engines", headers=h).json()["items"] == []


def test_credential_validation(db):
    c = client()
    h = register(c)
    bad = [
        {"provider": "nope", "secret": "x"},
        {"provider": "anthropic", "secret": ""},
        {"provider": "bedrock", "secret": {"access_key_id": "A"}},
        {"provider": "vertex", "secret": {"service_account_json": "not json"}},
        {"provider": "openai_compatible", "secret": "k", "config": {"model": "m"}},
        {"provider": "openai_compatible", "secret": "k", "config": {"endpoint": "ftp://x", "model": "m"}},
        {"provider": "anthropic", "secret": "k", "config": {"endpoint": "https://x"}},
        {
            "provider": "openai_compatible",
            "secret": "k",
            "config": {"endpoint": "https://x.example.com/v1", "model": "m", "region": "mars"},
        },
    ]
    for payload in bad:
        r = c.post("/v1/engines", headers=h, json=payload)
        assert r.status_code == 422, (payload, r.text)
    r = c.post(
        "/v1/engines",
        headers=h,
        json={
            "provider": "bedrock",
            "secret": {"access_key_id": "AKID", "secret_access_key": "abcdSECRET9"},
            "config": {"model": "eu.anthropic.claude-opus-5", "aws_region": "eu-central-1"},
        },
    )
    assert r.status_code == 201 and r.json()["secret_hint"] == "...RET9"
    r = c.post(
        "/v1/engines",
        headers=h,
        json={
            "provider": "openai_compatible",
            "label": "EU vLLM",
            "secret": "",
            "config": {"endpoint": "https://llm.example.eu/v1/", "model": "qwen", "region": "eu"},
        },
    )
    assert r.status_code == 201 and r.json()["engine"].startswith("compat:")
    assert r.json()["config"]["endpoint"] == "https://llm.example.eu/v1"


def test_org_endpoint_must_be_public_in_prod(db, monkeypatch):
    from arbiter.config import get_settings

    c = client()
    h = register(c)
    monkeypatch.setattr(get_settings(), "env", "prod")
    for url in ("http://llm.example.com/v1", "https://localhost/v1", "https://10.0.0.5/v1"):
        r = c.post(
            "/v1/engines",
            headers=h,
            json={"provider": "openai_compatible", "secret": "k", "config": {"endpoint": url, "model": "m"}},
        )
        assert r.status_code == 422, url


def test_probe_records_result(db, monkeypatch):
    c = client()
    h = register(c)
    cid = c.post("/v1/engines", headers=h, json={"provider": "deepl", "secret": "dk-1234:fx"}).json()["id"]
    # without a stub the test environment refuses a live call and says so
    r = c.post(f"/v1/engines/{cid}/test", headers=h)
    assert r.status_code == 200 and r.json()["ok"] is False and "test environment" in r.json()["error"]
    seen = {}

    def fake(provider, cred, settings):
        seen["args"] = (provider, cred.secret, cred.source)
        return "deepl-v2 answered"

    monkeypatch.setattr(probe, "run_probe", fake)
    r = c.post(f"/v1/engines/{cid}/test", headers=h)
    assert r.json()["ok"] is True and r.json()["credential"]["last_test_ok"] is True
    assert seen["args"] == ("deepl", "dk-1234:fx", "org")
    assert "dk-1234" not in r.text


def test_routes_and_budgets_crud(db):
    c = client()
    h = register(c)
    r = c.post(
        "/v1/engines/routes",
        headers=h,
        json={
            "purpose": "mt",
            "target_lang": "de",
            "engines": ["deepl", "llm-mt:anthropic"],
            "fallback": False,
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["scope"] == "org" and r.json()["source_lang"] is None
    assert c.post("/v1/engines/routes", headers=h, json={"engines": ["a", "a"]}).status_code == 422
    assert c.post("/v1/engines/routes", headers=h, json={"engines": [], "purpose": "mt"}).status_code == 422
    assert c.post("/v1/engines/routes", headers=h, json={"engines": ["a"], "purpose": "x"}).status_code == 422
    r = c.patch(f"/v1/engines/routes/{rid}", headers=h, json={"engines": ["google"], "enabled": False})
    assert r.json()["engines"] == ["google"] and r.json()["enabled"] is False
    assert len(c.get("/v1/engines/routes", headers=h).json()["items"]) == 1
    h2 = register(c, email="o2@example.com", org="O2")
    assert c.patch(f"/v1/engines/routes/{rid}", headers=h2, json={"enabled": True}).status_code == 404
    assert c.delete(f"/v1/engines/routes/{rid}", headers=h).status_code == 204

    r = c.put("/v1/engines/budgets/anthropic", headers=h, json={"monthly_cap": "250.00"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["monthly_cap"] == "250.00" and b["spent"] == "0.00" and b["exceeded"] is False
    assert c.put("/v1/engines/budgets/nope", headers=h, json={"monthly_cap": "1"}).status_code == 422
    assert c.put("/v1/engines/budgets/deepl", headers=h, json={"monthly_cap": "-1"}).status_code == 422
    assert [x["provider"] for x in c.get("/v1/engines/budgets", headers=h).json()["items"]] == ["anthropic"]
    assert c.delete("/v1/engines/budgets/anthropic", headers=h).status_code == 204
    assert c.delete("/v1/engines/budgets/anthropic", headers=h).status_code == 404


def test_preview_explains_routing(db):
    c = client()
    h = register(c)
    r = c.get("/v1/engines/preview?source_lang=en&target_lang=de", headers=h)
    assert r.status_code == 200
    p = r.json()["purposes"]
    assert p["mt"]["ok"] and p["mt"]["engines"][0] == "mock-mt"
    assert p["judge"]["engines"][0] == "mock-llm"


def test_processing_region_and_training_consent_on_org(db):
    c = client()
    h = register(c)
    o = _org(c, h)
    assert o["processing_region"] == "global" and o["training_consent"] is False
    r = c.patch("/v1/org", headers=h, json={"processing_region": "eu", "training_consent": True})
    assert r.status_code == 200 and r.json()["processing_region"] == "eu" and r.json()["training_consent"]
    assert c.patch("/v1/org", headers=h, json={"processing_region": "mars"}).status_code == 422
    # regulated orgs may use the EU route too
    r = c.patch("/v1/org", headers=h, json={"regulated": True, "processing_region": "eu"})
    assert r.status_code == 200 and r.json()["regulated"] is True
    # the add-on gate: an org whose add-ons exclude it cannot switch it on
    org = db.execute(select(Organization)).scalar_one()
    org.settings = {**org.settings, "addons": ["byok"], "processing_region": "global"}
    db.commit()
    r = c.patch("/v1/org", headers=h, json={"processing_region": "eu"})
    assert r.status_code == 422 and "add-on" in r.json()["error"]["message"]
    r = c.post("/v1/engines/catalog", headers=h)
    assert r.status_code == 405


def test_module_and_permission_gates(db):
    c = client()
    h = register(c)
    org = db.execute(select(Organization)).scalar_one()
    hc = _client_user(db, org.id)
    # a client may read the catalog but not manage keys
    assert c.get("/v1/engines/catalog", headers=hc).status_code == 200
    assert c.get("/v1/engines", headers=hc).status_code == 403
    assert c.post("/v1/engines", headers=hc, json={"provider": "deepl", "secret": "k"}).status_code == 403
    # BYOK add-on off
    org.settings = {"addons": ["eu_processing"]}
    db.commit()
    assert c.post("/v1/engines", headers=h, json={"provider": "deepl", "secret": "k"}).status_code == 422
    # engine module off: the feature does not exist for this org
    org.settings = {"modules": ["tms"]}
    db.commit()
    r = c.get("/v1/engines/catalog", headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled"
    assert c.get("/v1/training/jobs", headers=h).status_code == 404


def test_platform_admin_keys_and_routes(db):
    c = client()
    ha = _admin(db)
    h = register(c)
    assert c.get("/v1/admin/engines", headers=h).status_code == 403
    cat = {i["provider"]: i for i in c.get("/v1/admin/engines/catalog", headers=ha).json()["items"]}
    assert cat["openai_compatible"]["configured"] == "none"
    r = c.post(
        "/v1/admin/engines",
        headers=ha,
        json={
            "provider": "openai_compatible",
            "label": "Internal vLLM",
            "secret": "k-INTL",
            "config": {"endpoint": "http://10.0.0.7:8000/v1", "model": "qwen", "region": "eu"},
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["scope"] == "platform" and r.json()["secret_hint"] == "...INTL"
    pid = r.json()["id"]
    assert len(c.get("/v1/admin/engines", headers=ha).json()["items"]) == 1
    cat = {i["provider"]: i for i in c.get("/v1/admin/engines/catalog", headers=ha).json()["items"]}
    assert cat["openai_compatible"]["configured"] == "platform"
    # org users never see platform keys in their list, but the catalog says one exists
    assert c.get("/v1/engines", headers=h).json()["items"] == []
    cat = {i["provider"]: i for i in c.get("/v1/engines/catalog", headers=h).json()["items"]}
    assert cat["openai_compatible"]["configured"] == "platform"
    # an org cannot patch a platform key
    assert c.patch(f"/v1/engines/{pid}", headers=h, json={"label": "x"}).status_code == 404
    assert c.patch(f"/v1/admin/engines/{pid}", headers=ha, json={"enabled": False}).json()["enabled"] is False
    r = c.post("/v1/admin/engines/routes", headers=ha, json={"purpose": "judge", "engines": ["bedrock"]})
    assert r.status_code == 201 and r.json()["scope"] == "platform"
    assert len(c.get("/v1/admin/engines/routes", headers=ha).json()["items"]) == 1
    assert c.get("/v1/engines/routes", headers=h).json()["items"] == []
    assert c.delete(f"/v1/admin/engines/routes/{r.json()['id']}", headers=ha).status_code == 204
    assert c.delete(f"/v1/admin/engines/{pid}", headers=ha).status_code == 204
