"""Supabase claim profile and /v1 enablement rules (ADR 008). Synthetic keys and claims only."""

from typing import Any

import pytest

from verina.access.tokens import JwksConfigError, JwtVerifier, TokenRejected, load_jwks
from verina.api.matters import MattersApiConfigError, build_verifier, check_enablement
from verina.config import Settings

from .conftest import AUDIENCE, ISSUER, Keys, mint

pytestmark = pytest.mark.story("US-47")

USER = "6f1c2a52-7d1e-4b8a-9a43-0c7c1f6a2b10"
SUPABASE_CLAIMS: dict[str, Any] = {
    "role": "authenticated",
    "aal": "aal1",
    "is_anonymous": False,
    "email": "invented.user@example.test",
    "session_id": "4c0c8b7e-2f0e-4c39-9d43-77c2bd1f0a11",
}


def supabase_verifier(keys: Keys, **kwargs: Any) -> JwtVerifier:
    return JwtVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        keys=load_jwks(keys.jwks_json()),
        profile="supabase",
        **kwargs,
    )


def token(keys: Keys, subject: str = USER, **overrides: Any) -> str:
    return mint(keys, subject, alg="ES256", kid="ec-1", **{**SUPABASE_CLAIMS, **overrides})


def test_valid_supabase_token_reports_aal_only(keys: Keys) -> None:
    verified = supabase_verifier(keys).verify(token(keys))
    assert (verified.issuer, verified.subject, verified.aal) == (ISSUER, USER, "aal1")
    assert supabase_verifier(keys).verify(token(keys, aal="aal2")).aal == "aal2"
    # Missing is_anonymous is treated as not anonymous (older tokens).
    assert supabase_verifier(keys).verify(token(keys, is_anonymous=None)).subject == USER


@pytest.mark.parametrize(
    "overrides",
    [
        {"role": "anon"},
        {"role": "service_role"},
        {"role": None},
        {"role": ["authenticated"]},
        {"is_anonymous": True},
        {"is_anonymous": "false"},
        {"aal": "aal3"},
        {"aal": None},
        {"aal": 2},
    ],
)
def test_supabase_claim_failures(keys: Keys, overrides: dict[str, Any]) -> None:
    with pytest.raises(TokenRejected):
        supabase_verifier(keys).verify(token(keys, **overrides))


@pytest.mark.parametrize("subject", ["sub-a-lawyer", USER.upper(), USER + "0", "not-a-uuid"])
def test_supabase_subject_must_be_a_uuid(keys: Keys, subject: str) -> None:
    with pytest.raises(TokenRejected):
        supabase_verifier(keys).verify(token(keys, subject))


def test_require_aal2_rejects_aal1(keys: Keys) -> None:
    strict = supabase_verifier(keys, require_aal2=True)
    with pytest.raises(TokenRejected):
        strict.verify(token(keys))
    assert strict.verify(token(keys, aal="aal2")).aal == "aal2"


def test_generic_profile_ignores_supabase_claims(keys: Keys) -> None:
    generic = JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys=load_jwks(keys.jwks_json()))
    verified = generic.verify(token(keys, role="anon", is_anonymous=True))
    assert verified.aal is None
    assert generic.profile == "generic" and generic.issuer == ISSUER


@pytest.mark.parametrize(
    "kwargs",
    [{"profile": "other"}, {"require_aal2": True}, {"require_aal2": "yes"}],
)
def test_profile_configuration_is_validated(keys: Keys, kwargs: dict[str, Any]) -> None:
    with pytest.raises(JwksConfigError):
        JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys=load_jwks(keys.jwks_json()), **kwargs)


def test_key_source_required(keys: Keys) -> None:
    with pytest.raises(JwksConfigError):
        JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys=object())  # type: ignore[arg-type]
    with pytest.raises(JwksConfigError):
        JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys={})


# ----------------------------------------------------------------------------- enablement

SUPABASE_ISSUER = "https://synthetic-ref.supabase.co/auth/v1"
DEV: dict[str, Any] = {
    "env": "development",
    "matters_api_enabled": True,
    "database_url": "sqlite:///./.data/synthetic-dev.db",
    "auth_issuer": SUPABASE_ISSUER,
    "auth_audience": "authenticated",
    "auth_jwks_url": SUPABASE_ISSUER + "/.well-known/jwks.json",
    "auth_profile": "supabase",
    "audit_head_key": "synthetic-head-key-0123456789abcdef-0123",
}


def dev_settings(**overrides: Any) -> Settings:
    values = {**DEV, **overrides}
    return Settings(_env_file=None, **{k: v for k, v in values.items() if v is not None})


def test_development_env_with_complete_configuration_is_enabled() -> None:
    settings = dev_settings()
    check_enablement(settings)
    verifier = build_verifier(settings)
    assert verifier.profile == "supabase"


@pytest.mark.parametrize(
    "missing",
    ["auth_issuer", "auth_audience", "auth_jwks_url", "audit_head_key", "database_url"],
)
def test_development_env_requires_every_control(missing: str) -> None:
    with pytest.raises(MattersApiConfigError):
        check_enablement(dev_settings(**{missing: None}))


def test_development_env_refuses_a_static_jwks(keys: Keys) -> None:
    with pytest.raises(MattersApiConfigError):
        build_verifier(dev_settings(auth_jwks_url=None, auth_jwks=keys.jwks_json()))


@pytest.mark.parametrize("env", ["staging", "production"])
def test_staging_and_production_are_still_refused(env: str) -> None:
    with pytest.raises(MattersApiConfigError):
        check_enablement(dev_settings(env=env))


def test_defaulted_env_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERINA_ENV", raising=False)
    values = {k: v for k, v in DEV.items() if k != "env"}
    with pytest.raises(MattersApiConfigError):
        check_enablement(Settings(_env_file=None, **values))


def test_development_env_from_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERINA_ENV", "development")
    values = {k: v for k, v in DEV.items() if k != "env"}
    check_enablement(Settings(_env_file=None, **values))


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth_jwks_url": "https://other-ref.supabase.co/auth/v1/.well-known/jwks.json"},
        {"auth_jwks_url": "http://synthetic-ref.supabase.co/auth/v1/.well-known/jwks.json"},
        {"auth_profile": "generic", "auth_require_aal2": True},
        {"auth_profile": "generic", "auth_admin_require_aal2": True},
    ],
)
def test_invalid_development_auth_configuration(overrides: dict[str, Any]) -> None:
    with pytest.raises(MattersApiConfigError):
        build_verifier(dev_settings(**overrides))


def test_static_and_fetched_jwks_are_mutually_exclusive(keys: Keys) -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        auth_issuer=SUPABASE_ISSUER,
        auth_audience="authenticated",
        auth_jwks=keys.jwks_json(),
        auth_jwks_url=SUPABASE_ISSUER + "/.well-known/jwks.json",
    )
    with pytest.raises(MattersApiConfigError):
        build_verifier(settings)


def test_local_env_may_use_a_fetched_jwks() -> None:
    settings = Settings(
        _env_file=None,
        env="local",
        auth_issuer=SUPABASE_ISSUER,
        auth_audience="authenticated",
        auth_jwks_url=SUPABASE_ISSUER + "/.well-known/jwks.json",
        auth_profile="supabase",
        auth_require_aal2=True,
    )
    assert build_verifier(settings).profile == "supabase"
