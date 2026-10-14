"""Independent account recovery and fail-closed probes; invented identities only."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select

from verina.access import ActorId, Role, TenantId
from verina.access.accounts import AccountsError, AccountsService, Caller
from verina.access.auth_admin import FakeAuthAdmin
from verina.access.directory_schema import directory_accounts
from verina.access.identity import _issue
from verina.access.sql_identity import identity_bindings
from verina.audit import SqlAuditStore
from verina.audit.schema import audit_events
from verina.config import Settings
from verina.db import make_engine
from verina.main import create_app

from .conftest import ISSUER
from .test_accounts_api import PLATFORM, world  # noqa: F401

pytestmark = [pytest.mark.story("US-54"), pytest.mark.usefixtures("world")]


def platform() -> Caller:
    return Caller(ISSUER, PLATFORM, None, None, "pa_synthetic")


def test_committed_invite_and_update_replay_after_engine_restart(
    db_url: str, engine: Engine
) -> None:
    provider = FakeAuthAdmin()
    service = AccountsService(engine, SqlAuditStore(engine), provider, issuer=ISSUER)
    command: dict[str, Any] = dict(
        email="qa-restart@example.test", display_name="Invented QA", roles=["lawyer"]
    )
    operation = uuid4()
    original = service.invite_member(platform(), operation, "tenant-a", **command)
    update = uuid4()
    service.update_member(
        platform(), update, "tenant-a", original.value.actor_id, roles=["partner"]
    )
    with engine.begin() as conn:
        count = conn.execute(select(func.count()).select_from(audit_events)).scalar_one()
    engine.dispose()
    restarted = make_engine(db_url)
    fresh_provider = FakeAuthAdmin(fail_with="unavailable")
    try:
        recovered = AccountsService(
            restarted, SqlAuditStore(restarted), fresh_provider, issuer=ISSUER
        )
        replay = recovered.invite_member(platform(), operation, "tenant-a", **command)
        assert replay.value.actor_id == original.value.actor_id
        assert replay.value.roles == ("partner",)  # current view, no obsolete-role overwrite
        assert replay.status == 201
        recovered.update_member(
            platform(), update, "tenant-a", original.value.actor_id, roles=["partner"]
        )
        with restarted.begin() as conn:
            assert (
                conn.execute(select(func.count()).select_from(audit_events)).scalar_one() == count
            )
        assert fresh_provider.invites == []
    finally:
        restarted.dispose()


def test_me_acceptance_is_atomic_and_requires_current_exact_binding(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeAuthAdmin()
    store = SqlAuditStore(engine)
    service = AccountsService(engine, store, provider, issuer=ISSUER)
    member = service.invite_member(
        platform(),
        uuid4(),
        "tenant-a",
        email="qa-accept@example.test",
        display_name="Invented QA",
        roles=["lawyer"],
    ).value
    subject = provider.users["qa-accept@example.test"][0]
    caller = Caller(
        ISSUER,
        subject,
        None,
        _issue(TenantId("tenant-a"), ActorId(member.actor_id), [Role.LAWYER]),
        None,
    )

    def outage(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("invented audit failure")

    with monkeypatch.context() as patch:
        patch.setattr(store, "append_on_connection", outage)
        with pytest.raises(RuntimeError, match="invented audit failure"):
            service.me(caller)
    with engine.begin() as conn:
        assert (
            conn.execute(
                select(directory_accounts.c.invite_status).where(
                    directory_accounts.c.actor_id == member.actor_id
                )
            ).scalar_one()
            == "pending"
        )
        conn.execute(delete(identity_bindings).where(identity_bindings.c.subject == subject))
    assert service.me(caller) == {"linked": False}
    with engine.begin() as conn:
        assert (
            conn.execute(
                select(directory_accounts.c.invite_status).where(
                    directory_accounts.c.actor_id == member.actor_id
                )
            ).scalar_one()
            == "pending"
        )


def test_cross_issuer_stale_admin_cannot_replay_or_invite(engine: Engine) -> None:
    provider = FakeAuthAdmin()
    service = AccountsService(engine, SqlAuditStore(engine), provider, issuer=ISSUER)
    stale = Caller(
        "https://different.synthetic.test/",
        "sub-a-admin",
        None,
        _issue(TenantId("tenant-a"), ActorId("a-admin"), [Role.TENANT_ADMIN]),
        None,
    )
    for action in (
        lambda: service.list_members(stale, "tenant-a"),
        lambda: service.invite_member(
            stale,
            uuid4(),
            "tenant-a",
            email="qa-denied@example.test",
            display_name="Invented QA",
            roles=["lawyer"],
        ),
    ):
        with pytest.raises(AccountsError) as failure:
            action()
        assert failure.value.code == "not_found"
    assert provider.invites == []


def test_all_accounts_routes_absent_when_api_disabled() -> None:
    with TestClient(
        create_app(Settings(_env_file=None, env="test", matters_api_enabled=False))
    ) as client:
        for method, path in (
            ("GET", "/v1/me"),
            ("GET", "/v1/admin/organizations"),
            ("POST", "/v1/admin/organizations"),
            ("GET", "/v1/admin/organizations/tenant-a"),
            ("PATCH", "/v1/admin/organizations/tenant-a"),
            ("GET", "/v1/organizations/tenant-a/members"),
            ("POST", "/v1/organizations/tenant-a/members"),
            ("PATCH", "/v1/organizations/tenant-a/members/a-admin"),
            ("POST", "/v1/organizations/tenant-a/members/a-admin/resend-invite"),
        ):
            assert client.request(method, path).status_code == 404
