"""Verina audit package: event models and the durable hash-chained store (EN-8, ADR 004)."""

from verina.audit.events import (
    AccessAuditEvent,
    AIAuditEvent,
    AIAuditPayload,
    AIModelCallStarted,
    AuditEvent,
    AuditPayload,
    AuditPayloadError,
    register_payload_type,
)
from verina.audit.store import (
    AuditIntegrityError,
    DanglingCall,
    IntegrityIssue,
    IntegrityReport,
    SqlAuditStore,
    TenantAuditSink,
)

__all__ = [
    "AIAuditEvent",
    "AIAuditPayload",
    "AIModelCallStarted",
    "AccessAuditEvent",
    "AuditEvent",
    "AuditIntegrityError",
    "AuditPayload",
    "AuditPayloadError",
    "DanglingCall",
    "IntegrityIssue",
    "IntegrityReport",
    "SqlAuditStore",
    "TenantAuditSink",
    "register_payload_type",
]
