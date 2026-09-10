"""Persistence for habits and habit logs."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date

from sqlalchemy import func, select

from app.models.habit import Habit, HabitLog
from app.repositories.base import UserScopedRepository

#: Rows fetched per round trip when walking completion dates backwards.
#: Large enough that a typical streak is answered by one query, small enough
#: that a ten-year history is never loaded to answer "am I on a streak".
STREAK_PAGE_SIZE = 64


class HabitRepository(UserScopedRepository[Habit]):
    """Habit definitions and their logs.

    The interesting method here is :meth:`iter_completed_dates_desc`. It is
    what lets the streak engine keep its promise not to scan the whole
    history: the query is issued in pages and the generator stops pulling
    them the moment the caller stops asking.
    """

    model = Habit

    # -- definitions -------------------------------------------------------

    def list_active(self) -> list[Habit]:
        """Return active habits in display order."""
        statement = (
            self.scoped().where(Habit.is_active.is_(True)).order_by(Habit.sort_order, Habit.name)
        )
        return list(self.session.scalars(statement))

    def list_all_habits(self, *, include_inactive: bool = True) -> list[Habit]:
        """Return every habit, optionally including retired ones."""
        statement = self.scoped()
        if not include_inactive:
            statement = statement.where(Habit.is_active.is_(True))
        return list(self.session.scalars(statement.order_by(Habit.sort_order, Habit.name)))

    def get_by_name(self, name: str) -> Habit | None:
        """Return a habit by exact name."""
        return self.session.scalars(self.scoped().where(Habit.name == name)).first()

    def name_exists(self, name: str, *, exclude_id: int | None = None) -> bool:
        """Whether the profile already has a habit with this name."""
        statement = select(Habit.id).where(Habit.user_id == self.user_id, Habit.name == name)
        if exclude_id is not None:
            statement = statement.where(Habit.id != exclude_id)
        return self.session.scalars(statement.limit(1)).first() is not None

    # -- logs --------------------------------------------------------------

    def get_log(self, habit_id: int, log_date: date) -> HabitLog | None:
        """Return one habit's log for one day."""
        statement = select(HabitLog).where(
            HabitLog.habit_id == habit_id, HabitLog.log_date == log_date
        )
        return self.session.scalars(statement).first()

    def add_log(self, log: HabitLog) -> HabitLog:
        """Insert a habit log."""
        self.session.add(log)
        self.session.flush()
        return log

    def delete_log(self, log: HabitLog) -> None:
        """Remove a habit log."""
        self.session.delete(log)
        self.session.flush()

    def logs_for_day(self, log_date: date) -> dict[int, HabitLog]:
        """Return every log for one day, keyed by habit id.

        One query for the whole dashboard rather than one per habit - the
        N+1 the brief calls out by name.
        """
        statement = (
            select(HabitLog)
            .join(Habit, Habit.id == HabitLog.habit_id)
            .where(Habit.user_id == self.user_id, HabitLog.log_date == log_date)
        )
        return {log.habit_id: log for log in self.session.scalars(statement)}

    def logs_between(
        self, start: date, end: date, *, habit_ids: Sequence[int] | None = None
    ) -> list[HabitLog]:
        """Return logs inside an inclusive date range."""
        statement = (
            select(HabitLog)
            .join(Habit, Habit.id == HabitLog.habit_id)
            .where(
                Habit.user_id == self.user_id,
                HabitLog.log_date >= start,
                HabitLog.log_date <= end,
            )
        )
        if habit_ids:
            statement = statement.where(HabitLog.habit_id.in_(habit_ids))
        return list(self.session.scalars(statement.order_by(HabitLog.log_date)))

    def completed_dates(self, habit_id: int, *, since: date | None = None) -> list[date]:
        """Return every completion date for one habit, oldest first.

        Selects the date column alone, which the
        ``ix_habit_log_habit_date`` index can satisfy without touching the
        table. Needed in full only by the longest-streak calculation.
        """
        statement = select(HabitLog.log_date).where(
            HabitLog.habit_id == habit_id, HabitLog.completed.is_(True)
        )
        if since is not None:
            statement = statement.where(HabitLog.log_date >= since)
        return list(self.session.scalars(statement.order_by(HabitLog.log_date)))

    def iter_completed_dates_desc(
        self,
        habit_id: int,
        *,
        on_or_before: date | None = None,
        page_size: int = STREAK_PAGE_SIZE,
    ) -> Iterator[date]:
        """Yield completion dates newest first, fetching them in pages.

        This is the lazy source the current-streak walk consumes. A habit
        with four years of history and a two-day streak costs exactly one
        query of :data:`STREAK_PAGE_SIZE` rows, because the consumer stops
        iterating at the first gap and no further page is ever requested.

        Args:
            habit_id: The habit to read.
            on_or_before: Ignore completions after this date.
            page_size: Rows per round trip.

        Yields:
            Completion dates, descending.
        """
        offset = 0
        while True:
            statement = select(HabitLog.log_date).where(
                HabitLog.habit_id == habit_id, HabitLog.completed.is_(True)
            )
            if on_or_before is not None:
                statement = statement.where(HabitLog.log_date <= on_or_before)
            statement = statement.order_by(HabitLog.log_date.desc()).limit(page_size).offset(offset)

            page = list(self.session.scalars(statement))
            if not page:
                return
            yield from page
            if len(page) < page_size:
                return
            offset += page_size

    # -- aggregates --------------------------------------------------------

    def completions_per_day(self, start: date, end: date) -> dict[date, int]:
        """Count completed habit logs per day, across all habits."""
        statement = (
            select(HabitLog.log_date, func.count())
            .join(Habit, Habit.id == HabitLog.habit_id)
            .where(
                Habit.user_id == self.user_id,
                HabitLog.completed.is_(True),
                HabitLog.log_date >= start,
                HabitLog.log_date <= end,
            )
            .group_by(HabitLog.log_date)
        )
        return dict(self.session.execute(statement).tuples().all())

    def completions_per_habit(self, start: date, end: date) -> dict[int, int]:
        """Count completed logs per habit inside a range."""
        statement = (
            select(HabitLog.habit_id, func.count())
            .join(Habit, Habit.id == HabitLog.habit_id)
            .where(
                Habit.user_id == self.user_id,
                HabitLog.completed.is_(True),
                HabitLog.log_date >= start,
                HabitLog.log_date <= end,
            )
            .group_by(HabitLog.habit_id)
        )
        return dict(self.session.execute(statement).tuples().all())

    def consecutive_misses(self, habit_id: int, today: date, *, lookback: int = 30) -> int:
        """Count expected-but-unlogged days immediately before today.

        Bounded by ``lookback`` because this only feeds a nudge, and a nudge
        does not justify reading a whole history.
        """
        statement = (
            select(HabitLog.log_date)
            .where(
                HabitLog.habit_id == habit_id,
                HabitLog.completed.is_(True),
                HabitLog.log_date < today,
            )
            .order_by(HabitLog.log_date.desc())
            .limit(1)
        )
        last = self.session.scalars(statement).first()
        if last is None:
            return lookback
        return min(lookback, max(0, (today - last).days - 1))
