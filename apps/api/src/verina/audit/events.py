"""Audit event models (NFR-6, NFR-7, FR-9.2).

Two layers:

* **Payloads** are typed, metadata-only records such as :class:`AIModelCallStarted` and
  :class:`AIAuditEvent`. Each payload type is registered by its ``event_type``.
* The **envelope** :class:`AuditEvent` is what the durable store persists: tenant, per-tenant
  sequence number, event type, actor, matter, the payload as JSON, creation time and the
  hash chain fields (see :mod:`verina.audit.chain`).

Events never carry document text, prompts, model output, personal data or secrets: they
carry identifiers, hashes, counts and timings only. This is enforced structurally: payload
models forbid unknown fields, registered payload types may not declare content-like field
names, and strings are length-capped. These are structural safeguards, not a PII detector;
callers must still supply opaque identifiers and approved metadata.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_PAYLOAD_STRING = 256
"""Longest string allowed anywhere in a payload. Ids, hashes and enum values fit easily."""

MAX_IDENTIFIER = 256
"""Longest tenant/actor/matter identifier accepted by the envelope."""

FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "body",
        "content",
        "contents",
        "document",
        "document_text",
        "documents",
        "email",
        "instructions",
        "message",
        "messages",
        "name",
        "nric",
        "output",
        "output_text",
        "prompt",
        "prompts",
        "raw",
        "response",
        "system",
        "system_prompt",
        "text",
        "variables",
    }
)
"""Field names that suggest content or personal data. A payload type declaring any of them
is refused at registration (defence in depth on top of code review)."""


class AuditPayloadError(ValueError):
    """A payload is unknown, malformed or could carry content/personal data."""


class AIModelCallStarted(BaseModel):
    """Written *before* a model call (AI-4) so a crash mid-call leaves an auditable record.

    A start without a matching :class:`AIAuditEvent` (same ``call_id``) is a *dangling call*.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_type: Literal["ai.model_call_started"] = "ai.model_call_started"
    event_id: UUID = Field(default_factory=uuid4)
    call_id: UUID = Field(description="Shared with the completion event for this call.")
    occurred_at: datetime = Field(description="UTC time just before the call was dispatched.")

    matter_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)

    task_role: str
    model_id: str
    effort: str
    template_id: str
    template_version: str
    template_hash: str
    input_hash: str = Field(description="SHA-256 of the canonical, redacted request payload.")
    redaction_applied: bool
    redaction_counts: dict[str, int] = Field(default_factory=dict)


class AIAuditEvent(BaseModel):
    """Completion record: one per model call made through the AI orchestrator.

    ``outcome`` is ``success``, ``error`` (the client raised) or ``cancelled`` (the calling
    task was cancelled while the call was in flight).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_type: Literal["ai.model_call"] = "ai.model_call"
    event_id: UUID = Field(default_factory=uuid4)
    call_id: UUID = Field(
        default_factory=uuid4,
        description="Shared with the ai.model_call_started event for this call.",
    )
    occurred_at: datetime = Field(description="UTC time the call completed (or failed).")

    matter_id: str = Field(min_length=1)
    actor: str = Field(min_length=1, description="User or service principal id.")

    task_role: str
    model_id: str = Field(description="Model id requested from the registry.")
    served_model: str | None = Field(
        default=None, description="Model id reported by the provider, if the call returned."
    )
    effort: str

    template_id: str
    template_version: str
    template_hash: str

    input_hash: str = Field(description="SHA-256 of the canonical, redacted request payload.")
    output_hash: str | None = Field(
        default=None, description="SHA-256 of the model output as received (pre re-identification)."
    )

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(ge=0)

    redaction_applied: bool
    redaction_counts: dict[str, int] = Field(
        default_factory=dict, description="Placeholders issued per PII category (counts only)."
    )

    stop_reason: str | None = None
    provider_request_id: str | None = None
    outcome: Literal["success", "error", "cancelled"]
    error_type: str | None = None


AIAuditPayload = AIModelCallStarted | AIAuditEvent
"""Everything the orchestrator emits to an :class:`~verina.ai.audit.AuditSink`."""


class AccessAuditEvent(BaseModel):
    """One record per authorization decision at the application-service boundary (ADR 003).

    Carries the trusted tenant and actor, the requested action, the decision and reason codes.
    It never carries matter content, document text, titles or free-text reasons: a waiver or
    attestation reason is represented by its SHA-256 only (the text lives on the domain record).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_type: Literal["access.decision"] = "access.decision"
    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime

    tenant_id: str = Field(min_length=1, description="Tenant from the trusted identity adapter.")
    actor: str = Field(min_length=1, description="Actor from the trusted identity adapter.")
    action: str = Field(min_length=1)
    matter_id: str | None = Field(
        default=None, description="Requested matter id (as supplied), if the action is scoped."
    )

    decision: Literal["allow", "deny"]
    reason_code: str = Field(description="Disclosable reason code returned to the caller.")
    detail_code: str | None = Field(
        default=None,
        description="Internal diagnostic (e.g. ethical_wall, not_member). Never sent to callers.",
    )
    policy_version: str

    reason_sha256: str | None = Field(
        default=None, description="SHA-256 of a waiver/attestation reason; never the text."
    )
    same_actor_as_conflict_recorder: bool | None = Field(
        default=None,
        description="Waiver only: the waiving lawyer also recorded the conflict hit.",
    )
    result_count: int | None = Field(
        default=None, ge=0, description="List/search/count: number of visible matters returned."
    )


