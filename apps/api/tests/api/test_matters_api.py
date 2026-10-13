"""Authenticated /v1 matter routes over HTTP. Synthetic principals, titles and reasons only."""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select

from verina.access import (
    ActorId,
    IdentityDirectory,
    MatterAccess,
    MatterContent,
    MatterId,
    MatterRecord,
    MatterService,
    ReasonCode,
    SqlMatterRepository,
    TenantId,
)
from verina.access.mutations import receipts
from verina.api.matters import (
    _COLLECTION_ERRORS,
    _MATTER_ERRORS,
    MAX_BODY_BYTES,
    MattersApi,
    MattersApiConfigError,
)
from verina.audit.schema import audit_events
from verina.config import Settings
from verina.main import create_app
from verina.security import SECURITY_HEADERS

from .conftest import ISSUER, Keys, api_settings, bearer, mint

pytestmark = [pytest.mark.story("EN-7"), pytest.mark.story("US-3")]

NOT_FOUND = {"error": "not_found"}
CANARY_TITLE = "Invented Kestrel supply review"
CANARY_REASON = "Invented waiver rationale for Kestrel"


def auth(keys: Keys, subject: str = "sub-a-lawyer", **extra: str) -> dict[str, str]:
    return {**bearer(mint(keys, subject)), **extra}


def write(keys: Keys, subject: str = "sub-a-lawyer", **extra: str) -> dict[str, str]:
    return auth(keys, subject, **{"Idempotency-Key": str(uuid4()), **extra})


def create(client: TestClient, keys: Keys, subject: str = "sub-a-lawyer", **headers: str) -> str:
    response = client.post(
        "/v1/matters", headers=write(keys, subject, **headers), json={"title": CANARY_TITLE}
    )
    assert response.status_code == 201, response.text
    matter_id = response.json()["matter_id"]
    assert isinstance(matter_id, str)
    return matter_id


def counts(engine: Engine) -> tuple[int, int]:
    with engine.begin() as conn:
        receipts_count = conn.execute(select(func.count()).select_from(receipts)).scalar_one()
        completed = conn.execute(
            select(func.count())
            .select_from(audit_events)
            .where(audit_events.c.event_type == "matter.mutation_completed")
        ).scalar_one()
    return int(receipts_count), int(completed)


def api_of(client: TestClient) -> MattersApi:
    api = client.app.state.matters_api  # type: ignore[attr-defined]
    assert isinstance(api, MattersApi)
    return api


def assert_unauthenticated(response: Any, *, presented: bool = True) -> None:
    assert response.status_code == 401
    assert response.json() == {"error": "unauthenticated"}
    challenge = response.headers["WWW-Authenticate"]
    assert challenge.startswith('Bearer realm="verina"')
    assert ('error="invalid_token"' in challenge) is presented


# ----------------------------------------------------------------------- configuration


def test_routes_absent_when_disabled() -> None:
    client = TestClient(create_app(Settings(_env_file=None, env="test")))
    assert client.post("/v1/matters", json={"title": "x"}).status_code == 404
    assert client.get("/v1/matters/m-1").status_code == 404
    assert "/v1/matters" not in json.dumps(client.get("/openapi.json").json())
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth_issuer": None},
        {"auth_audience": None},
        {"auth_jwks": None},
        {"auth_issuer": ""},
        {"auth_audience": ""},
        {"auth_jwks": '{"keys": []}'},
        {"auth_jwks": '{"keys": [ not json'},
        {"auth_jwks": "C:/definitely/missing/jwks.json"},
        {"auth_extra_audiences": [""]},
    ],
)
def test_enabled_without_complete_config_fails_startup(
    db_url: str, keys: Keys, overrides: dict[str, Any]
) -> None:
    with pytest.raises(MattersApiConfigError):
        create_app(api_settings(db_url, keys, **overrides))


@pytest.mark.parametrize("env", ["production", "staging"])
def test_enabled_outside_local_or_test_fails_startup(db_url: str, keys: Keys, env: str) -> None:
    with pytest.raises(MattersApiConfigError):
        create_app(api_settings(db_url, keys, env=env))


def _without_env(db_url: str, keys: Keys) -> dict[str, Any]:
    values = api_settings(db_url, keys).model_dump()
    values.pop("env")
    return values


