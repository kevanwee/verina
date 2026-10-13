"""AI-4: start and completion records around every model call, and dangling-call detection."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.ai.conftest import make_orchestrator
from tests.audit.conftest import completed, started
from verina.ai import FakeModelClient, InMemoryAuditSink, ModelClientError, ModelRequest
from verina.ai.audit import AuditEmissionError, AuditSink
from verina.ai.client import ModelResponse
from verina.audit import AIAuditEvent, AIModelCallStarted, AuditPayload, SqlAuditStore
from verina.config import Settings

pytestmark = pytest.mark.story("AI-4")

TENANT = "tenant-a"
VARIABLES = {"contract_type": "mutual NDA", "perspective": "recipient"}


def _run(orch: object) -> None:
    asyncio.run(orch.run("triage", "clause.triage", VARIABLES, [], "M-1", "u-1"))  # type: ignore[attr-defined]


def test_start_and_completion_share_a_call_id_and_verify(store: SqlAuditStore) -> None:
    sink = store.for_tenant(TENANT)
    assert isinstance(sink, AuditSink)
    orch = make_orchestrator(FakeModelClient(), sink, Settings(env="test"))
    _run(orch)
    _run(orch)

    events = store.events(TENANT)
    assert [e.event_type for e in events] == [
        "ai.model_call_started",
        "ai.model_call",
        "ai.model_call_started",
        "ai.model_call",
    ]
    assert events[0].payload["call_id"] == events[1].payload["call_id"]
    assert events[0].payload["call_id"] != events[2].payload["call_id"]
    assert events[0].payload["input_hash"] == events[1].payload["input_hash"]
    assert events[1].payload["outcome"] == "success"
    assert all(e.matter_id == "M-1" and e.actor == "u-1" for e in events)
    assert store.verify_chain(TENANT).ok
    assert store.dangling_calls(TENANT) == []


def test_in_memory_sink_records_start_before_completion() -> None:
    sink = InMemoryAuditSink()
    client = FakeModelClient()
    orch = make_orchestrator(client, sink, Settings(env="test"))
    _run(orch)
    assert len(sink.records) == 2
    start, done = sink.records
    assert isinstance(start, AIModelCallStarted)
    assert isinstance(done, AIAuditEvent)
    assert sink.started == [start]
    assert sink.events == [done]
    assert start.call_id == done.call_id
    assert start.input_hash == done.input_hash


def test_failed_call_completes_with_error(store: SqlAuditStore) -> None:
    client = FakeModelClient(error=ModelClientError("boom", retryable=False))
    orch = make_orchestrator(client, store.for_tenant(TENANT), Settings(env="test"))
    with pytest.raises(ModelClientError):
        _run(orch)
    events = store.events(TENANT)
    assert events[1].payload["outcome"] == "error"
    assert store.dangling_calls(TENANT) == []


def test_crash_mid_call_leaves_a_dangling_call(store: SqlAuditStore) -> None:
    class ProcessDies(BaseException):
        """Stands in for a process kill: nothing after the call runs."""

    async def die(_request: ModelRequest) -> ModelResponse:
        raise ProcessDies

    client = FakeModelClient()
    client.complete = die  # type: ignore[method-assign, assignment]
    orch = make_orchestrator(client, store.for_tenant(TENANT), Settings(env="test"))
    with pytest.raises(ProcessDies):
        _run(orch)

    events = store.events(TENANT)
    assert [e.event_type for e in events] == ["ai.model_call_started"]
    dangling = store.dangling_calls(TENANT)
    assert len(dangling) == 1
    call = dangling[0]
    assert str(call.call_id) == events[0].payload["call_id"]
    assert (call.matter_id, call.actor, call.task_role, call.sequence) == (
        "M-1",
        "u-1",
        "triage",
        1,
    )
    assert store.verify_chain(TENANT).ok  # the chain is intact; the call is just unfinished


def test_cancelled_call_is_recorded_as_cancelled(store: SqlAuditStore) -> None:
    gate = asyncio.Event()

    async def hang(_request: ModelRequest) -> ModelResponse:
        await gate.wait()
        raise AssertionError("unreachable")

    client = FakeModelClient()
    client.complete = hang  # type: ignore[method-assign, assignment]
    orch = make_orchestrator(client, store.for_tenant(TENANT), Settings(env="test"))

    async def scenario() -> None:
        task = asyncio.create_task(orch.run("triage", "clause.triage", VARIABLES, [], "M-1", "u-1"))
        while not store.events(TENANT):
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    events = store.events(TENANT)
    assert [e.event_type for e in events] == ["ai.model_call_started", "ai.model_call"]
    assert events[1].payload["outcome"] == "cancelled"
    assert store.dangling_calls(TENANT) == []


def test_start_emission_failure_makes_no_model_call() -> None:
    class BrokenSink:
        async def emit(self, event: AuditPayload) -> None:
            raise OSError("disk full")

    client = FakeModelClient()
    orch = make_orchestrator(client, BrokenSink(), Settings(env="test"))
    with pytest.raises(AuditEmissionError):
        _run(orch)
    assert client.requests == []


def test_dangling_calls_respects_in_flight_window(store: SqlAuditStore) -> None:
    first = started()
    store.append(TENANT, first)
    store.append(TENANT, completed(first))
    second = started(matter_id="M-2")
    store.append(TENANT, second)
    store.append("tenant-b", started())

    now = datetime.now(UTC) + timedelta(seconds=30)  # ages use the store's append time
    assert [c.call_id for c in store.dangling_calls(TENANT, now=now)] == [second.call_id]
    assert store.dangling_calls(TENANT, older_than=timedelta(minutes=5), now=now) == []
    assert len(store.dangling_calls("tenant-b", now=now)) == 1
    assert store.dangling_calls("tenant-c") == []
