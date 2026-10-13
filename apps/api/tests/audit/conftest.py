"""Audit store fixtures. Synthetic data only.

Every store test runs on SQLite (a fresh file per test). When ``VERINA_TEST_POSTGRES_URL``
is set (CI service container), the same tests also run on PostgreSQL; the schema is rebuilt
through Alembic before each test.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from verina.audit import AIAuditEvent, AIModelCallStarted, SqlAuditStore
from verina.audit.schema import audit_events
from verina.db import downgrade, make_engine, upgrade

POSTGRES_URL = os.environ.get("VERINA_TEST_POSTGRES_URL")
BACKENDS = ["sqlite", "postgresql"] if POSTGRES_URL else ["sqlite"]

HEAD_KEY = b"synthetic-test-head-key-0123456789abcdef"

_SQLITE_GUARDS = (
    "audit_events_no_update",
    "audit_events_no_delete",
    "audit_chain_head_no_delete",
    "audit_chain_head_forward_only",
)


@pytest.fixture(params=BACKENDS)
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    if request.param == "sqlite":
        eng = make_engine(f"sqlite:///{tmp_path / 'audit.db'}")
        upgrade(eng)
    else:
        assert POSTGRES_URL is not None
        eng = make_engine(POSTGRES_URL)
        downgrade(eng)
        upgrade(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> SqlAuditStore:
    return SqlAuditStore(engine)


@pytest.fixture
def keyed_store(engine: Engine) -> SqlAuditStore:
    return SqlAuditStore(engine, head_key=HEAD_KEY)


def drop_guards(engine: Engine) -> None:
    """Simulate a privileged attacker: remove the append-only triggers."""
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
            conn.execute(text("ALTER TABLE audit_chain_head DISABLE TRIGGER USER"))
        else:
            for name in _SQLITE_GUARDS:
                conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))


def tamper(engine: Engine, sql: str, **params: Any) -> None:
    drop_guards(engine)
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def tamper_insert(engine: Engine, **values: Any) -> None:
    """Insert a raw row behind the store's back (typed, so datetimes bind correctly)."""
    drop_guards(engine)
    with engine.begin() as conn:
        conn.execute(audit_events.insert().values(**values))


def started(matter_id: str = "M-001", actor: str = "user-7") -> AIModelCallStarted:
    return AIModelCallStarted(
        call_id=uuid4(),
        occurred_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
        matter_id=matter_id,
        actor=actor,
        task_role="triage",
        model_id="claude-haiku-5-5",
        effort="low",
        template_id="clause.triage",
        template_version="0.1.0",
        template_hash="sha256:" + "a" * 64,
        input_hash="sha256:" + "b" * 64,
        redaction_applied=True,
        redaction_counts={"EMAIL": 1},
    )


def completed(start: AIModelCallStarted, outcome: str = "success") -> AIAuditEvent:
    return AIAuditEvent.model_validate(
        {
            "call_id": start.call_id,
            "occurred_at": datetime(2026, 10, 13, 9, 0, 1, tzinfo=UTC),
            "matter_id": start.matter_id,
            "actor": start.actor,
            "task_role": start.task_role,
            "model_id": start.model_id,
            "served_model": start.model_id,
            "effort": start.effort,
            "template_id": start.template_id,
            "template_version": start.template_version,
            "template_hash": start.template_hash,
            "input_hash": start.input_hash,
            "output_hash": "sha256:" + "c" * 64,
            "input_tokens": 10,
            "output_tokens": 2,
            "latency_ms": 12.5,
            "redaction_applied": True,
            "redaction_counts": {"EMAIL": 1},
            "outcome": outcome,
        }
    )


def fill(store: SqlAuditStore, tenant_id: str, calls: int = 3) -> None:
    """Append ``calls`` start/completion pairs (2 * calls events)."""
    for _ in range(calls):
        start = started()
        store.append(tenant_id, start)
        store.append(tenant_id, completed(start))
