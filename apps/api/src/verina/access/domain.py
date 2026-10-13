"""Immutable access-domain values (ADR 003).

Composition, not inheritance: a principal holds a set of roles, a matter holds a membership
set, an ethical-wall set and a conflict status. Each changes independently.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Self

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class InvalidIdentifierError(ValueError):
    """An identifier is empty, too long or contains unexpected characters."""


@dataclass(frozen=True, slots=True)
class _Identifier:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _ID_PATTERN.fullmatch(self.value):
            raise InvalidIdentifierError(f"invalid {type(self).__name__}")

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, raw: object) -> Self | None:
        """Return the identifier, or ``None`` if ``raw`` is not a valid one (never raises)."""
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str):
            return None
        try:
            return cls(raw)
        except InvalidIdentifierError:
            return None


@dataclass(frozen=True, slots=True)
class TenantId(_Identifier):
    """A customer firm or in-house team. Only the trusted identity adapter assigns it."""


@dataclass(frozen=True, slots=True)
class ActorId(_Identifier):
    """A user or service principal inside a tenant."""


@dataclass(frozen=True, slots=True)
class MatterId(_Identifier):
    """An opaque matter identifier. Unique within a tenant."""


class Role(StrEnum):
    LAWYER = "lawyer"
    PARTNER = "partner"
    REQUESTER = "requester"
    TENANT_ADMIN = "tenant_admin"
    KNOWLEDGE = "knowledge"


class Action(StrEnum):
    CREATE_MATTER = "create_matter"
    RECORD_CONFLICT_CHECK = "record_conflict_check"
    READ_MATTER = "read_matter"
    READ_STATUS = "read_status"
    LIST_MATTERS = "list_matters"
    SEARCH = "search"
    UPDATE_MATTER = "update_matter"
    DELETE_MATTER = "delete_matter"
    BUILD_MODEL_CONTEXT = "build_model_context"
    REVIEW = "review"
    WAIVE_CONFLICT = "waive_conflict"
    ATTEST_ENTRY = "attest_entry"
    EXPORT_TO_CLIENT = "export_to_client"
    MANAGE_MEMBERSHIP = "manage_membership"
    MANAGE_TENANT = "manage_tenant"


class ConflictStatus(StrEnum):
    PENDING = "pending"
    """No conflict result recorded yet. Review and model work are blocked."""
    CLEAR = "clear"
    CONFLICT = "conflict"
    """A conflict hit was recorded. Blocked until a member lawyer waives it ."""
    WAIVED = "waived"


class ReasonCode(StrEnum):
    """Reason codes that may be returned to the caller.

    ``MATTER_NOT_ACCESSIBLE`` is deliberately the same for a matter that does not exist, belongs
    to another tenant, sits behind an ethical wall or has no membership for the caller, so
    responses never disclose existence.
    """

    PROFILE_REQUIRED = "profile_required"
    ALLOWED = "allowed"
    UNAUTHENTICATED = "unauthenticated"
    MATTER_NOT_ACCESSIBLE = "matter_not_accessible"
    ROLE_NOT_PERMITTED = "role_not_permitted"
    SELF_ESCALATION = "self_escalation"
    TARGET_REQUIRED = "target_required"
    MATTER_CHANGED = "matter_changed"
    CONFLICT_CHANGED = "conflict_changed"
    CONFLICT_NOT_CLEARED = "conflict_not_cleared"
    CONFLICT_NOT_WAIVABLE = "conflict_not_waivable"
    REASON_REQUIRED = "reason_required"
    LEDGER_UNRESOLVED = "ledger_unresolved"
    LEDGER_STATUS_UNAVAILABLE = "ledger_status_unavailable"


class DenialDetail(StrEnum):
    """Internal diagnostic behind ``MATTER_NOT_ACCESSIBLE``. Audit only; never returned."""

    MATTER_NOT_FOUND = "matter_not_found"
    TENANT_MISMATCH = "tenant_mismatch"
    ETHICAL_WALL = "ethical_wall"
    NOT_MEMBER = "not_member"
    PRINCIPAL_INACTIVE = "principal_inactive"


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason_code: ReasonCode
    detail: DenialDetail | None = None

    @classmethod
    def allow(cls) -> "Decision":
        return cls(True, ReasonCode.ALLOWED)

    @classmethod
    def deny(cls, reason: ReasonCode, detail: DenialDetail | None = None) -> "Decision":
        return cls(False, reason, detail)


_PROFILE_ISSUER = object()


@dataclass(frozen=True, slots=True)
class ActorProfile:
    """Trusted synthetic identity snapshot; presentation never grants authority."""

    tenant_id: TenantId
    actor_id: ActorId
    display_name: str
    _issuer: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, TenantId) or not isinstance(self.actor_id, ActorId):
            raise TypeError("profile requires typed identity")
        if self._issuer is not _PROFILE_ISSUER:
            raise TypeError("profile must be issued by the identity adapter")
        if not isinstance(self.display_name, str) or not 0 < len(self.display_name.strip()) <= 120:
            raise ValueError("invalid profile")
        if any(ord(c) < 32 for c in self.display_name):
            raise ValueError("invalid profile")


def _issue_profile(tenant: TenantId, actor: ActorId, name: str) -> ActorProfile:
    return ActorProfile(tenant, actor, name.strip(), _PROFILE_ISSUER)


def profile_matches(profile: object, tenant: TenantId, actor: ActorId) -> bool:
    return (
        isinstance(profile, ActorProfile)
        and isinstance(profile.tenant_id, TenantId)
        and isinstance(profile.actor_id, ActorId)
        and profile._issuer is _PROFILE_ISSUER
        and profile.tenant_id == tenant
        and profile.actor_id == actor
        and isinstance(profile.display_name, str)
        and 0 < len(profile.display_name.strip()) <= 120
        and not any(ord(c) < 32 for c in profile.display_name)
    )


def is_utc_time(value: object) -> bool:
    from datetime import timedelta

    return isinstance(value, datetime) and value.utcoffset() == timedelta(0)


@dataclass(frozen=True, slots=True)
class ConflictCheckRecord:
    """A recorded synthetic lawyer result, not an automated conflicts search."""

    matter_id: MatterId
    result: ConflictStatus
    recorded_by: ActorId
    recorded_at: datetime
    version: int
    recorder_profile: ActorProfile


@dataclass(frozen=True, slots=True)
class ConflictWaiver:
    """A named, reasoned waiver of a recorded conflict hit (member-lawyer policy)."""

    matter_id: MatterId
    check_version: int
    actor_profile: ActorProfile
    waived_by: ActorId
    reason: str
    waived_at: datetime
    same_actor_as_conflict_recorder: bool
    """Surfaced at sign-off as a compensating control; does not block (PO decides)."""


@dataclass(frozen=True, slots=True)
class MatterAccess:
    """The access-control facts of a matter. Contains no matter content.

    The service reads this record, decides, and only then reads :class:`MatterContent`.
    """

    tenant_id: TenantId
    matter_id: MatterId
    members: frozenset[ActorId] = field(default_factory=frozenset)
    walled: frozenset[ActorId] = field(default_factory=frozenset)
    """Actors screened from this matter. Overrides membership and every role."""
    conflict_status: ConflictStatus = ConflictStatus.PENDING
    conflict_recorded_by: ActorId | None = None
    waiver: ConflictWaiver | None = None
    conflict_check: ConflictCheckRecord | None = None
    revision: int = 1
    """Optimistic storage revision, independent of the conflict-check version."""


@dataclass(frozen=True, slots=True)
class MatterDocument:
    document_id: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class MatterContent:
    title: str
    documents: tuple[MatterDocument, ...] = ()


@dataclass(frozen=True, slots=True)
class MatterRecord:
    access: MatterAccess
    content: MatterContent

    @property
    def tenant_id(self) -> TenantId:
        return self.access.tenant_id

    @property
    def matter_id(self) -> MatterId:
        return self.access.matter_id


def conflict_record_is_valid(matter: MatterAccess) -> bool:
    check = matter.conflict_check
    return (
        isinstance(check, ConflictCheckRecord)
        and isinstance(check.matter_id, MatterId)
        and check.matter_id == matter.matter_id
        and type(check.result) is ConflictStatus
        and check.result in {ConflictStatus.CLEAR, ConflictStatus.CONFLICT}
        and isinstance(check.recorded_by, ActorId)
        and check.recorded_by == matter.conflict_recorded_by
        and is_utc_time(check.recorded_at)
        and type(check.version) is int
        and check.version > 0
        and profile_matches(check.recorder_profile, matter.tenant_id, check.recorded_by)
        and (
            matter.conflict_status is check.result
            or (
                matter.conflict_status is ConflictStatus.WAIVED
                and check.result is ConflictStatus.CONFLICT
            )
        )
    )


def conflict_is_ready(matter: MatterAccess) -> bool:
    if not conflict_record_is_valid(matter):
        return False
    check = matter.conflict_check
    if check is None:
        return False
    if matter.conflict_status is ConflictStatus.CLEAR:
        return matter.waiver is None
    waiver = matter.waiver
    return (
        matter.conflict_status is ConflictStatus.WAIVED
        and isinstance(waiver, ConflictWaiver)
        and isinstance(waiver.matter_id, MatterId)
        and waiver.matter_id == matter.matter_id
        and type(waiver.check_version) is int
        and waiver.check_version == check.version
        and isinstance(waiver.waived_by, ActorId)
        and profile_matches(waiver.actor_profile, matter.tenant_id, waiver.waived_by)
        and is_utc_time(waiver.waived_at)
        and waiver.waived_at >= check.recorded_at
        and isinstance(waiver.reason, str)
        and 0 < len(waiver.reason.strip()) <= 2000
        and type(waiver.same_actor_as_conflict_recorder) is bool
        and waiver.same_actor_as_conflict_recorder == (waiver.waived_by == check.recorded_by)
    )
