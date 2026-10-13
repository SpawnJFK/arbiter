"""Releases + OTA (R-STR-REL-*), branches + merge (R-STR-04/05) and human review through the
reviewer community (D-061)."""

from __future__ import annotations

import json

from sqlalchemy import select
from str_helpers import FIX, client, keys, project, push, register, run_worker

from arbiter.community import queue as review_queue
from arbiter.community import review as community_review
from arbiter.models import Job, Organization, ReviewTask, TmEntry, Webhook, WebhookDelivery


def _setup(c, h, **over):
    pid = project(c, h, **over)["id"]
    push(c, h, pid, "en.json", (FIX / "en.json").read_bytes())
    push(
        c,
        h,
        pid,
        "de.json",
        json.dumps(
            {
                "app.title": "Acme Notizen",
                "home.greeting": "Hallo {name}!",
                "home.summary": "Kaputt {ordner}",  # blocked: never shipped
            }
        ).encode(),
        lang="de",
    )
    return pid


def test_release_publish_and_ota(db):
    c = client()
    h = register(c)
    pid = _setup(c, h)
    org = db.execute(select(Organization)).scalars().first()
    db.add(
        Webhook(
            org_id=org.id, url="https://hooks.example.com/x", secret="s", events=["strings.release.published"]
        )
    )
    db.commit()

    r = c.post(f"/v1/strings/projects/{pid}/releases", json={"formats": ["android", "xcstrings"]}, headers=h)
    assert r.status_code == 201, r.text
    rel = r.json()
    assert rel["version_label"] == "v1" and rel["status"] == "published" and rel["content_hash"]
    assert set(rel["files"]["de"]) == {"json", "android"} and "xcstrings" in rel["files"]["_all"]
    ota = rel["ota"]["langs"]["de"]["versioned"]
    assert "/ota/" in ota and pid not in ota  # public id, never the internal id
    assert db.execute(
        select(WebhookDelivery).where(WebhookDelivery.event == "strings.release.published")
    ).first()

    path = ota.split("://", 1)[1].split("/", 1)[1]
    res = c.get("/" + path)
    assert res.status_code == 200
    assert "immutable" in res.headers["cache-control"] and res.headers["etag"]
    assert res.headers["access-control-allow-origin"] == "*"
    bundle = res.json()
    assert bundle["app.title"] == "Acme Notizen"
    assert bundle["home.summary"].startswith("You have")  # blocked -> base fallback (R-STR-08)
    assert bundle["home.files"] == {"=0": "No files yet", "one": "# file", "other": "# files"}
    assert bundle["weekdays"] == ["Mon", "Tue", "Wed"]
    etag = res.headers["etag"]
    assert c.get("/" + path, headers={"If-None-Match": etag}).status_code == 304

    latest = c.get("/" + path.replace("/v1/", "/latest/"))
    assert latest.status_code == 200 and "max-age=60" in latest.headers["cache-control"]
    manifest = c.get("/" + path.replace("/de.json", "/manifest.json")).json()
    assert manifest["version_label"] == "v1" and set(manifest["langs"]) == {"en", "de", "ru"}

    # a draft release is not served, and `latest` keeps pointing at the published one
    d = c.post(
        f"/v1/strings/projects/{pid}/releases",
        json={"version_label": "2.0.0-rc1", "publish": False},
        headers=h,
    ).json()
    assert d["status"] == "draft" and d["ota"] is None
    assert c.get("/" + path.replace("/v1/", "/2.0.0-rc1/")).status_code == 404
    assert c.get("/" + path.replace("/v1/", "/latest/")).json() == bundle
    pub = c.post(f"/v1/strings/projects/{pid}/releases/{d['id']}/publish", headers=h)
    assert pub.json()["status"] == "published"
    assert c.get("/" + path.replace("/v1/", "/2.0.0-rc1/")).status_code == 200
    dup = c.post(f"/v1/strings/projects/{pid}/releases", json={"version_label": "v1"}, headers=h)
    assert dup.status_code == 409

    f = c.get(f"/v1/strings/projects/{pid}/releases/v1/files/de/android", headers=h)
    assert f.status_code == 200 and b"Acme Notizen" in f.content


def test_private_project_needs_distribution_token(db):
    c = client()
    h = register(c)
    pid = _setup(c, h)
    token = c.post(f"/v1/strings/projects/{pid}/distribution-token", headers=h).json()["token"]
    assert token.startswith("sdt_")
    rel = c.post(f"/v1/strings/projects/{pid}/releases", json={}, headers=h).json()
    path = "/" + rel["ota"]["langs"]["de"]["versioned"].split("://", 1)[1].split("/", 1)[1]
    assert c.get(path).status_code == 404
    assert c.get(path, params={"token": "sdt_wrong"}).status_code == 404
    ok = c.get(path, headers={"X-Distribution-Token": token})
    assert ok.status_code == 200 and ok.headers["cache-control"].startswith("private")
    assert c.get(f"/v1/strings/projects/{pid}", headers=h).json()["has_distribution_token"] is True


def test_client_role_cannot_publish(db):
    from arbiter.platform.permissions import has_permission

    class P:
        role = "client"

    assert has_permission(P(), "strings.read") and not has_permission(P(), "strings.publish")

    class Pm:
        role = "pm"

    assert has_permission(Pm(), "strings.publish") and has_permission(Pm(), "strings.write")


