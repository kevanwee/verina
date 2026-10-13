"""The single entry point for model calls (AGENTS.md section 4, FR-9.2, NFR-7).

``Orchestrator.run`` does, in order:

1. resolve the model for the task role and load the versioned template;
2. if redaction is enabled for the tenant/matter, pseudonymise variables, document titles
   and document text with one shared mapping (nothing unredacted leaves the process);
3. render instructions from variables only; documents travel as separate untrusted blocks;
4. emit an :class:`~verina.audit.events.AIModelCallStarted` record (AI-4). If the sink
   fails here, no model call is made;
5. call the model client;
6. re-identify placeholders in the output (the mapping never leaves the process);
7. emit exactly one completion :class:`~verina.audit.events.AIAuditEvent` with the same
   ``call_id``, on success, on a failed call (``error``) and on task cancellation
   (``cancelled``). If the audit sink fails, the run fails (fail closed).

A process crash between steps 4 and 7 leaves a start without a completion: a *dangling
call*, listed by :meth:`verina.audit.store.SqlAuditStore.dangling_calls`.

Validation errors raised before step 4 (unknown role, missing template, wrong variables)
make no model call and therefore emit no event.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from verina.ai._hashing import canonical_json, sha256_hex
from verina.ai.audit import AuditEmissionError, AuditSink
from verina.ai.client import ModelClient, ModelRequest, ModelResponse, UntrustedDocument
from verina.ai.models import ModelRegistry, ModelRole
from verina.ai.redaction import NoOpRedactor, RedactionMapping, Redactor, RegexRedactor
from verina.ai.templates import PromptTemplate, TemplateError, TemplateRegistry
from verina.audit.events import AIAuditEvent, AIAuditPayload, AIModelCallStarted

logger = logging.getLogger(__name__)


class RedactionPolicy(Protocol):
    """Decides whether redaction runs for a matter (tenant AI policy, FR-9.3)."""

    def redaction_enabled(self, matter_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class StaticRedactionPolicy:
    """Same answer for every matter. Default comes from ``VERINA_AI_REDACTION_ENABLED``."""

    enabled: bool = True

    def redaction_enabled(self, matter_id: str) -> bool:
        return self.enabled


class TemplateRoleMismatchError(TemplateError):
    """The template was written for a different task role than the one requested."""


@dataclass(frozen=True, slots=True)
class OrchestratorResult:
    text: str
    """Model output with placeholders re-identified."""
    stop_reason: str | None
    audit_event: AIAuditEvent


class Orchestrator:
    def __init__(
        self,
        *,
        client: ModelClient,
        models: ModelRegistry,
        templates: TemplateRegistry,
        audit_sink: AuditSink,
        redactor: Redactor | None = None,
        redaction_policy: RedactionPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._client = client
        self._models = models
        self._templates = templates
        self._sink = audit_sink
        self._redactor: Redactor = redactor if redactor is not None else RegexRedactor()
        self._policy: RedactionPolicy = (
            redaction_policy if redaction_policy is not None else StaticRedactionPolicy()
        )
        self._clock = clock
        self._timer = timer

    async def run(
        self,
        task_role: str | ModelRole,
        template_id: str,
        variables: Mapping[str, str],
        documents: Sequence[UntrustedDocument],
        matter_id: str,
        actor: str,
        *,
        template_version: str | None = None,
    ) -> OrchestratorResult:
        if not matter_id or not actor:
            raise ValueError("matter_id and actor are required for every model call")
        role = ModelRegistry.parse_role(task_role)
        spec = self._models.resolve(role)
        template = self._templates.get(template_id, template_version)
        if template.role is not role:
            raise TemplateRoleMismatchError(
                f"{template.ref} is a {template.role.value} template, not {role.value}"
            )

        redaction_on = self._policy.redaction_enabled(matter_id)
        redactor: Redactor = self._redactor if redaction_on else NoOpRedactor()
        safe_vars, safe_docs, mapping = self._redact_inputs(redactor, variables, documents)

        request = ModelRequest(
            model=spec.model_id,
            system=template.system_prompt,
            instructions=template.render(safe_vars),
            documents=safe_docs,
            max_tokens=spec.max_tokens,
            effort=spec.effort,
            output_schema=template.output_schema,
        )
        input_hash = sha256_hex(canonical_json(request.canonical()))
        call_id = uuid4()
        await self._emit(
            AIModelCallStarted(
                call_id=call_id,
                occurred_at=self._clock(),
                matter_id=matter_id,
                actor=actor,
                task_role=role.value,
                model_id=request.model,
                effort=request.effort,
                template_id=template.id,
                template_version=template.version,
                template_hash=template.content_hash,
                input_hash=input_hash,
                redaction_applied=redaction_on,
                redaction_counts=mapping.counts() if redaction_on else {},
            )
        )

        started = self._timer()
        try:
            response = await self._client.complete(request)
        except (Exception, asyncio.CancelledError) as exc:
            latency_ms = (self._timer() - started) * 1000
            event = self._event(
                call_id,
                matter_id,
                actor,
                role,
                request,
                template,
                input_hash,
                latency_ms,
                redaction_on,
                mapping,
                response=None,
                error=exc,
            )
            await self._emit(event)
            raise

        latency_ms = (self._timer() - started) * 1000
        event = self._event(
            call_id,
            matter_id,
            actor,
            role,
            request,
            template,
            input_hash,
            latency_ms,
            redaction_on,
            mapping,
            response=response,
            error=None,
        )
        await self._emit(event)
        return OrchestratorResult(
            text=redactor.reidentify(response.text, mapping),
            stop_reason=response.stop_reason,
            audit_event=event,
        )

    @staticmethod
    def _redact_inputs(
        redactor: Redactor,
        variables: Mapping[str, str],
        documents: Sequence[UntrustedDocument],
    ) -> tuple[dict[str, str], tuple[UntrustedDocument, ...], RedactionMapping]:
        mapping = RedactionMapping()
        safe_vars: dict[str, str] = {}
        for name in sorted(variables):
            value = variables[name]
            if not isinstance(value, str):
                raise TemplateError(f"variable {name!r} must be a string")
            safe_vars[name], mapping = redactor.redact(value, mapping)
        safe_docs: list[UntrustedDocument] = []
        for doc in documents:
            title, mapping = redactor.redact(doc.title, mapping)
            text, mapping = redactor.redact(doc.text, mapping)
            safe_docs.append(UntrustedDocument(document_id=doc.document_id, title=title, text=text))
        return safe_vars, tuple(safe_docs), mapping

    def _event(
        self,
        call_id: UUID,
        matter_id: str,
        actor: str,
        role: ModelRole,
        request: ModelRequest,
        template: PromptTemplate,
        input_hash: str,
        latency_ms: float,
        redaction_on: bool,
        mapping: RedactionMapping,
        *,
        response: ModelResponse | None,
        error: BaseException | None,
    ) -> AIAuditEvent:
        outcome: Literal["success", "error", "cancelled"] = "success"
        if isinstance(error, asyncio.CancelledError):
            outcome = "cancelled"
        elif error is not None:
            outcome = "error"
        return AIAuditEvent(
            call_id=call_id,
            occurred_at=self._clock(),
            matter_id=matter_id,
            actor=actor,
            task_role=role.value,
            model_id=request.model,
            served_model=response.served_model if response else None,
            effort=request.effort,
            template_id=template.id,
            template_version=template.version,
            template_hash=template.content_hash,
            input_hash=input_hash,
            output_hash=sha256_hex(response.text) if response else None,
            input_tokens=response.input_tokens if response else 0,
            output_tokens=response.output_tokens if response else 0,
            cache_read_input_tokens=response.cache_read_input_tokens if response else 0,
            cache_creation_input_tokens=response.cache_creation_input_tokens if response else 0,
            latency_ms=max(latency_ms, 0.0),
            redaction_applied=redaction_on,
            redaction_counts=mapping.counts() if redaction_on else {},
            stop_reason=response.stop_reason if response else None,
            provider_request_id=response.request_id if response else None,
            outcome=outcome,
            error_type=type(error).__name__ if error is not None else None,
        )

    async def _emit(self, event: AIAuditPayload) -> None:
        try:
            await self._sink.emit(event)
        except Exception as exc:
            logger.error("AI audit emission failed for event %s", event.event_id)
            raise AuditEmissionError("audit sink rejected the AI audit event") from exc
        if isinstance(event, AIModelCallStarted):
            logger.info(
                "ai.model_call_started event=%s call=%s matter=%s role=%s model=%s",
                event.event_id,
                event.call_id,
                event.matter_id,
                event.task_role,
                event.model_id,
            )
            return
        logger.info(
            "ai.model_call event=%s call=%s matter=%s role=%s model=%s template=%s@%s "
            "outcome=%s in=%d out=%d latency_ms=%.0f redacted=%s",
            event.event_id,
            event.call_id,
            event.matter_id,
            event.task_role,
            event.model_id,
            event.template_id,
            event.template_version,
            event.outcome,
            event.input_tokens,
            event.output_tokens,
            event.latency_ms,
            event.redaction_applied,
        )
