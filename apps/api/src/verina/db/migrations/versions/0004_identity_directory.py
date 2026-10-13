"""Verina-owned identity directory: verified (issuer, subject) bindings and principals.

Revision ID: 0004_identity_directory
Revises: 0003_matter_outcomes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_identity_directory"
down_revision: str | Sequence[str] | None = "0003_matter_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_principals",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("roles", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "actor_id"),
        sa.CheckConstraint("revision >= 1", name="ck_identity_principals_revision"),
    )
    op.create_table(
        "identity_bindings",
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("issuer", "subject"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["identity_principals.tenant_id", "identity_principals.actor_id"],
            name="fk_identity_bindings_principal",
        ),
    )
    op.create_index(
        "ix_identity_bindings_principal", "identity_bindings", ["tenant_id", "actor_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_identity_bindings_principal", table_name="identity_bindings")
    op.drop_table("identity_bindings")
    op.drop_table("identity_principals")
