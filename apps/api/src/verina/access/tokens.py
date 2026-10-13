"""Provider-neutral bearer-token verification against a configured static JWKS (ADR 007).

The verifier answers one question: did the configured issuer sign a currently valid token for
our audience, and if so, which ``(issuer, subject)`` does it name? It returns nothing else.
Tenant, actor, roles, active state and profile come from the Verina directory
(:mod:`verina.access.sql_identity`); token claims never grant authority.

Controls (all fail closed with :class:`TokenRejected`, which carries no detail):

* asymmetric algorithms only (``RS256``, ``ES256``, ``EdDSA``); ``none``, every ``HS*`` and
  any algorithm not bound to the selected key are rejected before signature verification;
* the header must name a ``kid`` present in the configured key set, and the header ``alg``
  must equal that key's declared ``alg``;
* embedded key material or key URLs in the header (``jwk``, ``jku``, ``x5u``, ``x5c``) and
  ``crit`` extensions are rejected; keys only ever come from configuration;
* exact ``iss``; ``aud`` must be the configured audience as a string or a single-element
  array. A multi-audience array is accepted only if every other value is in the explicit,
  empty-by-default ``extra_audiences`` allowlist (a token minted for several APIs is
  otherwise refused); ``exp``, ``iat`` and ``sub`` are required; ``nbf`` is honoured if present;
* bounded clock leeway, a maximum ``exp - iat`` lifetime and a maximum token size.

Keys are loaded once from configuration (inline JSON or a local file). No network fetch.
"""

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from jwt import PyJWK

ALLOWED_ALGORITHMS = frozenset({"RS256", "ES256", "EdDSA"})
_KEY_SHAPES: Mapping[str, tuple[str, str | None]] = {
    "RS256": ("RSA", None),
    "ES256": ("EC", "P-256"),
    "EdDSA": ("OKP", "Ed25519"),
}
_PRIVATE_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})
_FORBIDDEN_HEADERS = frozenset({"jwk", "jku", "x5u", "x5c", "crit"})
_ALLOWED_TYP = frozenset({"jwt", "at+jwt", "application/at+jwt"})
_JWT_SHAPE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")

MAX_TOKEN_BYTES = 8192
MAX_JWKS_BYTES = 65536
MAX_JWKS_KEYS = 20
MIN_RSA_BITS = 2048
MAX_LEEWAY_SECONDS = 120
MAX_SUBJECT_LENGTH = 255
MAX_ISSUER_LENGTH = 255


class TokenRejected(Exception):  # noqa: N818 - domain vocabulary
    """Any verification failure. Deliberately carries no cause, claim or token text."""

    def __init__(self) -> None:
        super().__init__("token rejected")


class JwksConfigError(ValueError):
    """The configured key set is unusable. Raised at startup; never at request time."""


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    """The only facts a token contributes: who issued it and the issuer's subject."""

    issuer: str
    subject: str


@dataclass(frozen=True, slots=True)
class _Key:
    algorithm: str
    key: Any


