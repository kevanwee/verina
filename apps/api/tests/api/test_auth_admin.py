"""Supabase Auth admin port and platform-admin bootstrap (ADR 009). No real network."""

import base64
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select

from verina.access.accounts import (
    AccountsError,
    bootstrap_platform_admin,
    normalise_email,
)
from verina.access.auth_admin import (
    LOOKUP_PAGE_SIZE,
    MAX_RESPONSE_BYTES,
    AuthAdminError,
    FakeAuthAdmin,
    InviteAlreadyAccepted,
    SupabaseAuthAdmin,
    validate_project_url,
)
from verina.access.directory_schema import SYSTEM_CHAIN_ID, platform_admins
from verina.access.provision import run as provision
from verina.access.subject_hmac import derive_subject_key
from verina.audit import SqlAuditStore
from verina.config import Settings

from .conftest import ISSUER

pytestmark = pytest.mark.story("US-47")

PROJECT = "https://synthetic-ref.supabase.co"
SUPA_ISSUER = PROJECT + "/auth/v1"
# Generated per run so no key-shaped literal is committed (secret scanners stay quiet).
SECRET = "sb_" + "secret_" + secrets.token_hex(16)
LEGACY = ".".join(
    base64.urlsafe_b64encode(part).rstrip(b"=").decode()
    for part in (b'{"alg":"HS256"}', b'{"role":"service_role"}', secrets.token_bytes(16))
)
USER_ID = "8d0fbd6e-3b0b-4a69-8f1e-2b6c55a7d001"
EMAIL = "invented.admin@example.test"


class Upstream:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get((request.method, request.url.path))
        if route is None:
            return httpx.Response(404, json={"msg": "not found"})
        return route(request)

    def admin(self, key: str = SECRET) -> SupabaseAuthAdmin:
        return SupabaseAuthAdmin(
            PROJECT,
            SecretStr(key),
            issuer=SUPA_ISSUER,
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )


def user(user_id: str = USER_ID, email: str = EMAIL) -> dict[str, Any]:
    return {"id": user_id, "email": email, "aud": "authenticated", "role": "authenticated"}


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


def test_invite_posts_email_with_redirect_and_secret_on_apikey_only(upstream: Upstream) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(200, json=user())
    subject = upstream.admin().invite_user(EMAIL, "http://localhost:3000/auth/callback")
    assert subject == USER_ID
    (request,) = upstream.requests
    assert request.url.params["redirect_to"] == "http://localhost:3000/auth/callback"
    assert json.loads(request.content) == {"email": EMAIL}
    assert request.headers["apikey"] == SECRET
    assert "authorization" not in request.headers
    assert request.headers["content-type"] == "application/json"


def test_legacy_service_role_key_is_also_sent_as_bearer(upstream: Upstream) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(200, json=user())
    upstream.admin(LEGACY).invite_user(EMAIL)
    (request,) = upstream.requests
    assert request.headers["authorization"] == f"Bearer {LEGACY}"
    assert "redirect_to" not in request.url.params


def test_existing_confirmed_user_is_looked_up_by_paging(upstream: Upstream) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(
        422, json={"error_code": "email_exists"}
    )
    filler = [user(f"00000000-0000-4000-8000-{i:012d}", f"u{i}@example.test") for i in range(200)]

    def users(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert request.url.params["per_page"] == str(LOOKUP_PAGE_SIZE)
        if page == 1:
            return httpx.Response(200, json={"users": filler})
        return httpx.Response(200, json={"users": [user(email=EMAIL.upper())]})

    upstream.routes[("GET", "/auth/v1/admin/users")] = users
    assert upstream.admin().invite_user(EMAIL) == USER_ID
    assert [r.url.path for r in upstream.requests] == [
        "/auth/v1/invite",
        "/auth/v1/admin/users",
        "/auth/v1/admin/users",
    ]


def test_lookup_that_never_finds_the_user_is_rejected(upstream: Upstream) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(422, json={})
    upstream.routes[("GET", "/auth/v1/admin/users")] = lambda r: httpx.Response(
        200, json={"users": []}
    )
    with pytest.raises(AuthAdminError) as failure:
        upstream.admin().invite_user(EMAIL)
    assert failure.value.kind == "rejected"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, "rate_limited"),
        (401, "misconfigured"),
        (403, "misconfigured"),
        (500, "unavailable"),
        (400, "rejected"),
    ],
)
def test_upstream_errors_map_to_coarse_kinds(upstream: Upstream, status: int, kind: str) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(
        status, json={"msg": "synthetic"}
    )
    with pytest.raises(AuthAdminError) as failure:
        upstream.admin().invite_user(EMAIL)
    assert failure.value.kind == kind
    assert SECRET not in str(failure.value) and EMAIL not in str(failure.value)


