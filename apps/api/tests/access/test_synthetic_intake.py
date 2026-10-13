"""Synthetic intake provenance and mutation boundaries; no routes or real data."""

import asyncio
from collections.abc import Awaitable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from verina.access import (
    AccessDenied,
    ActorId,
    ActorProfile,
    ConflictCheckRecord,
    ConflictStatus,
    ConflictWaiver,
    MatterId,
    Role,
)
from verina.access.domain import conflict_is_ready
from verina.ai import AuditEmissionError
from verina.ai.audit import InMemoryAuditSink
from verina.audit.events import AuditPayload

from .conftest import FIXED_NOW, TENANT_A, World

pytestmark = [pytest.mark.story("US-3"), pytest.mark.story("EN-7")]


def run[T](coro: Awaitable[T]) -> T:
    async def wrap() -> T:
        return await coro

    return asyncio.run(wrap())


def test_create_pending_with_server_identity_and_creator_only(world: World) -> None:
    matter = run(world.service.create_matter(world.p("a-lawyer"), "  Invented matter  "))
    record = world.repo.get(TENANT_A, matter)
    assert record is not None
    assert record.access.members == frozenset({ActorId("a-lawyer")})
    assert record.access.conflict_status is ConflictStatus.PENDING
    assert record.access.conflict_check is None
    assert record.access.waiver is None
    assert record.content.title == "Invented matter"
    assert world.sink.access_events[-1].action == "create_matter"
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        run(world.service.submit_review(world.p("a-lawyer"), matter.value))


@pytest.mark.parametrize("actor", ["a-requester", "a-admin", "a-knowledge"])
def test_create_role_denied_without_mutation(world: World, actor: str) -> None:
    before = dict(world.repo._partitions[TENANT_A])
    with pytest.raises(AccessDenied, match="role_not_permitted"):
        run(world.service.create_matter(world.p(actor), "Invented matter"))
    assert world.repo._partitions[TENANT_A] == before
    assert world.sink.access_events[-1].decision == "deny"


@pytest.mark.parametrize("title", ["", "  ", "x" * 201, None])
def test_invalid_title_generic_and_no_write(world: World, title: Any) -> None:
    with pytest.raises(ValueError, match=r"^invalid title$"):
        run(world.service.create_matter(world.p("a-lawyer"), title))
    assert world.sink.records == []


def test_missing_trusted_profile_denies_and_audits(world: World) -> None:
    world.identity._profiles.pop((TENANT_A, ActorId("a-lawyer")))
    for action in [
        world.service.create_matter(world.p("a-lawyer"), "Invented matter"),
        world.service.record_conflict_check(world.p("a-lawyer"), "m-gamma", ConflictStatus.CLEAR),
        world.service.waive_conflict(world.p("a-lawyer"), "m-beta", "Invented reason"),
    ]:
        with pytest.raises(AccessDenied, match="profile_required"):
            run(action)
        assert world.sink.access_events[-1].decision == "deny"
    assert world.access(TENANT_A, "m-beta").conflict_status is ConflictStatus.CONFLICT
    assert world.access(TENANT_A, "m-gamma").conflict_status is ConflictStatus.PENDING


def test_record_clear_named_profile_then_waiver_version_invalidation(world: World) -> None:
    principal = world.p("a-lawyer")
    check = run(world.service.record_conflict_check(principal, "m-gamma", ConflictStatus.CLEAR))
    assert check.version == 1 and check.recorded_at == FIXED_NOW
    assert check.recorder_profile.display_name == "Synthetic a-lawyer"
    assert run(world.service.submit_review(principal, "m-gamma"))
    hit = run(world.service.record_conflict_check(principal, "m-gamma", ConflictStatus.CONFLICT))
    assert hit.version == 2
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        run(world.service.submit_review(principal, "m-gamma"))
    waiver = run(world.service.waive_conflict(principal, "m-gamma", "  Invented waiver  "))
    assert waiver.check_version == 2 and waiver.same_actor_as_conflict_recorder
    assert waiver.reason == "Invented waiver"
    assert conflict_is_ready(world.access(TENANT_A, "m-gamma"))
    replacement = run(
        world.service.record_conflict_check(principal, "m-gamma", ConflictStatus.CONFLICT)
    )
    assert replacement.version == 3
    assert world.access(TENANT_A, "m-gamma").waiver is None
    world.set_access(TENANT_A, "m-gamma", conflict_status=ConflictStatus.WAIVED, waiver=waiver)
    assert not conflict_is_ready(world.access(TENANT_A, "m-gamma"))
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        run(world.service.submit_review(principal, "m-gamma"))


