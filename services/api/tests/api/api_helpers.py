"""API test helpers: a TestClient bound to the test DB and quick account creation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from arbiter.api.app import create_app


def client() -> TestClient:
    return TestClient(create_app())


def register(c: TestClient, email: str = "pm@example.com", org: str = "Acme GmbH") -> dict:
    r = c.post(
        "/v1/auth/register", json={"org_name": org, "name": "PM", "email": email, "password": "secret-123"}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
