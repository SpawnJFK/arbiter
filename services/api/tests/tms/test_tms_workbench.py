"""Workbench API: editor list and filters, live QA, assistance, MT, locks, find/replace,
split/merge (and delivery afterwards), preview, comments and client queries, concordance."""

from __future__ import annotations

from sqlalchemy import select
from tms_helpers import client, client_user, drain, order, register, segments

from arbiter.linguistic import tm
from arbiter.models import Job, Organization, ProvenanceEvent, Segment, User, WebhookDelivery


def _seg(items: list[dict], startswith: str) -> dict:
    return next(s for s in items if s["source_tagged"].startswith(startswith))


def test_editor_list_filters_and_live_check(db):
    c = client()
    h = register(c)
    job = order(c, h)
    items = segments(c, h, job["id"])
    assert len(items) == job["segment_count"] >= 6
    first = items[0]
    assert {"unit_id", "seg_index", "locked", "qa_count", "comment_threads", "slots"} <= set(first)
    assert all(s["state"] == "needs_review" for s in items)  # full tier: every segment to a human
    page = c.get(f"/v1/jobs/{job['id']}/editor/segments", headers=h, params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_offset"] == 2 and page["total"] == len(items)
    assert segments(c, h, job["id"], state="reviewed") == []
    assert len(segments(c, h, job["id"], q="contract")) == 1
    assert segments(c, h, job["id"], tm_band="none")
    assert c.get(f"/v1/jobs/{job['id']}/editor/segments?tm_band=bad", headers=h).status_code == 422

    bold = _seg(items, "The ")
    assert "⟦1⟧" in bold["source_tagged"]
    # dropping the standalone-free pair is a warning; dropping one half is blocking
    r = c.post(
        f"/v1/jobs/{job['id']}/segments/{bold['id']}/check",
        headers=h,
        json={"target_tagged": "Ugovor ⟦1⟧mora biti potpisan."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["blocking"] and any(i["code"] == "tag_unbalanced" for i in body["issues"])
    num = _seg(items, "Arbiter supports")
    r = c.post(
        f"/v1/jobs/{job['id']}/segments/{num['id']}/check",
        headers=h,
        json={"target_tagged": "Arbiter podrzava 13 formata."},
    ).json()
    assert any(i["code"] == "number_mismatch" for i in r["issues"])
    # nothing was saved
    again = segments(c, h, job["id"], q="Arbiter supports")[0]
    assert again["target_tagged"] == num["target_tagged"]


def test_assist_tm_diff_glossary_and_mt(db):
    c = client()
    h = register(c)
    job = order(c, h)
    j = db.get(Job, job["id"])
    tm.store(db, j.org_id, "en", "sr", "Arbiter supports 10 file formats.", "Arbiter podrzava 10 formata.")
    g = c.post("/v1/glossaries", headers=h, json={"name": "Main"}).json()
    c.post(
        f"/v1/glossaries/{g['id']}/terms",
        headers=h,
        json={
            "source_lang": "en",
            "target_lang": "sr",
            "source_term": "file formats",
            "target_term": "formati",
        },
    )
    db.commit()
    seg = _seg(segments(c, h, job["id"]), "Arbiter supports")
    a = c.get(f"/v1/jobs/{job['id']}/segments/{seg['id']}/assist", headers=h).json()
    assert a["tm_matches"] and a["tm_matches"][0]["kind"] == "fuzzy"
    ops = a["tm_matches"][0]["diff"]
    assert {"op": "delete", "text": "10"} in ops and {"op": "insert", "text": "12"} in ops
    # the job started without a glossary (version 0 = current terms), so the new term is a hit
    assert [t["target_term"] for t in a["terms"]] == ["formati"]

    r = c.post(f"/v1/jobs/{job['id']}/segments/{seg['id']}/mt", headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["engine"] == "mock-mt" and r.json()["target_tagged"]
    assert (
        c.post(
            f"/v1/jobs/{job['id']}/segments/{seg['id']}/mt", headers=h, json={"engine": "deepl"}
        ).status_code
        == 422
    )
    unchanged = _seg(segments(c, h, job["id"]), "Arbiter supports")
    assert unchanged["target_tagged"] == seg["target_tagged"]


def test_locks_block_clients_and_bulk_replace(db):
    c = client()
    h = register(c)
    ch = client_user(db, c, h)
    job = order(c, h)
    items = segments(c, h, job["id"])
    seg = items[1]
    r = c.post(f"/v1/jobs/{job['id']}/segments/lock", headers=h, json={"segment_ids": [seg["id"]]})
    assert r.status_code == 200 and r.json()["changed"] == 1
    assert (
        c.post(
            f"/v1/jobs/{job['id']}/segments/lock", headers=ch, json={"segment_ids": [seg["id"]]}
        ).status_code
        == 403
    )
    assert segments(c, h, job["id"], locked="true")[0]["id"] == seg["id"]
    r = c.patch(f"/v1/jobs/{job['id']}/segments/{seg['id']}", headers=ch, json={"target_tagged": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "segment_locked"
    r = c.post(f"/v1/jobs/{job['id']}/segments/{seg['id']}/approve", headers=ch)
    assert r.status_code == 409
    # the PM may still edit a locked segment
    r = c.patch(
        f"/v1/jobs/{job['id']}/segments/{seg['id']}", headers=h, json={"target_tagged": seg["target_tagged"]}
    )
    assert r.status_code == 200, r.text
    events = (
        db.execute(select(ProvenanceEvent.event).where(ProvenanceEvent.segment_id == seg["id"]))
        .scalars()
        .all()
    )
    assert "locked" in events
    r = c.post(
        f"/v1/jobs/{job['id']}/segments/lock", headers=h, json={"segment_ids": [seg["id"]], "locked": False}
    )
    assert r.json()["changed"] == 1


def test_find_replace_preview_apply_skips_and_force(db):
    c = client()
    h = register(c)
    ch = client_user(db, c, h)
    job = order(c, h)
    items = segments(c, h, job["id"])
    # mock MT keeps numbers and e-mails: "12" is in one target, "support@example.com" in another
    body = {"find": r"\d+", "replace": "<N>", "regex": True}
    prev = c.post(f"/v1/jobs/{job['id']}/find-replace", headers=h, json=body).json()
    assert prev["applied"] is False and prev["changed"] == 0 and prev["total_matches"] >= 2
    hit = next(i for i in prev["items"] if "12" in (i["before"] or ""))
    assert "<N>" in hit["after"] and hit["skip_reason"] is None
    # lock one matching segment and approve another: both are skipped without force
    locked_id = hit["segment_id"]
    c.post(f"/v1/jobs/{job['id']}/segments/lock", headers=h, json={"segment_ids": [locked_id]})
    other = next(i for i in prev["items"] if i["segment_id"] != locked_id and i["target_matches"])
    assert (
        c.post(f"/v1/jobs/{job['id']}/segments/{other['segment_id']}/approve", headers=h).status_code == 200
    )
    res = c.post(f"/v1/jobs/{job['id']}/find-replace", headers=h, json={**body, "apply": True}).json()
    reasons = {i["segment_id"]: i["skip_reason"] for i in res["items"]}
    assert reasons[locked_id] == "locked" and reasons[other["segment_id"]] == "approved"
    # a client cannot force
    r = c.post(f"/v1/jobs/{job['id']}/find-replace", headers=ch, json={**body, "apply": True, "force": True})
    assert r.status_code == 409
    forced = c.post(
        f"/v1/jobs/{job['id']}/find-replace", headers=h, json={**body, "apply": True, "force": True}
    ).json()
    assert forced["changed"] >= 2
    seg = db.get(Segment, locked_id)
    db.refresh(seg)
    assert "<N>" in seg.target_tagged
    ev = (
        db.execute(
            select(ProvenanceEvent).where(
                ProvenanceEvent.segment_id == locked_id, ProvenanceEvent.event == "target_set"
            )
        )
        .scalars()
        .all()
    )
    assert any(e.data.get("by") == "find_replace" for e in ev)
    # codes are never touched: replacing the bold word keeps ⟦1⟧ ⟦/1⟧
    bold = _seg(items, "The ")
    r = c.post(
        f"/v1/jobs/{job['id']}/find-replace",
        headers=h,
        json={"find": "1", "replace": "X", "segment_ids": [bold["id"]], "apply": True},
    ).json()
    assert r["changed"] == 0
    # invalid regex is a 422; replacing the source is refused
    assert (
        c.post(f"/v1/jobs/{job['id']}/find-replace", headers=h, json={"find": "(", "regex": True}).status_code
        == 422
    )
    r = c.post(
        f"/v1/jobs/{job['id']}/find-replace",
        headers=h,
        json={"find": "a", "replace": "b", "scope": "source", "apply": True},
    )
    assert r.status_code == 422


def test_split_merge_renumber_and_delivery(db):
    c = client()
    h = register(c)
    job = order(c, h)
    items = segments(c, h, job["id"])
    n = len(items)
    seg = _seg(items, "Arbiter supports")
    src, tgt = seg["source_tagged"], seg["target_tagged"]
    cut = len("Arbiter supports ")
    tcut = tgt.index(" ", tgt.index(" ") + 1) + 1
    # inside a code is refused, a missing target offset too
    bold = _seg(items, "The ")
    r = c.post(f"/v1/jobs/{job['id']}/segments/{bold['id']}/split", headers=h, json={"source_offset": 5})
    assert r.status_code == 422
    r = c.post(f"/v1/jobs/{job['id']}/segments/{seg['id']}/split", headers=h, json={"source_offset": cut})
    assert r.status_code == 422

    r = c.post(
        f"/v1/jobs/{job['id']}/segments/{seg['id']}/split",
        headers=h,
        json={"source_offset": cut, "target_offset": tcut},
    )
    assert r.status_code == 200, r.text
    a, b = r.json()["segments"]
    assert a["source_tagged"] + b["source_tagged"] == src
    assert a["target_tagged"] + b["target_tagged"] == tgt
    assert b["seq"] == a["seq"] + 1 and b["seg_index"] == a["seg_index"] + 1 and b["slots"] == 0
    after = segments(c, h, job["id"])
    assert len(after) == n + 1 and [s["seq"] for s in after] == list(range(n + 1))
    by_unit: dict[str, list[int]] = {}
    for s in after:
        by_unit.setdefault(s["unit_id"], []).append(s["seg_index"])
    assert all(v == list(range(len(v))) for v in by_unit.values())
    assert db.get(Job, job["id"]).segment_count == n + 1
    # clients cannot change structure
    ch = client_user(db, c, h)
    assert c.post(f"/v1/jobs/{job['id']}/segments/{a['id']}/merge-next", headers=ch).status_code == 403

    # merge back: exact source, slots restored
    r = c.post(f"/v1/jobs/{job['id']}/segments/{a['id']}/merge-next", headers=h)
    assert r.status_code == 200, r.text
    merged = r.json()["segment"]
    assert merged["source_tagged"] == src and merged["target_tagged"] == tgt and merged["slots"] == 1
    assert len(segments(c, h, job["id"])) == n
    events = (
        db.execute(select(ProvenanceEvent.event).where(ProvenanceEvent.job_id == job["id"])).scalars().all()
    )
    assert {"split", "split_created", "merged", "merged_away"} <= set(events)

    # merge two sentences of one paragraph, then deliver: the file is still written correctly
    items = segments(c, h, job["id"])
    first = _seg(items, "The ")
    second = next(
        s for s in items if s["unit_id"] == first["unit_id"] and s["seg_index"] == first["seg_index"] + 1
    )
    r = c.post(f"/v1/jobs/{job['id']}/segments/{first['id']}/merge-next", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["segment"]["slots"] == 2
    last = items[-1]
    assert c.post(f"/v1/jobs/{job['id']}/segments/{last['id']}/merge-next", headers=h).status_code == 409
    for s in segments(c, h, job["id"]):
        assert c.post(f"/v1/jobs/{job['id']}/segments/{s['id']}/approve", headers=h).status_code == 200
    drain()
    done = c.get(f"/v1/jobs/{job['id']}", headers=h).json()
    assert done["state"] == "delivered", done
    out = c.get(f"/v1/jobs/{job['id']}/download", headers=h)
    assert out.status_code == 200
    text = out.content.decode()
    assert second["target_tagged"].split()[0] in text and "12" in text
    # a delivered job cannot be restructured
    any_seg = segments(c, h, job["id"])[0]
    r = c.post(f"/v1/jobs/{job['id']}/segments/{any_seg['id']}/merge-next", headers=h)
    assert r.status_code == 409


def test_preview_markdown_and_side_by_side(db):
    c = client()
    h = register(c)
    job = order(c, h)
    r = c.get(f"/v1/jobs/{job['id']}/preview", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "sandbox" in r.headers["content-security-policy"] and r.headers["x-preview-mode"] == "rich"
    assert "<h1>" in r.text and "<strong>" in r.text
    j2 = order(c, h, data=b'{"title": "Hello world", "body": "Save the file."}', name="app.json")
    r = c.get(f"/v1/jobs/{j2['id']}/preview", headers=h)
    assert r.headers["x-preview-mode"] == "side_by_side" and "<table>" in r.text and "Hello world" in r.text


def test_comments_queries_client_portal_and_webhook(db):
    c = client()
    h = register(c)
    ch = client_user(db, c, h)
    c.post(
        "/v1/webhooks", headers=h, json={"url": "https://hooks.example.com/x", "events": ["job.query.opened"]}
    )
    job = order(c, h)
    seg = segments(c, h, job["id"])[1]
    r = c.post(
        f"/v1/jobs/{job['id']}/comments",
        headers=h,
        json={"segment_id": seg["id"], "body": "Internal: check with @ana.k please", "kind": "comment"},
    )
    assert r.status_code == 201 and r.json()["mentions"] == ["ana.k"]
    q = c.post(
        f"/v1/jobs/{job['id']}/comments",
        headers=h,
        json={"segment_id": seg["id"], "body": "Is 'Settings' a menu name?", "kind": "query"},
    ).json()
    assert q["thread_id"] == q["id"] and q["parent_id"] is None
    deliveries = db.execute(select(WebhookDelivery)).scalars().all()
    assert [d.event for d in deliveries] == ["job.query.opened"]
    assert deliveries[0].payload["data"]["comment_id"] == q["id"]

    # the client sees only the query, answers it, cannot open threads or see comments
    lst = c.get(f"/v1/jobs/{job['id']}/comments", headers=ch).json()["items"]
    assert [x["kind"] for x in lst] == ["query"]
    assert (
        c.post(f"/v1/jobs/{job['id']}/comments", headers=ch, json={"body": "hi", "kind": "query"}).status_code
        == 403
    )
    internal = c.get(f"/v1/jobs/{job['id']}/comments?kind=comment", headers=h).json()["items"][0]
    assert (
        c.post(
            f"/v1/jobs/{job['id']}/comments", headers=ch, json={"body": "x", "parent_id": internal["id"]}
        ).status_code
        == 404
    )
    ans = c.post(
        f"/v1/jobs/{job['id']}/comments",
        headers=ch,
        json={"body": "Yes, keep it in English.", "parent_id": q["id"]},
    )
    assert ans.status_code == 201 and ans.json()["thread_id"] == q["id"] and ans.json()["kind"] == "query"
    inbox = c.get("/v1/queries", headers=ch).json()["items"]
    assert len(inbox) == 1 and inbox[0]["filename"] == "notes.md" and len(inbox[0]["replies"]) == 1
    assert inbox[0]["source_tagged"] == seg["source_tagged"]
    row = segments(c, h, job["id"], open_query="true")
    assert (
        [s["id"] for s in row] == [seg["id"]]
        and row[0]["comment_threads"] == 2
        and row[0]["open_queries"] == 1
    )
    assert len(segments(c, h, job["id"], has_comment="false")) == len(segments(c, h, job["id"])) - 1
    # resolve on a reply resolves the thread
    r = c.patch(f"/v1/comments/{ans.json()['id']}", headers=h, json={"resolved": True})
    assert r.status_code == 200 and r.json()["id"] == q["id"] and r.json()["resolved"]
    assert c.get("/v1/queries", headers=ch).json()["items"] == []
    assert c.get(f"/v1/jobs/{job['id']}/comments?resolved=true", headers=h).json()["items"]
    # another org cannot see or touch it
    h2 = register(c, "other@example.com", "Other")
    assert c.get(f"/v1/jobs/{job['id']}/comments", headers=h2).status_code == 404
    assert c.patch(f"/v1/comments/{q['id']}", headers=h2, json={"resolved": False}).status_code == 404


def test_concordance_source_and_target(db):
    c = client()
    h = register(c)
    org_id = db.execute(select(User.org_id)).scalar_one()
    tm.store(db, org_id, "en", "de", "Sign the contract today.", "Unterschreiben Sie den Vertrag heute.")
    tm.store(db, org_id, "en", "de", "The contract term ends in May.", "Die Vertragslaufzeit endet im Mai.")
    tm.store(db, org_id, "en", "de", "Open the settings.", "Offnen Sie die Einstellungen.")
    tm.store(db, org_id, "en", "fr", "The contract.", "Le contrat.")
    db.commit()
    r = c.get(
        "/v1/tm/concordance", headers=h, params={"q": "contract", "source_lang": "en", "target_lang": "de"}
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2
    r = c.get(
        "/v1/tm/concordance",
        headers=h,
        params={"q": "Vertrag", "source_lang": "en", "target_lang": "de", "side": "target"},
    ).json()["items"]
    assert len(r) == 2 and all("Vertrag" in x["target_tagged"] for x in r)
    r = c.get(
        "/v1/tm/concordance",
        headers=h,
        params={"q": "Vertrag", "source_lang": "en", "target_lang": "de", "side": "source"},
    ).json()["items"]
    assert r == []


def test_tms_module_disabled_is_404(db):
    c = client()
    h = register(c)
    job = order(c, h)
    org = db.execute(select(Organization)).scalar_one()
    org.settings = {**(org.settings or {}), "modules": ["engine", "ai"]}
    db.commit()
    r = c.get(f"/v1/jobs/{job['id']}/editor/segments", headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled"
