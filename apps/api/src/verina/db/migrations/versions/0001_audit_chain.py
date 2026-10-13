"""Append-only, hash-chained audit store (EN-8, ADR 004).

Revision ID: 0001_audit_chain
Revises:
Create Date: 2026-10-13

Tables ``audit_events`` (one row per event, primary key ``(tenant_id, sequence)``) and
``audit_chain_head`` (per-tenant head checkpoint). Database triggers reject UPDATE, DELETE
and TRUNCATE on events, DELETE/TRUNCATE on heads, and any head update that does not move
forward. Triggers are defence in depth: a database owner can still drop them, which is what
hash-chain verification and the keyed head checkpoint detect.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_audit_chain"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_TRIGGERS = (
    """
    CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END
    """,
    """
    CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END
    """,
    """
    CREATE TRIGGER audit_chain_head_no_delete BEFORE DELETE ON audit_chain_head
    BEGIN SELECT RAISE(ABORT, 'audit_chain_head rows cannot be deleted'); END
    """,
    """
    CREATE TRIGGER audit_chain_head_forward_only BEFORE UPDATE ON audit_chain_head
    WHEN NEW.last_sequence <= OLD.last_sequence OR NEW.tenant_id <> OLD.tenant_id
    BEGIN SELECT RAISE(ABORT, 'audit_chain_head may only move forward'); END
    """,
)

_POSTGRES_TRIGGERS = (
    """
    CREATE FUNCTION verina_audit_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'audit store is append-only';
    END
    $$
    """,
    """
    CREATE FUNCTION verina_audit_head_forward_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.last_sequence <= OLD.last_sequence OR NEW.tenant_id <> OLD.tenant_id THEN
        RAISE EXCEPTION 'audit_chain_head may only move forward';
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION verina_audit_reject_change()
    """,
    """
    CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION verina_audit_reject_change()
    """,
    """
    CREATE TRIGGER audit_chain_head_no_delete BEFORE DELETE ON audit_chain_head
    FOR EACH ROW EXECUTE FUNCTION verina_audit_reject_change()
    """,
    """
    CREATE TRIGGER audit_chain_head_no_truncate BEFORE TRUNCATE ON audit_chain_head
    FOR EACH STATEMENT EXECUTE FUNCTION verina_audit_reject_change()
    """,
    """
    CREATE TRIGGER audit_chain_head_forward_only BEFORE UPDATE ON audit_chain_head
    FOR EACH ROW EXECUTE FUNCTION verina_audit_head_forward_only()
    """,
)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("tenant_id", sa.String(256), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("matter_id", sa.String(256), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.String(80), nullable=False),
        sa.Column("hash", sa.String(80), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "sequence", name="pk_audit_events"),
        sa.UniqueConstraint("event_id", name="uq_audit_events_event_id"),
    )
    op.create_index("ix_audit_events_tenant_type", "audit_events", ["tenant_id", "event_type"])
    op.create_table(
        "audit_chain_head",
        sa.Column("tenant_id", sa.String(256), primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.String(80), nullable=False),
        sa.Column("head_mac", sa.String(80), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    dialect = op.get_bind().dialect.name
    statements = _POSTGRES_TRIGGERS if dialect == "postgresql" else _SQLITE_TRIGGERS
    if dialect not in ("postgresql", "sqlite"):  # pragma: no cover - guarded by make_engine use
        raise NotImplementedError(f"audit store triggers not written for {dialect}")
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    # Dropping a table drops its triggers on both dialects.
    op.drop_table("audit_chain_head")
    op.drop_index("ix_audit_events_tenant_type", table_name="audit_events")
    op.drop_table("audit_events")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS verina_audit_head_forward_only()")
        op.execute("DROP FUNCTION IF EXISTS verina_audit_reject_change()")
