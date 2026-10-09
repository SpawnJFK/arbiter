"""D-037: `alembic upgrade head` on an empty database must give exactly the create_all schema.

Builds two scratch databases next to the test DB, one per path, and compares tables,
columns (type, nullability), indexes, unique constraints and foreign keys.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from conftest import TEST_DB_URL
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

API_DIR = Path(__file__).resolve().parents[2]


def _admin_engine():
    return create_engine(make_url(TEST_DB_URL).set(database="postgres"), isolation_level="AUTOCOMMIT")


def _snapshot(url: str) -> dict:
    eng = create_engine(url)
    insp = inspect(eng)
    out: dict = {}
    for t in sorted(insp.get_table_names()):
        if t == "alembic_version":
            continue
        out[t] = {
            "columns": sorted((c["name"], str(c["type"]), c["nullable"]) for c in insp.get_columns(t)),
            "indexes": sorted(
                (i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes(t)
            ),
            "uniques": sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(t)),
            "fks": sorted(
                (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
                for f in insp.get_foreign_keys(t)
            ),
        }
    eng.dispose()
    return out


def test_alembic_head_equals_create_all():
    suffix = uuid.uuid4().hex[:8]
    names = {"alembic": f"arbiter_mig_a_{suffix}", "create_all": f"arbiter_mig_c_{suffix}"}
    admin = _admin_engine()
    try:
        with admin.connect() as c:
            for n in names.values():
                c.execute(text(f'CREATE DATABASE "{n}"'))
        urls = {
            k: make_url(TEST_DB_URL).set(database=v).render_as_string(hide_password=False)
            for k, v in names.items()
        }

        env = {**os.environ, "ARBITER_DATABASE_URL": urls["alembic"]}
        r = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=API_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr

        from arbiter.dbinit import create_schema

        eng = create_engine(urls["create_all"])
        with eng.begin() as conn:
            create_schema(conn)
        eng.dispose()

        a, b = _snapshot(urls["alembic"]), _snapshot(urls["create_all"])
        assert set(a) == set(b), f"table sets differ: {set(a) ^ set(b)}"
        diffs = {t: (a[t], b[t]) for t in a if a[t] != b[t]}
        assert not diffs, f"schema differs in: {sorted(diffs)}"
    finally:
        with admin.connect() as c:
            for n in names.values():
                c.execute(text(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)'))
        admin.dispose()
