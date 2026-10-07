"""Fixtures built directly with models for community tests (no pipeline, no API)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from arbiter.community import profiles
from arbiter.models import (
    FileAsset,
    Job,
    Organization,
    Project,
    ReviewerPair,
    ReviewerProfile,
    Segment,
    utcnow,
)
from arbiter.pipeline import hooks

_counter = [0]


def _n() -> int:
    _counter[0] += 1
    return _counter[0]


def make_org(db: Session, *, regulated: bool = False, settings: dict[str, Any] | None = None) -> Organization:
    n = _n()
    org = Organization(
        name=f"Demo Org {n}", slug=f"demo-org-{n}", regulated=regulated, settings=settings or {}
    )
    db.add(org)
    db.flush()
    return org


def make_job(
    db: Session,
    org: Organization,
    sources: list[str],
    *,
    source_lang: str = "en",
    target_lang: str = "sr",
    due_in_minutes: int | None = 120,
    content_type: str = "general",
) -> tuple[Job, list[Segment]]:
    n = _n()
    due = utcnow() + timedelta(minutes=due_in_minutes) if due_in_minutes is not None else None
    project = Project(
        org_id=org.id,
        name=f"Project {n}",
        source_lang=source_lang,
        target_langs=[target_lang],
        tier="hybrid",
        content_type=content_type,
        due_at=due,
    )
    db.add(project)
    db.flush()
    f = FileAsset(
        org_id=org.id,
        filename=f"demo-{n}.txt",
        format="txt",
        sha256="0" * 64,
        size=10,
        storage_key=f"{org.id}/files/demo-{n}.txt",
        source_lang=source_lang,
    )
    db.add(f)
    db.flush()
    job = Job(
        project_id=project.id,
        org_id=org.id,
        file_id=f.id,
        source_lang=source_lang,
        target_lang=target_lang,
        tier="hybrid",
        content_type=content_type,
        state="review",
        due_at=due,
        cost_reviewers=Decimal("0"),
    )
    db.add(job)
    db.flush()
    segs = []
    for i, src in enumerate(sources):
        plain = src.replace("⟦1⟧", "").replace("⟦/1⟧", "").replace("⟦2/⟧", "")
        seg = Segment(
            job_id=job.id,
            seq=i,
            unit_id=f"p{i}",
            seg_index=0,
            source_tagged=src,
            source_plain=plain,
            source_codes=[],
            target_tagged=f"[sr] {src}",
            word_count=len(plain.split()),
            state="needs_review",
            qe_score=60.0,
            signals={"terms": [{"source_term": "window", "target_term": "prozor", "kind": "mandatory"}]},
        )
        db.add(seg)
        segs.append(seg)
    job.segment_count = len(segs)
    db.flush()
    return job, segs


def make_reviewer(
    db: Session,
    *,
    email: str | None = None,
    pairs: tuple[tuple[str, str], ...] = (("en", "sr"),),
    level: str = "reviewer",
    tax: bool = True,
    threshold: str = "50",
    domains: tuple[str, ...] = (),
) -> ReviewerProfile:
    """An already-qualified reviewer (tests are covered separately in the lifecycle test)."""
    _user, profile = profiles.apply(
        db,
        name="Test Reviewer",
        email=email or f"reviewer{_n()}@example.test",
        password="correct horse battery",
        country="RS",
        pairs=list(pairs),
        domains=list(domains),
    )
    profile.level = level
    profile.status = "active"
    profile.score = 70.0
    profile.payout_threshold = Decimal(threshold)
    for p in db.query(ReviewerPair).filter_by(reviewer_id=profile.id):
        p.status = "active"
        p.score = 70.0
    if tax:
        fill_tax(db, profile)
    db.flush()
    return profile


def fill_tax(db: Session, profile: ReviewerProfile) -> None:
    profiles.update_tax_info(
        db,
        profile,
        legal_name="Test Reviewer",
        tax_id="TEST-123",
        address="1 Example Street, Example City",
        date_of_birth="1990-01-01",
        payout_method="sepa",
        payout_details={"iban": "XX00 TEST"},
    )


class HookSpy:
    def __init__(self) -> None:
        self.reviewed: list[dict[str, Any]] = []
        self.escalated: list[dict[str, Any]] = []
        self.control: list[dict[str, Any]] = []


def patch_hooks(monkeypatch: Any) -> HookSpy:
    """Replace the pipeline hooks (the orchestrator is not part of these tests)."""
    spy = HookSpy()

    def reviewed(session: Session, segment_id: str, **kw: Any) -> None:
        spy.reviewed.append({"segment_id": segment_id, **kw})

    def escalated(session: Session, segment_id: str, **kw: Any) -> None:
        spy.escalated.append({"segment_id": segment_id, **kw})

    def control(session: Session, segment_id: str, **kw: Any) -> None:
        spy.control.append({"segment_id": segment_id, **kw})

    monkeypatch.setattr(hooks, "segment_reviewed", reviewed)
    monkeypatch.setattr(hooks, "segment_escalated", escalated)
    monkeypatch.setattr(hooks, "control_sample_verdict", control)
    return spy
