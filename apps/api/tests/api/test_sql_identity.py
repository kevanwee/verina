"""SqlIdentityAdapter and the Verina-owned identity directory (synthetic principals only)."""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, select, update
from starlette.datastructures import Headers

from verina.access import (
    ActorId,
    AuthenticationError,
    IdentityAdapter,
    IdentityDirectory,
    IdentityUnavailableError,
    Role,
    SqlIdentityAdapter,
    SqlMatterRepository,
    TenantId,
)
from verina.access.provision import run as provision
from verina.access.sql_identity import identity_bindings, identity_principals
from verina.access.tokens import JwtVerifier
from verina.config import Settings
from verina.db import active_connection, downgrade, make_engine, upgrade

from .conftest import ISSUER, Keys, bearer, mint

pytestmark = pytest.mark.story("EN-7")

A, B = TenantId("tenant-a"), TenantId("tenant-b")


@pytest.fixture
def adapter(
    engine: Engine, verifier: JwtVerifier, directory: IdentityDirectory
) -> SqlIdentityAdapter:
    return SqlIdentityAdapter(engine, verifier)


def test_adapter_satisfies_protocol(adapter: SqlIdentityAdapter) -> None:
    assert isinstance(adapter, IdentityAdapter)


def test_valid_token_resolves_directory_principal(adapter: SqlIdentityAdapter, keys: Keys) -> None:
    principal = adapter.authenticate(bearer(mint(keys)))
    assert (principal.tenant_id, principal.actor_id) == (A, ActorId("a-lawyer"))
    assert principal.roles == frozenset({Role.LAWYER})


def test_token_claims_never_grant_roles_or_tenant(adapter: SqlIdentityAdapter, keys: Keys) -> None:
    token = mint(
        keys,
        "sub-a-requester",
        roles=["partner", "tenant_admin"],
        role="partner",
        tenant_id="tenant-b",
        tenant="tenant-b",
        actor_id="b-lawyer",
        app_metadata={"roles": ["partner"]},
    )
    headers = {**bearer(token), "X-Tenant-Id": "tenant-b", "X-Roles": "partner"}
    principal = adapter.authenticate(headers)
    assert principal.tenant_id == A
    assert principal.actor_id == ActorId("a-requester")
    assert principal.roles == frozenset({Role.REQUESTER})


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer  two-spaces"},
        {"Authorization": "Bearer a b"},
        {"Authorization": "Bearer " + "x" * 9000},
        {"Authorization": "Bearer not-a-jwt"},
    ],
)
def test_missing_or_malformed_header(adapter: SqlIdentityAdapter, headers: dict[str, str]) -> None:
    with pytest.raises(AuthenticationError) as info:
        adapter.authenticate(headers)
    assert str(info.value) == "unauthenticated"


def test_duplicate_authorization_headers_are_rejected(
    adapter: SqlIdentityAdapter, keys: Keys
) -> None:
    value = f"Bearer {mint(keys)}".encode()
    headers = Headers(raw=[(b"authorization", value), (b"authorization", value)])
    with pytest.raises(AuthenticationError):
        adapter.authenticate(headers)


def test_unknown_binding_and_other_issuer_fail(
    adapter: SqlIdentityAdapter, keys: Keys, directory: IdentityDirectory
) -> None:
    with pytest.raises(AuthenticationError):
        adapter.authenticate(bearer(mint(keys, "sub-nobody")))
    # A binding under another issuer does not match tokens from the configured issuer.
    directory.upsert_principal("tenant-a", "a-other-idp", [Role.PARTNER])
    directory.bind("https://other.synthetic.test/", "sub-other", "tenant-a", "a-other-idp")
    with pytest.raises(AuthenticationError):
        adapter.authenticate(bearer(mint(keys, "sub-other")))


def test_deactivation_revokes_and_profile_is_retained(
    adapter: SqlIdentityAdapter, keys: Keys, directory: IdentityDirectory
) -> None:
    token = mint(keys)
    principal = adapter.authenticate(bearer(token))
    assert directory.set_active("tenant-a", "a-lawyer", False) == 2
    with pytest.raises(AuthenticationError):
        adapter.authenticate(bearer(token))
    assert adapter.current(principal.tenant_id, principal.actor_id) is None
    profile = adapter.profile(principal.tenant_id, principal.actor_id)
    assert profile is not None and profile.display_name == "Synthetic Lawyer A"
    directory.set_active("tenant-a", "a-lawyer", True)
    assert adapter.current(principal.tenant_id, principal.actor_id) == principal


