"""Sleep business rules."""

from __future__ import annotations

from datetime import date, time, timedelta

from app.core.errors import ValidationError
from app.core.logging_config import get_logger
from app.domain.sleep.calculations import (
    SleepStats,
    SleepWindow,
    resolve_sleep_window,
    summarize_sleep,
)
from app.models.sleep import SleepRecord
from app.schemas.common import DateRange, Page, Pagination
from app.schemas.sleep import SleepInput, SleepRead, SleepStatsRead
from app.services.base import BaseService

logger = get_logger(__name__)

#: Default analysis window for the sleep page.
DEFAULT_WINDOW_DAYS = 30


class SleepService(BaseService):
    """Recording nights and reporting on them."""

    def get_for_date(self, day: date) -> SleepRead | None:
        """Return the night filed under one date, if there is one."""
        with self.uow() as uow:
            record = uow.sleep.get_for_date(day)
            return SleepRead.model_validate(record) if record else None

    def list_between(self, period: DateRange) -> list[SleepRead]:
        """Return the nights inside a date range."""
        with self.uow() as uow:
            return [
                SleepRead.model_validate(row)
                for row in uow.sleep.list_between(period.start, period.end)
            ]

    def history(self, pagination: Pagination) -> Page[SleepRead]:
        """Return sleep history, one page at a time."""
        with self.uow() as uow:
            rows, total = uow.sleep.page(pagination)
            return Page[SleepRead](
                items=[SleepRead.model_validate(row) for row in rows],
                total=total,
                limit=pagination.limit,
                offset=pagination.offset,
            )

    def record(self, payload: SleepInput) -> SleepRead:
        """Save one night, replacing any existing record for that date.

        The three clock times the user typed are resolved into absolute
        instants by the domain layer before anything is written, so the
        stored duration is correct across midnight without this method
        needing to know that midnight exists.

        Raises:
            ValidationError: If the date is in the future or the resulting
                duration is implausible.
        """
        if payload.log_date > self.today():
            raise ValidationError(
                "Cannot record a night that has not happened yet",
                field="log_date",
                value=payload.log_date.isoformat(),
                user_hint="Sleep is filed under the morning you woke up.",
            )

        window = resolve_sleep_window(
            log_date=payload.log_date,
            sleep_time=payload.sleep_time,
            wake_time=payload.wake_time,
            bedtime=payload.bedtime,
            tz=self.tz,
        )

        with self.uow() as uow:
            existing = uow.sleep.get_for_date(payload.log_date)
            if existing is None:
                record = SleepRecord(
                    user_id=self.user_id,
                    log_date=payload.log_date,
                    bedtime_at=window.bedtime_at,
                    sleep_at=window.sleep_at,
                    wake_at=window.wake_at,
                    duration_minutes=window.duration_minutes,
                    quality=payload.quality,
                    interruptions=payload.interruptions,
                    notes=payload.notes,
                )
                uow.sleep.add(record)
                logger.info(
                    "Sleep recorded for %s (%.0f minutes)",
                    payload.log_date.isoformat(),
                    window.duration_minutes,
                )
            else:
                existing.bedtime_at = window.bedtime_at
                existing.sleep_at = window.sleep_at
                existing.wake_at = window.wake_at
                existing.duration_minutes = window.duration_minutes
                existing.quality = payload.quality
                existing.interruptions = payload.interruptions
                existing.notes = payload.notes
                record = existing
                logger.info("Sleep for %s updated", payload.log_date.isoformat())

            uow.commit()
            return SleepRead.model_validate(record)

    def delete(self, day: date) -> bool:
        """Remove the night filed under a date."""
        with self.uow() as uow:
            record = uow.sleep.get_for_date(day)
            if record is None:
                return False
            uow.sleep.delete(record)
            uow.commit()
            logger.info("Sleep record for %s deleted", day.isoformat())
            return True

    def stats(self, period: DateRange | None = None) -> SleepStatsRead:
        """Aggregate sleep over a window.

        Args:
            period: The range to analyse. Defaults to the last thirty days.
        """
        window = period or DateRange.last_n_days(self.today(), DEFAULT_WINDOW_DAYS)
        with self.uow() as uow:
            profile = uow.profiles.get_or_raise(self.user_id)
            target = float(profile.target_sleep_minutes)
            records = uow.sleep.list_between(window.start, window.end)

        summary = self._summarize(records, target)
        return SleepStatsRead(
            nights=summary.nights,
            average_minutes=summary.average_minutes,
            average_7d=summary.average_7d,
            average_30d=summary.average_30d,
            consistency_score=summary.consistency_score,
            sleep_debt_minutes=summary.sleep_debt_minutes,
            bedtime_variance_minutes=summary.bedtime_variance_minutes,
            wake_variance_minutes=summary.wake_variance_minutes,
            median_bedtime=summary.median_bedtime,
            median_wake=summary.median_wake,
            target_minutes=target,
        )

    def average_minutes(self, period: DateRange) -> float | None:
        """Average nightly sleep over a range, computed by the database."""
        with self.uow() as uow:
            return uow.sleep.average_minutes(period.start, period.end)

    def nights_below_target(self, period: DateRange) -> int:
        """Count nights shorter than the profile's target."""
        with self.uow() as uow:
            profile = uow.profiles.get_or_raise(self.user_id)
            return uow.sleep.count_below(
                period.start, period.end, float(profile.target_sleep_minutes)
            )

    def bedtime_shift(self, period: DateRange) -> float | None:
        """Minutes by which the median bedtime moved against the previous period.

        Positive means later. Returns ``None`` when either period has fewer
        than one recorded night.
        """
        previous = period.previous()
        with self.uow() as uow:
            profile = uow.profiles.get_or_raise(self.user_id)
            target = float(profile.target_sleep_minutes)
            current_rows = uow.sleep.list_between(period.start, period.end)
            previous_rows = uow.sleep.list_between(previous.start, previous.end)

        current = self._summarize(current_rows, target).median_bedtime
        earlier = self._summarize(previous_rows, target).median_bedtime
        if current is None or earlier is None:
            return None

        # Compared on the same midday-centred axis the domain layer uses, so
        # a move from 23:50 to 00:10 reads as twenty minutes later.
        return _clock_axis_minutes(current) - _clock_axis_minutes(earlier)

    def _summarize(self, records: list[SleepRecord], target_minutes: float) -> SleepStats:
        """Convert ORM rows into domain windows and summarise them."""
        windows = [
            SleepWindow(
                log_date=row.log_date,
                bedtime_at=row.bedtime_at,
                sleep_at=row.sleep_at,
                wake_at=row.wake_at,
                duration_minutes=row.duration_minutes,
            )
            for row in records
        ]
        return summarize_sleep(windows, target_minutes=target_minutes, tz=self.tz)

    def quick_log(self, sleep_time: str, wake_time: str, day: date | None = None) -> SleepRead:
        """Record a night from two ``HH:MM`` strings.

        The Quick Add path: ``23:20 -> 06:30`` and nothing else.

        Raises:
            ValidationError: If either string is not a valid ``HH:MM`` time.
        """
        return self.record(
            SleepInput(
                log_date=day or self.today(),
                sleep_time=_parse_clock(sleep_time, "sleep_time"),
                wake_time=_parse_clock(wake_time, "wake_time"),
            )
        )

    def recent_window(self, days: int = DEFAULT_WINDOW_DAYS) -> DateRange:
        """A date range covering the last ``days`` days, ending today."""
        today = self.today()
        return DateRange(start=today - timedelta(days=days - 1), end=today)


def _parse_clock(raw: str, field: str) -> time:
    """Parse an ``HH:MM`` string into a time.

    Raises:
        ValidationError: If the string is not a valid clock time.
    """
    try:
        hours, _, minutes = raw.strip().partition(":")
        return time(hour=int(hours), minute=int(minutes or 0))
    except (TypeError, ValueError) as error:
        raise ValidationError("Enter a time as HH:MM", field=field, value=raw) from error


def _clock_axis_minutes(moment: time) -> float:
    """Project a clock time onto the midday-centred axis, in minutes."""
    return ((moment.hour * 60 + moment.minute) + 720) % 1440


__all__ = ["DEFAULT_WINDOW_DAYS", "SleepService"]
