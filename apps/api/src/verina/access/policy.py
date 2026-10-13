"""Matter access policy (ADR 003, docs/security/ACCESS_MATRIX.md).

``MatterAccessPolicy.decide`` is deterministic, side-effect free and deny-by-default. It
evaluates, in order:

1. the action has a role grant at all (deny by default);
2. tenant-level actions (``manage_tenant``, unscoped ``list_matters``/``search``): role only;
3. matter visibility: exists in the caller's tenant, caller not behind an ethical wall,
   caller is a member. Every failure here returns the *same* ``matter_not_accessible`` code;
4. a role held by the caller grants the action (tenant administration grants no content);
5. self-escalation (membership changes targeting the caller);
6. the conflict gate (independent of membership);
7. a mandatory reason for waivers and attestations;
8. the ledger export gate, via an injected :class:`LedgerStatusProvider` (fails closed).

Role grants for waiver and attestation implement the member-lawyer policy.
Other grants marked "proposed" are engineering proposals.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol, runtime_checkable

from verina.access.domain import (
    Action,
    ActorId,
    ConflictStatus,
    Decision,
    DenialDetail,
    MatterAccess,
    MatterId,
    ReasonCode,
    Role,
    TenantId,
)
from verina.access.identity import Principal

POLICY_VERSION = "2026-10-13.2"

_CONTENT_READERS = frozenset({Role.LAWYER, Role.PARTNER, Role.KNOWLEDGE})
_LAWYERS = frozenset({Role.LAWYER, Role.PARTNER})

GRANTS: Mapping[Action, frozenset[Role]] = {
    Action.READ_MATTER: _CONTENT_READERS,
    Action.READ_STATUS: _CONTENT_READERS | {Role.REQUESTER},
    Action.LIST_MATTERS: _CONTENT_READERS,
    Action.SEARCH: _CONTENT_READERS,
    Action.UPDATE_MATTER: _LAWYERS,
    Action.DELETE_MATTER: frozenset({Role.PARTNER}),
    Action.BUILD_MODEL_CONTEXT: _LAWYERS,
    Action.REVIEW: _LAWYERS,
    Action.WAIVE_CONFLICT: _LAWYERS,  # Member-lawyer waiver: any lawyer with matter membership
    Action.ATTEST_ENTRY: _LAWYERS,  # Member-lawyer attestation: any lawyer on the matter
    Action.EXPORT_TO_CLIENT: _LAWYERS,
    Action.MANAGE_MEMBERSHIP: frozenset({Role.PARTNER}),
    Action.MANAGE_TENANT: frozenset({Role.TENANT_ADMIN}),
}
"""Which roles may perform each action. An action missing here is denied to everyone."""

TENANT_ACTIONS = frozenset({Action.MANAGE_TENANT})
"""Actions that never concern a matter; a matter argument is ignored."""

COLLECTION_ACTIONS = frozenset({Action.LIST_MATTERS, Action.SEARCH})
"""Without a matter: may the caller list/search at all. With a matter: may it appear."""

CONFLICT_GATED = frozenset(
    {Action.BUILD_MODEL_CONTEXT, Action.REVIEW, Action.ATTEST_ENTRY, Action.EXPORT_TO_CLIENT}
)
CONFLICT_CLEARED = frozenset({ConflictStatus.CLEAR, ConflictStatus.WAIVED})
REASON_REQUIRED = frozenset({Action.WAIVE_CONFLICT, Action.ATTEST_ENTRY})
MAX_REASON_LENGTH = 2000


class LedgerEntryStatus(StrEnum):
    VERIFIED = "verified"
    ATTESTED = "attested"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


EXPORT_RESOLVED = frozenset({LedgerEntryStatus.VERIFIED, LedgerEntryStatus.ATTESTED})
"""Only verified or lawyer-attested entries may reach a client (AGENTS.md)."""


@runtime_checkable
class LedgerStatusProvider(Protocol):
    """Read-only view of a matter's Verification Ledger (the ledger itself is later work)."""

    def entry_status_counts(
        self, tenant_id: TenantId, matter_id: MatterId
    ) -> Mapping[LedgerEntryStatus, int]: ...


