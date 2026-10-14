"""Accounts and organizations service (ADR 009, docs/api/ACCOUNTS_CONTRACT.md).

Platform administrators create organizations and invite members; tenant administrators manage
members of their own organization. Every write commits, in one transaction, the directory
change, a metadata-only ``directory.changed`` audit event (organization chain, or the system
chain for platform-level writes) and, for HTTP mutations, an ``admin_idempotency`` row.

Authority comes only from the Verina directory: the platform-admin grant (``platform_admins``,
keyed by verified ``(issuer, subject)``) and the caller's principal roles. Token claims never
grant anything. Denials are uniform ``not_found`` so a caller cannot probe which organizations
or members exist.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Row, func, select
from sqlalchemy.exc import IntegrityError

from verina.access.auth_admin import AuthAdminError, AuthAdminPort, InviteAlreadyAccepted
from verina.access.directory_schema import (
    SLUG_PATTERN,
    SYSTEM_CHAIN_ID,
    admin_idempotency,
    directory_accounts,
    organizations,
    platform_admins,
)
from verina.access.domain import ActorId, Role, TenantId
from verina.access.identity import Principal
from verina.access.sql_identity import (
    DirectoryRecordError,
    _decode_roles,
    _encode_roles,
    identity_bindings,
    identity_principals,
)
from verina.access.subject_hmac import subject_hmac
from verina.audit.events import DirectoryChanged
from verina.audit.store import SqlAuditStore

MAX_EMAIL_LENGTH = 254
MAX_LISTED = 1000
"""Hard cap on organizations/members returned by one list call (no pagination yet)."""
_EMAIL = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}"
    r"@(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


class AccountsError(Exception):
    """A generic, disclosable failure code (mapped to HTTP centrally). Carries no input."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalise_email(raw: object) -> str:
    """Lower-case, NFC, ASCII address in a conservative shape; raise ``ValueError`` otherwise.

    Supabase stores e-mail addresses lower-cased; matching the same normal form keeps the
    one-account-one-organization rule exact.
    """
    if not isinstance(raw, str):
        raise ValueError("invalid email")
    value = unicodedata.normalize("NFC", raw).strip().lower()
    if len(value) > MAX_EMAIL_LENGTH or not value.isascii() or _EMAIL.fullmatch(value) is None:
        raise ValueError("invalid email")
    return value


