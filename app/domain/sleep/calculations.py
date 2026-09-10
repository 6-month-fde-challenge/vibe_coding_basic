"""Sleep arithmetic, including the part that crosses midnight.

The midnight problem is solved once, here, by refusing to work with clock
times at all. A night is a pair of instants; "23:30 to 06:30" becomes two
datetimes seven hours apart, and every downstream calculation is ordinary
subtraction. Nothing later in the stack needs a branch for "wake time is
smaller than bedtime".

Clock-time *variance* is the one place the wall clock genuinely matters -
"is my bedtime drifting?" - and that gets its own circular-statistics
treatment below, because the naive answer says 23:50 and 00:10 are twenty-
three hours and forty minutes apart.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import ValidationError

#: A night shorter than this is a nap or a typo, not a night's sleep.
MIN_SLEEP_MINUTES = 30.0
#: Eighteen hours. Beyond this the entry is almost certainly a date mistake.
MAX_SLEEP_MINUTES = 1080.0

#: Clock times are projected onto an axis centred on midday before any
#: averaging, so that times either side of midnight stay neighbours.
_MIDDAY_SHIFT_MINUTES = 720


@dataclass(frozen=True, slots=True)
class SleepWindow:
    """One night resolved into absolute instants.

    Attributes:
        log_date: The morning the user woke up; the night's identity.
        bedtime_at: When they got into bed, if recorded.
        sleep_at: When they fell asleep.
        wake_at: When they woke.
        duration_minutes: ``wake_at - sleep_at``.
    """

    log_date: date
    bedtime_at: datetime | None
    sleep_at: datetime
    wake_at: datetime
    duration_minutes: float

    @property
    def latency_minutes(self) -> float | None:
        """Minutes spent in bed before falling asleep, if bedtime is known."""
        if self.bedtime_at is None:
            return None
        return (self.sleep_at - self.bedtime_at).total_seconds() / 60.0


@dataclass(frozen=True, slots=True)
class SleepStats:
    """Aggregate sleep figures over a window of nights.

    Attributes:
        nights: How many records were analysed.
        average_minutes: Mean duration across the window.
        average_7d: Mean over the seven most recent nights.
        average_30d: Mean over the thirty most recent nights.
        consistency_score: ``0-100``. One hundred means every night was the
            same length; it falls as the standard deviation grows.
        sleep_debt_minutes: Target minus actual, summed. Positive is a
            deficit.
        bedtime_variance_minutes: Standard deviation of the time the user
            fell asleep, measured on a circular clock.
        wake_variance_minutes: The same, for wake time.
        median_bedtime: Typical time of falling asleep.
        median_wake: Typical wake time.
    """

    nights: int = 0
    average_minutes: float | None = None
    average_7d: float | None = None
    average_30d: float | None = None
    consistency_score: float | None = None
    sleep_debt_minutes: float = 0.0
    bedtime_variance_minutes: float | None = None
    wake_variance_minutes: float | None = None
    median_bedtime: time | None = None
    median_wake: time | None = None

    @property
    def has_data(self) -> bool:
        """Whether any nights were analysed."""
        return self.nights > 0


def resolve_sleep_window(
    *,
    log_date: date,
    sleep_time: time,
    wake_time: time,
    tz: ZoneInfo,
    bedtime: time | None = None,
) -> SleepWindow:
    """Turn the three clock times a user types into absolute instants.

    ``log_date`` is the morning the user woke up. Falling asleep is placed on
    the previous evening whenever the sleep clock time is at or after the
    wake clock time, which is the ordinary case - and is exactly the rule
    that makes 23:30 to 06:30 come out as seven hours.

    Args:
        log_date: The date the user woke up, in their timezone.
        sleep_time: Wall-clock time they fell asleep.
        wake_time: Wall-clock time they woke.
        tz: The user's timezone.
        bedtime: Wall-clock time they got into bed, if recorded.

    Returns:
        The resolved window, with UTC instants.

    Raises:
        ValidationError: If the resulting duration is implausible.
    """
    wake_at = datetime.combine(log_date, wake_time, tzinfo=tz)
    sleep_at = datetime.combine(log_date, sleep_time, tzinfo=tz)
    if sleep_at >= wake_at:
        sleep_at -= timedelta(days=1)

    bedtime_at: datetime | None = None
    if bedtime is not None:
        bedtime_at = datetime.combine(sleep_at.date(), bedtime, tzinfo=tz)
        if bedtime_at > sleep_at:
            # Got into bed before midnight, fell asleep after it.
            bedtime_at -= timedelta(days=1)

    duration = (wake_at - sleep_at).total_seconds() / 60.0
    if duration < MIN_SLEEP_MINUTES:
        raise ValidationError(
            f"A night shorter than {MIN_SLEEP_MINUTES:.0f} minutes looks like a mistake",
            field="wake_time",
            value=wake_time.isoformat(),
            user_hint="Check the sleep and wake times - that is under half an hour.",
        )
    if duration > MAX_SLEEP_MINUTES:
        raise ValidationError(
            f"A night longer than {MAX_SLEEP_MINUTES / 60:.0f} hours looks like a mistake",
            field="wake_time",
            value=wake_time.isoformat(),
            user_hint="Check the date - that is more than eighteen hours in bed.",
        )

    return SleepWindow(
        log_date=log_date,
        bedtime_at=bedtime_at.astimezone(UTC) if bedtime_at else None,
        sleep_at=sleep_at.astimezone(UTC),
        wake_at=wake_at.astimezone(UTC),
        duration_minutes=duration,
    )


def _clock_axis(moment: time) -> float:
    """Project a clock time onto a midday-centred axis.

    Midnight sits in the middle of the axis rather than at its ends, so
    23:50 and 00:10 differ by twenty minutes rather than by a day.
    """
    minutes = moment.hour * 60 + moment.minute + moment.second / 60.0
    return (minutes + _MIDDAY_SHIFT_MINUTES) % 1440


def _from_clock_axis(value: float) -> time:
    """Invert :func:`_clock_axis`."""
    minutes = (value - _MIDDAY_SHIFT_MINUTES) % 1440
    hour, minute = divmod(round(minutes) % 1440, 60)
    return time(hour=hour, minute=minute)


def clock_time_variance(times: Sequence[time]) -> float | None:
    """Return the standard deviation, in minutes, of a set of clock times.

    Returns ``None`` for fewer than two readings, because a single point has
    no spread and pretending otherwise puts a zero on the dashboard that
    looks like perfect consistency.
    """
    if len(times) < 2:
        return None
    return statistics.pstdev([_clock_axis(moment) for moment in times])


def median_clock_time(times: Sequence[time]) -> time | None:
    """Return the median clock time, computed on the circular axis."""
    if not times:
        return None
    return _from_clock_axis(statistics.median([_clock_axis(moment) for moment in times]))


def consistency_score(durations: Sequence[float]) -> float | None:
    """Score how even a run of nights is, from 0 to 100.

    A ninety-minute standard deviation scores zero; identical nights score
    one hundred. The scale is linear in between and deliberately simple -
    it is a nudge, not a diagnosis.
    """
    if len(durations) < 2:
        return None
    spread = statistics.pstdev(durations)
    worst = 90.0
    return max(0.0, min(100.0, 100.0 * (1.0 - spread / worst)))


def summarize_sleep(
    windows: Sequence[SleepWindow],
    *,
    target_minutes: float,
    tz: ZoneInfo,
) -> SleepStats:
    """Aggregate a window of nights.

    Args:
        windows: Nights in any order; sorted internally, newest last.
        target_minutes: The user's nightly target, for the debt figure.
        tz: The user's timezone, needed to read clock times back out of the
            stored UTC instants.

    Returns:
        Populated statistics. Every field is ``None``-safe on empty input.
    """
    if not windows:
        return SleepStats()

    ordered = sorted(windows, key=lambda window: window.log_date)
    durations = [window.duration_minutes for window in ordered]

    sleep_times = [window.sleep_at.astimezone(tz).time() for window in ordered]
    wake_times = [window.wake_at.astimezone(tz).time() for window in ordered]

    debt = sum(target_minutes - duration for duration in durations)

    return SleepStats(
        nights=len(ordered),
        average_minutes=statistics.fmean(durations),
        average_7d=statistics.fmean(durations[-7:]) if durations else None,
        average_30d=statistics.fmean(durations[-30:]) if durations else None,
        consistency_score=consistency_score(durations),
        sleep_debt_minutes=debt,
        bedtime_variance_minutes=clock_time_variance(sleep_times),
        wake_variance_minutes=clock_time_variance(wake_times),
        median_bedtime=median_clock_time(sleep_times),
        median_wake=median_clock_time(wake_times),
    )
