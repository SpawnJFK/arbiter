"""Software strings through the API: projects, push/pull, QA, translate batches, branches, bulk,
module gate and tenancy (R-STR-*). Mock providers only."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select, text
from str_helpers import FIX, client, keys, project, push, register, run_worker

from arbiter.models import Organization, StringHistory, StringTranslation, TmEntry


def test_project_crud_tenancy_and_module_gate(db):
    c = client()
    h = register(c)
    p = project(c, h, target_langs=["de", "pt_br"])
    assert p["target_langs"] == ["de", "pt-BR"]
    assert p["public_id"].startswith("sp") and p["public_id"] != p["id"]
    assert p["stats"]["keys"] == 0
    assert c.get("/v1/strings/projects", headers=h).json()["items"][0]["id"] == p["id"]
    r = c.patch(f"/v1/strings/projects/{p['id']}", json={"settings": {"human_review": True}}, headers=h)
    assert r.json()["settings"]["human_review"] is True
    bad = c.patch(f"/v1/strings/projects/{p['id']}", json={"settings": {"nope": 1}}, headers=h)
    assert bad.status_code == 422

    # R-STR-01: another org gets 404
    other = register(c, email="other@example.com", org="Other Fictional Co")
    assert c.get(f"/v1/strings/projects/{p['id']}", headers=other).status_code == 404

    # module gate: an org without `strings` gets 404 module_disabled
    org = db.execute(select(Organization).where(Organization.name == "Other Fictional Co")).scalar_one()
    org.settings = {"modules": ["tms", "engine", "ai"]}
    db.commit()
    r = c.get("/v1/strings/projects", headers=other)
    assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled"


def test_regulated_org_cannot_use_auto(db):
    c = client()
    h = register(c)
    db.execute(text("UPDATE organizations SET regulated = true"))
    db.commit()
    r = c.post(
        "/v1/strings/projects",
        json={"name": "x", "base_lang": "en", "target_langs": ["de"], "tier": "auto"},
        headers=h,
    )
    assert r.status_code == 422  # R-STR-07


def test_push_base_and_target_then_pull(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    res = push(c, h, pid, "en.json", (FIX / "en.json").read_bytes())
    assert res["format"] == "json" and res["created"] == 6
    ks = keys(c, h, pid)
    assert ks["home.files"]["kind"] == "plural"
    assert ks["home.greeting"]["placeholders"] == ["{name}"]
    assert ks["home.files"]["plural_forms"]["ru"] == ["one", "few", "many", "other"]

    de = {
        "app.title": "Acme Notizen",
        "home.greeting": "Hallo {name}, willkommen zurück!",
        "home.summary": "Du hast ungelesene Nachrichten in {ordner}.",  # placeholders changed
        "home.files": "{count, plural, =0 {Noch keine Dateien} one {# Datei} other {# Dateien}}",
    }
    res = push(c, h, pid, "de.json", json.dumps(de).encode(), lang="de")
    assert res["updated"] == 4 and res["blocked"] == 1
    ks = keys(c, h, pid)
    summary = ks["home.summary"]["translations"]["de"]
    assert summary["blocked"] is True
    assert {i["code"] for i in summary["qa"]} >= {"placeholder_changed"}
    assert ks["home.greeting"]["translations"]["de"]["state"] == "reviewed"

    # pull leaves the blocked translation out unless asked
    out = c.get(f"/v1/strings/projects/{pid}/pull", params={"lang": "de", "format": "json"}, headers=h)
    assert out.status_code == 200
    data = json.loads(out.content)
    assert "home.summary" not in data and data["app.title"] == "Acme Notizen"
    assert data["home.files"].startswith("{count, plural, =0 {Noch keine Dateien}")
    # fallback fills gaps with base text
    out = c.get(f"/v1/strings/projects/{pid}/pull", params={"lang": "de", "fallback": True}, headers=h)
    assert json.loads(out.content)["settings.price"] == "Price: {amount, number, ::currency/EUR}"

    # pushing the same file again changes nothing (no version bump)
    res = push(c, h, pid, "de.json", json.dumps(de).encode(), lang="de")
    assert res["unchanged"] == 4 and res["updated"] == 0


def test_xliff_handoff_never_touches_base(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "strings.xml", (FIX / "strings.xml").read_bytes())
    x = c.get(f"/v1/strings/projects/{pid}/pull", params={"lang": "de", "format": "xliff21"}, headers=h)
    assert x.status_code == 200 and b'srcLang="en"' in x.content and b"app_name" not in x.content
    translated = x.content.replace(
        b"<source>Welcome, %1$s!</source>",
        b"<source>EDITED SOURCE</source><target>Willkommen, %1$s!</target>",
    )
    res = push(c, h, pid, "notes.xlf", translated, lang="de")
    assert res["format"] == "xliff21"
    ks = keys(c, h, pid)
    assert ks["welcome_title"]["translations"]["de"]["value"] == "Willkommen, %1$s!"
    assert ks["welcome_title"]["translations"]["en"]["value"] == "Welcome, %1$s!"  # R-STR-06


def test_android_pull_escapes_and_plurals(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "strings.xml", (FIX / "strings.xml").read_bytes())
    ks = keys(c, h, pid)
    kid = ks["notes_count"]["id"]
    r = c.put(
        f"/v1/strings/projects/{pid}/keys/{kid}/translations/ru",
        json={"forms": {"one": "%d заметка", "few": "%d заметки"}},
        headers=h,
    )
    tr = r.json()["translations"]["ru"]
    assert tr["blocked"] is True and any(i["code"] == "plural_forms_missing" for i in tr["qa"])
    r = c.put(
        f"/v1/strings/projects/{pid}/keys/{kid}/translations/ru",
        json={
            "forms": {"one": "%d заметка", "few": "%d заметки", "many": "%d заметок", "other": "%d заметки"}
        },
        headers=h,
    )
    assert r.json()["translations"]["ru"]["blocked"] is False
    kid2 = ks["dont_forget"]["id"]
    c.put(
        f"/v1/strings/projects/{pid}/keys/{kid2}/translations/ru",
        json={"value": 'Не забудьте "сохранить" & синхронизировать'},
        headers=h,
    )
    out = c.get(f"/v1/strings/projects/{pid}/pull", params={"lang": "ru", "format": "android"}, headers=h)
    body = out.content.decode()
    assert '<item quantity="many">%d заметок</item>' in body
    assert 'Не забудьте \\"сохранить\\" &amp; синхронизировать' in body


def test_translate_missing_batch_with_mock_engine(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "strings.xml", (FIX / "strings.xml").read_bytes())
    r = c.post(f"/v1/strings/projects/{pid}/translate", json={"langs": ["de", "ru"]}, headers=h)
    assert r.status_code == 202, r.text
    batch = r.json()
    # 9 translatable keys x 2 languages (app_name is translatable="false")
    assert batch["total"] == 18 and batch["status"] == "queued"
    again = c.post(f"/v1/strings/projects/{pid}/translate", json={}, headers=h)
    assert again.status_code == 409
    run_worker()
    b = c.get(f"/v1/strings/projects/{pid}/batches/{batch['id']}", headers=h).json()
    assert b["status"] == "done" and b["done"] == 18 and b["progress"] == 100
    assert sum(b["counts"][k] for k in ("machine", "reviewed", "blocked", "tm")) == 18
    ks = keys(c, h, pid)
    welcome = ks["welcome_title"]["translations"]["de"]
    assert "%1$s" in welcome["value"] and welcome["value"] != "Welcome, %1$s!"
    assert welcome["origin"] == "mt" and welcome["engine"] == "mock-mt"
    assert welcome["state"] in ("machine", "reviewed") and welcome["qe_score"] is not None
    tap = ks["tap_save"]["translations"]["de"]["value"]
    assert '<xliff:g id="count" example="3">%d</xliff:g>' in tap and "<b>" in tap
    ru_forms = ks["notes_count"]["translations"]["ru"]["forms"]
    assert set(ru_forms) == {"one", "few", "many", "other"} and all("%d" in v for v in ru_forms.values())
    assert set(ks["sort_options"]["translations"]["de"]["forms"]) == {"0", "1", "2"}
    assert "app_name" not in [n for n, k in ks.items() if k["translations"]["de"]]
    # every machine write left a history row
    n = db.execute(select(StringHistory).where(StringHistory.event == "machine")).scalars().all()
    assert len(n) == 18


def test_tm_reuse_and_pretranslate_tm_only(db):
    c = client()
    h = register(c)
    p1 = project(c, h, name="App one")["id"]
    push(c, h, p1, "en.json", json.dumps({"save": "Save changes", "hello": "Hello {name}"}).encode())
    ks = keys(c, h, p1)
    c.put(
        f"/v1/strings/projects/{p1}/keys/{ks['hello']['id']}/translations/de",
        json={"value": "Hallo {name}", "state": "approved"},
        headers=h,
    )
    assert db.execute(select(TmEntry)).scalars().first() is not None  # approved -> TM (R-TM-01)
    p2 = project(c, h, name="App two")["id"]
    push(c, h, p2, "en.json", json.dumps({"greeting": "Hello {name}", "other": "Unrelated"}).encode())
    r = c.post(
        f"/v1/strings/projects/{p2}/bulk", json={"action": "pretranslate_tm", "langs": ["de"]}, headers=h
    )
    assert r.json()["batch"]["total"] == 2
    run_worker()
    ks2 = keys(c, h, p2)
    g = ks2["greeting"]["translations"]["de"]
    assert g["value"] == "Hallo {name}" and g["origin"] == "tm"
    assert ks2["other"]["translations"]["de"] is None  # tm_only: no engine


def test_bulk_approve_clear_archive(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "en.json", (FIX / "en.json").read_bytes())
    push(
        c,
        h,
        pid,
        "de.json",
        json.dumps({"app.title": "Acme Notizen", "home.greeting": "Hallo {name}!"}).encode(),
        lang="de",
        state="machine",
    )
    r = c.post(f"/v1/strings/projects/{pid}/bulk", json={"action": "approve", "langs": ["de"]}, headers=h)
    assert r.json()["changed"] == 2
    assert keys(c, h, pid)["app.title"]["translations"]["de"]["state"] == "approved"
    kid = keys(c, h, pid)["app.title"]["id"]
    r = c.post(
        f"/v1/strings/projects/{pid}/bulk",
        json={"action": "clear", "langs": ["de"], "key_ids": [kid]},
        headers=h,
    )
    assert r.json()["changed"] == 1
    assert keys(c, h, pid)["app.title"]["translations"]["de"]["state"] == "untranslated"
    c.post(f"/v1/strings/projects/{pid}/bulk", json={"action": "archive", "key_ids": [kid]}, headers=h)
    assert "app.title" not in keys(c, h, pid)
    assert keys(c, h, pid, include_archived=True)["app.title"]["archived"] is True
    c.post(f"/v1/strings/projects/{pid}/bulk", json={"action": "tag", "tag": "v2"}, headers=h)
    assert len(keys(c, h, pid, tag="v2")) == 5


def test_source_change_drops_reviewed_back_to_machine(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "en.json", json.dumps({"save": "Save"}).encode())
    push(c, h, pid, "de.json", json.dumps({"save": "Speichern"}).encode(), lang="de")
    assert keys(c, h, pid)["save"]["translations"]["de"]["state"] == "reviewed"
    push(c, h, pid, "en.json", json.dumps({"save": "Save all"}).encode())
    tr = keys(c, h, pid)["save"]["translations"]["de"]
    assert tr["state"] == "machine" and tr["needs_review"] is True  # R-STR-03
    kid = keys(c, h, pid)["save"]["id"]
    events = [
        e["event"] for e in c.get(f"/v1/strings/projects/{pid}/keys/{kid}/history", headers=h).json()["items"]
    ]
    assert "source_changed" in events and "imported" in events


def test_push_archive_missing_and_search_filters(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "en.json", json.dumps({"a": "Apple", "b": "Banana", "c": "Cherry"}).encode())
    res = push(c, h, pid, "en.json", json.dumps({"a": "Apple", "b": "Banana"}).encode(), archive_missing=True)
    assert res["archived"] == 1
    assert set(keys(c, h, pid)) == {"a", "b"}
    assert set(keys(c, h, pid, q="banan")) == {"b"}
    push(c, h, pid, "de.json", json.dumps({"a": "Apfel"}).encode(), lang="de")
    assert set(keys(c, h, pid, lang="de", state="untranslated")) == {"b"}
    assert set(keys(c, h, pid, lang="de", state="reviewed")) == {"a"}


def test_key_crud_and_kind_change_guard(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    r = c.post(
        f"/v1/strings/projects/{pid}/keys",
        json={
            "name": "cart.count",
            "kind": "plural",
            "forms": {"one": "# item", "other": "# items"},
            "description": "Cart badge",
            "max_length": 20,
            "tags": ["cart"],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    k = r.json()
    assert k["translations"]["en"]["forms"] == {"one": "# item", "other": "# items"}
    dup = c.post(f"/v1/strings/projects/{pid}/keys", json={"name": "cart.count"}, headers=h)
    assert dup.status_code == 409
    r = c.patch(f"/v1/strings/projects/{pid}/keys/{k['id']}", json={"kind": "string"}, headers=h)
    assert r.status_code == 409
    r = c.patch(
        f"/v1/strings/projects/{pid}/keys/{k['id']}",
        json={"description": "Badge on the cart icon", "screenshot_url": "https://example.com/cart.png"},
        headers=h,
    )
    assert r.json()["screenshot_url"] == "https://example.com/cart.png"
    long = c.put(
        f"/v1/strings/projects/{pid}/keys/{k['id']}/translations/de",
        json={"forms": {"one": "# Artikel im Warenkorb gesamt", "other": "# Artikel"}},
        headers=h,
    )
    assert any(i["code"] == "length_exceeded" for i in long.json()["translations"]["de"]["qa"])


def test_history_is_append_only(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "en.json", json.dumps({"a": "Apple"}).encode())
    assert db.execute(select(StringHistory)).scalars().first() is not None
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE string_history SET value = 'x'"))
        db.flush()
    db.rollback()


def test_suggest_one(db):
    c = client()
    h = register(c)
    pid = project(c, h)["id"]
    push(c, h, pid, "en.json", json.dumps({"hello": "Hello {name}"}).encode())
    kid = keys(c, h, pid)["hello"]["id"]
    r = c.post(f"/v1/strings/projects/{pid}/keys/{kid}/translations/de/suggest", headers=h)
    assert r.status_code == 200, r.text
    tr = r.json()["key"]["translations"]["de"]
    assert "{name}" in tr["value"] and tr["engine"] == "mock-mt"
    v = db.execute(select(StringTranslation).where(StringTranslation.lang == "de")).scalar_one()
    assert v.version == 1


def test_formats_listing(db):
    c = client()
    h = register(c)
    names = [f["name"] for f in c.get("/v1/strings/formats", headers=h).json()["items"]]
    for n in (
        "json",
        "json_nested",
        "i18next",
        "formatjs",
        "arb",
        "android",
        "ios_strings",
        "stringsdict",
        "xcstrings",
        "yaml",
        "po",
        "pot",
        "xliff12",
        "xliff21",
        "csv",
        "xlsx",
    ):
        assert n in names
