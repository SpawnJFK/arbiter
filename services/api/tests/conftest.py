"""Shared fixtures.

Tests that touch the database use the `db` fixture: one schema build per test session
against ARBITER_TEST_DATABASE_URL (default: local arbiter_test), every table truncated
before each test. Tests never call a real provider: env is forced to "test" and all
provider keys are blanked.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ["ARBITER_ENV"] = "test"
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPL_API_KEY", "GOOGLE_API_KEY"):
    os.environ[f"ARBITER_{_k}"] = ""
TEST_DB_URL = os.environ.get(
    "ARBITER_TEST_DATABASE_URL", "postgresql+psycopg://arbiter:arbiter@localhost:5432/arbiter_test"
)
os.environ["ARBITER_DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("ARBITER_STORAGE_DIR", "/tmp/arbiter-test-storage")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from arbiter import db as dbmod  # noqa: E402
from arbiter.config import get_settings  # noqa: E402

get_settings.cache_clear()

_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    from arbiter.dbinit import create_schema, drop_schema

    dbmod.reset_engine(TEST_DB_URL)
    with dbmod.get_engine().begin() as conn:
        drop_schema(conn)
        create_schema(conn)
    _schema_ready = True


def _truncate() -> None:
    from arbiter.db import Base

    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with dbmod.get_engine().begin() as conn:
        # TRUNCATE does not fire row-level triggers, so the append-only guard stays intact.
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    _ensure_schema()
    _truncate()
    session = dbmod.session_factory()()
    try:
        yield session
        session.commit()
    finally:
        session.close()
