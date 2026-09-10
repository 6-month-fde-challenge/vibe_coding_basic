"""Persistence for goals, milestones and weekly targets."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.enums import GoalStatus, WeeklyMetric
from app.models.goal import Goal, GoalMilestone, WeeklyGoal
from app.repositories.base import UserScopedRepository
from app.schemas.common import Pagination


class GoalRepository(UserScopedRepository[Goal]):
    """Goal and milestone queries."""

    model = Goal

    def get_with_milestones(self, goal_id: int) -> Goal:
        """Return one goal with its milestones already loaded.

        Raises:
            NotFoundError: If the goal does not exist or is not owned.
        """
        goal = self.get_or_raise(goal_id)
        # Touch the collection inside the session so the caller can read it
        # after the schema conversion, without a lazy load firing later.
        _ = list(goal.milestones)
        return goal

    def list_open(self) -> list[Goal]:
        """Return goals still being worked on, soonest deadline first."""
        statement = (
            self.scoped()
            .where(Goal.status.in_([GoalStatus.NOT_STARTED, GoalStatus.IN_PROGRESS]))
            .options(selectinload(Goal.milestones))
            .order_by(Goal.target_date.is_(None), Goal.target_date, Goal.priority.desc())
        )
        return list(self.session.scalars(statement))

    def list_all_goals(self, *, statuses: list[GoalStatus] | None = None) -> list[Goal]:
        """Return goals, optionally filtered by status."""
        statement = self.scoped().options(selectinload(Goal.milestones))
        if statuses:
            statement = statement.where(Goal.status.in_(statuses))
        statement = statement.order_by(Goal.target_date.is_(None), Goal.target_date, Goal.id)
        return list(self.session.scalars(statement))

    def page(self, pagination: Pagination) -> tuple[list[Goal], int]:
        """One page of goals, newest first."""
        statement = self.scoped().options(selectinload(Goal.milestones)).order_by(Goal.id.desc())
        return self.paginate(statement, pagination)

    def add_milestone(self, milestone: GoalMilestone) -> GoalMilestone:
        """Insert a milestone."""
        self.session.add(milestone)
        self.session.flush()
        return milestone

    def get_milestone(self, milestone_id: int) -> GoalMilestone | None:
        """Return one milestone by id."""
        return self.session.get(GoalMilestone, milestone_id)

    def delete_milestone(self, milestone: GoalMilestone) -> None:
        """Remove a milestone."""
        self.session.delete(milestone)
        self.session.flush()

    def milestones_for(self, goal_id: int) -> list[GoalMilestone]:
        """Return one goal's milestones in display order."""
        statement = (
            select(GoalMilestone)
            .where(GoalMilestone.goal_id == goal_id)
            .order_by(GoalMilestone.sort_order, GoalMilestone.id)
        )
        return list(self.session.scalars(statement))


class WeeklyGoalRepository(UserScopedRepository[WeeklyGoal]):
    """Weekly numeric targets."""

    model = WeeklyGoal

    def list_for_week(self, week_start: date) -> list[WeeklyGoal]:
        """Return the targets set for one week."""
        statement = self.scoped().where(WeeklyGoal.week_start == week_start)
        return list(self.session.scalars(statement.order_by(WeeklyGoal.metric)))

    def get_for_metric(self, week_start: date, metric: WeeklyMetric) -> WeeklyGoal | None:
        """Return one week's target for one metric."""
        statement = self.scoped().where(
            WeeklyGoal.week_start == week_start, WeeklyGoal.metric == metric
        )
        return self.session.scalars(statement).first()

    def upsert(self, goal: WeeklyGoal) -> WeeklyGoal:
        """Insert a weekly target, or update the existing one."""
        existing = self.get_for_metric(goal.week_start, goal.metric)
        if existing is None:
            return self.add(goal)
        existing.target_value = goal.target_value
        existing.notes = goal.notes
        self.flush()
        return existing

    def list_between(self, start: date, end: date) -> list[WeeklyGoal]:
        """Return targets whose week starts inside a range."""
        statement = (
            self.scoped()
            .where(WeeklyGoal.week_start >= start, WeeklyGoal.week_start <= end)
            .order_by(WeeklyGoal.week_start)
        )
        return list(self.session.scalars(statement))
