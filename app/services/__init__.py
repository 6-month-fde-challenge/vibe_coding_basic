"""Services - the application layer.

Each service owns one subject area's business rules, receives its
dependencies through its constructor, and opens exactly one unit of work per
operation. Nothing here imports Streamlit; nothing above here writes SQL.
"""

from app.services.activity_service import ActivityService
from app.services.analytics_service import AnalyticsService
from app.services.base import BaseService
from app.services.category_service import CategoryService
from app.services.coach import PersonalCoach, RuleBasedCoach
from app.services.export_service import ExportService
from app.services.goal_service import GoalService
from app.services.habit_service import HabitService
from app.services.health_service import HealthService
from app.services.import_service import ImportReport, ImportService
from app.services.insight_service import InsightService
from app.services.journal_service import JournalService
from app.services.productivity_service import ProductivityService
from app.services.settings_service import SettingsService
from app.services.sleep_service import SleepService
from app.services.task_service import TaskService
from app.services.time_tracking_service import TimeTrackingService
from app.services.unit_of_work import UnitOfWork, UnitOfWorkFactory

__all__ = [
    "ActivityService",
    "AnalyticsService",
    "BaseService",
    "CategoryService",
    "ExportService",
    "GoalService",
    "HabitService",
    "HealthService",
    "ImportReport",
    "ImportService",
    "InsightService",
    "JournalService",
    "PersonalCoach",
    "ProductivityService",
    "RuleBasedCoach",
    "SettingsService",
    "SleepService",
    "TaskService",
    "TimeTrackingService",
    "UnitOfWork",
    "UnitOfWorkFactory",
]
