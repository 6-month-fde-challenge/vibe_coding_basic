"""Habit definitions and their daily logs."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type
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
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin
from app.database.types import JSONColumn, str_enum
from app.models.enums import HabitDirection, HabitFrequency, HabitType

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import UserProfile


class Habit(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """A repeated behaviour the user wants to measure.

    Everything that varies between "meditate 20 minutes", "drink 3 litres"
    and "wake before 06:30" is data on this row - the type, the direction of
    the comparison, the target, the unit and the schedule. No habit name
    appears anywhere in the code.
    """

    __tablename__ = "habit"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_habit_user_name"),
        Index("ix_habit_user_active", "user_id", "is_active"),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="date_order",
        ),
        CheckConstraint("target_value IS NULL OR target_value >= 0", name="target_non_negative"),
        CheckConstraint(
            "times_per_week IS NULL OR times_per_week BETWEEN 1 AND 7",
            name="times_per_week_range",
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="SET NULL"), nullable=True, index=True
    )

    habit_type: Mapped[HabitType] = mapped_column(
        str_enum(HabitType), nullable=False, default=HabitType.BOOLEAN
    )
    direction: Mapped[HabitDirection] = mapped_column(
        str_enum(HabitDirection), nullable=False, default=HabitDirection.AT_LEAST
    )
    frequency: Mapped[HabitFrequency] = mapped_column(
        str_enum(HabitFrequency), nullable=False, default=HabitFrequency.DAILY
    )

    #: The number that has to be reached for a measured habit.
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The "did not break the chain" floor - a bad day that still counts.
    min_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The number the user is actually aiming at.
    ideal_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Wall-clock target for a TIME habit ("wake before 06:30").
    target_time: Mapped[time_type | None] = mapped_column(Time, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)

    #: Weekday numbers (0=Monday) the habit is expected on.
    specific_days: Mapped[list[int] | None] = mapped_column(JSONColumn, nullable=True)
    #: Weekday numbers that are deliberate rest days - never counted as a miss.
    rest_days: Mapped[list[int] | None] = mapped_column(JSONColumn, nullable=True)
    times_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)

    start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True, index=True)
    end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    reminder_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reminder_time: Mapped[time_type | None] = mapped_column(Time, nullable=True)

    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    user: Mapped[UserProfile] = relationship(back_populates="habits")
    category: Mapped[Category | None] = relationship(back_populates="habits")
    logs: Mapped[list[HabitLog]] = relationship(
        back_populates="habit",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        """Return a debugging representation naming the habit."""
        return f"<Habit id={self.id} name={self.name!r} type={self.habit_type}>"


class HabitLog(IdMixin, TimestampMixin, Base):
    """One habit, on one day.

    The unique constraint on ``(habit_id, log_date)`` is the data-integrity
    rule from the specification: a habit cannot be logged twice for the same
    day. Updating an existing log is allowed; inserting a second one is not.
    """

    __tablename__ = "habit_log"
    __table_args__ = (
        UniqueConstraint("habit_id", "log_date", name="uq_habit_log_habit_date"),
        # Streaks read dates for one habit newest-first; analytics read a date
        # window across all habits. One index each.
        Index("ix_habit_log_habit_date", "habit_id", "log_date"),
        Index("ix_habit_log_date_completed", "log_date", "completed"),
        CheckConstraint("value IS NULL OR value >= 0", name="value_non_negative"),
    )

    habit_id: Mapped[int] = mapped_column(
        ForeignKey("habit.id", ondelete="CASCADE"), nullable=False, index=True
    )
    log_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    #: Measured amount for a non-boolean habit; ``None`` for BOOLEAN.
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Wall-clock reading for a TIME habit ("woke at 06:12").
    value_time: Mapped[time_type | None] = mapped_column(Time, nullable=True)
    #: Whether the target was met. Computed by the domain layer, stored so
    #: that streak queries never have to re-evaluate the rule row by row.
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Marks a day the user consciously took off; excluded from misses.
    is_rest_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    logged_at: Mapped[datetime | None] = mapped_column(nullable=True)

    habit: Mapped[Habit] = relationship(back_populates="logs")

    def __repr__(self) -> str:
        """Return a debugging representation naming habit and date."""
        return f"<HabitLog habit_id={self.habit_id} date={self.log_date} done={self.completed}>"
