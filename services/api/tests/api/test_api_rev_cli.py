"""Operator CLI: create-admin, seed-demo (idempotent), calibrate."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from api_helpers import client
from sqlalchemy import func, select

_TESTS = Path(__file__).resolve().parent.parent
if str(_TESTS / "community") not in sys.path:
    sys.path.append(str(_TESTS / "community"))

import comm_helpers  # noqa: E402

from arbiter import cli  # noqa: E402
from arbiter.models import (  # noqa: E402
    ControlSample,
    Glossary,
    Organization,
    ReviewerPair,
    ReviewerProfile,
    ReviewerTest,
    Term,
    Threshold,
    User,
    utcnow,
)


def _counts(db) -> dict[str, int]:
    return {
        m.__name__: db.execute(select(func.count()).select_from(m)).scalar_one()
        for m in (Organization, User, ReviewerProfile, ReviewerPair, ReviewerTest, Glossary, Term)
    }


def test_seed_demo_is_idempotent_and_logins_work(db, monkeypatch):
    first = cli.seed_demo(db)
    db.commit()
    before = _counts(db)
    assert before["Organization"] == 1 and before["User"] == 5
    assert before["ReviewerTest"] == 4 and before["Term"] == len(cli.DEMO_TERMS)

    second = cli.seed_demo(db)
    db.commit()
    assert second["created"] == [] and second["org_id"] == first["org_id"]
    assert _counts(db) == before

    org = db.get(Organization, first["org_id"])
    assert org.name == "Demo Co"
    kinds = {t.kind for t in db.execute(select(Term)).scalars()}
    assert kinds == {"mandatory", "forbidden", "do_not_translate"}
    profile = db.get(ReviewerProfile, first["reviewer_id"])
    assert profile.status == "active"
    pairs = db.execute(select(ReviewerPair).where(ReviewerPair.reviewer_id == profile.id)).scalars().all()
    assert {(p.source_lang, p.target_lang, p.status) for p in pairs} == {
        ("en", "sr", "active"),
        ("en", "de", "active"),
    }

    # Login accepts the reserved .test domain the demo accounts use.
    c = client()
    for email, role in (
        ("pm@demo.test", "pm"),
        ("client@demo.test", "client"),
        ("reviewer@demo.test", "reviewer"),
        ("admin@demo.test", "admin"),
    ):
        r = c.post("/v1/auth/login", json={"email": email, "password": cli.DEMO_PASSWORD})
        assert r.status_code == 200, (email, r.text)
        assert r.json()["user"]["role"] == role
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert c.get("/v1/admin/reviewers?status=active", headers=h).json()["items"][0]["email"] == (
        "reviewer@demo.test"
    )


def test_create_admin(db):
    user, created = cli.create_admin(db, "Root@Example.test", "admin-password-1")
    assert created and user.role == "admin" and user.org_id is None and user.email == "root@example.test"
    _, created = cli.create_admin(db, "root@example.test", "another-password")
    assert created is False
    comm_helpers.make_reviewer(db, email="rev@example.test")
    with pytest.raises(ValueError):
        cli.create_admin(db, "rev@example.test", "admin-password-1")
    with pytest.raises(ValueError):
        cli.create_admin(db, "x@example.test", "short")


def test_calibrate_moves_threshold_within_step_and_logs_reason(db):
    org = comm_helpers.make_org(db)
    job, segs = comm_helpers.make_job(db, org, ["One control sentence."])
    thr = Threshold(org_id=org.id, content_type="general", target_lang="sr", value=78.0)
    other = Threshold(org_id=org.id, content_type="marketing", target_lang="sr", value=80.0)
    db.add_all([thr, other])
    now = utcnow()
    # 240 samples, scores 60..99.x; every escaped error scores below 70 -> ideal 70.
    for i in range(240):
        score = 60.0 + i / 6
        db.add(
            ControlSample(
                segment_id=segs[0].id,
                job_id=job.id,
                org_id=org.id,
                qe_score=score,
                verdict="escaped" if score < 70 else "ok",
                decided_at=now - timedelta(days=1),
            )
        )
    db.flush()

    dry = cli.calibrate(db, now=now, dry_run=True)
    assert {r["threshold_id"]: r["applied"] for r in dry} == {thr.id: False, other.id: False}
    assert thr.value == 78.0

    rows = {r["threshold_id"]: r for r in cli.calibrate(db, now=now)}
    assert rows[thr.id]["applied"] is True and rows[thr.id]["samples"] == 240
    assert thr.value == 75.0  # ideal 70, step capped at 3 per week
    assert "step capped" in rows[thr.id]["reason"]
    assert rows[other.id]["applied"] is False and rows[other.id]["reason"].startswith("skipped: 0 samples")
    log = db.get(Organization, org.id).settings["calibration_log"]
    assert log[-1]["threshold_id"] == thr.id and log[-1]["old"] == 78.0 and log[-1]["new"] == 75.0

    # Same week: no second step.
    again = {r["threshold_id"]: r for r in cli.calibrate(db, now=now + timedelta(days=2))}
    assert again[thr.id]["applied"] is False and thr.value == 75.0
    cli._print_table(list(rows.values()))
