"""Agency OS: CRM, price lists, workflow templates, dashboards, AI assistant; job workflow columns.

Hand-written (not create_all). Must produce exactly the schema the models describe:
`alembic upgrade head` on an empty database is compared with metadata.create_all (tables,
columns, types, nullability, defaults, FKs, indexes, unique constraints). Objects added here
are also listed in dbinit.LATER_TABLES / LATER_COLUMNS so migration 0001 leaves them out.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(40), primary_key=True)


def _org() -> sa.Column:
    return sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False)


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "price_lists",
        _id(),
        _org(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rates", sa.JSON(), nullable=False),
        sa.Column("tm_weights", sa.JSON(), nullable=True),
        sa.Column("minimum_charge", sa.Numeric(12, 2), nullable=True),
        _ts("archived_at", True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_price_lists_org_id", "price_lists", ["org_id"])

    op.create_table(
        "workflow_templates",
        _id(),
        _org(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(60), nullable=True),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("preset_key", sa.String(40), nullable=True),
        _ts("archived_at", True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_workflow_templates_org_id", "workflow_templates", ["org_id"])

    op.create_table(
        "crm_accounts",
        _id(),
        _org(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("industry", sa.String(80), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("vat_id", sa.String(40), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("default_tier", sa.String(20), nullable=True),
        sa.Column(
            "workflow_template_id", sa.String(40), sa.ForeignKey("workflow_templates.id"), nullable=True
        ),
        sa.Column("price_list_id", sa.String(40), sa.ForeignKey("price_lists.id"), nullable=True),
        sa.Column("owner_user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_crm_accounts_org_id", "crm_accounts", ["org_id"])
    op.create_index("ix_crm_accounts_org_name", "crm_accounts", ["org_id", "name"])

    op.create_table(
        "crm_contacts",
        _id(),
        _org(),
        sa.Column(
            "account_id", sa.String(40), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(60), nullable=True),
        sa.Column("role", sa.String(120), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_crm_contacts_org_id", "crm_contacts", ["org_id"])
    op.create_index("ix_crm_contacts_account_id", "crm_contacts", ["account_id"])

    op.create_table(
        "crm_deals",
        _id(),
        _org(),
        sa.Column(
            "account_id", sa.String(40), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("value", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("expected_close", sa.Date(), nullable=True),
        sa.Column("quote_id", sa.String(40), sa.ForeignKey("quotes.id"), nullable=True),
        sa.Column("lost_reason", sa.String(500), nullable=True),
        sa.Column("owner_user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        _ts("closed_at", True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_crm_deals_org_id", "crm_deals", ["org_id"])
    op.create_index("ix_crm_deals_account_id", "crm_deals", ["account_id"])
    op.create_index("ix_crm_deals_org_stage", "crm_deals", ["org_id", "stage"])

    op.create_table(
        "crm_activities",
        _id(),
        _org(),
        sa.Column(
            "account_id", sa.String(40), sa.ForeignKey("crm_accounts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "deal_id", sa.String(40), sa.ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        _ts("due_at", True),
        sa.Column("done", sa.Boolean(), nullable=False),
        _ts("done_at", True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_crm_activities_org_id", "crm_activities", ["org_id"])
    op.create_index("ix_crm_activities_account_id", "crm_activities", ["account_id"])
    op.create_index("ix_crm_activities_deal_id", "crm_activities", ["deal_id"])

    op.create_table(
        "dashboards",
        _id(),
        _org(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("widgets", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_dashboards_org_id", "dashboards", ["org_id"])

    op.create_table(
        "assistant_threads",
        _id(),
        _org(),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_assistant_threads_org_id", "assistant_threads", ["org_id"])

    op.create_table(
        "assistant_messages",
        _id(),
        _org(),
        sa.Column(
            "thread_id",
            sa.String(40),
            sa.ForeignKey("assistant_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("applied", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("created_by", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_assistant_messages_org_id", "assistant_messages", ["org_id"])
    op.create_index("ix_assistant_messages_thread", "assistant_messages", ["thread_id", "created_at"])

    op.add_column(
        "projects", sa.Column("account_id", sa.String(40), sa.ForeignKey("crm_accounts.id"), nullable=True)
    )
    op.add_column(
        "projects",
        sa.Column(
            "workflow_template_id", sa.String(40), sa.ForeignKey("workflow_templates.id"), nullable=True
        ),
    )
    op.create_index("ix_projects_account_id", "projects", ["account_id"])

    op.add_column(
        "jobs", sa.Column("account_id", sa.String(40), sa.ForeignKey("crm_accounts.id"), nullable=True)
    )
    op.add_column("jobs", sa.Column("workflow", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("client_approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("senate_count", sa.Integer(), server_default="0", nullable=False))
    op.create_index("ix_jobs_account_id", "jobs", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_account_id", table_name="jobs")
    for col in ("senate_count", "client_approved_at", "workflow", "account_id"):
        op.drop_column("jobs", col)
    op.drop_index("ix_projects_account_id", table_name="projects")
    for col in ("workflow_template_id", "account_id"):
        op.drop_column("projects", col)
    for table in (
        "assistant_messages",
        "assistant_threads",
        "dashboards",
        "crm_activities",
        "crm_deals",
        "crm_contacts",
        "crm_accounts",
        "workflow_templates",
        "price_lists",
    ):
        op.drop_table(table)
