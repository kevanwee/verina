"""Independent stale-directory authorization probes; synthetic identities only."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, delete

from verina.access import ActorId, IdentityDirectory, Role, TenantId
from verina.access.accounts import AccountsError, AccountsService, Caller
from verina.access.auth_admin import FakeAuthAdmin
from verina.access.directory_schema import platform_admins
from verina.access.identity import _issue
from verina.access.sql_identity import identity_bindings
from verina.audit import SqlAuditStore

from .conftest import ISSUER

pytestmark = pytest.mark.story("US-54")


def test_stale_platform_grant_denied_before_replay_read_or_invite(engine: Engine) -> None:
    fake = FakeAuthAdmin()
    service = AccountsService(engine, SqlAuditStore(engine), fake, issuer=ISSUER)
    with engine.begin() as conn:
        conn.execute(
            platform_admins.insert().values(
                issuer=ISSUER,
                subject="security-platform",
                admin_id="pa_security",
                created_at=datetime.now(UTC),
            )
        )
    stale = Caller(ISSUER, "security-platform", None, None, "pa_security")
    operation = uuid4()
    original = service.create_organization(stale, operation, "Synthetic Security", "security-probe")
    with engine.begin() as conn:
        conn.execute(
            delete(platform_admins).where(platform_admins.c.subject == "security-platform")
        )
    calls: list[Callable[[], object]] = [
        lambda: service.create_organization(
            stale, operation, "Synthetic Security", "security-probe"
        ),
        lambda: service.list_organizations(stale),
        lambda: service.invite_member(
            stale,
            uuid4(),
            original.value.id,
            email="security@example.test",
            display_name="Synthetic Security",
            roles=["lawyer"],
        ),
    ]
    for call in calls:
        with pytest.raises(AccountsError) as denied:
            call()
        assert denied.value.code == "not_found"
    assert fake.invites == []
    assert service.me(stale) == {"linked": False}


def test_stale_tenant_roles_and_binding_do_not_leak_member_replay(
    engine: Engine,
    directory: IdentityDirectory,
) -> None:
    directory.upsert_principal(
        "tenant-security", "security-admin", [Role.TENANT_ADMIN], display_name="Synthetic Security"
    )
    directory.bind(ISSUER, "security-admin-subject", "tenant-security", "security-admin")
    stale = Caller(
        ISSUER,
        "security-admin-subject",
        None,
        _issue(TenantId("tenant-security"), ActorId("security-admin"), [Role.TENANT_ADMIN]),
        None,
    )
    fake = FakeAuthAdmin()
    service = AccountsService(engine, SqlAuditStore(engine), fake, issuer=ISSUER)
    operation = uuid4()
    command: dict[str, Any] = dict(
        email="security-member@example.test", display_name="Synthetic Member", roles=["lawyer"]
    )
    service.invite_member(stale, operation, "tenant-security", **command)
    directory.upsert_principal("tenant-security", "security-admin", [Role.LAWYER])
    assert service.me(stale)["roles"] == ["lawyer"]
    calls: list[Callable[[], object]] = [
        lambda: service.list_members(stale, "tenant-security"),
        lambda: service.invite_member(stale, operation, "tenant-security", **command),
    ]
    for call in calls:
        with pytest.raises(AccountsError) as denied:
            call()
        assert denied.value.code == "not_found"
    assert len(fake.invites) == 1
    directory.set_active("tenant-security", "security-admin", False)
    assert service.me(stale) == {"linked": False}
    directory.set_active("tenant-security", "security-admin", True)
    with engine.begin() as conn:
        conn.execute(
            delete(identity_bindings).where(identity_bindings.c.subject == "security-admin-subject")
        )
    assert service.me(stale) == {"linked": False}
