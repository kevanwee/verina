"""Organizations, platform-admin grant and directory audit (migration 0005, ADR 009)."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from verina.access import IdentityDirectory, Role, SqlIdentityAdapter
from verina.access.directory_schema import (
    SLUG_PATTERN,
    SYSTEM_CHAIN_ID,
    admin_idempotency,
    directory_accounts,
    legacy_slug,
    organizations,
    platform_admins,
)
from verina.access.domain import ActorId, TenantId
from verina.access.identity import AuthenticationError
from verina.access.sql_identity import identity_principals
from verina.access.subject_hmac import derive_subject_key, subject_hmac
from verina.access.tokens import JwtVerifier
from verina.audit import SqlAuditStore
from verina.audit.events import AuthenticationFailed, DirectoryChanged
from verina.db import downgrade, upgrade

from .conftest import ISSUER, Keys, bearer, mint

pytestmark = pytest.mark.story("US-47")

HEAD_KEY = b"synthetic-test-head-key-0123456789abcdef"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


@pytest.fixture
def adapter(engine: Engine, verifier: JwtVerifier) -> SqlIdentityAdapter:
    return SqlIdentityAdapter(engine, verifier)


def set_org_active(engine: Engine, org_id: str, active: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(organizations).where(organizations.c.id == org_id).values(active=active)
        )


# ----------------------------------------------------------------------------- migration


def test_migration_0005_tables_match_metadata(engine: Engine) -> None:
    inspector = inspect(engine)
    for table in (organizations, platform_admins, directory_accounts, admin_idempotency):
        reflected = {c["name"]: c for c in inspector.get_columns(table.name)}
        assert set(reflected) == {c.name for c in table.columns}, table.name
        for column in table.columns:
            assert reflected[column.name]["nullable"] == column.nullable, (table.name, column)
    assert inspector.get_pk_constraint("platform_admins")["constrained_columns"] == [
        "issuer",
        "subject",
    ]
    uniques = {u["name"] for u in inspector.get_unique_constraints("organizations")}
    assert "uq_organizations_slug" in uniques


def test_migration_0005_round_trip_and_backfill(engine: Engine) -> None:
    downgrade(engine, "0004_identity_directory")
    assert "organizations" not in inspect(engine).get_table_names()
    tenants = ["tenant-a", "Tenant_A", "x", "a" * 128, "tenant.b:c"]
    with engine.begin() as conn:
        for i, tenant in enumerate(tenants):
            conn.execute(
                identity_principals.insert().values(
                    tenant_id=tenant,
                    actor_id=f"actor-{i}",
                    roles="lawyer",
                    active=True,
                    display_name=None,
                    revision=1,
                    updated_at=NOW,
                )
            )
    upgrade(engine)
    with engine.begin() as conn:
        rows = {r.id: r for r in conn.execute(select(organizations))}
    assert set(rows) == set(tenants)
    slugs = [r.slug for r in rows.values()]
    assert len(set(slugs)) == len(slugs)
    assert all(SLUG_PATTERN.fullmatch(s) for s in slugs), slugs
    assert all(r.active is True and r.revision == 1 for r in rows.values())
    assert rows["x"].slug == "org-x"


def test_legacy_slug_rules() -> None:
    assert legacy_slug("tenant-a", set()) == "tenant-a"
    assert legacy_slug("tenant-a", {"tenant-a"}) == "tenant-a-2"
    assert legacy_slug("tenant-a", {"tenant-a", "tenant-a-2"}) == "tenant-a-3"
    assert legacy_slug("--", set()) == "org"
    long = legacy_slug("b" * 60, {"b" * 40})
    assert long == "b" * 38 + "-2" and SLUG_PATTERN.fullmatch(long)


def test_admin_idempotency_is_append_only(engine: Engine) -> None:
    store = SqlAuditStore(engine)
    event = store.append(
        SYSTEM_CHAIN_ID,
        DirectoryChanged(
            occurred_at=NOW,
            tenant_id=SYSTEM_CHAIN_ID,
            actor="cli:test",
            actor_kind="cli",
            action="platform_admin_bootstrapped",
        ),
    )
    with engine.begin() as conn:
        conn.execute(
            admin_idempotency.insert().values(
                scope=SYSTEM_CHAIN_ID,
                operation_id=str(uuid4()),
                actor_key="0" * 64,
                action="create_organization",
                request_hash="1" * 64,
                resource_id="org_x",
                status_code=201,
                event_id=str(event.event_id),
                created_at=NOW,
            )
        )
    for statement in (
        "UPDATE admin_idempotency SET status_code = 200",
        "DELETE FROM admin_idempotency",
    ):
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(statement))


def test_member_account_email_is_unique(engine: Engine) -> None:
    directory = IdentityDirectory(engine)
    directory.upsert_principal("tenant-u", "u-1", [Role.LAWYER])
    directory.upsert_principal("tenant-u", "u-2", [Role.LAWYER])
    with engine.begin() as conn:
        conn.execute(
            directory_accounts.insert().values(
                tenant_id="tenant-u",
                actor_id="u-1",
                email="same@example.test",
                invite_status="pending",
                invited_at=NOW,
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            directory_accounts.insert().values(
                tenant_id="tenant-u",
                actor_id="u-2",
                email="same@example.test",
                invite_status="pending",
                invited_at=NOW,
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            directory_accounts.insert().values(
                tenant_id="tenant-u",
                actor_id="u-2",
                email="other@example.test",
                invite_status="invited",
                invited_at=NOW,
            )
        )


# ----------------------------------------------------------------------------- authentication


def test_seeding_creates_active_organizations(engine: Engine, directory: IdentityDirectory) -> None:
    with engine.begin() as conn:
        ids = set(conn.execute(select(organizations.c.id)).scalars())
    assert {"tenant-a", "tenant-b"} <= ids


def test_organization_deactivation_fails_every_member_next_request(
    engine: Engine, directory: IdentityDirectory, adapter: SqlIdentityAdapter, keys: Keys
) -> None:
    principal = adapter.authenticate(bearer(mint(keys, "sub-a-lawyer")))
    assert principal.tenant_id == TenantId("tenant-a")
    set_org_active(engine, "tenant-a", False)
    for subject in ("sub-a-lawyer", "sub-a-partner", "sub-a-requester"):
        with pytest.raises(AuthenticationError) as failure:
            adapter.authenticate(bearer(mint(keys, subject)))
        assert failure.value.reason == "organization_inactive"
        assert failure.value.subject == (ISSUER, subject)
        assert str(failure.value) == "unauthenticated"
    assert adapter.current(TenantId("tenant-a"), ActorId("a-lawyer")) is None
    # Other organizations are unaffected.
    assert adapter.authenticate(bearer(mint(keys, "sub-b-lawyer"))).tenant_id == TenantId(
        "tenant-b"
    )
    set_org_active(engine, "tenant-a", True)
    assert adapter.current(TenantId("tenant-a"), ActorId("a-lawyer")) is not None


def test_missing_organization_row_fails_closed(
    engine: Engine, directory: IdentityDirectory, adapter: SqlIdentityAdapter, keys: Keys
) -> None:
    with engine.begin() as conn:
        conn.execute(organizations.delete().where(organizations.c.id == "tenant-b"))
    with pytest.raises(AuthenticationError) as failure:
        adapter.authenticate(bearer(mint(keys, "sub-b-lawyer")))
    assert failure.value.reason == "unbound"
    assert adapter.current(TenantId("tenant-b"), ActorId("b-lawyer")) is None


def test_resolution_reasons_and_platform_admin_grant(
    engine: Engine, directory: IdentityDirectory, adapter: SqlIdentityAdapter, keys: Keys
) -> None:
    unbound = adapter.resolve(bearer(mint(keys, "sub-nobody")))
    assert (unbound.principal, unbound.platform_admin_id, unbound.unlinked_reason) == (
        None,
        None,
        "unbound",
    )
    assert unbound.subject == (ISSUER, "sub-nobody")
    with engine.begin() as conn:
        conn.execute(
            platform_admins.insert().values(
                issuer=ISSUER, subject="sub-nobody", admin_id="pa_synthetic", created_at=NOW
            )
        )
    admin = adapter.resolve(bearer(mint(keys, "sub-nobody")))
    assert admin.platform_admin_id == "pa_synthetic" and admin.principal is None
    directory.set_active("tenant-a", "a-lawyer", False)
    inactive = adapter.resolve(bearer(mint(keys, "sub-a-lawyer")))
    assert inactive.unlinked_reason == "principal_inactive"
    with engine.begin() as conn:
        conn.execute(
            update(identity_principals)
            .where(identity_principals.c.actor_id == "a-partner")
            .values(roles="not-a-role")
        )
    broken = adapter.resolve(bearer(mint(keys, "sub-a-partner")))
    assert broken.unlinked_reason == "directory_record_invalid"


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({}, "missing_credential"),
        ({"Authorization": "Basic abc"}, "malformed_credential"),
        ({"Authorization": "Bearer  two"}, "malformed_credential"),
        ({"Authorization": "Bearer not.a.token"}, "token_rejected"),
    ],
)
def test_credential_failure_reason_classes(
    adapter: SqlIdentityAdapter, headers: dict[str, str], reason: str
) -> None:
    with pytest.raises(AuthenticationError) as failure:
        adapter.authenticate(headers)
    assert failure.value.reason == reason and failure.value.subject is None


def test_duplicate_authorization_headers_are_malformed(adapter: SqlIdentityAdapter) -> None:
    class Multi:
        def items(self) -> list[tuple[str, str]]:
            return [("authorization", "Bearer a.b.c"), ("Authorization", "Bearer a.b.c")]

    with pytest.raises(AuthenticationError) as failure:
        adapter.authenticate(Multi())  # type: ignore[arg-type]
    assert failure.value.reason == "malformed_credential"


# ----------------------------------------------------------------------------- directory audit


def audited_directory(engine: Engine) -> tuple[IdentityDirectory, SqlAuditStore]:
    store = SqlAuditStore(engine, head_key=HEAD_KEY)
    return (
        IdentityDirectory(engine, audit=store, subject_key=derive_subject_key(HEAD_KEY)),
        store,
    )


def test_provisioning_writes_are_audited_in_the_tenant_chain(engine: Engine) -> None:
    directory, store = audited_directory(engine)
    directory.upsert_principal("tenant-q", "q-1", [Role.LAWYER], display_name="Invented Q One")
    directory.bind(ISSUER, "sub-q-1", "tenant-q", "q-1")
    directory.set_active("tenant-q", "q-1", False)
    assert directory.unbind(ISSUER, "sub-q-1") is True
    assert directory.unbind(ISSUER, "sub-q-1") is False
    events = store.events("tenant-q")
    assert [e.payload["action"] for e in events] == [
        "principal_upserted",
        "binding_created",
        "principal_activation_changed",
        "binding_removed",
    ]
    assert store.verify_chain("tenant-q").ok
    dumped = json.dumps([e.payload for e in events])
    assert "Invented Q One" not in dumped and "sub-q-1" not in dumped
    expected = subject_hmac(derive_subject_key(HEAD_KEY), ISSUER, "sub-q-1")
    assert events[1].payload["subject_hmac"] == expected


def test_audit_failure_rolls_back_the_directory_write(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, store = audited_directory(engine)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(store, "append_on_connection", boom)
    with pytest.raises(RuntimeError):
        directory.upsert_principal("tenant-r", "r-1", [Role.LAWYER])
    with engine.begin() as conn:
        assert conn.execute(select(identity_principals)).first() is None
        assert (
            conn.execute(select(organizations).where(organizations.c.id == "tenant-r")).first()
            is None
        )


def test_directory_and_audit_must_share_an_engine(engine: Engine) -> None:
    from verina.db import make_engine

    other = make_engine("sqlite://")
    try:
        with pytest.raises(ValueError):
            IdentityDirectory(engine, audit=SqlAuditStore(other))
    finally:
        other.dispose()


# ----------------------------------------------------------------------------- payloads


def test_subject_hmac_is_keyed_and_domain_separated() -> None:
    key = derive_subject_key(SecretStr(HEAD_KEY.decode()))
    assert key == derive_subject_key(HEAD_KEY) and key != HEAD_KEY
    assert derive_subject_key(None) is None
    assert subject_hmac(None, ISSUER, "s") is None
    value = subject_hmac(key, ISSUER, "s")
    assert value is not None and value.startswith("hmac-sha256:") and len(value) == 76
    assert value != subject_hmac(derive_subject_key(b"x" * 32), ISSUER, "s")
    with pytest.raises(ValueError):
        derive_subject_key(b"short")


def test_new_payloads_refuse_content_fields() -> None:
    with pytest.raises(ValueError):
        DirectoryChanged.model_validate(
            {
                "occurred_at": NOW,
                "tenant_id": "t",
                "actor": "a",
                "actor_kind": "cli",
                "action": "member_invited",
                "email": "x@example.test",
            }
        )
    with pytest.raises(ValueError):
        AuthenticationFailed.model_validate(
            {
                "occurred_at": NOW,
                "tenant_id": "t",
                "reason_class": "unbound",
                "surface": "me",
                "subject_hmac": "raw-subject",
            }
        )
