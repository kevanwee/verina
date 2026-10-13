"""Access decisions use the durable registered audit payload contract."""

import asyncio
import json
from pathlib import Path

import pytest

from verina.access import AccessDenied, MatterService
from verina.ai.audit import AuditEmissionError
from verina.audit import SqlAuditStore
from verina.db import make_engine, upgrade

from .conftest import World

pytestmark = pytest.mark.story("EN-7")


def test_access_decisions_survive_restart_without_document_content(
    world: World, tmp_path: Path
) -> None:
    url = f"sqlite:///{tmp_path / 'access.db'}"
    engine = make_engine(url)
    upgrade(engine)
    store = SqlAuditStore(engine)
    service = MatterService(
        repository=world.repo,
        policy=world.service._policy,
        identity=world.identity,
        audit_sink=store.for_tenant("tenant-a"),
        review_runner=world.runner,
    )
    try:
        asyncio.run(service.get_matter(world.p("a-lawyer"), "m-alpha"))
        with pytest.raises(AccessDenied):
            asyncio.run(service.get_matter(world.p("a-outsider"), "m-alpha"))
    finally:
        engine.dispose()
    reopened = make_engine(url)
    try:
        recovered = SqlAuditStore(reopened)
        events = recovered.events("tenant-a")
        assert [e.payload["decision"] for e in events] == ["allow", "deny"]
        assert all(e.event_type == "access.decision" for e in events)
        assert "Liability" not in json.dumps([e.payload for e in events])
        assert recovered.events("tenant-b") == []
        assert recovered.verify_chain("tenant-a").ok
    finally:
        reopened.dispose()


def test_wrong_tenant_audit_sink_blocks_content_read(world: World, tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'wrong-tenant.db'}")
    upgrade(engine)
    store = SqlAuditStore(engine)
    world.service._sink = store.for_tenant("tenant-b")
    world.repo.calls.clear()
    try:
        with pytest.raises(AuditEmissionError):
            asyncio.run(world.service.get_matter(world.p("a-lawyer"), "m-alpha"))
        assert "get" not in world.repo.calls
        assert store.events("tenant-a") == store.events("tenant-b") == []
    finally:
        engine.dispose()
