"""Durable, append-only, hash-chained audit store (EN-8, NFR-6, AI-4). See ADR 004.

Writes
    :meth:`SqlAuditStore.append` is the only write path. In one transaction it locks the
    tenant's chain head (``BEGIN IMMEDIATE`` on SQLite, ``SELECT ... FOR UPDATE`` on
    PostgreSQL), checks the head still matches the stored chain tip, inserts event
    ``last_sequence + 1`` linked to the previous hash, and advances the head. Concurrent
    appends therefore serialise per tenant and cannot fork the chain; the
    ``(tenant_id, sequence)`` primary key is a second barrier. There are no update or delete
    methods, and database triggers reject UPDATE/DELETE/TRUNCATE.

Reads
    :meth:`SqlAuditStore.verify_chain` recomputes every hash and link for a tenant and
    compares the tip against the head checkpoint (and its HMAC when a key is configured).
    :meth:`SqlAuditStore.dangling_calls` lists model calls with a start record but no
    completion record.

Tenant binding
    The orchestrator's :class:`~verina.ai.audit.AuditSink` has no tenant argument. A sink for
    one tenant comes from :meth:`SqlAuditStore.for_tenant`; the application service that has
    authorised the caller (ADR 003) decides the tenant, never client input.
"""

import asyncio
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Engine, Row, select
from sqlalchemy.dialects import postgresql, sqlite

from verina.audit.chain import (
    GENESIS_HASH,
    event_hash,
    hash_material,
    head_mac,
    verify_head_mac,
)
from verina.audit.events import (
    MAX_IDENTIFIER,
    AIAuditEvent,
    AIModelCallStarted,
    AuditEvent,
    AuditPayload,
    AuditPayloadError,
    payload_to_json,
    validate_payload,
)
from verina.audit.schema import audit_chain_head, audit_events
from verina.config import Settings
from verina.db import make_engine

SCHEMA_VERSION = 1


class AuditIntegrityError(RuntimeError):
    """The stored chain no longer matches its head; appends are refused (fail closed)."""


