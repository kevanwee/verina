"""Independent QA negative oracles for recorded synthetic conflict readiness."""

import asyncio
from dataclasses import replace
from datetime import datetime

import pytest

from verina.access import AccessDenied, ActorId, ConflictStatus
from verina.ai import InMemoryAuditSink

from .conftest import TENANT_A, TENANT_B, World

pytestmark = [pytest.mark.story("US-3"), pytest.mark.story("EN-7")]


@pytest.mark.parametrize("status", [ConflictStatus.CLEAR, ConflictStatus.WAIVED])
@pytest.mark.parametrize("operation", ["context", "review", "attest", "export"])
def test_qa_bare_status_blocks_every_gated_operation(
    world: World, status: ConflictStatus, operation: str
) -> None:
    world.set_access(TENANT_A, "m-alpha", conflict_status=status, conflict_check=None)
    principal = world.p("a-lawyer")
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        if operation == "context":
            asyncio.run(world.service.build_model_context(principal, "m-alpha"))
        elif operation == "review":
            asyncio.run(world.service.submit_review(principal, "m-alpha"))
        elif operation == "attest":
            asyncio.run(world.service.attest_entry(principal, "m-alpha", "entry-1", "Invented"))
        else:
            asyncio.run(world.service.export_to_client(principal, "m-alpha"))
    assert world.runner.contexts == []


def test_qa_clearance_cannot_be_transplanted_to_another_matter(world: World) -> None:
    genuine = world.access(TENANT_A, "m-alpha")
    world.set_access(
        TENANT_A,
        "m-gamma",
        conflict_status=ConflictStatus.CLEAR,
        conflict_recorded_by=genuine.conflict_recorded_by,
        conflict_check=genuine.conflict_check,
    )
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        asyncio.run(world.service.submit_review(world.p("a-lawyer"), "m-gamma"))


def test_qa_waiver_for_same_version_and_actor_cannot_unlock_another_matter(world: World) -> None:
    principal = world.p("a-lawyer")
    waiver = asyncio.run(world.service.waive_conflict(principal, "m-beta", "Invented waiver"))
    check = asyncio.run(
        world.service.record_conflict_check(principal, "m-gamma", ConflictStatus.CONFLICT)
    )
    assert check.version == waiver.check_version
    world.set_access(TENANT_A, "m-gamma", conflict_status=ConflictStatus.WAIVED, waiver=waiver)
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        asyncio.run(world.service.build_model_context(principal, "m-gamma"))


def test_qa_foreign_profile_with_same_display_name_is_not_recorder_evidence(world: World) -> None:
    access = world.access(TENANT_A, "m-alpha")
    assert access.conflict_check is not None
    world.identity.register(
        "invented-profile-token", TENANT_B.value, "a-lawyer", [], display_name="Synthetic a-lawyer"
    )
    foreign = world.identity.profile(TENANT_B, ActorId("a-lawyer"))
    assert foreign is not None
    world.set_access(
        TENANT_A,
        "m-alpha",
        conflict_check=replace(access.conflict_check, recorder_profile=foreign),
    )
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        asyncio.run(world.service.submit_review(world.p("a-lawyer"), "m-alpha"))


def test_qa_changed_check_during_audit_is_not_overwritten(world: World) -> None:
    initial = world.access(TENANT_A, "m-beta")
    assert initial.conflict_check is not None
    replacement = replace(initial.conflict_check, version=7)

    class ReplaceDuringAudit(InMemoryAuditSink):
        async def emit(self, event: object) -> None:
            world.set_access(TENANT_A, "m-beta", conflict_check=replacement)

    world.service._sink = ReplaceDuringAudit()
    with pytest.raises(AccessDenied, match="conflict_changed"):
        asyncio.run(
            world.service.record_conflict_check(world.p("a-lawyer"), "m-beta", ConflictStatus.CLEAR)
        )
    assert world.access(TENANT_A, "m-beta").conflict_check == replacement
    assert world.access(TENANT_A, "m-beta").conflict_status is ConflictStatus.CONFLICT


def test_qa_bad_clock_cannot_replace_existing_clearance(world: World) -> None:
    initial = world.access(TENANT_A, "m-alpha")
    world.service._clock = lambda: datetime(2026, 10, 13)
    with pytest.raises(ValueError, match="invalid clock"):
        asyncio.run(
            world.service.record_conflict_check(
                world.p("a-lawyer"), "m-alpha", ConflictStatus.CONFLICT
            )
        )
    assert world.access(TENANT_A, "m-alpha") == initial
