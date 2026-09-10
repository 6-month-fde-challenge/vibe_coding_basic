"""Persistence for tracked time."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.models.category import Category
from app.models.time_entry import TimeEntry
from app.repositories.base import UserScopedRepository
from app.schemas.activity import TimeEntryFilter
from app.schemas.common import Pagination


class TimeEntryRepository(UserScopedRepository[TimeEntry]):
    """Time-entry queries.

    This is the table that grows fastest, so every read here is either
    aggregated in the database or bounded by a date range and a page.
    """

    model = TimeEntry

    def list_for_day(self, day: date) -> list[TimeEntry]:
        """Return one day's entries, categories preloaded."""
        statement = (
            self.scoped()
            .where(TimeEntry.log_date == day)
            .options(joinedload(TimeEntry.category))
            .order_by(TimeEntry.started_at.is_(None), TimeEntry.started_at, TimeEntry.id)
        )
        return list(self.session.scalars(statement))

    def list_between(
        self, start: date, end: date, *, category_ids: Sequence[int] | None = None
    ) -> list[TimeEntry]:
        """Return entries inside an inclusive range."""
        statement = (
            self.scoped()
            .where(TimeEntry.log_date >= start, TimeEntry.log_date <= end)
            .options(joinedload(TimeEntry.category))
            .order_by(TimeEntry.log_date)
        )
        if category_ids:
            statement = statement.where(TimeEntry.category_id.in_(category_ids))
        return list(self.session.scalars(statement))

    def search(self, criteria: TimeEntryFilter) -> tuple[list[TimeEntry], int]:
        """Filtered, paginated history for the time-tracking page."""
        statement = self.scoped().options(joinedload(TimeEntry.category))
        if criteria.date_from:
            statement = statement.where(TimeEntry.log_date >= criteria.date_from)
        if criteria.date_to:
            statement = statement.where(TimeEntry.log_date <= criteria.date_to)
        if criteria.category_ids:
            statement = statement.where(TimeEntry.category_id.in_(criteria.category_ids))
        if criteria.search:
            pattern = f"%{criteria.search.lower()}%"
            statement = statement.where(
                or_(func.lower(func.coalesce(TimeEntry.description, "")).like(pattern))
            )
        statement = statement.order_by(TimeEntry.log_date.desc(), TimeEntry.id.desc())
        return self.paginate(statement, criteria.pagination)

    def page(self, pagination: Pagination) -> tuple[list[TimeEntry], int]:
        """One page of history, newest first."""
        return self.search(TimeEntryFilter(pagination=pagination))

    # -- aggregates --------------------------------------------------------

    def minutes_by_category(self, start: date, end: date) -> list[tuple[int, str, bool, float]]:
        """Total minutes per category inside a range.

        Returns:
            Tuples of ``(category_id, name, is_productive, minutes)``,
            largest first. Everything the allocation chart needs, in one
            grouped query.
        """
        statement = (
            select(
                Category.id,
                Category.name,
                Category.is_productive,
                func.sum(TimeEntry.duration_minutes),
            )
            .join(Category, Category.id == TimeEntry.category_id)
            .where(
                TimeEntry.user_id == self.user_id,
                TimeEntry.log_date >= start,
                TimeEntry.log_date <= end,
            )
            .group_by(Category.id, Category.name, Category.is_productive)
            .order_by(func.sum(TimeEntry.duration_minutes).desc())
        )
        return [
            (category_id, name, bool(productive), float(minutes or 0.0))
            for category_id, name, productive, minutes in self.session.execute(statement)
        ]

    def minutes_per_day(self, start: date, end: date) -> dict[date, float]:
        """Total tracked minutes per day."""
        statement = (
            select(TimeEntry.log_date, func.sum(TimeEntry.duration_minutes))
            .where(
                TimeEntry.user_id == self.user_id,
                TimeEntry.log_date >= start,
                TimeEntry.log_date <= end,
            )
            .group_by(TimeEntry.log_date)
        )
        return {day: float(minutes or 0.0) for day, minutes in self.session.execute(statement)}

    def minutes_per_day_for_categories(
        self, start: date, end: date, category_ids: Sequence[int]
    ) -> dict[date, float]:
        """Total minutes per day, restricted to some categories."""
        if not category_ids:
            return {}
        statement = (
            select(TimeEntry.log_date, func.sum(TimeEntry.duration_minutes))
            .where(
                TimeEntry.user_id == self.user_id,
                TimeEntry.log_date >= start,
                TimeEntry.log_date <= end,
                TimeEntry.category_id.in_(category_ids),
            )
            .group_by(TimeEntry.log_date)
        )
        return {day: float(minutes or 0.0) for day, minutes in self.session.execute(statement)}

    def total_minutes_for_categories(
        self, start: date, end: date, category_ids: Sequence[int]
    ) -> float:
        """Total minutes across a range for some categories."""
        if not category_ids:
            return 0.0
        statement = select(func.sum(TimeEntry.duration_minutes)).where(
            TimeEntry.user_id == self.user_id,
            TimeEntry.log_date >= start,
            TimeEntry.log_date <= end,
            TimeEntry.category_id.in_(category_ids),
        )
        return float(self.session.scalar(statement) or 0.0)

    def entries_with_interval_on(self, day: date) -> list[TimeEntry]:
        """Return one day's entries that have both a start and an end.

        Only these can overlap, so only these are worth loading when the
        overlap rule is switched on.
        """
        statement = self.scoped().where(
            TimeEntry.log_date == day,
            TimeEntry.started_at.isnot(None),
            TimeEntry.ended_at.isnot(None),
        )
        return list(self.session.scalars(statement))
