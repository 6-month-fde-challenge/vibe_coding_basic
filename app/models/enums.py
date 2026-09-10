"""Enumerations shared by the persistence, domain and UI layers.

All of these are :class:`~enum.StrEnum`, so the value stored in the database
is a readable string rather than an ordinal. That matters for two reasons:
a hand-written SQL query against the file is legible, and inserting a new
member never renumbers the existing rows.
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle of a task."""

    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        """Whether no further transition out of this status is allowed."""
        return self in _TERMINAL_TASK_STATUSES

    @property
    def counts_as_done(self) -> bool:
        """Whether the task contributed to the day's completion figure."""
        return self is TaskStatus.COMPLETED


_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED})


class TaskPriority(StrEnum):
    """How much a task matters, used for ordering and scoring."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def weight(self) -> float:
        """Relative weight used when scoring a day's task completion."""
        return _PRIORITY_WEIGHTS[self]


_PRIORITY_WEIGHTS: dict[TaskPriority, float] = {
    TaskPriority.LOW: 0.5,
    TaskPriority.MEDIUM: 1.0,
    TaskPriority.HIGH: 1.5,
    TaskPriority.CRITICAL: 2.0,
}


class RecurrenceRule(StrEnum):
    """How often a recurring task regenerates."""

    NONE = "NONE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    CUSTOM = "CUSTOM"


class HabitType(StrEnum):
    """What kind of measurement a habit records.

    The type decides how "done" is judged, which is why habit completion is
    a single function over this enum rather than a chain of special cases
    scattered through the services.
    """

    BOOLEAN = "BOOLEAN"
    COUNT = "COUNT"
    DURATION = "DURATION"
    QUANTITY = "QUANTITY"
    TIME = "TIME"

    @property
    def is_measured(self) -> bool:
        """Whether the habit records a number rather than a yes/no."""
        return self is not HabitType.BOOLEAN


class HabitFrequency(StrEnum):
    """Which days a habit is expected on."""

    DAILY = "DAILY"
    WEEKDAYS = "WEEKDAYS"
    WEEKENDS = "WEEKENDS"
    SPECIFIC_DAYS = "SPECIFIC_DAYS"
    TIMES_PER_WEEK = "TIMES_PER_WEEK"


class HabitDirection(StrEnum):
    """Whether the target is a floor or a ceiling.

    ``AT_LEAST`` covers "drink 3 litres"; ``AT_MOST`` covers "no more than 30
    minutes of social media"; ``BEFORE`` covers "wake before 06:30".
    """

    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class CategoryKind(StrEnum):
    """Which part of the app a configurable category belongs to."""

    TASK = "TASK"
    HABIT = "HABIT"
    ACTIVITY = "ACTIVITY"
    TIME = "TIME"