def request_hash(action: str, scope: str, body: object) -> str:
    """Fingerprint of a command. Stored instead of the body (which may hold an e-mail)."""
    material = json.dumps([action, scope, body], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def actor_key(issuer: str, subject: str) -> str:
    return hashlib.sha256(f"{issuer}\n{subject}".encode()).hexdigest()


def bootstrap_platform_admin(
    engine: Engine,
    audit: SqlAuditStore,
    auth_admin: AuthAdminPort,
    *,
    issuer: str,
    email: str,
    redirect_to: str | None = None,
    subject_key: bytes | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Create the first platform administrator; refuse if one already exists.

    Invites (or finds) the identity-provider user for ``email``, then records the grant and a
    ``platform_admin_bootstrapped`` event on the system chain atomically. Returns the opaque
    admin id. The e-mail address is not stored in Verina.
    """
    address = normalise_email(email)
    with engine.connect() as probe:
        if probe.execute(select(platform_admins.c.admin_id).limit(1)).first() is not None:
            raise AccountsError("platform_admin_exists")
    subject = auth_admin.invite_user(address, redirect_to)
    admin_id = "pa_" + uuid4().hex
    now = clock()
    with engine.begin() as conn:
        audit.lock_tenant_on_connection(conn, SYSTEM_CHAIN_ID)
        if conn.execute(select(platform_admins.c.admin_id).limit(1)).first() is not None:
            raise AccountsError("platform_admin_exists")
        conn.execute(
            platform_admins.insert().values(
                issuer=issuer, subject=subject, admin_id=admin_id, created_at=now
            )
        )
        audit.append_on_connection(
            conn,
            SYSTEM_CHAIN_ID,
            DirectoryChanged(
                occurred_at=now,
                tenant_id=SYSTEM_CHAIN_ID,
                actor="cli:bootstrap",
                actor_kind="cli",
                action="platform_admin_bootstrapped",
                target_actor_id=admin_id,
                subject_hmac=subject_hmac(subject_key, issuer, subject),
            ),
        )
    return admin_id


# --------------------------------------------------------------------------- service

ActingKind = Literal["platform_admin", "tenant_admin"]


@dataclass(frozen=True, slots=True)
class Caller:
    """A verified caller and what the directory says about it (never what the token says)."""

    issuer: str
    subject: str
    aal: str | None
    principal: Principal | None
    platform_admin_id: str | None

    @property
    def key(self) -> str:
        return actor_key(self.issuer, self.subject)


@dataclass(frozen=True, slots=True)
class OrganizationView:
    id: str
    name: str
    slug: str
    active: bool
    member_count: int = 0

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "slug": self.slug, "active": self.active}

    def full(self) -> dict[str, Any]:
        """List/GET/PATCH representation: the organization plus its member count."""
        return {**self.public(), "member_count": self.member_count}


@dataclass(frozen=True, slots=True)
class MemberView:
    actor_id: str
    display_name: str | None
    email: str | None
    roles: tuple[str, ...]
    active: bool
    invite_status: str

    def public(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "display_name": self.display_name,
            "email": self.email,
            "roles": list(self.roles),
            "active": self.active,
            "invite_status": self.invite_status,
        }


@dataclass(frozen=True, slots=True)
class Outcome[T]:
    status: int
    value: T


@dataclass(frozen=True, slots=True)
class _Acting:
    actor: str
    kind: ActingKind


@dataclass(frozen=True, slots=True)
class _Replay:
    resource_id: str
    status: int


def _roles(values: Iterable[Role | str]) -> tuple[str, ...]:
    """Validate a non-empty set of member roles; returns them sorted."""
    items = list(values)
    roles = {Role(v).value for v in items}
    if not roles or len(roles) != len(items):
        raise ValueError("roles must be a non-empty set")
    return tuple(sorted(roles))


def _display_name(value: str) -> str:
    name = value.strip()
    if not 0 < len(name) <= 120 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("invalid display name")
    return name


class AccountsService:
    def __init__(
        self,
        engine: Engine,
        audit: SqlAuditStore,
        auth_admin: AuthAdminPort | None,
        *,
        issuer: str,
        invite_redirect_url: str | None = None,
        subject_key: bytes | None = None,
        admin_require_aal2: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if audit._engine is not engine:
            raise ValueError("accounts and audit must share one engine")
        self._engine = engine
        self._audit = audit
        self._auth_admin = auth_admin
        self._issuer = issuer
        self._redirect = invite_redirect_url
        self._subject_key = subject_key
        self._admin_require_aal2 = admin_require_aal2
        self._clock = clock

    # ---- authorization -----------------------------------------------------------------

    def _platform(self, caller: Caller) -> _Acting | None:
        if caller.platform_admin_id is None:
            return None
        if self._admin_require_aal2 and caller.aal != "aal2":
            return None
        return _Acting(caller.platform_admin_id, "platform_admin")

    def _deny(self, caller: Caller) -> AccountsError:
        # A platform admin who only lacks step-up gets the RFC 9470 challenge; everyone else
        # gets the uniform not_found.
        if caller.platform_admin_id is not None:
            return AccountsError("insufficient_user_authentication")
        return AccountsError("not_found")

    def _require_platform(self, caller: Caller) -> _Acting:
        acting = self._platform(caller)
        if acting is None:
            raise self._deny(caller)
        return acting

    def _require_org_admin(self, caller: Caller, org_id: str) -> tuple[_Acting, TenantId]:
        tenant = TenantId.parse(org_id)
        acting = self._platform(caller)
        principal = caller.principal
        if (
            acting is None
            and tenant is not None
            and principal is not None
            and principal.tenant_id == tenant
            and Role.TENANT_ADMIN in principal.roles
        ):
            acting = _Acting(principal.actor_id.value, "tenant_admin")
        if acting is None:
            raise self._deny(caller)
        if tenant is None:
            raise AccountsError("not_found")
        return acting, tenant

    def _recheck(self, conn: Connection, caller: Caller, acting: _Acting, org_id: str) -> None:
        """Re-read and hold current authority until protected reads/effects finish."""
        if acting.kind == "platform_admin":
            row = conn.execute(
                select(platform_admins.c.admin_id)
                .where(
                    platform_admins.c.issuer == caller.issuer,
                    platform_admins.c.subject == caller.subject,
                )
                .with_for_update(read=True)
            ).first()
            if row is None or row.admin_id != acting.actor:
                raise AccountsError("not_found")
            return
        row = conn.execute(
            select(
                identity_principals.c.roles, identity_principals.c.active, organizations.c.active
            )
            .select_from(
                identity_principals.join(
                    organizations, organizations.c.id == identity_principals.c.tenant_id
                ).join(
                    identity_bindings,
                    (identity_bindings.c.tenant_id == identity_principals.c.tenant_id)
                    & (identity_bindings.c.actor_id == identity_principals.c.actor_id),
                )
            )
            .where(
                identity_principals.c.tenant_id == org_id,
                identity_principals.c.actor_id == acting.actor,
                identity_bindings.c.issuer == caller.issuer,
                identity_bindings.c.subject == caller.subject,
            )
            .with_for_update(read=True)
        ).first()
        try:
            ok = (
                row is not None
                and row[1] is True
                and row[2] is True
                and Role.TENANT_ADMIN in _decode_roles(row[0])
            )
        except DirectoryRecordError:
            ok = False
        if not ok:
            raise AccountsError("not_found")

    # ---- idempotency -------------------------------------------------------------------

    @staticmethod
    def _replay(
        conn: Connection, scope: str, operation_id: UUID, caller: Caller, action: str, rhash: str
    ) -> _Replay | None:
        row = conn.execute(
            select(admin_idempotency).where(
                admin_idempotency.c.scope == scope,
                admin_idempotency.c.operation_id == str(operation_id),
            )
        ).first()
        if row is None:
            return None
        if (row.actor_key, row.action, row.request_hash) != (caller.key, action, rhash):
            raise AccountsError("idempotency_key_reused")
        return _Replay(str(row.resource_id), int(row.status_code))

    def _remember(
        self,
        conn: Connection,
        scope: str,
        operation_id: UUID,
        caller: Caller,
        action: str,
        rhash: str,
        resource_id: str,
        status: int,
        event_id: UUID,
        now: datetime,
    ) -> None:
        conn.execute(
            admin_idempotency.insert().values(
                scope=scope,
                operation_id=str(operation_id),
                actor_key=caller.key,
                action=action,
                request_hash=rhash,
                resource_id=resource_id,
                status_code=status,
                event_id=str(event_id),
                created_at=now,
            )
        )

    def _event(self, conn: Connection, chain: str, acting: _Acting, **fields: Any) -> UUID:
        event = self._audit.append_on_connection(
            conn,
            chain,
            DirectoryChanged(
                occurred_at=self._clock(),
                tenant_id=chain,
                actor=acting.actor,
                actor_kind=acting.kind,
                **fields,
            ),
        )
        return event.event_id

    # ---- views -------------------------------------------------------------------------

    @staticmethod
    def _org_view(conn: Connection, org_id: str) -> OrganizationView | None:
        row = conn.execute(select(organizations).where(organizations.c.id == org_id)).first()
        if row is None:
            return None
        members = conn.execute(
            select(func.count())
            .select_from(identity_principals)
            .where(identity_principals.c.tenant_id == org_id)
        ).scalar_one()
        return OrganizationView(row.id, row.name, row.slug, bool(row.active), int(members))

    @staticmethod
    def _member_from(row: Row[Any]) -> MemberView:
        try:
            roles = tuple(sorted(r.value for r in _decode_roles(row.roles)))
        except DirectoryRecordError:
            roles = ()
        return MemberView(
            actor_id=row.actor_id,
            display_name=row.display_name,
            email=row.email,
            roles=roles,
            active=row.active is True,
            # CLI-provisioned principals have no invitation; they are bound, so "accepted".
            invite_status=row.invite_status or "accepted",
        )

    @staticmethod
    def _members_query() -> Any:
        return select(
            identity_principals.c.actor_id,
            identity_principals.c.display_name,
            identity_principals.c.roles,
            identity_principals.c.active,
            directory_accounts.c.email,
            directory_accounts.c.invite_status,
        ).select_from(
            identity_principals.outerjoin(
                directory_accounts,
                (directory_accounts.c.tenant_id == identity_principals.c.tenant_id)
                & (directory_accounts.c.actor_id == identity_principals.c.actor_id),
            )
        )

    def _member_view(self, conn: Connection, org_id: str, actor_id: str) -> MemberView | None:
        row = conn.execute(
            self._members_query().where(
                identity_principals.c.tenant_id == org_id,
                identity_principals.c.actor_id == actor_id,
            )
        ).first()
        return None if row is None else self._member_from(row)

    # ---- identity ----------------------------------------------------------------------

    def me(self, caller: Caller) -> dict[str, Any]:
        """Refresh directory facts; accept an invitation only for a current binding."""
        principal = caller.principal
        with self._engine.begin() as conn:
            if principal is not None:
                # Keep the same chain -> authority lock order as administrative writes.
                self._audit.lock_tenant_on_connection(conn, principal.tenant_id.value)
            admin_id = conn.execute(
                select(platform_admins.c.admin_id)
                .where(
                    platform_admins.c.issuer == caller.issuer,
                    platform_admins.c.subject == caller.subject,
                )
                .with_for_update(read=True)
            ).scalar_one_or_none()
            is_admin = admin_id is not None
            unbound: dict[str, Any] = {"linked": False}
            if is_admin:
                unbound = {
                    "linked": True,
                    "actor_id": None,
                    "display_name": None,
                    "organization": None,
                    "roles": [],
                    "platform_admin": True,
                }
            if principal is None:
                return unbound
            tenant, actor = principal.tenant_id.value, principal.actor_id.value
            row = conn.execute(
                select(
                    identity_principals.c.display_name,
                    identity_principals.c.roles,
                    organizations.c.id,
                    organizations.c.name,
                    organizations.c.slug,
                )
                .select_from(
                    identity_principals.join(
                        organizations, organizations.c.id == identity_principals.c.tenant_id
                    ).join(
                        identity_bindings,
                        (identity_bindings.c.tenant_id == identity_principals.c.tenant_id)
                        & (identity_bindings.c.actor_id == identity_principals.c.actor_id),
                    )
                )
                .where(
                    identity_principals.c.tenant_id == tenant,
                    identity_principals.c.actor_id == actor,
                    identity_principals.c.active.is_(True),
                    organizations.c.active.is_(True),
                    identity_bindings.c.issuer == caller.issuer,
                    identity_bindings.c.subject == caller.subject,
                )
                .with_for_update(read=True)
            ).first()
            if row is None:
                return unbound
            try:
                roles = sorted(r.value for r in _decode_roles(row.roles))
            except DirectoryRecordError:
                return unbound
            self._accept_invite(conn, principal)
            return {
                "linked": True,
                "actor_id": actor,
                "display_name": row.display_name,
                "organization": {"id": row.id, "name": row.name, "slug": row.slug},
                "roles": roles,
                "platform_admin": is_admin,
            }

    def _accept_invite(self, conn: Connection, principal: Principal) -> None:
        tenant, actor = principal.tenant_id.value, principal.actor_id.value
        now = self._clock()
        result = conn.execute(
            directory_accounts.update()
            .where(
                directory_accounts.c.tenant_id == tenant,
                directory_accounts.c.actor_id == actor,
                directory_accounts.c.invite_status == "pending",
            )
            .values(invite_status="accepted", accepted_at=now)
        )
        if result.rowcount == 1:
            self._audit.append_on_connection(
                conn,
                tenant,
                DirectoryChanged(
                    occurred_at=now,
                    tenant_id=tenant,
                    actor=actor,
                    actor_kind="member",
                    action="invite_accepted",
                    organization_id=tenant,
                    target_actor_id=actor,
                ),
            )

    # ---- organizations -----------------------------------------------------------------

    def list_organizations(self, caller: Caller) -> list[OrganizationView]:
        acting = self._require_platform(caller)
        counts = (
            select(
                identity_principals.c.tenant_id.label("tenant_id"),
                func.count().label("members"),
            )
            .group_by(identity_principals.c.tenant_id)
            .subquery()
        )
        with self._engine.begin() as conn:
            self._recheck(conn, caller, acting, SYSTEM_CHAIN_ID)
            rows = conn.execute(
                select(organizations, counts.c.members)
                .select_from(
                    organizations.outerjoin(counts, counts.c.tenant_id == organizations.c.id)
                )
                .order_by(organizations.c.name, organizations.c.id)
                .limit(MAX_LISTED)
            ).all()
        return [
            OrganizationView(r.id, r.name, r.slug, bool(r.active), int(r.members or 0))
            for r in rows
        ]

    def get_organization(self, caller: Caller, org_id: str) -> OrganizationView:
        acting = self._require_platform(caller)
        with self._engine.begin() as conn:
            self._recheck(conn, caller, acting, SYSTEM_CHAIN_ID)
            view = self._org_view(conn, org_id) if TenantId.parse(org_id) else None
        if view is None:
            raise AccountsError("not_found")
        return view

    def create_organization(
        self, caller: Caller, operation_id: UUID, name: str, slug: str
    ) -> Outcome[OrganizationView]:
        acting = self._require_platform(caller)
        name = _display_name(name)
        if not isinstance(slug, str) or SLUG_PATTERN.fullmatch(slug) is None:
            raise ValueError("invalid slug")
        action, scope = "create_organization", SYSTEM_CHAIN_ID
        rhash = request_hash(action, scope, {"name": name, "slug": slug})
        now = self._clock()
        try:
            with self._engine.begin() as conn:
                # The system chain lock serialises organization creation (idempotency + slug).
                self._audit.lock_tenant_on_connection(conn, scope)
                self._recheck(conn, caller, acting, scope)
                replay = self._replay(conn, scope, operation_id, caller, action, rhash)
                if replay is not None:
                    view = self._org_view(conn, replay.resource_id)
                    if view is None:  # pragma: no cover - organizations are never deleted
                        raise AccountsError("not_found")
                    return Outcome(replay.status, view)
                taken = conn.execute(
                    select(organizations.c.id).where(organizations.c.slug == slug)
                ).first()
                if taken is not None:
                    raise AccountsError("slug_taken")
                org_id = "org_" + uuid4().hex
                conn.execute(
                    organizations.insert().values(
                        id=org_id,
                        name=name,
                        slug=slug,
                        active=True,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                event_id = self._event(
                    conn,
                    org_id,
                    acting,
                    action="organization_created",
                    organization_id=org_id,
                    operation_id=operation_id,
                    request_hash=rhash,
                    organization_active=True,
                    revision=1,
                )
                self._remember(
                    conn, scope, operation_id, caller, action, rhash, org_id, 201, event_id, now
                )
        except IntegrityError:
            raise AccountsError("slug_taken") from None
        return Outcome(201, OrganizationView(org_id, name, slug, True))

    def update_organization(
        self,
        caller: Caller,
        operation_id: UUID,
        org_id: str,
        *,
        name: str | None = None,
        active: bool | None = None,
    ) -> Outcome[OrganizationView]:
        acting = self._require_platform(caller)
        if name is None and active is None:
            raise ValueError("nothing to change")
        name = None if name is None else _display_name(name)
        if active is not None and type(active) is not bool:
            raise ValueError("active must be a boolean")
        self.get_organization(caller, org_id)  # 404 before taking any chain lock
        action = "update_organization"
        rhash = request_hash(action, org_id, {"name": name, "active": active})
        now = self._clock()
        with self._engine.begin() as conn:
            self._audit.lock_tenant_on_connection(conn, org_id)
            self._recheck(conn, caller, acting, org_id)
            replay = self._replay(conn, org_id, operation_id, caller, action, rhash)
            if replay is None:
                row = conn.execute(
                    select(organizations).where(organizations.c.id == org_id).with_for_update()
                ).one()
                values: dict[str, Any] = {"revision": int(row.revision) + 1, "updated_at": now}
                if name is not None:
                    values["name"] = name
                if active is not None:
                    values["active"] = active
                conn.execute(
                    organizations.update().where(organizations.c.id == org_id).values(**values)
                )
                event_id = self._event(
                    conn,
                    org_id,
                    acting,
                    action="organization_updated",
                    organization_id=org_id,
                    operation_id=operation_id,
                    request_hash=rhash,
                    organization_active=values.get("active", bool(row.active)),
                    revision=values["revision"],
                )
                self._remember(
                    conn, org_id, operation_id, caller, action, rhash, org_id, 200, event_id, now
                )
            view = self._org_view(conn, org_id)
        if view is None:  # pragma: no cover - organizations are never deleted
            raise AccountsError("not_found")
        return Outcome(200 if replay is None else replay.status, view)

    # ---- members -----------------------------------------------------------------------

    def _existing_org(self, conn: Connection, tenant: TenantId) -> OrganizationView:
        view = self._org_view(conn, tenant.value)
        if view is None:
            raise AccountsError("not_found")
        return view

    def list_members(self, caller: Caller, org_id: str) -> list[MemberView]:
        acting, tenant = self._require_org_admin(caller, org_id)
        with self._engine.begin() as conn:
            self._recheck(conn, caller, acting, tenant.value)
            self._existing_org(conn, tenant)
            rows = conn.execute(
                self._members_query()
                .where(identity_principals.c.tenant_id == tenant.value)
                .order_by(identity_principals.c.display_name, identity_principals.c.actor_id)
                .limit(MAX_LISTED)
            ).all()
        return [self._member_from(r) for r in rows]

    def invite_member(
        self,
        caller: Caller,
        operation_id: UUID,
        org_id: str,
        *,
        email: str,
        display_name: str,
        roles: Sequence[Role | str],
    ) -> Outcome[MemberView]:
        acting, tenant = self._require_org_admin(caller, org_id)
        address = normalise_email(email)
        name = _display_name(display_name)
        role_values = _roles(roles)
        action = "invite_member"
        rhash = request_hash(
            action, tenant.value, {"email": address, "name": name, "roles": list(role_values)}
        )
        with self._engine.begin() as conn:
            self._audit.lock_tenant_on_connection(conn, tenant.value)
            self._recheck(conn, caller, acting, tenant.value)
            org = self._existing_org(conn, tenant)
            replay = self._replay(conn, tenant.value, operation_id, caller, action, rhash)
            if replay is not None:
                return self._replayed_member(conn, tenant, replay)
            if not org.active:
                raise AccountsError("organization_inactive")
            if self._email_taken(conn, address):
                raise AccountsError("account_exists")
            if self._auth_admin is None:
                raise AuthAdminError("misconfigured")
            subject = self._auth_admin.invite_user(address, self._redirect)
        actor_id = "act_" + uuid4().hex
        now = self._clock()
        try:
            with self._engine.begin() as conn:
                self._audit.lock_tenant_on_connection(conn, tenant.value)
                self._recheck(conn, caller, acting, tenant.value)
                replay = self._replay(conn, tenant.value, operation_id, caller, action, rhash)
                if replay is not None:
                    return self._replayed_member(conn, tenant, replay)
                if not self._existing_org(conn, tenant).active:
                    raise AccountsError("organization_inactive")
                bound = conn.execute(
                    select(identity_bindings.c.tenant_id).where(
                        identity_bindings.c.issuer == self._issuer,
                        identity_bindings.c.subject == subject,
                    )
                ).first()
                if bound is not None or self._email_taken(conn, address):
                    raise AccountsError("account_exists")
                conn.execute(
                    identity_principals.insert().values(
                        tenant_id=tenant.value,
                        actor_id=actor_id,
                        roles=_encode_roles(role_values),
                        active=True,
                        display_name=name,
                        revision=1,
                        updated_at=now,
                    )
                )
                conn.execute(
                    directory_accounts.insert().values(
                        tenant_id=tenant.value,
                        actor_id=actor_id,
                        email=address,
                        invite_status="pending",
                        invited_at=now,
                        accepted_at=None,
                    )
                )
                conn.execute(
                    identity_bindings.insert().values(
                        issuer=self._issuer,
                        subject=subject,
                        tenant_id=tenant.value,
                        actor_id=actor_id,
                        created_at=now,
                    )
                )
                event_id = self._event(
                    conn,
                    tenant.value,
                    acting,
                    action="member_invited",
                    organization_id=tenant.value,
                    target_actor_id=actor_id,
                    operation_id=operation_id,
                    request_hash=rhash,
                    roles=role_values,
                    active=True,
                    revision=1,
                    subject_hmac=subject_hmac(self._subject_key, self._issuer, subject),
                )
                self._remember(
                    conn,
                    tenant.value,
                    operation_id,
                    caller,
                    action,
                    rhash,
                    actor_id,
                    201,
                    event_id,
                    now,
                )
        except IntegrityError:
            raise AccountsError("account_exists") from None
        return Outcome(201, MemberView(actor_id, name, address, role_values, True, "pending"))

    @staticmethod
    def _email_taken(conn: Connection, address: str) -> bool:
        return (
            conn.execute(
                select(directory_accounts.c.actor_id).where(directory_accounts.c.email == address)
            ).first()
            is not None
        )

    def _replayed_member(
        self, conn: Connection, tenant: TenantId, replay: _Replay
    ) -> Outcome[MemberView]:
        view = self._member_view(conn, tenant.value, replay.resource_id)
        if view is None:  # pragma: no cover - principals are never deleted
            raise AccountsError("not_found")
        return Outcome(replay.status, view)

    def update_member(
        self,
        caller: Caller,
        operation_id: UUID,
        org_id: str,
        actor_id: str,
        *,
        roles: Sequence[Role | str] | None = None,
        active: bool | None = None,
        display_name: str | None = None,
    ) -> Outcome[MemberView]:
        acting, tenant = self._require_org_admin(caller, org_id)
        actor = ActorId.parse(actor_id)
        if roles is None and active is None and display_name is None:
            raise ValueError("nothing to change")
        role_values = None if roles is None else _roles(roles)
        name = None if display_name is None else _display_name(display_name)
        if active is not None and type(active) is not bool:
            raise ValueError("active must be a boolean")
        action = "update_member"
        rhash = request_hash(
            action,
            tenant.value,
            {
                "actor_id": actor_id,
                "roles": None if role_values is None else list(role_values),
                "active": active,
                "name": name,
            },
        )
        if actor is None:
            raise AccountsError("not_found")
        with self._engine.begin() as conn:
            self._recheck(conn, caller, acting, tenant.value)
            self._existing_org(conn, tenant)
            if self._member_view(conn, tenant.value, actor.value) is None:
                raise AccountsError("not_found")
        now = self._clock()
        with self._engine.begin() as conn:
            self._audit.lock_tenant_on_connection(conn, tenant.value)
            self._recheck(conn, caller, acting, tenant.value)
            replay = self._replay(conn, tenant.value, operation_id, caller, action, rhash)
            if replay is not None:
                return self._replayed_member(conn, tenant, replay)
            key = (identity_principals.c.tenant_id == tenant.value) & (
                identity_principals.c.actor_id == actor.value
            )
            row = conn.execute(select(identity_principals).where(key).with_for_update()).one()
            try:
                current_roles = {r.value for r in _decode_roles(row.roles)}
            except DirectoryRecordError:
                current_roles = set()
            new_roles = set(role_values) if role_values is not None else current_roles
            new_active = bool(row.active) if active is None else active
            admin = Role.TENANT_ADMIN.value
            was_admin = row.active is True and admin in current_roles
            if was_admin and not (new_active and admin in new_roles):
                self._ensure_other_admin(conn, tenant.value, actor.value)
            values: dict[str, Any] = {
                "roles": _encode_roles(new_roles),
                "active": new_active,
                "revision": int(row.revision) + 1,
                "updated_at": now,
            }
            if name is not None:
                values["display_name"] = name
            conn.execute(
                identity_principals.update()
                .where(key, identity_principals.c.revision == row.revision)
                .values(**values)
            )
            event_id = self._event(
                conn,
                tenant.value,
                acting,
                action="member_updated",
                organization_id=tenant.value,
                target_actor_id=actor.value,
                operation_id=operation_id,
                request_hash=rhash,
                roles=tuple(sorted(new_roles)),
                active=new_active,
                revision=values["revision"],
            )
            self._remember(
                conn,
                tenant.value,
                operation_id,
                caller,
                action,
                rhash,
                actor.value,
                200,
                event_id,
                now,
            )
            view = self._member_view(conn, tenant.value, actor.value)
        if view is None:  # pragma: no cover - read in the same transaction
            raise AccountsError("not_found")
        return Outcome(200, view)

    @staticmethod
    def _ensure_other_admin(conn: Connection, tenant: str, actor: str) -> None:
        rows = conn.execute(
            select(identity_principals.c.roles).where(
                identity_principals.c.tenant_id == tenant,
                identity_principals.c.actor_id != actor,
                identity_principals.c.active.is_(True),
            )
        ).scalars()
        for raw in rows:
            try:
                if Role.TENANT_ADMIN in _decode_roles(raw):
                    return
            except DirectoryRecordError:
                continue
        raise AccountsError("last_admin")

    def resend_invite(
        self, caller: Caller, operation_id: UUID, org_id: str, actor_id: str
    ) -> Outcome[None]:
        acting, tenant = self._require_org_admin(caller, org_id)
        actor = ActorId.parse(actor_id)
        action = "resend_invite"
        rhash = request_hash(action, tenant.value, {"actor_id": actor_id})
        with self._engine.begin() as conn:
            self._audit.lock_tenant_on_connection(conn, tenant.value)
            self._recheck(conn, caller, acting, tenant.value)
            org = self._existing_org(conn, tenant)
            replay = self._replay(conn, tenant.value, operation_id, caller, action, rhash)
            if replay is not None:
                return Outcome(replay.status, None)
            member = None if actor is None else self._member_view(conn, tenant.value, actor.value)
            if member is None or member.email is None or actor is None:
                raise AccountsError("not_found")
            if not org.active:
                raise AccountsError("organization_inactive")
            if not member.active:
                raise AccountsError("member_inactive")
            if member.invite_status == "accepted":
                raise AccountsError("invite_already_accepted")
        if self._auth_admin is None:
            raise AuthAdminError("misconfigured")
        now = self._clock()
        try:
            with self._engine.begin() as conn:
                self._audit.lock_tenant_on_connection(conn, tenant.value)
                self._recheck(conn, caller, acting, tenant.value)
                current_org = self._existing_org(conn, tenant)
                current_member = self._member_view(conn, tenant.value, actor.value)
                if not current_org.active:
                    raise AccountsError("organization_inactive")
                if current_member is None or not current_member.active:
                    raise AccountsError("member_inactive")
                if current_member.invite_status == "accepted":
                    raise AccountsError("invite_already_accepted")
                self._auth_admin.resend_invite(member.email, self._redirect)
        except InviteAlreadyAccepted:
            with self._engine.begin() as conn:
                self._audit.lock_tenant_on_connection(conn, tenant.value)
                self._recheck(conn, caller, acting, tenant.value)
                result = conn.execute(
                    directory_accounts.update()
                    .where(
                        directory_accounts.c.tenant_id == tenant.value,
                        directory_accounts.c.actor_id == actor.value,
                        directory_accounts.c.invite_status == "pending",
                    )
                    .values(invite_status="accepted", accepted_at=now)
                )
                if result.rowcount == 1:
                    self._event(
                        conn,
                        tenant.value,
                        acting,
                        action="invite_accepted",
                        organization_id=tenant.value,
                        target_actor_id=actor.value,
                    )
            raise AccountsError("invite_already_accepted") from None
        with self._engine.begin() as conn:
            self._audit.lock_tenant_on_connection(conn, tenant.value)
            self._recheck(conn, caller, acting, tenant.value)
            replay = self._replay(conn, tenant.value, operation_id, caller, action, rhash)
            if replay is not None:
                return Outcome(replay.status, None)
            event_id = self._event(
                conn,
                tenant.value,
                acting,
                action="invite_resent",
                organization_id=tenant.value,
                target_actor_id=actor.value,
                operation_id=operation_id,
                request_hash=rhash,
            )
            self._remember(
                conn,
                tenant.value,
                operation_id,
                caller,
                action,
                rhash,
                actor.value,
                202,
                event_id,
                now,
            )
        return Outcome(202, None)
