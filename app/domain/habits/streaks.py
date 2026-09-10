"""The streak engine.

The efficiency requirement in the brief is specific: do not scan the whole
history to answer "what is my current streak". So the two calculations are
split by the shape of the data they need.

``current_streak``
    Consumes a **lazy, descending** iterator of completion dates and stops at
    the first break. A ten-year habit with a two-day streak reads three rows.
    The repository backs the iterator with a paged query, so the database
    only fetches what the walk actually consumes.

``longest_streak``
    Genuinely needs every completion, but only the *date column* of one
    habit - a narrow index-only scan, not the whole table.

Both take a :class:`~app.domain.habits.schedule.HabitSchedule`, because a
weekday habit must not be broken by a Saturday and a rest day must never
count as a miss.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from app.domain.habits.schedule import HabitSchedule


@dataclass(frozen=True, slots=True)
class StreakSummary:
    """Everything the UI shows about one habit's consistency.

    Attributes:
        current_streak: Unbroken expected days completed, counting back from
            today.
        longest_streak: The best run ever recorded.
        total_completions: Completed days inside the analysed window.
        expected_days: Days the habit was due inside the window.
        missed_days: Expected days with no completion, excluding today if it
            is still in progress.
        completion_rate: ``total_completions / expected_days``, ``0.0`` when
            nothing was expected.
        last_completed_on: Most recent completion, if any.
        weekly_consistency: Completion rate over the last seven days.
        monthly_consistency: Completion rate over the last thirty days.
    """

    current_streak: int = 0
    longest_streak: int = 0
    total_completions: int = 0
    expected_days: int = 0
    missed_days: int = 0
    completion_rate: float = 0.0
    last_completed_on: date | None = None
    weekly_consistency: float = 0.0
    monthly_consistency: float = 0.0

    @property
    def has_history(self) -> bool:
        """Whether there is anything to report."""
        return self.expected_days > 0 or self.total_completions > 0


def current_streak(
    completed_desc: Iterable[date],
    schedule: HabitSchedule,
    today: date,
    *,
    grace_today: bool = True,
) -> int:
    """Return the number of consecutive expected days completed up to today.

    Args:
        completed_desc: Completion dates, newest first. Consumed lazily and
            abandoned at the first gap, so the caller may pass a generator
            over a paged query.
        schedule: The habit's schedule, used to skip days it was not due.
        today: The user's local today.
        grace_today: When true, a not-yet-logged *today* does not break the
            run - it simply is not counted yet. This is the difference
            between a tracker that is useful at 9am and one that tells you
            your 40-day streak is over every single morning.

    Returns:
        The current streak length. Zero when the most recent expected day was
        missed.
    """
    if schedule.is_flexible:
        return _flexible_current_streak(completed_desc, schedule, today)

    cursor = schedule.previous_expected(today)
    if cursor is None:
        return 0

    streak = 0
    for completed in completed_desc:
        if completed > cursor:
            # Future-dated or already-counted rows: ignore rather than fail.
            continue
        if not schedule.is_expected_on(completed):
            # A completion on a day the habit was not due is a bonus. It must
            # not extend the run, and it must not break it either.
            continue

        if completed == cursor:
            streak += 1
            next_cursor = schedule.previous_expected(cursor - timedelta(days=1))
            if next_cursor is None:
                break
            cursor = next_cursor
            continue

        # completed < cursor: the day at the cursor was expected and missed.
        if grace_today and cursor == today and streak == 0:
            # Today has not been logged yet. Step back one expected day and
            # let the run continue from yesterday.
            previous = schedule.previous_expected(today - timedelta(days=1))
            if previous is None or completed > previous:
                return 0
            cursor = previous
            if completed == cursor:
                streak += 1
                next_cursor = schedule.previous_expected(cursor - timedelta(days=1))
                if next_cursor is None:
                    break
                cursor = next_cursor
                continue
        break

    return streak


def _flexible_current_streak(
    completed_desc: Iterable[date],
    schedule: HabitSchedule,
    today: date,
) -> int:
    """Count consecutive *weeks* meeting the quota, for a flexible habit.

    A "three times a week" habit has no compulsory day, so a day-by-day
    streak is meaningless. The unit is the week; the current week counts only
    once its quota is already met, so an unfinished week never reads as a
    break.
    """
    quota = schedule.times_per_week or 1
    per_week: dict[date, int] = {}
    for completed in completed_desc:
        if completed > today:
            continue
        week = completed - timedelta(days=completed.weekday())
        per_week[week] = per_week.get(week, 0) + 1

    if not per_week:
        return 0

    week_cursor = today - timedelta(days=today.weekday())
    streak = 0
    if per_week.get(week_cursor, 0) >= quota:
        streak += 1
    week_cursor -= timedelta(days=7)

    while per_week.get(week_cursor, 0) >= quota:
        week_end = week_cursor + timedelta(days=6)
        if schedule.start_date is not None and week_end < schedule.start_date:
            break
        streak += 1
        week_cursor -= timedelta(days=7)

    return streak


def longest_streak(completed_dates: Iterable[date], schedule: HabitSchedule) -> int:
    """Return the longest run of consecutive expected days ever completed.

    Args:
        completed_dates: Completion dates in any order. Sorted internally.
        schedule: The habit's schedule.

    Returns:
        The best run length, or ``0`` when there are no completions.
    """
    ordered = sorted(set(completed_dates))
    if not ordered:
        return 0
    if schedule.is_flexible:
        return _flexible_longest_streak(ordered, schedule)

    # Bonus completions on days the habit was not due neither extend nor
    # break a run, so they are dropped before the scan rather than
    # special-cased inside it.
    ordered = [day for day in ordered if schedule.is_expected_on(day)]
    if not ordered:
        return 0

    best = 1
    run = 1
    for previous, current in pairwise(ordered):
        expected_next = schedule.next_expected(previous + timedelta(days=1))
        run = run + 1 if expected_next == current else 1
        best = max(best, run)
    return best


def _flexible_longest_streak(ordered: Sequence[date], schedule: HabitSchedule) -> int:
    """Longest run of consecutive quota-meeting weeks."""
    quota = schedule.times_per_week or 1
    per_week: dict[date, int] = {}
    for day in ordered:
        week = day - timedelta(days=day.weekday())
        per_week[week] = per_week.get(week, 0) + 1

    qualifying = sorted(week for week, count in per_week.items() if count >= quota)
    if not qualifying:
        return 0

    best = 1
    run = 1
    for previous, current in pairwise(qualifying):
        run = run + 1 if current - previous == timedelta(days=7) else 1
        best = max(best, run)
    return best


def summarize(
    completed_dates: Sequence[date],
    schedule: HabitSchedule,
    today: date,
    *,
    window_start: date | None = None,
) -> StreakSummary:
    """Build the full consistency picture for one habit.

    Args:
        completed_dates: Every completion date the caller wants considered.
        schedule: The habit's schedule.
        today: The user's local today.
        window_start: Start of the analysis window. Defaults to the habit's
            start date, or the earliest completion, whichever exists.

    Returns:
        A populated :class:`StreakSummary`. Safe on an empty input.
    """
    unique = sorted(set(completed_dates))
    if not unique and schedule.start_date is None:
        return StreakSummary()

    start = window_start or schedule.start_date or (unique[0] if unique else today)
    end = min(today, schedule.end_date) if schedule.end_date else today
    if end < start:
        return StreakSummary(longest_streak=longest_streak(unique, schedule))

    completed_set = set(unique)
    expected = list(schedule.expected_days(start, end))
    # Only completions on days the habit was actually due count towards the
    # rate. A bonus Saturday on a weekdays-only habit is a nice thing to
    # have done, not 110% consistency.
    expected_set = set(expected)
    in_window = [day for day in unique if day in expected_set]

    # Today is not a miss until the day is over.
    missable = [day for day in expected if day != today]
    missed = sum(1 for day in missable if day not in completed_set)

    return StreakSummary(
        current_streak=current_streak(reversed(unique), schedule, today),
        longest_streak=longest_streak(unique, schedule),
        total_completions=len(in_window),
        expected_days=len(expected),
        missed_days=missed,
        completion_rate=(len(in_window) / len(expected)) if expected else 0.0,
        last_completed_on=unique[-1] if unique else None,
        weekly_consistency=_window_rate(completed_set, schedule, end, days=7),
        monthly_consistency=_window_rate(completed_set, schedule, end, days=30),
    )


def _window_rate(
    completed: set[date],
    schedule: HabitSchedule,
    end: date,
    *,
    days: int,
) -> float:
    """Completion rate over the last ``days`` days ending at ``end``."""
    start = end - timedelta(days=days - 1)
    expected = list(schedule.expected_days(start, end))
    if not expected:
        return 0.0
    hits = sum(1 for day in expected if day in completed)
    return hits / len(expected)