@pytest.mark.parametrize(
    "body",
    [
        {"id": "not-a-uuid", "email": EMAIL},
        {"id": USER_ID, "email": "someone.else@example.test"},
        ["not", "an", "object"],
        None,
    ],
)
def test_malformed_invite_responses_are_unavailable(upstream: Upstream, body: Any) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(200, json=body)
    with pytest.raises(AuthAdminError) as failure:
        upstream.admin().invite_user(EMAIL)
    assert failure.value.kind == "unavailable"


def test_oversize_and_network_failures_are_unavailable(upstream: Upstream) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(
        200, content=b"x" * (MAX_RESPONSE_BYTES + 1)
    )
    with pytest.raises(AuthAdminError):
        upstream.admin().invite_user(EMAIL)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("synthetic", request=request)

    upstream.routes[("POST", "/auth/v1/invite")] = down
    with pytest.raises(AuthAdminError) as failure:
        upstream.admin().invite_user(EMAIL)
    assert failure.value.kind == "unavailable"


def test_lookup_failures(upstream: Upstream) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(422, json={})
    upstream.routes[("GET", "/auth/v1/admin/users")] = lambda r: httpx.Response(503)
    with pytest.raises(AuthAdminError):
        upstream.admin().invite_user(EMAIL)
    upstream.routes[("GET", "/auth/v1/admin/users")] = lambda r: httpx.Response(200, json=[])
    with pytest.raises(AuthAdminError):
        upstream.admin().invite_user(EMAIL)


def test_resend_invite(upstream: Upstream) -> None:
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(200, json=user())
    upstream.admin().resend_invite(EMAIL, "http://localhost:3000/auth/callback")
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(422, json={})
    with pytest.raises(InviteAlreadyAccepted):
        upstream.admin().resend_invite(EMAIL)
    upstream.routes[("POST", "/auth/v1/invite")] = lambda r: httpx.Response(502)
    with pytest.raises(AuthAdminError):
        upstream.admin().resend_invite(EMAIL)


@pytest.mark.parametrize(
    "url",
    [
        "http://synthetic-ref.supabase.co",
        "https://synthetic-ref.supabase.co/auth/v1",
        "https://user:pw@synthetic-ref.supabase.co",
        "https://synthetic-ref.supabase.co?x=1",
        "https://other-ref.supabase.co",
        "",
    ],
)
def test_project_url_validation(url: str) -> None:
    with pytest.raises(AuthAdminError):
        validate_project_url(url, SUPA_ISSUER)
    assert validate_project_url(PROJECT + "/", SUPA_ISSUER) == PROJECT


def test_secret_key_is_required_and_never_in_repr() -> None:
    with pytest.raises(AuthAdminError):
        SupabaseAuthAdmin(PROJECT, SecretStr("  "))
    admin = SupabaseAuthAdmin(PROJECT, SecretStr(SECRET))
    assert SECRET not in repr(admin.__dict__)
    admin.close()
    borrowed = httpx.Client()
    SupabaseAuthAdmin(PROJECT, SecretStr(SECRET), client=borrowed).close()
    assert not borrowed.is_closed
    borrowed.close()
    settings = Settings(_env_file=None, supabase_secret_key=SECRET)
    assert SECRET not in repr(settings) and SECRET not in str(settings.model_dump())


def test_fake_auth_admin_behaviour() -> None:
    fake = FakeAuthAdmin()
    first = fake.invite_user("a@example.test", "http://x")
    assert fake.invite_user("a@example.test") == first
    fake.resend_invite("a@example.test")
    fake.confirm("a@example.test")
    with pytest.raises(InviteAlreadyAccepted):
        fake.resend_invite("a@example.test")
    with pytest.raises(AuthAdminError):
        fake.resend_invite("nobody@example.test")
    fake.fail_with = "unavailable"
    with pytest.raises(AuthAdminError):
        fake.invite_user("b@example.test")
    with pytest.raises(AuthAdminError):
        fake.resend_invite("a@example.test")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Invented.Person@Example.TEST", "invented.person@example.test"),
        ("  a+tag@sub.example.test ", "a+tag@sub.example.test"),
    ],
)
def test_email_normalisation(raw: str, expected: str) -> None:
    assert normalise_email(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "no-at-sign",
        "a@b",
        "a@-b.test",
        "a b@example.test",
        "é@example.test",
        "a@" + "b" * 250 + ".test",
        "x" * 65 + "@example.test",
        42,
        "a@exa mple.test",
        "a@example.test‮",
    ],
)
def test_email_rejections(raw: Any) -> None:
    with pytest.raises(ValueError):
        normalise_email(raw)


