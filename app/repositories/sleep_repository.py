"""Persistence for sleep records."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.models.sleep import SleepRecord
from app.repositories.base import UserScopedRepository
from app.schemas.common import Pagination


class SleepRepository(UserScopedRepository[SleepRecord]):
    """Sleep queries."""

    model = SleepRecord

    def get_for_date(self, log_date: date) -> SleepRecord | None:
        """Return the night filed under one date."""
        return self.session.scalars(self.scoped().where(SleepRecord.log_date == log_date)).first()

    def list_between(self, start: date, end: date) -> list[SleepRecord]:
        """Return nights inside an inclusive range, oldest first."""
        statement = (
            self.scoped()
            .where(SleepRecord.log_date >= start, SleepRecord.log_date <= end)
            .order_by(SleepRecord.log_date)
        )
        return list(self.session.scalars(statement))

    def list_recent(self, *, limit: int = 30) -> list[SleepRecord]:
        """Return the most recent nights, newest first."""
        statement = self.scoped().order_by(SleepRecord.log_date.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def page(self, pagination: Pagination) -> tuple[list[SleepRecord], int]:
        """Return one page of sleep history, newest first."""
        statement = self.scoped().order_by(SleepRecord.log_date.desc())
        return self.paginate(statement, pagination)

    def duration_per_day(self, start: date, end: date) -> dict[date, float]:
        """Return sleep minutes keyed by date.

        Reads two columns rather than whole rows: the heatmap and the
        weekly review both want the number, not the record.
        """
        statement = select(SleepRecord.log_date, SleepRecord.duration_minutes).where(
            SleepRecord.user_id == self.user_id,
            SleepRecord.log_date >= start,
            SleepRecord.log_date <= end,
        )
        return {day: float(minutes) for day, minutes in self.session.execute(statement)}

    def average_minutes(self, start: date, end: date) -> float | None:
        """Average nightly sleep across a range, computed by the database."""
        statement = select(func.avg(SleepRecord.duration_minutes)).where(
            SleepRecord.user_id == self.user_id,
            SleepRecord.log_date >= start,
            SleepRecord.log_date <= end,
        )
        value = self.session.scalar(statement)
        return float(value) if value is not None else None

    def count_below(self, start: date, end: date, target_minutes: float) -> int:
        """Count nights shorter than the target inside a range."""
        return self.count_owned(
            SleepRecord.log_date >= start,
            SleepRecord.log_date <= end,
            SleepRecord.duration_minutes < target_minutes,
        )
