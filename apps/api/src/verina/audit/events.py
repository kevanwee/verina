"""Audit event models.

Only the event *shape* lives here for now. The append-only, hash-chained store (NFR-6)
arrives with EN-8 and will persist these events unchanged.

Events never carry document text, prompts, model output, personal data or secrets: they
carry identifiers, hashes, counts and timings only (FR-9.2, NFR-7).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AIAuditEvent(BaseModel):
    """One record per external model call made through the AI orchestrator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_type: Literal["ai.model_call"] = "ai.model_call"
    event_id: UUID = Field(default_factory=uuid4)
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
    outcome: Literal["success", "error"]
    error_type: str | None = None
