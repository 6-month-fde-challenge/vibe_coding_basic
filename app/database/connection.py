"""Engine and session management.

Everything that knows what a database connection *is* lives here. The rest of
the application receives a :class:`Database` (or, below the service layer, a
plain ``Session``) and never constructs one.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config.settings import PROJECT_ROOT, Settings, get_settings
from app.core.errors import DatabaseError
from app.core.logging_config import get_logger

logger = get_logger(__name__)

#: Wait this long for a competing writer before raising "database is locked".
_SQLITE_BUSY_TIMEOUT_MS = 5_000


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    """Apply the SQLite pragmas this application depends on.

    ``foreign_keys`` is OFF by default in SQLite, which silently turns every
    ``ON DELETE CASCADE`` in the schema into a no-op. WAL mode lets the
    Streamlit UI read while a write is in flight instead of blocking.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Build a SQLAlchemy engine from settings.

    Args:
        settings: Configuration to read the URL and echo flag from.

    Returns:
        A configured engine. For SQLite the connection is shared across
        threads, because Streamlit runs each session on its own thread.
    """
    settings = settings or get_settings()
    url = settings.resolved_database_url
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "future": True}

    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # An in-memory database lives inside its connection; a pool that
            # opens a second one would see an empty schema.
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True

    engine = create_engine(url, **kwargs)
    if settings.is_sqlite:
        event.listen(engine, "connect", _configure_sqlite)

    logger.debug("Engine created for %s", engine.url.render_as_string(hide_password=True))
    return engine


class Database:
    """Owns the engine and hands out sessions.

    One instance per process. Streamlit caches it as a *resource*, never as
    data, because a session must not be shared between reruns.
    """

    def __init__(self, settings: Settings | None = None, engine: Engine | None = None) -> None:
        self._settings = settings or get_settings()
        self.engine: Engine = engine or create_db_engine(self._settings)
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
            future=True,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session, committing on success and rolling back on error.

        The ``finally`` clause is the point: a session that is neither
        committed nor closed holds a SQLite write lock, and the next page
        load then fails with "database is locked" far from the real cause.
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Database operation failed, rolled back")
            raise DatabaseError(
                "Database operation failed", details={"cause": type(exc).__name__}
            ) from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        """Close every pooled connection. Used by tests and by backup."""
        self.engine.dispose()

    def healthcheck(self) -> bool:
        """Return whether a trivial query succeeds against the database."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            logger.exception("Database healthcheck failed")
            return False
        return True

    @property
    def sqlite_path(self) -> Path | None:
        """Filesystem path of the SQLite file, or ``None`` for other backends."""
        if self.engine.dialect.name != "sqlite":
            return None
        database = self.engine.url.database
        if not database or database == ":memory:":
            return None
        return Path(database)


def alembic_config_path() -> Path:
    """Return the path to ``alembic.ini``."""
    return PROJECT_ROOT / "alembic.ini"


def run_migrations(database: Database) -> None:
    """Upgrade the database to the latest Alembic revision.

    Called on application start so a fresh clone needs one command, not two.
    Alembic is imported lazily because it pulls in a fair amount of machinery
    that a test using an in-memory schema does not need.
    """
    from alembic import command
    from alembic.config import Config

    config_path = alembic_config_path()
    if not config_path.exists():
        raise DatabaseError(
            "alembic.ini is missing",
            details={"expected_at": str(config_path)},
            user_hint="The migration configuration is missing from the project.",
        )

    config = Config(str(config_path))
    config.set_main_option("script_location", str(PROJECT_ROOT / "app" / "database" / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", database.engine.url.render_as_string(hide_password=False)
    )
    logger.info("Applying database migrations")
    command.upgrade(config, "head")
    logger.info("Database is at the latest revision")


def create_all(database: Database) -> None:
    """Create the schema directly from the models, bypassing Alembic.

    Only for tests and throwaway databases. Application startup goes through
    :func:`run_migrations` so that development and production share one
    definition of the schema.
    """
    from app import models  # noqa: F401 - registers every table on the metadata
    from app.database.base import Base

    Base.metadata.create_all(database.engine)
