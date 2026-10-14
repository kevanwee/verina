"""Accounts routes: /v1/me, platform organizations and members (ADR 009). Synthetic only."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from verina.access import IdentityDirectory, Role
from verina.access.accounts import AccountsError, AccountsService, Caller
from verina.access.auth_admin import FakeAuthAdmin
from verina.access.directory_schema import (
    admin_idempotency,
    directory_accounts,
    organizations,
    platform_admins,
)
from verina.access.sql_identity import identity_principals
from verina.api.accounts import ACCOUNT_ERRORS, translate
from verina.api.matters import ApiError, MattersApi
from verina.audit.schema import audit_events
from verina.main import create_app

from .conftest import ISSUER, Keys, api_settings, bearer, mint

pytestmark = pytest.mark.story("US-47")

NOT_FOUND = {"error": "not_found"}
PLATFORM = "sub-platform"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
REDIRECT = "http://localhost:3000/auth/callback"
PLACEHOLDER_SECRET = "-".join(("synthetic", "placeholder"))


@pytest.fixture
def world(engine: Engine, directory: IdentityDirectory) -> IdentityDirectory:
    """Seeded people plus a tenant admin per tenant and one org-less platform admin."""
    directory.upsert_principal(
        "tenant-a", "a-admin", [Role.TENANT_ADMIN], display_name="Synthetic Admin A"
    )
    directory.bind(ISSUER, "sub-a-admin", "tenant-a", "a-admin")
    directory.upsert_principal(
        "tenant-b", "b-admin", [Role.TENANT_ADMIN], display_name="Synthetic Admin B"
    )
    directory.bind(ISSUER, "sub-b-admin", "tenant-b", "b-admin")
    with engine.begin() as conn:
        conn.execute(
            platform_admins.insert().values(
                issuer=ISSUER, subject=PLATFORM, admin_id="pa_synthetic", created_at=NOW
            )
        )
    return directory


@pytest.fixture
def fake() -> FakeAuthAdmin:
    return FakeAuthAdmin()


@pytest.fixture
def client(
    db_url: str, keys: Keys, world: IdentityDirectory, fake: FakeAuthAdmin
) -> Iterator[TestClient]:
    app = create_app(api_settings(db_url, keys, auth_invite_redirect_url=REDIRECT))
    with TestClient(app) as test_client:
        api_of(test_client).accounts._auth_admin = fake
        yield test_client


def api_of(client: TestClient) -> MattersApi:
    api = client.app.state.matters_api  # type: ignore[attr-defined]
    assert isinstance(api, MattersApi)
    return api


def auth(keys: Keys, subject: str) -> dict[str, str]:
    return bearer(mint(keys, subject))


def write(keys: Keys, subject: str, key: str | None = None) -> dict[str, str]:
    return {**auth(keys, subject), "Idempotency-Key": key or str(uuid4())}


def create_org(
    client: TestClient, keys: Keys, slug: str = "invented-firm", name: str = "Invented Firm LLP"
) -> dict[str, Any]:
    response = client.post(
        "/v1/admin/organizations", headers=write(keys, PLATFORM), json={"name": name, "slug": slug}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def invite(
    client: TestClient,
    keys: Keys,
    org_id: str,
    email: str = "invented.member@example.test",
    roles: list[str] | None = None,
    subject: str = PLATFORM,
    key: str | None = None,
) -> Any:
    return client.post(
        f"/v1/organizations/{org_id}/members",
        headers=write(keys, subject, key),
        json={
            "email": email,
            "display_name": "Invented Member",
            "roles": roles or ["lawyer"],
        },
    )


def events(engine: Engine, chain: str, event_type: str = "directory.changed") -> list[Any]:
    with engine.begin() as conn:
        rows = conn.execute(
            select(audit_events.c.payload)
            .where(audit_events.c.tenant_id == chain, audit_events.c.event_type == event_type)
            .order_by(audit_events.c.sequence)
        ).scalars()
        return [json.loads(r) for r in rows]


# ----------------------------------------------------------------------------- /v1/me


def test_me_for_a_linked_member(client: TestClient, keys: Keys) -> None:
    response = client.get("/v1/me", headers=auth(keys, "sub-a-lawyer"))
    assert response.status_code == 200
    assert response.json() == {
        "linked": True,
        "actor_id": "a-lawyer",
        "display_name": "Synthetic Lawyer A",
        "organization": {"id": "tenant-a", "name": "tenant-a", "slug": "tenant-a"},
        "roles": ["lawyer"],
        "platform_admin": False,
    }


def test_me_for_an_org_less_platform_admin(client: TestClient, keys: Keys) -> None:
    assert client.get("/v1/me", headers=auth(keys, PLATFORM)).json() == {
        "linked": True,
        "actor_id": None,
        "display_name": None,
        "organization": None,
        "roles": [],
        "platform_admin": True,
    }


def test_me_for_a_platform_admin_who_is_also_a_member(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    with engine.begin() as conn:
        conn.execute(
            platform_admins.insert().values(
                issuer=ISSUER, subject="sub-a-admin", admin_id="pa_member", created_at=NOW
            )
        )
    body = client.get("/v1/me", headers=auth(keys, "sub-a-admin")).json()
    assert body["platform_admin"] is True and body["organization"]["id"] == "tenant-a"
    assert body["roles"] == ["tenant_admin"]


def test_me_unlinked_cases_answer_linked_false(
    client: TestClient, keys: Keys, world: IdentityDirectory, engine: Engine
) -> None:
    assert client.get("/v1/me", headers=auth(keys, "sub-unknown")).json() == {"linked": False}
    world.set_active("tenant-a", "a-lawyer", False)
    assert client.get("/v1/me", headers=auth(keys, "sub-a-lawyer")).json() == {"linked": False}
    with engine.begin() as conn:
        conn.execute(
            organizations.update().where(organizations.c.id == "tenant-b").values(active=False)
        )
    assert client.get("/v1/me", headers=auth(keys, "sub-b-lawyer")).json() == {"linked": False}


def test_me_requires_a_valid_token(client: TestClient, keys: Keys) -> None:
    missing = client.get("/v1/me")
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == 'Bearer realm="verina"'
    forged = client.get("/v1/me", headers=bearer(mint(keys, key=keys.attacker)))
    assert forged.status_code == 401 and "invalid_token" in forged.headers["WWW-Authenticate"]


def test_unbound_token_is_401_everywhere_except_me(client: TestClient, keys: Keys) -> None:
    headers = write(keys, "sub-unknown")
    for method, path in (
        ("GET", "/v1/admin/organizations"),
        ("GET", "/v1/admin/organizations/tenant-a"),
        ("GET", "/v1/organizations/tenant-a/members"),
        ("POST", "/v1/admin/organizations"),
        ("POST", "/v1/organizations/tenant-a/members"),
        ("GET", "/v1/matters/whatever"),
    ):
        response = client.request(method, path, headers=headers, json={})
        assert response.status_code == 401, (method, path)
        assert response.json() == {"error": "unauthenticated"}


# ----------------------------------------------------------------------------- organizations


def test_platform_admin_creates_lists_gets_and_updates_organizations(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    org = create_org(client, keys)
    assert set(org) == {"id", "name", "slug", "active"}
    assert org["active"] is True and org["slug"] == "invented-firm"
    assert org["id"].startswith("org_")
    listed = client.get("/v1/admin/organizations", headers=auth(keys, PLATFORM)).json()
    by_id = {o["id"]: o for o in listed["organizations"]}
    assert by_id[org["id"]]["member_count"] == 0
    assert by_id["tenant-a"]["member_count"] == 7
    got = client.get(f"/v1/admin/organizations/{org['id']}", headers=auth(keys, PLATFORM))
    assert got.json() == {**org, "member_count": 0}
    patched = client.patch(
        f"/v1/admin/organizations/{org['id']}",
        headers=write(keys, PLATFORM),
        json={"name": "Invented Firm (Renamed)"},
    )
    assert patched.status_code == 200
    assert patched.json() == {**org, "name": "Invented Firm (Renamed)", "member_count": 0}
    chain = events(engine, org["id"])
    assert [e["action"] for e in chain] == ["organization_created", "organization_updated"]
    assert all(e["actor"] == "pa_synthetic" for e in chain)
    assert "Invented Firm" not in json.dumps(chain)


@pytest.mark.parametrize("subject", ["sub-a-admin", "sub-a-lawyer", "sub-a-partner"])
def test_non_platform_admins_get_uniform_404_on_admin_routes(
    client: TestClient, keys: Keys, subject: str
) -> None:
    assert client.get("/v1/admin/organizations", headers=auth(keys, subject)).json() == NOT_FOUND
    assert (
        client.get("/v1/admin/organizations/tenant-a", headers=auth(keys, subject)).json()
        == NOT_FOUND
    )
    created = client.post(
        "/v1/admin/organizations",
        headers=write(keys, subject),
        json={"name": "Invented", "slug": "invented-x"},
    )
    assert (created.status_code, created.json()) == (404, NOT_FOUND)
    patched = client.patch(
        "/v1/admin/organizations/tenant-a", headers=write(keys, subject), json={"active": False}
    )
    assert (patched.status_code, patched.json()) == (404, NOT_FOUND)


def test_missing_organization_is_404_for_the_platform_admin(client: TestClient, keys: Keys) -> None:
    for org_id in ("org_missing", "bad id!", "_verina_system"):
        response = client.get(f"/v1/admin/organizations/{org_id}", headers=auth(keys, PLATFORM))
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    patched = client.patch(
        "/v1/admin/organizations/org_missing", headers=write(keys, PLATFORM), json={"active": True}
    )
    assert patched.status_code == 404


def test_duplicate_slug_is_409(client: TestClient, keys: Keys) -> None:
    create_org(client, keys, slug="dupe-firm")
    response = client.post(
        "/v1/admin/organizations",
        headers=write(keys, PLATFORM),
        json={"name": "Other", "slug": "dupe-firm"},
    )
    assert (response.status_code, response.json()) == (409, {"error": "slug_taken"})
    legacy = client.post(
        "/v1/admin/organizations",
        headers=write(keys, PLATFORM),
        json={"name": "Other", "slug": "tenant-a"},
    )
    assert legacy.status_code == 409


def test_create_is_idempotent(client: TestClient, keys: Keys, engine: Engine) -> None:
    key = str(uuid4())
    body = {"name": "Invented Repeat", "slug": "invented-repeat"}
    first = client.post("/v1/admin/organizations", headers=write(keys, PLATFORM, key), json=body)
    again = client.post("/v1/admin/organizations", headers=write(keys, PLATFORM, key), json=body)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    other = client.post(
        "/v1/admin/organizations",
        headers=write(keys, PLATFORM, key),
        json={**body, "slug": "invented-other"},
    )
    assert (other.status_code, other.json()) == (409, {"error": "idempotency_key_reused"})
    with engine.begin() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(organizations)
            .where(organizations.c.slug.like("invented-%"))
        ).scalar_one()
    assert count == 1


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "slug": "a"},
        {"name": "x", "slug": "-ab"},
        {"name": "x", "slug": "ab-"},
        {"name": "x", "slug": "a--b"},
        {"name": "x", "slug": "Upper"},
        {"name": "x", "slug": "a" * 41},
        {"name": "", "slug": "valid-slug"},
        {"name": "x" * 121, "slug": "valid-slug"},
        {"name": "bidi ‮ name", "slug": "valid-slug"},
        {"name": "x", "slug": "valid-slug", "extra": True},
        {"name": 5, "slug": "valid-slug"},
        {"slug": "valid-slug"},
    ],
)
def test_organization_validation(client: TestClient, keys: Keys, body: dict[str, Any]) -> None:
    response = client.post("/v1/admin/organizations", headers=write(keys, PLATFORM), json=body)
    assert (response.status_code, response.json()) == (422, {"error": "validation_failed"})


def test_idempotency_key_is_required(client: TestClient, keys: Keys) -> None:
    response = client.post(
        "/v1/admin/organizations",
        headers=auth(keys, PLATFORM),
        json={"name": "x", "slug": "valid-slug"},
    )
    assert (response.status_code, response.json()) == (400, {"error": "bad_request"})
    bad = client.post(
        "/v1/admin/organizations",
        headers={**auth(keys, PLATFORM), "Idempotency-Key": "nope"},
        json={"name": "x", "slug": "valid-slug"},
    )
    assert bad.status_code == 400


def test_empty_patch_is_422(client: TestClient, keys: Keys) -> None:
    response = client.patch(
        "/v1/admin/organizations/tenant-a", headers=write(keys, PLATFORM), json={}
    )
    assert response.status_code == 422
    nulls = client.patch(
        "/v1/admin/organizations/tenant-a",
        headers=write(keys, PLATFORM),
        json={"name": None, "active": None},
    )
    assert nulls.status_code == 422


def test_organization_deactivation_revokes_all_members(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    assert (
        client.get(
            "/v1/organizations/tenant-a/members", headers=auth(keys, "sub-a-admin")
        ).status_code
        == 200
    )
    off = client.patch(
        "/v1/admin/organizations/tenant-a", headers=write(keys, PLATFORM), json={"active": False}
    )
    assert off.status_code == 200 and off.json()["active"] is False
    for subject in ("sub-a-admin", "sub-a-lawyer"):
        denied = client.get("/v1/organizations/tenant-a/members", headers=auth(keys, subject))
        assert denied.status_code == 401
        assert client.get("/v1/me", headers=auth(keys, subject)).json() == {"linked": False}
    assert client.get("/v1/matters/anything", headers=auth(keys, "sub-a-lawyer")).status_code == 401
    # The platform admin still manages the deactivated organization.
    members = client.get("/v1/organizations/tenant-a/members", headers=auth(keys, PLATFORM))
    assert members.status_code == 200
    on = client.patch(
        "/v1/admin/organizations/tenant-a", headers=write(keys, PLATFORM), json={"active": True}
    )
    assert on.json()["active"] is True
    assert client.get("/v1/me", headers=auth(keys, "sub-a-lawyer")).json()["linked"] is True
    (updated,) = [e for e in events(engine, "tenant-a") if e["action"] == "organization_updated"][
        :1
    ]
    assert updated["organization_active"] is False


# ----------------------------------------------------------------------------- members


def test_member_listing_authorization_matrix(client: TestClient, keys: Keys) -> None:
    own = client.get("/v1/organizations/tenant-a/members", headers=auth(keys, "sub-a-admin"))
    assert own.status_code == 200
    members = {m["actor_id"]: m for m in own.json()["members"]}
    assert members["a-lawyer"] == {
        "actor_id": "a-lawyer",
        "display_name": "Synthetic Lawyer A",
        "email": None,
        "roles": ["lawyer"],
        "active": True,
        "invite_status": "accepted",
    }
    assert "b-lawyer" not in members
    platform = client.get("/v1/organizations/tenant-b/members", headers=auth(keys, PLATFORM))
    assert {m["actor_id"] for m in platform.json()["members"]} == {"b-lawyer", "b-admin"}
    for subject, org in (
        ("sub-a-admin", "tenant-b"),
        ("sub-a-lawyer", "tenant-a"),
        ("sub-a-partner", "tenant-a"),
        ("sub-b-admin", "tenant-a"),
        ("sub-a-admin", "org_missing"),
        ("sub-a-admin", "bad id"),
    ):
        response = client.get(f"/v1/organizations/{org}/members", headers=auth(keys, subject))
        assert (response.status_code, response.json()) == (404, NOT_FOUND), (subject, org)
    missing = client.get("/v1/organizations/org_missing/members", headers=auth(keys, PLATFORM))
    assert missing.status_code == 404


def test_invite_binds_the_supabase_user_and_audits(
    client: TestClient, keys: Keys, fake: FakeAuthAdmin, engine: Engine
) -> None:
    org = create_org(client, keys)
    response = invite(
        client,
        keys,
        org["id"],
        email="Invented.Member@Example.TEST",
        roles=["tenant_admin", "lawyer"],
    )
    assert response.status_code == 201, response.text
    member = response.json()
    assert member["email"] == "invented.member@example.test"
    assert member["roles"] == ["lawyer", "tenant_admin"]
    assert (member["active"], member["invite_status"]) == (True, "pending")
    assert member["actor_id"].startswith("act_")
    assert fake.invites == [("invented.member@example.test", REDIRECT)]
    chain = events(engine, org["id"])
    assert [e["action"] for e in chain] == ["organization_created", "member_invited"]
    assert "invented.member" not in json.dumps(chain) and "Invented Member" not in json.dumps(chain)
    # The invited person signs in with the Supabase subject the port returned.
    subject = fake.users["invented.member@example.test"][0]
    me = client.get("/v1/me", headers=auth(keys, subject)).json()
    assert me["linked"] is True and me["organization"]["id"] == org["id"]
    assert me["roles"] == ["lawyer", "tenant_admin"]
    listed = client.get(f"/v1/organizations/{org['id']}/members", headers=auth(keys, subject))
    assert listed.json()["members"][0]["invite_status"] == "accepted"
    assert events(engine, org["id"])[-1]["action"] == "invite_accepted"
    # A second /me does not write again.
    client.get("/v1/me", headers=auth(keys, subject))
    assert len(events(engine, org["id"])) == 3


def test_tenant_admin_invites_into_own_org_only(client: TestClient, keys: Keys) -> None:
    own = invite(client, keys, "tenant-a", subject="sub-a-admin", email="a.new@example.test")
    assert own.status_code == 201
    other = invite(client, keys, "tenant-b", subject="sub-a-admin", email="b.new@example.test")
    assert (other.status_code, other.json()) == (404, NOT_FOUND)
    lawyer = invite(client, keys, "tenant-a", subject="sub-a-lawyer", email="c.new@example.test")
    assert (lawyer.status_code, lawyer.json()) == (404, NOT_FOUND)


def test_one_account_one_organization(client: TestClient, keys: Keys, fake: FakeAuthAdmin) -> None:
    assert invite(client, keys, "tenant-a", email="shared@example.test").status_code == 201
    again = invite(client, keys, "tenant-b", email="SHARED@example.test")
    assert (again.status_code, again.json()) == (409, {"error": "account_exists"})
    assert len(fake.invites) == 1  # refused before contacting the provider


def test_existing_supabase_user_already_bound_is_409(
    client: TestClient, keys: Keys, fake: FakeAuthAdmin, world: IdentityDirectory
) -> None:
    # The provider already knows this address and its subject is bound (CLI-provisioned).
    fake.users["legacy@example.test"] = ("sub-a-partner", True)
    response = invite(client, keys, "tenant-b", email="legacy@example.test")
    assert (response.status_code, response.json()) == (409, {"error": "account_exists"})


def test_invite_is_idempotent(client: TestClient, keys: Keys, fake: FakeAuthAdmin) -> None:
    key = str(uuid4())
    first = invite(client, keys, "tenant-a", key=key)
    again = invite(client, keys, "tenant-a", key=key)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    assert len(fake.invites) == 1
    different = invite(client, keys, "tenant-a", email="other@example.test", key=key)
    assert (different.status_code, different.json()) == (409, {"error": "idempotency_key_reused"})
    by_other_admin = invite(client, keys, "tenant-a", subject="sub-a-admin", key=key)
    assert by_other_admin.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"email": "x@example.test", "display_name": "X", "roles": []},
        {"email": "x@example.test", "display_name": "X", "roles": ["owner"]},
        {"email": "x@example.test", "display_name": "X", "roles": ["lawyer", "lawyer"]},
        {"email": "x@example.test", "display_name": "X", "roles": ["platform_admin"]},
        {"email": "not-an-email", "display_name": "X", "roles": ["lawyer"]},
        {"email": "x@example.test", "display_name": "", "roles": ["lawyer"]},
        {"email": "x@example.test", "display_name": "​", "roles": ["lawyer"]},
        {"email": "x@example.test", "roles": ["lawyer"]},
        {"email": "x@example.test", "display_name": "X", "roles": "lawyer"},
    ],
)
def test_invite_validation(client: TestClient, keys: Keys, body: dict[str, Any]) -> None:
    response = client.post(
        "/v1/organizations/tenant-a/members", headers=write(keys, PLATFORM), json=body
    )
    assert (response.status_code, response.json()) == (422, {"error": "validation_failed"})
    assert "x@example.test" not in response.text


def test_invite_into_inactive_org_is_409(client: TestClient, keys: Keys) -> None:
    client.patch(
        "/v1/admin/organizations/tenant-b", headers=write(keys, PLATFORM), json={"active": False}
    )
    response = invite(client, keys, "tenant-b")
    assert (response.status_code, response.json()) == (409, {"error": "organization_inactive"})


@pytest.mark.parametrize(
    ("kind", "status", "error"),
    [
        ("unavailable", 503, "unavailable"),
        ("rate_limited", 429, "rate_limited"),
        ("misconfigured", 503, "unavailable"),
    ],
)
def test_provider_failures(
    client: TestClient,
    keys: Keys,
    fake: FakeAuthAdmin,
    engine: Engine,
    kind: Any,
    status: int,
    error: str,
) -> None:
    fake.fail_with = kind
    response = invite(client, keys, "tenant-a")
    assert (response.status_code, response.json()) == (status, {"error": error})
    with engine.begin() as conn:
        assert conn.execute(select(directory_accounts)).first() is None


def test_invite_without_a_configured_provider_is_503(client: TestClient, keys: Keys) -> None:
    api_of(client).accounts._auth_admin = None
    assert invite(client, keys, "tenant-a").status_code == 503
    assert (
        client.post(
            "/v1/organizations/tenant-a/members/a-lawyer/resend-invite",
            headers=write(keys, PLATFORM),
        ).status_code
        == 404  # a CLI principal has no invitation
    )


def test_update_member_roles_state_and_name(client: TestClient, keys: Keys, engine: Engine) -> None:
    response = client.patch(
        "/v1/organizations/tenant-a/members/a-lawyer",
        headers=write(keys, "sub-a-admin"),
        json={"roles": ["lawyer", "partner"], "display_name": "Synthetic Lawyer A (Partner)"},
    )
    assert response.status_code == 200
    assert response.json()["roles"] == ["lawyer", "partner"]
    assert response.json()["display_name"] == "Synthetic Lawyer A (Partner)"
    off = client.patch(
        "/v1/organizations/tenant-a/members/a-lawyer",
        headers=write(keys, "sub-a-admin"),
        json={"active": False},
    )
    assert off.json()["active"] is False
    assert client.get("/v1/me", headers=auth(keys, "sub-a-lawyer")).json() == {"linked": False}
    updates = [e for e in events(engine, "tenant-a") if e["action"] == "member_updated"]
    assert [u["active"] for u in updates] == [True, False]
    assert "Partner)" not in json.dumps(updates)


def test_update_member_authorization_matrix(client: TestClient, keys: Keys) -> None:
    for subject, org, actor in (
        ("sub-a-admin", "tenant-b", "b-lawyer"),
        ("sub-a-lawyer", "tenant-a", "a-partner"),
        ("sub-a-admin", "tenant-a", "b-lawyer"),
        ("sub-a-admin", "tenant-a", "missing-actor"),
        ("sub-a-admin", "tenant-a", "bad actor!"),
    ):
        response = client.patch(
            f"/v1/organizations/{org}/members/{actor}",
            headers=write(keys, subject),
            json={"active": False},
        )
        assert (response.status_code, response.json()) == (404, NOT_FOUND), (subject, org, actor)
    platform = client.patch(
        "/v1/organizations/tenant-b/members/b-lawyer",
        headers=write(keys, PLATFORM),
        json={"roles": ["partner"]},
    )
    assert platform.status_code == 200


def test_last_admin_protection(client: TestClient, keys: Keys) -> None:
    for body in ({"roles": ["lawyer"]}, {"active": False}):
        response = client.patch(
            "/v1/organizations/tenant-a/members/a-admin",
            headers=write(keys, "sub-a-admin"),
            json=body,
        )
        assert (response.status_code, response.json()) == (409, {"error": "last_admin"})
    # With a second active admin the first may step down.
    promote = client.patch(
        "/v1/organizations/tenant-a/members/a-partner",
        headers=write(keys, "sub-a-admin"),
        json={"roles": ["partner", "tenant_admin"]},
    )
    assert promote.status_code == 200
    step_down = client.patch(
        "/v1/organizations/tenant-a/members/a-admin",
        headers=write(keys, "sub-a-admin"),
        json={"roles": ["lawyer"]},
    )
    assert step_down.status_code == 200
    # The former admin has lost authority on the next request.
    denied = client.get("/v1/organizations/tenant-a/members", headers=auth(keys, "sub-a-admin"))
    assert denied.status_code == 404
    last = client.patch(
        "/v1/organizations/tenant-a/members/a-partner",
        headers=write(keys, PLATFORM),
        json={"active": False},
    )
    assert last.status_code == 409


def test_update_member_validation(client: TestClient, keys: Keys) -> None:
    bodies: list[dict[str, Any]] = [
        {},
        {"roles": []},
        {"active": "no"},
        {"roles": ["lawyer"], "email": "x"},
    ]
    for body in bodies:
        response = client.patch(
            "/v1/organizations/tenant-a/members/a-lawyer",
            headers=write(keys, "sub-a-admin"),
            json=body,
        )
        assert response.status_code == 422, body


def test_update_member_is_idempotent(client: TestClient, keys: Keys, engine: Engine) -> None:
    key = str(uuid4())
    body = {"roles": ["partner"]}
    url = "/v1/organizations/tenant-a/members/a-lawyer"
    first = client.patch(url, headers=write(keys, "sub-a-admin", key), json=body)
    again = client.patch(url, headers=write(keys, "sub-a-admin", key), json=body)
    assert first.json() == again.json()
    with engine.begin() as conn:
        assert conn.execute(select(func.count()).select_from(admin_idempotency)).scalar_one() == 1
        revision = conn.execute(
            select(identity_principals.c.revision).where(
                identity_principals.c.actor_id == "a-lawyer"
            )
        ).scalar_one()
    assert revision == 2


def test_resend_invite(client: TestClient, keys: Keys, fake: FakeAuthAdmin, engine: Engine) -> None:
    member = invite(client, keys, "tenant-a", subject="sub-a-admin").json()
    url = f"/v1/organizations/tenant-a/members/{member['actor_id']}/resend-invite"
    key = str(uuid4())
    response = client.post(url, headers=write(keys, "sub-a-admin", key))
    assert (response.status_code, response.json()) == (202, {})
    assert client.post(url, headers=write(keys, "sub-a-admin", key)).status_code == 202
    assert fake.resends == ["invented.member@example.test"]
    assert client.post(url, headers=write(keys, "sub-b-admin")).status_code == 404
    assert client.post(url, headers=write(keys, "sub-a-lawyer")).status_code == 404
    # The person confirmed their address at the provider: resend now reports accepted.
    fake.confirm("invented.member@example.test")
    accepted = client.post(url, headers=write(keys, "sub-a-admin"))
    assert (accepted.status_code, accepted.json()) == (409, {"error": "invite_already_accepted"})
    listed = client.get("/v1/organizations/tenant-a/members", headers=auth(keys, "sub-a-admin"))
    status = {m["actor_id"]: m["invite_status"] for m in listed.json()["members"]}
    assert status[member["actor_id"]] == "accepted"
    assert client.post(url, headers=write(keys, "sub-a-admin")).status_code == 409
    actions = [e["action"] for e in events(engine, "tenant-a")]
    assert actions.count("invite_resent") == 1 and actions.count("invite_accepted") == 1


def test_resend_accepts_an_empty_json_body(
    client: TestClient, keys: Keys, fake: FakeAuthAdmin
) -> None:
    member = invite(client, keys, "tenant-a").json()
    response = client.post(
        f"/v1/organizations/tenant-a/members/{member['actor_id']}/resend-invite",
        headers=write(keys, PLATFORM),
        json={},
    )
    assert (response.status_code, response.json()) == (202, {})
    assert fake.resends == ["invented.member@example.test"]


def test_patch_returns_the_full_member_and_organization(client: TestClient, keys: Keys) -> None:
    org = client.patch(
        "/v1/admin/organizations/tenant-b", headers=write(keys, PLATFORM), json={"name": "B"}
    ).json()
    assert org == {
        "id": "tenant-b",
        "name": "B",
        "slug": "tenant-b",
        "active": True,
        "member_count": 2,
    }
    member = client.patch(
        "/v1/organizations/tenant-b/members/b-lawyer",
        headers=write(keys, PLATFORM),
        json={"active": True},
    ).json()
    assert set(member) == {
        "actor_id",
        "display_name",
        "email",
        "roles",
        "active",
        "invite_status",
    }


def test_resend_for_inactive_member_or_unknown(client: TestClient, keys: Keys) -> None:
    member = invite(client, keys, "tenant-a").json()
    client.patch(
        f"/v1/organizations/tenant-a/members/{member['actor_id']}",
        headers=write(keys, PLATFORM),
        json={"active": False},
    )
    url = f"/v1/organizations/tenant-a/members/{member['actor_id']}/resend-invite"
    response = client.post(url, headers=write(keys, PLATFORM))
    assert (response.status_code, response.json()) == (409, {"error": "member_inactive"})
    unknown = client.post(
        "/v1/organizations/tenant-a/members/act_missing/resend-invite",
        headers=write(keys, PLATFORM),
    )
    assert unknown.status_code == 404
    client.patch(
        "/v1/admin/organizations/tenant-a", headers=write(keys, PLATFORM), json={"active": False}
    )
    inactive_org = client.post(url, headers=write(keys, PLATFORM))
    assert inactive_org.json() == {"error": "organization_inactive"}


# ----------------------------------------------------------------------------- atomicity


def test_audit_failure_rolls_back_organization_and_member_writes(
    client: TestClient, keys: Keys, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = api_of(client).audit

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit outage")

    org = create_org(client, keys, slug="before-outage")
    monkeypatch.setattr(store, "append_on_connection", boom)
    with pytest.raises(RuntimeError):
        create_org(client, keys, slug="during-outage")
    with pytest.raises(RuntimeError):
        invite(client, keys, org["id"])
    with engine.begin() as conn:
        slugs = set(conn.execute(select(organizations.c.slug)).scalars())
        assert "during-outage" not in slugs
        assert conn.execute(select(directory_accounts)).first() is None
        assert (
            conn.execute(
                select(identity_principals).where(identity_principals.c.tenant_id == org["id"])
            ).first()
            is None
        )
        assert conn.execute(select(func.count()).select_from(admin_idempotency)).scalar_one() == 1


def test_audit_chain_verifies_after_account_activity(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    org = create_org(client, keys)
    member = invite(client, keys, org["id"]).json()
    client.patch(
        f"/v1/organizations/{org['id']}/members/{member['actor_id']}",
        headers=write(keys, PLATFORM),
        json={"roles": ["tenant_admin"]},
    )
    store = api_of(client).audit
    assert store.verify_chain(org["id"]).ok
    assert store.verify_chain("tenant-a").ok


# ----------------------------------------------------------------------------- service units


def test_step_up_required_for_platform_admin_when_configured(engine: Engine, world: Any) -> None:
    from verina.audit import SqlAuditStore

    service = AccountsService(
        engine, SqlAuditStore(engine), FakeAuthAdmin(), issuer=ISSUER, admin_require_aal2=True
    )
    weak = Caller(ISSUER, PLATFORM, "aal1", None, "pa_synthetic")
    strong = Caller(ISSUER, PLATFORM, "aal2", None, "pa_synthetic")
    with pytest.raises(AccountsError) as failure:
        service.list_organizations(weak)
    assert failure.value.code == "insufficient_user_authentication"
    with pytest.raises(AccountsError) as member_route:
        service.list_members(weak, "tenant-a")
    assert member_route.value.code == "insufficient_user_authentication"
    assert service.list_organizations(strong)
    nobody = Caller(ISSUER, "sub-x", "aal2", None, None)
    with pytest.raises(AccountsError) as hidden:
        service.list_organizations(nobody)
    assert hidden.value.code == "not_found"


def test_revoked_platform_admin_cannot_write(engine: Engine, world: Any) -> None:
    from verina.audit import SqlAuditStore

    service = AccountsService(engine, SqlAuditStore(engine), FakeAuthAdmin(), issuer=ISSUER)
    stale = Caller(ISSUER, "sub-revoked", None, None, "pa_revoked")  # grant no longer in table
    with pytest.raises(AccountsError) as failure:
        service.create_organization(stale, uuid4(), "Invented", "invented-stale")
    assert failure.value.code == "not_found"


def test_accounts_service_requires_shared_engine(engine: Engine) -> None:
    from verina.audit import SqlAuditStore
    from verina.db import make_engine

    other = make_engine("sqlite://")
    try:
        with pytest.raises(ValueError):
            AccountsService(engine, SqlAuditStore(other), None, issuer=ISSUER)
    finally:
        other.dispose()


def test_error_mapping_is_complete() -> None:
    for code, (status, error) in ACCOUNT_ERRORS.items():
        mapped = translate(AccountsError(code), presented=True)
        assert (mapped.status, mapped.error) == (status, error)
    step_up = translate(AccountsError("insufficient_user_authentication"), presented=True)
    assert "insufficient_user_authentication" in step_up.headers["WWW-Authenticate"]
    assert translate(AccountsError("unknown_code"), presented=True).status == 500
    assert translate(ValueError("x"), presented=True).status == 422
    existing = ApiError(418, "teapot")
    assert translate(existing, presented=False) is existing
    with pytest.raises(KeyError):
        translate(KeyError("unmapped"), presented=True)


def test_supabase_configuration_is_validated_at_startup(db_url: str, keys: Keys) -> None:
    from verina.api.matters import MattersApiConfigError

    with pytest.raises(MattersApiConfigError):
        create_app(api_settings(db_url, keys, supabase_url="https://idp.synthetic.test"))
    with pytest.raises(MattersApiConfigError):
        create_app(
            api_settings(
                db_url,
                keys,
                supabase_url="https://other.synthetic.test",
                supabase_secret_key=PLACEHOLDER_SECRET,
            )
        )
    app = create_app(
        api_settings(
            db_url,
            keys,
            supabase_url="https://idp.synthetic.test",
            supabase_secret_key=PLACEHOLDER_SECRET,
        )
    )
    with TestClient(app) as test_client:
        assert api_of(test_client).accounts._auth_admin is not None
