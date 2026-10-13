"""Independent atomic outcome oracles, using only invented matter fixtures."""

import asyncio
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import DBAPIError

from verina.access import (
    AccessDenied,
    ActorId,
    ConflictStatus,
    MatterId,
    MatterService,
    MutationReplayError,
    SqlMatterMutationUnitOfWork,
    SqlMatterRepository,
)
from verina.access.domain import Action, MatterAccess, ReasonCode, TenantId
from verina.access.mutations import MutationToken, receipts
from verina.access.repository import MatterRevisionConflictError
from verina.audit import SqlAuditStore
from verina.audit.schema import audit_events
from verina.db import downgrade, make_engine, upgrade

from .conftest import FIXED_NOW, TENANT_A, TENANT_B, World

pytestmark = [pytest.mark.story("EN-8"), pytest.mark.story("US-3")]
BACKENDS = ["sqlite", "postgresql"] if os.getenv("VERINA_TEST_POSTGRES_URL") else ["sqlite"]


@pytest.fixture(params=BACKENDS)
def qa_outcome_engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    url = (
        os.environ["VERINA_TEST_POSTGRES_URL"]
        if request.param == "postgresql"
        else f"sqlite:///{tmp_path / 'qa-outcomes.db'}"
    )
    engine = make_engine(url)
    if request.param == "postgresql":
        downgrade(engine)
    upgrade(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def compose(
    engine: Engine, world: World
) -> tuple[SqlMatterRepository, SqlAuditStore, MatterService]:
    repo = SqlMatterRepository(engine)
    for tenant, partition in world.repo._partitions.items():
        for record in partition.values():
            repo.add(tenant, record)
    store = SqlAuditStore(engine, clock=lambda: FIXED_NOW)
    uow = SqlMatterMutationUnitOfWork(repo, store, clock=lambda: FIXED_NOW)
    service = MatterService(
        repository=repo,
        policy=world.service._policy,
        identity=world.identity,
        audit_sink=store.for_tenant(TENANT_A.value),
        review_runner=world.runner,
        clock=lambda: FIXED_NOW,
        mutation_uow=uow,
    )
    return repo, store, service


def completed_count(engine: Engine) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.event_type == "matter.mutation_completed")
            ).scalar_one()
        )


