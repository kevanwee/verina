"""Hash-chain primitives for the audit store (NFR-6, threat GOV-1).

Each tenant has its own chain. Event ``n`` stores ``prev_hash`` = hash of event ``n-1``
(``GENESIS_HASH`` for ``n = 1``) and ``hash`` = SHA-256 over the canonical JSON of every
envelope field except ``hash`` itself. Because ``tenant_id`` and ``sequence`` are hashed,
moving a row to another tenant or renumbering it breaks verification.

The per-tenant head checkpoint (``last_sequence``, ``last_hash``) is optionally MACed with a
key held outside the database (``VERINA_AUDIT_HEAD_KEY``). Without the key, someone who can
write the database can truncate the tail *and* rewind the head consistently. The key blocks
forging a new head but not replaying an old valid head and chain prefix, or deleting the
entire tenant chain. Freshness and expected-chain existence need an independent anchor.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

GENESIS_HASH = "sha256:" + "0" * 64
"""``prev_hash`` of the first event in every tenant chain."""

HASH_PREFIX = "sha256:"


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, ``(",", ":")`` separators, UTF-8 kept, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_hex(text: str) -> str:
    return HASH_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_timestamp(value: datetime) -> str:
    """Fixed-precision UTC timestamp. Naive values (SQLite round-trips) are taken as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def hash_material(
    *,
    schema_version: int,
    tenant_id: str,
    sequence: int,
    event_id: str,
    event_type: str,
    actor: str,
    matter_id: str | None,
    payload: dict[str, Any],
    created_at: datetime,
    prev_hash: str,
) -> dict[str, Any]:
    """Everything that is hashed: all envelope fields except ``hash``."""
    return {
        "schema_version": schema_version,
        "tenant_id": tenant_id,
        "sequence": sequence,
        "event_id": event_id,
        "event_type": event_type,
        "actor": actor,
        "matter_id": matter_id,
        "payload": payload,
        "created_at": utc_timestamp(created_at),
        "prev_hash": prev_hash,
    }


def event_hash(material: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(material))


def head_mac(key: bytes, *, tenant_id: str, last_sequence: int, last_hash: str) -> str:
    """HMAC-SHA256 over the canonical head checkpoint."""
    message = canonical_json(
        {"tenant_id": tenant_id, "last_sequence": last_sequence, "last_hash": last_hash}
    ).encode("utf-8")
    return "hmac-sha256:" + hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_head_mac(
    key: bytes, mac: str | None, *, tenant_id: str, last_sequence: int, last_hash: str
) -> bool:
    if mac is None:
        return False
    expected = head_mac(key, tenant_id=tenant_id, last_sequence=last_sequence, last_hash=last_hash)
    return hmac.compare_digest(expected, mac)
