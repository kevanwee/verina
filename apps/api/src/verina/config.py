"""Application settings, read from environment variables (prefix ``VERINA_``)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Never hard-code secrets; supply them via the environment."""

    model_config = SettingsConfigDict(
        env_prefix="VERINA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    allowed_origins: list[str] = ["http://localhost:3000"]
    database_url: str = "sqlite:///./verina-local.db"

    # --- AI orchestrator (verina.ai) -------------------------------------------------
    # The key is a SecretStr so it is masked in repr/str/model_dump. Supply it only via
    # the environment (VERINA_ANTHROPIC_API_KEY) or a secret manager, never in code.
    anthropic_api_key: SecretStr | None = None
    # Optional endpoint override (e.g. a ZDR-contracted gateway). None = SDK default.
    anthropic_base_url: str | None = None
    ai_request_timeout_seconds: float = Field(default=300.0, gt=0)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    ai_max_tokens: int = Field(default=16000, gt=0, le=128000)
    # Role -> model id. Defaults follow the product spec (Opus for drafting and
    # verification, Haiku for triage and extraction).
    ai_model_drafting: str = "claude-opus-5-5"
    ai_model_verification: str = "claude-opus-5-5"
    ai_model_triage: str = "claude-haiku-5-5"
    ai_model_extraction: str = "claude-haiku-5-5"
    # Default tenant policy: redact personal data before any external model call.
    ai_redaction_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide settings."""
    return Settings()
