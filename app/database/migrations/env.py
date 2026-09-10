"""Alembic environment.

Two things here are load-bearing:

* the URL comes from :mod:`app.config.settings`, never from ``alembic.ini``,
  so migrations cannot run against a different database than the app;
* ``render_as_batch`` is on, because SQLite cannot ``ALTER`` a column and
  Alembic has to rebuild the table instead. Without it, the second schema
  change of this project's life would fail.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from app.config.settings import get_settings
from app.database.base import Base

# Importing the models registers every table on Base.metadata, which is what
# autogenerate compares the database against.
import app.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers` defaults to True, which switches off every
    # logger not named in alembic.ini - including the whole `habit_tracker`
    # tree. Startup runs migrations, so without this every application log
    # line after startup vanished silently.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """Return the URL to migrate, preferring an explicit override."""
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return get_settings().resolved_database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    connectable = config.attributes.get("connection", None)
    if connectable is None:
        engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connectable)


def _run(connection: Connection) -> None:
    """Configure the context against a connection and run."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
