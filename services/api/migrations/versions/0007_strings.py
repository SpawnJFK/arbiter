"""Software string localization (module `strings`): projects, branches, keys, translations,
append-only history, releases (OTA bundles) and translate batches.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the tables are listed in dbinit.LATER_TABLES so migration 0001 leaves them out.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

from arbiter.models.strings import STRING_HISTORY_TRIGGER_SQL

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "string_projects",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("public_id", sa.String(40), nullable=False, unique=True),
        sa.Column("base_lang", sa.String(16), nullable=False),
        sa.Column("target_langs", sa.JSON(), nullable=False),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("archived_at", TZ, nullable=True),
    )
    op.create_index("ix_string_projects_org_id", "string_projects", ["org_id"])

    op.create_table(
        "string_branches",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("string_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("from_branch_id", sa.String(40), nullable=True),
        sa.Column("is_main", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("merged_at", TZ, nullable=True),
        sa.Column("merged_by", sa.String(40), nullable=True),
        sa.UniqueConstraint("project_id", "name"),
    )
    op.create_index("ix_string_branches_project_id", "string_branches", ["project_id"])

    op.create_table(
        "string_keys",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("string_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.String(40),
            sa.ForeignKey("string_branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(200), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("screenshot_url", sa.String(1000), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("translatable", sa.Boolean(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("archived_at", TZ, nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        sa.UniqueConstraint("project_id", "namespace", "name"),
    )
    op.create_index("ix_string_keys_project_branch", "string_keys", ["project_id", "branch_id"])

    op.create_table(
        "string_translations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "key_id", sa.String(40), sa.ForeignKey("string_keys.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "branch_id",
            sa.String(40),
            sa.ForeignKey("string_branches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lang", sa.String(16), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("forms", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(20), nullable=True),
        sa.Column("engine", sa.String(80), nullable=True),
        sa.Column("qe_score", sa.Float(), nullable=True),
        sa.Column("qa", sa.JSON(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_task_id", sa.String(40), nullable=True),
        sa.Column("updated_by", sa.String(120), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("updated_at", TZ, nullable=False),
        sa.UniqueConstraint("key_id", "branch_id", "lang"),
    )
    op.create_index("ix_string_tr_branch_lang", "string_translations", ["branch_id", "lang"])

    op.create_table(
        "string_history",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=False),
        sa.Column("project_id", sa.String(40), nullable=False),
        sa.Column("key_id", sa.String(40), nullable=False),
        sa.Column("branch_id", sa.String(40), nullable=False),
        sa.Column("lang", sa.String(16), nullable=False),
        sa.Column("event", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("forms", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("actor_type", sa.String(10), nullable=False),
        sa.Column("actor_id", sa.String(120), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("at", TZ, nullable=False),
    )
    op.create_index("ix_string_history_org_id", "string_history", ["org_id"])
    op.create_index("ix_string_history_key", "string_history", ["key_id", "lang", "at"])
    op.execute(STRING_HISTORY_TRIGGER_SQL)

    op.create_table(
        "string_releases",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("string_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch_id", sa.String(40), nullable=False),
        sa.Column("version_label", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("langs", sa.JSON(), nullable=False),
        sa.Column("bundles", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("key_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("published_at", TZ, nullable=True),
        sa.UniqueConstraint("project_id", "version_label"),
    )
    op.create_index("ix_string_releases_project_id", "string_releases", ["project_id"])

    op.create_table(
        "string_batches",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("string_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch_id", sa.String(40), nullable=False),
        sa.Column("langs", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("review_job_id", sa.String(40), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(40), nullable=True),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("finished_at", TZ, nullable=True),
    )
    op.create_index("ix_string_batches_project_id", "string_batches", ["project_id"])


def downgrade() -> None:
    op.drop_table("string_batches")
    op.drop_table("string_releases")
    op.execute("DROP TABLE IF EXISTS string_history CASCADE")
    op.execute("DROP FUNCTION IF EXISTS string_history_append_only() CASCADE")
    op.drop_table("string_translations")
    op.drop_table("string_keys")
    op.drop_table("string_branches")
    op.drop_table("string_projects")
