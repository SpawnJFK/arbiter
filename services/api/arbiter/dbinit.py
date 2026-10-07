"""Database bootstrap: extensions, tables, triggers.

Used by the initial Alembic migration and by the test suite, so both build the exact
same schema.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

import arbiter.models  # noqa: F401  (registers every table on Base.metadata)
from arbiter.db import Base
from arbiter.models.provenance import APPEND_ONLY_TRIGGER_SQL

EXTENSIONS_SQL = ("CREATE EXTENSION IF NOT EXISTS vector", "CREATE EXTENSION IF NOT EXISTS pg_trgm")


def create_schema(conn: Connection) -> None:
    for stmt in EXTENSIONS_SQL:
        conn.execute(text(stmt))
    Base.metadata.create_all(conn)
    conn.execute(text(APPEND_ONLY_TRIGGER_SQL))


def drop_schema(conn: Connection) -> None:
    Base.metadata.drop_all(conn)
    conn.execute(text("DROP FUNCTION IF EXISTS provenance_append_only() CASCADE"))