def _number(value: object) -> float | None:
    """A finite JSON NumericDate, or ``None`` (booleans and strings are not dates)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _validate_jwk(raw: object) -> tuple[str, _Key]:
    if not isinstance(raw, dict):
        raise JwksConfigError("each JWKS key must be an object")
    kid, alg, kty = raw.get("kid"), raw.get("alg"), raw.get("kty")
    if not isinstance(kid, str) or not 0 < len(kid) <= 128:
        raise JwksConfigError("each JWKS key needs a kid")
    if alg not in ALLOWED_ALGORITHMS or not isinstance(alg, str):
        raise JwksConfigError("each JWKS key needs an allowed asymmetric alg")
    expected_kty, expected_crv = _KEY_SHAPES[alg]
    if kty != expected_kty or (expected_crv is not None and raw.get("crv") != expected_crv):
        raise JwksConfigError("JWKS key type does not match its alg")
    if _PRIVATE_MEMBERS.intersection(raw):
        raise JwksConfigError("JWKS must contain public keys only")
    if raw.get("use", "sig") != "sig":
        raise JwksConfigError("JWKS key is not a signing key")
    key_ops = raw.get("key_ops")
    if key_ops is not None and (not isinstance(key_ops, list) or "verify" not in key_ops):
        raise JwksConfigError("JWKS key is not a verification key")
    try:
        key = PyJWK.from_dict(raw, algorithm=alg).key
    except (jwt.PyJWTError, ValueError, TypeError):
        raise JwksConfigError("JWKS key could not be loaded") from None
    if alg == "RS256" and (not isinstance(key, rsa.RSAPublicKey) or key.key_size < MIN_RSA_BITS):
        raise JwksConfigError("RSA keys must be public and at least 2048 bits")
    if alg == "ES256" and not isinstance(key, ec.EllipticCurvePublicKey):
        raise JwksConfigError("EC key must be public")
    if alg == "EdDSA" and not isinstance(key, ed25519.Ed25519PublicKey):
        raise JwksConfigError("EdDSA key must be a public Ed25519 key")
    return kid, _Key(alg, key)


def load_jwks(source: str) -> Mapping[str, _Key]:
    """Parse a JWKS from inline JSON (starts with ``{``) or a local file path."""
    if not isinstance(source, str) or not source.strip():
        raise JwksConfigError("JWKS source required")
    text = source.strip()
    if not text.startswith("{"):
        path = Path(text)
        try:
            if path.stat().st_size > MAX_JWKS_BYTES:
                raise JwksConfigError("JWKS file too large")
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise JwksConfigError("JWKS file unreadable") from None
    if len(text.encode("utf-8")) > MAX_JWKS_BYTES:
        raise JwksConfigError("JWKS too large")
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        raise JwksConfigError("JWKS is not valid JSON") from None
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise JwksConfigError("JWKS must be an object with a keys array")
    raw_keys = document["keys"]
    if not 0 < len(raw_keys) <= MAX_JWKS_KEYS:
        raise JwksConfigError("JWKS must contain between 1 and 20 keys")
    keys: dict[str, _Key] = {}
    for raw in raw_keys:
        kid, key = _validate_jwk(raw)
        if kid in keys:
            raise JwksConfigError("JWKS kid values must be unique")
        keys[kid] = key
    return keys


class JwtVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        keys: Mapping[str, _Key],
        leeway_seconds: int = 30,
        max_lifetime_seconds: int = 3600,
        extra_audiences: Iterable[str] = (),
    ) -> None:
        if not isinstance(issuer, str) or not 0 < len(issuer) <= MAX_ISSUER_LENGTH:
            raise JwksConfigError("issuer required")
        if issuer != issuer.strip() or any(ord(c) < 33 for c in issuer):
            raise JwksConfigError("issuer must not contain whitespace")
        if not isinstance(audience, str) or not 0 < len(audience) <= 255:
            raise JwksConfigError("audience required")
        extras = frozenset(extra_audiences)
        if any(not isinstance(a, str) or not 0 < len(a) <= 255 for a in extras):
            raise JwksConfigError("extra audiences must be non-empty strings")
        if not keys:
            raise JwksConfigError("at least one verification key required")
        if type(leeway_seconds) is not int or not 0 <= leeway_seconds <= MAX_LEEWAY_SECONDS:
            raise JwksConfigError("leeway out of range")
        if type(max_lifetime_seconds) is not int or not 60 <= max_lifetime_seconds <= 86400:
            raise JwksConfigError("max token lifetime out of range")
        self._issuer = issuer
        self._audience = audience
        self._extra_audiences = extras - {audience}
        self._keys = dict(keys)
        self._leeway = leeway_seconds
        self._max_lifetime = max_lifetime_seconds

    def verify(self, token: str) -> VerifiedToken:
        if not isinstance(token, str) or len(token) > MAX_TOKEN_BYTES:
            raise TokenRejected()
        if not token.isascii() or _JWT_SHAPE.fullmatch(token) is None:
            raise TokenRejected()
        try:
            header = jwt.get_unverified_header(token)
        except (jwt.PyJWTError, ValueError, TypeError, RecursionError):
            raise TokenRejected() from None
        key = self._select_key(header)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[key.algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_sub": True,
                },
            )
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError, RecursionError):
            raise TokenRejected() from None
        return self._check_claims(claims)

    def _select_key(self, header: object) -> _Key:
        if not isinstance(header, dict):
            raise TokenRejected()
        alg, kid, typ = header.get("alg"), header.get("kid"), header.get("typ")
        if not isinstance(alg, str) or alg not in ALLOWED_ALGORITHMS:
            raise TokenRejected()
        if _FORBIDDEN_HEADERS.intersection(header):
            raise TokenRejected()
        if typ is not None and (not isinstance(typ, str) or typ.lower() not in _ALLOWED_TYP):
            raise TokenRejected()
        if not isinstance(kid, str):
            raise TokenRejected()
        key = self._keys.get(kid)
        if key is None or key.algorithm != alg:
            raise TokenRejected()
        return key

    def _audience_ok(self, aud: object) -> bool:
        """Strict audience: ours alone, or ours plus explicitly allowlisted extras.

        PyJWT's ``strict_aud`` would also refuse a single-element array, which RFC 7519
        permits and some providers emit, so the strict rule is enforced here; PyJWT has
        already checked that our audience is present.
        """
        if isinstance(aud, str):
            return aud == self._audience
        if not isinstance(aud, list) or not aud or not all(isinstance(a, str) for a in aud):
            return False
        values = set(aud)
        return (
            len(values) == len(aud)
            and self._audience in values
            and values - {self._audience} <= self._extra_audiences
        )

    def _check_claims(self, claims: object) -> VerifiedToken:
        if not isinstance(claims, dict):
            raise TokenRejected()
        exp, iat = _number(claims.get("exp")), _number(claims.get("iat"))
        if exp is None or iat is None:
            raise TokenRejected()
        if "nbf" in claims and _number(claims["nbf"]) is None:
            raise TokenRejected()
        if exp <= iat or exp - iat > self._max_lifetime:
            raise TokenRejected()
        if not self._audience_ok(claims.get("aud")):
            raise TokenRejected()
        issuer, subject = claims.get("iss"), claims.get("sub")
        if issuer != self._issuer or not isinstance(subject, str):
            raise TokenRejected()
        if not 0 < len(subject) <= MAX_SUBJECT_LENGTH or any(
            ord(c) < 32 or ord(c) == 127 for c in subject
        ):
            raise TokenRejected()
        return VerifiedToken(self._issuer, subject)
