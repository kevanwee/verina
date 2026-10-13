"""Deterministic hashing helpers shared by templates and the orchestrator."""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialise ``value`` deterministically (sorted keys, no whitespace, UTF-8 kept)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    """Return ``sha256:<hex>`` for a UTF-8 string."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
