"""Assembling the dashboard, the reviews and the analytics pages.

This service composes the others. It owns no persistence and no arithmetic
of its own - its job is to gather the right numbers in a bounded number of
queries and hand back one read model per page, so that a Streamlit page can
be a list of ``st`` calls with no logic in it.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.logging_config import get_logger
from app.core.timeutils import Clock, to_local, week_bounds, weekday_name
from app.domain.analytics.aggregations import Bucket, build_heatmap, group_by_week
from app.domain.analytics.trends import (
    Comparison,
    best_and_worst,
    compare_periods,
    weekday_averages,
)
from app.domain.habits.streaks import summarize as summarize_streak
from app.models.enums import CategoryKind, HeatmapMetric, TaskStatus, TrendDirection
from app.models.journal import DailyLog
from app.schemas.analytics import (
    BucketRead,
    ComparisonRead,
    HabitPerformanceRead,
    HeatmapPoint,
    HeatmapRead,
    MonthlyReview,
    PeriodSummary,
    SeriesPoint,
    WeeklyReview,
)
from app.schemas.common import DateRange
from app.schemas.dashboard import (
    DailySummary,
    DashboardView,
    HabitCounts,
    TaskCounts,
    TimelineItem,
)
from app.schemas.journal import DailyLogRead
from app.schemas.sleep import SleepRead
from app.schemas.task import TaskRead
from app.services.base import BaseService
from app.services.category_service import DEFAULT_LEARNING_CATEGORIES
from app.services.goal_service import GoalService
from app.services.habit_service import HabitService, schedule_of
from app.services.health_service import HealthService
from app.services.insight_service import InsightService
from app.services.productivity_service import ProductivityService, to_read
from app.services.time_tracking_service import TimeTrackingService
from app.services.unit_of_work import UnitOfWork, UnitOfWorkFactory

logger = get_logger(__name__)

#: Names of the time categories the dashboard shows their own tile for.
STUDY_CATEGORY = "Studying"
CODING_CATEGORY = "Coding"
TEACHING_CATEGORY = "Teaching"

#: Comparison labels for the weekly review.
_COMPARISON_LABELS = {
    "average_score": "Daily score",
    "tasks_completed": "Tasks completed",
    "habit_completion_rate": "Habit consistency",
    "average_sleep_minutes": "Average sleep",
    "exercise_minutes": "Exercise",
    "study_minutes": "Study",
    "coding_minutes": "Coding",
    "teaching_minutes": "Teaching",
}


class AnalyticsService(BaseService):
    """Read models for the dashboard, weekly review and analytics pages."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        *,
        habits: HabitService,
        health: HealthService,
        goals: GoalService,
        time_tracking: TimeTrackingService,
        productivity: ProductivityService,
        insights: InsightService,
    ) -> None:
        super().__init__(unit_of_work, clock)
        self.habits = habits
        self.health = health
        self.goals = goals
        self.time_tracking = time_tracking
        self.productivity = productivity
        self.insights = insights

    # -- dashboard ---------------------------------------------------------

    def daily_summary(self, day: date | None = None) -> DailySummary:
        """Assemble everything the dashboard's overview shows."""
        target = day or self.today()
        period = DateRange(start=target, end=target)

        with self.uow() as uow:
            aggregate = uow.analytics.daily_aggregates(
                target,
                target,
                productive_category_ids=sorted(uow.categories.productive_ids()),
                learning_category_ids=self._learning_ids(uow),
            ).days.get(target)

            tasks = uow.tasks.list_for_day(target, include_overdue=False)
            overdue = uow.tasks.count_overdue(target)
            sleep_row = uow.sleep.get_for_date(target)
            daily_log = uow.daily_logs.get_for_date(target)
            journal = uow.journal.get_for_date(target)
            category_minutes = self._named_minutes(uow, period)

            sleep_read = SleepRead.model_validate(sleep_row) if sleep_row else None
            log_read = _daily_log_read(daily_log)

        completed = sum(1 for task in tasks if task.status is TaskStatus.COMPLETED)
        counted = [task for task in tasks if task.status is not TaskStatus.CANCELLED]
        habit_done, habit_due = self.habits.completion_rate_for_day(target)
        score = self.productivity.score_for_day(target)

        tracked = aggregate.tracked_minutes if aggregate else 0.0
        productive = aggregate.productive_minutes if aggregate else 0.0
        exercise = aggregate.activity_minutes if aggregate else 0.0
        sleep_minutes = sleep_read.duration_minutes if sleep_read else None
        free = None
        if sleep_minutes is not None:
            free = max(0.0, (24 * 60) - sleep_minutes - tracked - exercise)

        return DailySummary(
            log_date=target,
            weekday=weekday_name(target),
            tasks=TaskCounts(
                total=len(counted),
                completed=completed,
                pending=len(counted) - completed,
                overdue=overdue,
            ),
            habits=HabitCounts(due=habit_due, completed=habit_done, rest=0),
            sleep=sleep_read,
            sleep_minutes=sleep_minutes,
            exercise_minutes=exercise,
            study_minutes=category_minutes[STUDY_CATEGORY],
            coding_minutes=category_minutes[CODING_CATEGORY],
            teaching_minutes=category_minutes[TEACHING_CATEGORY],
            tracked_minutes=tracked,
            productive_minutes=productive,
            free_minutes=free,
            score=to_read(score),
            journal_mood=journal.mood if journal else None,
            journal_focus=journal.focus if journal else None,
            daily_log=log_read,
        )

    def dashboard(self, day: date | None = None) -> DashboardView:
        """Assemble the full dashboard payload."""
        target = day or self.today()
        period = DateRange(start=target, end=target)
        return DashboardView(
            summary=self.daily_summary(target),
            habits_today=self.habits.today_view(target),
            open_tasks=self._open_tasks(target),
            timeline=self.timeline(target),
            allocation=self.time_tracking.allocation_read(period),
            health=self.health.snapshot(target),
            generated_at=self.clock.now(),
        )

    def timeline(self, day: date | None = None) -> list[TimelineItem]:
        """Build the chronological view of one day.

        Four heterogeneous sources - sleep, activities, time entries and
        completed tasks - normalised into one sorted list. Entries with no
        recorded clock time are left out rather than guessed at.
        """
        target = day or self.today()
        items: list[TimelineItem] = []

        with self.uow() as uow:
            sleep_row = uow.sleep.get_for_date(target)
            if sleep_row is not None:
                items.append(
                    TimelineItem(
                        at=to_local(sleep_row.wake_at, self.tz).time(),
                        ends_at=None,
                        label="Woke up",
                        kind="sleep",
                        detail=f"{sleep_row.duration_minutes / 60:.1f}h asleep",
                        minutes=sleep_row.duration_minutes,
                    )
                )

            for activity in uow.activities.list_for_day(target):
                if activity.started_at is None:
                    continue
                items.append(
                    TimelineItem(
                        at=to_local(activity.started_at, self.tz).time(),
                        ends_at=(
                            to_local(activity.ended_at, self.tz).time()
                            if activity.ended_at
                            else None
                        ),
                        label=activity.category.name,
                        kind="activity",
                        detail=activity.intensity.value.title(),
                        minutes=activity.duration_minutes,
                    )
                )

            for entry in uow.time_entries.list_for_day(target):
                if entry.started_at is None:
                    continue
                items.append(
                    TimelineItem(
                        at=to_local(entry.started_at, self.tz).time(),
                        ends_at=(
                            to_local(entry.ended_at, self.tz).time() if entry.ended_at else None
                        ),
                        label=entry.category.name,
                        kind="time",
                        detail=entry.description,
                        minutes=entry.duration_minutes,
                    )
                )

            for task in uow.tasks.list_for_day(target, include_overdue=False):
                if task.status is not TaskStatus.COMPLETED or task.completed_at is None:
                    continue
                items.append(
                    TimelineItem(
                        at=to_local(task.completed_at, self.tz).time(),
                        ends_at=None,
                        label=task.title,
                        kind="task",
                        detail="Completed",
                        minutes=float(task.actual_minutes) if task.actual_minutes else None,
                    )
                )

            if sleep_row is not None and sleep_row.sleep_at is not None:
                asleep = to_local(sleep_row.sleep_at, self.tz)
                if asleep.date() == target:
                    items.append(
                        TimelineItem(
                            at=asleep.time(),
                            ends_at=None,
                            label="Went to sleep",
                            kind="sleep",
                            detail=None,
                            minutes=None,
                        )
                    )

        return sorted(items, key=lambda item: item.at)

    # -- period summaries --------------------------------------------------

    def period_summary(self, period: DateRange) -> PeriodSummary:
        """Aggregate a week, a month, or any other range."""
        # Days logged before this window was ever opened have no cached
        # score yet; fill those in before averaging them.
        self.productivity.ensure_scored(period)
        with self.uow() as uow:
            productive_ids = sorted(uow.categories.productive_ids())
            learning_ids = self._learning_ids(uow)
            aggregates = uow.analytics.daily_aggregates(
                period.start,
                period.end,
                productive_category_ids=productive_ids,
                learning_category_ids=learning_ids,
            )
            completed, planned = uow.analytics.task_totals(period.start, period.end)
            named = self._named_minutes(uow, period)
            habit_done = sum(uow.habits.completions_per_day(period.start, period.end).values())
            habit_due = self._habit_due_count(uow, period)
            sleep_avg = uow.sleep.average_minutes(period.start, period.end)

        scores = [
            aggregate.cached_score
            for aggregate in aggregates.days.values()
            if aggregate.cached_score is not None
        ]

        return PeriodSummary(
            start=period.start,
            end=period.end,
            days=period.days,
            average_score=(sum(scores) / len(scores)) if scores else None,
            tasks_completed=completed,
            tasks_total=planned,
            habit_completion_rate=(habit_done / habit_due) if habit_due else 0.0,
            average_sleep_minutes=sleep_avg,
            exercise_minutes=aggregates.total("activity_minutes"),
            study_minutes=named[STUDY_CATEGORY],
            coding_minutes=named[CODING_CATEGORY],
            teaching_minutes=named[TEACHING_CATEGORY],
            tracked_minutes=aggregates.total("tracked_minutes"),
            allocation=self.time_tracking.allocation_read(period),
        )

    def weekly_review(self, week_of: date | None = None) -> WeeklyReview:
        """Build the weekly review page's payload."""
        anchor = week_of or self.today()
        start, end = week_bounds(anchor, self._week_start())
        period = DateRange(start=start, end=end)
        previous_period = period.previous()

        summary = self.period_summary(period)
        previous = self.period_summary(previous_period)
        scores = self.productivity.cached_scores(period)
        best, worst = best_and_worst(scores)

        comparisons = compare_periods(
            _metric_map(previous),
            _metric_map(summary),
            labels=_COMPARISON_LABELS,
        )

        habit_performance = self.habit_performance(period)
        wins, problems = _wins_and_problems(comparisons, habit_performance)

        return WeeklyReview(
            summary=summary,
            previous=previous,
            comparisons=[ComparisonRead.model_validate(item) for item in comparisons],
            habit_performance=habit_performance,
            best_day=SeriesPoint(day=best.day, value=best.value) if best else None,
            worst_day=SeriesPoint(day=worst.day, value=worst.value) if worst else None,
            weekly_goals=self.goals.list_weekly(start),
            wins=wins,
            problems=problems,
            insights=self.insights.insights(period),
            recommendations=self.insights.recommendations(period),
            suggested_focus=_suggested_focus(habit_performance, comparisons),
        )

    def monthly_review(self, month_of: date | None = None) -> MonthlyReview:
        """Build the monthly analytics payload."""
        anchor = month_of or self.today()
        start = anchor.replace(day=1)
        end = min((start + timedelta(days=32)).replace(day=1) - timedelta(days=1), self.today())
        period = DateRange(start=start, end=end)

        summary = self.period_summary(period)
        scores = self.productivity.cached_scores(period)
        best, worst = best_and_worst(scores)
        buckets = group_by_week(scores, first_weekday=self._week_start())

        return MonthlyReview(
            summary=summary,
            weekly_buckets=[_bucket_read(bucket) for bucket in buckets],
            score_series=[
                SeriesPoint(day=day, value=value) for day, value in sorted(scores.items())
            ],
            habit_performance=self.habit_performance(period),
            best_day=SeriesPoint(day=best.day, value=best.value) if best else None,
            worst_day=SeriesPoint(day=worst.day, value=worst.value) if worst else None,
            weekday_averages=weekday_averages(scores),
            insights=self.insights.insights(period),
        )

    # -- habits and heatmap ------------------------------------------------

    def habit_performance(self, period: DateRange) -> list[HabitPerformanceRead]:
        """Per-habit completion over a period, ordered worst first.

        Two queries: the habits, and every log in the window. The schedules
        are then applied in memory, which is where they belong - they are
        rules, not rows.
        """
        with self.uow() as uow:
            habits = uow.habits.list_active()
            logs = uow.habits.logs_between(period.start, period.end)

        by_habit: dict[int, list[date]] = {}
        for log in logs:
            if log.completed:
                by_habit.setdefault(log.habit_id, []).append(log.log_date)

        performance: list[HabitPerformanceRead] = []
        for habit in habits:
            schedule = schedule_of(habit)
            expected = schedule.count_expected(period.start, period.end)
            logged = by_habit.get(habit.id, [])
            # Count only the days the habit was due, so a bonus completion
            # cannot report a rate above 100%.
            completed = [day for day in logged if schedule.is_expected_on(day)]
            summary = summarize_streak(logged, schedule, period.end, window_start=period.start)
            performance.append(
                HabitPerformanceRead(
                    habit_id=habit.id,
                    name=habit.name,
                    completed=len(completed),
                    expected=expected,
                    completion_rate=(len(completed) / expected) if expected else 0.0,
                    current_streak=summary.current_streak,
                    longest_streak=summary.longest_streak,
                )
            )
        return sorted(performance, key=lambda item: item.completion_rate)

    def heatmap(
        self,
        metric: HeatmapMetric = HeatmapMetric.PRODUCTIVITY,
        *,
        days: int = 365,
        end: date | None = None,
    ) -> HeatmapRead:
        """Build a GitHub-style calendar heatmap.

        One grouped query per metric over the whole window, not one per
        day.
        """
        last = end or self.today()
        first = last - timedelta(days=days - 1)
        period = DateRange(start=first, end=last)

        series = self._heatmap_series(metric, period)
        cells = build_heatmap(series, first, last, first_weekday=self._week_start())

        return HeatmapRead(
            metric=metric,
            start=first,
            end=last,
            points=[
                HeatmapPoint(
                    day=cell.day,
                    value=cell.value,
                    week_index=cell.week_index,
                    weekday=cell.weekday,
                )
                for cell in cells
            ],
            max_value=max(series.values(), default=0.0),
        )

    def score_series(self, period: DateRange) -> list[SeriesPoint]:
        """Return the daily scores as a plottable series, filling any gaps."""
        self.productivity.ensure_scored(period)
        scores = self.productivity.cached_scores(period)
        return [SeriesPoint(day=day, value=value) for day, value in sorted(scores.items())]

    # -- internals ---------------------------------------------------------

    def _heatmap_series(self, metric: HeatmapMetric, period: DateRange) -> dict[date, float]:
        """Return the date-keyed series behind one heatmap metric."""
        if metric is HeatmapMetric.PRODUCTIVITY:
            self.productivity.ensure_scored(period)
            return self.productivity.cached_scores(period)

        with self.uow() as uow:
            if metric is HeatmapMetric.HABIT_COMPLETION:
                counts = uow.habits.completions_per_day(period.start, period.end)
                return {day: float(count) for day, count in counts.items()}

            planned = uow.tasks.planned_per_day(period.start, period.end)
            completed = uow.tasks.completed_per_day(period.start, period.end)

        return {
            day: (completed.get(day, 0) / total) * 100.0 for day, total in planned.items() if total
        }

    def _open_tasks(self, day: date, limit: int = 10) -> list[TaskRead]:
        """Return the open tasks the dashboard should surface."""
        with self.uow() as uow:
            rows = uow.tasks.list_for_day(day)
        open_rows = [row for row in rows if row.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}]
        return [TaskRead.model_validate(row) for row in open_rows[:limit]]

    def _named_minutes(self, uow: UnitOfWork, period: DateRange) -> dict[str, float]:
        """Minutes for the three named time categories, in one query each."""
        lookup = {
            category.name: category.id
            for category in uow.categories.map_by_id(CategoryKind.TIME).values()
        }
        result: dict[str, float] = {}
        for name in (STUDY_CATEGORY, CODING_CATEGORY, TEACHING_CATEGORY):
            category_id = lookup.get(name)
            result[name] = (
                uow.time_entries.total_minutes_for_categories(
                    period.start, period.end, [category_id]
                )
                if category_id is not None
                else 0.0
            )
        return result

    def _habit_due_count(self, uow: UnitOfWork, period: DateRange) -> int:
        """Total habit-days expected across a period."""
        return sum(
            schedule_of(habit).count_expected(period.start, period.end)
            for habit in uow.habits.list_active()
        )

    def _learning_ids(self, uow: UnitOfWork) -> list[int]:
        """Resolve the learning time categories."""
        lookup = uow.categories.map_by_id(CategoryKind.TIME)
        return sorted(
            category_id
            for category_id, category in lookup.items()
            if category.name in DEFAULT_LEARNING_CATEGORIES
        )

    def _week_start(self) -> int:
        """The profile's first day of week."""
        with self.uow() as uow:
            return uow.profiles.get_or_raise(self.user_id).week_start


