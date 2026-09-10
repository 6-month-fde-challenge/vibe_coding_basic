"""Habit scheduling, completion rules and the streak engine."""

from app.domain.habits.completion import CompletionResult, HabitTarget, evaluate
from app.domain.habits.schedule import HabitSchedule
from app.domain.habits.streaks import (
    StreakSummary,
    current_streak,
    longest_streak,
    summarize,
)

__all__ = [
    "CompletionResult",
    "HabitSchedule",
    "HabitTarget",
    "StreakSummary",
    "current_streak",
    "evaluate",
    "longest_streak",
    "summarize",
]
