"""Verina AI package: the orchestrator is the only sanctioned path to a model.

See ``docs/adr/002-ai-orchestrator.md``.
"""

from verina.ai.audit import AuditEmissionError, AuditSink, InMemoryAuditSink
from verina.ai.client import (
    AnthropicClient,
    FakeModelClient,
    ModelClient,
    ModelClientError,
    ModelRequest,
    ModelResponse,
    UntrustedDocument,
)
from verina.ai.models import ModelRegistry, ModelRole, ModelSpec
from verina.ai.orchestrator import (
    Orchestrator,
    OrchestratorResult,
    RedactionPolicy,
    StaticRedactionPolicy,
)
from verina.ai.redaction import NoOpRedactor, RedactionMapping, Redactor, RegexRedactor
from verina.ai.templates import PromptTemplate, TemplateRegistry

__all__ = [
    "AnthropicClient",
    "AuditEmissionError",
    "AuditSink",
    "FakeModelClient",
    "InMemoryAuditSink",
    "ModelClient",
    "ModelClientError",
    "ModelRegistry",
    "ModelRequest",
    "ModelResponse",
    "ModelRole",
    "ModelSpec",
    "NoOpRedactor",
    "Orchestrator",
    "OrchestratorResult",
    "PromptTemplate",
    "RedactionMapping",
    "RedactionPolicy",
    "Redactor",
    "RegexRedactor",
    "StaticRedactionPolicy",
    "TemplateRegistry",
    "UntrustedDocument",
]
