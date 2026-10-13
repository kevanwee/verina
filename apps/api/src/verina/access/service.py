"""Matter application service: the single authorization boundary for matter work (ADR 003).

Every public method:

1. re-resolves the caller through the trusted identity adapter (roles and deactivation are
   current, never cached from an earlier request or job submission);
2. reads the matter's *access* record only, using the principal's tenant as the key;
3. asks :class:`MatterAccessPolicy` for a decision;
4. emits an :class:`AccessAuditEvent` (allow or deny; never content) and fails closed if the
   sink fails;
5. only after an allow reads content, mutates, or calls the review runner (the orchestrator
   port).

Methods take no tenant or actor argument: those come from the :class:`Principal` only.
Denials raise :class:`AccessDenied` carrying a disclosable reason code; a matter that does not
exist and one the caller may not see raise the identical error.
"""

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from verina.access.domain import (
    Action,
    ActorId,
    ActorProfile,
    ConflictCheckRecord,
    ConflictStatus,
    ConflictWaiver,
    Decision,
    DenialDetail,
    MatterAccess,
    MatterContent,
    MatterDocument,
    MatterId,
    MatterRecord,
    ReasonCode,
    TenantId,
    conflict_is_ready,
    is_utc_time,
    profile_matches,
)
from verina.access.identity import IdentityAdapter, Principal
from verina.access.mutations import (
    MutationReceipt,
    MutationReplayError,
    SqlMatterMutationUnitOfWork,
    request_hash,
)
from verina.access.policy import POLICY_VERSION, MatterAccessPolicy
from verina.access.repository import MatterRepository, MatterRevisionConflictError
from verina.ai.audit import AuditEmissionError, AuditSink
from verina.ai.client import UntrustedDocument
from verina.audit.events import AccessAuditEvent
from verina.audit.store import TenantAuditSink

logger = logging.getLogger(__name__)


class AccessDenied(Exception):  # noqa: N818 - domain vocabulary
    """The action was refused. ``reason_code`` is safe to return to the caller."""

    def __init__(self, reason_code: ReasonCode) -> None:
        self.reason_code = reason_code
        super().__init__(f"access denied: {reason_code.value}")


@dataclass(frozen=True, slots=True)
class MatterSummary:
    matter_id: MatterId
    title: str
    conflict_status: ConflictStatus


@dataclass(frozen=True, slots=True)
class MatterStatus:
    """Requester-safe status; no titles, documents, ledger, conflict details or waiver reasons."""

    matter_id: MatterId
    status: str


@dataclass(frozen=True, slots=True)
class ModelContext:
    """What the orchestrator receives for a matter. Built only after authorization."""

    tenant_id: TenantId
    matter_id: MatterId
    actor_id: ActorId
    documents: tuple[UntrustedDocument, ...]


@dataclass(frozen=True, slots=True)
class ReviewJob:
    """A queued review. Holds identifiers only; authority is re-checked at execution."""

    job_id: UUID
    tenant_id: TenantId
    actor_id: ActorId
    matter_id: MatterId


@dataclass(frozen=True, slots=True)
class Attestation:
    """A lawyer's attestation of one ledger entry . Persisting it is ledger work."""

    matter_id: MatterId
    entry_id: str
    attested_by: ActorId
    reason: str
    attested_at: datetime


@dataclass(frozen=True, slots=True)
class ExportClearance:
    matter_id: MatterId
    cleared_for: ActorId
    cleared_at: datetime