IssueKind = Literal[
    "hash_mismatch",
    "chain_break",
    "sequence_gap",
    "payload_invalid",
    "head_missing",
    "head_mismatch",
    "head_mac_invalid",
]


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    kind: IssueKind
    sequence: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    tenant_id: str
    event_count: int
    head_sequence: int | None
    head_hash: str | None
    head_mac_checked: bool
    issues: tuple[IntegrityIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.issues

    def kinds(self) -> set[str]:
        return {issue.kind for issue in self.issues}


@dataclass(frozen=True, slots=True)
class DanglingCall:
    """A model call that was started but never recorded a completion (AI-4)."""

    call_id: UUID
    sequence: int
    matter_id: str
    actor: str
    task_role: str
    model_id: str
    started_at: datetime


def _check_identifier(name: str, value: str) -> None:
    if not value or len(value) > MAX_IDENTIFIER:
        raise AuditPayloadError(f"{name} must be 1-{MAX_IDENTIFIER} characters")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlAuditStore:
    def __init__(
        self,
        engine: Engine,
        *,
        head_key: bytes | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        dialect = engine.dialect.name
        if dialect not in ("sqlite", "postgresql"):
            raise ValueError(f"unsupported audit database dialect {dialect!r}")
        if head_key is not None and len(head_key) < 32:
            raise ValueError("audit head key must be at least 32 bytes")
        self._engine = engine
        self._head_key = head_key
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Settings) -> "SqlAuditStore":
        """Store on ``VERINA_DATABASE_URL`` with the optional ``VERINA_AUDIT_HEAD_KEY``."""
        key = settings.audit_head_key
        return cls(
            make_engine(settings.database_url),
            head_key=key.get_secret_value().encode("utf-8") if key is not None else None,
        )

    # ---- writes ------------------------------------------------------------------------

    def append(self, tenant_id: str, payload: BaseModel) -> AuditEvent:
        """Append one payload in an owned transaction."""
        with self._engine.begin() as conn:
            return self.append_on_connection(conn, tenant_id, payload)

    def _require_connection(self, conn: Connection) -> None:
        if conn.engine is not self._engine or not conn.in_transaction():
            raise ValueError("audit append requires its active engine transaction")

    def lock_tenant_on_connection(self, conn: Connection, tenant_id: str) -> None:
        """Acquire the chain lock before operation/matter writes in shared transactions."""
        self._require_connection(conn)
        _check_identifier("tenant_id", tenant_id)
        self._lock_head(conn, tenant_id)

    def append_on_connection(
        self, conn: Connection, tenant_id: str, payload: BaseModel
    ) -> AuditEvent:
        """Append inside a caller-owned active transaction; never commit independently."""
        self._require_connection(conn)
        _check_identifier("tenant_id", tenant_id)
        data = payload_to_json(payload)
        if data.get("tenant_id", tenant_id) != tenant_id:
            raise AuditPayloadError("payload tenant does not match bound sink tenant")
        event_type = data["event_type"]
        actor = data["actor"]
        matter_id = data.get("matter_id")
        _check_identifier("actor", actor)
        if matter_id is not None:
            _check_identifier("matter_id", matter_id)
        event_id = str(data["event_id"])
        created_at = _as_utc(self._clock())

        last_sequence, last_hash = self._lock_head(conn, tenant_id)
        sequence = last_sequence + 1
        material = hash_material(
            schema_version=SCHEMA_VERSION,
            tenant_id=tenant_id,
            sequence=sequence,
            event_id=event_id,
            event_type=event_type,
            actor=actor,
            matter_id=matter_id,
            payload=data,
            created_at=created_at,
            prev_hash=last_hash,
        )
        digest = event_hash(material)
        conn.execute(
            audit_events.insert().values(
                tenant_id=tenant_id,
                sequence=sequence,
                event_id=event_id,
                schema_version=SCHEMA_VERSION,
                event_type=event_type,
                actor=actor,
                matter_id=matter_id,
                payload=json.dumps(data, sort_keys=True, separators=(",", ":")),
                created_at=created_at,
                prev_hash=last_hash,
                hash=digest,
            )
        )
        conn.execute(
            audit_chain_head.update()
            .where(audit_chain_head.c.tenant_id == tenant_id)
            .values(
                last_sequence=sequence,
                last_hash=digest,
                head_mac=self._mac(tenant_id, sequence, digest),
                updated_at=created_at,
            )
        )
        return AuditEvent(
            tenant_id=tenant_id,
            sequence=sequence,
            event_id=UUID(event_id),
            event_type=event_type,
            actor=actor,
            matter_id=matter_id,
            payload=data,
            created_at=created_at,
            prev_hash=last_hash,
            hash=digest,
        )

    def _lock_head(self, conn: Connection, tenant_id: str) -> tuple[int, str]:
        """Create the tenant's head if needed, lock it, and check it matches the chain tip."""
        insert = postgresql.insert if self._engine.dialect.name == "postgresql" else sqlite.insert
        conn.execute(
            insert(audit_chain_head)
            .values(
                tenant_id=tenant_id,
                last_sequence=0,
                last_hash=GENESIS_HASH,
                head_mac=self._mac(tenant_id, 0, GENESIS_HASH),
                updated_at=_as_utc(self._clock()),
            )
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )
        head = conn.execute(
            select(audit_chain_head)
            .where(audit_chain_head.c.tenant_id == tenant_id)
            .with_for_update()
        ).one()
        last_sequence = int(head.last_sequence)
        last_hash = str(head.last_hash)
        if self._head_key is not None and not verify_head_mac(
            self._head_key,
            head.head_mac,
            tenant_id=tenant_id,
            last_sequence=last_sequence,
            last_hash=last_hash,
        ):
            raise AuditIntegrityError("audit chain head failed its MAC check; append refused")
        tip = conn.execute(
            select(audit_events.c.sequence, audit_events.c.hash)
            .where(audit_events.c.tenant_id == tenant_id)
            .order_by(audit_events.c.sequence.desc())
            .limit(1)
        ).first()
        tip_state = (0, GENESIS_HASH) if tip is None else (int(tip.sequence), str(tip.hash))
        if tip_state != (last_sequence, last_hash):
            raise AuditIntegrityError("audit chain tip does not match its head; append refused")
        return last_sequence, last_hash

    def _mac(self, tenant_id: str, sequence: int, digest: str) -> str | None:
        if self._head_key is None:
            return None
        return head_mac(
            self._head_key, tenant_id=tenant_id, last_sequence=sequence, last_hash=digest
        )

    def for_tenant(self, tenant_id: str) -> "TenantAuditSink":
        _check_identifier("tenant_id", tenant_id)
        return TenantAuditSink(self, tenant_id)

    # ---- reads -------------------------------------------------------------------------

    def _rows(self, tenant_id: str, event_types: Iterable[str] | None = None) -> list[Row[Any]]:
        query = select(audit_events).where(audit_events.c.tenant_id == tenant_id)
        if event_types is not None:
            query = query.where(audit_events.c.event_type.in_(list(event_types)))
        with self._engine.connect() as conn:
            return list(conn.execute(query.order_by(audit_events.c.sequence)).all())

    @staticmethod
    def _to_event(row: Row[Any]) -> AuditEvent:
        return AuditEvent(
            schema_version=row.schema_version,
            tenant_id=row.tenant_id,
            sequence=row.sequence,
            event_id=UUID(row.event_id),
            event_type=row.event_type,
            actor=row.actor,
            matter_id=row.matter_id,
            payload=json.loads(row.payload),
            created_at=_as_utc(row.created_at),
            prev_hash=row.prev_hash,
            hash=row.hash,
        )

    def events(self, tenant_id: str) -> list[AuditEvent]:
        """All events for one tenant in sequence order (no cross-tenant reads)."""
        return [self._to_event(row) for row in self._rows(tenant_id)]

    def verify_chain(self, tenant_id: str) -> IntegrityReport:
        """Recompute the tenant's chain and compare it with the head checkpoint.

        Detects edited payloads or fields (``hash_mismatch``), edited hashes, deleted,
        reordered or inserted rows (``chain_break`` / ``sequence_gap`` / ``hash_mismatch``),
        rows spliced in from another tenant (the tenant id is hashed), tail truncation and
        appended rows (``head_mismatch``), and a forged head (``head_mac_invalid``, keyed).
        """
        # The rows and checkpoint must come from the same snapshot. A concurrent append
        # between two independent reads must not be reported as tampering.
        with self._engine.connect() as conn:
            if self._engine.dialect.name == "postgresql":
                conn = conn.execution_options(isolation_level="REPEATABLE READ")
            with conn.begin():
                rows = list(
                    conn.execute(
                        select(audit_events)
                        .where(audit_events.c.tenant_id == tenant_id)
                        .order_by(audit_events.c.sequence)
                    ).all()
                )
                head = conn.execute(
                    select(audit_chain_head).where(audit_chain_head.c.tenant_id == tenant_id)
                ).first()
        issues: list[IntegrityIssue] = []
        expected_sequence = 1
        expected_prev = GENESIS_HASH
        for row in rows:
            sequence = int(row.sequence)
            if sequence != expected_sequence:
                issues.append(
                    IntegrityIssue(
                        "sequence_gap",
                        sequence,
                        f"expected sequence {expected_sequence}, found {sequence}",
                    )
                )
            if row.prev_hash != expected_prev:
                issues.append(
                    IntegrityIssue(
                        "chain_break", sequence, "prev_hash does not match the preceding event"
                    )
                )
            try:
                payload = json.loads(row.payload)
                validate_payload(row.event_type, payload)
                recomputed = event_hash(
                    hash_material(
                        schema_version=int(row.schema_version),
                        tenant_id=row.tenant_id,
                        sequence=sequence,
                        event_id=row.event_id,
                        event_type=row.event_type,
                        actor=row.actor,
                        matter_id=row.matter_id,
                        payload=payload,
                        created_at=row.created_at,
                        prev_hash=row.prev_hash,
                    )
                )
            except (ValueError, TypeError) as exc:
                issues.append(
                    IntegrityIssue("payload_invalid", sequence, type(exc).__name__),
                )
            else:
                if recomputed != row.hash:
                    issues.append(
                        IntegrityIssue(
                            "hash_mismatch", sequence, "stored hash does not match event content"
                        )
                    )
            expected_sequence = sequence + 1
            expected_prev = row.hash

        tip_sequence = int(rows[-1].sequence) if rows else 0
        tip_hash = str(rows[-1].hash) if rows else GENESIS_HASH
        mac_checked = False
        if head is None:
            if rows:
                issues.append(
                    IntegrityIssue("head_missing", None, "events exist but the head is missing")
                )
            head_sequence, head_hash = None, None
        else:
            head_sequence, head_hash = int(head.last_sequence), str(head.last_hash)
            if (head_sequence, head_hash) != (tip_sequence, tip_hash):
                issues.append(
                    IntegrityIssue(
                        "head_mismatch",
                        tip_sequence,
                        f"head records sequence {head_sequence}; chain tip is {tip_sequence}",
                    )
                )
            if self._head_key is not None:
                mac_checked = True
                if not verify_head_mac(
                    self._head_key,
                    head.head_mac,
                    tenant_id=tenant_id,
                    last_sequence=head_sequence,
                    last_hash=head_hash,
                ):
                    issues.append(
                        IntegrityIssue("head_mac_invalid", head_sequence, "head MAC check failed")
                    )
        return IntegrityReport(
            tenant_id=tenant_id,
            event_count=len(rows),
            head_sequence=head_sequence,
            head_hash=head_hash,
            head_mac_checked=mac_checked,
            issues=tuple(issues),
        )

    def dangling_calls(
        self,
        tenant_id: str,
        *,
        older_than: timedelta = timedelta(0),
        now: datetime | None = None,
    ) -> list[DanglingCall]:
        """Model calls with an ``ai.model_call_started`` but no ``ai.model_call`` record.

        ``older_than`` excludes calls that may still be in flight; ages are measured from the
        store's append time (``created_at``), not the caller-supplied ``occurred_at``.
        """
        cutoff = _as_utc(now or self._clock()) - older_than
        started: dict[str, DanglingCall] = {}
        completed: set[str] = set()
        rows = self._rows(tenant_id, ("ai.model_call_started", "ai.model_call"))
        for row in rows:
            payload = json.loads(row.payload)
            try:
                if row.event_type == "ai.model_call":
                    completed.add(str(AIAuditEvent.model_validate(payload).call_id))
                    continue
                start = AIModelCallStarted.model_validate(payload)
            except ValidationError:
                continue  # reported by verify_chain as payload_invalid
            started[str(start.call_id)] = DanglingCall(
                call_id=start.call_id,
                sequence=int(row.sequence),
                matter_id=start.matter_id,
                actor=start.actor,
                task_role=start.task_role,
                model_id=start.model_id,
                started_at=_as_utc(row.created_at),
            )
        return [
            call
            for call_id, call in started.items()
            if call_id not in completed and call.started_at <= cutoff
        ]


class TenantAuditSink:
    """:class:`~verina.ai.audit.AuditSink` that appends to one tenant's chain."""

    def __init__(self, store: SqlAuditStore, tenant_id: str) -> None:
        self._store = store
        self.tenant_id = tenant_id

    async def emit(self, event: AuditPayload) -> None:
        # The database call is blocking; keep it off the event loop.
        await asyncio.to_thread(self._store.append, self.tenant_id, event)
