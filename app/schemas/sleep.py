"""Sleep input and output schemas."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import Field

from app.schemas.common import ReadSchema, Schema


class SleepInput(Schema):
    """One night, as the user types it.

    Clock times, not datetimes. Turning "23:30 to 06:30" into two instants
    is the domain layer's job - see
    :func:`app.domain.sleep.calculations.resolve_sleep_window` - so the form
    stays as simple as the question it is asking.
    """

    log_date: date
    sleep_time: time
    wake_time: time
    bedtime: time | None = None
    quality: int | None = Field(default=None, ge=1, le=10)
    interruptions: int = Field(default=0, ge=0, le=50)
    notes: str | None = Field(default=None, max_length=2000)


class SleepRead(ReadSchema):
    """A stored night."""

    id: int
    log_date: date
    bedtime_at: datetime | None
    sleep_at: datetime
    wake_at: datetime
    duration_minutes: float
    quality: int | None
    interruptions: int
    notes: str | None


class SleepStatsRead(ReadSchema):
    """Aggregate sleep figures for a window."""

    nights: int
    average_minutes: float | None
    average_7d: float | None
    average_30d: float | None
    consistency_score: float | None
    sleep_debt_minutes: float
    bedtime_variance_minutes: float | None
    wake_variance_minutes: float | None
    median_bedtime: time | None
    median_wake: time | None
    target_minutes: float
