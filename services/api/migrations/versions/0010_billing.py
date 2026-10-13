"""Subscription billing, credit wallet, provider events, payout rails (D-072, D-073, D-074).

Tables: plans, credit_packs, subscriptions, billing_customers, credit_ledger, billing_events,
payout_accounts, payout_batches. Columns on invoices: kind, provider, provider_ref,
provider_invoice_number, provider_url, due_at, paid_at. The starter plans and credit packs
are seeded by 0011.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the tables and columns are listed in dbinit.LATER_TABLES / LATER_COLUMNS.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("key", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("modules", sa.JSON(), nullable=False),
        sa.Column("prices", sa.JSON(), nullable=False),
        sa.Column("seat_prices", sa.JSON(), nullable=False),
        sa.Column("included", sa.JSON(), nullable=False),
        sa.Column("overage", sa.JSON(), nullable=False),
        sa.Column("seats_included", sa.Integer(), nullable=False),
        sa.Column("max_seats", sa.Integer(), nullable=True),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("custom", sa.Boolean(), nullable=False),
        sa.Column("public", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("provider_prices", sa.JSON(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "credit_packs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("key", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("credit_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("valid_days", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        _ts("created_at"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_key", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_subscription_id", sa.String(120), nullable=True, unique=True),
        sa.Column("provider_customer_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        _ts("current_period_start", True),
        _ts("current_period_end", True),
        _ts("cancel_at", True),
        _ts("canceled_at", True),
        sa.Column("meta", sa.JSON(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_subscriptions_org_id", "subscriptions", ["org_id"])
    op.create_table(
        "billing_customers",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_customer_id", sa.String(120), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("org_id", "provider"),
        sa.UniqueConstraint("provider", "provider_customer_id"),
    )
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 5), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("lot_id", sa.String(40), nullable=True),
        _ts("expires_at", True),
        sa.Column("txn_id", sa.String(40), nullable=False),
        sa.Column("ref", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        _ts("created_at"),
    )
    op.create_index("ix_credit_ledger_org", "credit_ledger", ["org_id", "created_at"])
    op.create_index("ix_credit_ledger_lot_id", "credit_ledger", ["lot_id"])
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
        _ts("received_at"),
        _ts("processed_at", True),
        sa.UniqueConstraint("provider", "event_id"),
    )
    op.create_table(
        "payout_accounts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("payee_kind", sa.String(20), nullable=False),
        sa.Column("payee_id", sa.String(40), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("provider_payee_id", sa.String(120), nullable=True),
        sa.Column("onboarding_url", sa.String(1000), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("payee_kind", "payee_id", "method"),
    )
    op.create_index("ix_payout_accounts_payee_id", "payout_accounts", ["payee_id"])
    op.create_table(
        "payout_batches",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("payout_ids", sa.JSON(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        _ts("created_at"),
    )

    # invoices: provider references (MoR documents) and the invoice kind.
    op.add_column(
        "invoices", sa.Column("kind", sa.String(20), nullable=False, server_default=sa.text("'usage'"))
    )
    op.add_column(
        "invoices",
        sa.Column("provider", sa.String(20), nullable=False, server_default=sa.text("'internal'")),
    )
    op.alter_column("invoices", "kind", server_default=None)
    op.alter_column("invoices", "provider", server_default=None)
    op.add_column("invoices", sa.Column("provider_ref", sa.String(120), nullable=True))
    op.add_column("invoices", sa.Column("provider_invoice_number", sa.String(120), nullable=True))
    op.add_column("invoices", sa.Column("provider_url", sa.String(1000), nullable=True))
    op.add_column("invoices", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_invoices_provider_ref", "invoices", ["provider_ref"])
    # The starter catalog is seeded by 0011, after plans.addons exists: the seed goes through
    # the ORM model, which always has the newest columns.


def downgrade() -> None:
    op.drop_index("ix_invoices_provider_ref", table_name="invoices")
    for col in (
        "paid_at",
        "due_at",
        "provider_url",
        "provider_invoice_number",
        "provider_ref",
        "provider",
        "kind",
    ):
        op.drop_column("invoices", col)
    for table in (
        "payout_batches",
        "payout_accounts",
        "billing_events",
        "credit_ledger",
        "billing_customers",
        "subscriptions",
        "credit_packs",
        "plans",
    ):
        op.drop_table(table)
