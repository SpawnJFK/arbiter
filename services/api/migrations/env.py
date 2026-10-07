"""Alembic environment. The URL always comes from ARBITER_DATABASE_URL (never from alembic.ini)."""

from alembic import context
from sqlalchemy import create_engine

import arbiter.models  # noqa: F401
from arbiter.config import get_settings
from arbiter.db import Base

target_metadata = Base.metadata


def run() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run()
