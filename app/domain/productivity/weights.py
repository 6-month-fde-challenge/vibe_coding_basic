"""Configurable weights for the productivity score.

The brief is explicit that arbitrary hard-coded weights must not be sprinkled
through the application. So there is exactly one place a weight can be
written down, it is validated, and it is persisted in ``app_settings`` where
the user can change it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: How far the weights may sum from 1.0 before the model complains. Loose
#: enough for six values typed by hand, tight enough to catch a real slip.
WEIGHT_SUM_TOLERANCE = 0.01

#: The key this configuration is stored under in ``app_settings``.
SETTINGS_KEY = "productivity_weights"


class ProductivityWeights(BaseModel):
    """Relative importance of each component of the daily score.

    The six weights should sum to 1.0. They are validated rather than
    normalised silently, because a set that sums to 1.4 is far more likely to
    be a typo than an intention - and silently rescaling it would make the
    score's explanation disagree with the numbers the user typed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_completion: float = Field(default=0.25, ge=0.0, le=1.0)
    habit_completion: float = Field(default=0.20, ge=0.0, le=1.0)
    sleep: float = Field(default=0.15, ge=0.0, le=1.0)
    exercise: float = Field(default=0.10, ge=0.0, le=1.0)
    learning: float = Field(default=0.15, ge=0.0, le=1.0)
    focus: float = Field(default=0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> ProductivityWeights:
        """Reject a set of weights that does not sum to 1.0."""
        total = self.total
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            msg = (
                f"Productivity weights must sum to 1.0 (they currently sum to {total:.3f}). "
                "Adjust them so the score stays out of 100."
            )
            raise ValueError(msg)
        return self

    @property
    def total(self) -> float:
        """Sum of every weight."""
        return (
            self.task_completion
            + self.habit_completion
            + self.sleep
            + self.exercise
            + self.learning
            + self.focus
        )

    def as_mapping(self) -> dict[str, float]:
        """Return the weights keyed by component name."""
        return {
            "task_completion": self.task_completion,
            "habit_completion": self.habit_completion,
            "sleep": self.sleep,
            "exercise": self.exercise,
            "learning": self.learning,
            "focus": self.focus,
        }

    @classmethod
    def rescaled(cls, **values: float) -> ProductivityWeights:
        """Build weights from values that do not yet sum to one.

        The explicit way to ask for normalisation, so that it never happens
        by accident. Used by the Settings screen's "balance these for me"
        action.

        Raises:
            ValueError: If every value is zero, leaving nothing to scale.
        """
        total = sum(values.values())
        if total <= 0:
            msg = "At least one weight must be greater than zero."
            raise ValueError(msg)
        return cls(**{key: value / total for key, value in values.items()})


#: Component labels, used by the UI so the breakdown reads in English.
COMPONENT_LABELS: dict[str, str] = {
    "task_completion": "Task completion",
    "habit_completion": "Habit consistency",
    "sleep": "Sleep",
    "exercise": "Exercise",
    "learning": "Learning",
    "focus": "Focus",
}
