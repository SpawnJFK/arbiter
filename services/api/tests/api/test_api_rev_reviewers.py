"""Reviewer and admin API: apply -> tests -> tasks -> earnings, access control, disputes, payouts."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from api_helpers import client, register
from fastapi.testclient import TestClient
from sqlalchemy import select

_TESTS = Path(__file__).resolve().parent.parent
for _d in ("community", "pipeline"):
    if str(_TESTS / _d) not in sys.path:
        sys.path.append(str(_TESTS / _d))

import comm_helpers  # noqa: E402
import pipe_helpers  # noqa: E402

from arbiter.billing import ledger, usage  # noqa: E402
from arbiter.cli import create_admin  # noqa: E402
from arbiter.community import queue, testing  # noqa: E402
from arbiter.models import Job, Payout, ReviewerTest, ReviewTask  # noqa: E402
from arbiter.pipeline import orchestrator  # noqa: E402
from arbiter.pipeline.worker import run_until_idle  # noqa: E402

PW = "long enough pw"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(c: TestClient, email: str, password: str) -> dict[str, str]:
    r = c.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return _bearer(r.json()["token"])


def _admin(c: TestClient, db) -> dict[str, str]:
    create_admin(db, "ops@example.com", "admin-password-1")
    db.commit()
    return _login(c, "ops@example.com", "admin-password-1")


def _apply(c: TestClient, email: str = "ana@example.com", pairs=(("en", "sr"),)) -> dict:
    r = c.post(
        "/v1/reviewers/apply",
        json={
            "name": "Ana Test",
            "email": email,
            "password": PW,
            "country": "RS",
            "pairs": [{"source_lang": s, "target_lang": t} for s, t in pairs],
            "domains": ["software"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _perfect(items: list[dict]) -> list[dict]:
    return [
        {"index": i, "target": it.get("reference") or it["target"], "errors": it.get("errors", [])}
        for i, it in enumerate(items)
    ]


def _pass_test(c: TestClient, db, h: dict, test_id: str) -> dict:
    r = c.post(f"/v1/reviewer/tests/{test_id}/start", headers=h)
    assert r.status_code == 200, r.text
    started = r.json()
    assert all(set(it) == {"index", "source", "target"} for it in started["items"])  # no answer keys
    items = db.get(ReviewerTest, test_id).items  # the expected answers, straight from the DB
    r = c.post(
        f"/v1/reviewer/attempts/{started['attempt_id']}/submit", json={"answers": _perfect(items)}, headers=h
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_reviewer_apply_tests_tasks_and_earnings(db):
    testing.seed_default_tests(db)
    db.commit()
    c = client()

    out = _apply(c)
    assert out["user"]["role"] == "reviewer" and out["user"]["org_id"] is None
    assert out["profile"]["status"] == "applied" and out["profile"]["pairs"][0]["status"] == "testing"
    assert c.post("/v1/reviewers/apply", json={**_apply_body("ana@example.com")}).status_code == 409
    h = _login(c, "ana@example.com", PW)  # login works for a reviewer account
    me = c.get("/v1/reviewer/me", headers=h).json()
    assert me["balance"] == "0.00" and me["tax_info_complete"] is False

    # Not active yet: no tasks.
    r = c.post("/v1/reviewer/tasks/next", headers=h)
    assert r.status_code == 403 and "not active" in r.json()["error"]["message"]

    tests = c.get("/v1/reviewer/tests", headers=h).json()
    assert tests["next_offset"] is None
    by_kind = {t["kind"]: t for t in tests["items"]}
    assert set(by_kind) == {"language", "practical"}  # en->sr only
    assert by_kind["language"]["status"] == "available" and by_kind["practical"]["status"] == "locked"
    assert c.post(f"/v1/reviewer/tests/{by_kind['practical']['id']}/start", headers=h).status_code == 409

    assert _pass_test(c, db, h, by_kind["language"]["id"])["passed"] is True
    assert _pass_test(c, db, h, by_kind["practical"]["id"])["passed"] is True
    me = c.get("/v1/reviewer/me", headers=h).json()
    assert me["status"] == "active" and me["level"] == "reviewer"
    assert me["pairs"][0]["status"] == "active"

    # Tax info via PATCH.
    r = c.patch(
        "/v1/reviewer/me",
        json={
            "legal_name": "Ana Test",
            "tax_id": "TEST-1",
            "address": "1 Example Street",
            "date_of_birth": "1990-01-01",
            "payout_method": "sepa",
            "payout_details": {"iban": "XX00 TEST"},
        },
        headers=h,
    )
    assert r.status_code == 200 and r.json()["tax_info_complete"] is True
    assert c.patch("/v1/reviewer/me", json={"payout_method": "cash"}, headers=h).status_code == 422

    # A full-tier job waits for humans.
    _, job = pipe_helpers.make_job(db, tier="full")
    orchestrator.start_job(db, job)
    db.commit()
    run_until_idle()
    db.expire_all()
    assert db.get(Job, job.id).state == "review"
    n_tasks = len(db.execute(select(ReviewTask).where(ReviewTask.job_id == job.id)).scalars().all())
    assert n_tasks >= 2

    r = c.post("/v1/reviewer/tasks/next", json={"source_lang": "en", "target_lang": "sr"}, headers=h)
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["source_lang"] == "en" and task["target_lang"] == "sr"
    assert "is_control" not in task and "expected" not in task
    assert c.post("/v1/reviewer/tasks/next", headers=h).json()["id"] == task["id"]  # one held task

    # Release and get it back.
    assert c.post(f"/v1/reviewer/tasks/{task['id']}/release", headers=h).status_code == 204
    assert c.post(f"/v1/reviewer/tasks/{task['id']}/release", headers=h).status_code == 404  # no longer yours
    task = c.post("/v1/reviewer/tasks/next", headers=h).json()

    r = c.post(
        f"/v1/reviewer/tasks/{task['id']}/submit",
        json={
            "decision": "edit",
            "target_tagged": task["target_tagged"],
            "errors": [{"dimension": "fluency", "severity": "minor", "span": "x", "explanation": "style"}],
            "comment": "",
            "time_ms": 60_000,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    paid = r.json()
    assert paid["ok"] is True and Decimal(paid["pay_amount"]) > 0
    assert c.post(
        f"/v1/reviewer/tasks/{task['id']}/submit", json={"decision": "accept"}, headers=h
    ).status_code in (
        404,
        409,
    )

    earn = c.get("/v1/reviewer/earnings", headers=h).json()
    assert earn["balance"] == paid["pay_amount"] and earn["pending"] == "0.00" and earn["paid"] == "0.00"
    assert [e["kind"] for e in earn["entries"]] == ["review_pay"]

    # Work through the rest; then the queue is empty -> 204.
    for _ in range(n_tasks - 1):
        t = c.post("/v1/reviewer/tasks/next", headers=h)
        assert t.status_code == 200, t.text
        r = c.post(
            f"/v1/reviewer/tasks/{t.json()['id']}/submit",
            json={"decision": "accept", "time_ms": 120_000},
            headers=h,
        )
        assert r.status_code == 200, r.text
    r = c.post("/v1/reviewer/tasks/next", headers=h)
    assert r.status_code == 204 and r.content == b""


def _apply_body(email: str) -> dict:
    return {
        "name": "Dup",
        "email": email,
        "password": PW,
        "country": "RS",
        "pairs": [{"source_lang": "en", "target_lang": "sr"}],
    }


def test_role_guards(db):
    c = client()
    customer = register(c)
    admin = _admin(c, db)
    reviewer = _bearer(_apply(c)["token"])
    reviewer_paths = [
        ("get", "/v1/reviewer/me"),
        ("get", "/v1/reviewer/tests"),
        ("post", "/v1/reviewer/tasks/next"),
        ("get", "/v1/reviewer/earnings"),
    ]
    admin_paths = [
        ("get", "/v1/admin/reviewers"),
        ("get", "/v1/admin/disputes"),
        ("get", "/v1/admin/payouts"),
        ("post", "/v1/admin/payouts/run"),
        ("get", "/v1/admin/orgs"),
    ]
    for method, path in reviewer_paths:
        assert getattr(c, method)(path, headers=customer).status_code == 403, path
        assert getattr(c, method)(path, headers=admin).status_code == 403, path
        assert getattr(c, method)(path).status_code == 401, path
    for method, path in admin_paths:
        assert getattr(c, method)(path, headers=customer).status_code == 403, path
        assert getattr(c, method)(path, headers=reviewer).status_code == 403, path
        assert getattr(c, method)(path, headers=admin).status_code == 200, path
    # A customer API key is not a reviewer either.
    key = c.post("/v1/api-keys", json={"name": "ci"}, headers=customer).json()["key"]
    assert c.get("/v1/reviewer/me", headers=_bearer(key)).status_code == 403
    assert c.get("/v1/admin/orgs", headers=_bearer(key)).status_code == 403


def test_admin_approves_and_suspends_reviewer(db):
    c = client()
    admin = _admin(c, db)
    out = _apply(c)
    rid = out["profile"]["id"]
    h = _bearer(out["token"])

    listed = c.get("/v1/admin/reviewers", params={"status": "applied"}, headers=admin).json()
    assert [p["id"] for p in listed["items"]] == [rid] and listed["next_offset"] is None
    assert c.get("/v1/admin/reviewers", params={"status": "nope"}, headers=admin).status_code == 422

    r = c.post(
        f"/v1/admin/reviewers/{rid}/status", json={"status": "active", "level": "senior"}, headers=admin
    )
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["level"] == "senior"
    # Active profile but no active pair and no work: nothing to do, not forbidden.
    assert c.post("/v1/reviewer/tasks/next", headers=h).status_code == 204

    r = c.post(f"/v1/admin/reviewers/{rid}/status", json={"status": "suspended"}, headers=admin)
    assert r.json()["status"] == "suspended"
    r = c.post("/v1/reviewer/tasks/next", headers=h)
    assert r.status_code == 403 and "suspended" in r.json()["error"]["message"]
    assert c.get("/v1/reviewer/me", headers=h).status_code == 200  # can still see the profile
    assert [
        p["id"] for p in c.get("/v1/admin/reviewers?status=suspended", headers=admin).json()["items"]
    ] == [rid]
    assert (
        c.post("/v1/admin/reviewers/rvw_missing/status", json={"status": "active"}, headers=admin).status_code
        == 404
    )


def test_dispute_flow_through_api(db):
    org = comm_helpers.make_org(db)
    job, segs = comm_helpers.make_job(db, org, ["Save your changes before closing the window."])
    queue.create_task(
        db,
        segs[0],
        job,
        is_control=True,
        expected={"decision": "edit", "errors": [{"span": "posle", "severity": "major"}]},
    )
    comm_helpers.make_reviewer(db, email="rev@example.com")
    db.commit()
    c = client()
    admin = _admin(c, db)
    h = _login(c, "rev@example.com", "correct horse battery")

    task = c.post("/v1/reviewer/tasks/next", headers=h).json()
    r = c.post(
        f"/v1/reviewer/tasks/{task['id']}/submit", json={"decision": "accept", "time_ms": 60_000}, headers=h
    )
    assert r.json() == {"ok": True, "pay_amount": "0.00", "state": "rejected"}
    earn = c.get("/v1/reviewer/earnings", headers=h).json()
    assert earn["balance"] == "0.00" and earn["rejected_tasks"][0]["task_id"] == task["id"]

    assert (
        c.post("/v1/reviewer/disputes", json={"task_id": task["id"], "reason": ""}, headers=h).status_code
        == 422
    )
    r = c.post(
        "/v1/reviewer/disputes", json={"task_id": task["id"], "reason": "The target was correct."}, headers=h
    )
    assert r.status_code == 201, r.text
    dispute = r.json()
    assert dispute["id"] and dispute["due_at"]
    assert (
        c.post(
            "/v1/reviewer/disputes", json={"task_id": task["id"], "reason": "again"}, headers=h
        ).status_code
        == 409
    )

    listed = c.get("/v1/admin/disputes", params={"status": "open"}, headers=admin).json()["items"]
    assert [d["id"] for d in listed] == [dispute["id"]]
    assert (
        c.post(
            f"/v1/admin/disputes/{dispute['id']}/decide", json={"outcome": "maybe"}, headers=admin
        ).status_code
        == 422
    )
    r = c.post(
        f"/v1/admin/disputes/{dispute['id']}/decide",
        json={"outcome": "overturned", "note": "Reviewer is right."},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["status"] == "overturned"
    assert r.json()["decided_by"] is not None
    assert c.get("/v1/reviewer/earnings", headers=h).json()["balance"] == "0.03"
    again = c.post(f"/v1/admin/disputes/{dispute['id']}/decide", json={"outcome": "upheld"}, headers=admin)
    assert again.status_code == 409


def _credit(db, reviewer_id: str, amount: str) -> None:
    ledger.post(
        db,
        credit=ledger.reviewer_account(reviewer_id),
        debit=ledger.REVIEW_COST,
        amount=Decimal(amount),
        kind="review_pay",
        ref="test",
    )


def test_payout_run_pays_complete_tax_info_and_blocks_incomplete(db):
    ok = comm_helpers.make_reviewer(db, email="paid@example.com", threshold="10")
    blocked = comm_helpers.make_reviewer(db, email="blocked@example.com", threshold="10", tax=False)
    _credit(db, ok.id, "25.00")
    _credit(db, blocked.id, "30.00")
    db.commit()
    c = client()
    admin = _admin(c, db)

    r = c.post("/v1/admin/payouts/run", headers=admin)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] == 1 and out["total"] == "25.00" and out["blocked"] == 1
    assert out["provider"] == "mock" and out["send"]["settled"] == 1

    items = c.get("/v1/admin/payouts", headers=admin).json()["items"]
    by_reviewer = {p["reviewer_id"]: p for p in items}
    assert by_reviewer[ok.id]["state"] == "settled" and by_reviewer[ok.id]["amount"] == "25.00"
    assert by_reviewer[blocked.id]["state"] == "blocked"
    assert set(by_reviewer[ok.id]) >= {"id", "reviewer_id", "amount", "state", "created_at"}
    blocked_only = c.get("/v1/admin/payouts", params={"state": "blocked"}, headers=admin).json()["items"]
    assert [p["reviewer_id"] for p in blocked_only] == [blocked.id]

    h = _login(c, "paid@example.com", "correct horse battery")
    earn = c.get("/v1/reviewer/earnings", headers=h).json()
    assert earn["balance"] == "0.00" and earn["paid"] == "25.00"
    hb = _login(c, "blocked@example.com", "correct horse battery")
    assert c.get("/v1/reviewer/earnings", headers=hb).json()["balance"] == "30.00"  # still owed
    db.expire_all()
    assert db.query(Payout).count() == 2

    # Running again the same day creates nothing new.
    again = c.post("/v1/admin/payouts/run", headers=admin).json()
    assert again["created"] == 0 and again["blocked"] == 1


def test_admin_orgs_with_usage_and_create_test(db):
    c = client()
    customer = register(c, email="pm@acme.com", org="Acme Test")
    admin = _admin(c, db)
    org_id = c.get("/v1/org", headers=customer).json()["id"]
    usage.record(db, org_id, None, "word", Decimal("1200"), Decimal("0"), "test:words:1")
    db.commit()

    orgs = c.get("/v1/admin/orgs", headers=admin).json()
    row = next(o for o in orgs["items"] if o["id"] == org_id)
    assert row["name"] == "Acme Test"
    assert row["usage"]["words"] == 1200 and row["usage"]["jobs"] == 0
    assert row["usage"]["period"] == usage.current_period()
    page = c.get("/v1/admin/orgs", params={"limit": 1}, headers=admin).json()
    assert len(page["items"]) == 1

    body = {
        "kind": "language",
        "source_lang": "en",
        "target_lang": "fr",
        "domain": "general",
        "items": [{"source": "Hello.", "target": "Bonjour.", "errors": [], "reference": "Bonjour."}],
        "pass_mark": 75,
        "time_limit_min": 20,
    }
    r = c.post("/v1/admin/tests", json=body, headers=admin)
    assert r.status_code == 201, r.text
    assert r.json()["target_lang"] == "fr" and r.json()["item_count"] == 1
    assert c.post("/v1/admin/tests", json={**body, "items": []}, headers=admin).status_code == 422
    assert c.post("/v1/admin/tests", json=body, headers=customer).status_code == 403
