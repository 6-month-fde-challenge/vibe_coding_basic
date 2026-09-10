"""SQLAlchemy ORM models.

Importing this package imports every model, which is what registers them all
on ``Base.metadata``. Alembic's autogenerate and ``create_all`` both depend on
that, so this module is imported for its side effect as well as its names.
"""

from app.database.base import Base
from app.models.activity import Activity
from app.models.category import Category
from app.models.enums import (
    ActivityIntensity,
    ActivityLevel,
    BmrFormula,
    CategoryKind,
    GoalCategory,
    GoalStatus,
    HabitDirection,
    HabitFrequency,
    HabitType,
    HeatmapMetric,
    InsightSeverity,
    RecurrenceRule,
    Sex,
    TaskPriority,
    TaskStatus,
    TrendDirection,
    WeeklyMetric,
)
from app.models.goal import Goal, GoalMilestone, WeeklyGoal
from app.models.habit import Habit, HabitLog
from app.models.journal import DailyLog, JournalEntry
from app.models.sleep import SleepRecord
from app.models.task import Task
from app.models.time_entry import TimeEntry
from app.models.user import AppSetting, BodyMeasurement, UserProfile

__all__ = [
    "Activity",
    "ActivityIntensity",
    "ActivityLevel",
    "AppSetting",
    "Base",
    "BmrFormula",
    "BodyMeasurement",
    "Category",
    "CategoryKind",
    "DailyLog",
    "Goal",
    "GoalCategory",
    "GoalMilestone",
    "GoalStatus",
    "Habit",
    "HabitDirection",
    "HabitFrequency",
    "HabitLog",
    "HabitType",
    "HeatmapMetric",
    "InsightSeverity",
    "JournalEntry",
    "RecurrenceRule",
    "Sex",
    "SleepRecord",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "TimeEntry",
    "TrendDirection",
    "UserProfile",
    "WeeklyGoal",
    "WeeklyMetric",
]
