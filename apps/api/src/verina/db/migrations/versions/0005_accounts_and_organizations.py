"""Organizations, platform admins, member accounts and admin idempotency (ADR 009).

Revision ID: 0005_accounts_and_organizations
Revises: 0004_identity_directory

Existing principals keep working: every distinct ``identity_principals.tenant_id`` gets an
active ``organizations`` row (name = tenant id, slug derived from it). Authentication then
requires an active organization row for the principal's tenant (fail closed if missing).
``admin_idempotency`` is append-only (database triggers), like mutation receipts.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0005_accounts_and_organizations"
down_revision: str | Sequence[str] | None = "0004_identity_directory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLUG_MAX = 40


def _slug_base(tenant_id: str) -> str:
    """Self-contained copy of the slug rule (migrations must not depend on app code)."""
    base = re.sub(r"[^a-z0-9]+", "-", tenant_id.lower()).strip("-")[:_SLUG_MAX].strip("-")
    return base if len(base) >= 2 else f"org-{base}".strip("-")


def _unique_slug(base: str, taken: set[str]) -> str:
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        suffix = f"-{n}"
        candidate = base[: _SLUG_MAX - len(suffix)].strip("-") + suffix
    taken.add(candidate)
    return candidate


def upgrade() -> None:
    organizations = op.create_table(
        "organizations",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        sa.CheckConstraint("revision >= 1", name="ck_organizations_revision"),
    )
    op.create_table(
        "platform_admins",
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("admin_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("issuer", "subject"),
        sa.UniqueConstraint("admin_id", name="uq_platform_admins_admin_id"),
    )
    op.create_table(
        "directory_accounts",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("invite_status", sa.String(16), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "actor_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["identity_principals.tenant_id", "identity_principals.actor_id"],
            name="fk_directory_accounts_principal",
        ),
        sa.UniqueConstraint("email", name="uq_directory_accounts_email"),
        sa.CheckConstraint(
            "invite_status IN ('pending', 'accepted')",
            name="ck_directory_accounts_invite_status",
        ),
    )
    op.create_table(
        "admin_idempotency",
        sa.Column("scope", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("actor_key", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope", "operation_id"),
        sa.ForeignKeyConstraint(["event_id"], ["audit_events.event_id"]),
    )

    bind = op.get_bind()
    # Offline (--sql) runs cannot read existing rows; the backfill applies online only.
    tenants = (
        []
        if op.get_context().as_sql
        else [
            row[0]
            for row in bind.execute(
                sa.text("SELECT DISTINCT tenant_id FROM identity_principals ORDER BY tenant_id")
            )
        ]
    )
    now = datetime.now(UTC)
    taken: set[str] = set()
    rows = [
        {
            "id": tenant,
            "name": tenant[:120],
            "slug": _unique_slug(_slug_base(tenant), taken),
            "active": True,
            "revision": 1,
            "created_at": now,
            "updated_at": now,
        }
        for tenant in tenants
    ]
    if rows:
        op.bulk_insert(organizations, rows)

    if bind.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER admin_idempotency_no_{action.lower()} BEFORE {action} "
                "ON admin_idempotency BEGIN SELECT RAISE(ABORT, "
                "'admin idempotency records are append-only'); END"
            )
    else:
        op.execute(
            "CREATE FUNCTION verina_admin_idempotency_reject_change() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
            "'admin idempotency records are append-only'; END $$"
        )
        op.execute(
            "CREATE TRIGGER admin_idempotency_append_only BEFORE UPDATE OR DELETE "
            "ON admin_idempotency FOR EACH ROW EXECUTE FUNCTION "
            "verina_admin_idempotency_reject_change()"
        )
        op.execute(
            "CREATE TRIGGER admin_idempotency_no_truncate BEFORE TRUNCATE "
            "ON admin_idempotency FOR EACH STATEMENT EXECUTE FUNCTION "
            "verina_admin_idempotency_reject_change()"
        )


def downgrade() -> None:
    op.drop_table("admin_idempotency")
    op.drop_table("directory_accounts")
    op.drop_table("platform_admins")
    op.drop_table("organizations")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION verina_admin_idempotency_reject_change()")
