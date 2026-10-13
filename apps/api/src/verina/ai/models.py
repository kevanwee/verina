"""Model registry: maps a task role to a Claude model id and call parameters.

Defaults (product spec, Architecture > Models):

* ``drafting`` and ``verification`` -> Claude Opus 5.5 (``claude-opus-5-5``)
* ``triage`` and ``extraction``     -> Claude Haiku 5.5 (``claude-haiku-5-5``)

Model ids come from settings (``VERINA_AI_MODEL_<ROLE>``) so an operator can pin or swap a
model without a code change; the id actually used is written to every audit event.

Thinking is always on for Opus 5.5 (and on by default for Haiku 5.5); depth is set with
``effort``. Both models default to ``medium`` effort, so we set it explicitly per role.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from verina.config import Settings

Effort = Literal["low", "medium", "high", "xhigh", "max"]

OPUS_5_5 = "claude-opus-5-5"
HAIKU_5_5 = "claude-haiku-5-5"


class ModelRole(StrEnum):
    """What a model call is for. Determines model choice and effort."""

    DRAFTING = "drafting"
    VERIFICATION = "verification"
    TRIAGE = "triage"
    EXTRACTION = "extraction"


DEFAULT_EFFORT: Mapping[ModelRole, Effort] = {
    ModelRole.DRAFTING: "high",
    ModelRole.VERIFICATION: "high",
    ModelRole.TRIAGE: "low",
    ModelRole.EXTRACTION: "medium",
}


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Resolved call parameters for one role."""

    model_id: str
    effort: Effort
    max_tokens: int


class UnknownModelRoleError(ValueError):
    """Raised when a role string is not one of :class:`ModelRole`."""


class ModelRegistry:
    """Immutable role -> :class:`ModelSpec` lookup."""

    def __init__(self, specs: Mapping[ModelRole, ModelSpec]) -> None:
        missing = [role.value for role in ModelRole if role not in specs]
        if missing:
            raise ValueError(f"model registry is missing roles: {', '.join(missing)}")
        self._specs = dict(specs)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ModelRegistry":
        model_ids = {
            ModelRole.DRAFTING: settings.ai_model_drafting,
            ModelRole.VERIFICATION: settings.ai_model_verification,
            ModelRole.TRIAGE: settings.ai_model_triage,
            ModelRole.EXTRACTION: settings.ai_model_extraction,
        }
        return cls(
            {
                role: ModelSpec(
                    model_id=model_ids[role],
                    effort=DEFAULT_EFFORT[role],
                    max_tokens=settings.ai_max_tokens,
                )
                for role in ModelRole
            }
        )

    @staticmethod
    def parse_role(role: str | ModelRole) -> ModelRole:
        try:
            return ModelRole(role)
        except ValueError as exc:
            raise UnknownModelRoleError(f"unknown task role: {role!r}") from exc

    def resolve(self, role: str | ModelRole) -> ModelSpec:
        return self._specs[self.parse_role(role)]
