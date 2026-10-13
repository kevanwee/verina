"""Pseudonymising redaction applied before any external model call.

``redact`` swaps personal data for stable placeholders (``[EMAIL_1]``) and records the
mapping; ``reidentify`` puts the originals back into the model output. The mapping holds
the only link between placeholder and person, so it is deliberately hard to move out of
the process: it cannot be pickled, has no serialiser, and its ``repr`` shows counts only.

The regex rules here are a **starting point** (Singapore NRIC/FIN with checksum, email
addresses, +65 phone numbers). The authoritative category list comes from the PDPA
counsel's taxonomy (``docs/compliance/pii-taxonomy.json``); each taxonomy category will
map to a :class:`RedactionRule`, or to a stronger detector behind the same
:class:`Redactor` protocol (names, addresses and bank details are not caught here).
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, NoReturn, Protocol, runtime_checkable

# --- Singapore NRIC / FIN --------------------------------------------------------------

_NRIC_WEIGHTS: Final = (2, 7, 6, 5, 4, 3, 2)
_NRIC_OFFSETS: Final = {"S": 0, "T": 4, "F": 0, "G": 4, "M": 3}
_NRIC_TABLES: Final = {
    "S": "JZIHGFEDCBA",
    "T": "JZIHGFEDCBA",
    "F": "XWUTRQPNMLK",
    "G": "XWUTRQPNMLK",
    "M": "XWUTRQPNJLK",
}


def nric_check_letter(prefix: str, digits: str) -> str:
    """Return the checksum letter for an NRIC/FIN ``prefix`` (S/T/F/G/M) and 7 digits."""
    prefix = prefix.upper()
    if prefix not in _NRIC_TABLES or len(digits) != 7 or not digits.isdigit():
        raise ValueError("expected prefix S/T/F/G/M and exactly 7 digits")
    total = sum(int(d) * w for d, w in zip(digits, _NRIC_WEIGHTS, strict=True))
    total += _NRIC_OFFSETS[prefix]
    return _NRIC_TABLES[prefix][total % 11]


def nric_checksum_valid(value: str) -> bool:
    """True if ``value`` is a well-formed NRIC/FIN whose check letter is correct."""
    value = value.strip().upper()
    if len(value) != 9 or value[0] not in _NRIC_TABLES or not value[8].isalpha():
        return False
    digits = value[1:8]
    if not digits.isdigit():
        return False
    return nric_check_letter(value[0], digits) == value[8]


# --- Mapping ---------------------------------------------------------------------------

_PLACEHOLDER_RE: Final = re.compile(r"\[([A-Z][A-Z0-9]*(?:_[A-Z][A-Z0-9]*)*)_(\d+)\]")


class RedactionError(ValueError):
    """Input cannot be safely distinguished from issued redaction placeholders."""


class RedactionMapping:
    """Placeholder <-> original value table for one orchestrator run. Process-local only."""

    __slots__ = ("_by_original", "_by_placeholder", "_counters", "_reserved")

    def __init__(self) -> None:
        self._by_placeholder: dict[str, str] = {}
        self._by_original: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}
        self._reserved: set[str] = set()

    def reserve_source_placeholders(self, text: str) -> None:
        """Keep source literals distinct from issued tokens; ambiguous later input fails."""
        literals = {match.group(0) for match in _PLACEHOLDER_RE.finditer(text)}
        if literals.intersection(self._by_placeholder):
            raise RedactionError("source placeholder conflicts with an issued redaction token")
        self._reserved.update(literals)

    def placeholder_for(self, category: str, original: str) -> str:
        """Return the placeholder for ``original``, issuing a new one on first sight."""
        key = (category, original)
        existing = self._by_original.get(key)
        if existing is not None:
            return existing
        n = self._counters.get(category, 0) + 1
        while f"[{category}_{n}]" in self._reserved:
            n += 1
        self._counters[category] = n
        placeholder = f"[{category}_{n}]"
        self._by_original[key] = placeholder
        self._by_placeholder[placeholder] = original
        return placeholder

    def original_for(self, placeholder: str) -> str | None:
        return self._by_placeholder.get(placeholder)

    def counts(self) -> dict[str, int]:
        """Number of distinct values redacted per category (safe to log or audit)."""
        counts: dict[str, int] = {}
        for category, _original in self._by_original:
            counts[category] = counts.get(category, 0) + 1
        return dict(sorted(counts.items()))

    def __len__(self) -> int:
        return len(self._by_placeholder)

    def __repr__(self) -> str:
        return f"RedactionMapping(entries={len(self)})"

    def __reduce__(self) -> NoReturn:
        raise TypeError("RedactionMapping must not leave the process (no pickling/copying)")


# --- Redactors -------------------------------------------------------------------------


@runtime_checkable
class Redactor(Protocol):
    """Replaces personal data with placeholders and restores it afterwards."""

    @property
    def name(self) -> str: ...

    def redact(
        self, text: str, mapping: RedactionMapping | None = None
    ) -> tuple[str, RedactionMapping]:
        """Return redacted text and the (new or extended) mapping.

        Pass the same ``mapping`` for every text in one model call so a value maps to the
        same placeholder across variables and documents.
        """
        ...

    def reidentify(self, text: str, mapping: RedactionMapping) -> str:
        """Replace known placeholders in ``text`` with their originals."""
        ...


def _reidentify(text: str, mapping: RedactionMapping) -> str:
    if len(mapping) == 0:
        return text

    def _sub(match: re.Match[str]) -> str:
        original = mapping.original_for(match.group(0))
        return match.group(0) if original is None else original

    return _PLACEHOLDER_RE.sub(_sub, text)


class NoOpRedactor:
    """Passes text through unchanged. Used when redaction is disabled for a tenant."""

    name = "noop"

    def redact(
        self, text: str, mapping: RedactionMapping | None = None
    ) -> tuple[str, RedactionMapping]:
        return text, mapping if mapping is not None else RedactionMapping()

    def reidentify(self, text: str, mapping: RedactionMapping) -> str:
        return _reidentify(text, mapping)


@dataclass(frozen=True, slots=True)
class RedactionRule:
    """One PII category: a regex plus an optional validator to cut false positives."""

    category: str
    pattern: re.Pattern[str]
    validator: Callable[[str], bool] | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z][A-Z0-9]*)*", self.category):
            raise ValueError(f"category {self.category!r} must be UPPER_SNAKE_CASE")


NRIC_FIN_RULE: Final = RedactionRule(
    category="NRIC_FIN",
    pattern=re.compile(r"(?<![A-Za-z0-9])[STFGM]\d{7}[A-Z](?![A-Za-z0-9])", re.IGNORECASE),
    validator=nric_checksum_valid,
)
EMAIL_RULE: Final = RedactionRule(
    category="EMAIL",
    pattern=re.compile(
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
        r"(?![A-Za-z0-9-])"
    ),
)
SG_PHONE_RULE: Final = RedactionRule(
    category="PHONE_SG",
    # +65 then an 8-digit number starting 3, 6, 8 or 9, optional single space/hyphen groups.
    pattern=re.compile(r"(?<![\w+])\+65[ -]?[3689]\d{3}[ -]?\d{4}(?!\d)"),
)

DEFAULT_RULES: Final[tuple[RedactionRule, ...]] = (NRIC_FIN_RULE, EMAIL_RULE, SG_PHONE_RULE)


class RegexRedactor:
    """Rule-based redactor. Overlapping matches resolve to the earliest, then longest."""

    name = "regex-v1"

    def __init__(self, rules: Sequence[RedactionRule] = DEFAULT_RULES) -> None:
        self._rules = tuple(rules)

    def redact(
        self, text: str, mapping: RedactionMapping | None = None
    ) -> tuple[str, RedactionMapping]:
        mapping = mapping if mapping is not None else RedactionMapping()
        mapping.reserve_source_placeholders(text)
        spans: list[tuple[int, int, RedactionRule]] = []
        for rule in self._rules:
            for match in rule.pattern.finditer(text):
                if rule.validator is None or rule.validator(match.group(0)):
                    spans.append((match.start(), match.end(), rule))
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

        out: list[str] = []
        cursor = 0
        for start, end, rule in spans:
            if start < cursor:
                continue  # overlaps an earlier, longer match
            value = text[start:end]
            if rule.category == NRIC_FIN_RULE.category:
                value = value.upper()  # one placeholder per identity regardless of case
            out.append(text[cursor:start])
            out.append(mapping.placeholder_for(rule.category, value))
            cursor = end
        out.append(text[cursor:])
        return "".join(out), mapping

    def reidentify(self, text: str, mapping: RedactionMapping) -> str:
        return _reidentify(text, mapping)
