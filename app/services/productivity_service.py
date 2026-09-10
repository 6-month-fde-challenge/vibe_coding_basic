"""Computing, caching and explaining the daily productivity score."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import insert, update

from app.core.logging_config import get_logger
from app.core.timeutils import Clock
from app.domain.habits.schedule import HabitSchedule
from app.domain.productivity.scoring import DayMetrics, ProductivityScore, score_day
from app.domain.productivity.weights import ProductivityWeights
from app.models.enums import CategoryKind
from app.models.habit import Habit
from app.models.journal import DailyLog
from app.schemas.common import DateRange
from app.schemas.dashboard import ProductivityScoreRead, ScoreComponentRead
from app.services.base import BaseService
from app.services.category_service import DEFAULT_LEARNING_CATEGORIES
from app.services.habit_service import schedule_of
from app.services.settings_service import SettingsService
from app.services.unit_of_work import UnitOfWork, UnitOfWorkFactory

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Targets:
    """The profile's daily targets, read once per computation."""

    sleep: float
    exercise: float
    learning: float


class ProductivityService(BaseService):
    """The score engine's application-level half.

    The arithmetic lives in :mod:`app.domain.productivity.scoring`. What
    happens here is gathering the inputs efficiently and caching the answer,
    because the calendar heatmap wants 365 of them at once.
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, clock: Clock, settings: SettingsService
    ) -> None:
        super().__init__(unit_of_work, clock)
        self._settings = settings

    def weights(self) -> ProductivityWeights:
        """Return the configured weights."""
        return self._settings.weights()

    def score_for_day(self, day: date | None = None, *, persist: bool = True) -> ProductivityScore:
        """Compute one day's score.

        Args:
            day: The day to score. Defaults to today.
            persist: Cache the result on the day's ``daily_log`` row. Turned
                off by callers that are only previewing a change to the
                weights.
        """
        target = day or self.today()
        weights = self.weights()

        with self.uow() as uow:
            metrics = self._metrics_for_day(uow, target)
            score = score_day(metrics, weights)

            if persist and score.has_data:
                log = uow.daily_logs.get_or_create(target)
                log.productivity_score = score.total
                log.score_breakdown = {"components": score.as_breakdown()}
                log.score_computed_at = self.clock.now()
                uow.commit()

        return score

    def score_read(self, day: date | None = None) -> ProductivityScoreRead:
        """One day's score in the shape the UI renders."""
        return to_read(self.score_for_day(day))

    def recompute_range(self, period: DateRange, *, only_missing: bool = False) -> int:
        """Recompute and cache every day's score across a range.

        Run after the weights change, and by the seeding script. Reads the
        habits and their logs once for the whole range rather than once per
        day.

        Args:
            period: The days to score.
            only_missing: Skip days that already have a cached score. Used
                by :meth:`ensure_scored`, which runs before the heatmap and
                the reviews so that a user who has been logging for weeks
                does not open Analytics to an empty calendar.

        Returns:
            How many days were scored.
        """
        weights = self.weights()
        scored = 0

        with self.uow() as uow:
            habits = uow.habits.list_all_habits(include_inactive=True)
            schedules = {habit.id: schedule_of(habit) for habit in habits}
            habit_logs = uow.habits.logs_between(period.start, period.end)
            targets = self._targets(uow)
            aggregates = uow.analytics.daily_aggregates(
                period.start,
                period.end,
                productive_category_ids=sorted(uow.categories.productive_ids()),
                learning_category_ids=self._learning_ids(uow),
            )

            completed_by_day: dict[date, set[int]] = {}
            for log in habit_logs:
                if log.completed:
                    completed_by_day.setdefault(log.log_date, set()).add(log.habit_id)

            # Load the whole range's rollup rows in one query, and collect
            # the writes rather than issuing them per day. Scoring a year
            # this way is a handful of statements instead of a thousand.
            existing = {
                row.log_date: row.id
                for row in uow.daily_logs.list_between(period.start, period.end)
            }
            to_insert: list[dict[str, Any]] = []
            to_update: list[dict[str, Any]] = []
            computed_at = self.clock.now()

            for day, aggregate in aggregates.days.items():
                if only_missing and aggregate.cached_score is not None:
                    continue
                due, done = _habit_counts(habits, schedules, completed_by_day.get(day, set()), day)
                metrics = DayMetrics(
                    task_rate=(
                        aggregate.tasks_completed / aggregate.tasks_planned
                        if aggregate.tasks_planned
                        else None
                    ),
                    habit_rate=(done / due) if due else None,
                    sleep_minutes=aggregate.sleep_minutes,
                    sleep_target_minutes=targets.sleep,
                    exercise_minutes=aggregate.activity_minutes or None,
                    exercise_target_minutes=targets.exercise,
                    learning_minutes=aggregate.learning_minutes or None,
                    learning_target_minutes=targets.learning,
                    focus_rating=aggregate.focus,
                )
                score = score_day(metrics, weights)
                if not score.has_data:
                    continue

                payload = {
                    "productivity_score": score.total,
                    "score_breakdown": {"components": score.as_breakdown()},
                    "score_computed_at": computed_at,
                }
                row_id = existing.get(day)
                if row_id is None:
                    to_insert.append({"user_id": self.user_id, "log_date": day, **payload})
                else:
                    to_update.append({"id": row_id, **payload})
                scored += 1

            if to_insert:
                uow.session.execute(insert(DailyLog), to_insert)
            if to_update:
                uow.session.execute(update(DailyLog), to_update)
            uow.commit()

        if scored:
            logger.info("Recomputed %d productivity scores", scored)
        return scored

    def ensure_scored(self, period: DateRange) -> int:
        """Score any day in the range that has data but no cached score.

        Cheap on the second call: the days already scored are skipped, so
        this settles into one grouped read plus a comparison.
        """
        return self.recompute_range(period, only_missing=True)

    def cached_scores(self, period: DateRange) -> dict[date, float]:
        """Return the cached scores across a range, without recomputing."""
        with self.uow() as uow:
            return uow.daily_logs.scores_between(period.start, period.end)

    # -- internals ---------------------------------------------------------

    def _metrics_for_day(self, uow: UnitOfWork, day: date) -> DayMetrics:
        """Gather one day's raw inputs."""
        targets = self._targets(uow)
        aggregates = uow.analytics.daily_aggregates(
            day,
            day,
            productive_category_ids=sorted(uow.categories.productive_ids()),
            learning_category_ids=self._learning_ids(uow),
        )
        aggregate = aggregates.days.get(day)

        habits = uow.habits.list_active()
        schedules = {habit.id: schedule_of(habit) for habit in habits}
        completed = {
            habit_id for habit_id, log in uow.habits.logs_for_day(day).items() if log.completed
        }
        due, done = _habit_counts(habits, schedules, completed, day)

        if aggregate is None:
            return DayMetrics(
                habit_rate=(done / due) if due else None,
                sleep_target_minutes=targets.sleep,
                exercise_target_minutes=targets.exercise,
                learning_target_minutes=targets.learning,
            )

        return DayMetrics(
            task_rate=(
                aggregate.tasks_completed / aggregate.tasks_planned
                if aggregate.tasks_planned
                else None
            ),
            habit_rate=(done / due) if due else None,
            sleep_minutes=aggregate.sleep_minutes,
            sleep_target_minutes=targets.sleep,
            exercise_minutes=aggregate.activity_minutes or None,
            exercise_target_minutes=targets.exercise,
            learning_minutes=aggregate.learning_minutes or None,
            learning_target_minutes=targets.learning,
            focus_rating=aggregate.focus,
        )

    def _targets(self, uow: UnitOfWork) -> _Targets:
        """Read the profile's daily targets."""
        profile = uow.profiles.get_or_raise(self.user_id)
        return _Targets(
            sleep=float(profile.target_sleep_minutes),
            exercise=float(profile.target_exercise_minutes),
            learning=float(
                profile.target_study_minutes
                + profile.target_coding_minutes
                + profile.target_teaching_minutes
            ),
        )

    def _learning_ids(self, uow: UnitOfWork) -> list[int]:
        """Resolve the time categories that count towards learning."""
        lookup = uow.categories.map_by_id(CategoryKind.TIME)
        return sorted(
            category_id
            for category_id, category in lookup.items()
            if category.name in DEFAULT_LEARNING_CATEGORIES
        )


def _habit_counts(
    habits: list[Habit],
    schedules: dict[int, HabitSchedule],
    completed_ids: set[int],
    day: date,
) -> tuple[int, int]:
    """Return ``(due, done)`` habit counts for one day."""
    due = 0
    done = 0
    for habit in habits:
        schedule = schedules.get(habit.id)
        if schedule is None or not schedule.is_expected_on(day):
            continue
        due += 1
        if habit.id in completed_ids:
            done += 1
    return due, done


def to_read(score: ProductivityScore) -> ProductivityScoreRead:
    """Convert a domain score into its read schema."""
    return ProductivityScoreRead(
        total=score.total,
        components=[
            ScoreComponentRead(
                key=component.key,
                label=component.label,
                weight=component.weight,
                achievement=component.achievement,
                points=component.points,
                detail=component.detail,
            )
            for component in score.components
        ],
        skipped=list(score.skipped),
        coverage=score.coverage,
    )


__all__ = ["ProductivityService", "to_read"]
