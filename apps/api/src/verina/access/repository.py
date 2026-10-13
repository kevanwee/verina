"""Tenant-scoped matter repository (ADR 003; threats API-2, DS-1, API-8).

Every operation takes an explicit :class:`TenantId` first. Collection operations (list,
search, count) also take a mandatory ``visible`` predicate that is applied *inside* the query,
before text matching or counting, so non-visible matters never contribute hits or counts.
The in-memory store is partitioned by tenant: a lookup cannot reach another tenant's records.
A database adapter must keep the same contract (and add row-level security as a second layer).
"""

import builtins
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from verina.access.domain import MatterAccess, MatterId, MatterRecord, TenantId

AccessFilter = Callable[[MatterAccess], bool]
"""Authorization predicate for collection queries, supplied by the application service."""


class TenantMismatchError(ValueError):
    """A record was written under a tenant key that is not its own."""


@runtime_checkable
class MatterRepository(Protocol):
    def add(self, tenant_id: TenantId, record: MatterRecord) -> None: ...

    def get_access(self, tenant_id: TenantId, matter_id: MatterId) -> MatterAccess | None:
        """Access-control facts only; no content. Used to authorize before content reads."""
        ...

    def get(self, tenant_id: TenantId, matter_id: MatterId) -> MatterRecord | None: ...

    def list(
        self, tenant_id: TenantId, *, visible: AccessFilter
    ) -> builtins.list[MatterRecord]: ...

    def search(
        self, tenant_id: TenantId, text: str, *, visible: AccessFilter
    ) -> builtins.list[MatterRecord]: ...

    def count(self, tenant_id: TenantId, *, visible: AccessFilter) -> int: ...

    def update(self, tenant_id: TenantId, record: MatterRecord) -> bool: ...

    def delete(self, tenant_id: TenantId, matter_id: MatterId) -> bool: ...


def _require_tenant(tenant_id: object) -> TenantId:
    if not isinstance(tenant_id, TenantId):
        raise TypeError("a TenantId is required for every repository operation")
    return tenant_id


class InMemoryMatterRepository:
    """Synthetic, process-local store. Tests and local development only."""

    def __init__(self) -> None:
        self._partitions: dict[TenantId, dict[MatterId, MatterRecord]] = {}

    def _partition(self, tenant_id: object) -> dict[MatterId, MatterRecord]:
        return self._partitions.get(_require_tenant(tenant_id), {})

    @staticmethod
    def _check_owner(tenant_id: TenantId, record: MatterRecord) -> None:
        if record.tenant_id != tenant_id:
            raise TenantMismatchError("record tenant does not match the tenant key")

    def add(self, tenant_id: TenantId, record: MatterRecord) -> None:
        self._check_owner(_require_tenant(tenant_id), record)
        partition = self._partitions.setdefault(tenant_id, {})
        if record.matter_id in partition:
            raise ValueError("matter already exists")
        partition[record.matter_id] = record

    def get_access(self, tenant_id: TenantId, matter_id: MatterId) -> MatterAccess | None:
        record = self._partition(tenant_id).get(matter_id)
        return record.access if record is not None else None

    def get(self, tenant_id: TenantId, matter_id: MatterId) -> MatterRecord | None:
        return self._partition(tenant_id).get(matter_id)

    def list(self, tenant_id: TenantId, *, visible: AccessFilter) -> builtins.list[MatterRecord]:
        records = self._partition(tenant_id).values()
        return sorted((r for r in records if visible(r.access)), key=lambda r: r.matter_id.value)

    def search(
        self, tenant_id: TenantId, text: str, *, visible: AccessFilter
    ) -> builtins.list[MatterRecord]:
        needle = text.casefold().strip()
        if not needle:
            return []
        return [
            r
            for r in self.list(tenant_id, visible=visible)  # authorization first, then match
            if needle in r.content.title.casefold()
            or any(needle in d.text.casefold() for d in r.content.documents)
        ]

    def count(self, tenant_id: TenantId, *, visible: AccessFilter) -> int:
        return sum(1 for r in self._partition(tenant_id).values() if visible(r.access))

    def update(self, tenant_id: TenantId, record: MatterRecord) -> bool:
        self._check_owner(_require_tenant(tenant_id), record)
        partition = self._partition(tenant_id)
        if record.matter_id not in partition:
            return False
        partition[record.matter_id] = record
        return True

    def delete(self, tenant_id: TenantId, matter_id: MatterId) -> bool:
        return self._partition(tenant_id).pop(matter_id, None) is not None
