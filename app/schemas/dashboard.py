"""Read models for the dashboard, the timeline and the daily summary."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import Field

from app.schemas.activity import AllocationRead
from app.schemas.common import ReadSchema
from app.schemas.habit import HabitTodayRead
from app.schemas.health import HealthSnapshot
from app.schemas.journal import DailyLogRead
from app.schemas.sleep import SleepRead
from app.schemas.task import TaskRead


class ScoreComponentRead(ReadSchema):
    """One line of the productivity score's explanation."""

    key: str
    label: str
    weight: float
    achievement: float
    points: float
    detail: str


class ProductivityScoreRead(ReadSchema):
    """A day's score with the arithmetic behind it."""

    total: float
    components: list[ScoreComponentRead] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    coverage: float = 0.0

    @property
    def has_data(self) -> bool:
        """Whether anything contributed to the score."""
        return bool(self.components)


class TimelineItem(ReadSchema):
    """One event on the chronological day view.

    Sources are heterogeneous - a sleep record, an activity, a time entry, a
    completed task - so the timeline normalises them into this one shape
    rather than making the page branch per type.
    """

    at: time
    ends_at: time | None
    label: str
    kind: str
    detail: str | None = None
    minutes: float | None = None


class TaskCounts(ReadSchema):
    """Task tallies for one day."""

    total: int = 0
    completed: int = 0
    pending: int = 0
    overdue: int = 0

    @property
    def rate(self) -> float:
        """Completed over total, 0 when there are no tasks."""
        return self.completed / self.total if self.total else 0.0


class HabitCounts(ReadSchema):
    """Habit tallies for one day."""

    due: int = 0
    completed: int = 0
    rest: int = 0

    @property
    def rate(self) -> float:
        """Completed over due, 0 when nothing was due."""
        return self.completed / self.due if self.due else 0.0


class DailySummary(ReadSchema):
    """Everything the dashboard shows for one day.

    Assembled by :class:`~app.services.analytics_service.AnalyticsService`
    in a fixed number of queries, so the page renders without issuing one
    query per widget.
    """

    log_date: date
    weekday: str
    tasks: TaskCounts
    habits: HabitCounts
    sleep: SleepRead | None
    sleep_minutes: float | None
    exercise_minutes: float
    study_minutes: float
    coding_minutes: float
    teaching_minutes: float
    tracked_minutes: float
    productive_minutes: float
    free_minutes: float | None
    score: ProductivityScoreRead
    journal_mood: int | None
    journal_focus: int | None
    daily_log: DailyLogRead | None

    @property
    def has_any_data(self) -> bool:
        """Whether anything at all was recorded on this day."""
        return bool(
            self.tasks.total
            or self.habits.due
            or self.sleep
            or self.tracked_minutes
            or self.daily_log
        )


class DashboardView(ReadSchema):
    """The complete dashboard payload for one day."""

    summary: DailySummary
    habits_today: list[HabitTodayRead]
    open_tasks: list[TaskRead]
    timeline: list[TimelineItem]
    allocation: AllocationRead
    health: HealthSnapshot
    generated_at: datetime
