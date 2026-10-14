"""Keyed pseudonyms for identity-provider subjects in audit metadata (ADR 009, SEC M4).

Audit events never carry a raw ``(issuer, subject)``. When one must be correlatable (an auth
failure for a verified but unlinked token, a binding change) the event carries
``hmac-sha256:<hex>`` computed with a key derived from the audit head key
(``VERINA_AUDIT_HEAD_KEY``), so no extra secret is introduced and the database alone cannot
reverse or test guesses against it. Without a configured key the field is omitted.
"""

import hashlib
import hmac
import json

from pydantic import SecretStr

_CONTEXT = b"verina/audit/subject-hmac/v1"


def derive_subject_key(head_key: SecretStr | bytes | None) -> bytes | None:
    """Domain-separated sub-key; ``None`` when no audit head key is configured."""
    if head_key is None:
        return None
    raw = (
        head_key.get_secret_value().encode("utf-8") if isinstance(head_key, SecretStr) else head_key
    )
    if len(raw) < 32:
        raise ValueError("audit head key must be at least 32 bytes")
    return hmac.new(raw, _CONTEXT, hashlib.sha256).digest()


def subject_hmac(key: bytes | None, issuer: str, subject: str) -> str | None:
    if key is None:
        return None
    message = json.dumps([issuer, subject], separators=(",", ":"), ensure_ascii=False)
    return "hmac-sha256:" + hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
