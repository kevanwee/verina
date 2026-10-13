"""EN-7/EN-8 shared boundary: tenant-bound registered access payloads."""

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from tests.audit.conftest import HEAD_KEY, drop_guards, fill, started, tamper
from verina.ai.audit import InMemoryAuditSink
from verina.audit import AccessAuditEvent, AuditPayloadError, SqlAuditStore
from verina.db import make_engine, upgrade


def access_event(tenant: str = "tenant-a") -> AccessAuditEvent:
    return AccessAuditEvent(
        occurred_at=datetime(2026, 10, 13, tzinfo=UTC),
        tenant_id=tenant,
        actor="lawyer-1",
        action="read_matter",
        matter_id="M-1",
        decision="deny",
        reason_code="matter_not_accessible",
        policy_version="test-1",
    )


def test_access_payload_persists_in_bound_tenant(store: SqlAuditStore) -> None:
    asyncio.run(store.for_tenant("tenant-a").emit(access_event()))
    event = store.events("tenant-a")[0]
    assert event.event_type == "access.decision"
    assert event.payload["decision"] == "deny"
    assert store.verify_chain("tenant-a").ok
    assert store.events("tenant-b") == []


def test_access_payload_cannot_claim_another_tenant(store: SqlAuditStore) -> None:
    with pytest.raises(AuditPayloadError, match="tenant"):
        asyncio.run(store.for_tenant("tenant-b").emit(access_event()))
    assert store.events("tenant-a") == store.events("tenant-b") == []


def test_memory_sink_keeps_access_out_of_ai_completions() -> None:
    sink = InMemoryAuditSink()
    event = access_event()
    asyncio.run(sink.emit(event))
    assert sink.records == sink.access_events == [event]
    assert sink.events == sink.ai_events == []
    assert sink.started == []


def test_store_survives_engine_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'durable.db'}"
    engine = make_engine(url)
    upgrade(engine)
    store = SqlAuditStore(engine, head_key=HEAD_KEY)
    original = store.append("tenant-a", started())
    engine.dispose()
    reopened = make_engine(url)
    try:
        recovered = SqlAuditStore(reopened, head_key=HEAD_KEY)
        assert recovered.events("tenant-a") == [original]
        assert recovered.verify_chain("tenant-a").ok
        assert recovered.append("tenant-a", started()).sequence == 2
    finally:
        reopened.dispose()


def test_valid_old_keyed_checkpoint_replay_is_documented_limit(engine: Engine) -> None:
    store = SqlAuditStore(engine, head_key=HEAD_KEY)
    fill(store, "tenant-a", calls=1)
    with engine.connect() as conn:
        checkpoint = conn.execute(text("SELECT * FROM audit_chain_head")).mappings().one()
        old = dict(checkpoint)
    fill(store, "tenant-a", calls=1)
    drop_guards(engine)
    tamper(engine, "DELETE FROM audit_events WHERE sequence > 2")
    tamper(
        engine,
        "UPDATE audit_chain_head SET last_sequence=:sequence, last_hash=:digest, head_mac=:mac",
        sequence=old["last_sequence"],
        digest=old["last_hash"],
        mac=old["head_mac"],
    )
    # A previously valid HMAC authenticates an old checkpoint too. Freshness requires
    # an independently retained checkpoint; this slice does not implement one.
    assert store.verify_chain("tenant-a").ok


def test_verification_remains_consistent_during_concurrent_append(store: SqlAuditStore) -> None:
    errors: list[BaseException] = []
    finished = threading.Event()

    def write() -> None:
        try:
            for _ in range(20):
                store.append("tenant-a", started())
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    writer = threading.Thread(target=write)
    writer.start()
    try:
        while not finished.is_set():
            assert store.verify_chain("tenant-a").ok
    finally:
        writer.join(timeout=30)
    assert not writer.is_alive()
    assert errors == []
    assert store.verify_chain("tenant-a").event_count == 20


def test_whole_tenant_deletion_needs_independent_existence_record(engine: Engine) -> None:
    store = SqlAuditStore(engine, head_key=HEAD_KEY)
    fill(store, "tenant-a", calls=1)
    tamper(engine, "DELETE FROM audit_events WHERE tenant_id='tenant-a'")
    tamper(engine, "DELETE FROM audit_chain_head WHERE tenant_id='tenant-a'")
    report = store.verify_chain("tenant-a")
    assert report.ok and report.event_count == 0 and report.head_sequence is None
