"""Activity business rules."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import ValidationError
from app.core.logging_config import get_logger
from app.core.timeutils import combine_local, minutes_between
from app.domain.activities.summary import ActivityRecord, ActivitySummary, summarize_activities
from app.domain.health.tdee import estimate_activity_calories
from app.models.activity import Activity
from app.models.enums import CategoryKind
from app.schemas.activity import ActivityInput, ActivityRead
from app.schemas.common import DateRange, Page, Pagination
from app.services.base import BaseService
from app.services.unit_of_work import UnitOfWork

logger = get_logger(__name__)


class ActivityService(BaseService):
    """Logging exercise and reporting on it."""

    def list_for_day(self, day: date | None = None) -> list[ActivityRead]:
        """Return one day's activities."""
        with self.uow() as uow:
            return [
                ActivityRead.model_validate(row)
                for row in uow.activities.list_for_day(day or self.today())
            ]

    def list_between(self, period: DateRange) -> list[ActivityRead]:
        """Return activities inside a date range."""
        with self.uow() as uow:
            return [
                ActivityRead.model_validate(row)
                for row in uow.activities.list_between(period.start, period.end)
            ]

    def history(self, pagination: Pagination) -> Page[ActivityRead]:
        """Return activity history, one page at a time."""
        with self.uow() as uow:
            rows, total = uow.activities.page(pagination)
            return Page[ActivityRead](
                items=[ActivityRead.model_validate(row) for row in rows],
                total=total,
                limit=pagination.limit,
                offset=pagination.offset,
            )

    def log(self, payload: ActivityInput) -> ActivityRead:
        """Record a bout of activity.

        Args:
            payload: Either a duration, or a start and end time from which
                one is computed.

        Raises:
            ValidationError: If the date is in the future, the category is
                not an activity category, or the interval is not positive.
        """
        self._reject_future(payload.log_date)
        started_at, ended_at, minutes = self._resolve_interval(payload)

        with self.uow() as uow:
            category = uow.categories.get_or_raise(payload.category_id)
            if category.kind is not CategoryKind.ACTIVITY:
                raise ValidationError(
                    "That category is not an activity type",
                    field="category_id",
                    value=payload.category_id,
                    user_hint=f"{category.name!r} is a {category.kind.value.lower()} category.",
                )

            calories = payload.calories
            if calories is None and payload.estimate_calories:
                calories = self._estimate_calories(uow, minutes, payload)

            activity = Activity(
                user_id=self.user_id,
                log_date=payload.log_date,
                category_id=payload.category_id,
                started_at=started_at,
                ended_at=ended_at,
                duration_minutes=minutes,
                intensity=payload.intensity,
                calories=calories,
                notes=payload.notes,
            )
            uow.activities.add(activity)
            uow.commit()
            logger.info(
                "Activity %s logged on %s (%.0f minutes)",
                activity.id,
                payload.log_date.isoformat(),
                minutes,
            )
            return ActivityRead.model_validate(activity)

    def delete(self, activity_id: int) -> None:
        """Remove a logged activity."""
        with self.uow() as uow:
            activity = uow.activities.get_or_raise(activity_id)
            uow.activities.delete(activity)
            uow.commit()
            logger.info("Activity %s deleted", activity_id)

    def minutes_on(self, day: date) -> float:
        """Total activity minutes on one day."""
        with self.uow() as uow:
            return uow.activities.total_minutes(day, day)

    def summary(self, period: DateRange) -> ActivitySummary:
        """Aggregate activity across a range."""
        with self.uow() as uow:
            rows = uow.activities.list_between(period.start, period.end)
            records = [
                ActivityRecord(
                    log_date=row.log_date,
                    category_id=row.category_id,
                    category_name=row.category.name,
                    duration_minutes=row.duration_minutes,
                    intensity=row.intensity,
                    calories=row.calories,
                )
                for row in rows
            ]
        return summarize_activities(records)

    def minutes_by_category(self, period: DateRange) -> dict[str, float]:
        """Total activity minutes per category name."""
        with self.uow() as uow:
            return uow.activities.minutes_by_category(period.start, period.end)

    # -- internals ---------------------------------------------------------

    def _reject_future(self, day: date) -> None:
        """Refuse to log something that has not happened."""
        if day > self.today():
            raise ValidationError(
                "Cannot log an activity in the future",
                field="log_date",
                value=day.isoformat(),
                user_hint="Pick today or an earlier date.",
            )

    def _resolve_interval(
        self, payload: ActivityInput
    ) -> tuple[datetime | None, datetime | None, float]:
        """Turn the form's times into UTC instants and a duration."""
        return resolve_interval(
            log_date=payload.log_date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            duration_minutes=payload.duration_minutes,
            tz=self.tz,
        )

    def _estimate_calories(
        self, uow: UnitOfWork, minutes: float, payload: ActivityInput
    ) -> float | None:
        """Estimate calories from the latest weight, if one is recorded."""
        measurement = uow.measurements.latest()
        if measurement is None:
            return None
        return estimate_activity_calories(
            weight_kg=measurement.weight_kg,
            duration_minutes=minutes,
            intensity=payload.intensity,
        )


def resolve_interval(
    *,
    log_date: date,
    start_time: time | None,
    end_time: time | None,
    duration_minutes: float | None,
    tz: ZoneInfo,
) -> tuple[datetime | None, datetime | None, float]:
    """Resolve a form's optional interval into instants and a duration.

    Shared by activities and time entries, which accept the same shape of
    input: either a duration on its own, or a start and end time.

    An end time at or before the start is read as crossing midnight, which
    is what makes a session from 23:00 to 00:30 ninety minutes rather than
    a validation error.

    Args:
        log_date: Local date the entry is filed under.
        start_time: Local start, if known.
        end_time: Local end, if known.
        duration_minutes: Explicit duration, used when there is no interval.
        tz: The user's timezone.

    Returns:
        ``(started_at, ended_at, duration_minutes)`` with UTC instants.

    Raises:
        ValidationError: If neither an interval nor a duration was given, or
            the resulting duration is not positive.
    """
    if start_time is not None and end_time is not None:
        started_at = combine_local(log_date, start_time, tz)
        ended_at = combine_local(log_date, end_time, tz)
        if ended_at <= started_at:
            ended_at += timedelta(days=1)
        minutes = minutes_between(started_at, ended_at)
        return started_at, ended_at, minutes

    if duration_minutes is None or duration_minutes <= 0:
        raise ValidationError(
            "A duration is required",
            field="duration_minutes",
            value=duration_minutes,
            user_hint="Enter how long it took, or a start and end time.",
        )
    return None, None, float(duration_minutes)


__all__ = ["ActivityService", "resolve_interval"]
