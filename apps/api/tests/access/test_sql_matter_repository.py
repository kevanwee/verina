"""Reusable durable matter repository: synthetic tests on SQLite and CI PostgreSQL."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, event, inspect, select

from tests.audit.conftest import engine as engine
from verina.access import (
    AccessDenied,
    ConflictStatus,
    MatterAccess,
    MatterContent,
    MatterDocument,
    MatterId,
    MatterRecord,
    MatterService,
    SqlMatterRepository,
    StoredMatterError,
    TenantId,
)
from verina.access.repository import MatterRevisionConflictError, TenantMismatchError
from verina.access.sql_repository import matters, metadata
from verina.db import downgrade, make_engine, upgrade

from .conftest import TENANT_A, TENANT_B, World

pytestmark = [pytest.mark.story("EN-7"), pytest.mark.story("US-3")]


def seeded(engine: Engine, world: World) -> SqlMatterRepository:
    repo = SqlMatterRepository(engine)
    for tenant, records in world.repo._partitions.items():
        for record in records.values():
            repo.add(tenant, record)
    return repo


def test_durable_record_checks_waiver_documents_survive_restart(
    engine: Engine, world: World
) -> None:
    repo = SqlMatterRepository(engine)
    service = MatterService(
        repository=repo,
        identity=world.identity,
        policy=world.service._policy,
        audit_sink=world.sink,
        review_runner=world.runner,
        clock=world.service._clock,
    )
    p = world.p("a-lawyer")
    matter = asyncio.run(service.create_matter(p, "Invented restart matter"))
    asyncio.run(service.record_conflict_check(p, matter.value, ConflictStatus.CONFLICT))
    asyncio.run(service.waive_conflict(p, matter.value, "Invented restart waiver"))
    record = repo.get(TENANT_A, matter)
    assert record is not None
    documents = (MatterDocument("doc-1", "Invented document", "Invented terms"),)
    assert repo.update(
        TENANT_A, replace(record, content=replace(record.content, documents=documents))
    )
    expected = repo.get(TENANT_A, matter)
    assert expected is not None and expected.access.revision == 4
    url = engine.url.render_as_string(hide_password=False)
    engine.dispose()
    reopened = make_engine(url)
    try:
        recovered = SqlMatterRepository(reopened).get(TENANT_A, matter)
        assert recovered == expected
        assert recovered is not None and recovered.access.conflict_check is not None
        assert recovered.access.conflict_check.recorder_profile.display_name == "Synthetic a-lawyer"
        assert (
            recovered.access.waiver is not None
            and recovered.access.waiver.reason == "Invented restart waiver"
        )
    finally:
        reopened.dispose()


def test_tenant_partition_access_only_projection_and_hidden_content(
    engine: Engine, world: World
) -> None:
    repo = seeded(engine, world)
    statements: list[str] = []

    def capture(
        _conn: Any, _cursor: Any, statement: str, _params: Any, _ctx: Any, _many: bool
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert repo.get_access(TENANT_A, MatterId("m-bravo")) is None
        assert repo.get_access(TENANT_A, MatterId("m-alpha")) is not None
        assert all("content_json" not in sql for sql in statements)
        statements.clear()
        assert repo.count(TENANT_A, visible=lambda a: False) == 0
        assert repo.list(TENANT_A, visible=lambda a: False) == []
        assert repo.search(TENANT_A, "Liability", visible=lambda a: False) == []
        assert all("content_json" not in sql for sql in statements)
        assert repo.get(TENANT_A, MatterId("m-bravo")) is None
        assert [r.matter_id.value for r in repo.list(TENANT_B, visible=lambda a: True)] == [
            "m-bravo",
            "m-shared",
        ]
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_stale_update_delete_and_read_snapshot_fail_closed(engine: Engine, world: World) -> None:
    repo = seeded(engine, world)
    old = repo.get(TENANT_A, MatterId("m-alpha"))
    assert old is not None
    changed = replace(old, access=replace(old.access, members=frozenset()))
    assert repo.update(TENANT_A, changed)
    assert not repo.update(
        TENANT_A, replace(old, content=MatterContent("Stale invented overwrite"))
    )
    assert not repo.delete(TENANT_A, old.matter_id, expected_revision=old.access.revision)
    with pytest.raises(MatterRevisionConflictError, match=r"^matter changed$"):
        repo.get(TENANT_A, old.matter_id, expected_access=old.access)
    fresh = repo.get(TENANT_A, old.matter_id)
    assert fresh is not None and fresh.access.revision == old.access.revision + 1
    assert fresh.access.members == frozenset()
    assert repo.delete(TENANT_A, old.matter_id, expected_revision=fresh.access.revision)


def test_concurrent_sessions_have_one_cas_winner(engine: Engine, world: World) -> None:
    repo = seeded(engine, world)
    old = repo.get(TENANT_A, MatterId("m-alpha"))
    assert old is not None
    barrier = threading.Barrier(2)

    def write(title: str) -> bool:
        candidate = replace(old, content=MatterContent(title))
        barrier.wait(timeout=10)
        return SqlMatterRepository(engine).update(TENANT_A, candidate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["Invented winner A", "Invented winner B"]))
    assert sorted(results) == [False, True]
    fresh = repo.get(TENANT_A, old.matter_id)
    assert fresh is not None and fresh.access.revision == 2


@pytest.mark.parametrize("revision", [True, 0, -1, 1.0])
def test_expected_revision_strict_for_mutations(
    engine: Engine, world: World, revision: Any
) -> None:
    repo = seeded(engine, world)
    old = repo.get(TENANT_A, MatterId("m-alpha"))
    assert old is not None
    with pytest.raises(ValueError, match="invalid expected revision"):
        repo.update(TENANT_A, replace(old, access=replace(old.access, revision=revision)))
    with pytest.raises(ValueError, match="invalid expected revision"):
        repo.delete(TENANT_A, old.matter_id, expected_revision=revision)
    assert repo.get(TENANT_A, old.matter_id) == old


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("schema_version", True),
        ("tenant_id", "tenant-b"),
        ("matter_id", "m-other"),
        ("unexpected", "Invented hidden canary"),
        ("conflict_check", None),
    ],
)
def test_malformed_stored_access_rejected_generically(
    engine: Engine, world: World, field: str, value: Any
) -> None:
    repo = seeded(engine, world)
    with engine.begin() as conn:
        raw = conn.execute(
            select(matters.c.access_json).where(
                matters.c.tenant_id == TENANT_A.value, matters.c.matter_id == "m-alpha"
            )
        ).scalar_one()
        payload = json.loads(raw)
        payload[field] = value
        conn.execute(
            matters.update()
            .where(matters.c.tenant_id == TENANT_A.value, matters.c.matter_id == "m-alpha")
            .values(access_json=json.dumps(payload))
        )
    with pytest.raises(StoredMatterError, match=r"^invalid stored matter$"):
        repo.get_access(TENANT_A, MatterId("m-alpha"))
    with pytest.raises(StoredMatterError, match=r"^invalid stored matter$"):
        repo.get(TENANT_A, MatterId("m-alpha"))


def test_hidden_malformed_content_not_loaded_for_access_or_collections(
    engine: Engine, world: World
) -> None:
    repo = seeded(engine, world)
    with engine.begin() as conn:
        conn.execute(
            matters.update()
            .where(matters.c.tenant_id == TENANT_A.value)
            .values(content_json='{"title":"Invented private malformed"}')
        )
    assert repo.get_access(TENANT_A, MatterId("m-alpha")) is not None
    assert repo.count(TENANT_A, visible=lambda a: True) == 4
    assert repo.list(TENANT_A, visible=lambda a: False) == []
    with pytest.raises(StoredMatterError, match=r"^invalid stored matter$"):
        repo.get(TENANT_A, MatterId("m-alpha"))


def test_foreign_writes_and_duplicate_rows_rejected(engine: Engine, world: World) -> None:
    repo = seeded(engine, world)
    record = repo.get(TENANT_A, MatterId("m-alpha"))
    assert record is not None
    with pytest.raises(TenantMismatchError):
        repo.add(TENANT_B, record)
    with pytest.raises(TenantMismatchError):
        repo.update(TENANT_B, record)
    with pytest.raises(ValueError, match="already exists"):
        repo.add(TENANT_A, record)
    assert repo.get(TenantId("unknown"), record.matter_id) is None


def test_migration_upgrade_preserves_audit_and_downgrade_removes_matters(engine: Engine) -> None:
    inspector = inspect(engine)
    assert inspector.get_pk_constraint("matters")["constrained_columns"] == [
        "tenant_id",
        "matter_id",
    ]
    assert set(c["name"] for c in inspector.get_columns("matters")) == set(
        c.name for c in metadata.tables["matters"].columns
    )
    downgrade(engine, "0001_audit_chain")
    assert "matters" not in inspect(engine).get_table_names()
    assert "audit_events" in inspect(engine).get_table_names()
    upgrade(engine)
    assert "matters" in inspect(engine).get_table_names()


def test_service_read_rejects_revision_change_before_content(engine: Engine, world: World) -> None:
    repo = seeded(engine, world)

    class Racing(SqlMatterRepository):
        def get(
            self,
            tenant_id: TenantId,
            matter_id: MatterId,
            *,
            expected_access: MatterAccess | None = None,
        ) -> MatterRecord | None:
            latest = repo.get(tenant_id, matter_id)
            assert latest is not None
            assert repo.update(
                tenant_id, replace(latest, access=replace(latest.access, members=frozenset()))
            )
            return super().get(tenant_id, matter_id, expected_access=expected_access)

    world.service._repo = Racing(engine)
    with pytest.raises(AccessDenied, match="matter_changed"):
        asyncio.run(world.service.get_matter(world.p("a-lawyer"), "m-alpha"))


@pytest.mark.parametrize("revision", [True, 1.0, 0, -1])
def test_codec_rejects_malformed_row_revision(world: World, revision: Any) -> None:
    from verina.access.storage_codec import decode_access, encode_access

    record = world.repo.get(TENANT_A, MatterId("m-alpha"))
    assert record is not None
    with pytest.raises(StoredMatterError):
        decode_access(encode_access(record.access), TENANT_A, record.matter_id, revision)
