"""Helpers for the customer API tests (no tests here): upload -> quote -> project, run the pipeline."""

from __future__ import annotations

from fastapi.testclient import TestClient

from arbiter.pipeline.worker import run_until_idle

DOC = (
    b"# Release notes\n\n"
    b"The **contract** must be signed before the update. Open Settings and click Save.\n\n"
    b"Arbiter supports 12 file formats. Prices start at 3.5 EUR.\n\n"
    b"Contact support@example.com for help.\n"
)


def upload(c: TestClient, h: dict, data: bytes = DOC, name: str = "notes.md", lang: str = "en") -> dict:
    r = c.post("/v1/files", headers=h, files={"file": (name, data)}, data={"source_lang": lang})
    assert r.status_code == 201, r.text
    return r.json()


def quote(c: TestClient, h: dict, file_id: str, langs: list[str] | None = None) -> dict:
    r = c.post("/v1/quotes", headers=h, json={"file_id": file_id, "target_langs": langs or ["sr"]})
    assert r.status_code == 201, r.text
    return r.json()


def project(c: TestClient, h: dict, quote_id: str, tier: str = "auto", **extra) -> dict:
    r = c.post(
        "/v1/projects", headers=h, json={"name": "Launch", "quote_id": quote_id, "tier": tier, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


def order(c: TestClient, h: dict, tier: str = "auto", langs: list[str] | None = None) -> dict:
    f = upload(c, h)
    q = quote(c, h, f["id"], langs)
    return project(c, h, q["id"], tier)


def drain() -> None:
    run_until_idle()
