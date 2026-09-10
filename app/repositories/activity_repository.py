"""Persistence for logged physical activity."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.models.activity import Activity
from app.models.category import Category
from app.repositories.base import UserScopedRepository
from app.schemas.common import Pagination


class ActivityRepository(UserScopedRepository[Activity]):
    """Activity queries."""

    model = Activity

    def list_for_day(self, day: date) -> list[Activity]:
        """Return one day's activities, with their categories preloaded.

        ``joinedload`` here is not an optimisation detail - without it,
        rendering ten activities with their category names is eleven
        queries.
        """
        statement = (
            self.scoped()
            .where(Activity.log_date == day)
            .options(joinedload(Activity.category))
            .order_by(Activity.started_at.is_(None), Activity.started_at)
        )
        return list(self.session.scalars(statement))

    def list_between(
        self, start: date, end: date, *, category_ids: Sequence[int] | None = None
    ) -> list[Activity]:
        """Return activities inside an inclusive range, with categories."""
        statement = (
            self.scoped()
            .where(Activity.log_date >= start, Activity.log_date <= end)
            .options(joinedload(Activity.category))
            .order_by(Activity.log_date)
        )
        if category_ids:
            statement = statement.where(Activity.category_id.in_(category_ids))
        return list(self.session.scalars(statement))

    def page(self, pagination: Pagination) -> tuple[list[Activity], int]:
        """Return one page of activity history, newest first."""
        statement = (
            self.scoped()
            .options(joinedload(Activity.category))
            .order_by(Activity.log_date.desc(), Activity.id.desc())
        )
        return self.paginate(statement, pagination)

    def minutes_per_day(self, start: date, end: date) -> dict[date, float]:
        """Total activity minutes per day, aggregated by the database."""
        statement = (
            select(Activity.log_date, func.sum(Activity.duration_minutes))
            .where(
                Activity.user_id == self.user_id,
                Activity.log_date >= start,
                Activity.log_date <= end,
            )
            .group_by(Activity.log_date)
        )
        return {day: float(minutes or 0.0) for day, minutes in self.session.execute(statement)}

    def minutes_by_category(self, start: date, end: date) -> dict[str, float]:
        """Total activity minutes per category name."""
        statement = (
            select(Category.name, func.sum(Activity.duration_minutes))
            .join(Category, Category.id == Activity.category_id)
            .where(
                Activity.user_id == self.user_id,
                Activity.log_date >= start,
                Activity.log_date <= end,
            )
            .group_by(Category.name)
            .order_by(func.sum(Activity.duration_minutes).desc())
        )
        return {name: float(minutes or 0.0) for name, minutes in self.session.execute(statement)}

    def total_minutes(self, start: date, end: date) -> float:
        """Total activity minutes across a range."""
        statement = select(func.sum(Activity.duration_minutes)).where(
            Activity.user_id == self.user_id,
            Activity.log_date >= start,
            Activity.log_date <= end,
        )
        return float(self.session.scalar(statement) or 0.0)

    def active_days(self, start: date, end: date) -> int:
        """Count distinct days with at least one activity."""
        statement = select(func.count(func.distinct(Activity.log_date))).where(
            Activity.user_id == self.user_id,
            Activity.log_date >= start,
            Activity.log_date <= end,
        )
        return int(self.session.scalar(statement) or 0)
