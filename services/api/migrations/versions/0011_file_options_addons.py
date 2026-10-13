"""File handler options and plan add-ons (D-076, D-077); seeds the starter billing catalog.

Columns: files.options, upload_sessions.options (format handler options given at upload,
used by extract, quote and merge), plans.addons (add-ons a plan includes). Then the starter
plans and credit packs are seeded (moved here from 0010 so the ORM insert sees every
column of plans); seeding never overwrites an existing row.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
files.options is listed in dbinit.LATER_COLUMNS so migration 0001 leaves it out.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("options", sa.JSON(), nullable=True))
    op.add_column("upload_sessions", sa.Column("options", sa.JSON(), nullable=True))
    op.add_column("plans", sa.Column("addons", sa.JSON(), nullable=False, server_default="[]"))
    op.alter_column("plans", "addons", server_default=None)

    # Starter catalog (editable data afterwards). Same function the CLI `seed-plans` runs.
    from sqlalchemy.orm import Session

    from arbiter.billing.catalog import seed_starter_catalog

    session = Session(bind=op.get_bind())
    seed_starter_catalog(session)
    session.flush()


def downgrade() -> None:
    op.drop_column("plans", "addons")
    op.drop_column("upload_sessions", "options")
    op.drop_column("files", "options")
