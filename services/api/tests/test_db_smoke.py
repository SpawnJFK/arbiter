import pytest
from sqlalchemy import text

from arbiter.models import Organization, ProvenanceEvent


def test_schema_and_append_only(db):
    org = Organization(name="Acme", slug="acme")
    db.add(org)
    db.flush()
    db.add(ProvenanceEvent(job_id="job_x", org_id=org.id, event="created", actor_type="system"))
    db.commit()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE provenance_events SET event='x'"))
    db.rollback()
