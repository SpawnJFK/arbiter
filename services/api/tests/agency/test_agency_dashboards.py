"""Dashboards: CRUD, widget validation, default dashboard, every metric on an org with data."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from agency_helpers import client, client_user_headers, drain, org_of, project, quote, register, upload

from arbiter.agency.dashboards import METRICS
from arbiter.models import utcnow


def _all_widgets():
    out = []
    for wtype, metrics in METRICS.items():
        for m in metrics:
            out.append({"type": wtype, "metric": m})
    return out


def _seed(c, h):
    """Two delivered jobs for an account, one overdue full-tier job, deals and activities."""
    acc = c.post("/v1/crm/accounts", headers=h, json={"name": "Acme"}).json()
    for _ in range(2):
        f = upload(c, h)
        q = quote(c, h, f["id"], account_id=acc["id"])
        project(c, h, q["id"], tier="auto")
    f = upload(c, h)
    q = quote(c, h, f["id"])
    due = (utcnow() - timedelta(hours=3)).isoformat()
    late = project(c, h, q["id"], tier="full", due_at=due)
    drain()
    c.post(
        "/v1/crm/deals",
        headers=h,
        json={"account_id": acc["id"], "title": "A", "value": "1000", "stage": "proposal"},
    )
    c.post("/v1/crm/deals", headers=h, json={"account_id": acc["id"], "title": "B", "value": "250.50"})
    c.post(
        "/v1/crm/deals",
        headers=h,
        json={"account_id": acc["id"], "title": "C", "value": "99", "stage": "won"},
    )
    c.post(
        "/v1/crm/activities",
        headers=h,
        json={"account_id": acc["id"], "kind": "task", "body": "Send invoice"},
    )
    return acc, late["jobs"][0]["id"]


def test_widget_validation_crud_and_default(db):
    c = client()
    h = register(c)
    r = c.post(
        "/v1/dashboards",
        headers=h,
        json={"name": "Bad", "widgets": [{"type": "kpi", "metric": "revenue_by_month"}]},
    )
    assert r.status_code == 422
    r = c.post(
        "/v1/dashboards", headers=h, json={"name": "Bad", "widgets": [{"type": "pie", "metric": "revenue"}]}
    )
    assert r.status_code == 422
    r = c.post(
        "/v1/dashboards",
        headers=h,
        json={
            "name": "Mine",
            "widgets": [
                {"type": "kpi", "metric": "revenue", "size": "s"},
                {"id": "w1", "type": "table", "metric": "overdue_jobs"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert [w["id"] for w in d["widgets"]] == ["w1", "w1_2"] and d["widgets"][0]["title"] == "Revenue"
    assert d["is_default"] is False
    d2 = c.patch(f"/v1/dashboards/{d['id']}", headers=h, json={"name": "Renamed", "widgets": []}).json()
    assert d2["name"] == "Renamed" and d2["widgets"] == []
    default = c.get("/v1/dashboards/default", headers=h).json()
    assert default["is_default"] and default["name"] == "Overview" and len(default["widgets"]) >= 8
    assert c.get("/v1/dashboards/default", headers=h).json()["id"] == default["id"]
    assert [x["id"] for x in c.get("/v1/dashboards", headers=h).json()["items"]] == [default["id"], d["id"]]
    assert c.delete(f"/v1/dashboards/{d['id']}", headers=h).json()["id"] == d["id"]
    assert c.get(f"/v1/dashboards/{d['id']}", headers=h).status_code == 404
    hb = register(c, "b@example.com", "Other")
    assert c.get(f"/v1/dashboards/{default['id']}/data", headers=hb).status_code == 404
    assert c.get(f"/v1/dashboards/{default['id']}/data?period=7d", headers=h).status_code == 422


def test_every_metric_returns_well_formed_data(db):
    c = client()
    h = register(c)
    acc, late_job = _seed(c, h)
    d = c.post("/v1/dashboards", headers=h, json={"name": "All", "widgets": _all_widgets()}).json()
    for period in ("30d", "90d", "365d"):
        r = c.get(f"/v1/dashboards/{d['id']}/data?period={period}", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["period"] == period and len(body["widgets"]) == len(_all_widgets())
        by = {(w["type"], d["widgets"][i]["metric"]): w for i, w in enumerate(body["widgets"])}
        for (wtype, metric), w in by.items():
            data = w["data"]
            assert w["title"], metric
            if wtype == "kpi":
                assert set(data) >= {"value", "unit", "previous"}, metric
            elif wtype in ("bar", "line"):
                assert isinstance(data["points"], list) and "unit" in data, metric
                assert all({"label", "value"} <= set(p) for p in data["points"]), metric
            elif wtype == "pipeline":
                assert [s["stage"] for s in data["stages"]] == [
                    "lead",
                    "qualified",
                    "proposal",
                    "negotiation",
                    "won",
                    "lost",
                ]
            else:
                assert isinstance(data["columns"], list) and isinstance(data["rows"], list), metric
    data = c.get(f"/v1/dashboards/{d['id']}/data?period=30d", headers=h).json()
    by = {
        (d["widgets"][i]["type"], d["widgets"][i]["metric"]): w["data"] for i, w in enumerate(data["widgets"])
    }
    jobs = c.get("/v1/jobs", headers=h).json()["items"]
    delivered = [j for j in jobs if j["state"] == "delivered"]
    assert len(delivered) == 2
    revenue = sum(Decimal(j["revenue"]) for j in delivered)
    assert by[("kpi", "revenue")]["value"] == str(revenue.quantize(Decimal("0.01"))) and revenue > 0
    assert by[("kpi", "revenue")]["unit"] == "EUR"
    cost = sum(Decimal(j["cost"]) for j in delivered)
    assert Decimal(by[("kpi", "margin")]["value"]) == (revenue - cost).quantize(Decimal("0.01"))
    assert by[("kpi", "margin_pct")]["value"] is not None
    assert by[("kpi", "jobs_active")]["value"] == 1
    assert by[("kpi", "jobs_overdue")]["value"] == 1
    assert by[("kpi", "words_delivered")]["value"] == sum(j["word_count"] for j in delivered)
    assert 0 <= by[("kpi", "auto_rate")]["value"] <= 1
    assert by[("kpi", "escaped_rate")]["value"] == 0
    assert (
        by[("kpi", "open_deals_value")]["value"] == "1250.50"
        and by[("kpi", "open_deals_value")]["count"] == 2
    )
    assert by[("kpi", "reviewer_cost")]["value"] == "0.00"
    assert [r["job_id"] for r in by[("table", "overdue_jobs")]["rows"]] == [late_job]
    assert by[("table", "overdue_jobs")]["rows"][0]["hours_overdue"] >= 2.9
    assert by[("table", "top_accounts")]["rows"][0]["name"] == "Acme"
    assert by[("table", "top_accounts")]["rows"][0]["jobs"] == 2
    assert len(by[("table", "recent_deliveries")]["rows"]) == 2
    assert [r["body"] for r in by[("table", "open_activities")]["rows"]] == ["Send invoice"]
    stages = {s["stage"]: s for s in by[("pipeline", "deals_by_stage")]["stages"]}
    assert stages["proposal"] == {"stage": "proposal", "count": 1, "value": "1000.00"}
    assert stages["won"]["count"] == 1
    month = utcnow().strftime("%Y-%m")
    rev_points = {p["label"]: p["value"] for p in by[("line", "revenue_by_month")]["points"]}
    assert rev_points[month] == str(revenue.quantize(Decimal("0.01")))
    assert {p["label"] for p in by[("bar", "jobs_by_state")]["points"]} == {"delivered", "review"}
    assert by[("bar", "revenue_by_account")]["points"][0]["label"] == "Acme"
    assert by[("bar", "words_by_pair")]["points"][0]["label"] == "en-sr"
    assert by[("line", "auto_rate_by_month")]["points"][-1]["label"] == month


def test_client_role_reads_dashboards_without_money(db):
    c = client()
    h = register(c)
    _seed(c, h)
    hc = client_user_headers(db, org_of(db).id)
    d = c.get("/v1/dashboards/default", headers=hc).json()
    data = c.get(f"/v1/dashboards/{d['id']}/data", headers=hc).json()
    kpis = {w["title"]: w["data"] for w in data["widgets"] if w["type"] == "kpi"}
    assert kpis["Revenue"]["value"] is None and kpis["Active jobs"]["value"] == 1
    # but the client role cannot change dashboards or use the assistant / CRM
    assert c.post("/v1/dashboards", headers=hc, json={"name": "x", "widgets": []}).status_code == 403
    assert c.get("/v1/crm/accounts", headers=hc).status_code == 403
    assert c.post("/v1/assistant/threads", headers=hc, json={}).status_code == 403