def test_current_rereads_roles_and_unbind_stops_new_auth(
    adapter: SqlIdentityAdapter, keys: Keys, directory: IdentityDirectory
) -> None:
    token = mint(keys)
    principal = adapter.authenticate(bearer(token))
    assert directory.upsert_principal("tenant-a", "a-lawyer", [Role.PARTNER, Role.LAWYER]) == 2
    current = adapter.current(principal.tenant_id, principal.actor_id)
    assert current is not None and current.roles == frozenset({Role.PARTNER, Role.LAWYER})
    # Omitting the display name on update keeps the retained profile.
    profile = adapter.profile(principal.tenant_id, principal.actor_id)
    assert profile is not None and profile.display_name == "Synthetic Lawyer A"
    assert directory.unbind(ISSUER, "sub-a-lawyer") is True
    assert directory.unbind(ISSUER, "sub-a-lawyer") is False
    with pytest.raises(AuthenticationError):
        adapter.authenticate(bearer(token))
    # current() is keyed by tenant/actor: an already-authenticated principal is not revoked by
    # unbinding alone (documented); deactivation is the revocation control.
    assert adapter.current(principal.tenant_id, principal.actor_id) is not None


def test_principal_without_profile_and_typed_inputs(
    adapter: SqlIdentityAdapter, keys: Keys
) -> None:
    principal = adapter.authenticate(bearer(mint(keys, "sub-a-noprofile")))
    assert adapter.profile(principal.tenant_id, principal.actor_id) is None
    assert adapter.current("tenant-a", "a-lawyer") is None  # type: ignore[arg-type]
    assert adapter.profile("tenant-a", "a-lawyer") is None  # type: ignore[arg-type]
    assert adapter.current(A, ActorId("a-missing")) is None
    assert adapter.profile(B, ActorId("a-lawyer")) is None


@pytest.mark.parametrize(
    "values",
    [
        {"roles": "lawyer,superuser"},
        {"roles": "lawyer,lawyer"},
        {"roles": "Lawyer"},
        {"display_name": "bad\nname"},
    ],
)
def test_corrupt_directory_rows_fail_closed(
    engine: Engine, adapter: SqlIdentityAdapter, keys: Keys, values: dict[str, str]
) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(identity_principals)
            .where(identity_principals.c.actor_id == "a-lawyer")
            .values(**values)
        )
    if "display_name" in values:
        assert adapter.profile(A, ActorId("a-lawyer")) is None
        return
    with pytest.raises(AuthenticationError):
        adapter.authenticate(bearer(mint(keys)))
    assert adapter.current(A, ActorId("a-lawyer")) is None


def test_current_reads_on_the_bound_mutation_transaction(
    engine: Engine, adapter: SqlIdentityAdapter
) -> None:
    """Inside a repository transaction the directory is read on that same connection.

    The uncommitted deactivation below is visible only to the same transaction, so a
    ``None`` result proves the shared connection was used (and on SQLite that no second
    ``BEGIN IMMEDIATE`` was attempted, which would otherwise wait for the first).
    """
    repo = SqlMatterRepository(engine)
    with repo._transaction() as conn:
        conn.execute(
            update(identity_principals)
            .where(identity_principals.c.actor_id == "a-lawyer")
            .values(active=False)
        )
        assert active_connection(engine) is conn
        assert adapter.current(A, ActorId("a-lawyer")) is None
        assert adapter.profile(A, ActorId("a-lawyer")) is not None
    assert active_connection(engine) is None
    assert adapter.current(A, ActorId("a-lawyer")) is None


def test_directory_unavailable_is_generic(
    keys: Keys, verifier: JwtVerifier, tmp_path: Path
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'empty.db'}")  # no migrations applied
    try:
        adapter = SqlIdentityAdapter(engine, verifier)
        with pytest.raises(IdentityUnavailableError) as info:
            adapter.authenticate(bearer(mint(keys)))
        assert str(info.value) == "identity directory unavailable"
        with pytest.raises(IdentityUnavailableError):
            adapter.current(A, ActorId("a-lawyer"))
    finally:
        engine.dispose()


def test_directory_validation(directory: IdentityDirectory) -> None:
    with pytest.raises(ValueError):
        directory.upsert_principal("tenant-a", "x", ["root"])
    with pytest.raises(ValueError):
        directory.upsert_principal("bad tenant", "x", [])
    with pytest.raises(ValueError):
        directory.upsert_principal("tenant-a", "x", [], display_name="  ")
    with pytest.raises(ValueError):
        directory.upsert_principal("tenant-a", "x", [], active="yes")  # type: ignore[arg-type]
    with pytest.raises(LookupError):
        directory.set_active("tenant-a", "a-missing", False)
    with pytest.raises(ValueError):
        directory.set_active("tenant-a", "a-lawyer", 0)  # type: ignore[arg-type]
    with pytest.raises(LookupError):
        directory.bind(ISSUER, "sub-new", "tenant-a", "a-missing")
    with pytest.raises(ValueError):
        directory.bind(ISSUER, "sub-a-lawyer", "tenant-a", "a-partner")  # already bound
    with pytest.raises(ValueError):
        directory.bind(ISSUER, "bad\nsubject", "tenant-a", "a-lawyer")
    with pytest.raises(ValueError):
        directory.bind("", "sub", "tenant-a", "a-lawyer")


