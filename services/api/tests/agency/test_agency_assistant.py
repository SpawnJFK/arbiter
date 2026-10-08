"""The Agency OS assistant: heuristic planner (Serbian and English), apply (all, subset, twice),
data questions from the context, and the real-model path with plan validation."""

from __future__ import annotations

import json
from datetime import timedelta

from agency_helpers import client, drain, org_of, project, quote, register, upload
from sqlalchemy import func, select

from arbiter.agency import assistant
from arbiter.engines.mock import ScriptedLlm
from arbiter.models import CrmAccount, Dashboard, PriceList, WorkflowTemplate, utcnow

SR = (
    "Mi smo agencija Primer Prevodi Demo. Naši klijenti su Acme d.o.o., Beta Pharma i Gamma Soft. "
    "Workflow: MT, pa QE, pa revizija, pa druga revizija za farmaciju, i odobrenje klijenta. "
    "Cena 0.08 EUR po reči. Hoću dashboard sa prihodom, maržom i poslovima koji kasne."
)
EN = (
    "We are a translation agency called Primer Prevodi Demo. Our clients are Acme Ltd, Beta Pharma and Gamma Soft. "
    "Our workflow: MT, then QE, then review, then a second review, and client approval. "
    "We charge 8 cents per word. I want a dashboard with revenue, margin and overdue jobs."
)


def _ask(c, h, text, thread_id=None, **extra):
    if thread_id is None:
        t = c.post("/v1/assistant/threads", headers=h, json={})
        assert t.status_code == 201, t.text
        thread_id = t.json()["id"]
    r = c.post(f"/v1/assistant/threads/{thread_id}/messages", headers=h, json={"content": text, **extra})
    assert r.status_code == 201, r.text
    return thread_id, r.json()["assistant_message"]


