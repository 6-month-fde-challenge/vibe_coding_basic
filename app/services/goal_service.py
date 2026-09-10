"""Goal and weekly-goal business rules."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.errors import NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.core.timeutils import week_start
from app.domain.goals.progress import (
    GoalPace,
    MilestoneSnapshot,
    compute_pace,
    derive_status,
    progress_from_milestones,
    validate_progress,
)
from app.models.enums import CategoryKind, GoalStatus, WeeklyMetric
from app.models.goal import Goal, GoalMilestone, WeeklyGoal
from app.schemas.common import Page, Pagination
from app.schemas.goal import (
    GoalCreate,
    GoalPaceRead,
    GoalRead,
    GoalUpdate,
    MilestoneInput,
    WeeklyGoalInput,
    WeeklyGoalRead,
)
from app.services.base import BaseService
from app.services.unit_of_work import UnitOfWork

logger = get_logger(__name__)


class GoalService(BaseService):
    """Longer-running goals, their milestones, and weekly numeric targets."""

    # -- goals -------------------------------------------------------------

    def list_goals(self, *, open_only: bool = False) -> list[GoalRead]:
        """Return goals, optionally only the ones still in play."""
        with self.uow() as uow:
            rows = uow.goals.list_open() if open_only else uow.goals.list_all_goals()
            return [GoalRead.model_validate(row) for row in rows]

    def get(self, goal_id: int) -> GoalRead:
        """Return one goal with its milestones."""
        with self.uow() as uow:
            return GoalRead.model_validate(uow.goals.get_with_milestones(goal_id))

    def history(self, pagination: Pagination) -> Page[GoalRead]:
        """Return goals one page at a time."""
        with self.uow() as uow:
            rows, total = uow.goals.page(pagination)
            return Page[GoalRead](
                items=[GoalRead.model_validate(row) for row in rows],
                total=total,
                limit=pagination.limit,
                offset=pagination.offset,
            )

    def create(self, payload: GoalCreate) -> GoalRead:
        """Create a goal and its milestones."""
        with self.uow() as uow:
            goal = Goal(
                user_id=self.user_id,
                title=payload.title,
                description=payload.description,
                category=payload.category,
                priority=payload.priority,
                status=GoalStatus.NOT_STARTED,
                start_date=payload.start_date or self.today(),
                target_date=payload.target_date,
                progress_percent=0.0,
            )
            uow.goals.add(goal)

            for order, milestone in enumerate(payload.milestones):
                uow.goals.add_milestone(
                    GoalMilestone(
                        goal_id=goal.id,
                        title=milestone.title,
                        due_date=milestone.due_date,
                        is_completed=milestone.is_completed,
                        completed_at=self.clock.now() if milestone.is_completed else None,
                        sort_order=milestone.sort_order or (order + 1) * 10,
                    )
                )

            self._recompute(uow, goal)
            uow.commit()
            logger.info("Goal %s created", goal.id)
            return GoalRead.model_validate(uow.goals.get_with_milestones(goal.id))

    def update(self, goal_id: int, payload: GoalUpdate) -> GoalRead:
        """Apply a partial edit to a goal."""
        with self.uow() as uow:
            goal = uow.goals.get_or_raise(goal_id)
            changes = payload.model_dump(exclude_unset=True)

            if "progress_percent" in changes and changes["progress_percent"] is not None:
                validate_progress(changes["progress_percent"])

            for field, value in changes.items():
                setattr(goal, field, value)

            if goal.start_date and goal.target_date and goal.target_date < goal.start_date:
                raise ValidationError(
                    "The target date is before the start date",
                    field="target_date",
                    value=goal.target_date.isoformat(),
                )

            self._recompute(uow, goal)
            uow.commit()
            logger.info("Goal %s updated", goal_id)
            return GoalRead.model_validate(uow.goals.get_with_milestones(goal_id))

    def delete(self, goal_id: int) -> None:
        """Delete a goal and its milestones."""
        with self.uow() as uow:
            goal = uow.goals.get_or_raise(goal_id)
            uow.goals.delete(goal)
            uow.commit()
            logger.info("Goal %s deleted", goal_id)

    def pace(self, goal_id: int) -> GoalPaceRead:
        """Return whether a goal is keeping up with its deadline."""
        with self.uow() as uow:
            goal = uow.goals.get_or_raise(goal_id)
            result = self._pace_of(goal)
        return GoalPaceRead(
            goal_id=goal_id,
            elapsed_fraction=result.elapsed_fraction,
            progress_fraction=result.progress_fraction,
            days_remaining=result.days_remaining,
            is_behind=result.is_behind,
            is_overdue=result.is_overdue,
        )

    # -- milestones --------------------------------------------------------

    def add_milestone(self, goal_id: int, payload: MilestoneInput) -> GoalRead:
        """Add a milestone and recompute the goal's progress."""
        with self.uow() as uow:
            goal = uow.goals.get_or_raise(goal_id)
            uow.goals.add_milestone(
                GoalMilestone(
                    goal_id=goal.id,
                    title=payload.title,
                    due_date=payload.due_date,
                    is_completed=payload.is_completed,
                    completed_at=self.clock.now() if payload.is_completed else None,
                    sort_order=payload.sort_order,
                )
            )
            self._recompute(uow, goal)
            uow.commit()
            return GoalRead.model_validate(uow.goals.get_with_milestones(goal_id))

    def toggle_milestone(self, milestone_id: int) -> GoalRead:
        """Tick or untick a milestone and recompute the goal.

        Raises:
            NotFoundError: If the milestone does not exist or belongs to
                another profile's goal.
        """
        with self.uow() as uow:
            milestone = uow.goals.get_milestone(milestone_id)
            if milestone is None:
                raise NotFoundError("Milestone", milestone_id)
            goal = uow.goals.get_or_raise(milestone.goal_id)

            milestone.is_completed = not milestone.is_completed
            milestone.completed_at = self.clock.now() if milestone.is_completed else None

            self._recompute(uow, goal)
            uow.commit()
            logger.info("Milestone %s toggled to %s", milestone_id, milestone.is_completed)
            return GoalRead.model_validate(uow.goals.get_with_milestones(goal.id))

    def delete_milestone(self, milestone_id: int) -> GoalRead:
        """Remove a milestone and recompute the goal."""
        with self.uow() as uow:
            milestone = uow.goals.get_milestone(milestone_id)
            if milestone is None:
                raise NotFoundError("Milestone", milestone_id)
            goal = uow.goals.get_or_raise(milestone.goal_id)

            uow.goals.delete_milestone(milestone)
            self._recompute(uow, goal)
            uow.commit()
            return GoalRead.model_validate(uow.goals.get_with_milestones(goal.id))

    # -- weekly goals ------------------------------------------------------

    def list_weekly(self, week: date | None = None) -> list[WeeklyGoalRead]:
        """Return the week's numeric targets, each with its progress.

        Progress is measured from the same daily records the rest of the
        app uses, so a weekly study target is met by logging study time -
        not by ticking the goal off separately.
        """
        start = week_start(week or self.today())
        with self.uow() as uow:
            targets = uow.weekly_goals.list_for_week(start)
            if not targets:
                return []
            achieved = self._achievements(uow, start, [target.metric for target in targets])

        return [
            WeeklyGoalRead(
                id=target.id,
                week_start=target.week_start,
                metric=target.metric,
                target_value=target.target_value,
                achieved_value=achieved.get(target.metric, 0.0),
                notes=target.notes,
            )
            for target in targets
        ]

    def set_weekly(self, payload: WeeklyGoalInput) -> WeeklyGoalRead:
        """Set or replace one weekly target."""
        start = week_start(payload.week_start)
        with self.uow() as uow:
            saved = uow.weekly_goals.upsert(
                WeeklyGoal(
                    user_id=self.user_id,
                    week_start=start,
                    metric=payload.metric,
                    target_value=payload.target_value,
                    notes=payload.notes,
                )
            )
            achieved = self._achievements(uow, start, [payload.metric])
            uow.commit()
            logger.info("Weekly goal set for %s (%s)", start.isoformat(), payload.metric.value)
            return WeeklyGoalRead(
                id=saved.id,
                week_start=saved.week_start,
                metric=saved.metric,
                target_value=saved.target_value,
                achieved_value=achieved.get(saved.metric, 0.0),
                notes=saved.notes,
            )

    def delete_weekly(self, weekly_goal_id: int) -> None:
        """Remove a weekly target."""
        with self.uow() as uow:
            target = uow.weekly_goals.get_or_raise(weekly_goal_id)
            uow.weekly_goals.delete(target)
            uow.commit()

    # -- internals ---------------------------------------------------------

    def _pace_of(self, goal: Goal) -> GoalPace:
        """Compute pace for one loaded goal."""
        return compute_pace(
            progress_percent=goal.progress_percent,
            start_date=goal.start_date,
            target_date=goal.target_date,
            today=self.today(),
            status=goal.status,
        )

    def _recompute(self, uow: UnitOfWork, goal: Goal) -> None:
        """Recompute progress from milestones, then derive the status.

        A goal with milestones takes its progress from them, so the bar and
        the ticks can never disagree. A goal without milestones keeps the
        percentage the user typed - which is why
        :func:`progress_from_milestones` returns ``None`` rather than zero
        for an empty list.
        """
        uow.flush()
        milestones = uow.goals.milestones_for(goal.id)
        derived = progress_from_milestones(
            [
                MilestoneSnapshot(title=item.title, is_completed=item.is_completed)
                for item in milestones
            ]
        )
        if derived is not None:
            goal.progress_percent = derived

        goal.status = derive_status(goal.progress_percent, goal.status)
        goal.completed_at = self.clock.now() if goal.status is GoalStatus.COMPLETED else None

    def _achievements(
        self, uow: UnitOfWork, week: date, metrics: list[WeeklyMetric]
    ) -> dict[WeeklyMetric, float]:
        """Measure the week's actual figures for the requested metrics."""
        end = week + timedelta(days=6)
        results: dict[WeeklyMetric, float] = {}
        category_names = {
            WeeklyMetric.STUDY_MINUTES: "Studying",
            WeeklyMetric.CODING_MINUTES: "Coding",
            WeeklyMetric.TEACHING_MINUTES: "Teaching",
        }

        for metric in metrics:
            if metric in category_names:
                category = uow.categories.get_by_name(CategoryKind.TIME, category_names[metric])
                results[metric] = (
                    uow.time_entries.total_minutes_for_categories(week, end, [category.id])
                    if category
                    else 0.0
                )
            elif metric is WeeklyMetric.EXERCISE_MINUTES:
                results[metric] = uow.activities.total_minutes(week, end)
            elif metric is WeeklyMetric.SLEEP_MINUTES:
                results[metric] = sum(uow.sleep.duration_per_day(week, end).values())
            elif metric is WeeklyMetric.TASKS_COMPLETED:
                results[metric] = float(sum(uow.tasks.completed_per_day(week, end).values()))
            elif metric is WeeklyMetric.HABIT_COMPLETIONS:
                results[metric] = float(sum(uow.habits.completions_per_day(week, end).values()))
        return results


__all__ = ["GoalService"]
