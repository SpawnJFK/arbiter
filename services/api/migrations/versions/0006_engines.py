"""Engine credentials (encrypted), routing rules, budgets, training jobs, custom models.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the tables are listed in dbinit.LATER_TABLES so migration 0001 leaves them out.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _org_fk(nullable: bool) -> sa.Column:
    return sa.Column(
        "org_id",
        sa.String(40),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "engine_credentials",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("scope", sa.String(10), nullable=False),
        _org_fk(True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(12), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("last_tested_at", True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_error", sa.String(500), nullable=True),
    )
    op.create_index("ix_engine_credentials_org_id", "engine_credentials", ["org_id"])
    op.create_index(
        "ix_engine_credentials_scope_provider", "engine_credentials", ["scope", "org_id", "provider"]
    )

    op.create_table(
        "engine_routes",
        sa.Column("id", sa.String(40), primary_key=True),
        _org_fk(True),
        sa.Column("source_lang", sa.String(16), nullable=True),
        sa.Column("target_lang", sa.String(16), nullable=True),
        sa.Column("content_type", sa.String(60), nullable=True),
        sa.Column("purpose", sa.String(10), nullable=False),
        sa.Column("engines", sa.JSON(), nullable=False),
        sa.Column("fallback", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(300), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_engine_routes_org_id", "engine_routes", ["org_id"])

    op.create_table(
        "engine_budgets",
        sa.Column("id", sa.String(40), primary_key=True),
        _org_fk(False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("monthly_cap", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("spent", sa.Numeric(16, 6), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("org_id", "provider"),
    )
    op.create_index("ix_engine_budgets_org_id", "engine_budgets", ["org_id"])

    op.create_table(
        "training_jobs",
        sa.Column("id", sa.String(40), primary_key=True),
        _org_fk(False),
        sa.Column("source_lang", sa.String(16), nullable=False),
        sa.Column("target_lang", sa.String(16), nullable=False),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("base_model", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("dataset_stats", sa.JSON(), nullable=False),
        sa.Column("train_storage_key", sa.String(400), nullable=True),
        sa.Column("validation_storage_key", sa.String(400), nullable=True),
        sa.Column("provider_job_id", sa.String(200), nullable=True),
        sa.Column("cost", sa.Numeric(12, 5), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("result_model_id", sa.String(300), nullable=True),
        sa.Column("endpoint", sa.String(400), nullable=True),
        sa.Column("custom_model_id", sa.String(40), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("polls", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=True),
        _ts("created_at"),
        _ts("finished_at", True),
    )
    op.create_index("ix_training_jobs_org_id", "training_jobs", ["org_id"])
    op.create_index("ix_training_jobs_state", "training_jobs", ["state"])

    op.create_table(
        "custom_models",
        sa.Column("id", sa.String(40), primary_key=True),
        _org_fk(False),
        sa.Column("training_job_id", sa.String(40), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_lang", sa.String(16), nullable=False),
        sa.Column("target_lang", sa.String(16), nullable=False),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("base_model", sa.String(200), nullable=False),
        sa.Column("provider_model_id", sa.String(300), nullable=False),
        sa.Column("endpoint", sa.String(400), nullable=False),
        sa.Column("credential_id", sa.String(40), nullable=True),
        sa.Column("region", sa.String(10), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("eval_mean_qe", sa.Float(), nullable=True),
        sa.Column("eval_segments", sa.Integer(), nullable=False),
        _ts("created_at"),
        _ts("activated_at", True),
    )
    op.create_index("ix_custom_models_org_id", "custom_models", ["org_id"])


def downgrade() -> None:
    op.drop_table("custom_models")
    op.drop_table("training_jobs")
    op.drop_table("engine_budgets")
    op.drop_table("engine_routes")
    op.drop_table("engine_credentials")
