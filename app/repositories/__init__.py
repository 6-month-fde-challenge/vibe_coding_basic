"""Repositories - the only place SQL is written.

Nothing above this layer imports SQLAlchemy, and nothing in this layer
implements a business rule. If a method here has an ``if`` in it that a
non-programmer would call a policy, it belongs in ``app.domain`` instead.
"""

from app.repositories.activity_repository import ActivityRepository
from app.repositories.analytics_repository import (
    AnalyticsRepository,
    DailyAggregate,
    RangeAggregate,
)
from app.repositories.base import BaseRepository, UserScopedRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.goal_repository import GoalRepository, WeeklyGoalRepository
from app.repositories.habit_repository import HabitRepository
from app.repositories.journal_repository import DailyLogRepository, JournalRepository
from app.repositories.profile_repository import (
    BodyMeasurementRepository,
    ProfileRepository,
    SettingsRepository,
)
from app.repositories.sleep_repository import SleepRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.time_entry_repository import TimeEntryRepository

__all__ = [
    "ActivityRepository",
    "AnalyticsRepository",
    "BaseRepository",
    "BodyMeasurementRepository",
    "CategoryRepository",
    "DailyAggregate",
    "DailyLogRepository",
    "GoalRepository",
    "HabitRepository",
    "JournalRepository",
    "ProfileRepository",
    "RangeAggregate",
    "SettingsRepository",
    "SleepRepository",
    "TaskRepository",
    "TimeEntryRepository",
    "UserScopedRepository",
    "WeeklyGoalRepository",
]