def test_directory_rejects_non_utc_clock(engine: Engine) -> None:
    directory = IdentityDirectory(engine, clock=lambda: datetime(2026, 10, 13))
    with pytest.raises(ValueError):
        directory.upsert_principal("tenant-a", "x", [])


def test_unsupported_dialect_rejected(verifier: JwtVerifier) -> None:
    class Fake:
        class dialect:  # noqa: N801
            name = "mysql"

    with pytest.raises(ValueError):
        SqlIdentityAdapter(Fake(), verifier)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IdentityDirectory(Fake())  # type: ignore[arg-type]


def test_migration_0004_round_trip(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert {"identity_principals", "identity_bindings"} <= tables
    assert inspect(engine).get_pk_constraint("identity_bindings")["constrained_columns"] == [
        "issuer",
        "subject",
    ]
    for table in (identity_principals, identity_bindings):
        reflected = {c["name"]: c for c in inspect(engine).get_columns(table.name)}
        assert set(reflected) == {c.name for c in table.columns}
        for column in table.columns:
            assert reflected[column.name]["nullable"] == column.nullable
    downgrade(engine, "0003_matter_outcomes")
    assert "identity_bindings" not in inspect(engine).get_table_names()
    assert "matter_mutation_receipts" in inspect(engine).get_table_names()
    upgrade(engine)
    assert "identity_bindings" in inspect(engine).get_table_names()


def test_binding_requires_existing_principal_at_database_level(engine: Engine) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            identity_bindings.insert().values(
                issuer=ISSUER,
                subject="orphan",
                tenant_id="tenant-a",
                actor_id="a-ghost",
                created_at=datetime.now().astimezone(),
            )
        )


# ----------------------------------------------------------------------------- provisioning


def _settings(db_url: str, env: str = "test") -> Settings:
    return Settings(_env_file=None, env=env, database_url=db_url)


def test_provision_cli_round_trip(
    db_url: str, engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(db_url)
    assert (
        provision(
            [
                "principal",
                "--tenant",
                "tenant-c",
                "--actor",
                "c-lawyer",
                "--roles",
                "lawyer, partner",
                "--display-name",
                "Synthetic Lawyer C",
            ],
            settings,
        )
        == 0
    )
    assert (
        provision(
            [
                "bind",
                "--issuer",
                ISSUER,
                "--subject",
                "sub-c",
                "--tenant",
                "tenant-c",
                "--actor",
                "c-lawyer",
            ],
            settings,
        )
        == 0
    )
    assert provision(["deactivate", "--tenant", "tenant-c", "--actor", "c-lawyer"], settings) == 0
    assert provision(["activate", "--tenant", "tenant-c", "--actor", "c-lawyer"], settings) == 0
    assert provision(["unbind", "--issuer", ISSUER, "--subject", "sub-c"], settings) == 0
    assert provision(["unbind", "--issuer", ISSUER, "--subject", "sub-c"], settings) == 1
    out = capsys.readouterr()
    assert "Synthetic Lawyer C" not in out.out + out.err
    assert "sub-c" not in out.out + out.err
    with engine.begin() as conn:
        row = conn.execute(
            select(identity_principals).where(identity_principals.c.actor_id == "c-lawyer")
        ).one()
    assert (row.roles, row.active, row.revision) == ("lawyer,partner", True, 3)


def test_provision_cli_rejections(
    db_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        provision(["deactivate", "--tenant", "t", "--actor", "a"], _settings(db_url, "production"))
        == 2
    )
    assert (
        provision(["deactivate", "--tenant", "tenant-a", "--actor", "nobody"], _settings(db_url))
        == 1
    )
    assert (
        provision(["principal", "--tenant", "bad tenant", "--actor", "a"], _settings(db_url)) == 1
    )
    empty = _settings(f"sqlite:///{tmp_path / 'blank.db'}")
    assert provision(["principal", "--tenant", "t", "--actor", "a"], empty) == 1
    err = capsys.readouterr().err
    assert "rejected" in err and "bad tenant" not in err
