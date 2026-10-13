"""Synthetic two-tenant world for access tests. No real names, clients or documents."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from verina.access import (
    ActorId,
    ConflictCheckRecord,
    ConflictStatus,
    InMemoryIdentityAdapter,
    InMemoryLedgerStatus,
    InMemoryMatterRepository,
    MatterAccess,
    MatterAccessPolicy,
    MatterContent,
    MatterDocument,
    MatterId,
    MatterRecord,
    MatterService,
    ModelContext,
    Principal,
    Role,
    TenantId,
)
from verina.ai import InMemoryAuditSink

FIXED_NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
TENANT_A = TenantId("tenant-a")
TENANT_B = TenantId("tenant-b")

# token, tenant, actor, roles
USERS: tuple[tuple[str, TenantId, str, tuple[Role, ...]], ...] = (
    ("tok-a-partner", TENANT_A, "a-partner", (Role.PARTNER,)),
    ("tok-a-lawyer", TENANT_A, "a-lawyer", (Role.LAWYER,)),
    ("tok-a-outsider", TENANT_A, "a-outsider", (Role.LAWYER,)),
    ("tok-a-requester", TENANT_A, "a-requester", (Role.REQUESTER,)),
    ("tok-a-admin", TENANT_A, "a-admin", (Role.TENANT_ADMIN,)),
    ("tok-a-knowledge", TENANT_A, "a-knowledge", (Role.KNOWLEDGE,)),
    ("tok-a-walled", TENANT_A, "a-walled", (Role.PARTNER,)),
    ("tok-b-partner", TENANT_B, "b-partner", (Role.PARTNER,)),
)


def _actors(*names: str) -> frozenset[ActorId]:
    return frozenset(ActorId(n) for n in names)


def _doc(n: int, text: str) -> MatterDocument:
    return MatterDocument(document_id=f"doc-{n}", title=f"Synthetic agreement {n}", text=text)


def seed_matters() -> list[MatterRecord]:
    return [
        MatterRecord(
            MatterAccess(
                TENANT_A,
                MatterId("m-alpha"),
                members=_actors(
                    "a-partner", "a-lawyer", "a-requester", "a-knowledge", "a-walled", "a-admin"
                ),
                walled=_actors("a-walled"),
                conflict_status=ConflictStatus.CLEAR,
            ),
            MatterContent("Alpha supply review", (_doc(1, "Liability cap of SGD 1 (synthetic)."),)),
        ),
        MatterRecord(
            MatterAccess(
                TENANT_A,
                MatterId("m-beta"),
                members=_actors("a-partner", "a-lawyer"),
                conflict_status=ConflictStatus.CONFLICT,
                conflict_recorded_by=ActorId("a-lawyer"),
            ),
            MatterContent("Beta services review", (_doc(2, "Termination for convenience."),)),
        ),
        MatterRecord(
            MatterAccess(
                TENANT_A,
                MatterId("m-gamma"),
                members=_actors("a-lawyer"),
                conflict_status=ConflictStatus.PENDING,
            ),
            MatterContent("Gamma licence review", (_doc(3, "Liability cap in licence."),)),
        ),
        MatterRecord(
            MatterAccess(
                TENANT_A,
                MatterId("m-shared"),
                members=_actors("a-lawyer"),
                conflict_status=ConflictStatus.CLEAR,
            ),
            MatterContent("Tenant A shared-id matter", ()),
        ),
        MatterRecord(
            MatterAccess(
                TENANT_B,
                MatterId("m-bravo"),
                members=_actors("b-partner"),
                conflict_status=ConflictStatus.CLEAR,
            ),
            MatterContent("Bravo secret review", (_doc(4, "Liability cap tenant B only."),)),
        ),
        MatterRecord(
            MatterAccess(
                TENANT_B,
                MatterId("m-shared"),
                members=_actors("b-partner"),
                conflict_status=ConflictStatus.CLEAR,
            ),
            MatterContent("Tenant B shared-id matter", ()),
        ),
    ]


class SpyRepository(InMemoryMatterRepository):
    """Records which repository operations ran, to prove authorization precedes content reads."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def get_access(self, tenant_id: TenantId, matter_id: MatterId) -> MatterAccess | None:
        self.calls.append("get_access")
        return super().get_access(tenant_id, matter_id)

    def get(
        self,
        tenant_id: TenantId,
        matter_id: MatterId,
        *,
        expected_access: MatterAccess | None = None,
    ) -> MatterRecord | None:
        self.calls.append("get")
        return super().get(tenant_id, matter_id, expected_access=expected_access)


class RecordingRunner:
    """Stands in for the orchestrator adapter; records every context it receives."""

    def __init__(self) -> None:
        self.contexts: list[ModelContext] = []

    async def run(self, context: ModelContext) -> str:
        self.contexts.append(context)
        return f"reviewed {context.matter_id} for {context.actor_id}"


@dataclass
class World:
    identity: InMemoryIdentityAdapter
    repo: SpyRepository
    ledger: InMemoryLedgerStatus
    sink: InMemoryAuditSink
    runner: RecordingRunner
    service: MatterService
    principals: dict[str, Principal] = field(default_factory=dict)

    def p(self, actor: str) -> Principal:
        return self.principals[actor]

    def access(self, tenant: TenantId, matter: str) -> MatterAccess:
        found = self.repo.get_access(tenant, MatterId(matter))
        assert found is not None
        return found

    def set_access(self, tenant: TenantId, matter: str, **changes: Any) -> None:
        from dataclasses import replace

        record = self.repo.get(tenant, MatterId(matter))
        assert record is not None
        assert self.repo.update(tenant, replace(record, access=replace(record.access, **changes)))
        self.repo.calls.clear()


def build_world() -> World:
    identity = InMemoryIdentityAdapter()
    principals = {
        actor: identity.register(
            token, tenant.value, actor, roles, display_name=f"Synthetic {actor}"
        )
        for token, tenant, actor, roles in USERS
    }
    repo = SpyRepository()
    for record in seed_matters():
        # These are explicitly invented checks, not a migration of operational records.
        from dataclasses import replace

        if record.access.conflict_status in {ConflictStatus.CLEAR, ConflictStatus.CONFLICT}:
            actor = ActorId("a-lawyer" if record.tenant_id == TENANT_A else "b-partner")
            profile = identity.profile(record.tenant_id, actor)
            assert profile is not None
            check = ConflictCheckRecord(
                record.matter_id, record.access.conflict_status, actor, FIXED_NOW, 1, profile
            )
            record = replace(
                record,
                access=replace(record.access, conflict_recorded_by=actor, conflict_check=check),
            )
        repo.add(record.tenant_id, record)
    repo.calls.clear()
    ledger = InMemoryLedgerStatus()
    sink = InMemoryAuditSink()
    runner = RecordingRunner()
    service = MatterService(
        repository=repo,
        policy=MatterAccessPolicy(ledger),
        identity=identity,
        audit_sink=sink,
        review_runner=runner,
        clock=lambda: FIXED_NOW,
    )
    return World(identity, repo, ledger, sink, runner, service, principals)


@pytest.fixture
def world() -> World:
    return build_world()
