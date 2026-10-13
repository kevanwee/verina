import copy
import pickle

import pytest

from verina.ai.redaction import (
    NoOpRedactor,
    RedactionMapping,
    Redactor,
    RegexRedactor,
    nric_check_letter,
    nric_checksum_valid,
)

# Widely published synthetic examples (no real person), one per prefix series.
KNOWN_VALID = ["S1234567D", "T1234567J", "F1234567N", "G1234567X", "M1234567K"]


@pytest.mark.parametrize("value", KNOWN_VALID)
def test_known_valid_nric_fin(value: str) -> None:
    assert nric_checksum_valid(value)
    assert nric_checksum_valid(value.lower())


@pytest.mark.parametrize(
    "value",
    ["S1234567A", "T1234567D", "F1234567X", "G1234567N", "M1234567X", "A1234567D", "S123456D"],
)
def test_invalid_nric_fin(value: str) -> None:
    assert not nric_checksum_valid(value)


def test_check_letter_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="prefix"):
        nric_check_letter("X", "1234567")
    with pytest.raises(ValueError, match="7 digits"):
        nric_check_letter("S", "12345a7")


def test_redacts_valid_nric_only() -> None:
    redactor = RegexRedactor()
    text = "Valid S1234567D, invalid S1234567A, embedded XS1234567D9, fin g1234567x."
    redacted, mapping = redactor.redact(text)
    assert redacted == (
        "Valid [NRIC_FIN_1], invalid S1234567A, embedded XS1234567D9, fin [NRIC_FIN_2]."
    )
    assert mapping.counts() == {"NRIC_FIN": 2}


@pytest.mark.parametrize(
    "email",
    ["jane.tan@example.com", "j+legal@sub.example.com.sg", "a_b-c%d@ex-ample.co"],
)
def test_redacts_emails(email: str) -> None:
    redacted, mapping = RegexRedactor().redact(f"Contact <{email}>.")
    assert redacted == "Contact <[EMAIL_1]>."
    assert mapping.original_for("[EMAIL_1]") == email


def test_email_trailing_dot_not_swallowed() -> None:
    redacted, _ = RegexRedactor().redact("Write to ops@example.com.")
    assert redacted == "Write to [EMAIL_1]."


@pytest.mark.parametrize(
    "phone", ["+6591234567", "+65 9123 4567", "+65-6123-4567", "+65 8123-4567", "+65 3123 4567"]
)
def test_redacts_sg_phone(phone: str) -> None:
    redacted, _ = RegexRedactor().redact(f"Tel: {phone}, ext 2")
    assert redacted == "Tel: [PHONE_SG_1], ext 2"


@pytest.mark.parametrize(
    "text",
    [
        "+65 1123 4567",  # SG numbers start 3/6/8/9
        "+65 9123 45678",  # too long
        "+44 20 7946 0000",  # not SG
        "Tel: 9123 4567",  # local form without +65 is out of scope for regex-v1
    ],
)
def test_does_not_redact_non_matching_phones(text: str) -> None:
    redacted, mapping = RegexRedactor().redact(text)
    assert redacted == text
    assert len(mapping) == 0


def test_same_value_same_placeholder_across_texts() -> None:
    redactor = RegexRedactor()
    first, mapping = redactor.redact("a@example.com and b@example.com")
    second, mapping = redactor.redact("again b@example.com then S1234567D", mapping)
    assert first == "[EMAIL_1] and [EMAIL_2]"
    assert second == "again [EMAIL_2] then [NRIC_FIN_1]"
    assert mapping.counts() == {"EMAIL": 2, "NRIC_FIN": 1}


def test_reidentify_round_trip() -> None:
    redactor = RegexRedactor()
    original = "Jane (S1234567D, jane@example.com, +65 9123 4567) signs for the Buyer."
    redacted, mapping = redactor.redact(original)
    for pii in ("S1234567D", "jane@example.com", "+65 9123 4567"):
        assert pii not in redacted
    assert redactor.reidentify(redacted, mapping) == original


def test_reidentify_leaves_unknown_placeholders() -> None:
    redactor = RegexRedactor()
    redacted, mapping = redactor.redact("x@example.com")
    model_output = f"{redacted} and [EMAIL_9] and [NOT A PLACEHOLDER]"
    assert redactor.reidentify(model_output, mapping) == (
        "x@example.com and [EMAIL_9] and [NOT A PLACEHOLDER]"
    )


def test_mapping_cannot_leave_process() -> None:
    _, mapping = RegexRedactor().redact("secret@example.com S1234567D")
    assert "secret" not in repr(mapping)
    assert "S1234567D" not in repr(mapping)
    with pytest.raises(TypeError, match="must not leave the process"):
        pickle.dumps(mapping)
    with pytest.raises(TypeError):
        copy.deepcopy(mapping)


def test_noop_redactor() -> None:
    redactor = NoOpRedactor()
    text = "S1234567D jane@example.com"
    redacted, mapping = redactor.redact(text)
    assert redacted == text
    assert len(mapping) == 0
    assert redactor.reidentify(text, mapping) == text
    existing = RedactionMapping()
    assert redactor.redact("x", existing)[1] is existing


def test_redactors_satisfy_protocol() -> None:
    assert isinstance(RegexRedactor(), Redactor)
    assert isinstance(NoOpRedactor(), Redactor)
