"""Persistence for journal entries and the per-day rollup log."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select

from app.models.journal import DailyLog, JournalEntry
from app.repositories.base import UserScopedRepository
from app.schemas.common import Pagination


class JournalRepository(UserScopedRepository[JournalEntry]):
    """Journal queries."""

    model = JournalEntry

    def get_for_date(self, entry_date: date) -> JournalEntry | None:
        """Return the entry for one date."""
        statement = self.scoped().where(JournalEntry.entry_date == entry_date)
        return self.session.scalars(statement).first()

    def list_between(self, start: date, end: date) -> list[JournalEntry]:
        """Return entries inside an inclusive range, oldest first."""
        statement = (
            self.scoped()
            .where(JournalEntry.entry_date >= start, JournalEntry.entry_date <= end)
            .order_by(JournalEntry.entry_date)
        )
        return list(self.session.scalars(statement))

    def page(self, pagination: Pagination) -> tuple[list[JournalEntry], int]:
        """One page of journal history, newest first."""
        statement = self.scoped().order_by(JournalEntry.entry_date.desc())
        return self.paginate(statement, pagination)

    def ratings_between(self, start: date, end: date) -> dict[date, tuple[int | None, int | None]]:
        """Return ``(mood, focus)`` per date.

        Two columns, not whole entries: the journal text is the largest
        thing in the database and the score engine has no use for it.
        """
        statement = select(JournalEntry.entry_date, JournalEntry.mood, JournalEntry.focus).where(
            JournalEntry.user_id == self.user_id,
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
        return {day: (mood, focus) for day, mood, focus in self.session.execute(statement)}

    def search_text(self, term: str, pagination: Pagination) -> tuple[list[JournalEntry], int]:
        """Free-text search across the entry's prose fields."""
        pattern = f"%{term.lower()}%"
        statement = self.scoped().where(
            or_(
                func.lower(func.coalesce(JournalEntry.reflection, "")).like(pattern),
                func.lower(func.coalesce(JournalEntry.accomplishments, "")).like(pattern),
                func.lower(func.coalesce(JournalEntry.challenges, "")).like(pattern),
                func.lower(func.coalesce(JournalEntry.gratitude, "")).like(pattern),
                func.lower(func.coalesce(JournalEntry.notes, "")).like(pattern),
            )
        )
        return self.paginate(statement.order_by(JournalEntry.entry_date.desc()), pagination)


class DailyLogRepository(UserScopedRepository[DailyLog]):
    """The per-day rollup row."""

    model = DailyLog

    def get_for_date(self, log_date: date) -> DailyLog | None:
        """Return the rollup for one date."""
        return self.session.scalars(self.scoped().where(DailyLog.log_date == log_date)).first()

    def get_or_create(self, log_date: date) -> DailyLog:
        """Return the rollup for one date, creating it if absent."""
        existing = self.get_for_date(log_date)
        if existing is not None:
            return existing
        return self.add(DailyLog(user_id=self.user_id, log_date=log_date))

    def list_between(self, start: date, end: date) -> list[DailyLog]:
        """Return rollups inside an inclusive range, oldest first."""
        statement = (
            self.scoped()
            .where(DailyLog.log_date >= start, DailyLog.log_date <= end)
            .order_by(DailyLog.log_date)
        )
        return list(self.session.scalars(statement))

    def scores_between(self, start: date, end: date) -> dict[date, float]:
        """Return cached productivity scores keyed by date.

        This is what makes a twelve-month heatmap one query instead of 365
        score computations.
        """
        statement = select(DailyLog.log_date, DailyLog.productivity_score).where(
            DailyLog.user_id == self.user_id,
            DailyLog.log_date >= start,
            DailyLog.log_date <= end,
            DailyLog.productivity_score.isnot(None),
        )
        return {day: float(score) for day, score in self.session.execute(statement)}