def test_branch_copy_on_write_merge_and_conflict(db):
    c = client()
    h = register(c)
    pid = _setup(c, h)
    br = c.post(f"/v1/strings/projects/{pid}/branches", json={"name": "feature/onboarding"}, headers=h).json()
    bid = br["id"]
    k = keys(c, h, pid)
    title, greet = k["app.title"]["id"], k["home.greeting"]["id"]

    c.put(
        f"/v1/strings/projects/{pid}/keys/{title}/translations/de",
        params={"branch": bid},
        json={"value": "Acme Notizbuch"},
        headers=h,
    )
    new = c.post(
        f"/v1/strings/projects/{pid}/keys",
        params={"branch": bid},
        json={"name": "onboarding.step1", "value": "Create your first note"},
        headers=h,
    )
    assert new.status_code == 201
    # main does not see branch changes; the branch sees main's untouched rows
    assert keys(c, h, pid)["app.title"]["translations"]["de"]["value"] == "Acme Notizen"
    assert "onboarding.step1" not in keys(c, h, pid)
    kb = keys(c, h, pid, branch=bid)
    assert kb["app.title"]["translations"]["de"]["value"] == "Acme Notizbuch"
    assert kb["app.title"]["translations"]["de"]["branch_local"] is True
    assert kb["home.greeting"]["translations"]["de"]["value"] == "Hallo {name}!"

    # conflict: main changes the same translation after the branch copied it
    c.put(
        f"/v1/strings/projects/{pid}/keys/{greet}/translations/de",
        params={"branch": bid},
        json={"value": "Servus {name}!"},
        headers=h,
    )
    c.put(f"/v1/strings/projects/{pid}/keys/{greet}/translations/de", json={"value": "Hi {name}!"}, headers=h)
    prev = c.get(f"/v1/strings/projects/{pid}/branches/{bid}/merge-preview", headers=h).json()
    assert [(x["key"], x["lang"]) for x in prev["conflicts"]] == [("home.greeting", "de")]
    r = c.post(f"/v1/strings/projects/{pid}/branches/{bid}/merge", json={}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["details"]["conflicts"]
    r = c.post(
        f"/v1/strings/projects/{pid}/branches/{bid}/merge",
        json={"resolutions": {f"{greet}:de": "main"}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["keys_moved"] == 1 and r.json()["branch"]["merged_at"]
    km = keys(c, h, pid)
    assert km["app.title"]["translations"]["de"]["value"] == "Acme Notizbuch"
    assert km["home.greeting"]["translations"]["de"]["value"] == "Hi {name}!"
    assert km["onboarding.step1"]["translations"]["en"]["value"] == "Create your first note"
    # a merged branch is read-only
    w = c.put(
        f"/v1/strings/projects/{pid}/keys/{title}/translations/de",
        params={"branch": bid},
        json={"value": "x"},
        headers=h,
    )
    assert w.status_code == 409


def test_human_review_through_community_queue(db):
    from community.comm_helpers import make_reviewer

    c = client()
    h = register(c)
    pid = project(c, h, target_langs=["de"], tier="full", settings={"human_review": True})["id"]
    push(
        c,
        h,
        pid,
        "en.json",
        json.dumps({"greet": "Hello {name}", "files": "{n, plural, one {# file} other {# files}}"}).encode(),
    )
    r = c.post(f"/v1/strings/projects/{pid}/translate", json={}, headers=h)
    run_worker()
    b = c.get(f"/v1/strings/projects/{pid}/batches/{r.json()['id']}", headers=h).json()
    assert b["counts"]["review_tasks"] == 3  # 1 string + 2 plural forms (de: one, other)
    assert b["review_job_id"]
    job = db.get(Job, b["review_job_id"])
    assert job.state == "review" and (job.workflow or {}).get("adapter") == "strings"
    assert keys(c, h, pid)["greet"]["translations"]["de"]["needs_review"] is True

    reviewer = make_reviewer(db, pairs=(("en", "de"),))
    db.commit()
    seen = 0
    while True:
        task = review_queue.next_task(db, reviewer)
        if task is None:
            break
        seen += 1
        target = task["target_tagged"]
        if "Hello" in task["source_tagged"]:
            target = "Hallo ⟦1/⟧"
            out = community_review.submit(
                db, reviewer, task["id"], decision="edit", target_tagged=target, time_ms=60000
            )
        else:
            out = community_review.submit(db, reviewer, task["id"], decision="accept", time_ms=60000)
        assert out["ok"]
        db.commit()
    assert seen == 3
    ks = keys(c, h, pid)
    g = ks["greet"]["translations"]["de"]
    assert g["value"] == "Hallo {name}" and g["state"] == "reviewed" and g["needs_review"] is False
    assert ks["files"]["translations"]["de"]["state"] == "reviewed"
    db.expire_all()
    assert db.get(Job, b["review_job_id"]).state == "delivered"
    assert all(t.state == "payable" for t in db.execute(select(ReviewTask)).scalars())
    assert db.execute(select(TmEntry).where(TmEntry.target_plain == "Hallo ")).scalars().first() is not None