def test_enabled_with_defaulted_env_fails_startup(
    db_url: str, keys: Keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VERINA_ENV", raising=False)
    settings = Settings(_env_file=None, **_without_env(db_url, keys))
    assert settings.env == "local" and "env" not in settings.model_fields_set
    with pytest.raises(MattersApiConfigError):
        create_app(settings)


def test_enabled_with_explicit_env_variable_starts(
    db_url: str, keys: Keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERINA_ENV", "test")
    settings = Settings(_env_file=None, **_without_env(db_url, keys))
    assert "env" in settings.model_fields_set
    app = create_app(settings)
    assert any(getattr(route, "path", "") == "/v1/matters" for route in app.routes)


def test_every_reason_code_has_a_central_mapping() -> None:
    assert set(_MATTER_ERRORS) == set(ReasonCode)
    assert set(_COLLECTION_ERRORS) == set(ReasonCode)
    # Only collection routes may answer 403; matter routes never distinguish membership.
    assert {status for status, _ in _MATTER_ERRORS.values()} <= {401, 404, 409, 422, 500}
    leaky = {
        code
        for code, (status, _) in _MATTER_ERRORS.items()
        if status == 404 and code is not ReasonCode.MATTER_NOT_ACCESSIBLE
    }
    assert all(_MATTER_ERRORS[code] == (404, "not_found") for code in leaky)


# ----------------------------------------------------------------------- authentication


def test_missing_and_invalid_credentials(client: TestClient, keys: Keys) -> None:
    assert_unauthenticated(client.get("/v1/matters/m-1"), presented=False)
    assert_unauthenticated(client.get("/v1/matters/m-1", headers={"Authorization": "Bearer x"}))
    assert_unauthenticated(
        client.get("/v1/matters/m-1", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    )
    expired = mint(keys, exp=1_000_000_000, iat=999_999_000)
    assert_unauthenticated(client.get("/v1/matters/m-1", headers=bearer(expired)))
    assert_unauthenticated(client.get("/v1/matters/m-1", headers=auth(keys, "sub-unknown")))
    wrong_key = mint(keys, key=keys.attacker)
    assert_unauthenticated(
        client.post("/v1/matters", headers=bearer(wrong_key), json={"title": "x"})
    )


def test_token_role_and_tenant_claims_are_ignored(client: TestClient, keys: Keys) -> None:
    token = mint(keys, "sub-a-requester", roles=["partner"], tenant_id="tenant-b")
    response = client.post(
        "/v1/matters",
        headers={
            **bearer(token),
            "Idempotency-Key": str(uuid4()),
            "X-Roles": "partner",
            "X-Tenant-Id": "tenant-b",
        },
        json={"title": "x"},
    )
    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_collection_denials_are_403(client: TestClient, keys: Keys) -> None:
    for subject in ("sub-a-requester", "sub-a-knowledge", "sub-a-noprofile"):
        response = client.post("/v1/matters", headers=write(keys, subject), json={"title": "x"})
        assert response.status_code == 403
        assert response.json() == {"error": "forbidden"}


# ----------------------------------------------------------------------- create and read


def test_create_then_read(client: TestClient, keys: Keys) -> None:
    response = client.post("/v1/matters", headers=write(keys), json={"title": CANARY_TITLE})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"matter_id", "revision"} and body["revision"] == 1
    assert response.headers["ETag"] == '"1"'
    assert response.headers["Location"] == f"/v1/matters/{body['matter_id']}"
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert "access-control-allow-origin" not in response.headers
    read = client.get(f"/v1/matters/{body['matter_id']}", headers=auth(keys))
    assert read.status_code == 200
    assert read.json() == {
        "matter_id": body["matter_id"],
        "revision": 1,
        "title": CANARY_TITLE,
        "conflict_status": "pending",
        "status": "awaiting_clearance",
    }
    assert read.headers["ETag"] == '"1"'


def test_requester_gets_status_projection_only(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    SqlMatterRepository(engine).add(
        TenantId("tenant-a"),
        MatterRecord(
            MatterAccess(
                TenantId("tenant-a"),
                MatterId("m-seeded"),
                members=frozenset(ActorId(a) for a in ("a-lawyer", "a-requester", "a-knowledge")),
            ),
            MatterContent(CANARY_TITLE),
        ),
    )
    status = client.get("/v1/matters/m-seeded", headers=auth(keys, "sub-a-requester"))
    assert status.status_code == 200
    assert status.json() == {"matter_id": "m-seeded", "status": "awaiting_clearance"}
    assert "ETag" not in status.headers
    knowledge = client.get("/v1/matters/m-seeded", headers=auth(keys, "sub-a-knowledge"))
    assert knowledge.json()["title"] == CANARY_TITLE
    # A member without a mutation role sees the same 404 as a stranger on mutation routes.
    patch = client.patch(
        "/v1/matters/m-seeded",
        headers=write(keys, "sub-a-requester", **{"If-Match": '"1"'}),
        json={"title": "x"},
    )
    assert patch.status_code == 404 and patch.json() == NOT_FOUND


def test_member_without_trusted_profile_gets_the_same_404(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    SqlMatterRepository(engine).add(
        TenantId("tenant-a"),
        MatterRecord(
            MatterAccess(
                TenantId("tenant-a"),
                MatterId("m-noprofile"),
                members=frozenset({ActorId("a-noprofile")}),
            ),
            MatterContent(CANARY_TITLE),
        ),
    )
    response = client.post(
        "/v1/matters/m-noprofile/conflict-checks",
        headers=write(keys, "sub-a-noprofile", **{"If-Match": '"1"'}),
        json={"result": "CLEAR"},
    )
    assert response.status_code == 404 and response.json() == NOT_FOUND
    # The same member can still read: the 404 is a uniform matter-route denial, not deletion.
    read = client.get("/v1/matters/m-noprofile", headers=auth(keys, "sub-a-noprofile"))
    assert read.status_code == 200


def test_non_member_other_tenant_and_missing_are_identical(client: TestClient, keys: Keys) -> None:
    mine = create(client, keys)
    theirs = create(client, keys, "sub-b-lawyer")

    def probe(
        subject: str, matter: str, if_match: str = '"1"'
    ) -> list[tuple[int, Any, str | None]]:
        results = []
        results.append(client.get(f"/v1/matters/{matter}", headers=auth(keys, subject)))
        results.append(
            client.patch(
                f"/v1/matters/{matter}",
                headers=write(keys, subject, **{"If-Match": if_match}),
                json={"title": "x"},
            )
        )
        results.append(
            client.post(
                f"/v1/matters/{matter}/conflict-checks",
                headers=write(keys, subject, **{"If-Match": if_match}),
                json={"result": "CLEAR"},
            )
        )
        results.append(
            client.post(
                f"/v1/matters/{matter}/conflict-waivers",
                headers=write(keys, subject, **{"If-Match": if_match}),
                json={"reason": "x"},
            )
        )
        return [(r.status_code, r.json(), r.headers.get("ETag")) for r in results]

    expected = [(404, NOT_FOUND, None)] * 4
    for if_match in ('"1"', '"99"'):  # a stale precondition must not turn 404 into 409
        assert probe("sub-a-outsider", mine, if_match) == expected  # same tenant, not member
        assert probe("sub-a-lawyer", theirs, if_match) == expected  # other tenant's real id
        assert probe("sub-b-lawyer", mine, if_match) == expected
        assert probe("sub-a-lawyer", str(uuid4()), if_match) == expected  # nonexistent
        assert probe("sub-a-lawyer", "bad id with spaces", if_match) == expected  # malformed
    # The real owners still see their own matters.
    assert (
        client.get(f"/v1/matters/{theirs}", headers=auth(keys, "sub-b-lawyer")).status_code == 200
    )


# ----------------------------------------------------------------------- idempotency


def test_idempotent_create_retry_returns_same_result_once(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    key = str(uuid4())
    headers = {**auth(keys), "Idempotency-Key": key}
    first = client.post("/v1/matters", headers=headers, json={"title": CANARY_TITLE})
    again = client.post(
        "/v1/matters",
        headers={**auth(keys), "Idempotency-Key": key.upper()},
        json={"title": CANARY_TITLE},
    )
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    assert first.headers["ETag"] == again.headers["ETag"]
    assert counts(engine) == (1, 1)
    changed = client.post("/v1/matters", headers=headers, json={"title": "Different title"})
    assert changed.status_code == 409
    assert changed.json() == {"error": "idempotency_key_reused"}
    other_actor = client.post(
        "/v1/matters",
        headers={**auth(keys, "sub-a-partner"), "Idempotency-Key": key},
        json={"title": CANARY_TITLE},
    )
    assert other_actor.status_code == 409
    assert counts(engine) == (1, 1)


def test_patch_preconditions_and_idempotent_retry(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    matter = create(client, keys)
    url = f"/v1/matters/{matter}"
    missing = client.patch(url, headers=write(keys), json={"title": "New"})
    assert missing.status_code == 428 and missing.json() == {"error": "precondition_required"}
    for bad in ('W/"1"', "*", "abc", "0", '"1', '"1", "2"', "1.0", "-1", "9" * 19):
        response = client.patch(url, headers=write(keys, **{"If-Match": bad}), json={"title": "N"})
        assert response.status_code == 400, bad
        assert response.json() == {"error": "bad_request"}
    stale = client.patch(url, headers=write(keys, **{"If-Match": '"7"'}), json={"title": "N"})
    assert stale.status_code == 409 and stale.json() == {"error": "revision_mismatch"}

    key = str(uuid4())
    headers = {**auth(keys), "Idempotency-Key": key, "If-Match": '"1"'}
    first = client.patch(url, headers=headers, json={"title": "Invented renamed review"})
    assert first.status_code == 200
    assert first.json() == {"matter_id": matter, "revision": 2}
    assert first.headers["ETag"] == '"2"'
    later = client.patch(
        url, headers=write(keys, **{"If-Match": "2"}), json={"title": "Invented later title"}
    )
    assert later.json()["revision"] == 3
    retry = client.patch(url, headers=headers, json={"title": "Invented renamed review"})
    assert retry.status_code == 200 and retry.json() == first.json()
    assert client.get(url, headers=auth(keys)).json()["title"] == "Invented later title"
    changed = client.patch(url, headers=headers, json={"title": "Something else"})
    assert changed.status_code == 409 and changed.json() == {"error": "idempotency_key_reused"}
    different_precondition = client.patch(
        url, headers={**headers, "If-Match": '"3"'}, json={"title": "Invented renamed review"}
    )
    assert different_precondition.status_code == 409
    # create + two successful updates; replays and rejects add nothing.
    assert counts(engine) == (3, 3)


@pytest.mark.parametrize(
    "key_headers",
    [
        [],
        [("Idempotency-Key", "not-a-uuid")],
        [("Idempotency-Key", "{" + "0" * 8 + "-0000-0000-0000-" + "0" * 12 + "}")],
        [("Idempotency-Key", str(uuid4())), ("Idempotency-Key", str(uuid4()))],
    ],
)
def test_idempotency_key_required_and_well_formed(
    client: TestClient, keys: Keys, key_headers: list[tuple[str, str]]
) -> None:
    headers = [*auth(keys).items(), *key_headers, ("Content-Type", "application/json")]
    response = client.post("/v1/matters", headers=headers, content=b'{"title": "x"}')
    assert response.status_code == 400
    assert response.json() == {"error": "bad_request"}


# ----------------------------------------------------------------------- bodies


@pytest.mark.parametrize(
    ("content", "content_type", "status"),
    [
        (b'{"title": "Invented"}', "text/plain", 415),
        (b'{"title": "Invented"}', "application/json; charset=latin-1", 415),
        (b"title=Invented", "application/x-www-form-urlencoded", 415),
        (b'{"title": "Invented", "tenant_id": "tenant-b"}', "application/json", 422),
        (b'{"title": ""}', "application/json", 422),
        (b'{"title": "   "}', "application/json", 422),
        (b'{"title": "bad\\u0000title"}', "application/json", 422),
        (b'{"title": 7}', "application/json", 422),
        (b"{not json", "application/json", 422),
        (b"[]", "application/json", 422),
        (b"", "application/json", 422),
        (json.dumps({"title": "x" * 201}).encode(), "application/json", 422),
        (json.dumps({"title": "x" * (MAX_BODY_BYTES + 10)}).encode(), "application/json", 413),
    ],
)
def test_create_body_validation_is_generic(
    client: TestClient, keys: Keys, content: bytes, content_type: str, status: int
) -> None:
    headers = {**write(keys), "Content-Type": content_type}
    response = client.post("/v1/matters", headers=headers, content=content)
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert "Invented" not in response.text and "tenant-b" not in response.text


def test_utf8_charset_is_accepted(client: TestClient, keys: Keys) -> None:
    headers = {**write(keys), "Content-Type": "application/json; charset=utf-8"}
    response = client.post(
        "/v1/matters", headers=headers, content='{"title": "Invented Ünïcode review"}'.encode()
    )
    assert response.status_code == 201


def test_streamed_body_over_limit_is_rejected(client: TestClient, keys: Keys) -> None:
    def chunks() -> Any:
        for _ in range(5):
            yield b" " * (MAX_BODY_BYTES // 2)

    headers = {**write(keys), "Content-Type": "application/json"}
    response = client.post("/v1/matters", headers=headers, content=chunks())
    assert response.status_code == 413


# ----------------------------------------------------------------------- conflict workflow


def test_conflict_check_and_waiver_flow(client: TestClient, keys: Keys) -> None:
    matter = create(client, keys)
    base = f"/v1/matters/{matter}"
    hit = client.post(
        f"{base}/conflict-checks",
        headers=write(keys, **{"If-Match": '"1"'}),
        json={"result": "CONFLICT"},
    )
    assert hit.status_code == 200
    assert hit.json() == {
        "matter_id": matter,
        "revision": 2,
        "conflict_status": "conflict",
        "check_version": 1,
    }
    invalid = client.post(
        f"{base}/conflict-checks",
        headers=write(keys, **{"If-Match": '"2"'}),
        json={"result": "clear"},
    )
    assert invalid.status_code == 422
    missing_reason = client.post(
        f"{base}/conflict-waivers",
        headers=write(keys, **{"If-Match": '"2"'}),
        json={"reason": "  "},
    )
    assert missing_reason.status_code == 422
    waiver = client.post(
        f"{base}/conflict-waivers",
        headers=write(keys, **{"If-Match": '"2"'}),
        json={"reason": CANARY_REASON},
    )
    assert waiver.status_code == 200
    assert waiver.json() == {
        "matter_id": matter,
        "revision": 3,
        "conflict_status": "waived",
        "check_version": 1,
    }
    assert CANARY_REASON not in waiver.text and "Synthetic" not in waiver.text
    status = client.get(base, headers=auth(keys)).json()
    assert (status["conflict_status"], status["status"], status["revision"]) == (
        "waived",
        "ready",
        3,
    )
    clear = client.post(
        f"{base}/conflict-checks",
        headers=write(keys, **{"If-Match": '"3"'}),
        json={"result": "CLEAR"},
    )
    assert clear.json()["conflict_status"] == "clear" and clear.json()["check_version"] == 2
    not_waivable = client.post(
        f"{base}/conflict-waivers",
        headers=write(keys, **{"If-Match": '"4"'}),
        json={"reason": CANARY_REASON},
    )
    assert not_waivable.status_code == 409
    assert not_waivable.json() == {"error": "conflict_not_waivable"}


def test_conflict_record_retry_after_newer_check_is_conflict_changed(
    client: TestClient, keys: Keys
) -> None:
    matter = create(client, keys)
    base = f"/v1/matters/{matter}/conflict-checks"
    headers = write(keys, **{"If-Match": '"1"'})
    first = client.post(base, headers=headers, json={"result": "CONFLICT"})
    assert first.status_code == 200
    client.post(base, headers=write(keys, **{"If-Match": '"2"'}), json={"result": "CLEAR"})
    retry = client.post(base, headers=headers, json={"result": "CONFLICT"})
    assert retry.status_code == 409
    assert retry.json() == {"error": "conflict_changed"}


# ----------------------------------------------------------------------- revocation


def test_deactivation_between_requests(
    client: TestClient, keys: Keys, directory: IdentityDirectory
) -> None:
    matter = create(client, keys)
    token_headers = auth(keys)
    assert client.get(f"/v1/matters/{matter}", headers=token_headers).status_code == 200
    directory.set_active("tenant-a", "a-lawyer", False)
    assert_unauthenticated(client.get(f"/v1/matters/{matter}", headers=token_headers))
    directory.set_active("tenant-a", "a-lawyer", True)
    directory.upsert_principal("tenant-a", "a-lawyer", ["requester"])
    # Role changes are effective on the next request too.
    reduced = client.get(f"/v1/matters/{matter}", headers=token_headers)
    assert reduced.json() == {"matter_id": matter, "status": "awaiting_clearance"}


def _prepare(client: TestClient, keys: Keys, route: str) -> tuple[str, str, dict[str, str], int]:
    """A fresh matter ready for ``route``: (url, method, body, current revision)."""
    matter = create(client, keys)
    if route == "patch":
        return f"/v1/matters/{matter}", "PATCH", {"title": "Invented revoked change"}, 1
    if route == "conflict-checks":
        return f"/v1/matters/{matter}/conflict-checks", "POST", {"result": "CONFLICT"}, 1
    hit = client.post(
        f"/v1/matters/{matter}/conflict-checks",
        headers=write(keys, **{"If-Match": '"1"'}),
        json={"result": "CONFLICT"},
    )
    assert hit.status_code == 200
    return f"/v1/matters/{matter}/conflict-waivers", "POST", {"reason": CANARY_REASON}, 2


@pytest.mark.parametrize("route", ["patch", "conflict-checks", "conflict-waivers"])
def test_deactivation_between_auth_and_commit_rolls_back(
    client: TestClient,
    keys: Keys,
    engine: Engine,
    directory: IdentityDirectory,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
) -> None:
    url, method, body, revision = _prepare(client, keys, route)
    uow = api_of(client).uow
    original = uow.put

    def revoke_then_put(*args: Any, **kwargs: Any) -> Any:
        directory.set_active("tenant-a", "a-lawyer", False)
        return original(*args, **kwargs)

    monkeypatch.setattr(uow, "put", revoke_then_put)
    before = counts(engine)
    response = client.request(
        method, url, headers=write(keys, **{"If-Match": f'"{revision}"'}), json=body
    )
    assert_unauthenticated(response)
    assert counts(engine) == before
    directory.set_active("tenant-a", "a-lawyer", True)
    monkeypatch.setattr(uow, "put", original)
    matter_url = "/".join(url.split("/")[:4])
    after = client.get(matter_url, headers=auth(keys)).json()
    assert (after["revision"], after["title"]) == (revision, CANARY_TITLE)


@pytest.mark.parametrize("route", ["patch", "conflict-checks", "conflict-waivers"])
def test_replay_after_deactivation_is_401_and_after_role_loss_is_404(
    client: TestClient,
    keys: Keys,
    engine: Engine,
    directory: IdentityDirectory,
    route: str,
) -> None:
    url, method, body, revision = _prepare(client, keys, route)
    headers = write(keys, **{"If-Match": f'"{revision}"'})
    assert client.request(method, url, headers=headers, json=body).status_code == 200
    before = counts(engine)
    directory.set_active("tenant-a", "a-lawyer", False)
    assert_unauthenticated(client.request(method, url, headers=headers, json=body))
    directory.set_active("tenant-a", "a-lawyer", True)
    directory.upsert_principal("tenant-a", "a-lawyer", ["requester"])
    lost = client.request(method, url, headers=headers, json=body)
    assert lost.status_code == 404 and lost.json() == NOT_FOUND
    assert counts(engine) == before


def test_same_actor_id_in_another_tenant_is_404(
    client: TestClient, keys: Keys, directory: IdentityDirectory
) -> None:
    matter = create(client, keys)
    directory.upsert_principal(
        "tenant-b", "a-lawyer", ["lawyer", "partner"], display_name="Synthetic Twin"
    )
    directory.bind(ISSUER, "sub-b-twin", "tenant-b", "a-lawyer")
    read = client.get(f"/v1/matters/{matter}", headers=auth(keys, "sub-b-twin"))
    patch = client.patch(
        f"/v1/matters/{matter}",
        headers=write(keys, "sub-b-twin", **{"If-Match": '"1"'}),
        json={"title": "x"},
    )
    assert (read.status_code, read.json()) == (404, NOT_FOUND)
    assert (patch.status_code, patch.json()) == (404, NOT_FOUND)


def test_deactivation_during_audit_emission_denies_create(
    client: TestClient,
    keys: Keys,
    engine: Engine,
    directory: IdentityDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = api_of(client).audit
    original = audit.append

    def append_then_revoke(tenant_id: str, payload: Any) -> Any:
        event = original(tenant_id, payload)
        if getattr(payload, "action", None) == "create_matter":
            directory.set_active("tenant-a", "a-lawyer", False)
        return event

    monkeypatch.setattr(audit, "append", append_then_revoke)
    response = client.post("/v1/matters", headers=write(keys), json={"title": CANARY_TITLE})
    assert_unauthenticated(response)
    assert counts(engine) == (0, 0)


def test_directory_unavailable_is_503(keys: Keys, tmp_path: Path) -> None:
    settings = api_settings(f"sqlite:///{tmp_path / 'unmigrated.db'}", keys)
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/matters/m-1", headers=auth(keys))
    assert response.status_code == 503
    assert response.json() == {"error": "unavailable"}


def test_no_tokens_titles_or_reasons_in_logs(
    client: TestClient, keys: Keys, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = mint(keys)
    headers = {**bearer(token), "Idempotency-Key": str(uuid4())}
    matter = client.post("/v1/matters", headers=headers, json={"title": CANARY_TITLE}).json()
    client.post(
        f"/v1/matters/{matter['matter_id']}/conflict-checks",
        headers={**bearer(token), "Idempotency-Key": str(uuid4()), "If-Match": '"1"'},
        json={"result": "CONFLICT"},
    )
    client.post(
        f"/v1/matters/{matter['matter_id']}/conflict-waivers",
        headers={**bearer(token), "Idempotency-Key": str(uuid4()), "If-Match": '"2"'},
        json={"reason": CANARY_REASON},
    )
    client.get("/v1/matters/x", headers={"Authorization": "Bearer " + token[:-4] + "AAAA"})
    text = caplog.text
    assert token not in text and token.split(".")[2] not in text
    assert CANARY_TITLE not in text and CANARY_REASON not in text


def test_no_canaries_in_logs_or_bodies_on_413_422_500(
    client: TestClient,
    keys: Keys,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG)
    matter = create(client, keys)
    too_large = client.post(
        "/v1/matters",
        headers={**write(keys), "Content-Type": "application/json"},
        content=json.dumps({"title": CANARY_TITLE * 1000}).encode(),
    )
    invalid = client.post(
        "/v1/matters", headers=write(keys), json={"title": CANARY_TITLE + "\u202e"}
    )

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"{CANARY_TITLE} {CANARY_REASON}")

    monkeypatch.setattr(MatterService, "update_title", boom)
    failing = TestClient(client.app, raise_server_exceptions=False)
    crashed = failing.patch(
        f"/v1/matters/{matter}",
        headers=write(keys, **{"If-Match": '"1"'}),
        json={"title": CANARY_TITLE},
    )
    assert (too_large.status_code, invalid.status_code, crashed.status_code) == (413, 422, 500)
    for response in (too_large, invalid, crashed):
        assert CANARY_TITLE not in response.text and CANARY_REASON not in response.text
    assert "RuntimeError" in caplog.text  # the failure is visible by type only
    assert CANARY_TITLE not in caplog.text and CANARY_REASON not in caplog.text


# ----------------------------------------------------------------------- review fixes


def _seed_shared(engine: Engine, matter: str = "m-shared-team") -> str:
    SqlMatterRepository(engine).add(
        TenantId("tenant-a"),
        MatterRecord(
            MatterAccess(
                TenantId("tenant-a"),
                MatterId(matter),
                members=frozenset({ActorId("a-lawyer"), ActorId("a-partner")}),
            ),
            MatterContent(CANARY_TITLE),
        ),
    )
    return f"/v1/matters/{matter}"


def test_other_actors_key_on_matter_route_is_uniform_404(
    client: TestClient, keys: Keys, engine: Engine
) -> None:
    url = _seed_shared(engine)
    key = str(uuid4())
    body = {"title": "Invented renamed team review"}
    first = client.patch(
        url, headers={**auth(keys), "Idempotency-Key": key, "If-Match": '"1"'}, json=body
    )
    assert first.status_code == 200
    before = counts(engine)
    # A co-member reusing the key (same body) and a stranger both get the plain 404.
    for subject in ("sub-a-partner", "sub-a-outsider"):
        other = client.patch(
            url,
            headers={**auth(keys, subject), "Idempotency-Key": key, "If-Match": '"1"'},
            json=body,
        )
        assert (other.status_code, other.json()) == (404, NOT_FOUND)
    # The key's own actor with a different request still gets 409.
    mine = client.patch(
        url,
        headers={**auth(keys), "Idempotency-Key": key, "If-Match": '"1"'},
        json={"title": "Different invented title"},
    )
    assert (mine.status_code, mine.json()) == (409, {"error": "idempotency_key_reused"})
    assert counts(engine) == before


def test_mutation_authorizer_without_bound_connection_fails_closed(
    client: TestClient, keys: Keys, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from verina.access import sql_repository

    matter = create(client, keys)
    before = counts(engine)

    @contextmanager
    def unbound(conn: Any) -> Any:
        yield conn

    monkeypatch.setattr(sql_repository, "bind_connection", unbound)
    response = client.patch(
        f"/v1/matters/{matter}",
        headers=write(keys, **{"If-Match": '"1"'}),
        json={"title": "Invented unbound change"},
    )
    assert (response.status_code, response.json()) == (503, {"error": "unavailable"})
    assert counts(engine) == before


@pytest.mark.parametrize(
    "title",
    [
        "Invented\u202eweiver",  # right-to-left override (Cf)
        "Invented\u200bzero width",  # zero-width space (Cf)
        "Invented\u2028line",  # line separator (Zl)
        "Invented\u2029para",  # paragraph separator (Zp)
        "Invented\ttab",  # tabs are allowed in reasons only
        "Invented\u00adsoft hyphen",  # soft hyphen (Cf)
    ],
)
def test_titles_reject_invisible_and_separator_characters(
    client: TestClient, keys: Keys, title: str
) -> None:
    response = client.post("/v1/matters", headers=write(keys), json={"title": title})
    assert (response.status_code, response.json()) == (422, {"error": "validation_failed"})


def test_text_is_nfc_normalised_and_reasons_allow_newlines(client: TestClient, keys: Keys) -> None:
    decomposed = "Invented Cafe\u0301 review"
    response = client.post("/v1/matters", headers=write(keys), json={"title": decomposed})
    assert response.status_code == 201
    matter = response.json()["matter_id"]
    title = client.get(f"/v1/matters/{matter}", headers=auth(keys)).json()["title"]
    assert title == "Invented Caf\u00e9 review"
    hit = client.post(
        f"/v1/matters/{matter}/conflict-checks",
        headers=write(keys, **{"If-Match": '"1"'}),
        json={"result": "CONFLICT"},
    )
    assert hit.status_code == 200
    for bad in ("Invented\u202ereason", "Invented\u200breason", "Invented\u2028reason"):
        rejected = client.post(
            f"/v1/matters/{matter}/conflict-waivers",
            headers=write(keys, **{"If-Match": '"2"'}),
            json={"reason": bad},
        )
        assert (rejected.status_code, rejected.json()) == (422, {"error": "validation_failed"})
    accepted = client.post(
        f"/v1/matters/{matter}/conflict-waivers",
        headers=write(keys, **{"If-Match": '"2"'}),
        json={"reason": "Invented line one\n\tInvented line two"},
    )
    assert accepted.status_code == 200


def test_principal_recheck_inside_mutation_uses_for_share_on_postgresql(
    client: TestClient, keys: Keys, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = api_of(client)
    if api.engine.dialect.name != "postgresql":
        pytest.skip("FOR SHARE row locking is PostgreSQL-specific; SQLite uses BEGIN IMMEDIATE")
    matter = create(client, keys)
    inside: list[str] = []
    active = {"put": False}
    original = api.uow.put

    def tracked_put(*args: Any, **kwargs: Any) -> Any:
        active["put"] = True
        try:
            return original(*args, **kwargs)
        finally:
            active["put"] = False

    def capture(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        if active["put"]:
            inside.append(statement)

    monkeypatch.setattr(api.uow, "put", tracked_put)
    event.listen(api.engine, "before_cursor_execute", capture)
    try:
        response = client.patch(
            f"/v1/matters/{matter}",
            headers=write(keys, **{"If-Match": '"1"'}),
            json={"title": "Invented locked change"},
        )
    finally:
        event.remove(api.engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    principal_reads = [
        s for s in inside if "identity_principals" in s and s.lstrip().upper().startswith("SELECT")
    ]
    assert principal_reads, "the mutation must re-read the principal inside its transaction"
    assert all("FOR SHARE" in s.upper() for s in principal_reads if "roles" in s)
    assert any("FOR SHARE" in s.upper() for s in principal_reads)
