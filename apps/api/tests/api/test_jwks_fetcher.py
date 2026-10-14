"""HTTPS JWKS fetcher (ADR 008). httpx MockTransport only; no real network."""

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from verina.access.jwks_fetcher import JwksFetcher, validate_jwks_url
from verina.access.tokens import (
    MAX_JWKS_BYTES,
    JwksConfigError,
    JwtVerifier,
    KeySourceUnavailable,
    TokenRejected,
)

from .conftest import AUDIENCE, Keys, mint

pytestmark = pytest.mark.story("US-47")

ISSUER = "https://idp.synthetic.test/"
URL = "https://idp.synthetic.test/.well-known/jwks.json"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Server:
    """Programmable JWKS endpoint behind an httpx MockTransport."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.calls = 0
        self.status = 200
        self.content_type = "application/json"
        self.body: bytes | None = None
        self.headers: dict[str, str] = {}
        self.fail = False
        self.gate: threading.Event | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert request.url == httpx.URL(URL)
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise httpx.ConnectError("synthetic outage", request=request)
        body = self.body if self.body is not None else json.dumps(self.document).encode()
        return httpx.Response(
            self.status,
            content=body,
            headers={"content-type": self.content_type, **self.headers},
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def fetcher(server: Server, clock: Clock, **kwargs: Any) -> JwksFetcher:
    return JwksFetcher(URL, issuer=ISSUER, client=server.client(), clock=clock, **kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def server(keys: Keys) -> Server:
    return Server(keys.jwks())


def test_fetches_once_and_caches(server: Server, clock: Clock) -> None:
    source = fetcher(server, clock)
    assert source.key_for("rsa-1") is not None
    assert source.key_for("ec-1") is not None
    assert source.key_for("ed-1") is not None
    assert server.calls == 1


def test_verifier_accepts_tokens_with_fetched_keys(
    server: Server, clock: Clock, keys: Keys
) -> None:
    verifier = JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys=fetcher(server, clock))
    assert verifier.verify(mint(keys, alg="ES256", kid="ec-1")).subject == "sub-a-lawyer"


def test_ttl_expiry_refetches(server: Server, clock: Clock) -> None:
    source = fetcher(server, clock, ttl_seconds=600)
    source.key_for("rsa-1")
    clock.advance(599)
    source.key_for("rsa-1")
    assert server.calls == 1
    clock.advance(2)
    source.key_for("rsa-1")
    assert server.calls == 2


def test_unknown_kid_refetch_is_rate_limited(server: Server, clock: Clock) -> None:
    source = fetcher(server, clock, refetch_interval_seconds=30)
    source.key_for("rsa-1")
    for _ in range(50):
        assert source.key_for("attacker-kid") is None
    assert server.calls == 1  # first fetch only; the interval has not elapsed
    clock.advance(31)
    assert source.key_for("attacker-kid") is None
    assert server.calls == 2
    assert source.key_for("another-unknown") is None
    assert server.calls == 2


def test_rotation_picks_up_new_kid(server: Server, clock: Clock, keys: Keys) -> None:
    source = fetcher(server, clock)
    assert source.key_for("rsa-1") is not None
    rotated = dict(server.document)
    rotated["keys"] = [{**k, "kid": "rsa-2"} if k["kid"] == "rsa-1" else k for k in rotated["keys"]]
    server.document = rotated
    clock.advance(31)
    assert source.key_for("rsa-2") is not None


def test_last_good_keys_survive_outage_until_max_stale(server: Server, clock: Clock) -> None:
    source = fetcher(server, clock, ttl_seconds=600, max_stale_seconds=3600)
    assert source.key_for("rsa-1") is not None
    server.fail = True
    clock.advance(1200)  # expired; refresh fails; last good set still within bound
    assert source.key_for("rsa-1") is not None
    clock.advance(2401)  # now beyond max staleness: fail closed
    with pytest.raises(KeySourceUnavailable):
        source.key_for("rsa-1")
    server.fail = False
    clock.advance(31)
    assert source.key_for("rsa-1") is not None


def test_never_fetched_fails_closed(server: Server, clock: Clock, keys: Keys) -> None:
    server.fail = True
    source = fetcher(server, clock)
    with pytest.raises(KeySourceUnavailable):
        source.key_for("rsa-1")
    verifier = JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys=source)
    with pytest.raises(KeySourceUnavailable):
        verifier.verify(mint(keys))
    assert server.calls == 1  # the verifier's lookup was rate-limited, not a second fetch


def _bad_responses() -> list[Callable[[Server], None]]:
    def status(s: Server) -> None:
        s.status = 500

    def redirect(s: Server) -> None:
        s.status = 302
        s.headers = {"location": "https://evil.synthetic.test/jwks.json"}

    def html(s: Server) -> None:
        s.content_type = "text/html"

    def oversize(s: Server) -> None:
        s.body = b'{"keys": [], "pad": "' + b"x" * (MAX_JWKS_BYTES + 10) + b'"}'

    def declared_oversize(s: Server) -> None:
        s.headers = {"content-length": str(MAX_JWKS_BYTES + 1)}

    def not_json(s: Server) -> None:
        s.body = b"{not json"

    def not_utf8(s: Server) -> None:
        s.body = b"\xff\xfe\x00"

    def private_key(s: Server) -> None:
        s.document = {"keys": [{**s.document["keys"][0], "d": "AAAA"}]}

    def symmetric(s: Server) -> None:
        s.document = {"keys": [{"kty": "oct", "k": "c2VjcmV0", "kid": "h", "alg": "HS256"}]}

    def empty(s: Server) -> None:
        s.document = {"keys": []}

    return [
        status,
        redirect,
        html,
        oversize,
        declared_oversize,
        not_json,
        not_utf8,
        private_key,
        symmetric,
        empty,
    ]


@pytest.mark.parametrize("breaker", _bad_responses())
def test_bad_responses_are_discarded(
    server: Server, clock: Clock, breaker: Callable[[Server], None]
) -> None:
    good = fetcher(server, clock)
    assert good.key_for("rsa-1") is not None
    breaker(server)
    clock.advance(601)
    # Refresh fails validation; the last good set is kept (still within max staleness).
    assert good.key_for("rsa-1") is not None
    fresh = fetcher(server, Clock())
    with pytest.raises(KeySourceUnavailable):
        fresh.key_for("rsa-1")


def test_concurrent_unknown_kid_lookups_are_single_flight(server: Server, keys: Keys) -> None:
    clock = Clock()
    source = fetcher(server, clock)
    server.gate = threading.Event()
    results: list[object] = []

    def lookup() -> None:
        results.append(source.key_for("rsa-1"))

    threads = [threading.Thread(target=lookup) for _ in range(8)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    server.gate.set()
    for thread in threads:
        thread.join(5)
    assert server.calls == 1
    assert len(results) == 8 and all(r is not None for r in results)


@pytest.mark.parametrize(
    "url",
    [
        "http://idp.synthetic.test/jwks.json",
        "https://other.synthetic.test/jwks.json",
        "https://idp.synthetic.test.evil.test/jwks.json",
        "https://idp.synthetic.test:8443/jwks.json",
        "https://user:pw@idp.synthetic.test/jwks.json",
        "https://idp.synthetic.test/jwks.json?x=1",
        "https://idp.synthetic.test/jwks.json#frag",
        " https://idp.synthetic.test/jwks.json",
        "https://idp.synthetic.test/jw ks.json",
        "",
        "file:///etc/passwd",
    ],
)
def test_url_must_be_https_on_the_issuer_host(url: str) -> None:
    with pytest.raises(JwksConfigError):
        validate_jwks_url(url, ISSUER)


def test_issuer_must_be_https_for_a_fetched_key_set() -> None:
    with pytest.raises(JwksConfigError):
        validate_jwks_url(URL, "http://idp.synthetic.test/")
    assert validate_jwks_url("https://IDP.synthetic.test:443/x", ISSUER)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ttl_seconds": 59},
        {"ttl_seconds": 86401},
        {"refetch_interval_seconds": 0},
        {"refetch_interval_seconds": 601, "ttl_seconds": 600},
        {"max_stale_seconds": 10},
        {"max_stale_seconds": 8 * 86400},
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"max_bytes": 0},
        {"max_bytes": MAX_JWKS_BYTES + 1},
    ],
)
def test_fetcher_bounds(kwargs: dict[str, Any]) -> None:
    with pytest.raises(JwksConfigError):
        JwksFetcher(URL, issuer=ISSUER, **kwargs)


def test_default_client_is_owned_and_closed() -> None:
    source = JwksFetcher(URL, issuer=ISSUER)
    source.close()
    borrowed = httpx.Client()
    other = JwksFetcher(URL, issuer=ISSUER, client=borrowed)
    other.close()
    assert not borrowed.is_closed
    borrowed.close()


def test_rejected_token_is_not_key_unavailable(server: Server, clock: Clock, keys: Keys) -> None:
    verifier = JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys=fetcher(server, clock))
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, kid="unknown-kid"))
    with pytest.raises(TokenRejected):
        verifier.verify(mint(keys, kid="k" * 129))
