"""SQLAlchemy table definitions for the audit store (mirrors Alembic revision 0001).

The Alembic migration is the source of truth for the database; these ``Table`` objects are
used to build queries. Keep them in step (``tests/audit/test_migrations.py`` checks).
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

HASH_LEN = 80
ID_LEN = 256

audit_events = Table(
    "audit_events",
    metadata,
    Column("tenant_id", String(ID_LEN), nullable=False),
    Column("sequence", BigInteger, nullable=False),
    Column("event_id", String(36), nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("actor", String(ID_LEN), nullable=False),
    Column("matter_id", String(ID_LEN), nullable=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("prev_hash", String(HASH_LEN), nullable=False),
    Column("hash", String(HASH_LEN), nullable=False),
    PrimaryKeyConstraint("tenant_id", "sequence", name="pk_audit_events"),
    UniqueConstraint("event_id", name="uq_audit_events_event_id"),
    Index("ix_audit_events_tenant_type", "tenant_id", "event_type"),
)

audit_chain_head = Table(
    "audit_chain_head",
    metadata,
    Column("tenant_id", String(ID_LEN), primary_key=True),
    Column("last_sequence", BigInteger, nullable=False),
    Column("last_hash", String(HASH_LEN), nullable=False),
    Column("head_mac", String(HASH_LEN), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
