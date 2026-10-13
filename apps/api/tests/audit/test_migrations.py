"""Alembic migrations and engine factory for the audit store (D-4)."""

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, inspect

from verina.audit.schema import metadata
from verina.config import Settings
from verina.db import alembic_config, downgrade, make_engine, normalise_url, upgrade

pytestmark = pytest.mark.story("EN-8")

TABLES = {"audit_events", "audit_chain_head"}


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_downgrade_upgrade(engine: Engine) -> None:
    assert _tables(engine) >= TABLES
    downgrade(engine)
    assert not TABLES & _tables(engine)
    upgrade(engine)
    assert _tables(engine) >= TABLES


def test_migration_matches_table_metadata(engine: Engine) -> None:
    inspector = inspect(engine)
    for table in metadata.sorted_tables:
        reflected = {c["name"]: c for c in inspector.get_columns(table.name)}
        assert set(reflected) == {c.name for c in table.columns}
        for column in table.columns:
            assert reflected[column.name]["nullable"] == column.nullable, column
    pk = inspector.get_pk_constraint("audit_events")
    assert pk["constrained_columns"] == ["tenant_id", "sequence"]
    uniques = inspector.get_unique_constraints("audit_events")
    assert any(u["column_names"] == ["event_id"] for u in uniques)


def test_cli_style_config_uses_url(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cli' / 'verina.db'}"
    cfg = alembic_config(url)
    (tmp_path / "cli").mkdir()
    command.upgrade(cfg, "head")
    engine = make_engine(url)
    try:
        assert _tables(engine) >= TABLES
    finally:
        engine.dispose()
    command.downgrade(cfg, "base")


def test_env_falls_back_to_settings_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from verina.config import get_settings

    url = f"sqlite:///{tmp_path / 'settings.db'}"
    monkeypatch.setenv("VERINA_DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config(), "head")
    finally:
        get_settings.cache_clear()
    engine = make_engine(url)
    try:
        assert _tables(engine) >= TABLES
    finally:
        engine.dispose()


def test_offline_sql_generation(capsys: pytest.CaptureFixture[str]) -> None:
    command.upgrade(alembic_config("sqlite:///offline.db"), "head", sql=True)
    sql = capsys.readouterr().out
    assert "CREATE TABLE audit_events" in sql
    assert "CREATE TRIGGER audit_events_no_update" in sql


def test_normalise_url() -> None:
    assert normalise_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalise_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalise_url("postgresql+psycopg://h/db") == "postgresql+psycopg://h/db"
    assert normalise_url("sqlite:///x.db") == "sqlite:///x.db"


def test_postgres_engine_is_created_lazily() -> None:
    engine = make_engine("postgresql://synthetic:synthetic@localhost:1/none")
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


def test_in_memory_sqlite_engine() -> None:
    engine = make_engine("sqlite://")
    upgrade(engine)
    assert _tables(engine) >= TABLES
    engine.dispose()


def test_default_database_url_is_git_ignored_location() -> None:
    url = Settings().database_url
    assert url.startswith("sqlite:///./.data/")
    root = Path(__file__).resolve().parents[4]
    assert ".data/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
