"""Independent durable matter oracles: restart, projection, CAS and hostile storage."""

import asyncio
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, event, select, text
from sqlalchemy.exc import DBAPIError

from verina.access import MatterId, SqlMatterRepository
from verina.access.domain import conflict_is_ready
from verina.access.repository import MatterRevisionConflictError
from verina.access.sql_repository import matters
from verina.access.storage_codec import (
    StoredMatterError,
    decode_access,
    decode_content,
    encode_access,
)
from verina.audit import SqlAuditStore
from verina.db import downgrade, make_engine, upgrade

from .conftest import TENANT_A, TENANT_B, World

pytestmark = [pytest.mark.story("EN-7"), pytest.mark.story("US-3")]
BACKENDS = ["sqlite", "postgresql"] if os.getenv("VERINA_TEST_POSTGRES_URL") else ["sqlite"]


@pytest.fixture(params=BACKENDS)
def qa_engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    if request.param == "postgresql":
        url = os.environ["VERINA_TEST_POSTGRES_URL"]
        engine = make_engine(url)
        downgrade(engine)
    else:
        engine = make_engine(f"sqlite:///{tmp_path / 'qa-matters.db'}")
    upgrade(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_qa_restart_preserves_named_waiver_content_and_revision(
    qa_engine: Engine, world: World
) -> None:
    asyncio.run(world.service.waive_conflict(world.p("a-lawyer"), "m-beta", "Invented QA waiver"))
    record = world.repo.get(TENANT_A, MatterId("m-beta"))
    assert record is not None
    original = replace(record, access=replace(record.access, revision=1))
    repo = SqlMatterRepository(qa_engine)
    repo.add(TENANT_A, original)
    changed = replace(original, content=replace(original.content, title="Invented current title"))
    assert repo.update(TENANT_A, changed)
    url = str(qa_engine.url)
    if qa_engine.dialect.name == "postgresql":
        url = qa_engine.url.render_as_string(hide_password=False)
    restarted_engine = make_engine(url)
    try:
        restored = SqlMatterRepository(restarted_engine).get(TENANT_A, original.matter_id)
        assert restored is not None
        assert restored.content == changed.content
        assert restored.access == replace(original.access, revision=2)
        assert restored.access.waiver is not None
        assert restored.access.waiver.actor_profile.display_name == "Synthetic a-lawyer"
        assert restored.access.conflict_check is not None
        assert restored.access.conflict_check.recorder_profile.display_name == "Synthetic a-lawyer"
        assert conflict_is_ready(restored.access)
        assert SqlMatterRepository(restarted_engine).get(TENANT_B, original.matter_id) is None
    finally:
        restarted_engine.dispose()


def test_qa_two_independent_writers_do_not_lose_update_or_allow_stale_delete(
    qa_engine: Engine, world: World
) -> None:
    original = world.repo.get(TENANT_A, MatterId("m-alpha"))
    assert original is not None
    SqlMatterRepository(qa_engine).add(TENANT_A, original)

    def write(title: str) -> bool:
        return SqlMatterRepository(qa_engine).update(
            TENANT_A, replace(original, content=replace(original.content, title=title))
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(write, ["Invented writer one", "Invented writer two"]))
    assert sorted(outcomes) == [False, True]
    repo = SqlMatterRepository(qa_engine)
    assert not repo.delete(TENANT_A, original.matter_id, expected_revision=1)
    current = repo.get(TENANT_A, original.matter_id)
    assert current is not None and current.access.revision == 2
    assert current.content.title in {"Invented writer one", "Invented writer two"}
    with pytest.raises(MatterRevisionConflictError):
        repo.get(TENANT_A, original.matter_id, expected_access=original.access)
    assert repo.delete(TENANT_A, original.matter_id, expected_revision=2)


@pytest.mark.parametrize("bad_revision", [True, False, 0, -1, 1.0, "1"])
def test_qa_invalid_revision_cannot_mutate_or_delete(
    qa_engine: Engine, world: World, bad_revision: Any
) -> None:
    original = world.repo.get(TENANT_A, MatterId("m-alpha"))
    assert original is not None
    repo = SqlMatterRepository(qa_engine)
    repo.add(TENANT_A, original)
    with pytest.raises(ValueError, match="invalid expected revision"):
        repo.update(
            TENANT_A, replace(original, access=replace(original.access, revision=bad_revision))
        )
    with pytest.raises(ValueError, match="invalid expected revision"):
        repo.delete(TENANT_A, original.matter_id, expected_revision=bad_revision)
    assert repo.get(TENANT_A, original.matter_id) == original


def test_qa_hidden_content_is_not_selected_even_when_corrupted(
    qa_engine: Engine, world: World
) -> None:
    original = world.repo.get(TENANT_A, MatterId("m-alpha"))
    assert original is not None
    repo = SqlMatterRepository(qa_engine)
    repo.add(TENANT_A, original)
    with qa_engine.begin() as conn:
        conn.execute(matters.update().values(content_json="Invented secret malformed content"))
    statements: list[str] = []

    def observe(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        statements.append(statement.lower())

    event.listen(qa_engine, "before_cursor_execute", observe)
    try:
        assert repo.get_access(TENANT_A, original.matter_id) == original.access
        assert repo.count(TENANT_A, visible=lambda access: True) == 1
        assert repo.list(TENANT_A, visible=lambda access: False) == []
        assert repo.search(TENANT_A, "secret", visible=lambda access: False) == []
        assert repo.get(TENANT_B, original.matter_id) is None
        assert not any(
            "content_json" in query for query in statements if query.startswith("select")
        )
    finally:
        event.remove(qa_engine, "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "schema_bool",
        "revision_bool",
        "foreign_tenant",
        "foreign_matter",
        "profile_actor",
        "profile_tenant",
        "check_matter",
        "duplicate_members",
        "utc_naive",
    ],
)
def test_qa_corrupt_access_payload_fails_generic(world: World, mutation: str) -> None:
    access = world.access(TENANT_A, "m-alpha")
    payload = json.loads(encode_access(access))
    if mutation == "unknown":
        payload["invented_extra"] = "Invented secret marker"
    elif mutation == "schema_bool":
        payload["schema_version"] = True
    elif mutation == "revision_bool":
        payload["revision"] = True
    elif mutation == "foreign_tenant":
        payload["tenant_id"] = TENANT_B.value
    elif mutation == "foreign_matter":
        payload["matter_id"] = "unrelated-matter"
    elif mutation == "profile_actor":
        payload["conflict_check"]["recorder_profile"]["actor_id"] = "unrelated-actor"
    elif mutation == "profile_tenant":
        payload["conflict_check"]["recorder_profile"]["tenant_id"] = TENANT_B.value
    elif mutation == "check_matter":
        payload["conflict_check"]["matter_id"] = "unrelated-matter"
    elif mutation == "duplicate_members":
        payload["members"] = ["a-lawyer", "a-lawyer"]
    else:
        payload["conflict_check"]["recorded_at"] = "2026-10-13T09:00:00"
    with pytest.raises(StoredMatterError, match=r"^invalid stored matter$"):
        decode_access(json.dumps(payload), TENANT_A, access.matter_id, access.revision)


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":1,"schema_version":1,"title":"Synthetic","documents":[]}',
        '{"schema_version":1,"title":"Synthetic","documents":[{"document_id":"doc-1","title":"Synthetic","text":"first","text":"second"}]}',
        '{"schema_version":true,"title":"Synthetic","documents":[]}',
        '{"schema_version":1,"title":"Synthetic","documents":[],"extra":"Invented private marker"}',
        "[]",
        "{broken",
    ],
)
def test_qa_content_duplicate_unknown_or_invalid_json_is_generic(raw: str) -> None:
    with pytest.raises(StoredMatterError, match=r"^invalid stored matter$"):
        decode_content(raw)


