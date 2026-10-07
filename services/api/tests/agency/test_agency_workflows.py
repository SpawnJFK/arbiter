"""Workflow templates: validation rules, presets, project snapshot (R-SEG-12 included)."""

from __future__ import annotations

import pytest
from agency_helpers import client, order, register, workflow

from arbiter.agency.workflows import WorkflowInvalid, validate_steps


def _steps(*kinds):
    return [{"kind": k} for k in kinds]


@pytest.mark.parametrize(
    ("tier", "kinds", "message"),
    [
        ("auto", ["qe", "delivery"], "mt or tm"),
        ("auto", ["mt", "delivery", "qe"], "delivery must be the last"),
        ("auto", ["mt", "qe"], "delivery must be the last"),
        ("full", ["mt", "human_review", "qe", "delivery"], "qe must come before any review"),
        ("full", ["mt", "human_review", "delivery"], "qe must come before any review"),
        ("auto", ["qe", "mt", "delivery"], "must come before qe"),
        ("full", ["mt", "qe", "second_review", "human_review", "delivery"], "second_review needs"),
        ("full", ["mt", "qe", "delivery"], "tier full needs a human_review"),
        ("auto", ["mt", "qe", "human_review", "delivery"], "tier auto cannot"),
        ("ai_review", ["mt", "qe", "human_review", "delivery"], "tier ai_review cannot"),
        ("full", ["mt", "mt", "qe", "human_review", "delivery"], "once"),
        ("full", ["tm", "qe", "delivery"], "TM-only"),
    ],
)
def test_validation_rules(tier, kinds, message):
    with pytest.raises(WorkflowInvalid, match=message):
        validate_steps(_steps(*kinds), tier, regulated=False)


def test_validation_params_and_valid_shapes():
    out = validate_steps(
        [
            {"kind": "tm"},
            {"kind": "mt", "params": {"engine": "deepl"}},
            {"kind": "qe", "params": {"threshold": 85}},
            {"kind": "human_review", "params": {"min_level": "senior"}},
            {"kind": "second_review"},
            {"kind": "client_review"},
            {"kind": "delivery"},
        ],
        "full",
        regulated=True,
    )
    assert out[2] == {"kind": "qe", "params": {"threshold": 85.0}}
    with pytest.raises(WorkflowInvalid, match="threshold"):
        validate_steps(
            [{"kind": "mt"}, {"kind": "qe", "params": {"threshold": 150}}, {"kind": "delivery"}],
            "auto",
            regulated=False,
        )
    with pytest.raises(WorkflowInvalid, match="min_level"):
        validate_steps(
            [
                {"kind": "mt"},
                {"kind": "qe"},
                {"kind": "human_review", "params": {"min_level": "boss"}},
                {"kind": "delivery"},
            ],
            "full",
            regulated=False,
        )
    with pytest.raises(WorkflowInvalid, match="does not take"):
        validate_steps(
            [{"kind": "mt", "params": {"speed": 1}}, {"kind": "delivery"}], "auto", regulated=False
        )
    # TM-only with a human translator, client approval on auto
    validate_steps(_steps("tm", "qe", "human_review", "delivery"), "full", regulated=False)
    validate_steps(_steps("tm", "mt", "qe", "client_review", "delivery"), "auto", regulated=False)


def test_r_seg_12_regulated_rejects_auto_and_ai_review_workflows(db):
    c = client()
    h = register(c)
    assert c.patch("/v1/org", headers=h, json={"regulated": True}).status_code == 200
    for tier, kinds in (
        ("auto", ["mt", "qe", "delivery"]),
        ("ai_review", ["mt", "qe", "ai_review", "delivery"]),
    ):
        r = c.post("/v1/workflows", headers=h, json={"name": "x", "tier": tier, "steps": _steps(*kinds)})
        assert r.status_code == 422 and r.json()["error"]["code"] == "workflow_invalid", r.text
        assert "R-SEG-12" in r.json()["error"]["message"]
    # presets exist but humanless ones are flagged unavailable for a regulated org
    items = c.get("/v1/workflows", headers=h).json()["items"]
    blocked = {w["name"] for w in items if not w["available"]}
    assert blocked == {"Machine only", "AI reviewed"}