@pytest.mark.parametrize("cancel", [False, True])
def test_qa_receipt_insert_fault_rolls_back_matter_event_and_head(
    qa_outcome_engine: Engine, world: World, cancel: bool
) -> None:
    repo, store, _ = compose(qa_outcome_engine, world)
    old = repo.get(TENANT_A, MatterId("m-alpha"))
    assert old is not None
    changed = replace(old, content=replace(old.content, title="Invented atomic replacement"))
    uow = SqlMatterMutationUnitOfWork(repo, store, clock=lambda: FIXED_NOW)
    token = uuid4()
    before = store.verify_chain(TENANT_A.value)

    def fail(conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool) -> None:
        if statement.lower().startswith("insert into matter_mutation_receipts"):
            if cancel:
                raise asyncio.CancelledError()
            raise OSError("Invented receipt insertion fault")

    event.listen(qa_outcome_engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(asyncio.CancelledError if cancel else OSError):
            uow.put(
                world.p("a-lawyer"),
                Action.UPDATE_MATTER,
                token,
                "a" * 64,
                changed,
                old.access,
                lambda access, replayed: None,
            )
    finally:
        event.remove(qa_outcome_engine, "before_cursor_execute", fail)
    assert repo.get(TENANT_A, old.matter_id) == old
    assert completed_count(qa_outcome_engine) == 0
    assert uow.peek(TENANT_A, token) is None
    after = store.verify_chain(TENANT_A.value)
    assert after.ok and after.event_count == before.event_count
    assert (after.head_sequence, after.head_hash) == (before.head_sequence, before.head_hash)
    outcome = uow.put(
        world.p("a-lawyer"),
        Action.UPDATE_MATTER,
        token,
        "a" * 64,
        changed,
        old.access,
        lambda access, replayed: None,
    )
    assert outcome.result_revision == 2
    assert completed_count(qa_outcome_engine) == 1
    assert store.verify_chain(TENANT_A.value).ok


def test_qa_committed_response_loss_retry_does_not_reapply_newer_title(
    qa_outcome_engine: Engine, world: World
) -> None:
    repo, store, service = compose(qa_outcome_engine, world)
    token = uuid4()
    principal = world.p("a-lawyer")
    # The caller never receives/retains the first None response.
    asyncio.run(service.update_title(principal, "m-alpha", "Invented first", operation_id=token))
    asyncio.run(service.update_title(principal, "m-alpha", "Invented later", operation_id=uuid4()))
    before = repo.get(TENANT_A, MatterId("m-alpha"))
    assert (
        asyncio.run(
            service.update_title(principal, "m-alpha", "Invented first", operation_id=token)
        )
        is None
    )
    assert repo.get(TENANT_A, MatterId("m-alpha")) == before
    assert completed_count(qa_outcome_engine) == 2
    assert store.verify_chain(TENANT_A.value).ok


@pytest.mark.parametrize("change", ["body", "actor", "revision", "action"])
def test_qa_operation_cannot_be_reused_for_changed_intent(
    qa_outcome_engine: Engine, world: World, change: str
) -> None:
    repo, _, service = compose(qa_outcome_engine, world)
    token = uuid4()
    asyncio.run(
        service.update_title(world.p("a-lawyer"), "m-alpha", "Invented first", operation_id=token)
    )
    before = repo.get(TENANT_A, MatterId("m-alpha"))
    with pytest.raises(MutationReplayError):
        if change == "body":
            asyncio.run(
                service.update_title(
                    world.p("a-lawyer"), "m-alpha", "Invented changed", operation_id=token
                )
            )
        elif change == "actor":
            asyncio.run(
                service.update_title(
                    world.p("a-partner"), "m-alpha", "Invented first", operation_id=token
                )
            )
        elif change == "revision":
            asyncio.run(
                service.update_title(
                    world.p("a-lawyer"),
                    "m-alpha",
                    "Invented first",
                    operation_id=token,
                    expected_revision=2,
                )
            )
        else:
            asyncio.run(
                service.record_conflict_check(
                    world.p("a-lawyer"), "m-alpha", ConflictStatus.CLEAR, operation_id=token
                )
            )
    assert repo.get(TENANT_A, MatterId("m-alpha")) == before
    assert completed_count(qa_outcome_engine) == 1


@pytest.mark.parametrize("wall", [False, True])
def test_qa_create_retry_needs_current_target_visibility(
    qa_outcome_engine: Engine, world: World, wall: bool
) -> None:
    repo, _, service = compose(qa_outcome_engine, world)
    token = uuid4()
    principal = world.p("a-lawyer")
    target = asyncio.run(service.create_matter(principal, "Invented create", operation_id=token))
    assert (
        asyncio.run(service.create_matter(principal, "Invented create", operation_id=token))
        == target
    )
    current = repo.get(TENANT_A, target)
    assert current is not None
    access = (
        replace(current.access, walled=frozenset({ActorId("a-lawyer")}))
        if wall
        else replace(current.access, members=frozenset())
    )
    assert repo.update(TENANT_A, replace(current, access=access))
    with pytest.raises(AccessDenied, match="matter_not_accessible"):
        asyncio.run(service.create_matter(principal, "Invented create", operation_id=token))
    assert completed_count(qa_outcome_engine) == 1


@pytest.mark.parametrize("waiver", [False, True])
def test_qa_old_check_or_waiver_retry_cannot_unlock_new_hit(
    qa_outcome_engine: Engine, world: World, waiver: bool
) -> None:
    repo, _, service = compose(qa_outcome_engine, world)
    principal, token = world.p("a-lawyer"), uuid4()
    if waiver:
        original = asyncio.run(
            service.waive_conflict(principal, "m-beta", "Invented reason", operation_id=token)
        )
        assert (
            asyncio.run(
                service.waive_conflict(principal, "m-beta", "Invented reason", operation_id=token)
            )
            == original
        )
    else:
        original_check = asyncio.run(
            service.record_conflict_check(
                principal, "m-beta", ConflictStatus.CLEAR, operation_id=token
            )
        )
        assert (
            asyncio.run(
                service.record_conflict_check(
                    principal, "m-beta", ConflictStatus.CLEAR, operation_id=token
                )
            )
            == original_check
        )
    asyncio.run(
        service.record_conflict_check(
            principal, "m-beta", ConflictStatus.CONFLICT, operation_id=uuid4()
        )
    )
    before = repo.get(TENANT_A, MatterId("m-beta"))
    with pytest.raises(AccessDenied, match="conflict_changed"):
        if waiver:
            asyncio.run(
                service.waive_conflict(principal, "m-beta", "Invented reason", operation_id=token)
            )
        else:
            asyncio.run(
                service.record_conflict_check(
                    principal, "m-beta", ConflictStatus.CLEAR, operation_id=token
                )
            )
    assert repo.get(TENANT_A, MatterId("m-beta")) == before
    assert completed_count(qa_outcome_engine) == 2


def test_qa_denied_replay_does_not_select_historical_protected_result(
    qa_outcome_engine: Engine, world: World
) -> None:
    _, _, service = compose(qa_outcome_engine, world)
    token = uuid4()
    asyncio.run(
        service.waive_conflict(
            world.p("a-lawyer"), "m-beta", "Invented protected reason", operation_id=token
        )
    )
    world.identity.set_roles(TENANT_A, ActorId("a-lawyer"), [])
    statements: list[str] = []

    def observe(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        statements.append(statement.lower())

    event.listen(qa_outcome_engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(AccessDenied):
            asyncio.run(
                service.waive_conflict(
                    world.p("a-lawyer"), "m-beta", "Invented protected reason", operation_id=token
                )
            )
    finally:
        event.remove(qa_outcome_engine, "before_cursor_execute", observe)
    assert not any("result_access_json" in sql for sql in statements if sql.startswith("select"))


def test_qa_reason_only_in_protected_receipt_not_completed_audit(
    qa_outcome_engine: Engine, world: World
) -> None:
    _, _, service = compose(qa_outcome_engine, world)
    marker = "Invented confidential QA reason"
    token = uuid4()
    asyncio.run(service.waive_conflict(world.p("a-lawyer"), "m-beta", marker, operation_id=token))
    with qa_outcome_engine.begin() as conn:
        payload = conn.execute(
            select(audit_events.c.payload).where(
                audit_events.c.event_type == "matter.mutation_completed"
            )
        ).scalar_one()
        protected = conn.execute(
            select(receipts.c.result_access_json).where(receipts.c.operation_id == str(token))
        ).scalar_one()
    assert marker not in payload and "Synthetic a-lawyer" not in payload
    assert marker in protected and "Synthetic a-lawyer" in protected
    assert '"members":[]' in protected and '"walled":[]' in protected


def test_qa_shared_append_rejects_wrong_engine_and_inactive_transaction(
    qa_outcome_engine: Engine, world: World, tmp_path: Path
) -> None:
    _, store, _ = compose(qa_outcome_engine, world)
    asyncio.run(world.service.get_matter(world.p("a-lawyer"), "m-alpha"))
    payload = world.sink.access_events[-1]
    with (
        qa_outcome_engine.connect() as conn,
        pytest.raises(ValueError, match="active engine transaction"),
    ):
        store.append_on_connection(conn, TENANT_A.value, payload)
    other = make_engine(f"sqlite:///{tmp_path / 'wrong-engine.db'}")
    try:
        with other.begin() as conn, pytest.raises(ValueError, match="active engine transaction"):
            store.append_on_connection(conn, TENANT_A.value, payload)
    finally:
        other.dispose()


def test_qa_same_actor_and_operation_key_are_independent_between_tenants(
    qa_outcome_engine: Engine, world: World
) -> None:
    repo, store, service_a = compose(qa_outcome_engine, world)
    principal_b = world.identity.register(
        "invented-tenant-b-lawyer",
        TENANT_B.value,
        "a-lawyer",
        ["lawyer"],
        display_name="Invented tenant B lawyer",
    )
    service_b = MatterService(
        repository=repo,
        policy=world.service._policy,
        identity=world.identity,
        audit_sink=store.for_tenant(TENANT_B.value),
        review_runner=world.runner,
        clock=lambda: FIXED_NOW,
        mutation_uow=SqlMatterMutationUnitOfWork(repo, store, clock=lambda: FIXED_NOW),
    )
    token = uuid4()
    target_a = asyncio.run(
        service_a.create_matter(world.p("a-lawyer"), "Invented A", operation_id=token)
    )
    target_b = asyncio.run(service_b.create_matter(principal_b, "Invented B", operation_id=token))
    assert target_a != target_b
    assert repo.get(TENANT_A, target_b) is None and repo.get(TENANT_B, target_a) is None
    assert (
        asyncio.run(service_b.create_matter(principal_b, "Invented B", operation_id=token))
        == target_b
    )
    assert completed_count(qa_outcome_engine) == 2


def test_qa_duplicate_uow_denial_selects_only_metadata_until_authorized(
    qa_outcome_engine: Engine, world: World
) -> None:
    repo, store, _ = compose(qa_outcome_engine, world)
    old = repo.get(TENANT_A, MatterId("m-alpha"))
    assert old is not None
    uow, token = SqlMatterMutationUnitOfWork(repo, store, clock=lambda: FIXED_NOW), uuid4()
    changed = replace(old, content=replace(old.content, title="Invented committed"))
    uow.put(
        world.p("a-lawyer"),
        Action.UPDATE_MATTER,
        token,
        "b" * 64,
        changed,
        old.access,
        lambda access, replayed: None,
    )
    statements: list[str] = []

    def observe(conn: Any, cursor: Any, sql: str, params: Any, context: Any, many: bool) -> None:
        statements.append(sql.lower())

    def deny(access: MatterAccess | None, replayed: bool) -> None:
        assert replayed
        raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)

    event.listen(qa_outcome_engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(AccessDenied):
            uow.put(
                world.p("a-lawyer"),
                Action.UPDATE_MATTER,
                token,
                "b" * 64,
                changed,
                old.access,
                deny,
            )
    finally:
        event.remove(qa_outcome_engine, "before_cursor_execute", observe)
    assert not any("result_access_json" in sql for sql in statements if sql.startswith("select"))


def test_qa_protected_replay_load_rejects_changed_authorized_snapshot(
    qa_outcome_engine: Engine, world: World
) -> None:
    repo, store, service = compose(qa_outcome_engine, world)
    token = uuid4()
    asyncio.run(
        service.waive_conflict(
            world.p("a-lawyer"), "m-beta", "Invented protected reason", operation_id=token
        )
    )
    old = repo.get(TENANT_A, MatterId("m-beta"))
    assert old is not None
    assert repo.update(TENANT_A, replace(old, access=replace(old.access, members=frozenset())))
    statements: list[str] = []

    def observe(conn: Any, cursor: Any, sql: str, params: Any, context: Any, many: bool) -> None:
        statements.append(sql.lower())

    event.listen(qa_outcome_engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(MatterRevisionConflictError):
            SqlMatterMutationUnitOfWork(repo, store).load_authorized(
                TENANT_A, token, old.access, lambda access, replayed: None
            )
    finally:
        event.remove(qa_outcome_engine, "before_cursor_execute", observe)
    assert not any("result_access_json" in sql for sql in statements if sql.startswith("select"))


def test_qa_same_operation_committing_after_peek_returns_original_completion(
    qa_outcome_engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, service = compose(qa_outcome_engine, world)
    uow = service._uow
    assert uow is not None
    old = repo.get(TENANT_A, MatterId("m-alpha"))
    assert old is not None
    token = uuid4()
    principal = world.p("a-lawyer")
    command = replace(old, content=replace(old.content, title="Invented identical operation"))
    fingerprint = hashlib.sha256(
        json.dumps(
            ["update_matter", "m-alpha", "Invented identical operation"],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    original_peek = uow.peek

    def commit_in_window(tenant: TenantId, operation: UUID) -> MutationToken | None:
        prior = original_peek(tenant, operation)
        if prior is None:
            uow.put(
                principal,
                Action.UPDATE_MATTER,
                token,
                fingerprint,
                command,
                old.access,
                lambda access, replayed: None,
            )
        return prior

    monkeypatch.setattr(uow, "peek", commit_in_window)
    assert (
        asyncio.run(
            service.update_title(
                principal, "m-alpha", "Invented identical operation", operation_id=token
            )
        )
        is None
    )
    current = repo.get(TENANT_A, old.matter_id)
    assert current is not None and current.access.revision == 2
    assert completed_count(qa_outcome_engine) == 1


def test_qa_migration_0003_preserves_prior_audit_guard_and_current_matter(
    tmp_path: Path, world: World
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'qa-migration-outcomes.db'}")
    try:
        upgrade(engine, "0002_matters")
        repo = SqlMatterRepository(engine)
        record = world.repo.get(TENANT_A, MatterId("m-alpha"))
        assert record is not None
        repo.add(TENANT_A, record)
        store = SqlAuditStore(engine)
        asyncio.run(world.service.get_matter(world.p("a-lawyer"), "m-alpha"))
        store.append(TENANT_A.value, world.sink.access_events[-1])
        before = store.verify_chain(TENANT_A.value)
        upgrade(engine, "0003_matter_outcomes")
        assert repo.get(TENANT_A, record.matter_id) == record
        after = store.verify_chain(TENANT_A.value)
        assert after.ok and (after.head_sequence, after.head_hash) == (
            before.head_sequence,
            before.head_hash,
        )
        with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
            conn.execute(text("UPDATE audit_events SET actor='Invented tamper'"))
    finally:
        engine.dispose()