def _apply(c, h, msg_id, actions=None):
    body = {} if actions is None else {"actions": actions}
    r = c.post(f"/v1/assistant/messages/{msg_id}/apply", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()["results"]


def _kinds(action):
    return [s["kind"] for s in action["data"]["steps"]]


def _counts(db, org_id):
    def n(model, *where):
        return db.execute(
            select(func.count()).select_from(model).where(model.org_id == org_id, *where)
        ).scalar_one()

    db.expire_all()
    return {
        "accounts": n(CrmAccount),
        "price_lists": n(PriceList),
        "workflows": n(WorkflowTemplate, WorkflowTemplate.preset_key.is_(None)),
        "dashboards": n(Dashboard),
    }


def test_serbian_description_plan_apply_all_and_twice(db):
    """Serbian input is understood; the output (locale en, the default) is English."""
    c = client()
    h = register(c)
    thread_id, msg = _ask(c, h, SR)
    plan = msg["plan"]
    types = [a["type"] for a in plan]
    assert types[0] == "update_org" and plan[0]["data"]["name"] == "Primer Prevodi Demo"
    assert (
        plan[0]["summary"]
        == 'Organization settings: name "Primer Prevodi Demo", vertical: translation agency'
    )
    assert [a["data"].get("name") for a in plan] == [
        "Primer Prevodi Demo",
        "Standard workflow",
        "Pharma workflow",
        "Standard price list",
        "Acme d.o.o.",
        "Beta Pharma",
        "Gamma Soft",
        "Business overview",
    ]
    assert plan[1]["summary"].startswith('Workflow "Standard workflow": TM > MT > QE > review')
    assert plan[3]["summary"] == 'Price list "Standard price list": 0.08 EUR/word (full)'
    assert plan[5]["summary"] == 'Client "Beta Pharma" (pharma, stricter workflow)'
    assert plan[7]["summary"].startswith('Dashboard "Business overview": revenue')
    assert msg["content"].startswith("Here is a proposed setup based on your description:")
    assert "This answer is in English" not in msg["content"]
    workflows = [a for a in plan if a["type"] == "create_workflow"]
    assert ["tm", "mt", "qe", "human_review", "second_review", "client_review", "delivery"] in [
        _kinds(w) for w in workflows
    ]
    main = workflows[0]
    assert _kinds(main) == ["tm", "mt", "qe", "human_review", "client_review", "delivery"]
    pl = next(a for a in plan if a["type"] == "create_price_list")
    assert pl["data"]["currency"] == "EUR" and [r["per_word"] for r in pl["data"]["rates"]] == ["0.08"]
    accounts = [a for a in plan if a["type"] == "create_account"]
    assert [a["data"]["name"] for a in accounts] == ["Acme d.o.o.", "Beta Pharma", "Gamma Soft"]
    dash = next(a for a in plan if a["type"] == "create_dashboard")
    metrics = {w["metric"] for w in dash["data"]["widgets"]}
    assert {"revenue", "margin", "jobs_overdue"} <= metrics
    assert msg["applied"] == [] and msg["role"] == "assistant"
    assert "language pairs" in msg["content"]  # asks for the language pairs, in English

    org = org_of(db)
    assert _counts(db, org.id) == {"accounts": 0, "price_lists": 0, "workflows": 0, "dashboards": 0}
    results = _apply(c, h, msg["id"])
    assert [r["ok"] for r in results] == [True] * len(plan), results
    db.expire_all()
    assert org_of(db).name == "Primer Prevodi Demo" and org_of(db).vertical == "translation_agency"
    assert _counts(db, org.id) == {"accounts": 3, "price_lists": 1, "workflows": 2, "dashboards": 1}
    accs = {a["name"]: a for a in c.get("/v1/crm/accounts", headers=h).json()["items"]}
    wfs = {w["id"]: w for w in c.get("/v1/workflows", headers=h).json()["items"]}
    beta_wf = wfs[accs["Beta Pharma"]["workflow_template_id"]]
    acme_wf = wfs[accs["Acme d.o.o."]["workflow_template_id"]]
    assert "second_review" in [s["kind"] for s in beta_wf["steps"]]
    assert "second_review" not in [s["kind"] for s in acme_wf["steps"]] and acme_wf["is_default"]
    pl_id = {a["price_list_id"] for a in accs.values()}
    assert len(pl_id) == 1 and None not in pl_id
    price_list = c.get(f"/v1/price-lists/{pl_id.pop()}", headers=h).json()
    assert price_list["rates"] == [
        {"source_lang": None, "target_lang": None, "tier": "full", "per_word": "0.08"}
    ]

    # applying again changes nothing
    again = _apply(c, h, msg["id"])
    assert all(r["ok"] and r.get("skipped") for r in again)
    assert [r["id"] for r in again] == [r["id"] for r in results]
    assert _counts(db, org.id) == {"accounts": 3, "price_lists": 1, "workflows": 2, "dashboards": 1}
    thread = c.get(f"/v1/assistant/threads/{thread_id}", headers=h).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
    assert thread["messages"][1]["applied"] == list(range(len(plan)))
    assert thread["title"].startswith("Mi smo agencija Primer Prevodi Demo")

    # the same description in a new thread does not duplicate objects (matched by name)
    _, msg2 = _ask(c, h, SR)
    results2 = _apply(c, h, msg2["id"])
    assert all(r["ok"] for r in results2)
    assert _counts(db, org.id) == {"accounts": 3, "price_lists": 1, "workflows": 2, "dashboards": 1}

    # the applied account can now order with its price list and workflow
    f = upload(c, h)
    q = quote(c, h, f["id"], account_id=accs["Beta Pharma"]["id"])
    assert q["tiers"]["full"]["rate_per_word"] == "0.08"
    prj = project(c, h, q["id"])
    assert prj["workflow_template_id"] == beta_wf["id"] and prj["tier"] == "full"


def test_apply_subset_only_creates_those(db):
    c = client()
    h = register(c)
    _, msg = _ask(c, h, SR)
    plan = msg["plan"]
    acme = next(i for i, a in enumerate(plan) if a["type"] == "create_account")
    results = _apply(c, h, msg["id"], [acme])
    assert len(results) == 1 and results[0]["ok"] and results[0]["index"] == acme
    assert len(results[0]["warnings"]) == 2  # workflow and price list links skipped (not applied)
    org = org_of(db)
    assert _counts(db, org.id) == {"accounts": 1, "price_lists": 0, "workflows": 0, "dashboards": 0}
    assert org.name != "Primer Prevodi Demo"
    acc = c.get(f"/v1/crm/accounts/{results[0]['id']}", headers=h).json()
    assert acc["price_list_id"] is None and acc["workflow_template_id"] is None
    # a later apply of the rest links new objects; the applied index is skipped
    rest = _apply(c, h, msg["id"])
    assert next(r for r in rest if r["index"] == acme).get("skipped")
    assert _counts(db, org.id) == {"accounts": 3, "price_lists": 1, "workflows": 2, "dashboards": 1}
    r = c.post(f"/v1/assistant/messages/{msg['id']}/apply", headers=h, json={"actions": [99]})
    assert r.status_code == 422


def test_english_variant(db):
    c = client()
    h = register(c)
    _, msg = _ask(c, h, EN)
    plan = msg["plan"]
    assert plan[0]["type"] == "update_org" and plan[0]["data"]["name"] == "Primer Prevodi Demo"
    wf = [a for a in plan if a["type"] == "create_workflow"]
    assert len(wf) == 1
    assert _kinds(wf[0]) == ["tm", "mt", "qe", "human_review", "second_review", "client_review", "delivery"]
    assert wf[0]["data"]["tier"] == "full"
    pl = next(a for a in plan if a["type"] == "create_price_list")
    assert pl["data"]["rates"][0]["per_word"] == "0.08" and pl["data"]["currency"] == "EUR"
    assert [a["data"]["name"] for a in plan if a["type"] == "create_account"] == [
        "Acme Ltd",
        "Beta Pharma",
        "Gamma Soft",
    ]
    dash = next(a for a in plan if a["type"] == "create_dashboard")
    assert {"revenue", "margin", "jobs_overdue"} <= {w["metric"] for w in dash["data"]["widgets"]}
    assert "language pairs" in msg["content"]
    assert all(r["ok"] for r in _apply(c, h, msg["id"]))


def test_heuristic_notes_dtp_team_and_questions():
    reply, plan = assistant.heuristic_plan(
        "Our process: DeepL, then QE, then proofreading, then DTP. We have 5 translators. "
        "Our clients: Delta Bank, Omega Legal.",
        {"org": {"name": "X", "vertical": "software", "regulated": True}},
    )
    wf = next(a for a in plan if a["type"] == "create_workflow")
    kinds = [s["kind"] for s in wf["data"]["steps"]]
    assert kinds == ["tm", "mt", "qe", "human_review", "delivery"] and wf["data"]["steps"][1]["params"] == {
        "engine": "deepl"
    }
    assert wf["data"]["tier"] == "full"
    assert [a["data"].get("industry") for a in plan if a["type"] == "create_account"] == ["finance", "legal"]
    assert "DTP" in reply and "/reviewers/apply" in reply and "per word" in reply
    # R-SEG-12: a regulated org asking for machine-only output still gets a human
    _, plan2 = assistant.heuristic_plan("Workflow: MT then QE then delivery.", {"org": {"regulated": True}})
    wf2 = plan2[0]["data"]
    assert wf2["tier"] == "full" and "human_review" in [s["kind"] for s in wf2["steps"]]


def test_data_question_answered_from_context_with_empty_plan(db):
    c = client()
    h = register(c)
    f = upload(c, h)
    q = quote(c, h, f["id"])
    late = project(c, h, q["id"], tier="full", due_at=(utcnow() - timedelta(hours=5)).isoformat())
    drain()
    _, msg = _ask(c, h, "koliko poslova kasni?")
    assert msg["plan"] == []
    assert "1 job is overdue" in msg["content"] and late["jobs"][0]["id"] in msg["content"]
    _, msg = _ask(c, h, "How many jobs are overdue?")
    assert msg["plan"] == [] and "1 job is overdue" in msg["content"]
    _, msg = _ask(c, h, "Koliki je prihod?")
    assert msg["plan"] == [] and "0.00 EUR" in msg["content"]


def test_real_model_path_validates_and_drops_invalid_actions(db, monkeypatch):
    answer = {
        "reply": "Here is a plan.",
        "plan": [
            {
                "type": "create_workflow",
                "summary": "Full review",
                "data": {
                    "name": "Full",
                    "tier": "full",
                    "steps": [{"kind": "mt"}, {"kind": "qe"}, {"kind": "human_review"}, {"kind": "delivery"}],
                },
            },
            {  # invalid: tier auto with a human review step
                "type": "create_workflow",
                "summary": "Broken",
                "data": {
                    "name": "Broken",
                    "tier": "auto",
                    "steps": [{"kind": "mt"}, {"kind": "human_review"}, {"kind": "delivery"}],
                },
            },
            {
                "type": "create_account",
                "summary": "Acme",
                "data": {"name": "Acme", "kind": "client", "workflow_template_id": "@0"},
            },
            {  # invented: the user never named this client
                "type": "create_account",
                "summary": "Invented",
                "data": {"name": "Zeta Corp", "kind": "client"},
            },
            {"type": "launch_rocket", "summary": "nope", "data": {}},
            {
                "type": "create_contact",
                "summary": "Ana",
                "data": {"account_id": "@2", "name": "Ana", "email": "ana@acme.example"},
            },
            {
                "type": "create_deal",
                "summary": "Deal",
                "data": {"account_id": "@2", "title": "Website", "value": "1200"},
            },
        ],
    }
    llm = ScriptedLlm({"assistant": [answer]}, name="scripted")
    monkeypatch.setattr(assistant, "_llm", lambda: llm)
    c = client()
    h = register(c)
    _, msg = _ask(c, h, "Our client is Acme, contact Ana (ana@acme.example). Set up a full review workflow.")
    call = llm.calls[0]
    assert call["system"] == assistant.SYSTEM_PROMPT
    assert (
        call["payload"]["task"] == "assistant"
        and call["payload"]["prompt_version"] == assistant.ASSISTANT_PROMPT_VERSION
    )
    assert call["payload"]["context"]["org"]["name"] == "Acme GmbH"
    assert "jobs" in call["payload"]["context"] and "revenue_90d" in call["payload"]["context"]
    plan = msg["plan"]
    assert [a["type"] for a in plan] == ["create_workflow", "create_account", "create_contact", "create_deal"]
    # references were renumbered after the drops
    assert plan[1]["data"]["workflow_template_id"] == "@0"
    assert plan[2]["data"]["account_id"] == "@1" and plan[3]["data"]["account_id"] == "@1"
    assert "3 proposed action(s) were dropped" in msg["content"]
    assert "Zeta Corp" in msg["content"] and "launch_rocket" in msg["content"]
    results = _apply(c, h, msg["id"])
    assert all(r["ok"] for r in results), results
    acc = c.get(f"/v1/crm/accounts/{results[1]['id']}", headers=h).json()
    assert acc["workflow_template_id"] == results[0]["id"]
    assert [x["email"] for x in acc["contacts"]] == ["ana@acme.example"] and len(acc["deals"]) == 1


def test_real_model_r_seg_12_and_failure_falls_back(db, monkeypatch):
    c = client()
    h = register(c)
    assert c.patch("/v1/org", headers=h, json={"regulated": True}).status_code == 200
    bad = {
        "reply": "ok",
        "plan": [
            {
                "type": "create_workflow",
                "summary": "x",
                "data": {"name": "Fast", "tier": "auto", "steps": [{"kind": "mt"}, {"kind": "delivery"}]},
            },
            {"type": "update_org", "summary": "y", "data": {"default_tier": "ai_review"}},
        ],
    }
    from arbiter.contracts import EngineError

    llm = ScriptedLlm({"assistant": [bad, EngineError("boom")]}, name="scripted")
    monkeypatch.setattr(assistant, "_llm", lambda: llm)
    _, msg = _ask(c, h, "Make it fast")
    assert msg["plan"] == [] and "R-SEG-12" in msg["content"]
    # the model fails: the built-in planner answers and says so
    _, msg = _ask(c, h, "koliko poslova kasni?")
    assert msg["plan"] == [] and "No job is overdue." in msg["content"]
    assert "built-in planner" in msg["content"]


def test_assistant_tenancy_and_validation(db):
    c = client()
    ha = register(c, "a@example.com", "Org A")
    hb = register(c, "b@example.com", "Org B")
    thread_id, msg = _ask(c, ha, SR)
    assert c.get(f"/v1/assistant/threads/{thread_id}", headers=hb).status_code == 404
    assert (
        c.post(f"/v1/assistant/threads/{thread_id}/messages", headers=hb, json={"content": "x"}).status_code
        == 404
    )
    assert c.post(f"/v1/assistant/messages/{msg['id']}/apply", headers=hb, json={}).status_code == 404
    assert c.get("/v1/assistant/threads", headers=hb).json()["items"] == []
    assert len(c.get("/v1/assistant/threads", headers=ha).json()["items"]) == 1
    assert (
        c.post(f"/v1/assistant/threads/{thread_id}/messages", headers=ha, json={"content": ""}).status_code
        == 422
    )
    thread = c.get(f"/v1/assistant/threads/{thread_id}", headers=ha).json()
    user_msg = thread["messages"][0]
    assert user_msg["plan"] is None
    r = c.post(f"/v1/assistant/messages/{user_msg['id']}/apply", headers=ha, json={})
    assert r.status_code == 409
    named = c.post("/v1/assistant/threads", headers=ha, json={"title": "Setup"}).json()
    assert named["title"] == "Setup" and named["messages"] == []
    assert json.loads(json.dumps(msg))  # plain JSON


def test_locale_reaches_the_model_prompt(db, monkeypatch):
    answer = {
        "reply": "Hier ist ein Plan.",
        "plan": [
            {
                "type": "create_dashboard",
                "summary": "Dashboard Geschäftsübersicht",
                "data": {
                    "name": "Geschäftsübersicht",
                    "widgets": [{"type": "kpi", "metric": "revenue", "title": "Umsatz"}],
                },
            }
        ],
    }
    llm = ScriptedLlm({"assistant": [answer]}, name="scripted")
    monkeypatch.setattr(assistant, "_llm", lambda: llm)
    c = client()
    h = register(c)
    _, msg = _ask(c, h, "Hoću dashboard sa prihodom.", locale="DE")
    payload = llm.calls[0]["payload"]
    assert payload["locale"] == "de" and payload["message"] == "Hoću dashboard sa prihodom."
    assert '"locale"' in llm.calls[0]["system"] and assistant.ASSISTANT_PROMPT_VERSION == "2026-10-08.1"
    assert msg["content"] == "Hier ist ein Plan."
    assert msg["plan"][0]["data"]["widgets"][0]["title"] == "Umsatz"


def test_heuristic_answers_in_english_with_a_note_for_other_locales(db):
    c = client()
    h = register(c)
    _, msg = _ask(c, h, SR, locale="sr-latn")
    assert msg["plan"][1]["data"]["name"] == "Standard workflow"
    assert "This answer is in English" in msg["content"] and "sr-Latn" in msg["content"]
    _, msg = _ask(c, h, "How many jobs are overdue?", locale="en-GB")
    assert "This answer is in English" not in msg["content"]
    t = c.post("/v1/assistant/threads", headers=h, json={}).json()
    r = c.post(
        f"/v1/assistant/threads/{t['id']}/messages",
        headers=h,
        json={"content": "x", "locale": "not a locale"},
    )
    assert r.status_code == 422


def test_heuristic_short_we_are_sentence_sets_org_name():
    from arbiter.agency.heuristic import heuristic_plan

    _, plan = heuristic_plan("We are Northwind Language Services. Our clients are Acme Ltd and Gamma Soft.")
    assert plan[0]["type"] == "update_org"
    assert plan[0]["data"]["name"] == "Northwind Language Services"
