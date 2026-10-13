import pytest

from verina.ai.models import (
    HAIKU_5_5,
    OPUS_5_5,
    ModelRegistry,
    ModelRole,
    ModelSpec,
    UnknownModelRoleError,
)
from verina.config import Settings


def test_default_role_mapping(settings: Settings) -> None:
    registry = ModelRegistry.from_settings(settings)
    assert registry.resolve("drafting").model_id == OPUS_5_5 == "claude-opus-5-5"
    assert registry.resolve(ModelRole.VERIFICATION).model_id == OPUS_5_5
    assert registry.resolve("triage").model_id == HAIKU_5_5 == "claude-haiku-5-5"
    assert registry.resolve("extraction").model_id == HAIKU_5_5
    assert registry.resolve("drafting").effort == "high"
    assert registry.resolve("triage").effort == "low"
    assert registry.resolve("triage").max_tokens == settings.ai_max_tokens


def test_models_configurable_via_settings() -> None:
    settings = Settings(env="test", ai_model_triage="claude-sonnet-5-5", ai_max_tokens=4000)
    spec = ModelRegistry.from_settings(settings).resolve("triage")
    assert spec == ModelSpec(model_id="claude-sonnet-5-5", effort="low", max_tokens=4000)


def test_models_configurable_via_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERINA_AI_MODEL_DRAFTING", "claude-opus-5")
    assert ModelRegistry.from_settings(Settings()).resolve("drafting").model_id == "claude-opus-5"


def test_unknown_role_and_incomplete_registry() -> None:
    with pytest.raises(UnknownModelRoleError):
        ModelRegistry.parse_role("summarise")
    with pytest.raises(ValueError, match="missing roles"):
        ModelRegistry({ModelRole.TRIAGE: ModelSpec("m", "low", 10)})
