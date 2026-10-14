"""Bounded HTTPS JWKS fetcher (ADR 009; closes the ADR 007 "reviewed fetcher" follow-up).

:class:`JwksFetcher` is a :class:`~verina.access.tokens.KeySource`. Controls:

* **Where:** HTTPS only, no user-info, query or fragment, and the URL host and port must equal
  the configured issuer's host and port, so a configuration typo cannot point verification at
  a third party. Redirects are not followed and environment proxies are ignored.
* **What:** a ``200`` response with a JSON media type, at most ``max_bytes`` (streamed, so
  an oversize body is cut off rather than buffered), validated by the same
  :func:`~verina.access.tokens.parse_jwks` rules as a static key set (asymmetric allowlist,
  ``kid``/``alg`` required, public keys only, RSA >= 2048 bits). Any failure discards the
  response and keeps the previous good set.
* **When:** keys are cached for ``ttl_seconds``. An unknown ``kid`` triggers a refetch, but
  refetches (for any reason) are rate-limited to one per ``refetch_interval_seconds`` and are
  single-flight: concurrent callers wait for the one in-flight fetch instead of starting their
  own. There is never a fetch per request.
* **Staleness:** when refreshing fails, the last good set keeps working until
  ``max_stale_seconds`` after it was fetched; after that (or before the first success) every
  lookup raises :class:`~verina.access.tokens.KeySourceUnavailable` (fail closed, HTTP 503).

Logs carry the failure class only, never the response body or URL query.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from verina.access.tokens import (
    MAX_JWKS_BYTES,
    JwksConfigError,
    KeySourceUnavailable,
    VerificationKey,
    parse_jwks,
)

logger = logging.getLogger(__name__)

_JSON_MEDIA_TYPES = frozenset({"application/json", "application/jwk-set+json"})

DEFAULT_TTL_SECONDS = 600
DEFAULT_REFETCH_INTERVAL_SECONDS = 30
DEFAULT_MAX_STALE_SECONDS = 6 * 3600
DEFAULT_TIMEOUT_SECONDS = 5.0


class JwksFetchError(Exception):
    """One fetch attempt failed. Internal; never surfaces to callers of :meth:`key_for`."""


def _origin(url: str, *, what: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise JwksConfigError(f"{what} must be an https URL")
    if parts.username is not None or parts.password is not None:
        raise JwksConfigError(f"{what} must not contain credentials")
    try:
        port = parts.port or 443
    except ValueError:
        raise JwksConfigError(f"{what} has an invalid port") from None
    return parts.hostname.lower(), port


def validate_jwks_url(url: str, issuer: str) -> str:
    """Return ``url`` if it is an acceptable JWKS location for ``issuer``; else raise."""
    if not isinstance(url, str) or not url or len(url) > 2048 or url != url.strip():
        raise JwksConfigError("JWKS URL required")
    if any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise JwksConfigError("JWKS URL must not contain whitespace or control characters")
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise JwksConfigError("JWKS URL must not carry a query or fragment")
    if _origin(url, what="JWKS URL") != _origin(issuer, what="issuer"):
        raise JwksConfigError("JWKS URL host must equal the issuer host")
    return url


@dataclass(frozen=True, slots=True)
class _KeySet:
    keys: Mapping[str, VerificationKey]
    fetched_at: float


class JwksFetcher:
    def __init__(
        self,
        url: str,
        *,
        issuer: str,
        client: httpx.Client | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        refetch_interval_seconds: int = DEFAULT_REFETCH_INTERVAL_SECONDS,
        max_stale_seconds: int = DEFAULT_MAX_STALE_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = MAX_JWKS_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = validate_jwks_url(url, issuer)
        if not 60 <= ttl_seconds <= 86400:
            raise JwksConfigError("JWKS cache TTL out of range")
        if not 1 <= refetch_interval_seconds <= ttl_seconds:
            raise JwksConfigError("JWKS refetch interval out of range")
        if not ttl_seconds <= max_stale_seconds <= 7 * 86400:
            raise JwksConfigError("JWKS max staleness out of range")
        if not 0 < timeout_seconds <= 30:
            raise JwksConfigError("JWKS timeout out of range")
        if not 0 < max_bytes <= MAX_JWKS_BYTES:
            raise JwksConfigError("JWKS size cap out of range")
        self._client = client or httpx.Client(trust_env=False)
        self._owns_client = client is None
        self._ttl = ttl_seconds
        self._interval = refetch_interval_seconds
        self._max_stale = max_stale_seconds
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_bytes = max_bytes
        self._clock = clock
        self._lock = threading.Lock()
        self._state: _KeySet | None = None
        self._last_attempt: float | None = None
        self.fetch_count = 0
        """Number of network attempts made (observability and tests)."""

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ---- KeySource ---------------------------------------------------------------------

    def key_for(self, kid: str) -> VerificationKey | None:
        now = self._clock()
        state = self._state
        if state is None or now - state.fetched_at >= self._ttl or kid not in state.keys:
            self._refresh(now)
            state = self._state
        if state is None or self._clock() - state.fetched_at > self._max_stale:
            raise KeySourceUnavailable()
        return state.keys.get(kid)

    # ---- internals ---------------------------------------------------------------------

    def _refresh(self, requested_at: float) -> None:
        with self._lock:  # single flight: waiters re-check after the in-flight fetch ends
            last = self._last_attempt
            if last is not None and (last >= requested_at or requested_at - last < self._interval):
                return  # someone just tried (or we are rate-limited); use what we have
            self._last_attempt = self._clock()
            self.fetch_count += 1
            try:
                keys = self._fetch()
            except (JwksFetchError, JwksConfigError, httpx.HTTPError) as exc:
                logger.warning("JWKS refresh failed: %s", type(exc).__name__)
                return
            self._state = _KeySet(keys, self._clock())

    def _fetch(self) -> dict[str, VerificationKey]:
        with self._client.stream(
            "GET",
            self._url,
            headers={"Accept": "application/json"},
            timeout=self._timeout,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise JwksFetchError("unexpected status")
            media = response.headers.get("content-type", "").partition(";")[0].strip().lower()
            if media not in _JSON_MEDIA_TYPES:
                raise JwksFetchError("unexpected media type")
            declared = response.headers.get("content-length")
            if declared is not None and (not declared.isdigit() or int(declared) > self._max_bytes):
                raise JwksFetchError("response too large")
            size, chunks = 0, []
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self._max_bytes:
                    raise JwksFetchError("response too large")
                chunks.append(chunk)
        try:
            text = b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError:
            raise JwksFetchError("response is not UTF-8") from None
        return parse_jwks(text)
