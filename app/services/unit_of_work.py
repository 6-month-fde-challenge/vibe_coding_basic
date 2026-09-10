"""Transaction boundary and repository assembly.

A service opens exactly one unit of work per operation. Inside it, every
repository shares one session, so a habit log and the daily-log row it
updates either both land or neither does.

The ``__exit__`` rolls back on any exception and always closes. That is the
``try/except/finally`` the brief asks for, in the one place where leaving it
out actually costs something: a SQLite session that is neither committed nor
closed keeps a write lock, and the next page load fails with "database is
locked" a long way from the real cause.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import DatabaseError
from app.core.logging_config import get_logger
from app.database.connection import Database
from app.repositories.activity_repository import ActivityRepository
from app.repositories.analytics_repository import AnalyticsRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.goal_repository import GoalRepository, WeeklyGoalRepository
from app.repositories.habit_repository import HabitRepository
from app.repositories.journal_repository import DailyLogRepository, JournalRepository
from app.repositories.profile_repository import (
    BodyMeasurementRepository,
    ProfileRepository,
    SettingsRepository,
)
from app.repositories.sleep_repository import SleepRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.time_entry_repository import TimeEntryRepository

logger = get_logger(__name__)


class UnitOfWork:
    """One session, one transaction, every repository.

    Use it as a context manager::

        with self.unit_of_work() as uow:
            uow.tasks.add(task)
            uow.commit()

    Forgetting :meth:`commit` rolls the work back. That is deliberate: an
    accidental partial write is far more expensive to discover than an
    accidental no-op.
    """

    def __init__(self, session_factory: sessionmaker[Session], user_id: int) -> None:
        self._session_factory = session_factory
        self.user_id = user_id
        self._session: Session | None = None
        self._committed = False

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Self:
        """Open a session and build the repositories against it."""
        self._session = self._session_factory()
        self._committed = False
        session = self._session
        user_id = self.user_id

        self.profiles = ProfileRepository(session)
        self.settings = SettingsRepository(session)
        self.measurements = BodyMeasurementRepository(session, user_id)
        self.categories = CategoryRepository(session, user_id)
        self.tasks = TaskRepository(session, user_id)
        self.habits = HabitRepository(session, user_id)
        self.sleep = SleepRepository(session, user_id)
        self.activities = ActivityRepository(session, user_id)
        self.time_entries = TimeEntryRepository(session, user_id)
        self.goals = GoalRepository(session, user_id)
        self.weekly_goals = WeeklyGoalRepository(session, user_id)
        self.journal = JournalRepository(session, user_id)
        self.daily_logs = DailyLogRepository(session, user_id)
        self.analytics = AnalyticsRepository(session, user_id)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Roll back on error or on forgotten changes, and always close.

        A read-only block is closed rather than rolled back. That matters:
        ``rollback()`` expires every instance the session loaded, so an ORM
        row read inside the block would raise ``DetachedInstanceError`` the
        moment a caller touched it afterwards. ``close()`` detaches the same
        rows but leaves the values they already loaded readable.
        """
        try:
            if exc_type is not None:
                self.rollback()
            elif not self._committed and self._has_pending_changes():
                logger.warning("Unit of work exited with uncommitted changes; rolling back")
                self.rollback()
        finally:
            if self._session is not None:
                self._session.close()
                self._session = None

    def _has_pending_changes(self) -> bool:
        """Whether anything was staged but never committed."""
        if self._session is None:
            return False
        return bool(self._session.new or self._session.dirty or self._session.deleted)

    # -- transaction control ----------------------------------------------

    @property
    def session(self) -> Session:
        """The active session.

        Raises:
            RuntimeError: If accessed outside the ``with`` block.
        """
        if self._session is None:
            msg = "UnitOfWork used outside its context manager."
            raise RuntimeError(msg)
        return self._session

    def commit(self) -> None:
        """Commit the transaction.

        Raises:
            DatabaseError: If the database refuses the write. The session is
                rolled back first, so the caller is never handed a session
                stuck in a failed transaction.
        """
        if self._session is None:  # pragma: no cover - misuse guard
            msg = "UnitOfWork used outside its context manager."
            raise RuntimeError(msg)
        try:
            self._session.commit()
        except SQLAlchemyError as error:
            self._session.rollback()
            logger.exception("Commit failed and was rolled back")
            raise DatabaseError(
                "Could not save the change",
                details={"cause": type(error).__name__},
            ) from error
        self._committed = True

    def rollback(self) -> None:
        """Discard everything staged in this transaction."""
        if self._session is not None:
            self._session.rollback()

    def flush(self) -> None:
        """Push pending changes so generated ids are available."""
        self.session.flush()


class UnitOfWorkFactory:
    """Builds units of work bound to one database and one profile.

    Services depend on this rather than on :class:`Database`, which is what
    lets a test hand them an in-memory database without any of them knowing.
    """

    def __init__(self, database: Database, user_id: int) -> None:
        self.database = database
        self.user_id = user_id

    def __call__(self) -> UnitOfWork:
        """Return a fresh, unopened unit of work."""
        return UnitOfWork(self.database.session_factory, self.user_id)
