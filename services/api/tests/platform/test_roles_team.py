"""Custom roles, team management, invites, privilege-escalation guards, tenancy."""

from __future__ import annotations

from types import SimpleNamespace

from platform_helpers import PW, client, invite_and_accept, login, register

from arbiter.platform.permissions import cannot_grant, covers, has_permission


def test_permission_patterns_and_explicit_only():
    assert covers("*", "*") and covers("jobs.*", "jobs.write") and covers("*.read", "jobs.read")
    assert (
        not covers("jobs.write", "jobs.*")
        and not covers("*.read", "*")
        and not covers("*.read", "audit.read")
    )
    client_role = SimpleNamespace(role="client")
    assert not has_permission(client_role, "audit.read")  # "*.read" does not open the audit log
    assert has_permission(SimpleNamespace(role="pm"), "audit.read")
    assert has_permission(SimpleNamespace(role="client", permissions=["audit.*"]), "audit.read")
    # an empty custom role grants nothing (it does not fall back to the base role)
    assert not has_permission(SimpleNamespace(role="pm", permissions=[]), "jobs.read")
    assert cannot_grant(SimpleNamespace(role="pm"), ["jobs.write", "*"]) == ["*"]


def test_role_crud_and_member_count(db):
    c = client()
    pm = register(c)
    r = c.get("/v1/roles", headers=pm)
    assert (
        r.status_code == 200
        and r.json()["items"] == []
        and any(x["key"] == "audit.read" for x in r.json()["catalog"])
    )
    r = c.post(
        "/v1/roles",
        headers=pm,
        json={
            "name": "Auditor",
            "base_role": "client",
            "permissions": ["audit.read", "jobs.read", "jobs.read"],
        },
    )
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["permissions"] == ["audit.read", "jobs.read"]
    assert c.post("/v1/roles", headers=pm, json={"name": "auditor"}).status_code == 409
    assert (
        c.post("/v1/roles", headers=pm, json={"name": "Bad", "permissions": ["Not A Perm"]}).status_code
        == 422
    )

    member = invite_and_accept(c, pm, "aud@example.com", role_id=role["id"])
    me = c.get("/v1/me", headers=member).json()
    assert me["user"]["role"] == "client" and me["user"]["role_id"] == role["id"]
    assert me["permissions"] == ["audit.read", "jobs.read"]
    assert c.get("/v1/audit", headers=member).status_code == 200  # custom role opens the audit log
    assert c.get("/v1/users", headers=member).status_code == 403  # but not the team list

    assert c.get("/v1/roles", headers=pm).json()["items"][0]["members"] == 1
    assert c.delete(f"/v1/roles/{role['id']}", headers=pm).status_code == 409  # in use

    r = c.patch(f"/v1/roles/{role['id']}", headers=pm, json={"permissions": ["users.read"]})
    assert r.status_code == 200 and r.json()["permissions"] == ["users.read"]
    assert c.get("/v1/audit", headers=member).status_code == 403
    assert c.get("/v1/users", headers=member).status_code == 200


def test_client_cannot_manage_roles_or_escalate(db):
    c = client()
    pm = register(c)
    cl = invite_and_accept(c, pm, "client@example.com", role="client")
    assert c.post("/v1/roles", headers=cl, json={"name": "X"}).status_code == 403
    assert c.post("/v1/users/invite", headers=cl, json={"email": "x@example.com"}).status_code == 403

    # a custom role that may manage roles still cannot hand out what it does not hold
    r = c.post(
        "/v1/roles",
        headers=pm,
        json={"name": "Role admin", "base_role": "client", "permissions": ["roles.write", "users.read"]},
    )
    ra = invite_and_accept(c, pm, "ra@example.com", role_id=r.json()["id"])
    r = c.post("/v1/roles", headers=ra, json={"name": "Sneaky", "permissions": ["billing.manage"]})
    assert r.status_code == 403 and r.json()["error"]["details"]["permissions"] == ["billing.manage"]
    r = c.post(
        "/v1/roles", headers=ra, json={"name": "Sneaky pm", "base_role": "pm", "permissions": ["users.read"]}
    )
    assert r.status_code == 403
    assert c.post("/v1/roles", headers=pm, json={"name": "God", "permissions": ["*"]}).status_code == 403


