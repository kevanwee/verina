"""Audit sink used by the orchestrator.

For every model call the sink receives an :class:`~verina.audit.events.AIModelCallStarted`
before dispatch and an :class:`~verina.audit.events.AIAuditEvent` (completion) afterwards,
sharing a ``call_id`` (AI-4). The durable implementation is
:class:`verina.audit.store.TenantAuditSink` (``SqlAuditStore.for_tenant``), see ADR 004.
"""

from typing import Protocol, runtime_checkable

from verina.audit.events import AccessAuditEvent, AIAuditEvent, AIModelCallStarted, AuditPayload


class AuditEmissionError(RuntimeError):
    """The audit sink failed. The orchestrator fails closed: no result is returned."""


@runtime_checkable
class AuditSink(Protocol):
    async def emit(self, event: AuditPayload) -> None: ...


class InMemoryAuditSink:
    """Keeps events in lists. For tests and local development only.

    ``records`` holds everything in emission order; ``started`` the start records and
    ``events`` the completion records.
    """

    def __init__(self) -> None:
        self.records: list[AuditPayload] = []
        self.started: list[AIModelCallStarted] = []
        self.events: list[AIAuditEvent] = []
        self.access_events: list[AccessAuditEvent] = []

    async def emit(self, event: AuditPayload) -> None:
        self.records.append(event)
        if isinstance(event, AIModelCallStarted):
            self.started.append(event)
        elif isinstance(event, AIAuditEvent):
            self.events.append(event)
        else:
            self.access_events.append(event)

    @property
    def ai_events(self) -> list[AIAuditEvent]:
        return self.events
