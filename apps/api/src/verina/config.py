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

    # "development" is a shared developer deployment (for example the Supabase dev project,
    # ADR 008). It must be set explicitly and has stricter enablement rules than local/test;
    # staging and production are refused by the /v1 API in this slice.
    env: Literal["local", "test", "development", "staging", "production"] = "local"
    log_level: str = "INFO"
    allowed_origins: list[str] = ["http://localhost:3000"]
    # SQLAlchemy URL (ADR 004). Local default is a SQLite file under the git-ignored
    # .data/ directory; CI points this at PostgreSQL (postgresql+psycopg://...).
    database_url: str = "sqlite:///./.data/verina-local.db"
    # Optional key (>= 32 bytes) for the audit chain-head HMAC (ADR 004). Without it, tail
    # truncation plus a consistent head rewind by a database writer is not detectable.
    audit_head_key: SecretStr | None = None

    # --- Authenticated matter API (ADR 007) --------------------------------------------
    # Off by default: the API stays health-only unless explicitly enabled. Enabling also
    # requires VERINA_ENV to be explicitly set to local or test, plus issuer, audience and
    # JWKS; startup fails closed otherwise.
    matters_api_enabled: bool = False
    # Exact expected ``iss`` claim (https:// required outside local/test).
    auth_issuer: str | None = None
    # Expected ``aud`` value: an API identifier, never an OAuth client_id.
    auth_audience: str | None = None
    # Explicit extra audiences a multi-audience token may also carry (default: none, so a
    # token minted for several APIs is refused).
    auth_extra_audiences: list[str] = Field(default_factory=list)
    # Static public JWKS: inline JSON (starting with "{") or a local file path. Public keys
    # only. Mutually exclusive with auth_jwks_url.
    auth_jwks: str | None = None
    # HTTPS JWKS endpoint (ADR 008), fetched with a bounded cache. Its host must equal the
    # issuer's host. Mutually exclusive with auth_jwks.
    auth_jwks_url: str | None = None
    auth_jwks_cache_ttl_seconds: int = Field(default=600, ge=60, le=86400)
    auth_jwks_refetch_interval_seconds: int = Field(default=30, ge=1, le=3600)
    auth_jwks_max_stale_seconds: int = Field(default=21600, ge=60, le=604800)
    auth_jwks_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    auth_leeway_seconds: int = Field(default=30, ge=0, le=120)
    auth_max_token_lifetime_seconds: int = Field(default=3600, ge=60, le=86400)
    # Claim profile: "generic" (ADR 007) or "supabase" (ADR 008: role must be
    # "authenticated", anonymous users refused, aal reported for step-up).
    auth_profile: Literal["generic", "supabase"] = "generic"
    # Require aal2 (MFA) on every token. Needs auth_profile=supabase.
    auth_require_aal2: bool = False
    # Require aal2 only when acting as a platform administrator. Default false so a dev
    # project works without MFA enrolment; turn on before any non-development use.
    auth_admin_require_aal2: bool = False

    # --- Supabase Auth admin (ADR 008) ---------------------------------------------------
    # Project URL, e.g. https://<ref>.supabase.co (public). Used for invitations only.
    supabase_url: str | None = None
    # Secret (sb_secret_...) or legacy service_role key. Server-side only, never logged,
    # never sent to the browser. Supply via the ignored apps/api/.env or a secret manager.
    supabase_secret_key: SecretStr | None = None
    # Where the invite e-mail link lands (must be in Supabase's redirect allow list).
    auth_invite_redirect_url: str | None = None

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
