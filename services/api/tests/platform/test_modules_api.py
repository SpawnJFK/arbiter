"""Module entitlements: GET /org/modules, admin PUT, route gating (404 module_disabled)."""

from __future__ import annotations

from platform_helpers import admin, client, org_id, register
from sqlalchemy import select

from arbiter.models import AuditEvent
from arbiter.platform.modules import MODULES


def test_defaults_all_modules_and_me_carries_them(db):
    c = client()
    h = register(c)
    r = c.get("/v1/org/modules", headers=h)
    assert r.status_code == 200
    assert r.json()["enabled"] == list(MODULES)
    assert {m["key"] for m in r.json()["catalog"]} == set(MODULES)
    me = c.get("/v1/me", headers=h).json()
    assert me["org"]["modules"] == list(MODULES)
    assert "audit.read" in me["permissions"] or "*.read" in me["permissions"]


def test_disabling_pm_hides_pm_routes_and_keeps_tms(db):
    c = client()
    h = register(c)
    ops = admin(c, db)
    oid = org_id(c, h)
    assert c.get("/v1/crm/accounts", headers=h).status_code == 200

    r = c.put(f"/v1/admin/orgs/{oid}/modules", headers=ops, json={"modules": ["tms", "ai"]})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] == ["tms", "ai"]

    for path in (
        "/v1/crm/accounts",
        "/v1/price-lists",
        "/v1/workflows",
        "/v1/dashboards",
        "/v1/assistant/threads",
    ):
        r = c.get(path, headers=h)
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "module_disabled", path
    # tms and ai keep working, and platform routes are never gated
    for path in (
        "/v1/projects",
        "/v1/jobs",
        "/v1/glossaries",
        "/v1/quality/dashboard",
        "/v1/me",
        "/v1/org",
        "/v1/usage",
    ):
        assert c.get(path, headers=h).status_code == 200, path
    assert c.get("/v1/me", headers=h).json()["org"]["modules"] == ["tms", "ai"]

    ev = db.execute(select(AuditEvent).where(AuditEvent.action == "module.changed")).scalar_one()
    assert ev.org_id == oid and ev.data["to"] == ["tms", "ai"] and ev.actor_type == "user"


def test_disabling_tms_hides_tms_routes_and_keeps_pm(db):
    c = client()
    h = register(c)
    ops = admin(c, db)
    oid = org_id(c, h)
    assert c.put(f"/v1/admin/orgs/{oid}/modules", headers=ops, json={"modules": ["pm"]}).status_code == 200
    for path in ("/v1/projects", "/v1/jobs", "/v1/glossaries", "/v1/tm/search?q=x", "/v1/term-questions"):
        r = c.get(path, headers=h)
        assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled", path
    r = c.post("/v1/files", headers=h, files={"file": ("a.md", b"# hi")}, data={"source_lang": "en"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled"
    assert c.get("/v1/quality/dashboard", headers=h).json()["error"]["code"] == "module_disabled"
    assert c.get("/v1/crm/accounts", headers=h).status_code == 200


def test_other_org_is_not_affected(db):
    c = client()
    a = register(c, "a@example.com", "Org A")
    b = register(c, "b@example.com", "Org B")
    ops = admin(c, db)
    c.put(f"/v1/admin/orgs/{org_id(c, a)}/modules", headers=ops, json={"modules": ["tms"]})
    assert c.get("/v1/crm/accounts", headers=a).status_code == 404
    assert c.get("/v1/crm/accounts", headers=b).status_code == 200


def test_invalid_module_lists_are_rejected(db):
    c = client()
    h = register(c)
    ops = admin(c, db)
    oid = org_id(c, h)
    r = c.put(f"/v1/admin/orgs/{oid}/modules", headers=ops, json={"modules": ["strings"]})
    assert r.status_code == 422 and "needs 'tms'" in r.json()["error"]["details"]["problems"][0]
    r = c.put(f"/v1/admin/orgs/{oid}/modules", headers=ops, json={"modules": ["tms", "nope"]})
    assert r.status_code == 422
    assert c.put("/v1/admin/orgs/org_missing/modules", headers=ops, json={"modules": []}).status_code == 404


def test_only_platform_admin_changes_modules(db):
    c = client()
    h = register(c)
    oid = org_id(c, h)
    assert c.put(f"/v1/admin/orgs/{oid}/modules", headers=h, json={"modules": []}).status_code == 403
    ops = admin(c, db)
    r = c.get(f"/v1/admin/orgs/{oid}", headers=ops)
    assert r.status_code == 200 and len(r.json()["catalog"]) == len(MODULES)
    # the admin org list carries modules too
    assert c.get("/v1/admin/orgs", headers=ops).json()["items"][0]["modules"] == list(MODULES)
