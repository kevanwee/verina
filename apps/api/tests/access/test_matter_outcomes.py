"""Atomic completion and retry oracles; fixtures are invented, not live matter data."""

import asyncio
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import SQLAlchemyError

from tests.audit.conftest import engine as engine
from verina.access import (
    AccessDenied,
    Action,
    ConflictStatus,
    MatterAccess,
    MatterContent,
    MatterId,
    MatterRecord,
    MatterService,
    MutationReceipt,
    MutationReplayError,
    SqlMatterMutationUnitOfWork,
    SqlMatterRepository,
)
from verina.access.mutations import receipts, request_hash
from verina.access.sql_repository import matters
from verina.audit import SqlAuditStore
from verina.audit.schema import audit_chain_head, audit_events
from verina.db import make_engine, upgrade

from .conftest import FIXED_NOW, TENANT_A, World

pytestmark = [pytest.mark.story("EN-14"), pytest.mark.story("EN-8")]


def composed(
    engine: Engine, world: World
) -> tuple[MatterService, SqlMatterRepository, SqlAuditStore, SqlMatterMutationUnitOfWork]:
    repo = SqlMatterRepository(engine)
    store = SqlAuditStore(engine)
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
    return service, repo, store, uow


def completions(store: SqlAuditStore) -> list[Any]:
    return [e for e in store.events(TENANT_A.value) if e.event_type == "matter.mutation_completed"]


def test_integrated_create_record_waive_title_and_retry_metadata(
    engine: Engine, world: World
) -> None:
    service, repo, store, uow = composed(engine, world)
    p = world.p("a-lawyer")
    creation, recording, waiving, updating = [uuid4() for _ in range(4)]
    matter = asyncio.run(
        service.create_matter(
            p, "Invented title canary", operation_id=creation, expected_revision=0
        )
    )
    assert (
        asyncio.run(service.create_matter(p, "Invented title canary", operation_id=creation))
        == matter
    )
    check = asyncio.run(
        service.record_conflict_check(
            p, matter.value, ConflictStatus.CONFLICT, operation_id=recording, expected_revision=1
        )
    )
    assert (
        asyncio.run(
            service.record_conflict_check(
                p, matter.value, ConflictStatus.CONFLICT, operation_id=recording
            )
        )
        == check
    )
    waiver = asyncio.run(
        service.waive_conflict(
            p, matter.value, "Invented reason canary", operation_id=waiving, expected_revision=2
        )
    )
    assert (
        asyncio.run(
            service.waive_conflict(p, matter.value, "Invented reason canary", operation_id=waiving)
        )
        == waiver
    )
    asyncio.run(
        service.update_title(
            p, matter.value, "Invented new title", operation_id=updating, expected_revision=3
        )
    )
    asyncio.run(service.update_title(p, matter.value, "Invented new title", operation_id=updating))
    saved = repo.get(TENANT_A, matter)
    assert saved is not None and saved.access.revision == 4
    events = completions(store)
    assert len(events) == 4
    assert [(e.payload["expected_revision"], e.payload["result_revision"]) for e in events] == [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
    ]
    assert all(
        value not in str([e.payload for e in events])
        for value in ["Invented reason canary", "Invented title canary", "Synthetic a-lawyer"]
    )
    assert store.verify_chain(TENANT_A.value).ok
    title_receipt = uow.lookup(TENANT_A, updating)
    assert title_receipt is not None and title_receipt.result_access.conflict_check is None
    assert title_receipt.result_access.waiver is None
    waive_receipt = uow.lookup(TENANT_A, waiving)
    assert waive_receipt is not None
    assert not waive_receipt.result_access.members and not waive_receipt.result_access.walled


