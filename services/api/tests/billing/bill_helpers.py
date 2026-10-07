"""Fixtures for billing tests, built directly with models and local storage."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from arbiter import storage
from arbiter.models import FileAsset, Organization

_counter = [0]

SAMPLE_TEXT = (
    "Save your changes before closing the window.\n\n"
    "Click Next to continue with the installation.\n\n"
    "Save your changes before closing the window.\n\n"
    "The report is generated every Monday morning.\n"
)


def make_org(db: Session, *, regulated: bool = False, settings: dict[str, Any] | None = None) -> Organization:
    _counter[0] += 1
    n = _counter[0]
    org = Organization(
        name=f"Bill Org {n}", slug=f"bill-org-{n}", regulated=regulated, settings=settings or {}
    )
    db.add(org)
    db.flush()
    return org


def make_file(
    db: Session, org: Organization, text: str = SAMPLE_TEXT, filename: str = "sample.txt"
) -> FileAsset:
    data = text.encode()
    f = FileAsset(
        org_id=org.id,
        filename=filename,
        format="txt",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        storage_key="pending",
        source_lang="en",
    )
    db.add(f)
    db.flush()
    f.storage_key = storage.make_key(org.id, "files", f.id, filename)
    storage.put(f.storage_key, data)
    db.flush()
    return f
