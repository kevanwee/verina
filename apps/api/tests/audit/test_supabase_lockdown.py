"""Supabase Data API lock-down (migration 0006, ADR 008).

Simulates Supabase's ``anon`` / ``authenticated`` roles and their default grants on a disposable
PostgreSQL database, runs the migrations, and proves those roles cannot read or write any Verina
table while the application (table owner) still can.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError

from tests.audit.conftest import started
from verina.audit import SqlAuditStore
from verina.db import downgrade, upgrade

pytestmark = pytest.mark.story("US-47")

API_ROLES = ("anon", "authenticated")


@pytest.fixture
def supabase_like(engine: Engine) -> Iterator[Engine]:
    if engine.dialect.name != "postgresql":
        pytest.skip("Data API lock-down is PostgreSQL-only (no-op on SQLite)")
    created: list[str] = []
    with engine.begin() as conn:
        for role in API_ROLES:
            exists = conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
            ).first()
            if exists is None:
                conn.execute(text(f"CREATE ROLE {role} NOLOGIN NOINHERIT"))
                created.append(role)
        conn.execute(text("GRANT USAGE ON SCHEMA public TO anon, authenticated"))
        # What Supabase does: every new table/function in public is granted to the API roles.
        for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            conn.execute(
                text(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON {kind} "
                    "TO anon, authenticated"
                )
            )
    try:
        downgrade(engine)
        upgrade(engine)
        yield engine
    finally:
        downgrade(engine)
        with engine.begin() as conn:
            for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                conn.execute(
                    text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON {kind} "
                        "FROM anon, authenticated"
                    )
                )
            conn.execute(text("REVOKE USAGE ON SCHEMA public FROM anon, authenticated"))
            for role in created:
                conn.execute(text(f"DROP OWNED BY {role}"))
                conn.execute(text(f"DROP ROLE {role}"))
        upgrade(engine)


def _tables(engine: Engine) -> list[str]:
    return sorted(set(inspect(engine).get_table_names()) | {"alembic_version"})


def test_api_roles_cannot_select_or_insert_any_verina_table(supabase_like: Engine) -> None:
    tables = _tables(supabase_like)
    assert {"organizations", "platform_admins", "audit_events", "matters"} <= set(tables)
    for role in API_ROLES:
        for table in tables:
            # Table names come from the database catalogue, never from input.
            for statement in (
                f"SELECT * FROM {table} LIMIT 1",  # noqa: S608
                f"INSERT INTO {table} DEFAULT VALUES",
                f"DELETE FROM {table}",  # noqa: S608
            ):
                with pytest.raises(DBAPIError) as denied, supabase_like.begin() as conn:
                    conn.execute(text(f"SET LOCAL ROLE {role}"))
                    conn.execute(text(statement))
                assert getattr(denied.value.orig, "sqlstate", None) == "42501", (role, statement)


def test_rls_enabled_not_forced_and_owner_still_works(supabase_like: Engine) -> None:
    with supabase_like.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                "WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind = 'r'"
            )
        ).all()
        privileges = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee IN ('anon', 'authenticated') AND table_schema = current_schema()"
            )
        ).scalar_one()
    by_name = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}
    assert set(_tables(supabase_like)) <= set(by_name)
    assert all(by_name[t] == (True, False) for t in _tables(supabase_like)), by_name
    assert privileges == 0
    store = SqlAuditStore(supabase_like)
    store.append("tenant-owner", started())
    assert store.verify_chain("tenant-owner").ok


def test_future_tables_are_not_granted_to_api_roles(supabase_like: Engine) -> None:
    with supabase_like.begin() as conn:
        conn.execute(text("CREATE TABLE verina_probe_future (x integer)"))
        try:
            granted = conn.execute(
                text("SELECT has_table_privilege('anon', 'verina_probe_future', 'SELECT')")
            ).scalar_one()
        finally:
            conn.execute(text("DROP TABLE verina_probe_future"))
    assert granted is False


def test_api_roles_cannot_execute_verina_functions(supabase_like: Engine) -> None:
    with supabase_like.begin() as conn:
        allowed = conn.execute(
            text("SELECT has_function_privilege('anon', 'verina_audit_reject_change()', 'EXECUTE')")
        ).scalar_one()
    assert allowed is False
    with pytest.raises(DBAPIError) as denied, supabase_like.begin() as conn:
        conn.execute(text("SET LOCAL ROLE anon"))
        conn.execute(text("SELECT verina_audit_reject_change()"))
    assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    # The append-only triggers still fire for the owner.
    SqlAuditStore(supabase_like).append("tenant-trigger", started())
    with pytest.raises(DBAPIError) as rejected, supabase_like.begin() as conn:
        conn.execute(text("UPDATE audit_events SET actor = 'changed'"))
    assert "append-only" in str(rejected.value.orig)


def test_downgrade_disables_rls_without_regranting(supabase_like: Engine) -> None:
    downgrade(supabase_like, "0005_accounts_and_organizations")
    with supabase_like.begin() as conn:
        forced = conn.execute(
            text(
                "SELECT bool_or(relrowsecurity) FROM pg_class "
                "WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r'"
            )
        ).scalar_one()
        privileges = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee IN ('anon', 'authenticated') AND table_schema = current_schema()"
            )
        ).scalar_one()
    assert forced is False and privileges == 0
    upgrade(supabase_like)


def test_lockdown_covers_every_verina_table() -> None:
    """A new table needs its own lock-down migration; this fails until one is added."""
    from alembic.script import ScriptDirectory

    from verina.access import directory_schema, mutations, sql_identity  # noqa: F401
    from verina.access.sql_repository import metadata as matter_metadata
    from verina.audit.schema import metadata as audit_metadata
    from verina.db import alembic_config

    script = ScriptDirectory.from_config(alembic_config())
    module = script.get_revision("0006_supabase_data_api_lockdown").module
    declared = set(audit_metadata.tables) | set(matter_metadata.tables) | {"alembic_version"}
    assert set(module.VERINA_TABLES) == declared


def test_lockdown_is_a_no_op_without_supabase_roles(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        downgrade(engine, "0005_accounts_and_organizations")
        upgrade(engine)
        return
    with engine.begin() as conn:
        present = conn.execute(
            text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        ).scalar_one()
        if present:
            pytest.skip("this database already has Supabase-like roles")
        enabled = conn.execute(
            text(
                "SELECT bool_or(relrowsecurity) FROM pg_class "
                "WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r'"
            )
        ).scalar_one()
    assert enabled is False