@pytest.mark.parametrize("fault", [RuntimeError, KeyboardInterrupt, asyncio.CancelledError])
def test_fault_after_audit_before_commit_rolls_back_everything(
    engine: Engine, world: World, fault: type[BaseException]
) -> None:
    service, repo, store, uow = composed(engine, world)
    token = uuid4()

    def fail(
        _conn: Any, _cursor: Any, statement: str, _params: Any, _ctx: Any, _many: bool
    ) -> None:
        if statement.startswith("INSERT INTO matter_mutation_receipts"):
            raise fault("invented precommit failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(fault):
            asyncio.run(
                service.create_matter(
                    world.p("a-lawyer"), "Invented failing matter", operation_id=token
                )
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert repo.count(TENANT_A, visible=lambda a: True) == 0
    assert completions(store) == []
    assert uow.lookup(TENANT_A, token) is None
    assert store.verify_chain(TENANT_A.value).ok
    assert all(e.event_type == "access.decision" for e in store.events(TENANT_A.value))
    asyncio.run(
        service.create_matter(world.p("a-lawyer"), "Invented failing matter", operation_id=token)
    )
    assert len(completions(store)) == 1


def test_audit_append_failure_does_not_apply_update(
    engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repo, store, _ = composed(engine, world)
    p = world.p("a-lawyer")
    matter = asyncio.run(service.create_matter(p, "Invented initial"))
    old = repo.get(TENANT_A, matter)
    original = store.append_on_connection

    def failed(conn: Any, tenant: str, payload: Any) -> Any:
        if payload.event_type == "matter.mutation_completed":
            original(conn, tenant, payload)
            raise RuntimeError("invented outcome failure")
        return original(conn, tenant, payload)

    monkeypatch.setattr(store, "append_on_connection", failed)
    with pytest.raises(RuntimeError, match="invented outcome failure"):
        asyncio.run(service.update_title(p, matter.value, "Invented changed"))
    assert repo.get(TENANT_A, matter) == old
    assert len(completions(store)) == 1
    assert store.verify_chain(TENANT_A.value).ok


def test_lost_commit_response_retries_original_without_new_mutation(
    engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repo, store, uow = composed(engine, world)
    token = uuid4()
    original = uow.put

    def lost(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise RuntimeError("invented response loss")

    monkeypatch.setattr(uow, "put", lost)
    with pytest.raises(RuntimeError, match="invented response loss"):
        asyncio.run(
            service.create_matter(world.p("a-lawyer"), "Invented committed", operation_id=token)
        )
    matter = asyncio.run(
        service.create_matter(world.p("a-lawyer"), "Invented committed", operation_id=token)
    )
    assert repo.get(TENANT_A, matter) is not None
    assert len(completions(store)) == 1


@pytest.mark.parametrize("change", ["title", "actor", "action", "expected"])
def test_operation_reuse_different_intent_conflicts(
    engine: Engine, world: World, change: str
) -> None:
    service, _, store, _ = composed(engine, world)
    p = world.p("a-lawyer")
    token = uuid4()
    matter = asyncio.run(service.create_matter(p, "Invented original", operation_id=token))
    with pytest.raises(MutationReplayError):
        if change == "title":
            asyncio.run(service.create_matter(p, "Invented changed", operation_id=token))
        elif change == "actor":
            asyncio.run(
                service.create_matter(world.p("a-partner"), "Invented original", operation_id=token)
            )
        elif change == "action":
            asyncio.run(
                service.update_title(p, matter.value, "Invented original", operation_id=token)
            )
        else:
            asyncio.run(
                service.create_matter(
                    p, "Invented original", operation_id=token, expected_revision=1
                )
            )
    assert len(completions(store)) == 1


def test_conflict_replay_does_not_reapply_or_return_stale_clearance(
    engine: Engine, world: World
) -> None:
    service, repo, store, _ = composed(engine, world)
    p = world.p("a-lawyer")
    matter = asyncio.run(service.create_matter(p, "Invented matter"))
    token = uuid4()
    asyncio.run(
        service.record_conflict_check(p, matter.value, ConflictStatus.CLEAR, operation_id=token)
    )
    asyncio.run(service.record_conflict_check(p, matter.value, ConflictStatus.CONFLICT))
    before = repo.get(TENANT_A, matter)
    with pytest.raises(AccessDenied, match="conflict_changed"):
        asyncio.run(
            service.record_conflict_check(p, matter.value, ConflictStatus.CLEAR, operation_id=token)
        )
    assert repo.get(TENANT_A, matter) == before
    assert len(completions(store)) == 3


def test_current_revocation_blocks_create_replay_before_private_receipt_read(
    engine: Engine, world: World
) -> None:
    service, repo, _, _ = composed(engine, world)
    p = world.p("a-lawyer")
    token = uuid4()
    matter = asyncio.run(service.create_matter(p, "Invented matter", operation_id=token))
    current = repo.get(TENANT_A, matter)
    assert current is not None
    assert repo.update(
        TENANT_A, replace(current, access=replace(current.access, members=frozenset()))
    )
    statements: list[str] = []

    def capture(
        _conn: Any, _cursor: Any, statement: str, _params: Any, _ctx: Any, _many: bool
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(AccessDenied, match="matter_not_accessible"):
            asyncio.run(service.create_matter(p, "Invented matter", operation_id=token))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert all(
        "result_access_json" not in query and "content_json" not in query for query in statements
    )


def test_concurrent_same_operation_has_one_completion(engine: Engine, world: World) -> None:
    _, repo, store, uow = composed(engine, world)
    p = world.p("a-lawyer")
    token = uuid4()
    record = MatterRecord(
        MatterAccess(TENANT_A, MatterId("invented-parallel"), members=frozenset({p.actor_id})),
        MatterContent("Invented parallel"),
    )

    def put(_: int) -> MutationReceipt:
        return uow.put(
            p,
            Action.CREATE_MATTER,
            token,
            request_hash(Action.CREATE_MATTER, None, "Invented parallel"),
            record,
            None,
            lambda access, replayed: None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(put, [1, 2]))
    assert results[0] == results[1]
    assert repo.count(TENANT_A, visible=lambda a: True) == 1
    assert len(completions(store)) == 1


def test_completed_receipts_cannot_be_updated_or_deleted(engine: Engine, world: World) -> None:
    service, _, _, _ = composed(engine, world)
    asyncio.run(service.create_matter(world.p("a-lawyer"), "Invented immutable"))
    for statement in [receipts.update().values(action="update_matter"), receipts.delete()]:
        with pytest.raises(SQLAlchemyError), engine.begin() as conn:
            conn.execute(statement)


def test_shared_append_rejects_inactive_or_foreign_connection(
    engine: Engine, tmp_path: Path
) -> None:
    store = SqlAuditStore(engine)
    other = make_engine(f"sqlite:///{tmp_path / 'foreign.db'}")
    try:
        with engine.connect() as conn, pytest.raises(ValueError):
            store.lock_tenant_on_connection(conn, TENANT_A.value)
        with other.begin() as conn, pytest.raises(ValueError):
            store.lock_tenant_on_connection(conn, TENANT_A.value)
    finally:
        other.dispose()


def test_durable_composition_rejects_arbitrary_sink_and_unsupported_mutations(
    engine: Engine, world: World
) -> None:
    service, repo, store, uow = composed(engine, world)
    with pytest.raises(ValueError, match="matching repository and audit"):
        MatterService(
            repository=repo,
            policy=world.service._policy,
            identity=world.identity,
            audit_sink=world.sink,
            review_runner=world.runner,
            mutation_uow=uow,
        )
    for action in [
        service.delete_matter(world.p("a-partner"), "m-any"),
        service.grant_membership(world.p("a-partner"), "m-any", "a-lawyer"),
    ]:
        with pytest.raises(ValueError, match="not integrated"):
            asyncio.run(action)
    assert store.events(TENANT_A.value) == []


def test_hard_process_exit_before_commit_rolls_back_sqlite(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hard-exit.db'}"
    engine = make_engine(url)
    upgrade(engine)
    script = """
import os,sys
from uuid import uuid4
from sqlalchemy import event
from verina.access import *
from verina.access.mutations import request_hash
from verina.audit import SqlAuditStore
from verina.db import make_engine
engine=make_engine(sys.argv[1])
identity=InMemoryIdentityAdapter()
p=identity.register("invented","tenant-a","actor",[Role.LAWYER])
repo=SqlMatterRepository(engine)
uow=SqlMatterMutationUnitOfWork(repo,SqlAuditStore(engine))
def exit_before_receipt(conn,cursor,statement,parameters,context,many):
    if statement.startswith("INSERT INTO matter_mutation_receipts"):
        os._exit(23)
event.listen(engine,"before_cursor_execute",exit_before_receipt)
record=MatterRecord(
    MatterAccess(p.tenant_id,MatterId("invented-crash"),members=frozenset({p.actor_id})),
    MatterContent("Invented crash")
)
uow.put(
    p,Action.CREATE_MATTER,uuid4(),
    request_hash(Action.CREATE_MATTER,None,"Invented crash"),
    record,None,lambda access,replay:None
)
"""
    try:
        result = subprocess.run(  # noqa: S603 - fixed test script and local fixture URL
            [sys.executable, "-c", script, url], check=False, capture_output=True, timeout=30
        )
        assert result.returncode == 23
        with engine.begin() as conn:
            for table in [matters, receipts, audit_events, audit_chain_head]:
                assert conn.execute(select(table)).all() == []
    finally:
        engine.dispose()
