"""Initial schema: extensions, all tables of the 0001 schema, append-only provenance trigger.

Builds the schema as it was at 0001 (dbinit.metadata_0001: the current models minus what
later migrations add), so later hand-written migrations run for real on a fresh database.

Revision ID: 0001
"""

from alembic import op

from arbiter.dbinit import create_schema, drop_schema

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_schema(op.get_bind(), revision="0001")


def downgrade() -> None:
    drop_schema(op.get_bind())
