"""Bearer-token verification against a static JWKS. Keys are generated at test time."""

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from verina.access.tokens import (
    MAX_JWKS_BYTES,
    MAX_TOKEN_BYTES,
    JwksConfigError,
    JwtVerifier,
    TokenRejected,
    VerifiedToken,
    load_jwks,
)

from .conftest import AUDIENCE, ISSUER, Keys, mint

pytestmark = pytest.mark.story("EN-7")


def _b64(data: object) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_valid_tokens_for_each_allowed_algorithm(keys: Keys, verifier: JwtVerifier) -> None:
    for alg, kid in (("RS256", "rsa-1"), ("ES256", "ec-1"), ("EdDSA", "ed-1")):
        assert verifier.verify(mint(keys, alg=alg, kid=kid)) == VerifiedToken(
            ISSUER, "sub-a-lawyer"
        )


def test_audience_array_containing_configured_audience(keys: Keys, verifier: JwtVerifier) -> None:
    token = mint(keys, aud=["other-api", AUDIENCE])
    assert verifier.verify(token).subject == "sub-a-lawyer"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 60},  # expired beyond leeway
        {"nbf": int(time.time()) + 300},  # not yet valid
        {"iat": int(time.time()) + 300, "exp": int(time.time()) + 600},  # issued in future
        {"iss": "https://idp.synthetic.test"},  # issuer must match exactly (no trailing /)
        {"iss": "https://evil.synthetic.test/"},
        {"aud": "another-api"},
        {"aud": ["another-api"]},
        {"exp": None},
        {"iat": None},
        {"sub": None},
        {"aud": None},
        {"iss": None},
        {"exp": True},
        {"iat": "1700000000"},
        {"nbf": "soon"},
        {"sub": ""},
        {"sub": "sub\nnewline"},
        {"sub": "s" * 256},
        {"sub": 12345},
        {"iat": int(time.time()) - 10, "exp": int(time.time()) + 7200},  # lifetime > 3600
        {"exp": int(time.time()) - 6, "iat": int(time.time()) - 5},  # exp before iat
        {"exp": 10**400},
    ],
)
def test_claim_failures_are_rejected(
    keys: Keys, verifier: JwtVerifier, overrides: dict[str, Any]
) -> None:
    with pytest.raises(TokenRejected) as info:
        verifier.verify(mint(keys, **overrides))
    assert str(info.value) == "token rejected"


def test_small_leeway_accepts_just_expired_token(keys: Keys, verifier: JwtVerifier) -> None:
    now = int(time.time())
    assert verifier.verify(mint(keys, iat=now - 100, exp=now - 2)).subject == "sub-a-lawyer"


def test_alg_none_is_rejected(keys: Keys, verifier: JwtVerifier) -> None:
    unsigned = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "iat": 1, "exp": 2},
        None,  # type: ignore[arg-type]
        algorithm="none",
        headers={"kid": "rsa-1"},
    )
    with pytest.raises(TokenRejected):
        verifier.verify(unsigned)
    # A bare "header.payload." form also fails the shape check.
    with pytest.raises(TokenRejected):
        verifier.verify(unsigned.rstrip("."))


def test_hs256_key_confusion_with_public_key_is_rejected(keys: Keys, verifier: JwtVerifier) -> None:
    public_pem = keys.rsa_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    now = int(time.time())
    header = _b64({"alg": "HS256", "kid": "rsa-1", "typ": "JWT"})
    payload = _b64({"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "iat": now, "exp": now + 60})
    signature = hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    forged = f"{header}.{payload}.{_b64(signature)}"
    with pytest.raises(TokenRejected):
        verifier.verify(forged)


def test_alg_must_match_the_selected_key(keys: Keys, verifier: JwtVerifier) -> None:
    # ES256 signature presented under the RSA key id.
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, alg="ES256", kid="rsa-1"))
    # Disallowed asymmetric algorithm even with a valid key.
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, alg="RS512", kid="rsa-1", key=keys.rsa_key))
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, alg="PS256", kid="rsa-1", key=keys.rsa_key))


def test_unknown_or_missing_kid_is_rejected(keys: Keys, verifier: JwtVerifier) -> None:
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, kid="rsa-2"))
    no_kid = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "iat": int(time.time()), "exp": 10**10},
        keys.rsa_key,
        algorithm="RS256",
    )
    with pytest.raises(TokenRejected):
        verifier.verify(no_kid)


def test_wrong_signing_key_and_tampering_are_rejected(keys: Keys, verifier: JwtVerifier) -> None:
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, key=keys.attacker))
    good = mint(keys)
    header, payload, signature = good.split(".")
    elevated = _b64(
        {**json.loads(base64.urlsafe_b64decode(payload + "==")), "sub": "sub-a-partner"}
    )
    with pytest.raises(TokenRejected):
        verifier.verify(f"{header}.{elevated}.{signature}")
    flipped = signature[:-2] + ("A" if signature[-2] != "A" else "B") + signature[-1]
    with pytest.raises(TokenRejected):
        verifier.verify(f"{header}.{payload}.{flipped}")


