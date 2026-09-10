"""Gathering the facts the insight rules run against.

The rules themselves are pure functions in
:mod:`app.domain.analytics.insights`. This service's only job is to fill in
an :class:`~app.domain.analytics.insights.InsightContext` from the database
- which means every rule stays unit-testable without one, and swapping in an
LLM-backed generator later is a matter of adding another producer over the
same context.
"""

from __future__ import annotations

from datetime import date

from app.core.logging_config import get_logger
from app.core.timeutils import Clock
from app.domain.analytics.insights import (
    HabitFacts,
    InsightContext,
    generate_insights,
    generate_recommendations,
)
from app.domain.analytics.statistics import mean
from app.domain.analytics.trends import weekday_averages
from app.domain.habits.streaks import summarize as summarize_streak
from app.models.enums import CategoryKind
from app.schemas.analytics import InsightRead, RecommendationRead
from app.schemas.common import DateRange
from app.services.base import BaseService
from app.services.habit_service import schedule_of
from app.services.productivity_service import ProductivityService
from app.services.sleep_service import SleepService
from app.services.unit_of_work import UnitOfWork, UnitOfWorkFactory

logger = get_logger(__name__)

#: Weekday numbers treated as the weekend for the study comparison.
_WEEKEND = {5, 6}


class InsightService(BaseService):
    """Deterministic insights and recommendations."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        *,
        productivity: ProductivityService,
        sleep: SleepService,
    ) -> None:
        super().__init__(unit_of_work, clock)
        self.productivity = productivity
        self.sleep = sleep

    def build_context(self, period: DateRange) -> InsightContext:
        """Gather every fact the rules are allowed to see."""
        previous = period.previous()
        today = self.today()

        scores = self.productivity.cached_scores(period)

        with self.uow() as uow:
            habits = self._habit_facts(uow, period, today)
            study_weekday, study_weekend = self._study_split(uow, period)
            current_categories = self._category_minutes(uow, period)
            previous_categories = self._category_minutes(uow, previous)
            completion_by_count = self._completion_by_task_count(uow, period)
            planned_today = uow.tasks.planned_per_day(today, today).get(today)
            profile = uow.profiles.get_or_raise(self.user_id)
            sleep_target = float(profile.target_sleep_minutes)

        return InsightContext(
            today=today,
            productivity_by_day=scores,
            weekday_productivity=weekday_averages(scores),
            habits=habits,
            sleep_avg_current=self.sleep.average_minutes(period),
            sleep_avg_previous=self.sleep.average_minutes(previous),
            sleep_target_minutes=sleep_target,
            sleep_nights_below_target=self.sleep.nights_below_target(period),
            study_weekday_avg=study_weekday,
            study_weekend_avg=study_weekend,
            completion_by_task_count=completion_by_count,
            tasks_planned_today=planned_today,
            minutes_by_category_current=current_categories,
            minutes_by_category_previous=previous_categories,
            bedtime_shift_minutes=self.sleep.bedtime_shift(period),
        )

    def insights(self, period: DateRange, *, limit: int = 6) -> list[InsightRead]:
        """Run the insight rules over a period."""
        produced = generate_insights(self.build_context(period), limit=limit)
        logger.debug("Generated %d insights", len(produced))
        return [
            InsightRead(
                key=item.key,
                message=item.message,
                severity=item.severity,
                evidence=item.evidence,
            )
            for item in produced
        ]

    def recommendations(self, period: DateRange, *, limit: int = 3) -> list[RecommendationRead]:
        """Run the recommendation rules over a period."""
        produced = generate_recommendations(self.build_context(period), limit=limit)
        return [
            RecommendationRead(
                key=item.key,
                message=item.message,
                rationale=item.rationale,
                evidence=item.evidence,
            )
            for item in produced
        ]

    # -- fact gathering ----------------------------------------------------

    def _habit_facts(self, uow: UnitOfWork, period: DateRange, today: date) -> list[HabitFacts]:
        """Per-habit figures, from two queries rather than four per habit."""
        habits = uow.habits.list_active()
        if not habits:
            return []

        logs = uow.habits.logs_between(period.start, period.end)
        completed_by_habit: dict[int, list[date]] = {}
        for log in logs:
            if log.completed:
                completed_by_habit.setdefault(log.habit_id, []).append(log.log_date)

        facts: list[HabitFacts] = []
        for habit in habits:
            schedule = schedule_of(habit)
            expected = schedule.count_expected(period.start, period.end)
            completed = completed_by_habit.get(habit.id, [])
            summary = summarize_streak(completed, schedule, today, window_start=period.start)
            facts.append(
                HabitFacts(
                    name=habit.name,
                    current_streak=summary.current_streak,
                    longest_streak=summary.longest_streak,
                    completion_rate=(len(completed) / expected) if expected else 0.0,
                    consecutive_misses=uow.habits.consecutive_misses(habit.id, today),
                )
            )
        return facts

    def _study_split(self, uow: UnitOfWork, period: DateRange) -> tuple[float | None, float | None]:
        """Average daily study minutes on weekdays against weekends."""
        category = uow.categories.get_by_name(CategoryKind.TIME, "Studying")
        if category is None:
            return None, None

        per_day = uow.time_entries.minutes_per_day_for_categories(
            period.start, period.end, [category.id]
        )
        weekday_values = [
            minutes for day, minutes in per_day.items() if day.weekday() not in _WEEKEND
        ]
        weekend_values = [minutes for day, minutes in per_day.items() if day.weekday() in _WEEKEND]
        return mean(weekday_values), mean(weekend_values)

    def _category_minutes(self, uow: UnitOfWork, period: DateRange) -> dict[str, float]:
        """Total minutes per time-category name across a period."""
        return {
            name: minutes
            for _, name, _, minutes in uow.time_entries.minutes_by_category(
                period.start, period.end
            )
        }

    def _completion_by_task_count(self, uow: UnitOfWork, period: DateRange) -> dict[int, float]:
        """Completion rate grouped by how many tasks were planned that day.

        This is what turns "you complete 87% of tasks when you plan fewer
        than 8 a day" from a slogan into a measurement.
        """
        planned = uow.tasks.planned_per_day(period.start, period.end)
        completed = uow.tasks.completed_per_day(period.start, period.end)

        buckets: dict[int, list[float]] = {}
        for day, total in planned.items():
            if total <= 0:
                continue
            buckets.setdefault(total, []).append(completed.get(day, 0) / total)

        # A single day is not evidence; require at least two before the rule
        # is allowed to draw a conclusion from a bucket.
        return {
            count: sum(values) / len(values)
            for count, values in buckets.items()
            if len(values) >= 2
        }


__all__ = ["InsightService"]