class InMemoryLedgerStatus:
    """Synthetic ledger status per matter. Unknown matters raise rather than certify readiness."""

    def __init__(self) -> None:
        self._counts: dict[tuple[TenantId, MatterId], dict[LedgerEntryStatus, int]] = {}

    def set(
        self, tenant_id: TenantId, matter_id: MatterId, counts: Mapping[LedgerEntryStatus, int]
    ) -> None:
        self._counts[(tenant_id, matter_id)] = dict(counts)

    def entry_status_counts(
        self, tenant_id: TenantId, matter_id: MatterId
    ) -> Mapping[LedgerEntryStatus, int]:
        return dict(self._counts[(tenant_id, matter_id)])


def reason_is_valid(reason: str | None) -> bool:
    return reason is not None and 0 < len(reason.strip()) <= MAX_REASON_LENGTH


class MatterAccessPolicy:
    def __init__(self, ledger: LedgerStatusProvider) -> None:
        self._ledger = ledger

    def decide(
        self,
        principal: Principal,
        action: Action,
        matter: MatterAccess | None,
        *,
        reason: str | None = None,
        target_actor: ActorId | None = None,
    ) -> Decision:
        if not isinstance(principal, Principal):
            return Decision.deny(ReasonCode.UNAUTHENTICATED)
        granted = GRANTS.get(action, frozenset())
        role_ok = principal.has_any(granted)

        if action in TENANT_ACTIONS or (action in COLLECTION_ACTIONS and matter is None):
            return Decision.allow() if role_ok else Decision.deny(ReasonCode.ROLE_NOT_PERMITTED)

        visibility = self._visibility(principal, matter)
        if visibility is not None:
            return Decision.deny(ReasonCode.MATTER_NOT_ACCESSIBLE, visibility)
        if matter is None:
            return Decision.deny(ReasonCode.MATTER_NOT_ACCESSIBLE)

        if not role_ok:
            return Decision.deny(ReasonCode.ROLE_NOT_PERMITTED)

        if action is Action.MANAGE_MEMBERSHIP:
            if target_actor is None:
                return Decision.deny(ReasonCode.TARGET_REQUIRED)
            if target_actor == principal.actor_id:
                return Decision.deny(ReasonCode.SELF_ESCALATION)

        if action in CONFLICT_GATED and matter.conflict_status not in CONFLICT_CLEARED:
            return Decision.deny(ReasonCode.CONFLICT_NOT_CLEARED)
        if (
            action is Action.WAIVE_CONFLICT
            and matter.conflict_status is not ConflictStatus.CONFLICT
        ):
            return Decision.deny(ReasonCode.CONFLICT_NOT_WAIVABLE)

        if action in REASON_REQUIRED and not reason_is_valid(reason):
            return Decision.deny(ReasonCode.REASON_REQUIRED)

        if action is Action.EXPORT_TO_CLIENT:
            return self._export_gate(matter)

        return Decision.allow()

    @staticmethod
    def _visibility(principal: Principal, matter: MatterAccess | None) -> DenialDetail | None:
        if matter is None:
            return DenialDetail.MATTER_NOT_FOUND
        if matter.tenant_id != principal.tenant_id:
            return DenialDetail.TENANT_MISMATCH
        if principal.actor_id in matter.walled:
            return DenialDetail.ETHICAL_WALL
        if principal.actor_id not in matter.members:
            return DenialDetail.NOT_MEMBER
        return None

    def _export_gate(self, matter: MatterAccess) -> Decision:
        try:
            counts = self._ledger.entry_status_counts(matter.tenant_id, matter.matter_id)
            # Empty/unknown data is not evidence that the complete ledger was checked.
            # An explicitly checked empty ledger uses a known status with a zero count.
            if not isinstance(counts, Mapping) or not counts:
                raise ValueError("ledger coverage unavailable")
            normalized = {LedgerEntryStatus(status): n for status, n in counts.items()}
            if any(type(n) is not int or n < 0 for n in normalized.values()):
                raise ValueError("invalid ledger counts")
            unresolved = any(
                n > 0 for status, n in normalized.items() if status not in EXPORT_RESOLVED
            )
        except Exception:
            return Decision.deny(ReasonCode.LEDGER_STATUS_UNAVAILABLE)
        if unresolved:
            return Decision.deny(ReasonCode.LEDGER_UNRESOLVED)
        return Decision.allow()