@pytest.mark.parametrize("nested", [False, True])
def test_qa_duplicate_access_keys_are_not_silently_reinterpreted(
    world: World, nested: bool
) -> None:
    access = world.access(TENANT_A, "m-alpha")
    raw = encode_access(access)
    if nested:
        raw = raw.replace('"display_name":', '"display_name":"Invented impostor","display_name":')
    else:
        raw = raw.replace('"schema_version":1', '"schema_version":1,"schema_version":1')
    with pytest.raises(StoredMatterError, match=r"^invalid stored matter$"):
        decode_access(raw, TENANT_A, access.matter_id, access.revision)


def test_qa_corrupt_stored_binding_rejects_before_content_selection(
    qa_engine: Engine, world: World
) -> None:
    original = world.repo.get(TENANT_A, MatterId("m-alpha"))
    assert original is not None
    repo = SqlMatterRepository(qa_engine)
    repo.add(TENANT_A, original)
    payload = json.loads(encode_access(original.access))
    payload["matter_id"] = "unrelated-matter"
    with qa_engine.begin() as conn:
        conn.execute(
            matters.update().values(
                access_json=json.dumps(payload), content_json="Invented secret malformed content"
            )
        )
    with pytest.raises(StoredMatterError, match=r"^invalid stored matter$"):
        repo.get(TENANT_A, original.matter_id)


def test_qa_upgrade_0001_to_0002_preserves_audit_event_and_guards(
    tmp_path: Path, world: World
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'qa-upgrade.db'}")
    try:
        upgrade(engine, "0001_audit_chain")
        asyncio.run(world.service.get_matter(world.p("a-lawyer"), "m-alpha"))
        store = SqlAuditStore(engine)
        store.append(TENANT_A.value, world.sink.access_events[-1])
        with engine.begin() as conn:
            triggers_before = set(
                conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars()
            )
            events_before = conn.execute(text("SELECT hash FROM audit_events")).all()
        upgrade(engine, "0002_matters")
        with engine.begin() as conn:
            triggers_after = set(
                conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars()
            )
            assert conn.execute(text("SELECT hash FROM audit_events")).all() == events_before
            assert conn.execute(select(matters.c.matter_id)).all() == []
        assert triggers_after == triggers_before
        assert store.verify_chain(TENANT_A.value).ok
        with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
            conn.execute(text("UPDATE audit_events SET actor='Invented tamper'"))
    finally:
        engine.dispose()
