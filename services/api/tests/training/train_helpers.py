"""Fixtures for own-model tests: an org with human-approved segments (fictional content)."""

from __future__ import annotations

from arbiter.models import FileAsset, Job, Organization, Project, Segment


def org_with_segments(
    db,
    *,
    n: int = 30,
    consent: bool = True,
    source_lang: str = "en",
    target_lang: str = "sr",
    content_type: str = "general",
    slug: str = "acme",
    region: str | None = None,
    org: Organization | None = None,
) -> Organization:
    if org is None:
        settings = {"training_consent": consent}
        if region:
            settings["processing_region"] = region
        org = Organization(name=slug, slug=slug, settings=settings)
        db.add(org)
        db.flush()
    fa = FileAsset(
        org_id=org.id,
        filename="a.md",
        format="md",
        sha256="0" * 64,
        size=1,
        storage_key="k",
        source_lang="en",
    )
    db.add(fa)
    db.flush()
    prj = Project(org_id=org.id, name="P", source_lang=source_lang, target_langs=[target_lang], tier="full")
    db.add(prj)
    db.flush()
    job = Job(
        project_id=prj.id,
        org_id=org.id,
        file_id=fa.id,
        source_lang=source_lang,
        target_lang=target_lang,
        tier="full",
        content_type=content_type,
        state="delivered",
    )
    db.add(job)
    db.flush()
    for i in range(n):
        db.add(
            Segment(
                job_id=job.id,
                seq=i,
                unit_id=f"u{i}",
                seg_index=0,
                source_tagged=f"Open ⟦1⟧item {i}⟦/1⟧ now",
                source_plain=f"Open item {i} now",
                target_tagged=f"Otvori ⟦1⟧stavku {i}⟦/1⟧ sada",
                state="delivered",
                decision="reviewed",
                origin="human",
            )
        )
    # never in a dataset: auto-approved, not yet reviewed, empty
    db.add(
        Segment(
            job_id=job.id,
            seq=n,
            unit_id="auto",
            seg_index=0,
            source_tagged="Auto approved",
            source_plain="Auto approved",
            target_tagged="Auto",
            state="delivered",
            decision="auto_approve",
        )
    )
    db.add(
        Segment(
            job_id=job.id,
            seq=n + 1,
            unit_id="open",
            seg_index=0,
            source_tagged="Waiting",
            source_plain="Waiting",
            target_tagged="Ceka",
            state="needs_review",
            decision="review",
        )
    )
    # a duplicate source: only one example survives
    db.add(
        Segment(
            job_id=job.id,
            seq=n + 2,
            unit_id="dup",
            seg_index=0,
            source_tagged="Open ⟦1⟧item 0⟦/1⟧ now",
            source_plain="Open item 0 now",
            target_tagged="Otvori ⟦1⟧stavku 0⟦/1⟧ odmah",
            state="reviewed",
            decision="reviewed",
        )
    )
    db.flush()
    return org
