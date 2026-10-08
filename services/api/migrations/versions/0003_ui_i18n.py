"""UI string localization store: ui_locales, ui_messages.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the tables are listed in dbinit.LATER_TABLES so migration 0001 leaves them out.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ui_locales",
        sa.Column("locale", sa.String(35), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ui_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "locale", sa.String(35), sa.ForeignKey("ui_locales.locale", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("locale", "key"),
    )
    op.create_index("ix_ui_messages_locale", "ui_messages", ["locale"])


def downgrade() -> None:
    op.drop_table("ui_messages")
    op.drop_table("ui_locales")
