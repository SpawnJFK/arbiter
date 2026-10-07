"""Customer flow over HTTP: upload -> quote -> project -> pipeline -> download/evidence."""

from __future__ import annotations

from datetime import timedelta

import orjson
from api_helpers import client, register
from sqlalchemy import func, select
from test_api_cust_helpers import DOC, drain, order, project, quote, upload

from arbiter.api import security
from arbiter.models import Job, Project, Quote, User, utcnow


def test_auto_tier_end_to_end_download_evidence_segments(db):
    c = client()
    h = register(c)
    f = upload(c, h)
    assert f["format"] == "markdown" or f["format"]
    assert f["segment_count"] >= 4 and f["word_count"] > 10
    q = quote(c, h, f["id"])
    assert q["tiers"]["auto"]["available"] and isinstance(q["tiers"]["auto"]["price"], str)
    assert c.get(f"/v1/quotes/{q['id']}", headers=h).json()["id"] == q["id"]
    prj = project(c, h, q["id"], "auto")
    assert len(prj["jobs"]) == 1 and prj["jobs"][0]["state"] == "running"
    job_id = prj["jobs"][0]["id"]
    # money is a decimal string and the revenue equals the quoted price
    assert prj["jobs"][0]["revenue"] == q["tiers"]["auto"]["price"]
    assert c.get(f"/v1/quotes/{q['id']}", headers=h).json()["status"] == "accepted"

    r = c.get(f"/v1/jobs/{job_id}/download", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_delivered"

    drain()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "delivered", job
    assert job["progress"] == 1.0 and job["filename"] == "notes.md"
    assert job["margin"] is not None and job["cost"] is not None

    r = c.get(f"/v1/jobs/{job_id}/download", headers=h)
    assert r.status_code == 200
    assert r.content and r.content != DOC
    assert "notes.sr.md" in r.headers["content-disposition"]

    ev = c.get(f"/v1/jobs/{job_id}/evidence?format=json", headers=h)
    assert ev.status_code == 200
    pack = orjson.loads(ev.content)
    assert pack
    pdf = c.get(f"/v1/jobs/{job_id}/evidence", params={"format": "pdf"}, headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    x = c.get(f"/v1/jobs/{job_id}/xliff", headers=h)
    assert x.status_code == 200 and b'version="2.1"' in x.content and b"<target" in x.content

    page1 = c.get(f"/v1/jobs/{job_id}/segments?limit=2", headers=h).json()
    assert len(page1["items"]) == 2 and page1["next_offset"] == 2
    assert [s["seq"] for s in page1["items"]] == [0, 1]
    rest = c.get(f"/v1/jobs/{job_id}/segments?offset=2&limit=200", headers=h).json()
    assert rest["next_offset"] is None and rest["items"][0]["seq"] == 2
    assert c.get(f"/v1/jobs/{job_id}/segments?state=delivered", headers=h).json()["items"]

    # a delivered segment can be reported as an escaped error
    seg_id = page1["items"][0]["id"]
    r = c.post(f"/v1/jobs/{job_id}/report-error", headers=h, json={"segment_id": seg_id, "note": "typo"})
    assert r.status_code == 201 and r.json()["id"].startswith("esc_")

    jobs = c.get("/v1/jobs?state=delivered", headers=h).json()
    assert [j["id"] for j in jobs["items"]] == [job_id]
    assert c.get(f"/v1/jobs?project_id={prj['id']}", headers=h).json()["items"]
    lst = c.get("/v1/projects", headers=h).json()
    assert lst["items"][0]["id"] == prj["id"] and "jobs" not in lst["items"][0]
    assert c.get(f"/v1/projects/{prj['id']}", headers=h).json()["jobs"][0]["id"] == job_id

    dash = c.get("/v1/quality/dashboard", headers=h).json()
    assert dash["auto_rate"] == 1.0 and dash["escaped_rate"] is not None
    assert c.get("/v1/quality/thresholds", headers=h).json()["next_offset"] is None
    usage = c.get("/v1/usage", headers=h).json()
    assert usage["words"] > 0 and isinstance(usage["amount"], str)
    assert c.get("/v1/usage?period=2026-13", headers=h).status_code == 422
    assert c.get("/v1/invoices", headers=h).json() == {"items": [], "next_offset": None}


def test_two_target_languages_split_revenue(db):
    c = client()
    h = register(c)
    f = upload(c, h)
    q = quote(c, h, f["id"], ["sr", "de"])
    prj = project(c, h, q["id"], "hybrid")
    from decimal import Decimal

    total = sum(Decimal(j["revenue"]) for j in prj["jobs"])
    assert total == Decimal(q["tiers"]["hybrid"]["price"])
    assert {j["target_lang"] for j in prj["jobs"]} == {"sr", "de"}


def test_r_seg_12_regulated_org_cannot_order_auto(db):
    c = client()
    h = register(c)
    assert c.patch("/v1/org", json={"regulated": True}, headers=h).status_code == 200
    f = upload(c, h)
    q = quote(c, h, f["id"])
    assert q["tiers"]["auto"]["available"] is False
    r = c.post("/v1/projects", headers=h, json={"name": "X", "quote_id": q["id"], "tier": "auto"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "tier_not_allowed"
    r = c.post("/v1/projects", headers=h, json={"name": "X", "quote_id": q["id"], "tier": "ai_review"})
    assert r.json()["error"]["code"] == "tier_not_allowed"
    assert (
        c.post("/v1/projects", headers=h, json={"name": "X", "quote_id": q["id"], "tier": "full"}).status_code
        == 201
    )


def test_expired_or_used_quote_is_409(db):
    c = client()
    h = register(c)
    f = upload(c, h)
    q = quote(c, h, f["id"])
    row = db.get(Quote, q["id"])
    row.valid_until = utcnow() - timedelta(minutes=1)
    db.commit()
    assert c.get(f"/v1/quotes/{q['id']}", headers=h).json()["status"] == "expired"
    r = c.post("/v1/projects", headers=h, json={"name": "X", "quote_id": q["id"], "tier": "auto"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_expired"

    q2 = quote(c, h, f["id"])
    project(c, h, q2["id"])
    r = c.post("/v1/projects", headers=h, json={"name": "X", "quote_id": q2["id"], "tier": "auto"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_not_open"


def test_idempotent_project_creation(db):
    c = client()
    h = register(c)
    f = upload(c, h)
    q = quote(c, h, f["id"])
    body = {"name": "Once", "quote_id": q["id"], "tier": "auto"}
    hk = {**h, "Idempotency-Key": "order-42"}
    r1 = c.post("/v1/projects", headers=hk, json=body)
    r2 = c.post("/v1/projects", headers=hk, json=body)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    db.expire_all()
    assert db.execute(select(func.count()).select_from(Project)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(Job)).scalar_one() == 1
    r3 = c.post("/v1/projects", headers=hk, json={**body, "name": "Other"})
    assert r3.status_code == 409 and r3.json()["error"]["code"] == "idempotency_conflict"


def test_tenancy_second_org_sees_nothing(db):
    c = client()
    h1 = register(c)
    prj = order(c, h1)
    job_id = prj["jobs"][0]["id"]
    file_id = prj["jobs"][0]["file_id"]
    g = c.post("/v1/glossaries", headers=h1, json={"name": "Main"}).json()

    h2 = register(c, email="other@example.com", org="Other Ltd")
    assert c.get(f"/v1/jobs/{job_id}", headers=h2).status_code == 404
    assert c.get(f"/v1/jobs/{job_id}/segments", headers=h2).status_code == 404
    assert c.get(f"/v1/jobs/{job_id}/download", headers=h2).status_code == 404
    assert c.get(f"/v1/projects/{prj['id']}", headers=h2).status_code == 404
    r = c.post("/v1/quotes", headers=h2, json={"file_id": file_id, "target_langs": ["de"]})
    assert r.status_code == 404
    assert c.get(f"/v1/glossaries/{g['id']}/terms", headers=h2).status_code == 404
    assert c.get("/v1/jobs", headers=h2).json()["items"] == []
    assert c.get("/v1/glossaries", headers=h2).json()["items"] == []


def test_client_role_hides_money(db):
    c = client()
    h = register(c)
    prj = order(c, h)
    job_id = prj["jobs"][0]["id"]
    pm = db.execute(select(User)).scalar_one()
    u = User(email="client@example.com", name="Client", password_hash="x", role="client", org_id=pm.org_id)
    db.add(u)
    db.commit()
    ch = {"Authorization": f"Bearer {security.issue_token(u.id, 'client', pm.org_id)}"}
    job = c.get(f"/v1/jobs/{job_id}", headers=ch).json()
    assert job["revenue"] is None and job["cost"] is None and job["margin"] is None
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["margin"] is not None
    # PM-only endpoints
    assert c.get("/v1/exceptions", headers=ch).status_code == 403
    assert c.post(f"/v1/jobs/{job_id}/cancel", headers=ch).status_code == 403


def test_unsupported_pdf_is_422(db):
    c = client()
    h = register(c)
    r = c.post(
        "/v1/files", headers=h, files={"file": ("brochure.pdf", b"%PDF-1.7 ...")}, data={"source_lang": "en"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_file"


def test_full_tier_waits_then_pm_edits_and_approves(db):
    c = client()
    h = register(c)
    prj = order(c, h, tier="full")
    job_id = prj["jobs"][0]["id"]
    drain()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "review"
    segs = c.get(f"/v1/jobs/{job_id}/segments?limit=200", headers=h).json()["items"]
    assert segs and all(s["state"] == "needs_review" for s in segs)

    tagged = next(s for s in segs if "⟦1⟧" in s["source_tagged"])
    broken = tagged["target_tagged"].replace("⟦/1⟧", "")
    r = c.patch(f"/v1/jobs/{job_id}/segments/{tagged['id']}", headers=h, json={"target_tagged": broken})
    assert r.status_code == 422 and r.json()["error"]["code"] == "tag_error"

    fixed = "⟦1⟧Ugovor⟦/1⟧ mora biti potpisan pre ažuriranja. Otvorite Podešavanja i kliknite Sačuvaj."
    r = c.patch(f"/v1/jobs/{job_id}/segments/{tagged['id']}", headers=h, json={"target_tagged": fixed})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "reviewed" and r.json()["origin"] == "human"

    for s in segs:
        if s["id"] == tagged["id"]:
            continue
        r = c.post(f"/v1/jobs/{job_id}/segments/{s['id']}/approve", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "reviewed"
    # approving twice is harmless
    assert c.post(f"/v1/jobs/{job_id}/segments/{segs[0]['id']}/approve", headers=h).status_code == 200
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["state"] == "ready"
    drain()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "delivered"
    out = c.get(f"/v1/jobs/{job_id}/download", headers=h).content.decode()
    assert "**Ugovor**" in out

    from arbiter.models import ProvenanceEvent

    db.expire_all()
    human = (
        db.execute(
            select(ProvenanceEvent).where(
                ProvenanceEvent.job_id == job_id, ProvenanceEvent.actor_type == "human"
            )
        )
        .scalars()
        .all()
    )
    assert {e.event for e in human} >= {"target_set", "reviewed", "approved"}


def test_cancel_and_exceptions(db):
    c = client()
    h = register(c)
    prj = order(c, h, tier="full")
    job_id = prj["jobs"][0]["id"]
    drain()
    job = db.get(Job, job_id)
    job.due_at = utcnow() - timedelta(hours=1)
    db.commit()
    ex = c.get("/v1/exceptions", headers=h).json()["items"]
    assert any(e["kind"] == "overdue" and e["job_id"] == job_id for e in ex)
    r = c.post(f"/v1/jobs/{job_id}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert c.post(f"/v1/jobs/{job_id}/cancel", headers=h).json()["state"] == "cancelled"
    done = order(c, h)["jobs"][0]["id"]
    drain()
    r = c.post(f"/v1/jobs/{done}/cancel", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "illegal_state"