# ----------------------------------------------------------------------------- bootstrap

HEAD_KEY = "synthetic-test-head-key-0123456789abcdef"


def test_bootstrap_grants_once_and_audits_on_the_system_chain(engine: Engine) -> None:
    fake = FakeAuthAdmin()
    store = SqlAuditStore(engine, head_key=HEAD_KEY.encode())
    admin_id = bootstrap_platform_admin(
        engine,
        store,
        fake,
        issuer=ISSUER,
        email=EMAIL.upper(),
        redirect_to="http://localhost:3000/auth/callback",
        subject_key=derive_subject_key(HEAD_KEY.encode()),
    )
    assert admin_id.startswith("pa_")
    assert fake.invites == [(EMAIL, "http://localhost:3000/auth/callback")]
    with engine.begin() as conn:
        row = conn.execute(select(platform_admins)).one()
    assert (row.issuer, row.subject, row.admin_id) == (ISSUER, fake.users[EMAIL][0], admin_id)
    (event,) = store.events(SYSTEM_CHAIN_ID)
    assert event.payload["action"] == "platform_admin_bootstrapped"
    assert EMAIL not in json.dumps(event.payload)
    assert store.verify_chain(SYSTEM_CHAIN_ID).ok
    with pytest.raises(AccountsError):
        bootstrap_platform_admin(engine, store, fake, issuer=ISSUER, email="other@example.test")
    assert len(fake.invites) == 1  # refused before inviting anyone


def test_bootstrap_audit_failure_rolls_back(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqlAuditStore(engine)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(store, "append_on_connection", boom)
    with pytest.raises(RuntimeError):
        bootstrap_platform_admin(engine, store, FakeAuthAdmin(), issuer=ISSUER, email=EMAIL)
    with engine.begin() as conn:
        assert conn.execute(select(platform_admins)).first() is None


def _settings(db_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "development",
        "database_url": db_url,
        "auth_issuer": ISSUER,
        "supabase_url": PROJECT,
        "supabase_secret_key": SECRET,
        "audit_head_key": HEAD_KEY,
    }
    values.update(overrides)
    return Settings(_env_file=None, **{k: v for k, v in values.items() if v is not None})


def test_bootstrap_cli(db_url: str, engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeAuthAdmin()
    argv = ["bootstrap-platform-admin", "--email", EMAIL]
    assert provision(argv, _settings(db_url), auth_admin_factory=lambda s: fake) == 0
    assert provision(argv, _settings(db_url), auth_admin_factory=lambda s: fake) == 1
    out = capsys.readouterr()
    assert EMAIL not in out.out + out.err and SECRET not in out.out + out.err
    assert "already exists" in out.err


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"env": "production"}, 2),
        ({"env": "staging"}, 2),
        ({"auth_issuer": None}, 2),
    ],
)
def test_bootstrap_cli_guards(
    db_url: str, engine: Engine, overrides: dict[str, Any], code: int
) -> None:
    fake = FakeAuthAdmin()
    argv = ["bootstrap-platform-admin", "--email", EMAIL]
    assert (
        provision(argv, _settings(db_url, **overrides), auth_admin_factory=lambda s: fake) == code
    )
    assert fake.invites == []


def test_bootstrap_cli_refuses_defaulted_env(
    db_url: str, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VERINA_ENV", raising=False)
    settings = Settings(_env_file=None, database_url=db_url, auth_issuer=ISSUER)
    assert provision(["bootstrap-platform-admin", "--email", EMAIL], settings) == 2


def test_bootstrap_cli_failures(
    db_url: str, engine: Engine, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    argv = ["bootstrap-platform-admin", "--email", EMAIL]
    failing = FakeAuthAdmin(fail_with="unavailable")
    assert provision(argv, _settings(db_url), auth_admin_factory=lambda s: failing) == 1
    assert "identity provider" in capsys.readouterr().err
    bad = ["bootstrap-platform-admin", "--email", "not-an-email"]
    assert provision(bad, _settings(db_url), auth_admin_factory=lambda s: FakeAuthAdmin()) == 1
    # The real factory refuses an incomplete Supabase configuration.
    assert provision(argv, _settings(db_url, supabase_secret_key=None)) == 1
    assert provision(argv, _settings(db_url, supabase_url="http://insecure.test")) == 1
    broken = _settings(f"sqlite:///{tmp_path / 'unmigrated.db'}")
    assert provision(argv, broken, auth_admin_factory=lambda s: FakeAuthAdmin()) == 1
