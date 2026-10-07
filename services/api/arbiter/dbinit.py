"""Database bootstrap: extensions, tables, triggers.

Two callers, one final schema:
  * the test suite (and `create_schema()` in general) builds the CURRENT schema from the
    models with metadata.create_all;
  * Alembic builds it step by step: migration 0001 calls `create_schema(conn, revision="0001")`,
    which leaves out every object a later, hand-written migration adds (LATER_TABLES and
    LATER_COLUMNS below), so `alembic upgrade head` on an empty database runs 0002+ for real
    and ends with the same schema as create_all.
When a new migration adds tables or columns, list them here too.
"""

from __future__ import annotations

from sqlalchemy import Connection, MetaData, Table, text

import arbiter.models  # noqa: F401  (registers every table on Base.metadata)
from arbiter.db import Base
from arbiter.models.provenance import APPEND_ONLY_TRIGGER_SQL

EXTENSIONS_SQL = ("CREATE EXTENSION IF NOT EXISTS vector", "CREATE EXTENSION IF NOT EXISTS pg_trgm")

# Objects added by migration 0002_agency_os (not part of the 0001 schema).
LATER_TABLES: frozenset[str] = frozenset(
    {
        "price_lists",
        "workflow_templates",
        "crm_accounts",
        "crm_contacts",
        "crm_deals",
        "crm_activities",
        "dashboards",
        "assistant_threads",
        "assistant_messages",
    }
)
LATER_COLUMNS: dict[str, frozenset[str]] = {
    "projects": frozenset({"account_id", "workflow_template_id"}),
    "jobs": frozenset({"account_id", "workflow", "client_approved_at", "senate_count"}),
}


def _without(table: Table, meta: MetaData, drop: frozenset[str]) -> Table:
    """Copy of `table` into `meta` minus the columns in `drop` (and their FKs and indexes)."""
    t = table.to_metadata(meta)
    for name in drop:
        col = t.c[name]
        for fk in list(col.foreign_keys):
            t.foreign_keys.discard(fk)
            t.constraints.discard(fk.constraint)
        for ix in list(t.indexes):
            if name in ix.columns:
                t.indexes.discard(ix)
        t._columns.remove(col)  # noqa: SLF001  (no public API to drop a column from a Table)
    return t


def metadata_0001() -> MetaData:
    """The schema as migration 0001 created it."""
    meta = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name in LATER_TABLES:
            continue
        _without(table, meta, LATER_COLUMNS.get(table.name, frozenset()))
    return meta


def create_schema(conn: Connection, revision: str | None = None) -> None:
    for stmt in EXTENSIONS_SQL:
        conn.execute(text(stmt))
    meta = metadata_0001() if revision == "0001" else Base.metadata
    meta.create_all(conn)
    conn.execute(text(APPEND_ONLY_TRIGGER_SQL))


def drop_schema(conn: Connection) -> None:
    Base.metadata.drop_all(conn)
    conn.execute(text("DROP FUNCTION IF EXISTS provenance_append_only() CASCADE"))
