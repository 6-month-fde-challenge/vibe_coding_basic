"""Timezone-aware date and time helpers.

Two rules hold everywhere in this application:

1. Every ``datetime`` that crosses a layer boundary is timezone-aware and
   stored in UTC.
2. Every *day* - a habit log date, a task due date, the date a night's sleep
   is filed under - is a naive :class:`datetime.date` in the **user's**
   timezone. Days are a human concept; UTC is a storage concept.

Turning one into the other is the job of this module, and nothing else should
be doing it by hand.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

#: Monday, matching :meth:`datetime.date.weekday`.
DEFAULT_WEEK_START = 0

_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@runtime_checkable
class Clock(Protocol):
    """Source of "now".

    Injected rather than called directly so that tests can pin the current
    moment instead of skipping assertions that depend on it.
    """

    @property
    def timezone(self) -> ZoneInfo:
        """The user's timezone, which defines their day boundary."""
        ...

    def now(self) -> datetime:
        """Current instant as an aware UTC datetime."""
        ...

    def local_now(self) -> datetime:
        """Current instant as an aware datetime in the user's timezone."""
        ...

    def today(self) -> date:
        """Today's calendar date in the user's timezone."""
        ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    """A :class:`Clock` backed by the operating system clock."""

    tz: ZoneInfo

    @property
    def timezone(self) -> ZoneInfo:
        """The user's timezone."""
        return self.tz

    def now(self) -> datetime:
        """Current instant as an aware UTC datetime."""
        return datetime.now(UTC)

    def local_now(self) -> datetime:
        """Current instant in the user's timezone."""
        return self.now().astimezone(self.tz)

    def today(self) -> date:
        """Today's date in the user's timezone."""
        return self.local_now().date()


@dataclass(frozen=True, slots=True)
class FixedClock:
    """A :class:`Clock` pinned to one instant, for tests and replays."""

    instant: datetime
    tz: ZoneInfo

    @property
    def timezone(self) -> ZoneInfo:
        """The configured timezone."""
        return self.tz

    def now(self) -> datetime:
        """The pinned instant, normalised to UTC."""
        return ensure_utc(self.instant)

    def local_now(self) -> datetime:
        """The pinned instant in the configured timezone."""
        return self.now().astimezone(self.tz)

    def today(self) -> date:
        """The date of the pinned instant in the configured timezone."""
        return self.local_now().date()


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime.

    A naive datetime is *assumed* to already be UTC. Callers holding a local
    naive value should use :func:`combine_local` or :func:`localize` instead
    of relying on that assumption.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def localize(value: datetime, tz: ZoneInfo) -> datetime:
    """Attach ``tz`` to a naive datetime, or convert an aware one into it."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def to_local(value: datetime, tz: ZoneInfo) -> datetime:
    """Convert an instant (aware, or naive-UTC) into the user's timezone."""
    return ensure_utc(value).astimezone(tz)


def local_date_of(value: datetime, tz: ZoneInfo) -> date:
    """Return the calendar date an instant falls on in the user's timezone."""
    return to_local(value, tz).date()


def combine_local(day: date, moment: time, tz: ZoneInfo) -> datetime:
    """Combine a local date and local time into an aware UTC datetime.

    Args:
        day: Calendar date in the user's timezone.
        moment: Wall-clock time in the user's timezone.
        tz: The user's timezone.

    Returns:
        The corresponding instant, in UTC.
    """
    return datetime.combine(day, moment, tzinfo=tz).astimezone(UTC)


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the half-open UTC interval covering one local day.

    Half-open on purpose: it composes correctly for range queries and cannot
    double-count a record landing exactly on midnight. Computing the end as
    "start of the next day" rather than "start + 24h" keeps it right across a
    daylight-saving transition, where a local day may be 23 or 25 hours long.

    Args:
        day: Calendar date in the user's timezone.
        tz: The user's timezone.

    Returns:
        ``(start, end)`` in UTC, where ``end`` is exclusive.
    """
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def range_bounds_utc(start_day: date, end_day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the UTC interval covering an inclusive range of local days."""
    start, _ = day_bounds_utc(start_day, tz)
    _, end = day_bounds_utc(end_day, tz)
    return start, end


def week_start(day: date, first_weekday: int = DEFAULT_WEEK_START) -> date:
    """Return the first day of the week containing ``day``.

    Args:
        day: Any date in the week.
        first_weekday: ``0`` for Monday through ``6`` for Sunday.
    """
    offset = (day.weekday() - first_weekday) % 7
    return day - timedelta(days=offset)


def week_bounds(day: date, first_weekday: int = DEFAULT_WEEK_START) -> tuple[date, date]:
    """Return the inclusive first and last dates of the week containing ``day``."""
    start = week_start(day, first_weekday)
    return start, start + timedelta(days=6)


def month_bounds(day: date) -> tuple[date, date]:
    """Return the inclusive first and last dates of the month containing ``day``."""
    start = day.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month - timedelta(days=1)


def date_range(start: date, end: date) -> Iterator[date]:
    """Yield every date from ``start`` to ``end`` inclusive.

    Yields nothing when ``end`` precedes ``start``, which is what callers
    building an empty report want.
    """
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def days_between(start: date, end: date) -> int:
    """Return the inclusive number of days spanned by two dates."""
    return max(0, (end - start).days + 1)


def weekday_name(day: date) -> str:
    """Return the English weekday name for a date."""
    return _WEEKDAY_NAMES[day.weekday()]


def iso_week_label(day: date) -> str:
    """Return a sortable ISO week label such as ``2026-W37``."""
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def month_label(day: date) -> str:
    """Return a sortable month label such as ``2026-09``."""
    return f"{day.year}-{day.month:02d}"


def format_duration(minutes: float | None) -> str:
    """Render a minute count as ``7h 32m``.

    Args:
        minutes: Duration in minutes. ``None`` and negatives render as ``-``.
    """
    if minutes is None or minutes < 0:
        return "-"
    total = round(minutes)
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def minutes_between(start: datetime, end: datetime) -> float:
    """Return the number of minutes from ``start`` to ``end``.

    Both values are normalised to UTC first, so a pair that straddles a
    timezone or DST boundary still measures real elapsed time.
    """
    return (ensure_utc(end) - ensure_utc(start)).total_seconds() / 60.0
