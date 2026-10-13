"""Helpers for the workbench and TM tools tests (self-contained: no imports from other test folders)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from arbiter.api import security
from arbiter.api.app import create_app
from arbiter.models import User
from arbiter.pipeline.worker import run_until_idle

DOC = (
    b"# Release notes\n\n"
    b"The **contract** must be signed before the update. Open Settings and click Save.\n\n"
    b"Arbiter supports 12 file formats. Prices start at 3.5 EUR.\n\n"
    b"Contact support@example.com for help.\n"
)


def client() -> TestClient:
    return TestClient(create_app())


def register(c: TestClient, email: str = "pm@example.com", org: str = "Acme GmbH") -> dict:
    r = c.post(
        "/v1/auth/register", json={"org_name": org, "name": "PM", "email": email, "password": "secret-123"}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def client_user(db, c: TestClient, h: dict, email: str = "client@example.com") -> dict:
    """A client-role user in the PM's org, returned as auth headers."""
    org_id = c.get("/v1/me", headers=h).json()["user"]["org_id"]
    u = User(email=email, name="Client", password_hash="x", role="client", org_id=org_id)
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {security.issue_token(u.id, 'client', org_id)}"}


def order(
    c: TestClient, h: dict, tier: str = "full", data: bytes = DOC, name: str = "notes.md", langs=("sr",)
) -> dict:
    r = c.post("/v1/files", headers=h, files={"file": (name, data)}, data={"source_lang": "en"})
    assert r.status_code == 201, r.text
    f = r.json()
    r = c.post("/v1/quotes", headers=h, json={"file_id": f["id"], "target_langs": list(langs)})
    assert r.status_code == 201, r.text
    r = c.post("/v1/projects", headers=h, json={"name": "Launch", "quote_id": r.json()["id"], "tier": tier})
    assert r.status_code == 201, r.text
    run_until_idle()
    job_id = r.json()["jobs"][0]["id"]
    return c.get(f"/v1/jobs/{job_id}", headers=h).json()


def segments(c: TestClient, h: dict, job_id: str, **params) -> list[dict]:
    r = c.get(f"/v1/jobs/{job_id}/editor/segments", headers=h, params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def drain() -> None:
    run_until_idle()