@pytest.mark.parametrize(
    "extra",
    [
        {"jku": "https://evil.synthetic.test/jwks"},
        {"x5u": "https://evil.synthetic.test/cert"},
        {"jwk": {"kty": "RSA"}},
        {"x5c": ["AAAA"]},
        {"crit": ["exp"]},
        {"typ": "id_token+jwt"},
        {"typ": 7},
    ],
)
def test_forbidden_header_parameters(
    keys: Keys, verifier: JwtVerifier, extra: dict[str, Any]
) -> None:
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, headers=extra))


def test_access_token_typ_is_accepted(keys: Keys, verifier: JwtVerifier) -> None:
    assert verifier.verify(mint(keys, headers={"typ": "at+jwt"})).subject == "sub-a-lawyer"


@pytest.mark.parametrize(
    "token",
    [
        "",
        "abc",
        "a.b",
        "a.b.c.d",
        "a b.c.d",
        "é.é.é",
        "x" * (MAX_TOKEN_BYTES + 1),
        _b64(b"not json") + "." + _b64({}) + ".sig",
        _b64([1, 2]) + "." + _b64({}) + ".sig",
    ],
)
def test_malformed_tokens_are_rejected(verifier: JwtVerifier, token: str) -> None:
    with pytest.raises(TokenRejected):
        verifier.verify(token)


def test_oversize_valid_token_is_rejected(keys: Keys, verifier: JwtVerifier) -> None:
    token = mint(keys, padding="p" * MAX_TOKEN_BYTES)
    with pytest.raises(TokenRejected):
        verifier.verify(token)


def test_non_string_token_is_rejected(verifier: JwtVerifier) -> None:
    with pytest.raises(TokenRejected):
        verifier.verify(None)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- JWKS loading


def _rsa_jwk(key: rsa.RSAPrivateKey, **extra: Any) -> dict[str, Any]:
    return {
        **RSAAlgorithm.to_jwk(key.public_key(), as_dict=True),
        "kid": "k1",
        "alg": "RS256",
        **extra,
    }


def test_jwks_from_file(tmp_path: Path, keys: Keys) -> None:
    path = tmp_path / "jwks.json"
    path.write_text(keys.jwks_json(), encoding="utf-8")
    assert set(load_jwks(str(path))) == {"rsa-1", "ec-1", "ed-1"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda k: {"keys": [{**k, "alg": "HS256"}]},
        lambda k: {"keys": [{**k, "alg": None}]},
        lambda k: {"keys": [{**k, "kid": None}]},
        lambda k: {"keys": [{**k, "kid": ""}]},
        lambda k: {"keys": [{**k, "alg": "ES256"}]},  # kty mismatch
        lambda k: {"keys": [{**k, "use": "enc"}]},
        lambda k: {"keys": [{**k, "key_ops": ["encrypt"]}]},
        lambda k: {"keys": [{**k, "d": "AAAA"}]},  # private member
        lambda k: {"keys": [{**k, "n": "!!"}]},
        lambda k: {"keys": [k, k]},  # duplicate kid
        lambda k: {"keys": []},
        lambda k: {"keys": [k] * 21},
        lambda k: {"keys": "nope"},
        lambda k: {"keys": ["nope"]},
        lambda k: [k],
        lambda k: {"keys": [{"kty": "oct", "k": "c2VjcmV0", "kid": "h", "alg": "HS256"}]},
    ],
)
def test_invalid_jwks_fails_closed(keys: Keys, mutate: Any) -> None:
    with pytest.raises(JwksConfigError):
        load_jwks(json.dumps(mutate(_rsa_jwk(keys.rsa_key))))


def test_ec_curve_and_okp_curve_must_match(keys: Keys) -> None:
    jwks = keys.jwks()
    ec_key = {**jwks["keys"][1], "crv": "P-384"}
    with pytest.raises(JwksConfigError):
        load_jwks(json.dumps({"keys": [ec_key]}))
    ed_key = {**jwks["keys"][2], "crv": "X25519"}
    with pytest.raises(JwksConfigError):
        load_jwks(json.dumps({"keys": [ed_key]}))


def test_weak_rsa_key_is_rejected() -> None:
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)  # noqa: S505
    with pytest.raises(JwksConfigError):
        load_jwks(json.dumps({"keys": [_rsa_jwk(weak)]}))


def test_jwks_source_errors(tmp_path: Path) -> None:
    with pytest.raises(JwksConfigError):
        load_jwks("")
    with pytest.raises(JwksConfigError):
        load_jwks(str(tmp_path / "missing.json"))
    with pytest.raises(JwksConfigError):
        load_jwks("{not json")
    big = tmp_path / "big.json"
    big.write_text("{" + " " * MAX_JWKS_BYTES + "}", encoding="utf-8")
    with pytest.raises(JwksConfigError):
        load_jwks(str(big))
    with pytest.raises(JwksConfigError):
        load_jwks('{"keys": []' + " " * MAX_JWKS_BYTES + "}")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"issuer": ""},
        {"issuer": " https://idp.synthetic.test/"},
        {"issuer": "https://idp synthetic"},
        {"audience": ""},
        {"keys": {}},
        {"leeway_seconds": 121},
        {"leeway_seconds": -1},
        {"max_lifetime_seconds": 59},
        {"max_lifetime_seconds": 86401},
    ],
)
def test_verifier_configuration_is_bounded(keys: Keys, kwargs: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "keys": load_jwks(keys.jwks_json()),
    }
    values.update(kwargs)
    with pytest.raises(JwksConfigError):
        JwtVerifier(**values)
