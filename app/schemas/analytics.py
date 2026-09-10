"""Read models for analytics, reviews, insights and the heatmap."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from app.models.enums import HeatmapMetric, InsightSeverity, TrendDirection
from app.schemas.activity import AllocationRead
from app.schemas.common import ReadSchema
from app.schemas.goal import WeeklyGoalRead


class InsightRead(ReadSchema):
    """One generated observation."""

    key: str
    message: str
    severity: InsightSeverity
    evidence: dict[str, float | str] = Field(default_factory=dict)


class RecommendationRead(ReadSchema):
    """One suggested adjustment."""

    key: str
    message: str
    rationale: str
    evidence: dict[str, float | str] = Field(default_factory=dict)


class ComparisonRead(ReadSchema):
    """A metric compared across two periods."""

    label: str
    previous: float | None
    current: float | None
    change: float | None
    change_percent: float | None
    direction: TrendDirection


class SeriesPoint(ReadSchema):
    """One point of a daily series."""

    day: date
    value: float | None


class BucketRead(ReadSchema):
    """A week or month rolled up to one number."""

    key: str
    start: date
    end: date
    total: float
    average: float | None
    days_with_data: int


class HeatmapPoint(ReadSchema):
    """One square of the calendar heatmap."""

    day: date
    value: float | None
    week_index: int
    weekday: int


class HeatmapRead(ReadSchema):
    """A full heatmap grid plus the scale it should be coloured on."""

    metric: HeatmapMetric
    start: date
    end: date
    points: list[HeatmapPoint]
    max_value: float

    @property
    def has_data(self) -> bool:
        """Whether any square has a value."""
        return any(point.value is not None for point in self.points)


class HabitPerformanceRead(ReadSchema):
    """One habit's performance over a window."""

    habit_id: int
    name: str
    completed: int
    expected: int
    completion_rate: float
    current_streak: int
    longest_streak: int


class PeriodSummary(ReadSchema):
    """Aggregate figures for a week or a month."""

    start: date
    end: date
    days: int
    average_score: float | None
    tasks_completed: int
    tasks_total: int
    habit_completion_rate: float
    average_sleep_minutes: float | None
    exercise_minutes: float
    study_minutes: float
    coding_minutes: float
    teaching_minutes: float
    tracked_minutes: float
    allocation: AllocationRead


class WeeklyReview(ReadSchema):
    """The weekly review page's payload."""

    summary: PeriodSummary
    previous: PeriodSummary | None
    comparisons: list[ComparisonRead]
    habit_performance: list[HabitPerformanceRead]
    best_day: SeriesPoint | None
    worst_day: SeriesPoint | None
    weekly_goals: list[WeeklyGoalRead]
    wins: list[str]
    problems: list[str]
    insights: list[InsightRead]
    recommendations: list[RecommendationRead]
    suggested_focus: str | None


class MonthlyReview(ReadSchema):
    """The monthly analytics payload."""

    summary: PeriodSummary
    weekly_buckets: list[BucketRead]
    score_series: list[SeriesPoint]
    habit_performance: list[HabitPerformanceRead]
    best_day: SeriesPoint | None
    worst_day: SeriesPoint | None
    weekday_averages: dict[int, float]
    insights: list[InsightRead]