class ActivityIntensity(StrEnum):
    """Perceived effort of a logged activity."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"

    @property
    def met_estimate(self) -> float:
        """A coarse MET value used only for optional calorie estimates."""
        return _INTENSITY_MET[self]


_INTENSITY_MET: dict[ActivityIntensity, float] = {
    ActivityIntensity.LOW: 3.0,
    ActivityIntensity.MODERATE: 6.0,
    ActivityIntensity.HIGH: 9.0,
}


class GoalCategory(StrEnum):
    """Subject area of a longer-running goal."""

    PERSONAL = "PERSONAL"
    FITNESS = "FITNESS"
    LEARNING = "LEARNING"
    CAREER = "CAREER"
    FINANCIAL = "FINANCIAL"
    PROJECT = "PROJECT"
    HEALTH = "HEALTH"
    OTHER = "OTHER"


class GoalStatus(StrEnum):
    """Lifecycle of a goal."""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    ABANDONED = "ABANDONED"

    @property
    def is_open(self) -> bool:
        """Whether the goal still needs attention."""
        return self in {GoalStatus.NOT_STARTED, GoalStatus.IN_PROGRESS}


class Sex(StrEnum):
    """Biological sex, required by the BMR formulas.

    ``UNSPECIFIED`` is accepted by the profile but rejected by the BMR
    calculation, which needs one of the two constants the published formula
    defines. The app says so rather than silently guessing.
    """

    MALE = "MALE"
    FEMALE = "FEMALE"
    UNSPECIFIED = "UNSPECIFIED"


class ActivityLevel(StrEnum):
    """Lifestyle activity level, used to turn a BMR into a TDEE estimate."""

    SEDENTARY = "SEDENTARY"
    LIGHTLY_ACTIVE = "LIGHTLY_ACTIVE"
    MODERATELY_ACTIVE = "MODERATELY_ACTIVE"
    VERY_ACTIVE = "VERY_ACTIVE"
    EXTRA_ACTIVE = "EXTRA_ACTIVE"

    @property
    def multiplier(self) -> float:
        """The Harris-Benedict style activity multiplier."""
        return _ACTIVITY_MULTIPLIERS[self]

    @property
    def label(self) -> str:
        """Human-readable name for the UI."""
        return self.value.replace("_", " ").title()


_ACTIVITY_MULTIPLIERS: dict[ActivityLevel, float] = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHTLY_ACTIVE: 1.375,
    ActivityLevel.MODERATELY_ACTIVE: 1.55,
    ActivityLevel.VERY_ACTIVE: 1.725,
    ActivityLevel.EXTRA_ACTIVE: 1.9,
}


class BmrFormula(StrEnum):
    """Which published BMR equation to use.

    Configurable because the formulas disagree by a few hundred kcal and the
    honest answer is that all of them are estimates.
    """

    MIFFLIN_ST_JEOR = "MIFFLIN_ST_JEOR"
    HARRIS_BENEDICT = "HARRIS_BENEDICT"
    KATCH_MCARDLE = "KATCH_MCARDLE"


class WeeklyMetric(StrEnum):
    """A quantity a weekly goal can be set against."""

    STUDY_MINUTES = "STUDY_MINUTES"
    CODING_MINUTES = "CODING_MINUTES"
    TEACHING_MINUTES = "TEACHING_MINUTES"
    EXERCISE_MINUTES = "EXERCISE_MINUTES"
    SLEEP_MINUTES = "SLEEP_MINUTES"
    TASKS_COMPLETED = "TASKS_COMPLETED"
    HABIT_COMPLETIONS = "HABIT_COMPLETIONS"

    @property
    def unit(self) -> str:
        """Unit label for display."""
        return "minutes" if self.value.endswith("MINUTES") else "count"


class HeatmapMetric(StrEnum):
    """Which number the calendar heatmap colours a day by."""

    PRODUCTIVITY = "PRODUCTIVITY"
    HABIT_COMPLETION = "HABIT_COMPLETION"
    TASK_COMPLETION = "TASK_COMPLETION"


class InsightSeverity(StrEnum):
    """How loudly an insight or recommendation should be presented."""

    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    ATTENTION = "ATTENTION"


class TrendDirection(StrEnum):
    """Direction of a measured change between two periods."""

    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


def members[E: StrEnum](enum_cls: type[E]) -> list[E]:
    """Return an enum's members as a correctly typed list.

    ``list(SomeStrEnum)`` is widened to ``list[str]`` by the type checker,
    because a ``StrEnum`` member *is* a string. That loses the member type
    at every UI call site, so the widening is undone once, here.
    """
    return list(enum_cls)


__all__ = [
    "ActivityIntensity",
    "ActivityLevel",
    "BmrFormula",
    "CategoryKind",
    "GoalCategory",
    "GoalStatus",
    "HabitDirection",
    "HabitFrequency",
    "HabitType",
    "HeatmapMetric",
    "InsightSeverity",
    "RecurrenceRule",
    "Sex",
    "TaskPriority",
    "TaskStatus",
    "TrendDirection",
    "WeeklyMetric",
    "members",
]
