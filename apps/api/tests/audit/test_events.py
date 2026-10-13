"""Audit payload schemas: metadata only, never document text or personal data."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tests.audit.conftest import completed, started
from verina.audit.events import (
    FORBIDDEN_FIELD_NAMES,
    MAX_PAYLOAD_STRING,
    AIAuditEvent,
    AuditEvent,
    AuditPayloadError,
    payload_to_json,
    payload_type,
    register_payload_type,
    registered_event_types,
    validate_payload,
)

pytestmark = pytest.mark.story("EN-8")

SYNTHETIC_TEXT = "The Discloser shall keep the synthetic clause confidential."


def test_registered_types_declare_no_content_fields() -> None:
    assert registered_event_types() >= {"ai.model_call_started", "ai.model_call"}
    for event_type in registered_event_types():
        model = payload_type(event_type)
        assert not set(model.model_fields) & FORBIDDEN_FIELD_NAMES
        assert model.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("field", ["document_text", "prompt", "output", "text", "name"])
def test_payload_with_content_field_is_rejected(field: str) -> None:
    payload = started().model_dump(mode="json") | {field: SYNTHETIC_TEXT}
    with pytest.raises(AuditPayloadError) as info:
        validate_payload("ai.model_call_started", payload)
    # The error names the field but never echoes the content.
    assert field in str(info.value)
    assert SYNTHETIC_TEXT not in str(info.value)
    with pytest.raises(ValidationError):
        AIAuditEvent.model_validate(completed(started()).model_dump() | {field: SYNTHETIC_TEXT})


def test_long_strings_are_rejected_everywhere() -> None:
    long_value = "x" * (MAX_PAYLOAD_STRING + 1)
    with pytest.raises(AuditPayloadError, match="exceeds"):
        payload_to_json(started(actor=long_value))
    bad_counts = started().model_copy(update={"redaction_counts": {long_value: 1}})
    with pytest.raises(AuditPayloadError, match="exceeds"):
        payload_to_json(bad_counts)
    with pytest.raises(ValidationError):
        AuditEvent(
            tenant_id="t",
            sequence=1,
            event_id=uuid4(),
            event_type="ai.model_call",
            actor="a",
            payload={"nested": [long_value]},
            created_at=datetime.now(UTC),
            prev_hash="p",
            hash="h",
        )


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(AuditPayloadError, match="unknown"):
        validate_payload("ledger.attested", {})


def test_validate_payload_round_trips() -> None:
    data = payload_to_json(started())
    assert validate_payload("ai.model_call_started", data) == data


class _Base(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: UUID = Field(default_factory=uuid4)
    matter_id: str = "M-1"
    actor: str = "u-1"


def test_register_refuses_content_fields() -> None:
    class Leaky(_Base):
        event_type: Literal["test.leaky"] = "test.leaky"
        document_text: str = ""

    with pytest.raises(AuditPayloadError, match="content-like"):
        register_payload_type(Leaky)


def test_register_refuses_open_models_and_missing_fields() -> None:
    class Open(BaseModel):
        model_config = ConfigDict(extra="allow")
        event_type: str = "test.open"

    class NoActor(BaseModel):
        model_config = ConfigDict(extra="forbid")
        event_type: str = "test.no_actor"
        event_id: UUID = Field(default_factory=uuid4)
        matter_id: str = "M"

    class NoDefault(_Base):
        event_type: str

    with pytest.raises(AuditPayloadError, match="extra"):
        register_payload_type(Open)
    with pytest.raises(AuditPayloadError, match="actor"):
        register_payload_type(NoActor)
    with pytest.raises(AuditPayloadError, match="literal"):
        register_payload_type(NoDefault)


def test_register_new_type_and_reject_duplicates() -> None:
    class Attested(_Base):
        event_type: Literal["test.attested"] = "test.attested"
        ledger_entry_id: str = "L-1"

    assert register_payload_type(Attested) is Attested
    assert register_payload_type(Attested) is Attested  # idempotent

    class Impostor(_Base):
        event_type: Literal["test.attested"] = "test.attested"

    with pytest.raises(AuditPayloadError, match="already registered"):
        register_payload_type(Impostor)
    assert payload_to_json(Attested())["ledger_entry_id"] == "L-1"
