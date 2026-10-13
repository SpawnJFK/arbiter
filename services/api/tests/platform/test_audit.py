"""Audit log: append-only trigger, events from existing routes, filters, paging, CSV export."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest
from platform_helpers import client, invite_and_accept, register
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

_API = Path(__file__).resolve().parent.parent / "api"
if str(_API) not in sys.path:
    sys.path.append(str(_API))

from test_api_cust_helpers import order  # noqa: E402

from arbiter.models import AuditEvent  # noqa: E402
from arbiter.platform.audit import audit, to_csv  # noqa: E402


def test_audit_events_are_append_only(db):
    ev = audit(db, None, "test.event", "thing", "t1", {"x": 1}, org_id="org_x")
    db.commit()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_events SET action = 'tampered' WHERE id = :i"), {"i": ev.id})
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": ev.id})
    db.rollback()
    assert db.get(AuditEvent, ev.id).action == "test.event"


def test_secrets_are_scrubbed_and_csv_is_injection_safe(db):
    ev = audit(
        db, None, "x.y", data={"client_secret": "s3cr3t", "nested": {"api_key": "k"}, "n": 1}, org_id="o"
    )
    assert ev.data == {"client_secret": "[redacted]", "nested": {"api_key": "[redacted]"}, "n": 1}
    ev2 = audit(db, None, "x.y", target_id="=HYPERLINK(1)", org_id="o")
    db.flush()
    rows = list(csv.reader(io.StringIO(to_csv([ev2]))))
    assert rows[1][6] == "'=HYPERLINK(1)"


def test_existing_routes_write_audit_events_with_ip_and_agent(db):
    c = client()
    pm = register(c)
    hdr = {**pm, "User-Agent": "audit-test/1.0"}
    c.patch("/v1/org", headers=hdr, json={"default_tier": "full"})
    key = c.post("/v1/api-keys", headers=hdr, json={"name": "ci"}).json()
    c.delete(f"/v1/api-keys/{key['id']}", headers=hdr)
    wh = c.post(
        "/v1/webhooks", headers=hdr, json={"url": "https://hooks.example.com/x", "events": ["job.delivered"]}
    )
    assert wh.status_code == 201, wh.text
    c.delete(f"/v1/webhooks/{wh.json()['id']}", headers=hdr)
    prj = order(c, pm, tier="full")
    job_id = prj["jobs"][0]["id"]
    assert c.post(f"/v1/jobs/{job_id}/cancel", headers=pm).status_code == 200
    g = c.post("/v1/glossaries", headers=pm, json={"name": "G"}).json()
    r = c.post(
        f"/v1/glossaries/{g['id']}/import",
        headers=pm,
        files={"file": ("t.csv", b"source,target,source_lang,target_lang\ncontract,ugovor,en,sr\n")},
    )
    assert r.status_code == 200, r.text

    actions = [e.action for e in db.execute(select(AuditEvent).order_by(AuditEvent.at)).scalars()]
    for a in (
        "org.created",
        "org.updated",
        "api_key.created",
        "api_key.revoked",
        "webhook.created",
        "webhook.deleted",
        "project.created",
        "job.cancelled",
        "glossary.imported",
    ):
        assert a in actions, a
    upd = db.execute(select(AuditEvent).where(AuditEvent.action == "org.updated")).scalar_one()
    assert upd.data["changes"]["default_tier"] == {"from": "hybrid", "to": "full"}
    assert upd.user_agent == "audit-test/1.0" and upd.ip and upd.actor_label == "pm@example.com"
    created = db.execute(select(AuditEvent).where(AuditEvent.action == "api_key.created")).scalar_one()
    assert "key" not in created.data  # the secret key itself is never logged


def test_audit_list_filters_paging_export_and_permissions(db):
    c = client()
    pm = register(c)
    for i in range(3):
        c.post("/v1/api-keys", headers=pm, json={"name": f"k{i}"})
    r = c.get("/v1/audit", headers=pm, params={"action": "api_key.created", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2 and body["next_offset"] == 2
    assert (
        body["items"][0]["target"]["type"] == "api_key"
        and body["items"][0]["actor"]["label"] == "pm@example.com"
    )
    assert len(c.get("/v1/audit", headers=pm, params={"action": "api_key.*"}).json()["items"]) == 3
    assert c.get("/v1/audit", headers=pm, params={"actor": "nobody@example.com"}).json()["items"] == []
    assert c.get("/v1/audit", headers=pm, params={"until": "2000-01-01T00:00:00Z"}).json()["items"] == []

    r = c.get("/v1/audit/export", headers=pm, params={"action": "api_key.created"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "at" and len(rows) == 4
    assert c.get("/v1/audit", headers=pm, params={"action": "audit.exported"}).json()["items"]

    cl = invite_and_accept(c, pm, "client@example.com", role="client")
    assert c.get("/v1/audit", headers=cl).status_code == 403
    assert c.get("/v1/audit/export", headers=cl).status_code == 403


def test_audit_is_scoped_to_the_org(db):
    c = client()
    a = register(c, "a@example.com", "Org A")
    b = register(c, "b@example.com", "Org B")
    c.post("/v1/api-keys", headers=a, json={"name": "a-key"})
    items = c.get("/v1/audit", headers=b).json()["items"]
    assert all(e["actor"]["label"] == "b@example.com" for e in items)
    assert not any(e["action"] == "api_key.created" for e in items)
