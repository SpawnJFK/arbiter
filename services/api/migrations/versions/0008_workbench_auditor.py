"""Workbench (segment comments and locks, TM alignment, target concordance index) and the auditor.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the new tables, columns and indexes are listed in dbinit (LATER_TABLES, LATER_COLUMNS,
LATER_INDEXES) so migration 0001 leaves them out.

Revision ID: 0008
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("segments", sa.Column("locked_by", sa.String(40), nullable=True))
    op.add_column("segments", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_tm_trgm_target",
        "tm_entries",
        ["target_plain"],
        postgresql_using="gin",
        postgresql_ops={"target_plain": "gin_trgm_ops"},
    )

    op.create_table(
        "segment_comments",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", sa.String(40), nullable=True),
        sa.Column("thread_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("author_id", sa.String(40), nullable=False),
        sa.Column("author_role", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions", sa.JSON(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("resolved_by", sa.String(40), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_segment_comments_org_id", "segment_comments", ["org_id"])
    op.create_index("ix_comments_job_segment", "segment_comments", ["job_id", "segment_id"])
    op.create_index("ix_comments_thread", "segment_comments", ["thread_id"])

    op.create_table(
        "tm_alignments",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source_lang", sa.String(16), nullable=False),
        sa.Column("target_lang", sa.String(16), nullable=False),
        sa.Column("source_filename", sa.String(400), nullable=False),
        sa.Column("target_filename", sa.String(400), nullable=False),
        sa.Column("content_type", sa.String(60), nullable=False),
        sa.Column("pairs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("committed_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tm_alignments_org_id", "tm_alignments", ["org_id"])

    op.create_table(
        "audits",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_lang", sa.String(16), nullable=False),
        sa.Column("target_lang", sa.String(16), nullable=False),
        sa.Column("input_format", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(400), nullable=False),
        sa.Column("storage_key", sa.String(400), nullable=False),
        sa.Column("target_filename", sa.String(400), nullable=True),
        sa.Column("target_storage_key", sa.String(400), nullable=True),
        sa.Column("glossary_id", sa.String(40), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("segments_total", sa.Integer(), nullable=False),
        sa.Column("segments_done", sa.Integer(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("mqm_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.String(10), nullable=True),
        sa.Column("ai_units", sa.Numeric(12, 4), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audits_org_id", "audits", ["org_id"])
    op.create_index("ix_audits_state", "audits", ["state"])

    op.create_table(
        "audit_segments",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("audit_id", sa.String(40), sa.ForeignKey("audits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.String(200), nullable=False),
        sa.Column("source_tagged", sa.Text(), nullable=False),
        sa.Column("target_tagged", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("mqm_errors", sa.JSON(), nullable=False),
        sa.Column("ai_checked", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_severity", sa.String(10), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_audit_segments_seq", "audit_segments", ["audit_id", "seq"])


def downgrade() -> None:
    op.drop_table("audit_segments")
    op.drop_table("audits")
    op.drop_table("tm_alignments")
    op.drop_table("segment_comments")
    op.drop_index("ix_tm_trgm_target", table_name="tm_entries")
    op.drop_column("segments", "locked_at")
    op.drop_column("segments", "locked_by")
