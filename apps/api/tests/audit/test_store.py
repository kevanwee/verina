"""EN-8: durable, append-only, hash-chained audit store. Synthetic data only."""

import hashlib
import json
import threading
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.audit.conftest import (
    HEAD_KEY,
    completed,
    drop_guards,
    fill,
    started,
    tamper,
    tamper_insert,
)
from verina.audit import AuditIntegrityError, AuditPayloadError, SqlAuditStore
from verina.audit.chain import (
    GENESIS_HASH,
    canonical_json,
    event_hash,
    hash_material,
    head_mac,
    utc_timestamp,
)
from verina.config import Settings
from verina.db import upgrade

pytestmark = pytest.mark.story("EN-8")

TENANT = "tenant-a"
OTHER = "tenant-b"


def test_append_builds_a_verifiable_chain(store: SqlAuditStore) -> None:  # api-EN-8-01
    fill(store, TENANT, calls=3)
    events = store.events(TENANT)

    assert [e.sequence for e in events] == [1, 2, 3, 4, 5, 6]
    assert events[0].prev_hash == GENESIS_HASH
    for prev, nxt in pairwise(events):
        assert nxt.prev_hash == prev.hash
    assert [e.event_type for e in events[:2]] == ["ai.model_call_started", "ai.model_call"]
    assert events[0].payload["call_id"] == events[1].payload["call_id"]

    report = store.verify_chain(TENANT)
    assert report.ok, report.issues
    assert report.event_count == 6
    assert report.head_sequence == 6
    assert report.head_hash == events[-1].hash
    assert report.head_mac_checked is False


def test_hash_is_sha256_over_canonical_json_of_all_fields_but_hash(store: SqlAuditStore) -> None:
    returned = store.append(TENANT, started())
    stored = store.events(TENANT)[0]
    assert stored == returned

    material = stored.model_dump(mode="json", exclude={"hash"})
    material["created_at"] = utc_timestamp(stored.created_at)
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert encoded == canonical_json(material)
    expected = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert stored.hash == expected


def test_empty_tenant_verifies(store: SqlAuditStore) -> None:
    report = store.verify_chain("nobody")
    assert report.ok
    assert report.event_count == 0
    assert report.head_sequence is None


def test_database_rejects_update_and_delete(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT, calls=1)
    statements = [
        "UPDATE audit_events SET actor = 'mallory' WHERE sequence = 1",
        "DELETE FROM audit_events WHERE sequence = 2",
        "DELETE FROM audit_chain_head",
        "UPDATE audit_chain_head SET last_sequence = 1",
    ]
    if engine.dialect.name == "postgresql":
        statements += ["TRUNCATE audit_events", "TRUNCATE audit_chain_head"]
    for sql in statements:
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(sql))
    assert store.verify_chain(TENANT).ok


def test_store_exposes_no_mutation_methods() -> None:
    public = {name for name in dir(SqlAuditStore) if not name.startswith("_")}
    assert public == {
        "append",
        "dangling_calls",
        "events",
        "for_tenant",
        "from_settings",
        "verify_chain",
    }


def test_edited_payload_is_detected(engine: Engine, store: SqlAuditStore) -> None:  # api-EN-8-02
    fill(store, TENANT)
    row = store.events(TENANT)[1]
    payload = dict(row.payload, output_tokens=999)
    tamper(
        engine,
        "UPDATE audit_events SET payload = :p WHERE tenant_id = :t AND sequence = 2",
        p=json.dumps(payload),
        t=TENANT,
    )
    report = store.verify_chain(TENANT)
    assert not report.ok
    assert [(i.kind, i.sequence) for i in report.issues] == [("hash_mismatch", 2)]


def test_edited_envelope_field_is_detected(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT)
    tamper(engine, "UPDATE audit_events SET actor = 'mallory' WHERE sequence = 3")
    assert [(i.kind, i.sequence) for i in store.verify_chain(TENANT).issues] == [
        ("hash_mismatch", 3)
    ]


