"""Module pm: the PM copilot in the assistant (capacity, deadline risk, assignment proposals,
draft quotes), English and Serbian input, plan-then-apply."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from agency_helpers import client, drain, order, org_of, register
from sqlalchemy import select
from vendor_helpers import assign, due_in, token_of, vendor

from arbiter.agency import assistant
from arbiter.agency.heuristic_pm import parse_pm
from arbiter.engines.mock import ScriptedLlm
from arbiter.models import CrmActivity, CrmDeal, VendorAssignment


def _ask(c, h, text, **extra):
    t = c.post("/v1/assistant/threads", headers=h, json={})
    assert t.status_code == 201, t.text
    r = c.post(f"/v1/assistant/threads/{t.json()['id']}/messages", headers=h, json={"content": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()["assistant_message"]


def _apply(c, h, msg_id):
    r = c.post(f"/v1/assistant/messages/{msg_id}/apply", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def test_parse_pm_understands_english_and_serbian():
    today = datetime(2026, 10, 13, tzinfo=UTC).date()  # a Tuesday
    q = parse_pm("Who is free for EN->DE 20k words by Friday?", today)
    assert q is not None
    assert (q["intent"], q["source_lang"], q["target_lang"], q["words"]) == ("capacity", "en", "de", 20000)
    assert q["by"].isoformat() == "2026-10-16"
    q = parse_pm("Ko je slobodan za engleski na nemački, 20.000 reči do petka?", today)
    assert q is not None
    assert (q["intent"], q["source_lang"], q["target_lang"], q["words"]) == ("capacity", "en", "de", 20000)
    assert q["by"].isoformat() == "2026-10-16"
    q = parse_pm("who can take 5,500 words english to french in 3 days", today)
    assert q is not None and (q["target_lang"], q["words"], q["by"].isoformat()) == ("fr", 5500, "2026-10-16")
    assert parse_pm("Which jobs are at risk?", today)["intent"] == "risk"
    assert parse_pm("Koji poslovi su u riziku?", today)["intent"] == "risk"
    assert parse_pm("Šta neće stići na vreme?", today)["intent"] == "risk"
    q = parse_pm("Propose assignments for job job_01M4TN7V4PWH8SMJ7HQJSRFWPV", today)
    assert q["intent"] == "propose_assignment" and q["job_id"] == "job_01m4tn7v4pwh8smj7hqjsrfwpv"
    assert parse_pm("Predloži dodelu za posao Launch, druga revizija", today)["step"] == "second_review"
    q = parse_pm("Draft a quote for Acme: 5000 words EN>DE, full review", today)
    assert (q["intent"], q["words"], q["tier"]) == ("draft_quote", 5000, "full")
    assert (
        parse_pm("Napravi ponudu za Acme, 5000 reči sa engleskog na nemački", today)["intent"]
        == "draft_quote"
    )
    assert parse_pm("do 20.10.", today) is None
    assert parse_pm("We are an agency called Northwind. Our clients are Acme.", today) is None
    assert parse_pm("koliko poslova kasni?", today) is None  # an existing data question, not PM


def test_capacity_question_english_and_serbian(db):
    c = client()
    h = register(c)
    vendor(c, h, "Ana Fast", pair=("en", "de"), capacity=10_000, rate="0.04")
    vendor(c, h, "Bojan Slow", pair=("en", "de"), capacity=1_000, rate="0.03")
    vendor(c, h, "Cedomir", pair=("en", "fr"), capacity=50_000)
    msg = _ask(c, h, "Who is free for EN->DE 20k words in 2 days?")
    assert msg["plan"] == []
    assert "Ana Fast: can make it" in msg["content"] and "Bojan Slow: cannot make it" in msg["content"]
    assert "Cedomir" not in msg["content"] and "1 of 2 can deliver in time." in msg["content"]
    assert "1600.00 EUR" in msg["content"]  # 20,000 x 0.08 translation rate (no service named)
    sr = _ask(c, h, "Ko je slobodan za engleski na nemacki 20.000 reci za 2 dana?", locale="sr-Latn")
    assert (
        "Ana Fast: can make it" in sr["content"]
        and "built-in planner always answers in English" in sr["content"]
    )
    ask = _ask(c, h, "Who is free next week?")
    assert ask["plan"] == [] and "Which language pair?" in ask["content"]


def test_risk_question_lists_jobs_at_risk(db):
    c = client()
    h = register(c)
    snail = vendor(c, h, "Snail", capacity=1)
    risky = order(c, h, tier="full", due_at=due_in(10))["jobs"][0]["id"]
    out = assign(c, h, risky, vendor_ids=[snail["id"]])["items"][0]
    c.post(f"/v1/vendor-portal/{token_of(out['link'])}/accept")
    drain()
    msg = _ask(c, h, "Which jobs are at risk?")
    assert "1 job(s) at risk" in msg["content"] and risky in msg["content"] and "Snail" in msg["content"]
    sr = _ask(c, h, "Koji poslovi su u riziku?")
    assert risky in sr["content"] and msg["plan"] == []


def test_propose_assignments_plan_applies_an_offer(db):
    c = client()
    h = register(c)
    a = vendor(c, h, "Ana", rate="0.03")
    b = vendor(c, h, "Bojan", rate="0.05")
    vendor(c, h, "Dieter", pair=("en", "de"))
    job_id = order(c, h, tier="full", due_at=due_in(96))["jobs"][0]["id"]
    msg = _ask(c, h, f"Propose assignments for job {job_id}")
    assert len(msg["plan"]) == 1
    act = msg["plan"][0]
    assert act["type"] == "create_assignment" and act["data"]["job_id"] == job_id
    assert act["data"]["vendor_ids"] == [a["id"], b["id"]] and act["data"]["strategy"] == "sequential"
    assert "Nothing is sent before that" in msg["content"]
    assert db.execute(select(VendorAssignment)).first() is None  # nothing happens before apply
    res = _apply(c, h, msg["id"])
    assert res[0]["ok"] and res[0]["note"] == "offered to Ana"
    rows = db.execute(select(VendorAssignment).order_by(VendorAssignment.rank)).scalars().all()
    assert [(r.vendor_id, r.status) for r in rows] == [(a["id"], "offered"), (b["id"], "pending")]
    # Serbian, by project name ("Launch" in the helper)
    sr = _ask(c, h, "Predlozi dodelu za posao Launch")
    assert sr["plan"] and sr["plan"][0]["data"]["job_id"] == job_id
    unknown = _ask(c, h, "Propose assignments for job nobody-knows")
    assert unknown["plan"] == [] and "Which job?" in unknown["content"]


def test_draft_quote_uses_the_client_price_list(db):
    c = client()
    h = register(c)
    pl = c.post(
        "/v1/price-lists",
        headers=h,
        json={
            "name": "Acme rates",
            "currency": "EUR",
            "rates": [{"source_lang": "en", "target_lang": "de", "tier": "full", "per_word": "0.10"}],
            "minimum_charge": "30",
        },
    ).json()
    acc = c.post("/v1/crm/accounts", headers=h, json={"name": "Acme", "price_list_id": pl["id"]}).json()
    msg = _ask(c, h, "Draft a quote for Acme: 5000 words EN->DE, full review")
    assert "500.00 EUR" in msg["content"]
    act = msg["plan"][0]
    assert act["type"] == "draft_quote" and act["data"] == {
        "account_id": acc["id"],
        "source_lang": "en",
        "target_langs": ["de"],
        "words": 5000,
        "tier": "full",
    }
    res = _apply(c, h, msg["id"])
    assert res[0]["ok"]
    deal = db.get(CrmDeal, res[0]["id"])
    assert deal.stage == "proposal" and deal.value == Decimal("500.00") and deal.account_id == acc["id"]
    note = db.execute(select(CrmActivity).where(CrmActivity.deal_id == deal.id)).scalar_one()
    assert "500.00 EUR" in note.body
    sr = _ask(c, h, "Napravi ponudu za Acme, 100 reci sa engleskog na nemacki")
    assert "30.00 EUR" in sr["content"] and "minimum charge applied" in sr["content"]
    missing = _ask(c, h, "Draft a quote for Acme")
    assert missing["plan"] == [] and "How many words?" in missing["content"]


def test_model_gets_pm_facts_and_module_gate(db, monkeypatch):
    c = client()
    h = register(c)
    a = vendor(c, h, "Ana", rate="0.03")
    job_id = order(c, h, tier="full")["jobs"][0]["id"]
    answer = {
        "reply": "Offer it to Ana.",
        "plan": [
            {
                "type": "create_assignment",
                "summary": "Offer to Ana",
                "data": {"job_id": job_id, "step": "human_review", "mode": "vendor", "vendor_ids": [a["id"]]},
            }
        ],
    }
    llm = ScriptedLlm({"assistant": [answer, answer]}, name="scripted")
    monkeypatch.setattr(assistant, "_llm", lambda: llm)
    msg = _ask(c, h, f"Who should do job {job_id}? Propose assignments for job {job_id}")
    ctx = llm.calls[0]["payload"]["context"]
    assert ctx["pm"]["query"]["intent"] == "propose_assignment"
    assert (
        ctx["pm"]["query"]["result"][0]["vendor_id"] == a["id"] and ctx["pm"]["vendors"][0]["name"] == "Ana"
    )
    assert msg["plan"][0]["type"] == "create_assignment"
    # without the pm module the assistant itself is gated (D-052): 404 module_disabled
    org = org_of(db)
    org.settings = {"modules": ["tms", "engine", "ai", "community"]}
    db.commit()
    r = c.post("/v1/assistant/threads", headers=h, json={})
    assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled"
    assert len(llm.calls) == 1