@pytest.mark.parametrize(
    "result", ["clear", "conflict", ConflictStatus.WAIVED, ConflictStatus.PENDING, None]
)
def test_record_result_strict_no_shortcut(world: World, result: Any) -> None:
    with pytest.raises(ValueError, match=r"^invalid conflict result$"):
        run(world.service.record_conflict_check(world.p("a-lawyer"), "m-gamma", result))
    assert world.access(TENANT_A, "m-gamma").conflict_status is ConflictStatus.PENDING


@pytest.mark.parametrize(
    "actor,matter",
    [
        ("a-requester", "m-alpha"),
        ("a-knowledge", "m-alpha"),
        ("a-admin", "m-alpha"),
        ("a-outsider", "m-alpha"),
        ("a-walled", "m-alpha"),
        ("b-partner", "m-alpha"),
    ],
)
def test_record_requires_role_membership_and_tenant(world: World, actor: str, matter: str) -> None:
    before = world.access(TENANT_A, matter)
    world.repo.calls.clear()
    with pytest.raises(AccessDenied):
        run(world.service.record_conflict_check(world.p(actor), matter, ConflictStatus.CLEAR))
    assert "get" not in world.repo.calls
    assert world.access(TENANT_A, matter) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"version": 0},
        {"version": -1},
        {"result": "clear"},
        {"recorded_at": datetime(2026, 10, 13)},
        {
            "recorded_at": datetime(2026, 10, 13, tzinfo=UTC).astimezone(
                timezone(timedelta(hours=8))
            )
        },
        {"recorded_by": "a-lawyer"},
        {"recorder_profile": None},
    ],
)
def test_malformed_clear_record_cannot_unlock(world: World, changes: dict[str, Any]) -> None:
    access = world.access(TENANT_A, "m-alpha")
    assert access.conflict_check is not None
    world.set_access(TENANT_A, "m-alpha", conflict_check=replace(access.conflict_check, **changes))
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        run(world.service.submit_review(world.p("a-lawyer"), "m-alpha"))
    assert (
        run(world.service.get_matter_status(world.p("a-requester"), "m-alpha")).status
        == "awaiting_clearance"
    )


@pytest.mark.parametrize("status", [ConflictStatus.CLEAR, ConflictStatus.WAIVED])
def test_bare_flags_fail_closed(world: World, status: ConflictStatus) -> None:
    world.set_access(TENANT_A, "m-alpha", conflict_status=status, conflict_check=None)
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        run(world.service.build_model_context(world.p("a-lawyer"), "m-alpha"))
    assert world.runner.contexts == []


@pytest.mark.parametrize("operation", ["create", "record", "waive"])
def test_audit_failure_does_not_mutate(world: World, operation: str) -> None:
    class Failure(InMemoryAuditSink):
        async def emit(self, event: AuditPayload) -> None:
            raise RuntimeError("invented failure")

    world.service._sink = Failure()
    before = dict(world.repo._partitions[TENANT_A])
    with pytest.raises(AuditEmissionError):
        run(_operation(world, operation))
    assert world.repo._partitions[TENANT_A] == before


def _operation(
    world: World, operation: str
) -> Awaitable[MatterId | ConflictCheckRecord | ConflictWaiver]:
    p = world.p("a-lawyer")
    if operation == "create":
        return world.service.create_matter(p, "Invented matter")
    if operation == "record":
        return world.service.record_conflict_check(p, "m-beta", ConflictStatus.CLEAR)
    return world.service.waive_conflict(p, "m-beta", "Invented waiver")


@pytest.mark.parametrize(
    "operation,change",
    [
        (o, c)
        for o in ["create", "record", "waive"]
        for c in ["role", "inactive", "profile", "membership", "wall"]
        if not (o == "create" and c in {"membership", "wall"})
    ],
)
def test_fresh_authority_after_audit(world: World, operation: str, change: str) -> None:
    actor = ActorId("a-lawyer")

    class Changing(InMemoryAuditSink):
        changed = False

        async def emit(self, event: AuditPayload) -> None:
            await super().emit(event)
            if not self.changed:
                self.changed = True
                if change == "role":
                    world.identity.set_roles(TENANT_A, actor, {Role.REQUESTER})
                elif change == "inactive":
                    world.identity.deactivate(TENANT_A, actor)
                elif change == "profile":
                    world.identity._profiles.pop((TENANT_A, actor))
                elif change == "membership":
                    world.set_access(TENANT_A, "m-beta", members=frozenset())
                else:
                    world.set_access(TENANT_A, "m-beta", walled=frozenset({actor}))

    world.service._sink = Changing()
    before = world.access(TENANT_A, "m-beta")
    count = len(world.repo._partitions[TENANT_A])
    with pytest.raises(AccessDenied):
        run(_operation(world, operation))
    after = world.access(TENANT_A, "m-beta")
    assert after.conflict_check == before.conflict_check
    assert after.waiver == before.waiver
    assert len(world.repo._partitions[TENANT_A]) == count


