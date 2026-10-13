"""Synthetic identity world for token, directory and HTTP tests.

Signing keys are generated in memory at test time; no private key is ever written to the
repository. Issuers, subjects, tenants, actors and titles are invented.
"""

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from fastapi.testclient import TestClient
from jwt.algorithms import ECAlgorithm, OKPAlgorithm, RSAAlgorithm
from sqlalchemy import Engine

from verina.access import IdentityDirectory, Role
from verina.access.tokens import JwtVerifier, load_jwks
from verina.config import Settings
from verina.db import downgrade, make_engine, upgrade
from verina.main import create_app

ISSUER = "https://idp.synthetic.test/"
AUDIENCE = "verina-api-test"
POSTGRES_URL = os.environ.get("VERINA_TEST_POSTGRES_URL")
BACKENDS = ["sqlite", "postgresql"] if POSTGRES_URL else ["sqlite"]

# subject, tenant, actor, roles, display name (None = no trusted profile)
PEOPLE: tuple[tuple[str, str, str, tuple[Role, ...], str | None], ...] = (
    ("sub-a-lawyer", "tenant-a", "a-lawyer", (Role.LAWYER,), "Synthetic Lawyer A"),
    ("sub-a-partner", "tenant-a", "a-partner", (Role.PARTNER,), "Synthetic Partner A"),
    ("sub-a-outsider", "tenant-a", "a-outsider", (Role.LAWYER,), "Synthetic Outsider A"),
    ("sub-a-requester", "tenant-a", "a-requester", (Role.REQUESTER,), "Synthetic Requester"),
    ("sub-a-knowledge", "tenant-a", "a-knowledge", (Role.KNOWLEDGE,), "Synthetic Knowledge"),
    ("sub-a-noprofile", "tenant-a", "a-noprofile", (Role.LAWYER,), None),
    ("sub-b-lawyer", "tenant-b", "b-lawyer", (Role.LAWYER,), "Synthetic Lawyer B"),
)


@dataclass(frozen=True)
class Keys:
    rsa_key: rsa.RSAPrivateKey
    ec_key: ec.EllipticCurvePrivateKey
    ed_key: ed25519.Ed25519PrivateKey
    attacker: rsa.RSAPrivateKey

    def jwks(self) -> dict[str, Any]:
        return {
            "keys": [
                {
                    **RSAAlgorithm.to_jwk(self.rsa_key.public_key(), as_dict=True),
                    "kid": "rsa-1",
                    "alg": "RS256",
                    "use": "sig",
                },
                {
                    **ECAlgorithm.to_jwk(self.ec_key.public_key(), as_dict=True),
                    "kid": "ec-1",
                    "alg": "ES256",
                },
                {
                    **OKPAlgorithm.to_jwk(self.ed_key.public_key(), as_dict=True),
                    "kid": "ed-1",
                    "alg": "EdDSA",
                },
            ]
        }

    def jwks_json(self) -> str:
        return json.dumps(self.jwks())


@pytest.fixture(scope="session")
def keys() -> Keys:
    return Keys(
        rsa_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        ec_key=ec.generate_private_key(ec.SECP256R1()),
        ed_key=ed25519.Ed25519PrivateKey.generate(),
        attacker=rsa.generate_private_key(public_exponent=65537, key_size=2048),
    )


def claims(subject: str = "sub-a-lawyer", **overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject,
        "iat": now - 5,
        "exp": now + 600,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def mint(
    keys: Keys,
    subject: str = "sub-a-lawyer",
    *,
    kid: str = "rsa-1",
    alg: str = "RS256",
    key: Any = None,
    headers: dict[str, Any] | None = None,
    **overrides: Any,
) -> str:
    signing = key
    if signing is None:
        signing = {"RS256": keys.rsa_key, "ES256": keys.ec_key, "EdDSA": keys.ed_key}[alg]
    return jwt.encode(
        claims(subject, **overrides),
        signing,
        algorithm=alg,
        headers={"kid": kid, **(headers or {})},
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def verifier(keys: Keys) -> JwtVerifier:
    return JwtVerifier(
        issuer=ISSUER, audience=AUDIENCE, keys=load_jwks(keys.jwks_json()), leeway_seconds=5
    )


@pytest.fixture(params=BACKENDS)
def db_url(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[str]:
    if request.param == "postgresql":
        assert POSTGRES_URL is not None
        url = POSTGRES_URL
        engine = make_engine(url)
        downgrade(engine)
    else:
        url = f"sqlite:///{tmp_path / 'identity.db'}"
        engine = make_engine(url)
    upgrade(engine)
    engine.dispose()
    yield url


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    # A short SQLite busy timeout turns any accidental second write transaction into a
    # fast failure instead of a 30 s stall.
    eng = (
        make_engine(db_url, connect_args={"timeout": 3})
        if db_url.startswith("sqlite")
        else make_engine(db_url)
    )
    try:
        yield eng
    finally:
        eng.dispose()


def seed_directory(engine: Engine) -> IdentityDirectory:
    directory = IdentityDirectory(engine)
    for subject, tenant, actor, roles, name in PEOPLE:
        directory.upsert_principal(tenant, actor, roles, display_name=name)
        directory.bind(ISSUER, subject, tenant, actor)
    return directory


@pytest.fixture
def directory(engine: Engine) -> IdentityDirectory:
    return seed_directory(engine)


def api_settings(db_url: str, keys: Keys, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "matters_api_enabled": True,
        "database_url": db_url,
        "auth_issuer": ISSUER,
        "auth_audience": AUDIENCE,
        "auth_jwks": keys.jwks_json(),
        "auth_leeway_seconds": 5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def client(db_url: str, keys: Keys, directory: IdentityDirectory) -> Iterator[TestClient]:
    app = create_app(api_settings(db_url, keys))
    with TestClient(app) as test_client:
        yield test_client
