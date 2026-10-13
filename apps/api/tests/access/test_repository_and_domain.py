"""Repository tenant-key contract and domain value tests (EN-7; DS-1, API-8)."""

from dataclasses import replace
from typing import cast

import pytest

from verina.access import (
    ActorId,
    InMemoryMatterRepository,
    InvalidIdentifierError,
    MatterAccess,
    MatterContent,
    MatterId,
    MatterRecord,
    MatterRepository,
    TenantId,
    TenantMismatchError,
)

from .conftest import TENANT_A, TENANT_B, seed_matters

pytestmark = pytest.mark.story("EN-7")


def everything(_: MatterAccess) -> bool:
    return True


def nothing(_: MatterAccess) -> bool:
    return False


@pytest.fixture
def repo() -> InMemoryMatterRepository:
    r = InMemoryMatterRepository()
    for record in seed_matters():
        r.add(record.tenant_id, record)
    return r


def test_in_memory_repository_satisfies_protocol(repo: InMemoryMatterRepository) -> None:
    assert isinstance(repo, MatterRepository)


@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.get("tenant-a", MatterId("m-alpha")),
        lambda r: r.get_access(None, MatterId("m-alpha")),
        lambda r: r.list("tenant-a", visible=everything),
        lambda r: r.search(ActorId("tenant-a"), "x", visible=everything),
        lambda r: r.count("tenant-a", visible=everything),
        lambda r: r.delete("tenant-a", MatterId("m-alpha"), expected_revision=1),
    ],
)
def test_every_operation_requires_a_tenant_key(
    repo: InMemoryMatterRepository, call: object
) -> None:
    with pytest.raises(TypeError, match="TenantId"):
        call(repo)  # type: ignore[operator]


def test_queries_are_partitioned_by_tenant(repo: InMemoryMatterRepository) -> None:
    assert repo.get(TENANT_A, MatterId("m-bravo")) is None
    assert repo.get_access(TENANT_A, MatterId("m-bravo")) is None
    assert [r.matter_id.value for r in repo.list(TENANT_B, visible=everything)] == [
        "m-bravo",
        "m-shared",
    ]
    assert repo.count(TENANT_A, visible=everything) == 4
    assert repo.count(TENANT_A, visible=nothing) == 0
    assert repo.count(TenantId("tenant-unknown"), visible=everything) == 0
    hits = repo.search(TENANT_A, "LIABILITY", visible=everything)
    assert [r.matter_id.value for r in hits] == ["m-alpha", "m-gamma"]
    assert repo.search(TENANT_A, "liability", visible=nothing) == []
    assert repo.search(TENANT_A, "   ", visible=everything) == []


def test_cross_tenant_writes_rejected(repo: InMemoryMatterRepository) -> None:
    bravo = repo.get(TENANT_B, MatterId("m-bravo"))
    assert bravo is not None
    with pytest.raises(TenantMismatchError):
        repo.update(TENANT_A, replace(bravo, content=MatterContent("overwritten")))
    with pytest.raises(TenantMismatchError):
        repo.add(TENANT_A, bravo)
    assert repo.delete(TENANT_A, MatterId("m-bravo"), expected_revision=1) is False
    assert repo.get(TENANT_B, MatterId("m-bravo")) == bravo
    ghost = MatterRecord(MatterAccess(TENANT_A, MatterId("m-ghost")), MatterContent("ghost"))
    assert repo.update(TENANT_A, ghost) is False
    with pytest.raises(ValueError, match="exists"):
        repo.add(TENANT_B, bravo)


@pytest.mark.parametrize("raw", ["", " a", "a b", "../x", "x" * 129, "é", "a\n"])
def test_identifiers_validate(raw: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        TenantId(raw)
    assert MatterId.parse(raw) is None


def test_identifier_types_are_distinct_values() -> None:
    assert TenantId("x") != cast(object, ActorId("x"))
    assert str(MatterId("m-1")) == "m-1"
    assert MatterId.parse(MatterId("m-1")) == MatterId("m-1")
    assert MatterId.parse(42) is None
    with pytest.raises(InvalidIdentifierError):
        ActorId(42)  # type: ignore[arg-type]