AuditPayload = AIAuditPayload | AccessAuditEvent


_PAYLOAD_TYPES: dict[str, type[BaseModel]] = {}


def register_payload_type(model: type[BaseModel]) -> type[BaseModel]:
    """Register a metadata-only payload type under its ``event_type`` default.

    Refuses models that allow extra fields, lack a literal ``event_type``, ``matter_id`` or
    ``actor`` field, or declare a content-like field name (see ``FORBIDDEN_FIELD_NAMES``).
    """
    if model.model_config.get("extra") != "forbid":
        raise AuditPayloadError(f"{model.__name__} must set extra='forbid'")
    fields = model.model_fields
    for required in ("event_type", "matter_id", "actor", "event_id"):
        if required not in fields:
            raise AuditPayloadError(f"{model.__name__} must declare {required!r}")
    bad = sorted(set(fields) & FORBIDDEN_FIELD_NAMES)
    if bad:
        raise AuditPayloadError(f"{model.__name__} declares content-like fields: {bad}")
    event_type = fields["event_type"].default
    if not isinstance(event_type, str) or not event_type:
        raise AuditPayloadError(f"{model.__name__}.event_type needs a literal string default")
    existing = _PAYLOAD_TYPES.get(event_type)
    if existing is not None and existing is not model:
        raise AuditPayloadError(f"event type {event_type!r} is already registered")
    _PAYLOAD_TYPES[event_type] = model
    return model


register_payload_type(AIModelCallStarted)
register_payload_type(AIAuditEvent)
register_payload_type(AccessAuditEvent)


def payload_type(event_type: str) -> type[BaseModel]:
    try:
        return _PAYLOAD_TYPES[event_type]
    except KeyError:
        raise AuditPayloadError(f"unknown audit event type {event_type!r}") from None


def registered_event_types() -> frozenset[str]:
    return frozenset(_PAYLOAD_TYPES)


def _check_strings(value: Any, path: str) -> None:
    if isinstance(value, str):
        if len(value) > MAX_PAYLOAD_STRING:
            raise AuditPayloadError(
                f"payload field {path} exceeds {MAX_PAYLOAD_STRING} characters; audit payloads "
                "carry identifiers and hashes only, never text"
            )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _check_strings(str(key), f"{path}.<key>")
            _check_strings(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for i, item in enumerate(value):
            _check_strings(item, f"{path}[{i}]")


def validate_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a JSON payload against its registered schema and return its JSON form."""
    model = payload_type(event_type)
    try:
        parsed = model.model_validate(dict(payload))
    except ValidationError as exc:
        # Only field locations and error types: never echo the offending values.
        where = ", ".join(
            f"{'.'.join(str(p) for p in err['loc'])}:{err['type']}" for err in exc.errors()
        )
        raise AuditPayloadError(f"invalid {event_type} payload ({where})") from None
    return payload_to_json(parsed)


def payload_to_json(payload: BaseModel) -> dict[str, Any]:
    """JSON form of a registered payload, after the content/size checks."""
    event_type = getattr(payload, "event_type", None)
    if not isinstance(event_type, str) or payload_type(event_type) is not type(payload):
        raise AuditPayloadError(f"{type(payload).__name__} is not a registered audit payload")
    data = payload.model_dump(mode="json")
    _check_strings(data, "payload")
    return data


class AuditEvent(BaseModel):
    """The persisted envelope: one link in a tenant's hash chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=MAX_IDENTIFIER)
    sequence: int = Field(ge=1, description="1-based, gap-free per tenant.")
    event_id: UUID
    event_type: str = Field(min_length=1, max_length=64)
    actor: str = Field(min_length=1, max_length=MAX_IDENTIFIER)
    matter_id: str | None = Field(default=None, max_length=MAX_IDENTIFIER)
    payload: dict[str, Any]
    created_at: datetime = Field(description="UTC time the store appended the event.")
    prev_hash: str
    hash: str

    @field_validator("payload")
    @classmethod
    def _payload_is_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _check_strings(value, "payload")
        return value
