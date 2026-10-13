"""Regression coverage for requester projection and post-audit authority changes."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import asdict
from typing import Any

import pytest

from verina.access import (
    AccessDenied,
    ActorId,
    ConflictStatus,
    InMemoryLedgerStatus,
    LedgerEntryStatus,
    MatterAccessPolicy,
    MatterId,
    ReasonCode,
    Role,
)
from verina.audit.events import AuditPayload

from .conftest import TENANT_A, World

pytestmark = pytest.mark.story("EN-7")


def test_requester_status_projection_never_reads_content(world: World) -> None:
    requester = world.p("a-requester")
    world.repo.calls.clear()
    projection = asyncio.run(world.service.get_matter_status(requester, "m-alpha"))
    assert asdict(projection) == {"matter_id": {"value": "m-alpha"}, "status": "ready"}
    assert "get" not in world.repo.calls
    for operation in (
        world.service.get_matter(requester, "m-alpha"),
        world.service.list_matters(requester),
        world.service.search_matters(requester, "Liability"),
        world.service.build_model_context(requester, "m-alpha"),
    ):
        with pytest.raises(AccessDenied) as error:
            asyncio.run(operation)
        assert error.value.reason_code is ReasonCode.ROLE_NOT_PERMITTED
    assert "get" not in world.repo.calls


@pytest.mark.parametrize("condition", ["membership", "wall", "role", "inactive", "conflict"])
@pytest.mark.parametrize("operation", ["context", "review", "waiver", "attest", "export"])
def test_revocation_during_audit_await_prevents_sensitive_action(
    world: World, condition: str, operation: str
) -> None:
    actor = ActorId("a-lawyer")
    matter = "m-beta" if operation == "waiver" else "m-alpha"
    world.ledger.set(TENANT_A, MatterId(matter), {LedgerEntryStatus.VERIFIED: 1})
    previous_sink = world.service._sink

    class RevokingSink:
        changed = False

        async def emit(self, event: AuditPayload) -> None:
            await asyncio.sleep(0)
            if not self.changed:
                self.changed = True
                access = world.access(TENANT_A, matter)
                if condition == "membership":
                    world.set_access(TENANT_A, matter, members=access.members - {actor})
                elif condition == "wall":
                    world.set_access(TENANT_A, matter, walled=frozenset({actor}))
                elif condition == "role":
                    world.identity.set_roles(TENANT_A, actor, [Role.REQUESTER])
                elif condition == "inactive":
                    world.identity.deactivate(TENANT_A, actor)
                else:
                    # A waiver cannot apply to a conflict result that changed while awaiting.
                    new = ConflictStatus.CLEAR if operation == "waiver" else ConflictStatus.PENDING
                    world.set_access(TENANT_A, matter, conflict_status=new)
            await previous_sink.emit(event)

    world.service._sink = RevokingSink()
    p = world.p("a-lawyer")
    operations: dict[str, Callable[[], Coroutine[Any, Any, object]]] = {
        "context": lambda: world.service.build_model_context(p, matter),
        "review": lambda: world.service.submit_review(p, matter),
        "waiver": lambda: world.service.waive_conflict(p, matter, "Synthetic waiver"),
        "attest": lambda: world.service.attest_entry(p, matter, "entry-1", "Synthetic attestation"),
        "export": lambda: world.service.export_to_client(p, matter),
    }
    world.repo.calls.clear()
    with pytest.raises(AccessDenied):
        asyncio.run(operations[operation]())
    assert "get" not in world.repo.calls
    assert world.runner.contexts == []
    assert world.sink.access_events[-1].decision == "deny"
    assert world.access(TENANT_A, matter).waiver is None


@pytest.mark.parametrize("operation", ["read", "list", "count", "search", "status"])
def test_revocation_during_audit_does_not_return_stale_content_or_counts(
    world: World, operation: str
) -> None:
    p = world.p("a-lawyer")
    previous = world.service._sink

    class RemoveAllMembership:
        async def emit(self, event: AuditPayload) -> None:
            await asyncio.sleep(0)
            for matter in ("m-alpha", "m-beta", "m-gamma", "m-shared"):
                access = world.access(TENANT_A, matter)
                world.set_access(TENANT_A, matter, members=access.members - {p.actor_id})
            await previous.emit(event)

    world.service._sink = RemoveAllMembership()
    if operation in {"read", "status"}:
        coroutine = (
            world.service.get_matter(p, "m-alpha")
            if operation == "read"
            else world.service.get_matter_status(p, "m-alpha")
        )
        with pytest.raises(AccessDenied):
            asyncio.run(coroutine)
        assert "get" not in world.repo.calls
    else:
        operations: dict[str, Callable[[], Coroutine[Any, Any, object]]] = {
            "list": lambda: world.service.list_matters(p),
            "count": lambda: world.service.count_matters(p),
            "search": lambda: world.service.search_matters(p, "Liability"),
        }
        result = asyncio.run(operations[operation]())
        assert result == (0 if operation == "count" else [])


@pytest.mark.parametrize(
    "counts",
    [
        {},
        {"verified": -1},
        {"verified": True},
        {"verified": 1.0},
        {"verified": "1"},
        {"unknown": 0},
    ],
)
def test_unavailable_or_malformed_ledger_cannot_clear_export(world: World, counts: Any) -> None:
    class Ledger:
        def entry_status_counts(self, tenant_id: object, matter_id: object) -> Any:
            return counts

    world.service._policy = MatterAccessPolicy(Ledger())
    with pytest.raises(AccessDenied) as error:
        asyncio.run(world.service.export_to_client(world.p("a-lawyer"), "m-alpha"))
    assert error.value.reason_code is ReasonCode.LEDGER_STATUS_UNAVAILABLE


def test_unknown_ledger_denies_but_explicit_checked_zero_allows(world: World) -> None:
    world.service._policy = MatterAccessPolicy(InMemoryLedgerStatus())
    with pytest.raises(AccessDenied) as error:
        asyncio.run(world.service.export_to_client(world.p("a-lawyer"), "m-alpha"))
    assert error.value.reason_code is ReasonCode.LEDGER_STATUS_UNAVAILABLE
    ledger = InMemoryLedgerStatus()
    ledger.set(TENANT_A, MatterId("m-alpha"), {LedgerEntryStatus.VERIFIED: 0})
    world.service._policy = MatterAccessPolicy(ledger)
    clearance = asyncio.run(world.service.export_to_client(world.p("a-lawyer"), "m-alpha"))
    assert clearance.cleared_for == ActorId("a-lawyer")


def test_review_output_not_returned_after_membership_revoked_in_runner(world: World) -> None:
    principal = world.p("a-lawyer")
    job = asyncio.run(world.service.submit_review(principal, "m-alpha"))

    class Runner:
        async def run(self, context: object) -> str:
            access = world.access(TENANT_A, "m-alpha")
            world.set_access(TENANT_A, "m-alpha", members=access.members - {principal.actor_id})
            return "synthetic restricted output"

    world.service._runner = Runner()
    with pytest.raises(AccessDenied):
        asyncio.run(world.service.execute_review(job))
    assert world.sink.access_events[-1].decision == "deny"
