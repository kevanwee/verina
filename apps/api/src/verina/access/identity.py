"""Trusted identity adapter (ADR 003).

A :class:`Principal` is the only source of tenant, actor and roles for an authorization
decision. It is issued by an :class:`IdentityAdapter` from a credential; tenant/actor/role
values in route parameters, bodies, headers or frontend state are never read.

No identity vendor is selected. :class:`InMemoryIdentityAdapter` maps synthetic opaque tokens
to principals for tests and local development; an OIDC adapter can replace it behind the same
protocol once the identity-provider decision is made.
"""

import hmac
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from verina.access.domain import ActorId, ActorProfile, Role, TenantId, _issue_profile

_ISSUER = object()


class AuthenticationError(Exception):
    """Missing, malformed, unknown or revoked credential. Its message carries no detail.

    ``reason`` is an internal failure class for the audit chain (``missing_credential``,
    ``token_rejected``, ``unbound``, ``principal_inactive``, ``organization_inactive`` ...);
    ``subject`` is the verified ``(issuer, subject)`` when the token itself was valid. Neither
    is ever returned to the caller; audit records only a keyed HMAC of the subject.
    """

    def __init__(
        self, reason: str = "unauthenticated", subject: tuple[str, str] | None = None
    ) -> None:
        super().__init__("unauthenticated")
        self.reason = reason
        self.subject = subject


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated actor. Construct only through an identity adapter."""

    tenant_id: TenantId
    actor_id: ActorId
    roles: frozenset[Role]
    _issuer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issuer is not _ISSUER:
            raise TypeError("Principal must be issued by a trusted IdentityAdapter")
        if not isinstance(self.tenant_id, TenantId) or not isinstance(self.actor_id, ActorId):
            raise TypeError("Principal requires TenantId and ActorId values")

    def has_any(self, roles: Iterable[Role]) -> bool:
        return not self.roles.isdisjoint(roles)


def _issue(tenant_id: TenantId, actor_id: ActorId, roles: Iterable[Role]) -> Principal:
    return Principal(tenant_id, actor_id, frozenset(Role(r) for r in roles), _ISSUER)


@runtime_checkable
class IdentityAdapter(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        """Resolve a principal from the credential only. Raise :class:`AuthenticationError`."""
        ...

    def profile(self, tenant_id: TenantId, actor_id: ActorId) -> ActorProfile | None:
        """Retrieve a trusted identity binding, retained after deactivation."""
        ...

    def current(self, tenant_id: TenantId, actor_id: ActorId) -> Principal | None:
        """Return the principal's *current* state (roles may have changed), or ``None`` if
        the actor was deactivated. Used to re-evaluate queued work at execution time."""
        ...


@dataclass(slots=True)
class _Account:
    tenant_id: TenantId
    actor_id: ActorId
    roles: frozenset[Role]
    active: bool = True


class InMemoryIdentityAdapter:
    """Synthetic bearer tokens to principals. Tests and local development only.

    Only the ``Authorization: Bearer <token>`` header is read. Any ``X-Tenant-Id``,
    ``X-Actor-Id``, ``X-Roles`` or similar header is ignored by construction.
    """

    def __init__(self) -> None:
        self._profiles: dict[tuple[TenantId, ActorId], ActorProfile] = {}
        self._by_token: dict[str, tuple[TenantId, ActorId]] = {}
        self._accounts: dict[tuple[TenantId, ActorId], _Account] = {}

    def register(
        self,
        token: str,
        tenant_id: str,
        actor_id: str,
        roles: Iterable[Role | str],
        *,
        display_name: str | None = None,
    ) -> Principal:
        if not token:
            raise ValueError("token required")
        key = (TenantId(tenant_id), ActorId(actor_id))
        if display_name is not None:
            self._profiles[key] = _issue_profile(*key, display_name)
        self._accounts[key] = _Account(*key, roles=frozenset(Role(r) for r in roles))
        self._by_token[token] = key
        principal = self.current(*key)
        if principal is None:
            raise AuthenticationError()
        return principal

    def profile(self, tenant_id: TenantId, actor_id: ActorId) -> ActorProfile | None:
        return self._profiles.get((tenant_id, actor_id))

    def set_roles(self, tenant_id: TenantId, actor_id: ActorId, roles: Iterable[Role]) -> None:
        self._accounts[(tenant_id, actor_id)].roles = frozenset(roles)

    def deactivate(self, tenant_id: TenantId, actor_id: ActorId) -> None:
        self._accounts[(tenant_id, actor_id)].active = False

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        value = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError()
        presented = token.strip().encode("utf-8")
        key = next(
            (
                k
                for t, k in self._by_token.items()
                if hmac.compare_digest(t.encode("utf-8"), presented)
            ),
            None,
        )
        principal = self.current(*key) if key is not None else None
        if principal is None:
            raise AuthenticationError()
        return principal

    def current(self, tenant_id: TenantId, actor_id: ActorId) -> Principal | None:
        account = self._accounts.get((tenant_id, actor_id))
        if account is None or not account.active:
            return None
        return _issue(account.tenant_id, account.actor_id, account.roles)
