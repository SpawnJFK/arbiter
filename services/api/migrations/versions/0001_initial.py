"""Initial schema: extensions, all tables, append-only provenance trigger.

Revision ID: 0001
"""

from alembic import op

from arbiter.dbinit import create_schema, drop_schema

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_schema(op.get_bind())


def downgrade() -> None:
    drop_schema(op.get_bind())
