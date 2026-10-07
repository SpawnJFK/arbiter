"""Helpers for the Agency OS tests (self-contained: no imports from other test folders)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from arbiter.api import security
from arbiter.api.app import create_app
from arbiter.community import profiles, queue, review
from arbiter.models import Organization, ReviewerPair, User
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


def org_of(db, email: str = "pm@example.com") -> Organization:
    user = db.execute(select(User).where(User.email == email)).scalar_one()
    return db.get(Organization, user.org_id)


def client_user_headers(db, org_id: str, email: str = "client@example.com") -> dict:
    u = User(
        email=email,
        name="Client",
        password_hash=security.hash_password("x-123456"),
        role="client",
        org_id=org_id,
    )
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {security.issue_token(u.id, 'client', org_id)}"}


def upload(c: TestClient, h: dict, data: bytes = DOC, name: str = "notes.md", lang: str = "en") -> dict:
    r = c.post("/v1/files", headers=h, files={"file": (name, data)}, data={"source_lang": lang})
    assert r.status_code == 201, r.text
    return r.json()


def quote(c: TestClient, h: dict, file_id: str, langs: list[str] | None = None, **extra) -> dict:
    r = c.post("/v1/quotes", headers=h, json={"file_id": file_id, "target_langs": langs or ["sr"], **extra})
    assert r.status_code == 201, r.text
    return r.json()


def project(c: TestClient, h: dict, quote_id: str, **extra) -> dict:
    r = c.post("/v1/projects", headers=h, json={"name": "Launch", "quote_id": quote_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def order(c: TestClient, h: dict, data: bytes = DOC, **extra) -> dict:
    """upload -> quote -> project; extra goes to POST /projects (tier, workflow_template_id, ...)."""
    f = upload(c, h, data)
    q = quote(c, h, f["id"])
    return project(c, h, q["id"], **extra)


def workflow(c: TestClient, h: dict, tier: str, kinds: list[str], name: str = "WF", **params) -> dict:
    steps = [{"kind": k, "params": params.get(k, {})} for k in kinds]
    r = c.post("/v1/workflows", headers=h, json={"name": name, "tier": tier, "steps": steps})
    assert r.status_code == 201, r.text
    return r.json()


def drain() -> None:
    run_until_idle()


def active_reviewer(db, email: str, level: str = "senior"):
    _, prof = profiles.apply(
        db,
        name=email.split("@")[0],
        email=email,
        password="pw-123456",
        country="RS",
        pairs=[{"source_lang": "en", "target_lang": "sr"}],
        domains=["general"],
    )
    prof.status, prof.level = "active", level
    db.execute(update(ReviewerPair).where(ReviewerPair.reviewer_id == prof.id).values(status="active"))
    db.commit()
    return prof


def review_all(db, prof, decision: str = "accept") -> int:
    """The reviewer takes and accepts every task offered to them. Returns how many."""
    n = 0
    while (task := queue.next_task(db, prof)) is not None:
        review.submit(db, prof, task["id"], decision=decision, time_ms=600_000)
        db.commit()
        n += 1
    return n
