"""Atomic mutation receipts linked to metadata-only completed audit events.

Revision ID: 0003_matter_outcomes
Revises: 0002_matters
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_matter_outcomes"
down_revision: str | Sequence[str] | None = "0002_matters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matter_mutation_receipts",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("matter_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("expected_revision", sa.BigInteger(), nullable=False),
        sa.Column("result_revision", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("result_access_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "operation_id"),
        sa.ForeignKeyConstraint(["event_id"], ["audit_events.event_id"]),
        sa.CheckConstraint(
            "expected_revision >= 0 AND result_revision = expected_revision + 1",
            name="ck_receipt_revision_step",
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER mutation_receipts_no_{action.lower()} BEFORE {action} "
                "ON matter_mutation_receipts BEGIN SELECT RAISE(ABORT, "
                "'mutation receipts are append-only'); END"
            )
    else:
        op.execute(
            "CREATE FUNCTION verina_receipts_reject_change() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
            "'mutation receipts are append-only'; END $$"
        )
        op.execute(
            "CREATE TRIGGER mutation_receipts_append_only BEFORE UPDATE OR DELETE "
            "ON matter_mutation_receipts FOR EACH ROW EXECUTE FUNCTION "
            "verina_receipts_reject_change()"
        )
        op.execute(
            "CREATE TRIGGER mutation_receipts_no_truncate BEFORE TRUNCATE "
            "ON matter_mutation_receipts FOR EACH STATEMENT EXECUTE FUNCTION "
            "verina_receipts_reject_change()"
        )


def downgrade() -> None:
    op.drop_table("matter_mutation_receipts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION verina_receipts_reject_change()")
