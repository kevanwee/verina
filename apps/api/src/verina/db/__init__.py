"""Database engine factory and Alembic helpers (ADR 004).

SQLite for local development and unit tests; PostgreSQL (psycopg 3) in CI. The URL comes
from ``VERINA_DATABASE_URL``. Schema changes go through Alembic only
(``verina/db/migrations``); application code never calls ``metadata.create_all``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

SQLITE_BUSY_TIMEOUT_SECONDS = 30.0

_ACTIVE_CONNECTION: ContextVar[Connection | None] = ContextVar(
    "verina_active_connection", default=None
)


@contextmanager
def bind_connection(conn: Connection) -> Iterator[Connection]:
    """Expose ``conn`` to same-engine readers running inside its transaction.

    A repository transaction binds its connection so that a collaborator called from
    inside it (the identity directory re-check in a durable mutation) reads on the *same*
    transaction instead of opening a second one. On SQLite a second ``BEGIN IMMEDIATE``
    would wait for the first; on PostgreSQL the shared transaction lets the directory row
    be locked until the mutation commits. The binding is task/thread-local (``ContextVar``).
    """
    token = _ACTIVE_CONNECTION.set(conn)
    try:
        yield conn
    finally:
        _ACTIVE_CONNECTION.reset(token)


def active_connection(engine: Engine) -> Connection | None:
    """The bound connection when it belongs to ``engine`` and its transaction is open."""
    conn = _ACTIVE_CONNECTION.get()
    if conn is None or conn.engine is not engine or not conn.in_transaction():
        return None
    return conn


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
