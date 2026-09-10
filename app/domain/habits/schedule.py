"""When a habit is expected, and when it is legitimately off.

A streak engine that does not know the schedule is wrong in both directions:
it punishes a Saturday for a weekday habit, and it rewards a rest day as if
it were a completion. So the schedule is its own value object, decided once,
and the streak code asks it rather than guessing.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.models.enums import HabitFrequency

#: A schedule walk never needs to look back further than this to find the
#: next expected day. It bounds the loop for a schedule that expects nothing.
_MAX_SCAN_DAYS = 400

_WEEKDAYS = frozenset({0, 1, 2, 3, 4})
_WEEKENDS = frozenset({5, 6})


@dataclass(frozen=True, slots=True)
class HabitSchedule:
    """The rules deciding which dates a habit is due on.

    Attributes:
        frequency: Which pattern applies.
        specific_days: Weekday numbers (0=Monday) for ``SPECIFIC_DAYS``.
        rest_days: Weekday numbers that are never counted as a miss, whatever
            the frequency says.
        times_per_week: Target count for ``TIMES_PER_WEEK``, where no
            individual day is compulsory.
        start_date: The habit does not exist before this date.
        end_date: The habit does not exist after this date.
    """

    frequency: HabitFrequency = HabitFrequency.DAILY
    specific_days: frozenset[int] = frozenset()
    rest_days: frozenset[int] = frozenset()
    times_per_week: int | None = None
    start_date: date | None = None
    end_date: date | None = None

    @classmethod
    def build(
        cls,
        frequency: HabitFrequency = HabitFrequency.DAILY,
        specific_days: Sequence[int] | None = None,
        rest_days: Sequence[int] | None = None,
        times_per_week: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> HabitSchedule:
        """Build a schedule from the loose values stored on a habit row."""
        return cls(
            frequency=frequency,
            specific_days=frozenset(specific_days or ()),
            rest_days=frozenset(rest_days or ()),
            times_per_week=times_per_week,
            start_date=start_date,
            end_date=end_date,
        )

    @property
    def is_flexible(self) -> bool:
        """Whether the habit has a weekly quota rather than fixed days.

        A flexible habit cannot break a day-by-day streak, so the streak
        engine measures it in weeks instead.
        """
        return self.frequency is HabitFrequency.TIMES_PER_WEEK

    def is_within_lifetime(self, day: date) -> bool:
        """Whether ``day`` falls inside the habit's start/end window."""
        if self.start_date is not None and day < self.start_date:
            return False
        return not (self.end_date is not None and day > self.end_date)

    def is_rest_day(self, day: date) -> bool:
        """Whether ``day`` is a declared rest day."""
        return day.weekday() in self.rest_days

    def is_expected_on(self, day: date) -> bool:
        """Whether the habit is due on ``day``.

        A rest day is never expected. Neither is a date outside the habit's
        lifetime, which is what stops a habit created today from showing a
        year of missed days behind it.
        """
        if not self.is_within_lifetime(day) or self.is_rest_day(day):
            return False

        match self.frequency:
            case HabitFrequency.DAILY:
                return True
            case HabitFrequency.WEEKDAYS:
                return day.weekday() in _WEEKDAYS
            case HabitFrequency.WEEKENDS:
                return day.weekday() in _WEEKENDS
            case HabitFrequency.SPECIFIC_DAYS:
                return day.weekday() in self.specific_days
            case HabitFrequency.TIMES_PER_WEEK:
                # No individual day is compulsory; the week as a whole is.
                return False
        return False

    def expected_days(self, start: date, end: date) -> Iterator[date]:
        """Yield every expected date in the inclusive range."""
        current = start
        while current <= end:
            if self.is_expected_on(current):
                yield current
            current += timedelta(days=1)

    def count_expected(self, start: date, end: date) -> int:
        """Return how many days in the inclusive range the habit was due."""
        return sum(1 for _ in self.expected_days(start, end))

    def previous_expected(self, day: date, *, inclusive: bool = True) -> date | None:
        """Return the latest expected date at or before ``day``.

        Returns ``None`` if there is none within :data:`_MAX_SCAN_DAYS`, or
        once the walk passes the habit's start date.
        """
        cursor = day if inclusive else day - timedelta(days=1)
        for _ in range(_MAX_SCAN_DAYS):
            if self.start_date is not None and cursor < self.start_date:
                return None
            if self.is_expected_on(cursor):
                return cursor
            cursor -= timedelta(days=1)
        return None

    def next_expected(self, day: date, *, inclusive: bool = True) -> date | None:
        """Return the earliest expected date at or after ``day``."""
        cursor = day if inclusive else day + timedelta(days=1)
        for _ in range(_MAX_SCAN_DAYS):
            if self.end_date is not None and cursor > self.end_date:
                return None
            if self.is_expected_on(cursor):
                return cursor
            cursor += timedelta(days=1)
        return None
