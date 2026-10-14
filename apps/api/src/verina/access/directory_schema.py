"""Organization, platform-admin and member-account tables (migration 0005, ADR 009).

* ``organizations`` - one row per customer organization. Its opaque ``id`` *is* the tenant id
  used by principals, matters and the audit chain. ``active = false`` makes every principal of
  the organization fail authentication on its next request.
* ``platform_admins`` - Verina platform operators, keyed by verified ``(issuer, subject)``.
  The grant lives only here (never in a token claim) and is created only by the bootstrap CLI.
* ``directory_accounts`` - the minimal member-management extension of ``identity_principals``:
  the invited e-mail address (for admin display and to enforce one account per organization)
  and the invite status. Legacy/CLI principals have no row.
* ``admin_idempotency`` - one row per committed administrative mutation, linking the
  ``Idempotency-Key`` to the actor, a request hash and the audit event of that write. It stores
  no request body, name or e-mail address.

These ``Table`` objects mirror the Alembic migration, which is the source of truth.
"""

import re
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    UniqueConstraint,
    select,
)

from verina.access.sql_repository import metadata
from verina.audit.schema import audit_events

SYSTEM_CHAIN_ID = "_verina_system"
"""Audit chain for platform-level events (platform-admin bootstrap, auth failures that cannot
be attributed to an organization). The leading underscore is not a valid ``TenantId`` first
character, so no organization chain can ever collide with it."""

INVITE_STATUSES = ("pending", "accepted")

SLUG_PATTERN = re.compile(r"^[a-z0-9](-?[a-z0-9]){1,39}$")
_SLUG_MAX = 40

organizations = Table(
    "organizations",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("slug", String(40), nullable=False),
    Column("active", Boolean, nullable=False),
    Column("revision", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("slug", name="uq_organizations_slug"),
    CheckConstraint("revision >= 1", name="ck_organizations_revision"),
)

platform_admins = Table(
    "platform_admins",
    metadata,
    Column("issuer", String(255), primary_key=True),
    Column("subject", String(255), primary_key=True),
    Column("admin_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("admin_id", name="uq_platform_admins_admin_id"),
)

directory_accounts = Table(
    "directory_accounts",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("actor_id", String(128), primary_key=True),
    Column("email", String(254), nullable=False),
    Column("invite_status", String(16), nullable=False),
    Column("invited_at", DateTime(timezone=True), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ["tenant_id", "actor_id"],
        ["identity_principals.tenant_id", "identity_principals.actor_id"],
        name="fk_directory_accounts_principal",
    ),
    UniqueConstraint("email", name="uq_directory_accounts_email"),
    CheckConstraint(
        "invite_status IN ('pending', 'accepted')", name="ck_directory_accounts_invite_status"
    ),
)

admin_idempotency = Table(
    "admin_idempotency",
    metadata,
    Column("scope", String(128), primary_key=True),
    Column("operation_id", String(36), primary_key=True),
    Column("actor_key", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("resource_id", String(128), nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("event_id", String(36), ForeignKey(audit_events.c.event_id), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def legacy_slug(tenant_id: str, taken: set[str]) -> str:
    """Derive a unique slug for a tenant created outside the organization routes.

    Same rule as migration 0005's backfill: lower-case, runs of other characters become one
    hyphen, at most 40 characters, a numeric suffix when taken.
    """
    base = re.sub(r"[^a-z0-9]+", "-", tenant_id.lower()).strip("-")[:_SLUG_MAX].strip("-")
    if len(base) < 2:
        base = f"org-{base}".strip("-")
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        suffix = f"-{n}"
        candidate = base[: _SLUG_MAX - len(suffix)].strip("-") + suffix
    return candidate


def ensure_organization(conn: Connection, tenant_id: str, now: datetime) -> bool:
    """Create an active organization row for ``tenant_id`` if none exists (local CLI/tests).

    Returns ``True`` when a row was created. Runs on the caller's transaction.
    """
    exists = conn.execute(select(organizations.c.id).where(organizations.c.id == tenant_id)).first()
    if exists is not None:
        return False
    taken = set(conn.execute(select(organizations.c.slug)).scalars())
    conn.execute(
        organizations.insert().values(
            id=tenant_id,
            name=tenant_id[:120],
            slug=legacy_slug(tenant_id, taken),
            active=True,
            revision=1,
            created_at=now,
            updated_at=now,
        )
    )
    return True
