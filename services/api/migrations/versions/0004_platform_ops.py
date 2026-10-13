"""Platform operations: upload_sessions (direct uploads), email_messages, account_tokens.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the tables are listed in dbinit.LATER_TABLES so migration 0001 leaves them out.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_by", sa.String(60), nullable=False),
        sa.Column("filename", sa.String(400), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=False),
        sa.Column("source_lang", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(400), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("file_id", sa.String(40), sa.ForeignKey("files.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_upload_sessions_org_id", "upload_sessions", ["org_id"])

    op.create_table(
        "email_messages",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("to_address", sa.String(320), nullable=False),
        sa.Column("template", sa.String(60), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("provider_id", sa.String(200), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_email_messages_org_id", "email_messages", ["org_id"])
    op.create_index("ix_email_messages_to", "email_messages", ["to_address", "created_at"])

    op.create_table(
        "account_tokens",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("account_tokens")
    op.drop_table("email_messages")
    op.drop_table("upload_sessions")
