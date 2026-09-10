"""Goal, milestone and weekly-goal schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, model_validator

from app.models.enums import GoalCategory, GoalStatus, TaskPriority, WeeklyMetric
from app.schemas.common import ReadSchema, Schema


class MilestoneInput(Schema):
    """A checkpoint on the way to a goal."""

    title: str = Field(min_length=1, max_length=200)
    due_date: date | None = None
    is_completed: bool = False
    sort_order: int = 100


class GoalCreate(Schema):
    """Fields accepted when creating a goal."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: GoalCategory = GoalCategory.PERSONAL
    priority: TaskPriority = TaskPriority.MEDIUM
    start_date: date | None = None
    target_date: date | None = None
    milestones: list[MilestoneInput] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _dates_ordered(self) -> GoalCreate:
        """Reject a target date before the start date."""
        if self.start_date and self.target_date and self.target_date < self.start_date:
            msg = "The target date is before the start date."
            raise ValueError(msg)
        return self


class GoalUpdate(Schema):
    """Fields accepted when editing a goal."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: GoalCategory | None = None
    priority: TaskPriority | None = None
    status: GoalStatus | None = None
    start_date: date | None = None
    target_date: date | None = None
    progress_percent: float | None = Field(default=None, ge=0, le=100)


class MilestoneRead(ReadSchema):
    """A stored milestone."""

    id: int
    goal_id: int
    title: str
    is_completed: bool
    completed_at: datetime | None
    due_date: date | None
    sort_order: int


class GoalRead(ReadSchema):
    """A goal as the UI sees it."""

    id: int
    title: str
    description: str | None
    category: GoalCategory
    status: GoalStatus
    priority: TaskPriority
    start_date: date | None
    target_date: date | None
    completed_at: datetime | None
    progress_percent: float
    milestones: list[MilestoneRead] = Field(default_factory=list)

    @property
    def completed_milestones(self) -> int:
        """How many milestones are ticked."""
        return sum(1 for milestone in self.milestones if milestone.is_completed)


class GoalPaceRead(ReadSchema):
    """Whether a goal is keeping up with its deadline."""

    goal_id: int
    elapsed_fraction: float | None
    progress_fraction: float
    days_remaining: int | None
    is_behind: bool
    is_overdue: bool


class WeeklyGoalInput(Schema):
    """A numeric target for one week."""

    week_start: date
    metric: WeeklyMetric
    target_value: float = Field(gt=0)
    notes: str | None = Field(default=None, max_length=1000)


class WeeklyGoalRead(ReadSchema):
    """A weekly target with its current progress."""

    id: int
    week_start: date
    metric: WeeklyMetric
    target_value: float
    achieved_value: float
    notes: str | None

    @property
    def progress_fraction(self) -> float:
        """Achieved over target, capped at 1.0."""
        if self.target_value <= 0:
            return 0.0
        return min(1.0, self.achieved_value / self.target_value)

    @property
    def is_met(self) -> bool:
        """Whether the target has been reached."""
        return self.achieved_value >= self.target_value
