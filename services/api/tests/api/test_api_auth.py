from api_helpers import client, register


def test_register_login_me_and_keys(db):
    c = client()
    h = register(c)
    assert c.get("/v1/me", headers=h).json()["org"]["name"] == "Acme GmbH"
    assert (
        c.post("/v1/auth/login", json={"email": "pm@example.com", "password": "nope-nope"}).status_code == 401
    )
    assert (
        c.post("/v1/auth/login", json={"email": "PM@example.com", "password": "secret-123"}).status_code
        == 200
    )
    r = c.post("/v1/api-keys", json={"name": "ci"}, headers=h)
    key = r.json()["key"]
    kh = {"Authorization": f"Bearer {key}"}
    assert c.get("/v1/org", headers=kh).status_code == 200
    c.delete(f"/v1/api-keys/{r.json()['id']}", headers=h)
    assert c.get("/v1/org", headers=kh).status_code == 401
    assert c.get("/v1/me").json()["error"]["code"] == "unauthorized"


def test_regulated_org_cannot_choose_auto(db):
    c = client()
    h = register(c)
    assert c.patch("/v1/org", json={"regulated": True}, headers=h).json()["default_tier"] == "hybrid"
    assert c.patch("/v1/org", json={"default_tier": "auto"}, headers=h).status_code == 422
