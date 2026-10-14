"""Rate limits and authentication-failure audit (ADR 009; SEC M4 and L5, partial)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from verina.access import IdentityDirectory, Role
from verina.access.auth_admin import FakeAuthAdmin
from verina.access.directory_schema import SYSTEM_CHAIN_ID, platform_admins
from verina.access.subject_hmac import derive_subject_key, subject_hmac
from verina.api.gate import AuthGate, Limits, RateLimited, TokenBucket
from verina.api.matters import MattersApi
from verina.audit.schema import audit_events
from verina.main import create_app

from .conftest import ISSUER, Keys, api_settings, bearer, mint

pytestmark = pytest.mark.story("US-47")

HEAD_KEY = "synthetic-test-head-key-0123456789abcdef"
PLATFORM = "sub-platform"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def client(
    db_url: str, keys: Keys, directory: IdentityDirectory, engine: Engine
) -> Iterator[TestClient]:
    directory.upsert_principal("tenant-a", "a-admin", [Role.TENANT_ADMIN], display_name="Admin A")
    directory.bind(ISSUER, "sub-a-admin", "tenant-a", "a-admin")
    with engine.begin() as conn:
        conn.execute(
            platform_admins.insert().values(
                issuer=ISSUER,
                subject=PLATFORM,
                admin_id="pa_gate",
                created_at=datetime(2026, 10, 14, tzinfo=UTC),
            )
        )
    app = create_app(api_settings(db_url, keys, audit_head_key=HEAD_KEY))
    with TestClient(app) as test_client:
        api_of(test_client).accounts._auth_admin = FakeAuthAdmin()
        yield test_client


def api_of(client: TestClient) -> MattersApi:
    api = client.app.state.matters_api  # type: ignore[attr-defined]
    assert isinstance(api, MattersApi)
    return api


def replace_gate(client: TestClient, gate: AuthGate) -> None:
    object.__setattr__(api_of(client), "gate", gate)


def failures(engine: Engine) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        rows = conn.execute(
            select(audit_events.c.payload)
            .where(
                audit_events.c.tenant_id == SYSTEM_CHAIN_ID,
                audit_events.c.event_type == "auth.failure",
            )
            .order_by(audit_events.c.sequence)
        ).scalars()
        return [json.loads(r) for r in rows]


# ----------------------------------------------------------------------------- token bucket


def test_token_bucket_capacity_refill_and_retry_after() -> None:
    clock = Clock()
    bucket = TokenBucket(3, 1.0, clock=clock)
    assert bucket.retry_after("k") is None
    assert [bucket.try_acquire("k") for _ in range(4)] == [True, True, True, False]
    assert bucket.retry_after("k") == 1
    assert bucket.try_acquire("other")  # keys are independent
    clock.now += 1.0
    assert bucket.retry_after("k") is None
    assert bucket.try_acquire("k") and not bucket.try_acquire("k")
    clock.now += 100
    assert [bucket.try_acquire("k") for _ in range(4)] == [True, True, True, False]


def test_token_bucket_evicts_least_recent_keys() -> None:
    clock = Clock()
    bucket = TokenBucket(1, 0.001, max_keys=2, clock=clock)
    assert bucket.try_acquire("a") and bucket.try_acquire("b") and bucket.try_acquire("c")
    assert bucket.try_acquire("a")  # "a" was evicted, so it starts full again
    assert not bucket.try_acquire("c")


@pytest.mark.parametrize("args", [(0, 1.0), (1, 0.0), (1, -1.0)])
def test_token_bucket_validation(args: tuple[int, float]) -> None:
    with pytest.raises(ValueError):
        TokenBucket(*args)
    with pytest.raises(ValueError):
        TokenBucket(1, 1.0, max_keys=0)


def test_rate_limited_has_a_positive_retry_after() -> None:
    assert RateLimited(0).retry_after == 1


# ----------------------------------------------------------------------------- auth failure audit


def test_auth_failures_are_audited_with_reason_and_keyed_subject(
    client: TestClient, keys: Keys, engine: Engine, directory: IdentityDirectory
) -> None:
    client.get("/v1/me")
    client.get("/v1/admin/organizations", headers=bearer(mint(keys, key=keys.attacker)))
    client.get("/v1/admin/organizations", headers=bearer(mint(keys, "sub-unbound")))
    directory.set_active("tenant-a", "a-lawyer", False)
    client.get("/v1/matters/whatever", headers=bearer(mint(keys, "sub-a-lawyer")))
    client.get("/v1/organizations/tenant-a/members", headers={"Authorization": "Basic x"})
    events = failures(engine)
    assert [(e["reason_class"], e["surface"]) for e in events] == [
        ("missing_credential", "me"),
        ("token_rejected", "admin"),
        ("unbound", "admin"),
        ("principal_inactive", "matters"),
        ("malformed_credential", "members"),
    ]
    key = derive_subject_key(HEAD_KEY.encode())
    assert events[2]["subject_hmac"] == subject_hmac(key, ISSUER, "sub-unbound")
    assert events[3]["subject_hmac"] == subject_hmac(key, ISSUER, "sub-a-lawyer")
    assert events[0]["subject_hmac"] is None and events[1]["subject_hmac"] is None
    dumped = json.dumps(events)
    assert "sub-unbound" not in dumped and "sub-a-lawyer" not in dumped
    assert all(e["actor"] == "unauthenticated" for e in events)
    assert api_of(client).audit.verify_chain(SYSTEM_CHAIN_ID).ok


def test_me_with_unbound_token_is_not_a_failure(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    assert client.get("/v1/me", headers=bearer(mint(keys, "sub-unbound"))).json() == {
        "linked": False
    }
    assert failures(engine) == []


def test_repeated_failures_from_one_client_are_throttled(client: TestClient, keys: Keys) -> None:
    clock = Clock()
    replace_gate(
        client,
        AuthGate(
            api_of(client).audit,
            limits=Limits(failures_per_client=3, failure_refill_per_second=0.1),
            clock=clock,
        ),
    )
    good = bearer(mint(keys, "sub-a-lawyer"))
    assert client.get("/v1/me", headers=good).status_code == 200
    for _ in range(3):
        assert client.get("/v1/me", headers=bearer("x.y.z")).status_code == 401
    limited = client.get("/v1/me", headers=good)
    assert (limited.status_code, limited.json()) == (429, {"error": "rate_limited"})
    assert int(limited.headers["Retry-After"]) >= 1
    blocked_matters = client.get("/v1/matters/whatever", headers=good)
    assert blocked_matters.status_code == 429
    clock.now += 11
    assert client.get("/v1/me", headers=good).status_code == 200


def test_failure_audit_writes_are_rate_limited_with_a_suppressed_count(
    client: TestClient, engine: Engine
) -> None:
    clock = Clock()
    replace_gate(
        client,
        AuthGate(
            api_of(client).audit,
            limits=Limits(audited_failures=2, audit_refill_per_second=0.5),
            clock=clock,
        ),
    )
    for _ in range(5):
        assert client.get("/v1/me").status_code == 401
    assert len(failures(engine)) == 2
    clock.now += 2
    client.get("/v1/me")
    events = failures(engine)
    assert len(events) == 3 and events[-1]["suppressed_since_last"] == 3


def test_failure_audit_outage_keeps_the_401(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = api_of(client).audit

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(store, "append", boom)
    response = client.get("/v1/me")
    assert response.status_code == 401
    monkeypatch.undo()
    client.get("/v1/me")
    events = failures(engine)
    assert len(events) == 1 and events[0]["suppressed_since_last"] == 1


def test_unknown_reason_is_recorded_generically(client: TestClient, engine: Engine) -> None:
    import asyncio

    from verina.access.identity import AuthenticationError

    gate = api_of(client).gate

    class Request:
        client = None

    asyncio.run(gate.failed(Request(), AuthenticationError("something_new"), "me"))  # type: ignore[arg-type]
    assert failures(engine)[-1]["reason_class"] == "unauthenticated"


# ----------------------------------------------------------------------------- invite limits


def test_invites_and_resends_are_limited_per_account(client: TestClient, keys: Keys) -> None:
    replace_gate(
        client,
        AuthGate(
            api_of(client).audit,
            limits=Limits(invites_per_account=2, invite_refill_per_second=0.001),
        ),
    )

    def invite(subject: str, email: str) -> Any:
        return client.post(
            "/v1/organizations/tenant-a/members",
            headers={**bearer(mint(keys, subject)), "Idempotency-Key": str(uuid4())},
            json={"email": email, "display_name": "Invented", "roles": ["lawyer"]},
        )

    first = invite("sub-a-admin", "one@example.test")
    assert first.status_code == 201
    resend = client.post(
        f"/v1/organizations/tenant-a/members/{first.json()['actor_id']}/resend-invite",
        headers={**bearer(mint(keys, "sub-a-admin")), "Idempotency-Key": str(uuid4())},
    )
    assert resend.status_code == 202
    limited = invite("sub-a-admin", "two@example.test")
    assert (limited.status_code, limited.json()) == (429, {"error": "rate_limited"})
    assert "Retry-After" in limited.headers
    # Another account has its own budget.
    assert invite(PLATFORM, "three@example.test").status_code == 201