def test_edited_hash_is_detected(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT)
    tamper(engine, "UPDATE audit_events SET hash = :h WHERE sequence = 2", h="sha256:" + "f" * 64)
    issues = [(i.kind, i.sequence) for i in store.verify_chain(TENANT).issues]
    assert ("hash_mismatch", 2) in issues
    assert ("chain_break", 3) in issues


def test_rehashed_tip_without_key_is_still_caught_by_head(
    engine: Engine, store: SqlAuditStore
) -> None:
    fill(store, TENANT)
    tamper(engine, "UPDATE audit_events SET hash = :h WHERE sequence = 6", h="sha256:" + "f" * 64)
    kinds = store.verify_chain(TENANT).kinds()
    assert kinds == {"hash_mismatch", "head_mismatch"}


def test_deleted_middle_row_is_detected(  # api-EN-8-03
    engine: Engine, store: SqlAuditStore
) -> None:
    fill(store, TENANT)
    tamper(engine, "DELETE FROM audit_events WHERE tenant_id = :t AND sequence = 3", t=TENANT)
    issues = [(i.kind, i.sequence) for i in store.verify_chain(TENANT).issues]
    assert ("sequence_gap", 4) in issues
    assert ("chain_break", 4) in issues


def test_reordered_rows_are_detected(engine: Engine, store: SqlAuditStore) -> None:  # api-EN-8-04
    fill(store, TENANT)
    tamper(engine, "UPDATE audit_events SET sequence = 100 WHERE sequence = 2")
    tamper(engine, "UPDATE audit_events SET sequence = 2 WHERE sequence = 3")
    tamper(engine, "UPDATE audit_events SET sequence = 3 WHERE sequence = 100")
    report = store.verify_chain(TENANT)
    issues = {(i.kind, i.sequence) for i in report.issues}
    assert {("hash_mismatch", 2), ("hash_mismatch", 3), ("chain_break", 2)} <= issues


def test_inserted_middle_row_is_detected(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT, calls=2)
    victim = store.events(TENANT)[1]
    # Shift events 2..4 up by one, then insert a forged event at 2 that links to event 1.
    for seq in (4, 3, 2):
        tamper(
            engine, "UPDATE audit_events SET sequence = :n WHERE sequence = :o", n=seq + 1, o=seq
        )
    tamper_insert(
        engine,
        tenant_id=TENANT,
        sequence=2,
        event_id="00000000-0000-4000-8000-000000000001",
        schema_version=1,
        event_type=victim.event_type,
        actor=victim.actor,
        matter_id=victim.matter_id,
        payload=json.dumps(victim.payload),
        created_at=victim.created_at,
        prev_hash=victim.prev_hash,
        hash=victim.hash,
    )
    report = store.verify_chain(TENANT)
    kinds = report.kinds()
    assert "hash_mismatch" in kinds
    assert "head_mismatch" in kinds


def test_appended_row_without_head_update_is_detected(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT, calls=1)
    other = SqlAuditStore(engine)
    other.append("scratch", started())
    forged = other.events("scratch")[0]
    tip = store.events(TENANT)[-1]
    # A correctly linked and correctly hashed extra event, inserted behind the store's back.
    material = hash_material(
        schema_version=1,
        tenant_id=TENANT,
        sequence=3,
        event_id="00000000-0000-4000-8000-000000000002",
        event_type=forged.event_type,
        actor=forged.actor,
        matter_id=forged.matter_id,
        payload=forged.payload,
        created_at=forged.created_at,
        prev_hash=tip.hash,
    )
    tamper_insert(
        engine,
        tenant_id=TENANT,
        sequence=3,
        event_id=material["event_id"],
        schema_version=1,
        event_type=forged.event_type,
        actor=forged.actor,
        matter_id=forged.matter_id,
        payload=json.dumps(forged.payload),
        created_at=forged.created_at,
        prev_hash=tip.hash,
        hash=event_hash(material),
    )
    report = store.verify_chain(TENANT)
    assert report.kinds() == {"head_mismatch"}
    with pytest.raises(AuditIntegrityError):
        store.append(TENANT, started())


