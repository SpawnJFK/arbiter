"""UI string localization store: public reads, admin CRUD, merge/replace, placeholder safety."""

from __future__ import annotations

from api_helpers import client, register

from arbiter.api import security
from arbiter.i18n import placeholders
from arbiter.models import User


def _admin(db) -> dict:
    u = User(
        email="root@example.com", name="Root", password_hash=security.hash_password("x-123456"), role="admin"
    )
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {security.issue_token(u.id, 'admin', None)}"}


def test_placeholders_icu_lite():
    assert placeholders("Hi {name}") == {"name"}
    assert placeholders("{count, plural, one {# job by {user}} other {# jobs}}") == {"count"}
    assert placeholders("Don't '{escaped}' it {x}") == {"x"}
    assert placeholders("nothing here") == set()


def test_locales_crud_and_public_reads(db):
    c = client()
    ha = _admin(db)
    # only the implicit English source exists
    assert c.get("/v1/i18n/locales").json() == {
        "items": [
            {"locale": "en", "name": "English", "enabled": True, "message_count": None, "updated_at": None}
        ]
    }
    r = c.put("/v1/admin/i18n/locales/DE", headers=ha, json={"name": "Deutsch"})
    assert r.status_code == 200 and r.json()["locale"] == "de" and r.json()["enabled"] is False
    r = c.put(
        "/v1/admin/i18n/messages/de",
        headers=ha,
        json={"messages": {"nav.jobs": "Aufträge", "nav.crm": "CRM"}},
    )
    assert r.json() == {"locale": "de", "upserted": 2, "deleted": 0, "total": 2}
    # disabled: hidden from the public, visible to the admin
    assert [x["locale"] for x in c.get("/v1/i18n/locales").json()["items"]] == ["en"]
    assert c.get("/v1/i18n/messages/de").status_code == 404
    admin_list = c.get("/v1/i18n/locales", headers=ha).json()["items"]
    assert [x["locale"] for x in admin_list] == ["en", "de"] and admin_list[1]["message_count"] == 2
    assert c.get("/v1/i18n/messages/de", headers=ha).json()["messages"]["nav.jobs"] == "Aufträge"

    c.put("/v1/admin/i18n/locales/de", headers=ha, json={"name": "Deutsch", "enabled": True})
    c.put("/v1/admin/i18n/locales/pt-br", headers=ha, json={"name": "Português (Brasil)", "enabled": True})
    items = c.get("/v1/i18n/locales").json()["items"]
    assert [(x["locale"], x["message_count"]) for x in items] == [("en", None), ("de", 2), ("pt-BR", 0)]
    assert items[1]["updated_at"]
    r = c.get("/v1/i18n/messages/de")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=60"
    assert r.json() == {"locale": "de", "messages": {"nav.crm": "CRM", "nav.jobs": "Aufträge"}}
    assert c.get("/v1/i18n/messages/en").json() == {"locale": "en", "messages": {}}
    assert c.get("/v1/i18n/messages/xx").status_code == 404
    assert c.get("/v1/i18n/messages/not_a!locale").status_code == 422

    assert c.delete("/v1/admin/i18n/locales/de", headers=ha).status_code == 204
    assert [x["locale"] for x in c.get("/v1/i18n/locales").json()["items"]] == ["en", "pt-BR"]
    assert c.delete("/v1/admin/i18n/locales/de", headers=ha).status_code == 404
    # English is the source and is never stored
    assert c.put("/v1/admin/i18n/locales/en", headers=ha, json={"name": "English"}).status_code == 422
    assert c.put("/v1/admin/i18n/messages/en", headers=ha, json={"messages": {"a": "b"}}).status_code == 422


def test_merge_and_replace_semantics(db):
    c = client()
    ha = _admin(db)
    url = "/v1/admin/i18n/messages/sr-latn"
    r = c.put(url, headers=ha, json={"messages": {"a": "A", "b": "B", "c": "C"}})
    assert r.json() == {"locale": "sr-Latn", "upserted": 3, "deleted": 0, "total": 3}
    # merge: change b, keep c, remove a with an empty value, unchanged value not counted
    r = c.put(url, headers=ha, json={"messages": {"a": "", "b": "B2", "c": "C"}, "mode": "merge"})
    assert r.json() == {"locale": "sr-Latn", "upserted": 1, "deleted": 1, "total": 2}
    # replace: the locale ends with exactly the given keys
    r = c.put(url, headers=ha, json={"messages": {"d": "D"}, "mode": "replace"})
    assert r.json() == {"locale": "sr-Latn", "upserted": 1, "deleted": 2, "total": 1}
    msgs = c.get("/v1/i18n/messages/sr-Latn", headers=ha).json()["messages"]
    assert msgs == {"d": "D"}
    # limits
    assert c.put(url, headers=ha, json={"messages": {"k" * 201: "x"}}).status_code == 422
    assert c.put(url, headers=ha, json={"messages": {"k": "x" * 5001}}).status_code == 422
    assert c.put(url, headers=ha, json={"messages": {}, "mode": "upsert"}).status_code == 422
    assert c.put("/v1/admin/i18n/messages/bad locale", headers=ha, json={"messages": {}}).status_code == 422


def test_placeholder_mismatch_rejected_per_key(db):
    c = client()
    ha = _admin(db)
    source = {
        "jobs.count": "{count, plural, one {# job} other {# jobs}}",
        "hello": "Hello {name}",
        "plain": "Save",
    }
    bad = {
        "jobs.count": "{n, plural, one {# posao} other {# poslova}}",
        "hello": "Zdravo",
        "plain": "Sačuvaj",
    }
    r = c.put("/v1/admin/i18n/messages/sr", headers=ha, json={"messages": bad, "source": source})
    assert r.status_code == 422
    details = r.json()["error"]["details"]["placeholders"]
    assert details == {
        "jobs.count": {"expected": ["count"], "got": ["n"]},
        "hello": {"expected": ["name"], "got": []},
    }
    assert c.get("/v1/i18n/locales", headers=ha).json()["items"][1:] == []  # nothing written
    good = {
        "jobs.count": "{count, plural, one {# posao} few {# posla} other {# poslova}}",
        "hello": "Zdravo {name}",
    }
    r = c.put("/v1/admin/i18n/messages/sr", headers=ha, json={"messages": good, "source": source})
    assert r.status_code == 200 and r.json()["total"] == 2


def test_non_admin_forbidden(db):
    c = client()
    h = register(c)
    assert c.put("/v1/admin/i18n/locales/de", headers=h, json={"name": "Deutsch"}).status_code == 403
    assert c.put("/v1/admin/i18n/messages/de", headers=h, json={"messages": {"a": "b"}}).status_code == 403
    assert c.delete("/v1/admin/i18n/locales/de", headers=h).status_code == 403
    assert c.put("/v1/admin/i18n/locales/de", json={"name": "Deutsch"}).status_code == 401
    # a PM token on the public endpoints gets the public view
    assert c.get("/v1/i18n/locales", headers=h).status_code == 200