def _daily_log_read(row: DailyLog | None) -> DailyLogRead | None:
    """Convert a daily-log row to its schema, tolerating ``None``."""
    return DailyLogRead.model_validate(row) if row is not None else None


def _metric_map(summary: PeriodSummary) -> dict[str, float | None]:
    """Reduce a period summary to the metrics the comparison table shows."""
    return {
        "average_score": summary.average_score,
        "tasks_completed": float(summary.tasks_completed),
        "habit_completion_rate": summary.habit_completion_rate * 100.0,
        "average_sleep_minutes": summary.average_sleep_minutes,
        "exercise_minutes": summary.exercise_minutes,
        "study_minutes": summary.study_minutes,
        "coding_minutes": summary.coding_minutes,
        "teaching_minutes": summary.teaching_minutes,
    }


def _bucket_read(bucket: Bucket) -> BucketRead:
    """Convert a domain bucket into its read schema."""
    return BucketRead(
        key=bucket.key,
        start=bucket.start,
        end=bucket.end,
        total=bucket.total,
        average=bucket.average,
        days_with_data=bucket.days_with_data,
    )


def _wins_and_problems(
    comparisons: list[Comparison], performance: list[HabitPerformanceRead]
) -> tuple[list[str], list[str]]:
    """Turn the comparison table into two short prose lists."""
    wins: list[str] = []
    problems: list[str] = []

    for item in comparisons:
        if item.change_percent is None:
            continue
        phrase = f"{item.label} {'up' if item.change_percent > 0 else 'down'} " + (
            f"{abs(item.change_percent):.0f}% on last period"
        )
        if item.direction is TrendDirection.UP:
            wins.append(phrase)
        elif item.direction is TrendDirection.DOWN:
            problems.append(phrase)

    if performance:
        best = performance[-1]
        if best.completion_rate >= 0.8:
            wins.append(f"{best.name} held at {best.completion_rate * 100:.0f}%")
        weakest = performance[0]
        if weakest.completion_rate < 0.5:
            problems.append(f"{weakest.name} only {weakest.completion_rate * 100:.0f}%")

    return wins[:4], problems[:4]


def _suggested_focus(
    performance: list[HabitPerformanceRead], comparisons: list[Comparison]
) -> str | None:
    """Pick one thing to concentrate on next week."""
    if performance and performance[0].completion_rate < 0.6:
        weakest = performance[0]
        return (
            f"Focus on {weakest.name} - it came in at "
            f"{weakest.completion_rate * 100:.0f}% of the days it was due."
        )

    declining = [
        (item.label, item.change_percent)
        for item in comparisons
        if item.change_percent is not None and item.change_percent < -10
    ]
    if declining:
        label, change = min(declining, key=lambda pair: pair[1])
        return f"{label} fell {abs(change):.0f}% - worth a look."
    return None


__all__ = ["AnalyticsService"]