@runtime_checkable
class ReviewRunner(Protocol):
    """Port to the AI orchestrator. The adapter must call ``Orchestrator.run`` only."""

    async def run(self, context: ModelContext) -> str: ...


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MatterService:
    def __init__(
        self,
        *,
        repository: MatterRepository,
        policy: MatterAccessPolicy,
        identity: IdentityAdapter,
        audit_sink: AuditSink,
        review_runner: ReviewRunner,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        mutation_uow: SqlMatterMutationUnitOfWork | None = None,
    ) -> None:
        if mutation_uow is not None and (
            mutation_uow.repository is not repository
            or not isinstance(audit_sink, TenantAuditSink)
            or audit_sink._store is not mutation_uow.audit
        ):
            raise ValueError("durable mutation composition requires matching repository and audit")
        self._uow = mutation_uow
        self._repo = repository
        self._policy = policy
        self._identity = identity
        self._sink = audit_sink
        self._runner = review_runner
        self._clock = clock

    async def create_matter(
        self,
        principal: Principal,
        title: str,
        *,
        operation_id: UUID | None = None,
        expected_revision: int | None = None,
    ) -> MatterId:
        """Local/test synthetic foundation. Creator membership only; no HTTP wiring."""
        if not isinstance(title, str) or not 0 < len(title.strip()) <= 200:
            raise ValueError("invalid title")
        token = self._token(operation_id, expected_revision)
        fingerprint = request_hash(Action.CREATE_MATTER, None, title.strip())
        replay = await self._replay(
            principal, Action.CREATE_MATTER, token, fingerprint, None, expected_revision
        )
        if replay is not None:
            return replay.matter_id
        principal = await self._authorize_collection(principal, Action.CREATE_MATTER)
        self._profile(principal)
        if self._uow is None:
            self._expect(expected_revision, 0)
        matter_id = (
            MatterId(
                str(
                    uuid5(
                        NAMESPACE_URL, f"verina:{principal.tenant_id}:{principal.actor_id}:{token}"
                    )
                )
            )
            if self._uow
            else MatterId(str(uuid4()))
        )
        await self._emit(principal, Action.CREATE_MATTER, matter_id.value, Decision.allow())
        principal = await self._recheck_collection(principal, Action.CREATE_MATTER)
        self._profile(principal)
        record = MatterRecord(
            MatterAccess(principal.tenant_id, matter_id, members=frozenset({principal.actor_id})),
            MatterContent(title.strip()),
        )
        if self._uow:
            return self._commit(
                principal,
                Action.CREATE_MATTER,
                token,
                fingerprint,
                record,
                None,
                requested_revision=expected_revision,
            ).matter_id
        self._repo.add(principal.tenant_id, record)
        return matter_id

    async def record_conflict_check(
        self,
        principal: Principal,
        matter_id: str,
        result: ConflictStatus,
        *,
        operation_id: UUID | None = None,
        expected_revision: int | None = None,
    ) -> ConflictCheckRecord:
        """Record a lawyer's synthetic result, replacing and invalidating any old waiver."""
        if type(result) is not ConflictStatus or result not in {
            ConflictStatus.CLEAR,
            ConflictStatus.CONFLICT,
        }:
            raise ValueError("invalid conflict result")
        token = self._token(operation_id, expected_revision)
        fingerprint = request_hash(Action.RECORD_CONFLICT_CHECK, matter_id, result.value)
        replay = await self._replay(
            principal,
            Action.RECORD_CONFLICT_CHECK,
            token,
            fingerprint,
            matter_id,
            expected_revision,
        )
        if replay is not None:
            if replay.result_access.conflict_check is None:
                raise MutationReplayError()
            return replay.result_access.conflict_check
        principal, access = await self._authorize(
            principal, Action.RECORD_CONFLICT_CHECK, matter_id
        )
        if self._uow is None:
            self._expect(expected_revision, access.revision)
        profile = self._profile(principal)
        previous = access.conflict_check
        if previous is not None and (
            not isinstance(previous, ConflictCheckRecord)
            or type(previous.version) is not int
            or previous.version <= 0
        ):
            raise ValueError("invalid conflict record")
        version = previous.version + 1 if previous is not None else 1
        check = ConflictCheckRecord(
            access.matter_id, result, principal.actor_id, self._utc_now(), version, profile
        )
        record = self._content(principal, access)
        new_access = replace(
            access,
            conflict_status=result,
            conflict_recorded_by=principal.actor_id,
            conflict_check=check,
            waiver=None,
        )
        if self._uow:
            result_access = self._commit(
                principal,
                Action.RECORD_CONFLICT_CHECK,
                token,
                fingerprint,
                replace(record, access=new_access),
                access,
                requested_revision=expected_revision,
            )
            if result_access.conflict_check is None:
                raise MutationReplayError()
            return result_access.conflict_check
        self._persist(principal, replace(record, access=new_access))
        return check

    def _token(self, operation_id: UUID | None, expected_revision: int | None) -> UUID:
        if self._uow is None and (operation_id is not None or expected_revision is not None):
            raise ValueError("durable mutation port required")
        if operation_id is not None and not isinstance(operation_id, UUID):
            raise ValueError("invalid operation id")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 0
        ):
            raise MutationReplayError()
        return operation_id or uuid4()

    @staticmethod
    def _expect(expected: int | None, actual: int) -> None:
        if expected is not None and expected != actual:
            raise AccessDenied(ReasonCode.MATTER_CHANGED)

    async def _replay(
        self,
        principal: Principal,
        action: Action,
        token: UUID,
        fingerprint: str,
        matter_id: str | None,
        expected_revision: int | None,
        *,
        reason: str | None = None,
    ) -> MutationReceipt | None:
        if self._uow is None:
            return None
        principal = await self._refresh(principal, action, matter_id)
        receipt = self._uow.peek(principal.tenant_id, token)
        if receipt is None:
            return None
        if (
            receipt.actor_id != principal.actor_id
            or receipt.action is not action
            or (matter_id is not None and receipt.matter_id != MatterId.parse(matter_id))
        ):
            raise MutationReplayError()
        if action is Action.CREATE_MATTER:
            principal = await self._authorize_collection(principal, action)
            self._profile(principal)
            principal, access = await self._authorize(
                principal, Action.READ_STATUS, receipt.matter_id.value
            )
            await self._emit(principal, action, receipt.matter_id.value, Decision.allow())
            principal, access = await self._authorize(
                principal, Action.READ_STATUS, receipt.matter_id.value
            )
        else:
            principal, access = await self._authorize(
                principal, action, receipt.matter_id.value, reason=reason, completed_replay=True
            )
        self._uow.validate_replay(
            receipt,
            principal,
            action,
            receipt.matter_id,
            fingerprint,
            receipt.expected_revision if expected_revision is None else expected_revision,
        )
        try:
            receipt = self._uow.load_authorized(
                principal.tenant_id,
                token,
                access,
                self._mutation_authorizer(principal, action, reason),
            )
        except MatterRevisionConflictError:
            raise AccessDenied(ReasonCode.CONFLICT_CHANGED) from None
        if action in {Action.RECORD_CONFLICT_CHECK, Action.WAIVE_CONFLICT} and (
            access.conflict_check,
            access.waiver,
            access.conflict_status,
        ) != (
            receipt.result_access.conflict_check,
            receipt.result_access.waiver,
            receipt.result_access.conflict_status,
        ):
            await self._emit(
                principal,
                action,
                receipt.matter_id.value,
                Decision.deny(ReasonCode.CONFLICT_CHANGED),
            )
            raise AccessDenied(ReasonCode.CONFLICT_CHANGED)
        return receipt

    def _commit(
        self,
        principal: Principal,
        action: Action,
        token: UUID,
        fingerprint: str,
        record: MatterRecord,
        expected_access: MatterAccess | None,
        *,
        reason: str | None = None,
        requested_revision: int | None = None,
    ) -> MatterAccess:
        if self._uow is None:
            raise ValueError("durable mutation port required")

        try:
            return self._uow.put(
                principal,
                action,
                token,
                fingerprint,
                record,
                expected_access,
                self._mutation_authorizer(principal, action, reason),
                requested_revision=requested_revision,
            ).result_access
        except MatterRevisionConflictError:
            raise AccessDenied(ReasonCode.MATTER_CHANGED) from None

    def _mutation_authorizer(
        self, principal: Principal, action: Action, reason: str | None
    ) -> Callable[[MatterAccess | None, bool], None]:
        def authorize(access: MatterAccess | None, replayed: bool) -> None:
            current = self._identity.current(principal.tenant_id, principal.actor_id)
            if current is None:
                raise AccessDenied(ReasonCode.UNAUTHENTICATED)
            decision = self._named_decision(
                current,
                action,
                self._policy.decide(
                    current, action, access, reason=reason, completed_replay=replayed
                ),
            )
            if not decision.allowed:
                raise AccessDenied(decision.reason_code)
            if replayed and action is Action.CREATE_MATTER:
                visibility = self._policy.decide(current, Action.READ_STATUS, access)
                if not visibility.allowed:
                    raise AccessDenied(visibility.reason_code)

        return authorize

    def _named_decision(self, principal: Principal, action: Action, decision: Decision) -> Decision:
        if decision.allowed and action in {
            Action.CREATE_MATTER,
            Action.RECORD_CONFLICT_CHECK,
            Action.WAIVE_CONFLICT,
        }:
            profile = self._identity.profile(principal.tenant_id, principal.actor_id)
            if not profile_matches(profile, principal.tenant_id, principal.actor_id):
                return Decision.deny(ReasonCode.PROFILE_REQUIRED)
        return decision

    def _profile(self, principal: Principal) -> ActorProfile:
        profile = self._identity.profile(principal.tenant_id, principal.actor_id)
        if not profile_matches(profile, principal.tenant_id, principal.actor_id):
            raise AccessDenied(ReasonCode.PROFILE_REQUIRED)
        if profile is None:
            raise AccessDenied(ReasonCode.PROFILE_REQUIRED)
        return profile

    def _utc_now(self) -> datetime:
        now = self._clock()
        if not is_utc_time(now):
            raise ValueError("invalid clock")
        return now

    # ------------------------------------------------------------------ reads

    async def get_matter(self, principal: Principal, matter_id: str) -> MatterRecord:
        principal, access = await self._authorize(principal, Action.READ_MATTER, matter_id)
        return self._content(principal, access)

    async def get_matter_status(self, principal: Principal, matter_id: str) -> MatterStatus:
        _, access = await self._authorize(principal, Action.READ_STATUS, matter_id)
        status = "ready" if conflict_is_ready(access) else "awaiting_clearance"
        return MatterStatus(access.matter_id, status)

    async def list_matters(self, principal: Principal) -> list[MatterSummary]:
        principal = await self._authorize_collection(principal, Action.LIST_MATTERS)
        records = self._repo.list(principal.tenant_id, visible=self._visible_to(principal))
        await self._audit_collection(principal, Action.LIST_MATTERS, len(records))
        principal = await self._recheck_collection(principal, Action.LIST_MATTERS)
        return [
            _summary(r)
            for r in self._repo.list(principal.tenant_id, visible=self._visible_to(principal))
        ]

    async def count_matters(self, principal: Principal) -> int:
        principal = await self._authorize_collection(principal, Action.LIST_MATTERS)
        count = self._repo.count(principal.tenant_id, visible=self._visible_to(principal))
        await self._audit_collection(principal, Action.LIST_MATTERS, count)
        principal = await self._recheck_collection(principal, Action.LIST_MATTERS)
        return self._repo.count(principal.tenant_id, visible=self._visible_to(principal))

    async def search_matters(self, principal: Principal, text: str) -> list[MatterSummary]:
        principal = await self._authorize_collection(principal, Action.SEARCH)
        records = self._repo.search(principal.tenant_id, text, visible=self._visible_to(principal))
        await self._audit_collection(principal, Action.SEARCH, len(records))
        principal = await self._recheck_collection(principal, Action.SEARCH)
        return [
            _summary(r)
            for r in self._repo.search(
                principal.tenant_id, text, visible=self._visible_to(principal)
            )
        ]

    # -------------------------------------------------------------- mutations

    async def update_title(
        self,
        principal: Principal,
        matter_id: str,
        title: str,
        *,
        operation_id: UUID | None = None,
        expected_revision: int | None = None,
    ) -> None:
        if not title.strip():
            raise ValueError("title required")
        token = self._token(operation_id, expected_revision)
        fingerprint = request_hash(Action.UPDATE_MATTER, matter_id, title.strip())
        if (
            await self._replay(
                principal, Action.UPDATE_MATTER, token, fingerprint, matter_id, expected_revision
            )
            is not None
        ):
            return
        principal, access = await self._authorize(principal, Action.UPDATE_MATTER, matter_id)
        if self._uow is None:
            self._expect(expected_revision, access.revision)
        record = self._content(principal, access)
        new = replace(record, content=replace(record.content, title=title.strip()))
        if self._uow:
            self._commit(
                principal,
                Action.UPDATE_MATTER,
                token,
                fingerprint,
                new,
                access,
                requested_revision=expected_revision,
            )
        else:
            self._persist(principal, new)

    async def delete_matter(self, principal: Principal, matter_id: str) -> None:
        if self._uow:
            raise ValueError("delete outcome is not integrated")
        principal, access = await self._authorize(principal, Action.DELETE_MATTER, matter_id)
        if not self._repo.delete(
            principal.tenant_id, access.matter_id, expected_revision=access.revision
        ):
            raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)

    async def grant_membership(
        self, principal: Principal, matter_id: str, target_actor: str
    ) -> None:
        if self._uow:
            raise ValueError("membership outcome is not integrated")
        target = ActorId.parse(target_actor)
        principal, access = await self._authorize(
            principal, Action.MANAGE_MEMBERSHIP, matter_id, target_actor=target
        )
        if target is None:
            raise AccessDenied(ReasonCode.TARGET_REQUIRED)
        record = self._content(principal, access)
        self._persist(
            principal, replace(record, access=replace(access, members=access.members | {target}))
        )

    async def waive_conflict(
        self,
        principal: Principal,
        matter_id: str,
        reason: str,
        *,
        operation_id: UUID | None = None,
        expected_revision: int | None = None,
    ) -> ConflictWaiver:
        """Member-lawyer waiver: any lawyer with matter membership, mandatory reason, audited."""
        token = self._token(operation_id, expected_revision)
        if not isinstance(reason, str):
            raise ValueError("invalid reason")
        fingerprint = request_hash(Action.WAIVE_CONFLICT, matter_id, reason.strip())
        replay = await self._replay(
            principal,
            Action.WAIVE_CONFLICT,
            token,
            fingerprint,
            matter_id,
            expected_revision,
            reason=reason,
        )
        if replay is not None:
            if replay.result_access.waiver is None:
                raise MutationReplayError()
            return replay.result_access.waiver
        principal, access = await self._authorize(
            principal, Action.WAIVE_CONFLICT, matter_id, reason=reason
        )
        if self._uow is None:
            self._expect(expected_revision, access.revision)
        profile = self._profile(principal)
        check = access.conflict_check
        if check is None:
            raise AccessDenied(ReasonCode.CONFLICT_NOT_WAIVABLE)
        now = self._utc_now()
        if now < check.recorded_at:
            raise ValueError("invalid clock")
        waiver = ConflictWaiver(
            matter_id=access.matter_id,
            check_version=check.version,
            actor_profile=profile,
            waived_by=principal.actor_id,
            reason=reason.strip(),
            waived_at=now,
            same_actor_as_conflict_recorder=access.conflict_recorded_by == principal.actor_id,
        )
        record = self._content(principal, access)
        new_access = replace(access, conflict_status=ConflictStatus.WAIVED, waiver=waiver)
        if self._uow:
            result_access = self._commit(
                principal,
                Action.WAIVE_CONFLICT,
                token,
                fingerprint,
                replace(record, access=new_access),
                access,
                reason=reason,
                requested_revision=expected_revision,
            )
            if result_access.waiver is None:
                raise MutationReplayError()
            return result_access.waiver
        self._persist(principal, replace(record, access=new_access))
        return waiver

    async def attest_entry(
        self, principal: Principal, matter_id: str, entry_id: str, reason: str
    ) -> Attestation:
        """Member lawyers may attest with a reason. Durable ledger writes are later work."""
        if not entry_id.strip():
            raise ValueError("entry_id required")
        principal, access = await self._authorize(
            principal, Action.ATTEST_ENTRY, matter_id, reason=reason
        )
        return Attestation(
            matter_id=access.matter_id,
            entry_id=entry_id.strip(),
            attested_by=principal.actor_id,
            reason=reason.strip(),
            attested_at=self._clock(),
        )

    async def export_to_client(self, principal: Principal, matter_id: str) -> ExportClearance:
        """Server-side export gate. The export artefact itself is later work."""
        principal, access = await self._authorize(principal, Action.EXPORT_TO_CLIENT, matter_id)
        return ExportClearance(access.matter_id, principal.actor_id, self._clock())

    async def authorize_tenant_administration(self, principal: Principal) -> None:
        principal = await self._refresh(principal, Action.MANAGE_TENANT, None)
        decision = self._policy.decide(principal, Action.MANAGE_TENANT, None)
        await self._emit(principal, Action.MANAGE_TENANT, None, decision)
        if not decision.allowed:
            raise AccessDenied(decision.reason_code)

    # ------------------------------------------------------------ model work

    async def build_model_context(self, principal: Principal, matter_id: str) -> ModelContext:
        principal, access = await self._authorize(principal, Action.BUILD_MODEL_CONTEXT, matter_id)
        return self._model_context(principal, access)

    async def submit_review(self, principal: Principal, matter_id: str) -> ReviewJob:
        principal, access = await self._authorize(principal, Action.REVIEW, matter_id)
        return ReviewJob(uuid4(), principal.tenant_id, principal.actor_id, access.matter_id)

    async def execute_review(self, job: ReviewJob) -> str:
        """Run a queued review. Authority is re-evaluated now, not trusted from submission."""
        current = self._identity.current(job.tenant_id, job.actor_id)
        if current is None:
            await self._emit_inactive(job.tenant_id, job.actor_id, Action.REVIEW, job.matter_id)
            raise AccessDenied(ReasonCode.UNAUTHENTICATED)
        principal, access = await self._authorize(current, Action.REVIEW, job.matter_id.value)
        context = self._model_context(principal, access)
        result = await self._runner.run(context)
        # Long-running review can outlive role, membership or conflict authority.
        # Discard output if the actor no longer has access at the return boundary.
        await self._authorize(principal, Action.REVIEW, job.matter_id.value)
        return result

    # -------------------------------------------------------------- internals

    def _visible_to(self, principal: Principal) -> Callable[[MatterAccess], bool]:
        def visible(access: MatterAccess) -> bool:
            return self._policy.decide(principal, Action.READ_MATTER, access).allowed

        return visible

    async def _refresh(
        self, principal: Principal, action: Action, matter_id: str | None
    ) -> Principal:
        if not isinstance(principal, Principal):
            raise AccessDenied(ReasonCode.UNAUTHENTICATED)
        current = self._identity.current(principal.tenant_id, principal.actor_id)
        if current is None:
            await self._emit_inactive(principal.tenant_id, principal.actor_id, action, matter_id)
            raise AccessDenied(ReasonCode.UNAUTHENTICATED)
        return current

    async def _authorize(
        self,
        principal: Principal,
        action: Action,
        matter_id: object,
        *,
        reason: str | None = None,
        target_actor: ActorId | None = None,
        completed_replay: bool = False,
    ) -> tuple[Principal, MatterAccess]:
        parsed = MatterId.parse(matter_id)
        requested = parsed.value if parsed is not None else None  # never log raw input
        principal = await self._refresh(principal, action, requested)
        access = self._repo.get_access(principal.tenant_id, parsed) if parsed else None
        decision = self._policy.decide(
            principal,
            action,
            access,
            reason=reason,
            target_actor=target_actor,
            completed_replay=completed_replay,
        )
        decision = self._named_decision(principal, action, decision)
        same_actor = (
            access.conflict_recorded_by == principal.actor_id
            if action is Action.WAIVE_CONFLICT and access is not None and decision.allowed
            else None
        )
        await self._emit(
            principal,
            action,
            requested,
            decision,
            reason_sha256=_sha256(reason.strip()) if reason and decision.allowed else None,
            same_actor=same_actor,
        )
        if not decision.allowed:
            raise AccessDenied(decision.reason_code)
        if access is None:
            raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)
        # Audit persistence yields to other tasks. Re-read all authority after it returns;
        # no await is allowed between this final check and the in-memory operation.
        current = self._identity.current(principal.tenant_id, principal.actor_id)
        if current is None:
            await self._emit_inactive(principal.tenant_id, principal.actor_id, action, requested)
            raise AccessDenied(ReasonCode.UNAUTHENTICATED)
        fresh = self._repo.get_access(current.tenant_id, parsed) if parsed else None
        final = self._policy.decide(
            current,
            action,
            fresh,
            reason=reason,
            target_actor=target_actor,
            completed_replay=completed_replay,
        )
        final = self._named_decision(current, action, final)
        if (
            final.allowed
            and action in {Action.WAIVE_CONFLICT, Action.RECORD_CONFLICT_CHECK}
            and access is not None
            and fresh is not None
            and (fresh.conflict_check, fresh.conflict_status, fresh.waiver)
            != (access.conflict_check, access.conflict_status, access.waiver)
        ):
            final = Decision.deny(ReasonCode.CONFLICT_CHANGED)
        if not final.allowed:
            await self._emit(current, action, requested, final)
            raise AccessDenied(final.reason_code)
        if fresh is None:
            raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)
        return current, fresh

    async def _authorize_collection(self, principal: Principal, action: Action) -> Principal:
        principal = await self._refresh(principal, action, None)
        decision = self._named_decision(
            principal, action, self._policy.decide(principal, action, None)
        )
        if not decision.allowed:
            await self._emit(principal, action, None, decision)
            raise AccessDenied(decision.reason_code)
        return principal

    async def _recheck_collection(self, principal: Principal, action: Action) -> Principal:
        # Called after the audit await. Return current identity then synchronously re-query.
        current = self._identity.current(principal.tenant_id, principal.actor_id)
        if current is None:
            await self._emit_inactive(principal.tenant_id, principal.actor_id, action, None)
            raise AccessDenied(ReasonCode.UNAUTHENTICATED)
        decision = self._named_decision(current, action, self._policy.decide(current, action, None))
        if not decision.allowed:
            await self._emit(current, action, None, decision)
            raise AccessDenied(decision.reason_code)
        return current

    async def _audit_collection(self, principal: Principal, action: Action, count: int) -> None:
        await self._emit(principal, action, None, Decision.allow(), result_count=count)

    def _content(self, principal: Principal, access: MatterAccess) -> MatterRecord:
        try:
            record = self._repo.get(principal.tenant_id, access.matter_id, expected_access=access)
        except MatterRevisionConflictError:
            raise AccessDenied(ReasonCode.MATTER_CHANGED) from None
        if record is None:  # deleted between authorization and read
            raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)
        if record.access != access:
            raise AccessDenied(ReasonCode.MATTER_CHANGED)
        return record

    def _model_context(self, principal: Principal, access: MatterAccess) -> ModelContext:
        record = self._content(principal, access)
        return ModelContext(
            tenant_id=principal.tenant_id,
            matter_id=record.matter_id,
            actor_id=principal.actor_id,
            documents=_untrusted(record.content.documents),
        )

    def _persist(self, principal: Principal, record: MatterRecord) -> None:
        if not self._repo.update(principal.tenant_id, record):
            raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)

    async def _emit_inactive(
        self, tenant_id: TenantId, actor_id: ActorId, action: Action, matter_id: object
    ) -> None:
        decision = Decision.deny(ReasonCode.UNAUTHENTICATED, DenialDetail.PRINCIPAL_INACTIVE)
        await self._send(
            AccessAuditEvent(
                occurred_at=self._clock(),
                tenant_id=tenant_id.value,
                actor=actor_id.value,
                action=action.value,
                matter_id=str(matter_id) if matter_id is not None else None,
                decision="deny",
                reason_code=decision.reason_code.value,
                detail_code=decision.detail.value if decision.detail else None,
                policy_version=POLICY_VERSION,
            )
        )

    async def _emit(
        self,
        principal: Principal,
        action: Action,
        matter_id: str | None,
        decision: Decision,
        *,
        reason_sha256: str | None = None,
        same_actor: bool | None = None,
        result_count: int | None = None,
    ) -> None:
        await self._send(
            AccessAuditEvent(
                occurred_at=self._clock(),
                tenant_id=principal.tenant_id.value,
                actor=principal.actor_id.value,
                action=action.value,
                matter_id=matter_id,
                decision="allow" if decision.allowed else "deny",
                reason_code=decision.reason_code.value,
                detail_code=decision.detail.value if decision.detail else None,
                policy_version=POLICY_VERSION,
                reason_sha256=reason_sha256,
                same_actor_as_conflict_recorder=same_actor,
                result_count=result_count,
            )
        )

    async def _send(self, event: AccessAuditEvent) -> None:
        try:
            await self._sink.emit(event)
        except Exception as exc:
            logger.error("access audit emission failed for event %s", event.event_id)
            raise AuditEmissionError("audit sink rejected the access audit event") from exc
        logger.info(
            "access.decision event=%s actor=%s action=%s decision=%s reason=%s",
            event.event_id,
            event.actor,
            event.action,
            event.decision,
            event.reason_code,
        )


def _summary(record: MatterRecord) -> MatterSummary:
    return MatterSummary(record.matter_id, record.content.title, record.access.conflict_status)


def _untrusted(documents: Sequence[MatterDocument]) -> tuple[UntrustedDocument, ...]:
    return tuple(
        UntrustedDocument(document_id=d.document_id, title=d.title, text=d.text) for d in documents
    )
