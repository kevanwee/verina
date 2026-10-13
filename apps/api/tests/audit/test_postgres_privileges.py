"""Restricted-role database evidence, not production identity provisioning."""

import secrets
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.audit.conftest import started
from verina.audit import SqlAuditStore
from verina.db import make_engine


def test_postgres_application_role_can_append_but_cannot_change_history(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL privilege evidence requires the CI PostgreSQL service")

    # UUID/hex values only, quoted with the PostgreSQL dialect; no user input in DDL.
    role = "verina_test_app_" + uuid4().hex
    quoted_role = engine.dialect.identifier_preparer.quote(role)
    password = secrets.token_hex(24)
    application: Engine | None = None
    created = False
    try:
        with engine.begin() as bootstrap:
            bootstrap.execute(
                text(
                    f"CREATE ROLE {quoted_role} LOGIN PASSWORD '{password}' "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                )
            )
            bootstrap.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_role}"))
            bootstrap.execute(text(f"GRANT SELECT, INSERT ON audit_events TO {quoted_role}"))
            bootstrap.execute(
                text(f"GRANT SELECT, INSERT, UPDATE ON audit_chain_head TO {quoted_role}")
            )
        created = True

        application = make_engine(
            engine.url.set(username=role, password=password).render_as_string(hide_password=False)
        )
        with application.connect() as session:
            assert session.execute(text("SELECT current_user")).scalar_one() == role
            flags = session.execute(
                text(
                    "SELECT rolsuper, rolcreaterole, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).one()
            assert tuple(flags) == (False, False, False)

        store = SqlAuditStore(application)
        store.append("tenant-restricted", started())
        store.append("tenant-restricted", started())
        assert store.verify_chain("tenant-restricted").ok
        assert len(store.events("tenant-restricted")) == 2

        forbidden = (
            "UPDATE audit_events SET actor='changed'",
            "DELETE FROM audit_events",
            "TRUNCATE audit_events",
            "ALTER TABLE audit_events DISABLE TRIGGER USER",
            "DROP TRIGGER audit_events_append_only ON audit_events",
            "DROP TABLE audit_events",
        )
        for statement in forbidden:
            with pytest.raises(DBAPIError) as failure, application.begin() as session:
                session.execute(text(statement))
            # Assert permission denial, not syntax failure or a bootstrap trigger exception.
            assert getattr(failure.value.orig, "sqlstate", None) == "42501"
        assert store.verify_chain("tenant-restricted").ok
        assert store.verify_chain("tenant-restricted").event_count == 2
    finally:
        if application is not None:
            application.dispose()
        if created:
            with engine.begin() as bootstrap:
                bootstrap.execute(text(f"DROP OWNED BY {quoted_role}"))
                bootstrap.execute(text(f"DROP ROLE {quoted_role}"))
