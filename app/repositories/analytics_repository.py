"""Cross-table aggregate reads.

The per-entity repositories each know how to aggregate their own table. This
one composes them into the shape the analytics service actually asks for -
"give me every day in this range, with its tasks, habits, sleep and tracked
minutes" - using a fixed number of grouped queries regardless of how many
days are requested.

The alternative, a loop that asks each repository once per day, is 365 * 6
round trips for a year of heatmap. That is the N+1 the brief forbids, just
spread over a calendar instead of a list.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models.enums import TaskStatus
from app.repositories.activity_repository import ActivityRepository
from app.repositories.habit_repository import HabitRepository
from app.repositories.journal_repository import DailyLogRepository, JournalRepository
from app.repositories.sleep_repository import SleepRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.time_entry_repository import TimeEntryRepository


@dataclass(slots=True)
class DailyAggregate:
    """Everything known about one day, in numbers.

    Attributes:
        day: The date.
        tasks_planned: Non-cancelled tasks due that day.
        tasks_completed: Of those, how many were finished.
        habits_completed: Habit logs marked complete.
        sleep_minutes: Minutes slept, if a night was recorded.
        activity_minutes: Minutes of logged exercise.
        tracked_minutes: Minutes across all time entries.
        productive_minutes: Minutes in categories flagged productive.
        learning_minutes: Minutes in the learning categories.
        mood: Journal mood rating.
        focus: Journal focus rating.
        cached_score: Previously computed productivity score, if any.
    """

    day: date
    tasks_planned: int = 0
    tasks_completed: int = 0
    habits_completed: int = 0
    sleep_minutes: float | None = None
    activity_minutes: float = 0.0
    tracked_minutes: float = 0.0
    productive_minutes: float = 0.0
    learning_minutes: float = 0.0
    mood: int | None = None
    focus: int | None = None
    cached_score: float | None = None


@dataclass(slots=True)
class RangeAggregate:
    """A whole range of days, plus the totals across it."""

    start: date
    end: date
    days: dict[date, DailyAggregate] = field(default_factory=dict)

    def series(self, attribute: str) -> dict[date, float]:
        """Return one attribute as a date-keyed series, skipping ``None``."""
        out: dict[date, float] = {}
        for day, aggregate in self.days.items():
            value = getattr(aggregate, attribute)
            if value is not None:
                out[day] = float(value)
        return out

    def total(self, attribute: str) -> float:
        """Sum one attribute across the range."""
        return sum(float(getattr(aggregate, attribute) or 0.0) for aggregate in self.days.values())


class AnalyticsRepository:
    """Reads that span several tables.

    Composed from the entity repositories rather than reaching into the
    session directly, so that each table's query rules stay in one place.
    """

    def __init__(self, session: Session, user_id: int) -> None:
        self.session = session
        self.user_id = user_id
        self.tasks = TaskRepository(session, user_id)
        self.habits = HabitRepository(session, user_id)
        self.sleep = SleepRepository(session, user_id)
        self.activities = ActivityRepository(session, user_id)
        self.time_entries = TimeEntryRepository(session, user_id)
        self.journal = JournalRepository(session, user_id)
        self.daily_logs = DailyLogRepository(session, user_id)

    def daily_aggregates(
        self,
        start: date,
        end: date,
        *,
        productive_category_ids: Sequence[int] = (),
        learning_category_ids: Sequence[int] = (),
    ) -> RangeAggregate:
        """Build a per-day aggregate for an inclusive date range.

        Issues eight grouped queries in total, whatever the length of the
        range.

        Args:
            start: First day.
            end: Last day.
            productive_category_ids: Time categories counted as productive.
            learning_category_ids: Time categories counted as learning.

        Returns:
            A :class:`RangeAggregate` with one entry per day that had any
            data. Days with nothing recorded are absent; callers that need a
            dense series fill the gaps with
            :func:`app.domain.analytics.aggregations.fill_missing_days`.
        """
        planned = self.tasks.planned_per_day(start, end)
        completed = self.tasks.completed_per_day(start, end)
        habits = self.habits.completions_per_day(start, end)
        sleep = self.sleep.duration_per_day(start, end)
        activity = self.activities.minutes_per_day(start, end)
        tracked = self.time_entries.minutes_per_day(start, end)
        productive = self.time_entries.minutes_per_day_for_categories(
            start, end, productive_category_ids
        )
        learning = self.time_entries.minutes_per_day_for_categories(
            start, end, learning_category_ids
        )
        ratings = self.journal.ratings_between(start, end)
        scores = self.daily_logs.scores_between(start, end)

        touched: set[date] = set()
        for source in (planned, completed, habits, sleep, activity, tracked, ratings, scores):
            touched.update(source)

        days = {
            day: DailyAggregate(
                day=day,
                tasks_planned=planned.get(day, 0),
                tasks_completed=completed.get(day, 0),
                habits_completed=habits.get(day, 0),
                sleep_minutes=sleep.get(day),
                activity_minutes=activity.get(day, 0.0),
                tracked_minutes=tracked.get(day, 0.0),
                productive_minutes=productive.get(day, 0.0),
                learning_minutes=learning.get(day, 0.0),
                mood=ratings.get(day, (None, None))[0],
                focus=ratings.get(day, (None, None))[1],
                cached_score=scores.get(day),
            )
            for day in sorted(touched)
        }
        return RangeAggregate(start=start, end=end, days=days)

    def task_totals(self, start: date, end: date) -> tuple[int, int]:
        """Return ``(completed, planned)`` task counts over a range."""
        by_status = self.tasks.count_by_status(start, end)
        planned = sum(
            count for status, count in by_status.items() if status is not TaskStatus.CANCELLED
        )
        return by_status.get(TaskStatus.COMPLETED, 0), planned
