"""Module pm: capacity planner, assignment suggestions, deadline risk, timeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agency_helpers import client, drain, order, register, workflow
from vendor_helpers import assign, due_in, token_of, vendor

from arbiter.models import Job, VendorAssignment

ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _today():
    return datetime.now(UTC).date()


def test_planner_uses_capacity_absences_and_load(db):
    c = client()
    h = register(c)
    today = _today()
    vendor(c, h, "Ana Slow", capacity=1000, rate="0.03")
    away = vendor(c, h, "Bojan Away", capacity=5000, rate="0.06")
    busy = vendor(c, h, "Cica Busy", capacity=5000, rate="0.02")
    vendor(c, h, "Dieter", pair=("en", "de"), capacity=99999)
    c.post(
        f"/v1/vendors/{away['id']}/absences",
        headers=h,
        json={"start_date": today.isoformat(), "end_date": (today + timedelta(days=1)).isoformat()},
    )
    # Cica already carries 13,500 words due in two days: 4,500 a day of her 5,000
    job_id = order(c, h, tier="full")["jobs"][0]["id"]
    db.add(
        VendorAssignment(
            org_id=db.get(Job, job_id).org_id,
            job_id=job_id,
            step="human_review",
            vendor_id=busy["id"],
            offer_group="ofg_test",
            words=13_500,
            status="in_progress",
            due_at=datetime.combine(today + timedelta(days=2), datetime.min.time(), tzinfo=UTC),
            token_nonce="x",
        )
    )
    db.commit()

    by = today + timedelta(days=2)
    r = c.get(
        "/v1/capacity",
        headers=h,
        params={
            "source_lang": "en",
            "target_lang": "sr",
            "words": 4000,
            "by": by.isoformat(),
            "service": "review",
        },
    )
    assert r.status_code == 200, r.text
    rows = {x["name"]: x for x in r.json()["items"]}
    assert set(rows) == {"Ana Slow", "Bojan Away", "Cica Busy"}  # Dieter has no en>sr
    assert rows["Ana Slow"]["free_words"] == 3000 and rows["Ana Slow"]["can_meet"] is False
    assert rows["Ana Slow"]["earliest_finish"] == (today + timedelta(days=3)).isoformat()
    assert rows["Bojan Away"]["free_words"] == 5000 and rows["Bojan Away"]["can_meet"] is True
    assert rows["Bojan Away"]["earliest_finish"] == by.isoformat()
    assert len(rows["Bojan Away"]["absent_days"]) == 2
    assert rows["Cica Busy"]["free_words"] == 1500 and rows["Cica Busy"]["can_meet"] is False
    assert rows["Bojan Away"]["price"] == {
        "amount": "240.00",
        "rate": "0.06",
        "unit": "word",
        "currency": "EUR",
    }
    assert r.json()["items"][0]["name"] == "Bojan Away" and r.json()["items"][0]["rank"] == 1


def test_suggestions_for_job_rank_vendors_and_exclude_first_reviewer(db):
    c = client()
    h = register(c)
    a = vendor(c, h, "Ana", rate="0.03")
    b = vendor(c, h, "Bojan", rate="0.05")
    wf = workflow(c, h, "full", ["tm", "mt", "qe", "human_review", "second_review", "delivery"])
    job_id = order(c, h, workflow_template_id=wf["id"], due_at=due_in(96))["jobs"][0]["id"]
    s = c.get(f"/v1/jobs/{job_id}/assignment-suggestions", headers=h).json()
    assert [x["name"] for x in s["items"]] == ["Ana", "Bojan"]  # both can meet; Ana is cheaper
    assert s["words"] > 0 and all(x["can_meet"] for x in s["items"])
    one = assign(c, h, job_id, vendor_ids=[a["id"]])["items"][0]
    c.post(f"/v1/vendor-portal/{token_of(one['link'])}/accept")
    s2 = c.get(
        f"/v1/jobs/{job_id}/assignment-suggestions", headers=h, params={"step": "second_review"}
    ).json()
    assert [(x["name"], x["eligible"]) for x in s2["items"]] == [("Bojan", True), ("Ana", False)]
    auto_job = order(c, h, tier="auto")["jobs"][0]["id"]
    assert c.get(f"/v1/jobs/{auto_job}/assignment-suggestions", headers=h).status_code == 422
    assert b


def test_deadline_risk_flags_slow_vendor_in_exceptions_and_timeline(db):
    c = client()
    h = register(c)
    snail = vendor(c, h, "Snail", capacity=1, working_days=ALL_DAYS)
    risky = order(c, h, tier="full", due_at=due_in(10))["jobs"][0]["id"]
    safe = order(c, h, tier="full", due_at=due_in(48))["jobs"][0]["id"]
    out = assign(c, h, risky, vendor_ids=[snail["id"]])["items"][0]
    c.post(f"/v1/vendor-portal/{token_of(out['link'])}/accept")
    drain()

    risk = {r["job_id"]: r for r in c.get("/v1/pm/deadline-risk", headers=h).json()["items"]}
    assert risk[risky]["at_risk"] is True and risk[risky]["routes"]["human_review"]["route"] == "vendor"
    assert risk[risky]["remaining_words"] > 0 and risk[risky]["slack_hours"] < 0
    assert risk[safe]["at_risk"] is False and risk[safe]["routes"]["human_review"]["route"] == "marketplace"
    only = c.get("/v1/pm/deadline-risk", headers=h, params={"only_at_risk": True}).json()["items"]
    assert [r["job_id"] for r in only] == [risky]

    exc = [e for e in c.get("/v1/exceptions", headers=h).json()["items"] if e["kind"] == "deadline_risk"]
    assert [e["job_id"] for e in exc] == [risky] and "estimated finish" in exc[0]["reason"]

    tl = c.get("/v1/pm/timeline", headers=h, params={"days": 7}).json()
    assert len(tl["days"]) == 7 and tl["vendors"][0]["name"] == "Snail"
    day0 = tl["vendors"][0]["days"][0]
    assert day0["capacity"] == 1 and day0["assignments"] == [out["id"]]
    assert {j["job_id"]: j["at_risk"] for j in tl["jobs"]} == {risky: True, safe: False}
    assert any(a["id"] == out["id"] for a in tl["assignments"])
    cal = c.get(f"/v1/vendors/{snail['id']}/calendar", headers=h, params={"days": 3}).json()
    assert len(cal["days"]) == 3 and cal["assignments"][0]["id"] == out["id"]
