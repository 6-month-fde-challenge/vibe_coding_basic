"""The task table."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin
from app.database.types import JSONColumn, str_enum
from app.models.enums import RecurrenceRule, TaskPriority, TaskStatus

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import UserProfile


class Task(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """One thing to do.

    Recurring tasks are modelled as a *template* row plus generated
    occurrences that point back at it through :attr:`parent_task_id`. Storing
    occurrences rather than computing them on the fly means a completed
    occurrence keeps its own history even if the template is later edited or
    deleted.
    """

    __tablename__ = "task"
    __table_args__ = (
        # The dashboard asks "what is open today" constantly; this covers it
        # without touching the table.
        Index("ix_task_user_status_due", "user_id", "status", "due_date"),
        Index("ix_task_user_due", "user_id", "due_date"),
        Index("ix_task_user_completed_at", "user_id", "completed_at"),
        CheckConstraint(
            "estimated_minutes IS NULL OR estimated_minutes >= 0", name="estimated_non_negative"
        ),
        CheckConstraint(
            "actual_minutes IS NULL OR actual_minutes >= 0", name="actual_non_negative"
        ),
        CheckConstraint("recurrence_interval >= 1", name="recurrence_interval_positive"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[TaskPriority] = mapped_column(
        str_enum(TaskPriority), nullable=False, default=TaskPriority.MEDIUM, index=True
    )
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus), nullable=False, default=TaskStatus.TODO, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="SET NULL"), nullable=True, index=True
    )

    due_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    due_time: Mapped[time_type | None] = mapped_column(Time, nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    recurrence: Mapped[RecurrenceRule] = mapped_column(
        str_enum(RecurrenceRule), nullable=False, default=RecurrenceRule.NONE
    )
    #: Every N days/weeks/months, for CUSTOM and for "every other week".
    recurrence_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Weekday numbers (0=Monday) for a weekly recurrence on specific days.
    recurrence_days: Mapped[list[int] | None] = mapped_column(JSONColumn, nullable=True)
    recurrence_until: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    parent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), nullable=True, index=True
    )

    tags: Mapped[list[str] | None] = mapped_column(JSONColumn, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    user: Mapped[UserProfile] = relationship(back_populates="tasks")
    category: Mapped[Category | None] = relationship(back_populates="tasks")
    occurrences: Mapped[list[Task]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
        remote_side=None,
        foreign_keys=[parent_task_id],
    )
    template: Mapped[Task | None] = relationship(
        back_populates="occurrences",
        remote_side="Task.id",
        foreign_keys=[parent_task_id],
    )

    @property
    def is_recurring_template(self) -> bool:
        """Whether this row is a template that spawns occurrences."""
        return self.recurrence is not RecurrenceRule.NONE and self.parent_task_id is None

    def __repr__(self) -> str:
        """Return a debugging representation naming the status."""
        return f"<Task id={self.id} status={self.status} title={self.title[:30]!r}>"