def test_team_list_invite_patch_deactivate(db):
    c = client()
    pm = register(c)
    r = c.post(
        "/v1/users/invite", headers=pm, json={"email": "New@Example.com", "name": "New", "role": "client"}
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["user"]["status"] == "invited" and out["user"]["email"] == "new@example.com"
    assert out["invite_url"].endswith(out["invite_token"]) and out["email_sent"] is False
    assert c.post("/v1/users/invite", headers=pm, json={"email": "new@example.com"}).status_code == 409

    # an invited user cannot log in before accepting
    assert c.post("/v1/auth/login", json={"email": "new@example.com", "password": PW}).status_code == 401
    r = c.post("/v1/auth/invite/accept", json={"token": out["invite_token"], "password": PW})
    assert r.status_code == 200
    assert (
        c.post("/v1/auth/invite/accept", json={"token": out["invite_token"], "password": PW}).status_code
        == 404
    )
    login(c, "new@example.com")

    users = c.get("/v1/users", headers=pm).json()["items"]
    assert [u["status"] for u in users] == ["active", "active"]
    uid = users[1]["id"]
    r = c.patch(f"/v1/users/{uid}", headers=pm, json={"role": "pm", "name": "Promoted"})
    assert r.status_code == 200 and r.json()["role"] == "pm" and r.json()["name"] == "Promoted"

    assert c.delete(f"/v1/users/{uid}", headers=pm).status_code == 204
    assert c.get("/v1/users", headers=pm).json()["items"][1]["status"] == "deactivated"
    assert c.post("/v1/auth/login", json={"email": "new@example.com", "password": PW}).status_code == 401
    r = c.patch(f"/v1/users/{uid}", headers=pm, json={"is_active": True})
    assert r.status_code == 200 and r.json()["status"] == "active"


def test_lockout_guards(db):
    c = client()
    pm = register(c)
    me = c.get("/v1/me", headers=pm).json()["user"]["id"]
    assert c.patch(f"/v1/users/{me}", headers=pm, json={"role": "client"}).status_code == 422
    assert c.delete(f"/v1/users/{me}", headers=pm).status_code == 422
    # a second pm demoting the only other pm is fine, but not the last one
    pm2 = invite_and_accept(c, pm, "pm2@example.com", role="pm")
    assert c.patch(f"/v1/users/{me}", headers=pm2, json={"role": "client"}).status_code == 200
    pm2_id = c.get("/v1/me", headers=pm2).json()["user"]["id"]
    r = c.post(
        "/v1/roles",
        headers=pm2,
        json={"name": "Team lead", "base_role": "client", "permissions": ["users.write"]},
    )
    assert r.status_code == 201
    # the last pm cannot be deactivated by anyone else either
    lead = invite_and_accept(c, pm2, "lead@example.com", role_id=r.json()["id"])
    r = c.delete(f"/v1/users/{pm2_id}", headers=lead)
    assert r.status_code == 409 and "at least one active project manager" in r.json()["error"]["message"]


def test_api_keys_cannot_manage_team_and_tenancy_is_404(db):
    c = client()
    a = register(c, "a@example.com", "Org A")
    b = register(c, "b@example.com", "Org B")
    key = c.post("/v1/api-keys", headers=a, json={"name": "ci"}).json()["key"]
    kh = {"Authorization": f"Bearer {key}"}
    assert c.post("/v1/users/invite", headers=kh, json={"email": "k@example.com"}).status_code == 403
    assert c.post("/v1/roles", headers=kh, json={"name": "K"}).status_code == 403

    role = c.post("/v1/roles", headers=a, json={"name": "A role"}).json()
    b_user = c.get("/v1/me", headers=b).json()["user"]["id"]
    assert c.patch(f"/v1/roles/{role['id']}", headers=b, json={"name": "x"}).status_code == 404
    assert c.delete(f"/v1/roles/{role['id']}", headers=b).status_code == 404
    assert c.patch(f"/v1/users/{b_user}", headers=a, json={"name": "x"}).status_code == 404
    assert (
        c.post(
            "/v1/users/invite", headers=b, json={"email": "z@example.com", "role_id": role["id"]}
        ).status_code
        == 404
    )
    assert [u["email"] for u in c.get("/v1/users", headers=b).json()["items"]] == ["b@example.com"]


def test_clearing_custom_role_keeps_base_and_delete_role(db):
    c = client()
    pm = register(c)
    role = c.post("/v1/roles", headers=pm, json={"name": "R", "permissions": ["jobs.read"]}).json()
    invite_and_accept(c, pm, "m@example.com", role_id=role["id"])
    uid = c.get("/v1/users", headers=pm).json()["items"][1]["id"]
    r = c.patch(f"/v1/users/{uid}", headers=pm, json={"role_id": None})
    assert r.status_code == 200 and r.json()["role_id"] is None and r.json()["role"] == "client"
    assert c.delete(f"/v1/roles/{role['id']}", headers=pm).status_code == 204
    assert c.get("/v1/roles", headers=pm).json()["items"] == []
