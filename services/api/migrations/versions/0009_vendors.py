"""Agency vendors (module pm): vendors, absences, documents, assignments, number series,
purchase orders, vendor invoices; jobs.cost_vendors.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the tables are listed in dbinit.LATER_TABLES and the column in dbinit.LATER_COLUMNS so
migration 0001 leaves them out.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _org() -> sa.Column:
    return sa.Column("org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False)


def upgrade() -> None:
    op.add_column("jobs", sa.Column("cost_vendors", sa.Numeric(12, 5), nullable=False, server_default="0"))
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(60), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("pairs", sa.JSON(), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column("rates", sa.JSON(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=True),
        sa.Column("tax_id", sa.String(64), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("payment_method", sa.String(20), nullable=True),
        sa.Column("iban", sa.String(64), nullable=True),
        sa.Column("swift", sa.String(20), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("capacity_words_per_day", sa.Integer(), nullable=False),
        sa.Column("working_days", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=True),
        sa.Column("nda_signed", sa.Boolean(), nullable=False),
        sa.Column("nda_signed_at", sa.Date(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_vendors_org_id", "vendors", ["org_id"])
    op.create_index("ix_vendors_org_name", "vendors", ["org_id", "name"])

    op.create_table(
        "vendor_absences",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column(
            "vendor_id", sa.String(40), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_vendor_absences_org_id", "vendor_absences", ["org_id"])
    op.create_index("ix_vendor_absences_vendor_id", "vendor_absences", ["vendor_id"])

    op.create_table(
        "vendor_documents",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column(
            "vendor_id", sa.String(40), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("signed", sa.Boolean(), nullable=False),
        sa.Column("signed_at", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("filename", sa.String(400), nullable=True),
        sa.Column("storage_key", sa.String(400), nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_vendor_documents_org_id", "vendor_documents", ["org_id"])
    op.create_index("ix_vendor_documents_vendor_id", "vendor_documents", ["vendor_id"])

    op.create_table(
        "vendor_assignments",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step", sa.String(30), nullable=False),
        sa.Column("service", sa.String(20), nullable=False),
        sa.Column("assignee_kind", sa.String(20), nullable=False),
        sa.Column("vendor_id", sa.String(40), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("offer_group", sa.String(40), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(20), nullable=False),
        sa.Column("words", sa.Integer(), nullable=False),
        sa.Column("words_done", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 2), nullable=False),
        sa.Column("rate", sa.Numeric(12, 5), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _ts("due_at", True),
        sa.Column("offer_timeout_minutes", sa.Integer(), nullable=False),
        _ts("offered_at", True),
        _ts("offer_expires_at", True),
        _ts("responded_at", True),
        _ts("started_at", True),
        _ts("delivered_at", True),
        _ts("approved_at", True),
        sa.Column("token_nonce", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(40), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_vendor_assignments_org_id", "vendor_assignments", ["org_id"])
    op.create_index("ix_vendor_assignments_offer_group", "vendor_assignments", ["offer_group"])
    op.create_index("ix_vendor_assignments_job_step", "vendor_assignments", ["job_id", "step"])
    op.create_index("ix_vendor_assignments_vendor_status", "vendor_assignments", ["vendor_id", "status"])

    op.create_table(
        "number_series",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last", sa.Integer(), nullable=False),
        sa.UniqueConstraint("org_id", "kind", "year"),
    )
    op.create_index("ix_number_series_org_id", "number_series", ["org_id"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column("number", sa.String(40), nullable=False),
        sa.Column("vendor_id", sa.String(40), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("assignment_id", sa.String(40), sa.ForeignKey("vendor_assignments.id"), nullable=False),
        sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _ts("due_at", True),
        _ts("issued_at"),
        sa.Column("vendor_invoice_id", sa.String(40), nullable=True),
        sa.UniqueConstraint("org_id", "number"),
        sa.UniqueConstraint("assignment_id"),
    )
    op.create_index("ix_purchase_orders_org_id", "purchase_orders", ["org_id"])
    op.create_index("ix_purchase_orders_vendor_id", "purchase_orders", ["vendor_id"])
    op.create_index("ix_purchase_orders_job_id", "purchase_orders", ["job_id"])

    op.create_table(
        "vendor_invoices",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column("vendor_id", sa.String(40), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("number", sa.String(60), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("assignment_ids", sa.JSON(), nullable=False),
        sa.Column("lines", sa.JSON(), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(400), nullable=True),
        sa.Column("storage_key", sa.String(400), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        _ts("received_at"),
        _ts("approved_at", True),
        _ts("paid_at", True),
        sa.UniqueConstraint("org_id", "vendor_id", "number"),
    )
    op.create_index("ix_vendor_invoices_org_id", "vendor_invoices", ["org_id"])
    op.create_index("ix_vendor_invoices_vendor_id", "vendor_invoices", ["vendor_id"])
    op.create_index("ix_vendor_invoices_org_period", "vendor_invoices", ["org_id", "period"])


def downgrade() -> None:
    op.drop_table("vendor_invoices")
    op.drop_table("purchase_orders")
    op.drop_table("number_series")
    op.drop_table("vendor_assignments")
    op.drop_table("vendor_documents")
    op.drop_table("vendor_absences")
    op.drop_table("vendors")
    op.drop_column("jobs", "cost_vendors")
