"""Deciding whether a habit log counts as done.

Five habit types and four comparison directions is twenty combinations, and
scattering them through the service layer as ``if habit.name == ...`` is how
a tracker ends up unable to express "no more than 30 minutes of social
media". One value object, one function, one place to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from app.core.errors import ValidationError
from app.models.enums import HabitDirection, HabitType


@dataclass(frozen=True, slots=True)
class HabitTarget:
    """What "done" means for one habit.

    Attributes:
        habit_type: What is being measured.
        direction: Whether the target is a floor, a ceiling, or a deadline.
        target_value: The number to compare against, for measured habits.
        target_time: The clock time to compare against, for ``TIME`` habits.
        min_target: A lower bar that still preserves a streak. When set, a
            value between ``min_target`` and ``target_value`` counts as done
            but is reported as a partial day.
    """

    habit_type: HabitType = HabitType.BOOLEAN
    direction: HabitDirection = HabitDirection.AT_LEAST
    target_value: float | None = None
    target_time: time | None = None
    min_target: float | None = None


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """The verdict on one logged day.

    Attributes:
        completed: Whether the day counts towards the streak.
        ratio: Progress against the target, clamped to ``0.0..1.0``. Used by
            progress bars and by the productivity score, which rewards a
            near-miss more than a zero.
        partial: True when the minimum was met but the ideal was not.
    """

    completed: bool
    ratio: float
    partial: bool = False


def _minutes_of(moment: time) -> int:
    """Return minutes since midnight, so two clock times can be compared."""
    return moment.hour * 60 + moment.minute


def _clamp01(value: float) -> float:
    """Clamp a float into the closed unit interval."""
    return max(0.0, min(1.0, value))


def evaluate(
    target: HabitTarget,
    *,
    value: float | None = None,
    value_time: time | None = None,
    checked: bool = False,
) -> CompletionResult:
    """Judge one logged day against the habit's target.

    Args:
        target: The habit's definition of done.
        value: Measured amount, for ``COUNT``/``DURATION``/``QUANTITY``.
        value_time: Recorded clock time, for ``TIME``.
        checked: The tick box, for ``BOOLEAN``.

    Returns:
        Whether the day counts, and how close it came.

    Raises:
        ValidationError: If the log is missing the reading its habit type
            requires, or the habit is missing the target it needs.
    """
    if target.habit_type is HabitType.BOOLEAN:
        return CompletionResult(completed=checked, ratio=1.0 if checked else 0.0)

    if target.habit_type is HabitType.TIME:
        return _evaluate_time(target, value_time)

    if value is None:
        raise ValidationError(
            "This habit records an amount, so a value is required",
            field="value",
            user_hint="Enter how much you did.",
        )
    if value < 0:
        raise ValidationError("Value cannot be negative", field="value", value=value)
    if target.target_value is None:
        # No target set: any positive amount is a completion. Better than
        # refusing to record a habit the user has not finished configuring.
        return CompletionResult(completed=value > 0, ratio=1.0 if value > 0 else 0.0)

    return _evaluate_measured(target, value)


def _evaluate_measured(target: HabitTarget, value: float) -> CompletionResult:
    """Compare a measured amount against a numeric target."""
    goal = target.target_value
    if goal is None:  # pragma: no cover - the caller has already checked
        return CompletionResult(completed=value > 0, ratio=1.0 if value > 0 else 0.0)

    if target.direction is HabitDirection.AT_MOST:
        # A ceiling: staying at zero is a perfect day, exceeding it is a miss.
        completed = value <= goal
        ratio = 1.0 if completed else _clamp01(goal / value) if value > 0 else 1.0
        return CompletionResult(completed=completed, ratio=ratio)

    ratio = _clamp01(value / goal) if goal > 0 else (1.0 if value > 0 else 0.0)
    if value >= goal:
        return CompletionResult(completed=True, ratio=1.0)
    if target.min_target is not None and value >= target.min_target:
        return CompletionResult(completed=True, ratio=ratio, partial=True)
    return CompletionResult(completed=False, ratio=ratio)


def _evaluate_time(target: HabitTarget, value_time: time | None) -> CompletionResult:
    """Compare a recorded clock time against a deadline."""
    if value_time is None:
        raise ValidationError(
            "This habit records a time of day, so a time is required",
            field="value_time",
            user_hint="Enter the time you did it.",
        )
    if target.target_time is None:
        raise ValidationError(
            "This habit has no target time set",
            field="target_time",
            user_hint="Set a target time for this habit in the Habits screen.",
        )

    actual = _minutes_of(value_time)
    goal = _minutes_of(target.target_time)

    if target.direction is HabitDirection.AFTER:
        completed = actual >= goal
        drift = actual - goal
    else:
        # BEFORE is the default reading for a TIME habit ("wake before 06:30").
        completed = actual <= goal
        drift = goal - actual

    if completed:
        return CompletionResult(completed=True, ratio=1.0)

    # Ratio decays over an hour of overshoot, so "six minutes late" still
    # scores far better than "two hours late".
    ratio = _clamp01(1.0 + (drift / 60.0))
    return CompletionResult(completed=False, ratio=ratio)
