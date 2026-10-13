"""Helpers for software strings tests: an org + PM through the API and a string project."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from arbiter.api.app import create_app

FIX = Path(__file__).parent / "fixtures"


def client() -> TestClient:
    return TestClient(create_app())


def register(
    c: TestClient, email: str = "dev@example.com", org: str = "Fictional Apps Ltd"
) -> dict[str, str]:
    r = c.post(
        "/v1/auth/register", json={"org_name": org, "name": "Dev", "email": email, "password": "secret-123"}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def project(c: TestClient, h: dict[str, str], **over: Any) -> dict[str, Any]:
    body = {"name": "Notes app", "base_lang": "en", "target_langs": ["de", "ru"], "platforms": ["android"]}
    body.update(over)
    r = c.post("/v1/strings/projects", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def push(
    c: TestClient, h: dict[str, str], pid: str, filename: str, data: bytes, **form: Any
) -> dict[str, Any]:
    r = c.post(
        f"/v1/strings/projects/{pid}/push",
        files={"file": (filename, data)},
        data={k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in form.items()},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def keys(c: TestClient, h: dict[str, str], pid: str, **q: Any) -> dict[str, dict[str, Any]]:
    r = c.get(f"/v1/strings/projects/{pid}/keys", params={"limit": 1000, **q}, headers=h)
    assert r.status_code == 200, r.text
    return {k["name"]: k for k in r.json()["items"]}


def run_worker() -> int:
    from arbiter.pipeline.worker import run_until_idle

    return run_until_idle()