def test_profile_snapshot_survives_rename_and_deactivation(world: World) -> None:
    check = run(
        world.service.record_conflict_check(world.p("a-lawyer"), "m-alpha", ConflictStatus.CLEAR)
    )
    world.identity.register(
        "tok-a-lawyer",
        "tenant-a",
        "a-lawyer",
        [Role.LAWYER],
        display_name="Renamed synthetic lawyer",
    )
    world.identity.deactivate(TENANT_A, ActorId("a-lawyer"))
    assert check.recorder_profile.display_name == "Synthetic a-lawyer"
    assert conflict_is_ready(world.access(TENANT_A, "m-alpha"))
    assert run(world.service.submit_review(world.p("a-partner"), "m-alpha"))
    with pytest.raises(AccessDenied, match="unauthenticated"):
        run(
            world.service.record_conflict_check(
                world.p("a-lawyer"), "m-alpha", ConflictStatus.CLEAR
            )
        )


def test_requester_projection_and_audit_have_no_name_title_reason(world: World) -> None:
    run(
        world.service.record_conflict_check(world.p("a-lawyer"), "m-alpha", ConflictStatus.CONFLICT)
    )
    run(world.service.waive_conflict(world.p("a-lawyer"), "m-alpha", "Invented private reason"))
    status = run(world.service.get_matter_status(world.p("a-requester"), "m-alpha"))
    assert set(asdict(status)) == {"matter_id", "status"}
    assert status.status == "ready"
    audit = str([event.model_dump() for event in world.sink.access_events])
    assert all(
        value not in audit
        for value in ["Synthetic a-lawyer", "Invented private reason", "Alpha supply review"]
    )


def test_clock_invalid_or_before_hit_does_not_persist_waiver(world: World) -> None:
    before = world.access(TENANT_A, "m-beta")
    for now in [datetime(2026, 10, 13), FIXED_NOW - timedelta(seconds=1)]:

        def clock(value: datetime = now) -> datetime:
            return value

        world.service._clock = clock
        with pytest.raises(ValueError, match="invalid clock"):
            run(world.service.waive_conflict(world.p("a-lawyer"), "m-beta", "Invented reason"))
        assert world.access(TENANT_A, "m-beta") == before


def test_repository_failure_is_allow_decision_not_completed_receipt(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(world.repo, "update", lambda *args: False)
    with pytest.raises(AccessDenied, match="matter_not_accessible"):
        run(
            world.service.record_conflict_check(
                world.p("a-lawyer"), "m-gamma", ConflictStatus.CLEAR
            )
        )
    assert world.sink.access_events[-1].decision == "allow"
    assert world.access(TENANT_A, "m-gamma").conflict_status is ConflictStatus.PENDING


def test_profile_cannot_be_self_issued() -> None:
    with pytest.raises(TypeError):
        ActorProfile(TENANT_A, ActorId("actor"), "Synthetic impostor")


@pytest.mark.parametrize("operation", ["record", "waive"])
def test_changed_check_during_audit_is_not_silently_rebound(world: World, operation: str) -> None:
    original = world.access(TENANT_A, "m-beta")
    assert original.conflict_check is not None
    changed = replace(original.conflict_check, version=9)

    class Changing(InMemoryAuditSink):
        done = False

        async def emit(self, event: AuditPayload) -> None:
            await super().emit(event)
            if not self.done:
                self.done = True
                world.set_access(TENANT_A, "m-beta", conflict_check=changed)

    world.service._sink = Changing()
    with pytest.raises(AccessDenied, match="conflict_changed"):
        run(_operation(world, operation))
    assert world.access(TENANT_A, "m-beta").conflict_check == changed
    assert world.access(TENANT_A, "m-beta").waiver is None
    assert world.service._sink.access_events[-1].decision == "deny"


def test_check_and_waiver_cannot_be_transplanted_to_other_matter(world: World) -> None:
    p = world.p("a-lawyer")
    waiver = run(world.service.waive_conflict(p, "m-beta", "Invented waiver"))
    source = world.access(TENANT_A, "m-beta")
    world.set_access(
        TENANT_A,
        "m-gamma",
        conflict_status=ConflictStatus.WAIVED,
        conflict_recorded_by=source.conflict_recorded_by,
        conflict_check=source.conflict_check,
        waiver=waiver,
    )
    assert not conflict_is_ready(world.access(TENANT_A, "m-gamma"))
    with pytest.raises(AccessDenied, match="conflict_not_cleared"):
        run(world.service.submit_review(p, "m-gamma"))
    clear = run(world.service.record_conflict_check(p, "m-alpha", ConflictStatus.CLEAR))
    world.set_access(
        TENANT_A,
        "m-gamma",
        conflict_status=ConflictStatus.CLEAR,
        conflict_recorded_by=clear.recorded_by,
        conflict_check=clear,
        waiver=None,
    )
    assert not conflict_is_ready(world.access(TENANT_A, "m-gamma"))
