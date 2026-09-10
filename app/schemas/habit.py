"""Habit input and output schemas."""

from __future__ import annotations

from datetime import date, time

from pydantic import Field, model_validator

from app.models.enums import HabitDirection, HabitFrequency, HabitType
from app.schemas.common import ReadSchema, Schema


class HabitCreate(Schema):
    """Fields accepted when creating a habit.

    The cross-field checks here are the ones that would otherwise produce a
    habit that can never be completed: a measured habit with no target, or a
    "wake before" habit with no time to be before.
    """

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category_id: int | None = None
    habit_type: HabitType = HabitType.BOOLEAN
    direction: HabitDirection = HabitDirection.AT_LEAST
    frequency: HabitFrequency = HabitFrequency.DAILY
    target_value: float | None = Field(default=None, ge=0)
    min_target: float | None = Field(default=None, ge=0)
    ideal_target: float | None = Field(default=None, ge=0)
    target_time: time | None = None
    unit: str | None = Field(default=None, max_length=24)
    specific_days: list[int] | None = None
    rest_days: list[int] | None = None
    times_per_week: int | None = Field(default=None, ge=1, le=7)
    start_date: date | None = None
    end_date: date | None = None
    reminder_enabled: bool = False
    reminder_time: time | None = None
    color: str | None = Field(default=None, max_length=16)
    icon: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def _check_definition(self) -> HabitCreate:
        """Reject a habit whose target cannot be evaluated."""
        if self.habit_type.is_measured and self.habit_type is not HabitType.TIME:
            if self.target_value is None:
                msg = "A measured habit needs a target value."
                raise ValueError(msg)
            if self.min_target is not None and self.min_target > self.target_value:
                msg = "The minimum target cannot exceed the main target."
                raise ValueError(msg)

        if self.habit_type is HabitType.TIME and self.target_time is None:
            msg = "A time-of-day habit needs a target time."
            raise ValueError(msg)

        if self.frequency is HabitFrequency.SPECIFIC_DAYS and not self.specific_days:
            msg = "Choose at least one day for a habit scheduled on specific days."
            raise ValueError(msg)

        if self.frequency is HabitFrequency.TIMES_PER_WEEK and not self.times_per_week:
            msg = "Set how many times a week this habit should be done."
            raise ValueError(msg)

        for field_name in ("specific_days", "rest_days"):
            days = getattr(self, field_name)
            if days and any(day < 0 or day > 6 for day in days):
                msg = f"{field_name} must contain numbers from 0 (Monday) to 6 (Sunday)."
                raise ValueError(msg)

        if self.end_date and self.start_date and self.end_date < self.start_date:
            msg = "A habit cannot end before it starts."
            raise ValueError(msg)
        return self


class HabitUpdate(Schema):
    """Fields accepted when editing a habit."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category_id: int | None = None
    target_value: float | None = Field(default=None, ge=0)
    min_target: float | None = Field(default=None, ge=0)
    ideal_target: float | None = Field(default=None, ge=0)
    target_time: time | None = None
    unit: str | None = Field(default=None, max_length=24)
    frequency: HabitFrequency | None = None
    specific_days: list[int] | None = None
    rest_days: list[int] | None = None
    times_per_week: int | None = Field(default=None, ge=1, le=7)
    end_date: date | None = None
    is_active: bool | None = None
    reminder_enabled: bool | None = None
    reminder_time: time | None = None
    color: str | None = Field(default=None, max_length=16)
    icon: str | None = Field(default=None, max_length=16)
    sort_order: int | None = None


class HabitLogInput(Schema):
    """One day's reading for one habit."""

    habit_id: int
    log_date: date
    value: float | None = Field(default=None, ge=0)
    value_time: time | None = None
    checked: bool = False
    is_rest_day: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class HabitRead(ReadSchema):
    """A habit definition as the UI sees it."""

    id: int
    name: str
    description: str | None
    category_id: int | None
    habit_type: HabitType
    direction: HabitDirection
    frequency: HabitFrequency
    target_value: float | None
    min_target: float | None
    ideal_target: float | None
    target_time: time | None
    unit: str | None
    specific_days: list[int] | None
    rest_days: list[int] | None
    times_per_week: int | None
    start_date: date | None
    end_date: date | None
    is_active: bool
    reminder_enabled: bool
    reminder_time: time | None
    color: str | None
    icon: str | None
    sort_order: int

    @property
    def target_label(self) -> str:
        """Human-readable target, such as ``20 minutes`` or ``before 06:30``."""
        if self.habit_type is HabitType.BOOLEAN:
            return "Done or not"
        if self.habit_type is HabitType.TIME and self.target_time:
            preposition = "after" if self.direction is HabitDirection.AFTER else "before"
            return f"{preposition} {self.target_time.strftime('%H:%M')}"
        if self.target_value is None:
            return "No target set"
        unit = f" {self.unit}" if self.unit else ""
        qualifier = "at most" if self.direction is HabitDirection.AT_MOST else ""
        return f"{qualifier} {self.target_value:g}{unit}".strip()


class HabitLogRead(ReadSchema):
    """One recorded day for one habit."""

    id: int
    habit_id: int
    log_date: date
    value: float | None
    value_time: time | None
    completed: bool
    is_rest_day: bool
    notes: str | None


class HabitStreakRead(ReadSchema):
    """Streak figures for one habit."""

    habit_id: int
    current_streak: int
    longest_streak: int
    completion_rate: float
    missed_days: int
    weekly_consistency: float
    monthly_consistency: float
    last_completed_on: date | None


class HabitTodayRead(ReadSchema):
    """A habit plus today's state, which is what the dashboard renders."""

    habit: HabitRead
    log: HabitLogRead | None
    is_due_today: bool
    is_rest_day: bool
    streak: HabitStreakRead

    @property
    def is_done(self) -> bool:
        """Whether today's target has been met."""
        return bool(self.log and self.log.completed)
