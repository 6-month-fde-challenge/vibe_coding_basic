"""Long-running goals, their milestones, and weekly quantitative targets."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin
from app.database.types import str_enum
from app.models.enums import GoalCategory, GoalStatus, TaskPriority, WeeklyMetric

if TYPE_CHECKING:
    from app.models.user import UserProfile


class Goal(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """Something being worked towards over weeks or months."""

    __tablename__ = "goal"
    __table_args__ = (
        Index("ix_goal_user_status", "user_id", "status"),
        Index("ix_goal_user_target_date", "user_id", "target_date"),
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="progress_range"),
        CheckConstraint(
            "target_date IS NULL OR start_date IS NULL OR target_date >= start_date",
            name="date_order",
        ),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[GoalCategory] = mapped_column(
        str_enum(GoalCategory), nullable=False, default=GoalCategory.PERSONAL, index=True
    )
    status: Mapped[GoalStatus] = mapped_column(
        str_enum(GoalStatus), nullable=False, default=GoalStatus.NOT_STARTED
    )
    priority: Mapped[TaskPriority] = mapped_column(
        str_enum(TaskPriority), nullable=False, default=TaskPriority.MEDIUM
    )
    start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    #: Manual override. When milestones exist the service recomputes this
    #: from them, so the two can never drift apart in the UI.
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    user: Mapped[UserProfile] = relationship(back_populates="goals")
    milestones: Mapped[list[GoalMilestone]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GoalMilestone.sort_order",
    )

    def __repr__(self) -> str:
        """Return a debugging representation naming the goal and progress."""
        return f"<Goal id={self.id} title={self.title[:30]!r} progress={self.progress_percent:.0f}>"


class GoalMilestone(IdMixin, TimestampMixin, Base):
    """A checkpoint on the way to a goal."""

    __tablename__ = "goal_milestone"
    __table_args__ = (Index("ix_goal_milestone_goal_order", "goal_id", "sort_order"),)

    goal_id: Mapped[int] = mapped_column(
        ForeignKey("goal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    due_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    goal: Mapped[Goal] = relationship(back_populates="milestones")

    def __repr__(self) -> str:
        """Return a debugging representation naming the milestone."""
        return f"<GoalMilestone goal_id={self.goal_id} done={self.is_completed}>"


class WeeklyGoal(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """A numeric target for one week, fed by the daily records.

    "Study 10 hours this week" is not a goal with milestones; it is a sum
    over the week's time entries compared against a number. Keeping it in its
    own small table means the weekly review can answer it with one query.
    """

    __tablename__ = "weekly_goal"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", "metric", name="uq_weekly_goal_user_week_metric"),
        Index("ix_weekly_goal_user_week", "user_id", "week_start"),
        CheckConstraint("target_value > 0", name="target_positive"),
    )

    #: Monday of the week this target applies to.
    week_start: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    metric: Mapped[WeeklyMetric] = mapped_column(str_enum(WeeklyMetric), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="weekly_goals")

    def __repr__(self) -> str:
        """Return a debugging representation naming week and metric."""
        return f"<WeeklyGoal week={self.week_start} metric={self.metric}>"
