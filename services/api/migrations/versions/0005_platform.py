"""Platform: custom roles, team invites, append-only audit log, per-org OpenID Connect SSO.

Hand-written. `alembic upgrade head` on an empty database must equal metadata.create_all;
the tables and users.role_id are listed in dbinit.LATER_TABLES / LATER_COLUMNS so migration
0001 leaves them out.

Revision ID: 0005
Revises: 0004 (the lead re-chains revisions when parallel branches merge)
"""

import sqlalchemy as sa
from alembic import op

from arbiter.models.platform import AUDIT_APPEND_ONLY_TRIGGER_SQL

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _org(primary_key: bool = False) -> sa.Column:
    return sa.Column(
        "org_id", sa.String(40), sa.ForeignKey("organizations.id"), nullable=False, primary_key=primary_key
    )


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("base_role", sa.String(20), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("org_id", "name"),
    )
    op.create_index("ix_roles_org_id", "roles", ["org_id"])

    op.add_column("users", sa.Column("role_id", sa.String(40), sa.ForeignKey("roles.id"), nullable=True))
    op.create_index("ix_users_role_id", "users", ["role_id"])

    op.create_table(
        "user_invites",
        sa.Column("id", sa.String(40), primary_key=True),
        _org(),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", sa.String(40), nullable=True),
        _ts("expires_at"),
        _ts("used_at", nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_user_invites_org_id", "user_invites", ["org_id"])
    op.create_index("ix_user_invites_user_id", "user_invites", ["user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("org_id", sa.String(40), nullable=True),
        sa.Column("actor_type", sa.String(12), nullable=False),
        sa.Column("actor_id", sa.String(40), nullable=False),
        sa.Column("actor_label", sa.String(320), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(80), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("user_agent", sa.String(400), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        _ts("at"),
    )
    op.create_index("ix_audit_org_at", "audit_events", ["org_id", "at"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.execute(AUDIT_APPEND_ONLY_TRIGGER_SQL)

    op.create_table(
        "sso_configs",
        _org(primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("issuer", sa.String(500), nullable=False),
        sa.Column("client_id", sa.String(300), nullable=False),
        sa.Column("client_secret_enc", sa.Text(), nullable=False),
        sa.Column("default_role", sa.String(20), nullable=False),
        sa.Column("default_role_id", sa.String(40), sa.ForeignKey("roles.id"), nullable=True),
        sa.Column("enforce_sso", sa.Boolean(), nullable=False),
        _ts("updated_at"),
    )
    op.create_table(
        "sso_domains",
        sa.Column("domain", sa.String(253), primary_key=True),
        _org(),
        sa.Column("verification_token", sa.String(64), nullable=False),
        _ts("verified_at", nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_sso_domains_org_id", "sso_domains", ["org_id"])
    op.create_table(
        "sso_states",
        sa.Column("state", sa.String(64), primary_key=True),
        _org(),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("next_path", sa.String(500), nullable=False),
        _ts("expires_at"),
        _ts("used_at", nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_sso_states_org_id", "sso_states", ["org_id"])


def downgrade() -> None:
    op.drop_table("sso_states")
    op.drop_table("sso_domains")
    op.drop_table("sso_configs")
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_append_only() CASCADE")
    op.drop_table("user_invites")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_column("users", "role_id")
    op.drop_table("roles")
