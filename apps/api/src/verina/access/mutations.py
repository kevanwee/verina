"""Same-database atomic matter mutation, completion audit and protected retry receipt."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Connection,
    ForeignKey,
    Row,
    String,
    Table,
    Text,
    select,
)

from verina.access.domain import (
    Action,
    ActorId,
    ConflictStatus,
    MatterAccess,
    MatterId,
    MatterRecord,
    TenantId,
    is_utc_time,
)
from verina.access.identity import Principal
from verina.access.repository import MatterRevisionConflictError
from verina.access.sql_repository import SqlMatterRepository, matters, metadata
from verina.access.storage_codec import (
    StoredMatterError,
    decode_access,
    encode_access,
    encode_content,
)
from verina.audit.chain import event_hash, hash_material
from verina.audit.events import MatterMutationCompleted
from verina.audit.schema import audit_events
from verina.audit.store import SqlAuditStore
from verina.db import require_bound_connection

SUPPORTED = frozenset(
    {
        Action.CREATE_MATTER,
        Action.UPDATE_MATTER,
        Action.RECORD_CONFLICT_CHECK,
        Action.WAIVE_CONFLICT,
    }
)
receipts = Table(
    "matter_mutation_receipts",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("operation_id", String(36), primary_key=True),
    Column("actor_id", String(128), nullable=False),
    Column("action", String(40), nullable=False),
    Column("matter_id", String(128), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("expected_revision", BigInteger, nullable=False),
    Column("result_revision", BigInteger, nullable=False),
    Column(
        "event_id", String(36), ForeignKey(audit_events.c.event_id), nullable=False, unique=True
    ),
    Column("result_access_json", Text, nullable=False),
    CheckConstraint(
        "expected_revision >= 0 AND result_revision = expected_revision + 1",
        name="ck_receipt_revision_step",
    ),
)


class MutationReplayError(RuntimeError):
    """A token cannot be reused for a different intent or an invalid receipt."""

    def __init__(self) -> None:
        super().__init__("mutation replay conflict")


@dataclass(frozen=True, slots=True)
class MutationToken:
    operation_id: UUID
    actor_id: ActorId
    action: Action
    matter_id: MatterId
    request_hash: str
    expected_revision: int
    result_revision: int
    event_id: UUID


@dataclass(frozen=True, slots=True)
class MutationReceipt(MutationToken):
    result_access: MatterAccess


def request_hash(action: Action, target: str | None, value: str) -> str:
    """Bounded normalized command fingerprint, never raw input in audit or receipts."""
    return hashlib.sha256(
        json.dumps(
            [action.value, target, value], separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _state_hash(record: MatterRecord) -> str:
    return hashlib.sha256(
        (encode_access(record.access) + "\n" + encode_content(record.content)).encode()
    ).hexdigest()


class SqlMatterMutationUnitOfWork:
    def __init__(
        self,
        repository: SqlMatterRepository,
        audit: SqlAuditStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if repository._engine is not audit._engine:
            raise ValueError("matter and audit must share one engine")
        self.repository = repository
        self.audit = audit
        self._clock = clock

    def _check(
        self,
        authorize: Callable[[MatterAccess | None, bool], None],
        current: MatterAccess | None,
        replayed: bool,
    ) -> None:
        """Run the service authorizer; identity reads must use this mutation's transaction."""
        with require_bound_connection(self.repository._engine):
            authorize(current, replayed)

    def _metadata(self, conn: Connection, row: Row[Any]) -> tuple[MutationToken, str]:
        try:
            if (
                type(row.expected_revision) is not int
                or row.expected_revision < 0
                or type(row.result_revision) is not int
                or row.result_revision != row.expected_revision + 1
            ):
                raise MutationReplayError()
            event_row = conn.execute(
                select(audit_events).where(
                    audit_events.c.tenant_id == row.tenant_id,
                    audit_events.c.event_id == row.event_id,
                )
            ).one_or_none()
            if event_row is None or len(event_row.payload) > 100_000:
                raise MutationReplayError()
            data = json.loads(event_row.payload)
            payload = MatterMutationCompleted.model_validate(data)
            material = hash_material(
                schema_version=event_row.schema_version,
                tenant_id=event_row.tenant_id,
                sequence=event_row.sequence,
                event_id=event_row.event_id,
                event_type=event_row.event_type,
                actor=event_row.actor,
                matter_id=event_row.matter_id,
                payload=data,
                created_at=event_row.created_at,
                prev_hash=event_row.prev_hash,
            )
            if (
                event_hash(material) != event_row.hash
                or event_row.event_type != "matter.mutation_completed"
            ):
                raise MutationReplayError()
            if (
                payload.tenant_id,
                payload.actor,
                payload.action,
                payload.matter_id,
                str(payload.operation_id),
                payload.request_hash,
                payload.expected_revision,
                payload.result_revision,
                str(payload.event_id),
            ) != (
                row.tenant_id,
                row.actor_id,
                row.action,
                row.matter_id,
                row.operation_id,
                row.request_hash,
                row.expected_revision,
                row.result_revision,
                row.event_id,
            ):
                raise MutationReplayError()
            if event_row.actor != row.actor_id or event_row.matter_id != row.matter_id:
                raise MutationReplayError()
            action = Action(row.action)
            if action not in SUPPORTED:
                raise MutationReplayError()
            TenantId(row.tenant_id)
            token = MutationToken(
                UUID(row.operation_id),
                ActorId(row.actor_id),
                action,
                MatterId(row.matter_id),
                row.request_hash,
                row.expected_revision,
                row.result_revision,
                UUID(row.event_id),
            )
            return token, payload.result_access_hash
        except (ValueError, TypeError, RecursionError):
            raise MutationReplayError() from None

    def _decode(self, conn: Connection, row: Row[Any]) -> MutationReceipt:
        try:
            token, expected_hash = self._metadata(conn, row)
            access = decode_access(
                row.result_access_json,
                TenantId(row.tenant_id),
                token.matter_id,
                token.result_revision,
            )
            if hashlib.sha256(encode_access(access).encode()).hexdigest() != expected_hash:
                raise MutationReplayError()
            return MutationReceipt(
                token.operation_id,
                token.actor_id,
                token.action,
                token.matter_id,
                token.request_hash,
                token.expected_revision,
                token.result_revision,
                token.event_id,
                access,
            )
        except (ValueError, TypeError, StoredMatterError, RecursionError):
            raise MutationReplayError() from None

    def peek(self, tenant: TenantId, operation_id: UUID) -> MutationToken | None:
        """Verified metadata only; never select protected historical retry facts."""
        if not isinstance(tenant, TenantId) or not isinstance(operation_id, UUID):
            raise MutationReplayError()
        columns = [column for column in receipts.c if column.name != "result_access_json"]
        with self.repository._transaction() as conn:
            row = conn.execute(
                select(*columns).where(
                    receipts.c.tenant_id == tenant.value,
                    receipts.c.operation_id == str(operation_id),
                )
            ).first()
            return self._metadata(conn, row)[0] if row else None

    def lookup(self, tenant: TenantId, operation_id: UUID) -> MutationReceipt | None:
        if not isinstance(tenant, TenantId) or not isinstance(operation_id, UUID):
            raise MutationReplayError()
        with self.repository._transaction() as conn:
            row = conn.execute(
                select(receipts).where(
                    receipts.c.tenant_id == tenant.value,
                    receipts.c.operation_id == str(operation_id),
                )
            ).first()
            return self._decode(conn, row) if row else None

    def load_authorized(
        self,
        tenant: TenantId,
        operation_id: UUID,
        expected_access: MatterAccess,
        authorize: Callable[[MatterAccess | None, bool], None],
    ) -> MutationReceipt:
        """Revalidate the authorized DB snapshot before selecting protected retry facts."""
        with self.repository._transaction() as conn:
            self.audit.lock_tenant_on_connection(conn, tenant.value)
            columns = [column for column in receipts.c if column.name != "result_access_json"]
            row = conn.execute(
                select(*columns).where(
                    receipts.c.tenant_id == tenant.value,
                    receipts.c.operation_id == str(operation_id),
                )
            ).one_or_none()
            if row is None:
                raise MutationReplayError()
            token, _ = self._metadata(conn, row)
            current_row = conn.execute(
                select(matters.c.access_json, matters.c.revision)
                .where(self.repository._key(tenant, token.matter_id))
                .with_for_update(read=True)
            ).one_or_none()
            current = (
                decode_access(
                    current_row.access_json, tenant, token.matter_id, current_row.revision
                )
                if current_row
                else None
            )
            if current is None or current != expected_access:
                raise MatterRevisionConflictError("matter changed")
            self._check(authorize, current, True)
            full = conn.execute(
                select(receipts).where(
                    receipts.c.tenant_id == tenant.value,
                    receipts.c.operation_id == str(operation_id),
                )
            ).one()
            receipt = self._decode(conn, full)
            if token.action in {Action.RECORD_CONFLICT_CHECK, Action.WAIVE_CONFLICT} and (
                current.conflict_check,
                current.waiver,
                current.conflict_status,
            ) != (
                receipt.result_access.conflict_check,
                receipt.result_access.waiver,
                receipt.result_access.conflict_status,
            ):
                raise MatterRevisionConflictError("conflict changed")
            return receipt

    @staticmethod
    def validate_replay(
        receipt: MutationToken,
        principal: Principal,
        action: Action,
        target: MatterId,
        fingerprint: str,
        expected_revision: int,
    ) -> None:
        if type(expected_revision) is not int or (
            receipt.actor_id,
            receipt.action,
            receipt.matter_id,
            receipt.request_hash,
            receipt.expected_revision,
        ) != (principal.actor_id, action, target, fingerprint, expected_revision):
            raise MutationReplayError()

    def put(
        self,
        principal: Principal,
        action: Action,
        operation_id: UUID,
        fingerprint: str,
        record: MatterRecord,
        expected_access: MatterAccess | None,
        authorize: Callable[[MatterAccess | None, bool], None],
        *,
        requested_revision: int | None = None,
    ) -> MutationReceipt:
        if requested_revision is not None and (
            type(requested_revision) is not int or requested_revision < 0
        ):
            raise MutationReplayError()
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            raise MutationReplayError()
        if (
            action not in SUPPORTED
            or not isinstance(operation_id, UUID)
            or record.tenant_id != principal.tenant_id
        ):
            raise MutationReplayError()
        expected_revision = 0 if action is Action.CREATE_MATTER else record.access.revision
        if (
            type(expected_revision) is not int
            or expected_revision < 0
            or (action is not Action.CREATE_MATTER and expected_revision < 1)
        ):
            raise MutationReplayError()
        after = (
            record
            if action is Action.CREATE_MATTER
            else replace(record, access=replace(record.access, revision=expected_revision + 1))
        )
        access_json, content_json = encode_access(after.access), encode_content(after.content)
        snapshot = replace(after.access, members=frozenset(), walled=frozenset())
        if action in {Action.CREATE_MATTER, Action.UPDATE_MATTER}:
            snapshot = replace(
                snapshot,
                conflict_status=ConflictStatus.PENDING,
                conflict_check=None,
                conflict_recorded_by=None,
                waiver=None,
            )
        snapshot_json = encode_access(snapshot)
        now = self._clock()
        if not is_utc_time(now):
            raise ValueError("invalid mutation clock")
        with self.repository._transaction() as conn:
            self.audit.lock_tenant_on_connection(conn, principal.tenant_id.value)
            existing = conn.execute(
                select(
                    *[column for column in receipts.c if column.name != "result_access_json"]
                ).where(
                    receipts.c.tenant_id == principal.tenant_id.value,
                    receipts.c.operation_id == str(operation_id),
                )
            ).first()
            row = conn.execute(
                select(matters.c.access_json, matters.c.revision)
                .where(self.repository._key(principal.tenant_id, record.matter_id))
                .with_for_update()
            ).first()
            current = (
                decode_access(row.access_json, principal.tenant_id, record.matter_id, row.revision)
                if row
                else None
            )
            if existing:
                token, _ = self._metadata(conn, existing)
                self.validate_replay(
                    token,
                    principal,
                    action,
                    record.matter_id,
                    fingerprint,
                    token.expected_revision if requested_revision is None else requested_revision,
                )
                self._check(authorize, current, True)
                full = conn.execute(
                    select(receipts).where(
                        receipts.c.tenant_id == principal.tenant_id.value,
                        receipts.c.operation_id == str(operation_id),
                    )
                ).one()
                receipt = self._decode(conn, full)
                if action in {Action.RECORD_CONFLICT_CHECK, Action.WAIVE_CONFLICT} and (
                    current is None
                    or (current.conflict_check, current.waiver, current.conflict_status)
                    != (
                        receipt.result_access.conflict_check,
                        receipt.result_access.waiver,
                        receipt.result_access.conflict_status,
                    )
                ):
                    raise MatterRevisionConflictError("conflict changed")
                return receipt
            self._check(authorize, current, False)
            if requested_revision is not None and requested_revision != expected_revision:
                raise MatterRevisionConflictError("matter changed")
            before_hash = None
            if action is Action.CREATE_MATTER:
                if current is not None or after.access.revision != 1:
                    raise MatterRevisionConflictError("matter changed")
                conn.execute(
                    matters.insert().values(
                        tenant_id=principal.tenant_id.value,
                        matter_id=record.matter_id.value,
                        revision=1,
                        access_json=access_json,
                        content_json=content_json,
                    )
                )
            else:
                if (
                    current is None
                    or current != expected_access
                    or current.revision != expected_revision
                ):
                    raise MatterRevisionConflictError("matter changed")
                # Authorized access is validated before selecting/decoding prior content.
                before_hash = _state_hash(self.repository._content(conn, current))
                changed = conn.execute(
                    matters.update()
                    .where(
                        self.repository._key(principal.tenant_id, record.matter_id),
                        matters.c.revision == expected_revision,
                    )
                    .values(
                        revision=after.access.revision,
                        access_json=access_json,
                        content_json=content_json,
                    )
                )
                if changed.rowcount != 1:
                    raise MatterRevisionConflictError("matter changed")
            payload = MatterMutationCompleted(
                occurred_at=now,
                tenant_id=principal.tenant_id.value,
                actor=principal.actor_id.value,
                matter_id=record.matter_id.value,
                operation_id=operation_id,
                action=cast(Any, action.value),
                expected_revision=expected_revision,
                result_revision=after.access.revision,
                expected_check_version=current.conflict_check.version
                if current and current.conflict_check
                else None,
                request_hash=fingerprint,
                before_hash=before_hash,
                after_hash=_state_hash(after),
                result_access_hash=hashlib.sha256(snapshot_json.encode()).hexdigest(),
            )
            self.audit.append_on_connection(conn, principal.tenant_id.value, payload)
            conn.execute(
                receipts.insert().values(
                    tenant_id=principal.tenant_id.value,
                    operation_id=str(operation_id),
                    actor_id=principal.actor_id.value,
                    action=action.value,
                    matter_id=record.matter_id.value,
                    request_hash=fingerprint,
                    expected_revision=expected_revision,
                    result_revision=after.access.revision,
                    event_id=str(payload.event_id),
                    result_access_json=snapshot_json,
                )
            )
            receipt = MutationReceipt(
                operation_id,
                principal.actor_id,
                action,
                record.matter_id,
                fingerprint,
                expected_revision,
                after.access.revision,
                payload.event_id,
                snapshot,
            )
        return receipt
