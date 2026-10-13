"""Database engine factory and Alembic helpers (ADR 004).

SQLite for local development and unit tests; PostgreSQL (psycopg 3) in CI. The URL comes
from ``VERINA_DATABASE_URL``. Schema changes go through Alembic only
(``verina/db/migrations``); application code never calls ``metadata.create_all``.
"""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

SQLITE_BUSY_TIMEOUT_SECONDS = 30.0


def normalise_url(url: str) -> str:
    """Use the psycopg 3 driver for plain ``postgresql://`` / ``postgres://`` URLs."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def make_engine(url: str, **kwargs: Any) -> Engine:
    """Create an engine with the transaction semantics the audit store relies on.

    SQLite: every transaction starts with ``BEGIN IMMEDIATE``, taking the database write lock
    up front, so concurrent appends serialise instead of racing on the chain head. Parent
    directories of file databases are created. PostgreSQL: default READ COMMITTED; the store
    takes a row lock on the tenant's chain head (``SELECT ... FOR UPDATE``).
    """
    url = normalise_url(url)
    kwargs.setdefault("hide_parameters", True)
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return create_engine(url, pool_pre_ping=True, **kwargs)

    database = parsed.database
    if database and database != ":memory:" and not database.startswith("file:"):
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    connect_args = dict(kwargs.pop("connect_args", {}))
    connect_args.setdefault("check_same_thread", False)
    connect_args.setdefault("timeout", SQLITE_BUSY_TIMEOUT_SECONDS)
    engine = create_engine(url, connect_args=connect_args, **kwargs)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        # Let SQLAlchemy, not the sqlite3 module, decide when transactions begin.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url is not None:
        # ConfigParser interpolation: escape '%' in passwords.
        cfg.set_main_option("sqlalchemy.url", normalise_url(url).replace("%", "%%"))
    return cfg


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Run migrations up to ``revision`` on ``engine``."""
    with engine.connect() as connection:
        cfg = alembic_config()
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)
        connection.commit()


def downgrade(engine: Engine, revision: str = "base") -> None:
    """Run migrations down to ``revision`` on ``engine``."""
    with engine.connect() as connection:
        cfg = alembic_config()
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, revision)
        connection.commit()
