"""Alembic environment for Verina.

Connection precedence: a connection passed by :func:`verina.db.upgrade` (tests, app code),
then ``sqlalchemy.url`` from the Alembic config, then ``VERINA_DATABASE_URL`` via settings.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from verina.access import directory_schema as _directory  # noqa: F401 - registers accounts
from verina.access import mutations as _mutations  # noqa: F401 - registers receipt table
from verina.access import sql_identity as _sql_identity  # noqa: F401 - registers directory
from verina.access.sql_repository import metadata as matter_metadata
from verina.audit.schema import metadata
from verina.config import get_settings
from verina.db import make_engine

config = context.config
if config.config_file_name is not None:  # CLI use; programmatic runs keep app logging
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = [metadata, matter_metadata]


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            _run(conn)
            conn.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
