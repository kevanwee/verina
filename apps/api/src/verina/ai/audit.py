"""Audit sink used by the orchestrator.

The sink receives one :class:`~verina.audit.events.AIAuditEvent` per model call. EN-8 will
provide the append-only, hash-chained store behind this same protocol.
"""

from typing import Protocol, runtime_checkable

from verina.audit.events import AIAuditEvent


class AuditEmissionError(RuntimeError):
    """The audit sink failed. The orchestrator fails closed: no result is returned."""


@runtime_checkable
class AuditSink(Protocol):
    async def emit(self, event: AIAuditEvent) -> None: ...


class InMemoryAuditSink:
    """Keeps events in a list. For tests and local development only."""

    def __init__(self) -> None:
        self.events: list[AIAuditEvent] = []

    async def emit(self, event: AIAuditEvent) -> None:
        self.events.append(event)
