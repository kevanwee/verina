"""Shared fixtures for AI orchestrator tests. All data is synthetic; no network is used."""

from datetime import UTC, datetime

import pytest

from verina.ai import (
    FakeModelClient,
    InMemoryAuditSink,
    ModelRegistry,
    Orchestrator,
    StaticRedactionPolicy,
    TemplateRegistry,
)
from verina.config import Settings

FIXED_NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


@pytest.fixture
def settings() -> Settings:
    return Settings(env="test")


@pytest.fixture
def fake_client() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def sink() -> InMemoryAuditSink:
    return InMemoryAuditSink()


def make_orchestrator(
    client: FakeModelClient,
    sink: InMemoryAuditSink,
    settings: Settings,
    *,
    redaction: bool = True,
) -> Orchestrator:
    ticks = iter([1.000, 1.250, 2.000, 2.500, 3.000, 3.500])
    return Orchestrator(
        client=client,
        models=ModelRegistry.from_settings(settings),
        templates=TemplateRegistry.load_default(),
        audit_sink=sink,
        redaction_policy=StaticRedactionPolicy(enabled=redaction),
        clock=lambda: FIXED_NOW,
        timer=lambda: next(ticks),
    )