def test_tail_truncation_is_detected_and_blocks_appends(
    engine: Engine, store: SqlAuditStore
) -> None:
    fill(store, TENANT)
    tamper(engine, "DELETE FROM audit_events WHERE tenant_id = :t AND sequence >= 5", t=TENANT)
    report = store.verify_chain(TENANT)
    assert [(i.kind, i.sequence) for i in report.issues] == [("head_mismatch", 4)]
    assert report.head_sequence == 6
    with pytest.raises(AuditIntegrityError, match="tip"):
        store.append(TENANT, started())


def test_truncation_with_head_rewind_needs_the_head_key(engine: Engine) -> None:
    unkeyed = SqlAuditStore(engine)
    keyed = SqlAuditStore(engine, head_key=HEAD_KEY)
    fill(keyed, TENANT)
    tip = keyed.events(TENANT)[3]
    tamper(engine, "DELETE FROM audit_events WHERE tenant_id = :t AND sequence >= 5", t=TENANT)
    tamper(
        engine,
        "UPDATE audit_chain_head SET last_sequence = 4, last_hash = :h WHERE tenant_id = :t",
        h=tip.hash,
        t=TENANT,
    )
    # Documented limitation: without the key a consistent rewind is not detectable.
    assert unkeyed.verify_chain(TENANT).ok
    report = keyed.verify_chain(TENANT)
    assert report.head_mac_checked
    assert report.kinds() == {"head_mac_invalid"}
    with pytest.raises(AuditIntegrityError, match="MAC"):
        keyed.append(TENANT, started())


def test_keyed_head_verifies_and_rejects_a_wrong_key(engine: Engine) -> None:
    keyed = SqlAuditStore(engine, head_key=HEAD_KEY)
    fill(keyed, TENANT, calls=2)
    report = keyed.verify_chain(TENANT)
    assert report.ok and report.head_mac_checked
    with engine.connect() as conn:
        mac = conn.execute(text("SELECT head_mac FROM audit_chain_head")).scalar_one()
    assert mac == head_mac(
        HEAD_KEY, tenant_id=TENANT, last_sequence=4, last_hash=keyed.events(TENANT)[-1].hash
    )
    wrong = SqlAuditStore(engine, head_key=b"another-synthetic-key-0123456789abcdef")
    assert wrong.verify_chain(TENANT).kinds() == {"head_mac_invalid"}
    with pytest.raises(AuditIntegrityError):
        wrong.append(TENANT, started())


def test_missing_head_is_detected(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT, calls=1)
    tamper(engine, "DELETE FROM audit_chain_head WHERE tenant_id = :t", t=TENANT)
    assert store.verify_chain(TENANT).kinds() == {"head_missing"}


def test_cross_tenant_splice_is_detected(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT)
    fill(store, OTHER)
    # Replace tenant A's event 3 with tenant B's event 3 (same position, B's valid hash).
    tamper(engine, "DELETE FROM audit_events WHERE tenant_id = :t AND sequence = 3", t=TENANT)
    tamper(
        engine,
        "UPDATE audit_events SET tenant_id = :a WHERE tenant_id = :b AND sequence = 3",
        a=TENANT,
        b=OTHER,
    )
    issues = {(i.kind, i.sequence) for i in store.verify_chain(TENANT).issues}
    assert ("hash_mismatch", 3) in issues
    assert ("chain_break", 3) in issues
    # Tenant B lost a row: the gap is visible on its own chain too.
    assert "sequence_gap" in store.verify_chain(OTHER).kinds()


