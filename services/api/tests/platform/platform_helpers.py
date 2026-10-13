"""Helpers for the platform tests (no tests here): clients, accounts, platform admin."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

_API = Path(__file__).resolve().parent.parent / "api"
if str(_API) not in sys.path:
    sys.path.append(str(_API))

from api_helpers import client, register  # noqa: E402

from arbiter.cli import create_admin  # noqa: E402

__all__ = ["admin", "bearer", "client", "login", "register"]

PW = "secret-123"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(c: TestClient, email: str, password: str = PW) -> dict[str, str]:
    r = c.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return bearer(r.json()["token"])


def admin(c: TestClient, db) -> dict[str, str]:
    create_admin(db, "ops@example.com", "admin-password-1")
    db.commit()
    return login(c, "ops@example.com", "admin-password-1")


def org_id(c: TestClient, h: dict) -> str:
    return c.get("/v1/me", headers=h).json()["org"]["id"]


def invite_and_accept(c: TestClient, pm: dict, email: str, **body) -> dict[str, str]:
    """Invite a member (dev/test returns the token), accept it, return the member's auth header."""
    r = c.post("/v1/users/invite", headers=pm, json={"email": email, **body})
    assert r.status_code == 201, r.text
    tok = r.json()["invite_token"]
    r = c.post("/v1/auth/invite/accept", json={"token": tok, "password": PW, "name": "Member"})
    assert r.status_code == 200, r.text
    return bearer(r.json()["token"])
