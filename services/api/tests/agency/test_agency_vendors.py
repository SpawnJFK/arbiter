"""Module pm: own vendors, assignment routing, offers, vendor workbench, POs, vendor invoices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from agency_helpers import active_reviewer, client, drain, order, org_of, register, review_all, workflow
from sqlalchemy import select, update
from vendor_helpers import assign, due_in, token_of, vendor, work_all

from arbiter.api import security
from arbiter.models import (
    Job,
    PurchaseOrder,
    ReviewTask,
    Segment,
    User,
    VendorAssignment,
    WebhookDelivery,
    WorkItem,
)

FULL = ["tm", "mt", "qe", "human_review", "delivery"]
FULL_TWO = ["tm", "mt", "qe", "human_review", "second_review", "delivery"]


def _segs(db, job_id):
    return db.execute(select(Segment).where(Segment.job_id == job_id).order_by(Segment.seq)).scalars().all()


def _tasks(db, job_id, states=("queued", "offered", "held")):
    return (
        db.execute(select(ReviewTask).where(ReviewTask.job_id == job_id, ReviewTask.state.in_(states)))
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------- vendors


def test_vendor_crud_filters_absences_documents_and_tenancy(db):
    c = client()
    h = register(c)
    v = vendor(c, h, "Ana Lekic", rate="0.04", kind="person", tax_id="RS123", iban="RS35000")
    assert v["pairs"] == [{"source_lang": "en", "target_lang": "sr", "services": ["translation", "review"]}]
    assert {r["service"] for r in v["rates"]} == {"translation", "review"}
    assert v["status"] == "active" and v["currency"] == "EUR"
    vendor(c, h, "Bruno GmbH", pair=("en", "de"), kind="company")

    lst = c.get("/v1/vendors", headers=h, params={"source_lang": "en", "target_lang": "sr"}).json()["items"]
    assert [x["name"] for x in lst] == ["Ana Lekic"]
    assert len(c.get("/v1/vendors", headers=h).json()["items"]) == 2

    r = c.patch(f"/v1/vendors/{v['id']}", headers=h, json={"capacity_words_per_day": 4000, "rating": "4.5"})
    assert (
        r.status_code == 200 and r.json()["capacity_words_per_day"] == 4000 and r.json()["rating"] == "4.50"
    )
    # duplicate rate for the same languages, service and unit is refused
    dup = [
        {"service": "review", "unit": "word", "rate": "0.1"},
        {"service": "review", "unit": "word", "rate": "0.2"},
    ]
    assert c.patch(f"/v1/vendors/{v['id']}", headers=h, json={"rates": dup}).status_code == 422

    ab = c.post(
        f"/v1/vendors/{v['id']}/absences",
        headers=h,
        json={"start_date": "2030-01-02", "end_date": "2030-01-05"},
    )
    assert ab.status_code == 201
    bad = c.post(
        f"/v1/vendors/{v['id']}/absences",
        headers=h,
        json={"start_date": "2030-01-05", "end_date": "2030-01-02"},
    )
    assert bad.status_code == 422
    doc = c.post(
        f"/v1/vendors/{v['id']}/documents",
        headers=h,
        json={"kind": "nda", "title": "NDA 2026", "signed": True, "signed_at": "2026-01-10"},
    )
    assert doc.status_code == 201
    detail = c.get(f"/v1/vendors/{v['id']}", headers=h).json()
    assert detail["nda_signed"] is True and detail["nda_signed_at"] == "2026-01-10"
    assert len(detail["absences"]) == 1 and len(detail["documents"]) == 1 and detail["assignments"] == []
    assert c.delete(f"/v1/vendors/{v['id']}/absences/{ab.json()['id']}", headers=h).status_code == 204

    # tenancy: another org sees 404; a client user may not even read
    hb = register(c, "b@example.com", "Other Org")
    assert c.get(f"/v1/vendors/{v['id']}", headers=hb).status_code == 404
    assert c.patch(f"/v1/vendors/{v['id']}", headers=hb, json={"name": "x"}).status_code == 404
    org = org_of(db)
    u = User(email="cl@example.com", name="C", password_hash="x", role="client", org_id=org.id)
    db.add(u)
    db.commit()
    hc = {"Authorization": f"Bearer {security.issue_token(u.id, 'client', org.id)}"}
    assert c.get("/v1/vendors", headers=hc).status_code == 403

    # DELETE deactivates (POs and invoices keep pointing at the vendor)
    assert c.delete(f"/v1/vendors/{v['id']}", headers=h).json()["status"] == "inactive"


def test_module_disabled_hides_vendor_routes(db):
    c = client()
    h = register(c)
    org = org_of(db)
    org.settings = {"modules": ["tms", "engine", "ai", "community"]}
    db.commit()
    r = c.get("/v1/vendors", headers=h)
    assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled"


def test_vendor_csv_import_creates_updates_and_reports_bad_rows(db):
    c = client()
    h = register(c)
    vendor(c, h, "Ana Lekic", email="ana@vendors.example", capacity=1000)
    csv_data = (
        b"name;email;pairs;services;rate_per_word;currency;capacity_words_per_day;nda_signed;domains\n"
        b"Ana Lekic;ana@vendors.example;en>sr;review;0,045;EUR;5000;yes;legal|pharma\n"
        b"Marko Ilic;marko@vendors.example;en>sr,de>sr;translation|review;0.06;EUR;3000;no;\n"
        b"Broken;broken@vendors.example;ensr;review;0.05;EUR;100;no;\n"
    )
    r = c.post("/v1/vendors/import", headers=h, files={"file": ("vendors.csv", csv_data)})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] == 1 and out["updated"] == 1
    assert [e["row"] for e in out["errors"]] == [4]
    names = {v["name"]: v for v in c.get("/v1/vendors", headers=h).json()["items"]}
    assert names["Ana Lekic"]["capacity_words_per_day"] == 5000 and names["Ana Lekic"]["nda_signed"] is True
    assert names["Ana Lekic"]["domains"] == ["legal", "pharma"]
    assert len(names["Marko Ilic"]["pairs"]) == 2
    assert {r["rate"] for r in names["Marko Ilic"]["rates"]} == {"0.06"}
    bad = c.post("/v1/vendors/import", headers=h, files={"file": ("v.csv", b"email\nx@y.z\n")})
    assert bad.status_code == 422


# --------------------------------------------------------------------------- routing and offers


def test_sequential_offer_decline_accept_work_approve_invoice(db):
    c = client()
    h = register(c)
    hook = c.post(
        "/v1/webhooks", headers=h, json={"url": "http://hooks.example/x", "events": ["job.needs_attention"]}
    )
    assert hook.status_code == 201
    a = vendor(c, h, "Ana Lekic", rate="0.04")
    b = vendor(c, h, "Bojan Peric", rate="0.05")
    wf = workflow(c, h, "full", FULL)
    job_id = order(c, h, workflow_template_id=wf["id"], due_at=due_in(72))["jobs"][0]["id"]

    out = assign(c, h, job_id, vendor_ids=[a["id"], b["id"]], strategy="sequential")
    first, second = out["items"]
    assert first["status"] == "offered" and second["status"] == "pending" and first["link"]
    assert first["messages"][0]["subject"] == "New job offer"
    assert first["messages"][0]["channel"] == "email"
    drain()
    from arbiter.models import EmailMessage

    offer_mail = (
        db.execute(select(EmailMessage).where(EmailMessage.template == "vendor_message")).scalars().first()
    )
    assert offer_mail is not None and offer_mail.status == "logged" and "/vendor/" in offer_mail.body_text
    assert offer_mail.body_text.startswith("Hi Ana Lekic,")
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "review"
    # nothing reached the marketplace: every open segment waits for the assignment
    assert _tasks(db, job_id) == []
    segs = _segs(db, job_id)
    assert segs and all(s.state == "needs_review" and s.signals["route"] == first["id"] for s in segs)

    # a reviewer of the marketplace gets nothing from this job
    rev = active_reviewer(db, "rev@example.com")
    assert review_all(db, rev) == 0

    ta = token_of(first["link"])
    view = c.get(f"/v1/vendor-portal/{ta}").json()
    assert view["assignment"]["status"] == "offered" and view["segments"] == []
    assert "margin" not in str(view) and view["job"]["source_lang"] == "en"
    # the vendor cannot work before accepting
    seg_id = segs[0].id
    assert c.post(f"/v1/vendor-portal/{ta}/segments/{seg_id}", json={"decision": "accept"}).status_code == 409

    r = c.post(f"/v1/vendor-portal/{ta}/decline", json={"reason": "busy"})
    assert r.status_code == 200 and r.json()["assignment"]["status"] == "declined"
    rows = c.get(f"/v1/jobs/{job_id}/assignments", headers=h).json()
    by_id = {x["id"]: x for x in rows["items"]}
    assert by_id[second["id"]]["status"] == "offered"
    assert rows["routes"]["human_review"]["assignment_id"] == second["id"]
    db.expire_all()
    assert all(s.signals["route"] == second["id"] for s in _segs(db, job_id))

    tb = token_of(by_id[second["id"]]["link"])
    acc = c.post(f"/v1/vendor-portal/{tb}/accept")
    assert acc.status_code == 200 and acc.json()["assignment"]["status"] == "accepted"
    po_number = acc.json()["assignment"]["po_number"]
    assert po_number == f"PO-{datetime.now(UTC).year}-0001"
    assert c.post(f"/v1/vendor-portal/{tb}/accept").status_code == 200  # idempotent
    pdf = c.get(f"/v1/vendor-portal/{tb}/po.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    n = work_all(c, tb)
    assert n == len(segs)
    view = c.get(f"/v1/vendor-portal/{tb}").json()
    assert view["assignment"]["status"] == "delivered" and view["remaining"] == 0
    assert all(s["done"] for s in view["segments"])
    drain()
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert job["state"] == "delivered"
    db.expire_all()
    for s in _segs(db, job_id):
        assert s.reviewer_id == b["id"] and s.signals["reviews"][0]["reviewer_id"] == b["id"]

    # PM approves: the vendor fee becomes job cost, the margin includes it
    asg = db.get(VendorAssignment, second["id"])
    expected = max(Decimal("1.00"), (Decimal("0.05") * asg.words).quantize(Decimal("0.01")))
    assert asg.amount == expected
    before = Decimal(job["cost"])
    ap = c.post(f"/v1/assignments/{second['id']}/approve", headers=h)
    assert ap.status_code == 200 and ap.json()["status"] == "approved"
    job = c.get(f"/v1/jobs/{job_id}", headers=h).json()
    assert Decimal(job["cost"]) == before + expected
    assert Decimal(job["margin"]) == Decimal(job["revenue"]) - Decimal(job["cost"])

    period = datetime.now(UTC).strftime("%Y-%m")
    pay = c.get("/v1/payables", headers=h, params={"period": period}).json()
    assert pay["items"][0]["vendor_name"] == "Bojan Peric" and Decimal(pay["items"][0]["accrued"]) == expected

    inv = c.post("/v1/vendor-invoices/auto", headers=h, json={}).json()["items"]
    assert len(inv) == 1 and inv[0]["number"] == f"VI-{datetime.now(UTC).year}-0001"
    assert Decimal(inv[0]["total"]) == expected and inv[0]["lines"][0]["po_number"] == po_number
    db.expire_all()
    assert db.get(VendorAssignment, second["id"]).status == "invoiced"
    po = db.execute(select(PurchaseOrder).where(PurchaseOrder.assignment_id == second["id"])).scalar_one()
    assert po.status == "invoiced" and po.vendor_invoice_id == inv[0]["id"]
    assert c.post("/v1/vendor-invoices/auto", headers=h, json={}).json()["items"] == []  # nothing left

    pay = c.get("/v1/payables", headers=h, params={"period": period}).json()
    assert Decimal(pay["items"][0]["invoiced"]) == expected and Decimal(pay["items"][0]["accrued"]) == 0
    assert c.post(f"/v1/vendor-invoices/{inv[0]['id']}/pay", headers=h).status_code == 409  # not approved yet
    assert c.post(f"/v1/vendor-invoices/{inv[0]['id']}/approve", headers=h).json()["status"] == "approved"
    assert c.post(f"/v1/vendor-invoices/{inv[0]['id']}/pay", headers=h).json()["status"] == "paid"
    pay = c.get("/v1/payables", headers=h, params={"period": period}).json()
    assert Decimal(pay["items"][0]["paid"]) == expected

    csv_out = c.get("/v1/vendor-invoices/export.csv", headers=h, params={"period": period})
    assert csv_out.status_code == 200 and "text/csv" in csv_out.headers["content-type"]
    lines = csv_out.text.strip().splitlines()
    assert lines[0].startswith("invoice_number,") and inv[0]["number"] in lines[1] and po_number in lines[1]

    pos = c.get("/v1/purchase-orders", headers=h).json()["items"]
    assert [p["number"] for p in pos] == [po_number]
    assert c.get(f"/v1/purchase-orders/{pos[0]['id']}/pdf", headers=h).content.startswith(b"%PDF")
    payloads = [d.payload["data"] for d in db.execute(select(WebhookDelivery)).scalars()]
    assert any(p.get("reason") == "vendor_delivered" for p in payloads)


def test_offer_timeout_moves_on_and_exhausted_offers_fall_back_to_marketplace(db):
    c = client()
    h = register(c)
    hook = c.post(
        "/v1/webhooks", headers=h, json={"url": "http://hooks.example/x", "events": ["job.needs_attention"]}
    )
    assert hook.status_code == 201
    a = vendor(c, h, "Ana Lekic")
    b = vendor(c, h, "Bojan Peric")
    job_id = order(c, h, tier="full")["jobs"][0]["id"]
    drain()
    n_segs = len(_segs(db, job_id))
    assert len(_tasks(db, job_id)) == n_segs  # default route: marketplace

    out = assign(c, h, job_id, vendor_ids=[a["id"], b["id"]], offer_timeout_minutes=5)
    first, second = out["items"]
    db.expire_all()
    assert _tasks(db, job_id) == []  # queued marketplace tasks were pulled back

    def expire(asg_id):
        past = datetime.now(UTC) - timedelta(minutes=1)
        db.execute(
            update(VendorAssignment).where(VendorAssignment.id == asg_id).values(offer_expires_at=past)
        )
        db.execute(
            update(WorkItem).where(WorkItem.idempotency_key == f"{asg_id}:offer_timeout").values(run_at=past)
        )
        db.commit()
        drain()
        db.expire_all()

    expire(first["id"])
    assert db.get(VendorAssignment, first["id"]).status == "expired"
    assert db.get(VendorAssignment, second["id"]).status == "offered"
    assert _tasks(db, job_id) == []
    expire(second["id"])
    assert db.get(VendorAssignment, second["id"]).status == "expired"
    # every vendor timed out: the marketplace gets the step back, the PM is told
    assert len(_tasks(db, job_id)) == n_segs
    assert all("route" not in s.signals for s in _segs(db, job_id))
    payloads = [d.payload["data"] for d in db.execute(select(WebhookDelivery)).scalars()]
    assert any(p.get("reason") == "vendor_unassigned" for p in payloads)
    rev = active_reviewer(db, "rev@example.com")
    assert review_all(db, rev) == n_segs
    drain()
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["state"] == "delivered"


def test_broadcast_first_accept_wins_and_others_are_withdrawn(db):
    c = client()
    h = register(c)
    a = vendor(c, h, "Ana Lekic")
    b = vendor(c, h, "Bojan Peric")
    job_id = order(c, h, tier="full")["jobs"][0]["id"]
    out = assign(c, h, job_id, vendor_ids=[a["id"], b["id"]], strategy="broadcast")
    assert [x["status"] for x in out["items"]] == ["offered", "offered"]
    ta, tb = (token_of(x["link"]) for x in out["items"])
    assert c.post(f"/v1/vendor-portal/{tb}/accept").status_code == 200
    # the loser's link is revoked once withdrawn
    assert c.post(f"/v1/vendor-portal/{ta}/accept").status_code == 404
    rows = {x["vendor_id"]: x for x in c.get(f"/v1/jobs/{job_id}/assignments", headers=h).json()["items"]}
    assert rows[a["id"]]["status"] == "withdrawn" and rows[b["id"]]["status"] == "accepted"
    assert rows[a["id"]]["messages"][-1]["subject"] == "Offer taken"


def test_internal_assignment_and_switching_routes(db):
    c = client()
    h = register(c)
    job_id = order(c, h, tier="full")["jobs"][0]["id"]
    drain()
    n_segs = len(_segs(db, job_id))
    pm = db.execute(select(User).where(User.email == "pm@example.com")).scalar_one()

    out = assign(c, h, job_id, mode="internal", user_id=pm.id)
    asg = out["items"][0]
    assert asg["status"] == "accepted" and asg["amount"] == "0.00" and asg["assignee_kind"] == "internal"
    db.expire_all()
    assert _tasks(db, job_id) == []
    # back to the marketplace: tasks come back, the internal assignment is cancelled
    r = c.post(f"/v1/jobs/{job_id}/assignments", headers=h, json={"mode": "marketplace"})
    assert r.status_code == 201 and r.json()["items"] == []
    db.expire_all()
    assert len(_tasks(db, job_id)) == n_segs
    assert db.get(VendorAssignment, asg["id"]).status == "cancelled"
    assert c.get(f"/v1/vendor-portal/{token_of(asg['link'])}").status_code == 404  # revoked

    out = assign(c, h, job_id, mode="internal", user_id=pm.id)
    t = token_of(out["items"][0]["link"])
    assert work_all(c, t, decision="accept") == n_segs
    assert c.get(f"/v1/vendor-portal/{t}").json()["assignment"]["status"] == "delivered"
    drain()
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["state"] == "delivered"
    assert all(s.reviewer_id == pm.id for s in _segs(db, job_id))
    # an internal assignment has no PO
    assert c.get("/v1/purchase-orders", headers=h).json()["items"] == []


def test_second_review_vendor_must_differ_and_both_steps_route(db):
    c = client()
    h = register(c)
    a = vendor(c, h, "Ana Lekic")
    b = vendor(c, h, "Bojan Peric")
    wf = workflow(c, h, "full", FULL_TWO)
    job_id = order(c, h, workflow_template_id=wf["id"])["jobs"][0]["id"]
    one = assign(c, h, job_id, step="human_review", vendor_ids=[a["id"]])["items"][0]
    ta = token_of(one["link"])
    assert c.post(f"/v1/vendor-portal/{ta}/accept").status_code == 200
    r = c.post(
        f"/v1/jobs/{job_id}/assignments", headers=h, json={"step": "second_review", "vendor_ids": [a["id"]]}
    )
    assert r.status_code == 422 and "second review" in r.json()["error"]["message"]
    two = assign(c, h, job_id, step="second_review", vendor_ids=[b["id"]])["items"][0]
    tb = token_of(two["link"])
    assert c.post(f"/v1/vendor-portal/{tb}/accept").status_code == 200
    drain()
    n_segs = len(_segs(db, job_id))
    assert c.get(f"/v1/vendor-portal/{tb}").json()["remaining"] == 0
    assert work_all(c, ta) == n_segs
    db.expire_all()
    assert all(s.signals["route"] == two["id"] for s in _segs(db, job_id))
    assert _tasks(db, job_id) == []
    assert c.get(f"/v1/vendor-portal/{tb}").json()["remaining"] == n_segs
    assert work_all(c, tb) == n_segs
    drain()
    assert c.get(f"/v1/jobs/{job_id}", headers=h).json()["state"] == "delivered"
    for s in _segs(db, job_id):
        assert [r["reviewer_id"] for r in s.signals["reviews"]] == [a["id"], b["id"]]


def test_assignment_validation_tokens_tags_and_reopen(db):
    c = client()
    h = register(c)
    a = vendor(c, h, "Ana Lekic")
    de = vendor(c, h, "Dieter", pair=("en", "de"))
    norate = vendor(c, h, "No Rate", rates=[])
    auto_job = order(c, h, tier="auto")["jobs"][0]["id"]
    r = c.post(f"/v1/jobs/{auto_job}/assignments", headers=h, json={"vendor_ids": [a["id"]]})
    assert r.status_code == 422  # an auto job has no human step
    job_id = order(c, h, tier="full")["jobs"][0]["id"]
    assert (
        c.post(f"/v1/jobs/{job_id}/assignments", headers=h, json={"vendor_ids": [de["id"]]}).status_code
        == 422
    )
    assert (
        c.post(f"/v1/jobs/{job_id}/assignments", headers=h, json={"vendor_ids": [norate["id"]]}).status_code
        == 422
    )
    # a rate given by the PM overrides the vendor's
    over = assign(c, h, job_id, vendor_ids=[norate["id"]], rate="0.02", words=1000)["items"][0]
    assert over["amount"] == "20.00" and over["words"] == 1000
    hb = register(c, "b@example.com", "Other Org")
    assert (
        c.post(f"/v1/jobs/{job_id}/assignments", headers=hb, json={"vendor_ids": [a["id"]]}).status_code
        == 404
    )
    assert c.get("/v1/vendor-portal/not-a-token").status_code == 404

    out = assign(c, h, job_id, vendor_ids=[a["id"]])["items"][0]  # replaces the previous offer
    assert db.get(VendorAssignment, over["id"]).status == "withdrawn"
    t = token_of(out["link"])
    assert c.post(f"/v1/vendor-portal/{t}/accept").status_code == 200
    drain()
    seg = next(s for s in _segs(db, job_id) if "⟦" in s.source_tagged)
    broken = c.post(
        f"/v1/vendor-portal/{t}/segments/{seg.id}",
        json={"decision": "edit", "target_tagged": "⟦9/⟧ unknown code"},
    )
    assert broken.status_code == 422 and broken.json()["error"]["details"]["tag_issues"]
    fixed = seg.target_tagged.replace("⟦/1⟧", " ok⟦/1⟧", 1)
    r = c.post(f"/v1/vendor-portal/{t}/segments/{seg.id}", json={"decision": "edit", "target_tagged": fixed})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Segment, seg.id).target_tagged == fixed and db.get(Segment, seg.id).origin == "human"
    # complete is refused while work is left; then the vendor finishes and the PM sends it back
    assert c.post(f"/v1/vendor-portal/{t}/complete").status_code == 409
    work_all(c, t)
    assert (
        c.post(f"/v1/assignments/{out['id']}/reopen", headers=h, json={"note": "check terms"}).json()[
            "status"
        ]
        == "in_progress"
    )
    assert c.post(f"/v1/vendor-portal/{t}/complete").json()["assignment"]["status"] == "delivered"
    # the PM cannot re-route a delivered step without deciding on it
    r = c.post(f"/v1/jobs/{job_id}/assignments", headers=h, json={"mode": "marketplace"})
    assert r.status_code == 409
    job = db.get(Job, job_id)
    assert job is not None


def test_vendor_invoice_upload_from_workbench(db):
    c = client()
    h = register(c)
    a = vendor(c, h, "Ana Lekic", rate="0.04")
    job_id = order(c, h, tier="full")["jobs"][0]["id"]
    out = assign(c, h, job_id, vendor_ids=[a["id"]])["items"][0]
    t = token_of(out["link"])
    c.post(f"/v1/vendor-portal/{t}/accept")
    drain()
    work_all(c, t)
    files = {"file": ("inv-77.pdf", b"%PDF-1.4 vendor invoice")}
    early = c.post(f"/v1/vendor-portal/{t}/invoice", data={"number": "INV-77"}, files=files)
    assert early.status_code == 409  # not approved yet
    c.post(f"/v1/assignments/{out['id']}/approve", headers=h)
    r = c.post(f"/v1/vendor-portal/{t}/invoice", data={"number": "INV-77"}, files=files)
    assert r.status_code == 201, r.text
    inv = c.get("/v1/vendor-invoices", headers=h).json()["items"][0]
    assert inv["source"] == "upload" and inv["number"] == "INV-77" and inv["has_file"]
    f = c.get(f"/v1/vendor-invoices/{inv['id']}/file", headers=h)
    assert f.status_code == 200 and f.content.startswith(b"%PDF")
    # reject: the work can be invoiced again
    assert c.post(f"/v1/vendor-invoices/{inv['id']}/reject", headers=h).json()["status"] == "rejected"
    db.expire_all()
    assert db.get(VendorAssignment, out["id"]).status == "approved"
    again = c.post(f"/v1/vendor-portal/{t}/invoice", data={"number": "INV-78"}, files=files)
    assert again.status_code == 201