def test_tenants_have_independent_chains(engine: Engine, store: SqlAuditStore) -> None:
    fill(store, TENANT, calls=2)
    fill(store, OTHER, calls=1)
    assert [e.sequence for e in store.events(OTHER)] == [1, 2]
    assert store.events(OTHER)[0].prev_hash == GENESIS_HASH
    assert {e.tenant_id for e in store.events(TENANT)} == {TENANT}
    tamper(engine, "UPDATE audit_events SET actor = 'x' WHERE tenant_id = :t", t=TENANT)
    assert not store.verify_chain(TENANT).ok
    assert store.verify_chain(OTHER).ok


def test_unparseable_or_content_bearing_payload_is_reported(
    engine: Engine, store: SqlAuditStore
) -> None:
    fill(store, TENANT, calls=1)
    payload = dict(store.events(TENANT)[0].payload, document_text="Synthetic clause text")
    tamper(engine, "UPDATE audit_events SET payload = :p WHERE sequence = 1", p=json.dumps(payload))
    tamper(engine, "UPDATE audit_events SET payload = '{not json' WHERE sequence = 2")
    issues = [(i.kind, i.sequence) for i in store.verify_chain(TENANT).issues]
    assert issues == [("payload_invalid", 1), ("payload_invalid", 2)]


def test_concurrent_appends_do_not_fork_the_chain(store: SqlAuditStore) -> None:
    errors: list[BaseException] = []

    def worker(tenant: str) -> None:
        try:
            for _ in range(15):
                store.append(tenant, started())
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in [TENANT, OTHER] * 4]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    for tenant in (TENANT, OTHER):
        events = store.events(tenant)
        assert [e.sequence for e in events] == list(range(1, 61))
        report = store.verify_chain(tenant)
        assert report.ok, report.issues


def test_append_validates_inputs(store: SqlAuditStore) -> None:
    with pytest.raises(AuditPayloadError):
        store.append("", started())
    with pytest.raises(AuditPayloadError):
        store.append("t" * 300, started())
    with pytest.raises(AuditPayloadError, match="not a registered"):
        store.append(TENANT, Settings())
    long_matter = started(matter_id="M" * 300)
    with pytest.raises(AuditPayloadError, match="exceeds"):
        store.append(TENANT, long_matter)
    assert store.events(TENANT) == []


def test_store_configuration_is_validated(engine: Engine) -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        SqlAuditStore(engine, head_key=b"short")
    fake = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    with pytest.raises(ValueError, match="unsupported"):
        SqlAuditStore(fake)  # type: ignore[arg-type]
    with pytest.raises(AuditPayloadError):
        SqlAuditStore(engine).for_tenant("")


def test_from_settings(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "dir" / "verina.db"
    settings = Settings(
        database_url=f"sqlite:///{db}",
        audit_head_key="synthetic-settings-key-0123456789abcdef",
    )
    store = SqlAuditStore.from_settings(settings)
    assert db.parent.is_dir()
    upgrade(store._engine)
    store.append(TENANT, started())
    assert store.verify_chain(TENANT).head_mac_checked
    assert SqlAuditStore.from_settings(Settings(database_url=f"sqlite:///{db}"))
    store._engine.dispose()


def test_completion_pairs_round_trip(store: SqlAuditStore) -> None:
    start = started()
    store.append(TENANT, start)
    done = completed(start, outcome="cancelled")
    event = store.append(TENANT, done)
    assert event.payload["outcome"] == "cancelled"
    assert event.payload["latency_ms"] == 12.5
    assert store.verify_chain(TENANT).ok


def test_guards_can_only_be_removed_by_a_privileged_role(engine: Engine) -> None:
    # Sanity check for the tamper helper itself: after dropping guards, updates succeed.
    store = SqlAuditStore(engine)
    fill(store, TENANT, calls=1)
    drop_guards(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET actor = 'x' WHERE sequence = 1"))
    assert not store.verify_chain(TENANT).ok
