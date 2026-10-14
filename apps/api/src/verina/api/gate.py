"""Per-process abuse controls and authentication-failure audit for ``/v1`` (ADR 008).

Partially closes SEC L5 and SEC M4 from the ADR 007 enablement gate:

* :class:`TokenBucket` - a small thread-safe token-bucket limiter keyed by string, with a
  bounded number of tracked keys (least recently used keys are evicted).
* :class:`AuthGate` - before authenticating, refuses a client whose recent authentication
  failures exhausted its bucket (HTTP 429); after a failure, consumes that bucket and records
  an ``auth.failure`` event on the system audit chain with the reason class and, when the token
  itself verified, a keyed HMAC of ``(issuer, subject)``. Audit writes are themselves
  rate-limited; failures that are not recorded individually are counted in the next event's
  ``suppressed_since_last``. Invitations and resends are limited per calling account.

Limits of per-process limiting (documented in ADR 008): every worker process has its own
buckets, so the effective limit is multiplied by the number of workers and resets on restart;
the client key is the socket peer address, which behind a reverse proxy is the proxy unless
the server is run with trusted forwarded headers. A shared store (or the edge/WAF) is required
before any multi-instance or internet-exposed deployment.
"""

import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, get_args

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from verina.access.directory_schema import SYSTEM_CHAIN_ID
from verina.access.identity import AuthenticationError
from verina.access.subject_hmac import subject_hmac
from verina.audit.events import AuthenticationFailed
from verina.audit.store import SqlAuditStore

logger = logging.getLogger(__name__)

Surface = Literal["me", "admin", "members", "matters"]
_REASONS = frozenset(get_args(AuthenticationFailed.model_fields["reason_class"].annotation))


class RateLimited(Exception):  # noqa: N818 - domain vocabulary
    """The caller exceeded a per-process limit. Maps to 429 with ``Retry-After``."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limited")
        self.retry_after = max(1, retry_after)


class TokenBucket:
    def __init__(
        self,
        capacity: int,
        refill_per_second: float,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or refill_per_second <= 0 or max_keys < 1:
            raise ValueError("invalid token bucket")
        self._capacity = float(capacity)
        self._rate = refill_per_second
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def _level(self, key: str, now: float) -> float:
        tokens, updated = self._buckets.get(key, (self._capacity, now))
        return min(self._capacity, tokens + (now - updated) * self._rate)

    def _store(self, key: str, tokens: float, now: float) -> None:
        self._buckets[key] = (tokens, now)
        self._buckets.move_to_end(key)
        while len(self._buckets) > self._max_keys:
            self._buckets.popitem(last=False)

    def try_acquire(self, key: str) -> bool:
        """Take one token if available."""
        with self._lock:
            now = self._clock()
            tokens = self._level(key, now)
            if tokens < 1:
                self._store(key, tokens, now)
                return False
            self._store(key, tokens - 1, now)
            return True

    def retry_after(self, key: str) -> int | None:
        """Seconds until one token is available, or ``None`` if one is available now."""
        with self._lock:
            now = self._clock()
            if key not in self._buckets:
                return None
            tokens = self._level(key, now)
            if tokens >= 1:
                return None
            return max(1, math.ceil((1 - tokens) / self._rate))


@dataclass(frozen=True, slots=True)
class Limits:
    failures_per_client: int = 20
    failure_refill_per_second: float = 1 / 3
    audited_failures: int = 60
    audit_refill_per_second: float = 1.0
    invites_per_account: int = 10
    invite_refill_per_second: float = 1 / 60


class AuthGate:
    def __init__(
        self,
        audit: SqlAuditStore,
        *,
        subject_key: bytes | None = None,
        limits: Limits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        limits = limits or Limits()
        self._audit = audit
        self._subject_key = subject_key
        self._failures = TokenBucket(
            limits.failures_per_client, limits.failure_refill_per_second, clock=clock
        )
        self._audit_writes = TokenBucket(
            limits.audited_failures, limits.audit_refill_per_second, clock=clock
        )
        self._invites = TokenBucket(
            limits.invites_per_account, limits.invite_refill_per_second, clock=clock
        )
        self._suppressed = 0
        self._lock = threading.Lock()

    @staticmethod
    def client_key(request: Request) -> str:
        return request.client.host if request.client is not None else "unknown"

    def check_client(self, request: Request) -> None:
        """Refuse a client whose recent authentication failures exhausted its bucket."""
        wait = self._failures.retry_after(self.client_key(request))
        if wait is not None:
            raise RateLimited(wait)

    async def failed(self, request: Request, exc: AuthenticationError, surface: Surface) -> None:
        """Count an authentication failure for the client and audit it (rate-limited)."""
        self._failures.try_acquire(self.client_key(request))
        if not self._audit_writes.try_acquire("global"):
            with self._lock:
                self._suppressed += 1
            return
        await run_in_threadpool(self._record, exc, surface)

    def _record(self, exc: AuthenticationError, surface: Surface) -> None:
        with self._lock:
            suppressed, self._suppressed = self._suppressed, 0
        reason = exc.reason if exc.reason in _REASONS else "unauthenticated"
        subject = exc.subject
        try:
            self._audit.append(
                SYSTEM_CHAIN_ID,
                AuthenticationFailed.model_validate(
                    {
                        "occurred_at": datetime.now(UTC),
                        "tenant_id": SYSTEM_CHAIN_ID,
                        "reason_class": reason,
                        "surface": surface,
                        "subject_hmac": (
                            None
                            if subject is None
                            else subject_hmac(self._subject_key, subject[0], subject[1])
                        ),
                        "suppressed_since_last": suppressed,
                    }
                ),
            )
        except Exception as failure:  # the request is already denied; never fail open
            with self._lock:
                self._suppressed += suppressed + 1
            logger.warning("auth failure audit write failed: %s", type(failure).__name__)

    def allow_invite(self, account_key: str) -> None:
        """Per-account limit on invitations and resends (provider e-mail is scarce)."""
        if not self._invites.try_acquire(account_key):
            raise RateLimited(self._invites.retry_after(account_key) or 1)
