"""Task input and output schemas."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import Field, model_validator

from app.models.enums import RecurrenceRule, TaskPriority, TaskStatus
from app.schemas.common import Pagination, ReadSchema, Schema

MAX_TAGS = 12


class TaskCreate(Schema):
    """Fields accepted when creating a task."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    priority: TaskPriority = TaskPriority.MEDIUM
    category_id: int | None = None
    due_date: date | None = None
    due_time: time | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    recurrence: RecurrenceRule = RecurrenceRule.NONE
    recurrence_interval: int = Field(default=1, ge=1, le=365)
    recurrence_days: list[int] | None = None
    recurrence_until: date | None = None
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _check_recurrence(self) -> TaskCreate:
        """A repeating task needs a due date to repeat from."""
        if self.recurrence is not RecurrenceRule.NONE and self.due_date is None:
            msg = "A recurring task needs a due date to repeat from."
            raise ValueError(msg)
        if self.recurrence_days and any(day < 0 or day > 6 for day in self.recurrence_days):
            msg = "Recurrence days must be between 0 (Monday) and 6 (Sunday)."
            raise ValueError(msg)
        if (
            self.recurrence_until is not None
            and self.due_date is not None
            and self.recurrence_until < self.due_date
        ):
            msg = "A recurrence cannot end before the first occurrence."
            raise ValueError(msg)
        return self


class TaskUpdate(Schema):
    """Fields accepted when editing a task. Everything is optional."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    priority: TaskPriority | None = None
    category_id: int | None = None
    due_date: date | None = None
    due_time: time | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    actual_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    notes: str | None = Field(default=None, max_length=4000)
    sort_order: int | None = None


class TaskFilter(Schema):
    """Search and filter criteria for the task list."""

    statuses: list[TaskStatus] | None = None
    priorities: list[TaskPriority] | None = None
    category_ids: list[int] | None = None
    due_from: date | None = None
    due_to: date | None = None
    search: str | None = Field(default=None, max_length=120)
    include_occurrences: bool = True
    tag: str | None = Field(default=None, max_length=40)
    pagination: Pagination = Pagination()

    @model_validator(mode="after")
    def _ordered(self) -> TaskFilter:
        """Reject a due-date window that ends before it starts."""
        if self.due_from and self.due_to and self.due_to < self.due_from:
            msg = "The due-date range ends before it starts."
            raise ValueError(msg)
        return self


class TaskRead(ReadSchema):
    """A task as the UI sees it."""

    id: int
    title: str
    description: str | None
    priority: TaskPriority
    status: TaskStatus
    category_id: int | None
    due_date: date | None
    due_time: time | None
    estimated_minutes: int | None
    actual_minutes: int | None
    completed_at: datetime | None
    recurrence: RecurrenceRule
    recurrence_interval: int
    recurrence_days: list[int] | None
    recurrence_until: date | None
    parent_task_id: int | None
    tags: list[str] | None
    notes: str | None
    sort_order: int

    @property
    def is_open(self) -> bool:
        """Whether the task still needs doing."""
        return self.status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