def test_presets_seeded_once_and_crud(db):
    c = client()
    h = register(c)
    items = c.get("/v1/workflows", headers=h).json()["items"]
    names = [w["name"] for w in items]
    assert names == [
        "Machine only",
        "AI reviewed",
        "Hybrid (MT+QE+human for low scores)",
        "Full human review",
        "Regulated: two reviewers + client approval",
    ]
    reg = items[-1]
    assert reg["tier"] == "full" and [s["kind"] for s in reg["steps"]] == [
        "tm", "mt", "qe", "human_review", "second_review", "client_review", "delivery"
    ]  # fmt: skip
    assert {w["preset"] for w in items} == {
        "machine_only",
        "ai_reviewed",
        "hybrid",
        "full_review",
        "regulated",
    }
    assert len(c.get("/v1/workflows", headers=h).json()["items"]) == 5  # not seeded twice

    wf = workflow(c, h, "hybrid", ["tm", "mt", "qe", "senate", "human_review", "delivery"], name="Mine")
    assert c.patch(f"/v1/workflows/{wf['id']}", headers=h, json={"is_default": True}).json()["is_default"]
    r = c.patch(f"/v1/workflows/{wf['id']}", headers=h, json={"tier": "auto"})
    assert r.status_code == 422  # human_review on auto
    r = c.patch(
        f"/v1/workflows/{wf['id']}",
        headers=h,
        json={"tier": "auto", "steps": _steps("tm", "mt", "qe", "delivery")},
    )
    assert r.status_code == 200 and r.json()["tier"] == "auto"
    assert c.delete(f"/v1/workflows/{wf['id']}", headers=h).json()["archived"] is True
    assert len(c.get("/v1/workflows", headers=h).json()["items"]) == 5
    hb = register(c, "b@example.com", "Other")
    assert c.get(f"/v1/workflows/{wf['id']}", headers=hb).status_code == 404


def test_project_freezes_workflow_snapshot_and_tier_from_template(db):
    c = client()
    h = register(c)
    wf = workflow(c, h, "full", ["tm", "mt", "qe", "human_review", "delivery"], qe={"threshold": 90})
    prj = order(c, h, tier="auto", workflow_template_id=wf["id"])  # template tier wins
    assert prj["tier"] == "full" and prj["workflow_template_id"] == wf["id"]
    job = prj["jobs"][0]
    assert job["tier"] == "full"
    assert job["workflow"]["template_id"] == wf["id"] and job["workflow"]["source"] == "template"
    assert [s["kind"] for s in job["workflow"]["steps"]] == ["tm", "mt", "qe", "human_review", "delivery"]
    # editing the template later does not touch the frozen snapshot
    c.patch(
        f"/v1/workflows/{wf['id']}",
        headers=h,
        json={"steps": _steps("tm", "mt", "qe", "human_review", "client_review", "delivery")},
    )
    again = c.get(f"/v1/jobs/{job['id']}", headers=h).json()
    assert [s["kind"] for s in again["workflow"]["steps"]] == ["tm", "mt", "qe", "human_review", "delivery"]

    # no template: snapshot derived from the tier
    plain = order(c, h, tier="hybrid")["jobs"][0]
    assert plain["workflow"]["source"] == "tier" and plain["workflow"]["tier"] == "hybrid"
    # neither tier nor template: org default tier (hybrid)
    assert order(c, h)["jobs"][0]["tier"] == "hybrid"


def test_account_workflow_used_when_tier_not_given(db):
    c = client()
    h = register(c)
    wf = workflow(c, h, "full", ["tm", "mt", "qe", "human_review", "delivery"], name="Acme flow")
    acc = c.post(
        "/v1/crm/accounts", headers=h, json={"name": "Acme", "workflow_template_id": wf["id"]}
    ).json()
    prj = order(c, h, account_id=acc["id"])
    assert (
        prj["workflow_template_id"] == wf["id"] and prj["tier"] == "full" and prj["account_id"] == acc["id"]
    )
    # an explicit tier wins over the account's template
    prj2 = order(c, h, account_id=acc["id"], tier="auto")
    assert prj2["workflow_template_id"] is None and prj2["tier"] == "auto"


def test_r_seg_12_project_refuses_humanless_template_after_org_became_regulated(db):
    c = client()
    h = register(c)
    wf = workflow(c, h, "auto", ["tm", "mt", "qe", "delivery"])
    assert c.patch("/v1/org", headers=h, json={"regulated": True}).status_code == 200
    from agency_helpers import quote, upload

    f = upload(c, h)
    q = quote(c, h, f["id"])
    r = c.post(
        "/v1/projects", headers=h, json={"name": "x", "quote_id": q["id"], "workflow_template_id": wf["id"]}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "tier_not_allowed"
    r = c.post(
        "/v1/projects", headers=h, json={"name": "x", "quote_id": q["id"], "workflow_template_id": "wfl_nope"}
    )
    assert r.status_code == 404
