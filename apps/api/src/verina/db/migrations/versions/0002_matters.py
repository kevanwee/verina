"""Tenant-keyed durable matter projection, independent from audit outcomes.

Revision ID: 0002_matters
Revises: 0001_audit_chain
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_matters"
down_revision: str | Sequence[str] | None = "0001_audit_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matters",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("matter_id", sa.String(128), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("access_json", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "matter_id"),
        sa.CheckConstraint("revision >= 1", name="ck_matters_positive_revision"),
    )


def downgrade() -> None:
    op.drop_table("matters")
