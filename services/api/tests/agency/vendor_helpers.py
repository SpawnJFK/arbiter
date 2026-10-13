"""Helpers for the vendor management tests (module pm)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def vendor(
    c: TestClient,
    h: dict,
    name: str,
    *,
    email: str | None = None,
    rate: str = "0.05",
    pair: tuple[str, str] = ("en", "sr"),
    capacity: int = 3000,
    **extra,
) -> dict:
    body = {
        "name": name,
        "email": email or f"{name.lower().replace(' ', '.')}@vendors.example",
        "pairs": [{"source_lang": pair[0], "target_lang": pair[1], "services": ["translation", "review"]}],
        "rates": [
            {"service": "review", "unit": "word", "rate": rate},
            {"service": "translation", "unit": "word", "rate": str(float(rate) * 2)},
            {"service": "review", "unit": "minimum", "rate": "1.00"},
        ],
        "capacity_words_per_day": capacity,
        "working_days": [0, 1, 2, 3, 4, 5, 6],
        **extra,
    }
    r = c.post("/v1/vendors", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def token_of(link: str) -> str:
    return link.rsplit("/vendor/", 1)[1]


def assign(c: TestClient, h: dict, job_id: str, **body) -> dict:
    r = c.post(f"/v1/jobs/{job_id}/assignments", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def due_in(hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def work_all(c: TestClient, token: str, decision: str = "accept") -> int:
    """The vendor accepts every open segment in the workbench. Returns how many."""
    view = c.get(f"/v1/vendor-portal/{token}").json()
    n = 0
    for s in view["segments"]:
        if s["done"]:
            continue
        r = c.post(f"/v1/vendor-portal/{token}/segments/{s['id']}", json={"decision": decision})
        assert r.status_code == 200, r.text
        n += 1
    return n
