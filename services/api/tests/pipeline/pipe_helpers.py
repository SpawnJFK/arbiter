from __future__ import annotations

import hashlib
from datetime import timedelta

from arbiter import storage
from arbiter.models import FileAsset, Job, Organization, Project, utcnow

DOC = (
    b"# Release notes\n\n"
    b"The **contract** must be signed before the update. Open Settings and click Save.\n\n"
    b"Arbiter supports 12 file formats. Prices start at 3.5 EUR.\n\n"
    b"Contact support@example.com for help.\n"
)


def make_job(
    db, *, tier="auto", regulated=False, policy="wait", data=DOC, filename="notes.md", due_hours=None
):
    org = Organization(
        name="Acme", slug=f"acme-{tier}-{policy}", regulated=regulated, no_reviewer_policy=policy
    )
    db.add(org)
    db.flush()
    fa = FileAsset(
        org_id=org.id,
        filename=filename,
        format=filename.rsplit(".", 1)[-1],
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        storage_key="",
        source_lang="en",
    )
    db.add(fa)
    db.flush()
    fa.storage_key = storage.make_key(org.id, "source", fa.id, filename)
    storage.put(fa.storage_key, data)
    prj = Project(org_id=org.id, name="P", source_lang="en", target_langs=["sr"], tier=tier)
    db.add(prj)
    db.flush()
    job = Job(
        project_id=prj.id,
        org_id=org.id,
        file_id=fa.id,
        source_lang="en",
        target_lang="sr",
        tier=tier,
        state="quoted",
        due_at=(utcnow() + timedelta(hours=due_hours)) if due_hours else None,
    )
    db.add(job)
    db.flush()
    return org, job
