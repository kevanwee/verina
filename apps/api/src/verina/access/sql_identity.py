"""Verified-token identity adapter backed by a Verina-owned SQL directory (ADR 007).

``authenticate`` verifies the bearer token (:mod:`verina.access.tokens`) and uses only the
verified ``(issuer, subject)`` pair to look up an ``identity_bindings`` row. The binding names
a ``(tenant, actor)`` whose ``identity_principals`` row supplies roles, active state and the
trusted display profile. Nothing else in the token is read: role, tenant, group, scope or
e-mail claims have no effect.

``current`` re-reads the principal row on every call, so role changes and deactivation
committed to the shared database are seen by the next authorization check in any process.
When called inside a durable mutation transaction (``SqlMatterMutationUnitOfWork``) it reads
on that same transaction (see :func:`verina.db.bind_connection`); on PostgreSQL the row is
then held with ``FOR SHARE`` until commit, so a concurrent deactivation is ordered after the
mutation rather than racing it. ``profile`` returns the retained display profile even after
deactivation (historical attribution); it never grants authority.

Organizations (ADR 008): every principal belongs to the ``organizations`` row whose id is its
tenant id. ``authenticate`` and ``current`` require that row to exist and be active, so an
organization deactivation makes all of its principals fail on their next request or check
(on PostgreSQL the organization row is also held ``FOR SHARE`` inside a mutation).
:meth:`SqlIdentityAdapter.resolve` exposes the full lookup (principal, platform-admin grant,
or why the token is not linked) for ``/v1/me`` and the administration routes.

Not covered: identity-provider session revocation (a still-valid token for an active binding
keeps working until ``exp``), reads already returned to a caller, and directory changes made
outside this database.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Connection,
    DateTime,
    Engine,
    ForeignKeyConstraint,
    Index,
    Row,
    String,
    Table,
    select,
)
from sqlalchemy.exc import SQLAlchemyError

from verina.access.directory_schema import ensure_organization, organizations, platform_admins
from verina.access.domain import (
    ActorId,
    ActorProfile,
    InvalidIdentifierError,
    Role,
    TenantId,
    _issue_profile,
    is_utc_time,
)
from verina.access.identity import AuthenticationError, Principal, _issue
from verina.access.sql_repository import metadata
from verina.access.subject_hmac import subject_hmac
from verina.access.tokens import (
    MAX_ISSUER_LENGTH,
    MAX_SUBJECT_LENGTH,
    MAX_TOKEN_BYTES,
    JwtVerifier,
    KeySourceUnavailable,
    TokenRejected,
    VerifiedToken,
)
from verina.audit.events import DirectoryChanged
from verina.audit.store import SqlAuditStore
from verina.db import active_connection, bound_connection_required

identity_principals = Table(
    "identity_principals",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("actor_id", String(128), primary_key=True),
    Column("roles", String(200), nullable=False),
    Column("active", Boolean, nullable=False),
    Column("display_name", String(120), nullable=True),
    Column("revision", BigInteger, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("revision >= 1", name="ck_identity_principals_revision"),
)

identity_bindings = Table(
    "identity_bindings",
    metadata,
    Column("issuer", String(255), primary_key=True),
    Column("subject", String(255), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("actor_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "actor_id"],
        [identity_principals.c.tenant_id, identity_principals.c.actor_id],
        name="fk_identity_bindings_principal",
    ),
    Index("ix_identity_bindings_principal", "tenant_id", "actor_id"),
)


class IdentityUnavailableError(RuntimeError):
    """The directory could not be read. Generic; never carries SQL or token detail."""

    def __init__(self) -> None:
        super().__init__("identity directory unavailable")


class DirectoryRecordError(ValueError):
    """A stored directory row is malformed. Callers fail closed."""


def _encode_roles(roles: Iterable[Role | str]) -> str:
    values = sorted({Role(r).value for r in roles})
    return ",".join(values)


def _decode_roles(raw: object) -> frozenset[Role]:
    if not isinstance(raw, str):
        raise DirectoryRecordError("roles")
    if raw == "":
        return frozenset()
    parts = raw.split(",")
    try:
        roles = frozenset(Role(part) for part in parts)
    except ValueError:
        raise DirectoryRecordError("roles") from None
    if len(roles) != len(parts):
        raise DirectoryRecordError("roles")
    return roles


def _principal_from(row: Row[Any]) -> Principal:
    if type(row.active) is not bool:
        raise DirectoryRecordError("active")
    try:
        return _issue(TenantId(row.tenant_id), ActorId(row.actor_id), _decode_roles(row.roles))
    except (InvalidIdentifierError, TypeError):
        raise DirectoryRecordError("principal") from None


def _check_text(value: object, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("invalid identity binding value")
    return value


def _bearer(headers: Mapping[str, str]) -> str:
    values = [v for k, v in headers.items() if k.lower() == "authorization"]
    if not values:
        raise AuthenticationError("missing_credential")
    if len(values) != 1:
        raise AuthenticationError("malformed_credential")
    value = values[0]
    if not isinstance(value, str) or len(value) > MAX_TOKEN_BYTES + 7:
        raise AuthenticationError("malformed_credential")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token or token != token.strip() or " " in token:
        raise AuthenticationError("malformed_credential")
    return token


@dataclass(frozen=True, slots=True)
class Resolution:
    """What a *verified* token resolves to in the Verina directory (never from its claims).

    ``principal`` is set only for an active binding whose principal and organization are both
    active. ``platform_admin_id`` is set when ``(issuer, subject)`` holds the platform-admin
    grant. ``unlinked_reason`` explains a missing principal (internal; audit only).
    """

    token: VerifiedToken
    principal: Principal | None
    platform_admin_id: str | None
    unlinked_reason: str | None

    @property
    def subject(self) -> tuple[str, str]:
        return (self.token.issuer, self.token.subject)


_PRINCIPAL_COLUMNS = (
    identity_principals.c.tenant_id,
    identity_principals.c.actor_id,
    identity_principals.c.roles,
    identity_principals.c.active,
    organizations.c.active.label("organization_active"),
)
_PRINCIPAL_ORGANIZATION = identity_principals.join(
    organizations, organizations.c.id == identity_principals.c.tenant_id
)


class SqlIdentityAdapter:
    """:class:`~verina.access.identity.IdentityAdapter` for verified bearer tokens."""

    def __init__(self, engine: Engine, verifier: JwtVerifier) -> None:
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("unsupported identity database")
        self._engine = engine
        self._verifier = verifier

    @contextmanager
    def _read(self) -> Iterator[tuple[Connection, bool]]:
        bound = active_connection(self._engine)
        if bound is not None:
            yield bound, True
            return
        if bound_connection_required(self._engine):
            # A mutation authorizer must re-check identity on the mutation's own transaction;
            # never fall back to a separate one (which could miss locks or self-block).
            raise IdentityUnavailableError()
        try:
            with self._engine.begin() as conn:
                yield conn, False
        except SQLAlchemyError:
            raise IdentityUnavailableError() from None

    @property
    def verifier(self) -> JwtVerifier:
        return self._verifier

    def verify(self, headers: Mapping[str, str]) -> VerifiedToken:
        """Verify the bearer credential only (no directory read)."""
        token = _bearer(headers)
        try:
            return self._verifier.verify(token)
        except TokenRejected:
            raise AuthenticationError("token_rejected") from None
        except KeySourceUnavailable:
            raise IdentityUnavailableError() from None

    def resolve(self, headers: Mapping[str, str]) -> Resolution:
        """Verify the token, then look up its binding and platform-admin grant.

        Raises :class:`AuthenticationError` only for credential/token failures; a valid but
        unlinked token returns a :class:`Resolution` without a principal.
        """
        verified = self.verify(headers)
        query = (
            select(*_PRINCIPAL_COLUMNS)
            .select_from(
                identity_bindings.join(
                    _PRINCIPAL_ORGANIZATION,
                    (identity_bindings.c.tenant_id == identity_principals.c.tenant_id)
                    & (identity_bindings.c.actor_id == identity_principals.c.actor_id),
                )
            )
            .where(
                identity_bindings.c.issuer == verified.issuer,
                identity_bindings.c.subject == verified.subject,
            )
        )
        admin_query = select(platform_admins.c.admin_id).where(
            platform_admins.c.issuer == verified.issuer,
            platform_admins.c.subject == verified.subject,
        )
        with self._read() as (conn, _):
            row = conn.execute(query).one_or_none()
            admin_id = conn.execute(admin_query).scalar_one_or_none()
        principal: Principal | None = None
        reason: str | None = None
        if row is None:
            reason = "unbound"  # also covers a binding whose organization row is missing
        elif row.active is not True:
            reason = "principal_inactive"
        elif row.organization_active is not True:
            reason = "organization_inactive"
        else:
            try:
                principal = _principal_from(row)
            except DirectoryRecordError:
                reason = "directory_record_invalid"
        return Resolution(
            verified, principal, admin_id if isinstance(admin_id, str) else None, reason
        )

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        resolution = self.resolve(headers)
        if resolution.principal is None:
            raise AuthenticationError(resolution.unlinked_reason or "unbound", resolution.subject)
        return resolution.principal

    def current(self, tenant_id: TenantId, actor_id: ActorId) -> Principal | None:
        if not isinstance(tenant_id, TenantId) or not isinstance(actor_id, ActorId):
            return None
        query = (
            select(*_PRINCIPAL_COLUMNS)
            .select_from(_PRINCIPAL_ORGANIZATION)
            .where(
                identity_principals.c.tenant_id == tenant_id.value,
                identity_principals.c.actor_id == actor_id.value,
            )
        )
        with self._read() as (conn, bound):
            if bound:
                # Inside a durable mutation: hold the principal and organization rows until
                # commit (PostgreSQL FOR SHARE; SQLite already serializes writers with
                # BEGIN IMMEDIATE), so a concurrent deactivation is ordered after the mutation.
                query = query.with_for_update(read=True)
            row = conn.execute(query).one_or_none()
        if row is None or row.active is not True or row.organization_active is not True:
            return None
        try:
            principal = _principal_from(row)
        except DirectoryRecordError:
            return None
        if principal.tenant_id != tenant_id or principal.actor_id != actor_id:
            return None
        return principal

    def profile(self, tenant_id: TenantId, actor_id: ActorId) -> ActorProfile | None:
        if not isinstance(tenant_id, TenantId) or not isinstance(actor_id, ActorId):
            return None
        with self._read() as (conn, _):
            name = conn.execute(
                select(identity_principals.c.display_name).where(
                    identity_principals.c.tenant_id == tenant_id.value,
                    identity_principals.c.actor_id == actor_id.value,
                )
            ).scalar_one_or_none()
        if name is None:
            return None
        try:
            return _issue_profile(tenant_id, actor_id, name)
        except (ValueError, TypeError):
            return None


class IdentityDirectory:
    """Local/dev provisioning of synthetic principals and bindings. No HTTP surface.

    Every write bumps the principal ``revision`` and ``updated_at`` and makes sure the
    principal's tenant has an ``organizations`` row (ADR 008). With an ``audit`` store (the
    provisioning CLI always passes one) each write appends a metadata-only
    ``directory.changed`` event to the tenant's chain in the same transaction; without one
    (unit-test seeding) nothing is audited.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        audit: SqlAuditStore | None = None,
        subject_key: bytes | None = None,
    ) -> None:
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("unsupported identity database")
        if audit is not None and audit._engine is not engine:
            raise ValueError("directory and audit must share one engine")
        self._engine = engine
        self._clock = clock
        self._audit = audit
        self._subject_key = subject_key

    def _now(self) -> datetime:
        now = self._clock()
        if not is_utc_time(now):
            raise ValueError("invalid clock")
        return now

    @contextmanager
    def _write(self, tenant: TenantId) -> Iterator[Connection]:
        with self._engine.begin() as conn:
            if self._audit is not None:
                # Same lock order as matter mutations: tenant chain head first.
                self._audit.lock_tenant_on_connection(conn, tenant.value)
            yield conn

    def _record(self, conn: Connection, tenant: TenantId, now: datetime, **fields: Any) -> None:
        if self._audit is None:
            return
        self._audit.append_on_connection(
            conn,
            tenant.value,
            DirectoryChanged(
                occurred_at=now,
                tenant_id=tenant.value,
                actor="cli:provision",
                actor_kind="cli",
                organization_id=tenant.value,
                **fields,
            ),
        )

    def upsert_principal(
        self,
        tenant_id: str,
        actor_id: str,
        roles: Iterable[Role | str],
        *,
        display_name: str | None = None,
        active: bool = True,
    ) -> int:
        """Create or replace a principal's roles and state. Returns the new revision.

        ``display_name`` sets the trusted profile; omitting it on an update keeps the
        retained profile.
        """
        tenant, actor = TenantId(tenant_id), ActorId(actor_id)
        encoded = _encode_roles(roles)
        if display_name is not None:
            display_name = _issue_profile(tenant, actor, display_name).display_name
        if type(active) is not bool:
            raise ValueError("active must be a boolean")
        now = self._now()
        key = (identity_principals.c.tenant_id == tenant.value) & (
            identity_principals.c.actor_id == actor.value
        )
        with self._write(tenant) as conn:
            ensure_organization(conn, tenant.value, now)
            current = conn.execute(
                select(identity_principals.c.revision).where(key).with_for_update()
            ).scalar_one_or_none()
            if current is None:
                conn.execute(
                    identity_principals.insert().values(
                        tenant_id=tenant.value,
                        actor_id=actor.value,
                        roles=encoded,
                        active=active,
                        display_name=display_name,
                        revision=1,
                        updated_at=now,
                    )
                )
                revision = 1
            else:
                values: dict[str, object] = {
                    "roles": encoded,
                    "active": active,
                    "revision": current + 1,
                    "updated_at": now,
                }
                if display_name is not None:  # an omitted name keeps the retained profile
                    values["display_name"] = display_name
                conn.execute(
                    identity_principals.update()
                    .where(key, identity_principals.c.revision == current)
                    .values(**values)
                )
                revision = int(current) + 1
            self._record(
                conn,
                tenant,
                now,
                action="principal_upserted",
                target_actor_id=actor.value,
                roles=tuple(r for r in encoded.split(",") if r),
                active=active,
                revision=revision,
            )
            return revision

    def set_active(self, tenant_id: str, actor_id: str, active: bool) -> int:
        """Deactivate (or reactivate) without removing the retained profile."""
        tenant, actor = TenantId(tenant_id), ActorId(actor_id)
        if type(active) is not bool:
            raise ValueError("active must be a boolean")
        now = self._now()
        key = (identity_principals.c.tenant_id == tenant.value) & (
            identity_principals.c.actor_id == actor.value
        )
        with self._write(tenant) as conn:
            current = conn.execute(
                select(identity_principals.c.revision).where(key).with_for_update()
            ).scalar_one_or_none()
            if current is None:
                raise LookupError("unknown principal")
            conn.execute(
                identity_principals.update()
                .where(key, identity_principals.c.revision == current)
                .values(active=active, revision=current + 1, updated_at=now)
            )
            self._record(
                conn,
                tenant,
                now,
                action="principal_activation_changed",
                target_actor_id=actor.value,
                active=active,
                revision=int(current) + 1,
            )
            return int(current) + 1

    def bind(self, issuer: str, subject: str, tenant_id: str, actor_id: str) -> None:
        """Bind a verified ``(issuer, subject)`` to an existing principal."""
        issuer = _check_text(issuer, MAX_ISSUER_LENGTH)
        subject = _check_text(subject, MAX_SUBJECT_LENGTH)
        tenant, actor = TenantId(tenant_id), ActorId(actor_id)
        now = self._now()
        with self._write(tenant) as conn:
            exists = conn.execute(
                select(identity_principals.c.revision).where(
                    identity_principals.c.tenant_id == tenant.value,
                    identity_principals.c.actor_id == actor.value,
                )
            ).scalar_one_or_none()
            if exists is None:
                raise LookupError("unknown principal")
            taken = conn.execute(
                select(identity_bindings.c.tenant_id).where(
                    identity_bindings.c.issuer == issuer,
                    identity_bindings.c.subject == subject,
                )
            ).first()
            if taken is not None:
                raise ValueError("binding already exists")
            conn.execute(
                identity_bindings.insert().values(
                    issuer=issuer,
                    subject=subject,
                    tenant_id=tenant.value,
                    actor_id=actor.value,
                    created_at=now,
                )
            )
            self._record(
                conn,
                tenant,
                now,
                action="binding_created",
                target_actor_id=actor.value,
                subject_hmac=subject_hmac(self._subject_key, issuer, subject),
            )

    def unbind(self, issuer: str, subject: str) -> bool:
        """Remove a binding. New requests with that subject then fail authentication."""
        issuer = _check_text(issuer, MAX_ISSUER_LENGTH)
        subject = _check_text(subject, MAX_SUBJECT_LENGTH)
        where = (identity_bindings.c.issuer == issuer) & (identity_bindings.c.subject == subject)
        with self._engine.connect() as probe:
            found = probe.execute(
                select(identity_bindings.c.tenant_id, identity_bindings.c.actor_id).where(where)
            ).first()
        if found is None:
            return False
        tenant = TenantId(found.tenant_id)
        now = self._now()
        with self._write(tenant) as conn:
            result = conn.execute(
                identity_bindings.delete().where(
                    where, identity_bindings.c.tenant_id == tenant.value
                )
            )
            if result.rowcount != 1:
                return False
            self._record(
                conn,
                tenant,
                now,
                action="binding_removed",
                target_actor_id=found.actor_id,
                subject_hmac=subject_hmac(self._subject_key, issuer, subject),
            )
            return True
