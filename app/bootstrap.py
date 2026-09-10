"""Application startup and dependency wiring.

One place builds the object graph. Everything else receives what it needs
through its constructor, which is what makes the services testable and what
would let a FastAPI process reuse them unchanged - it would call
:func:`build_container` too, and never import ``app.ui``.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.config.settings import Settings, get_settings
from app.core.logging_config import get_logger, setup_logging
from app.core.timeutils import Clock, SystemClock
from app.database.connection import Database, create_all, run_migrations
from app.models.user import UserProfile
from app.notifications.base import NotificationService, NullNotificationService
from app.repositories.profile_repository import ProfileRepository
from app.services.activity_service import ActivityService
from app.services.analytics_service import AnalyticsService
from app.services.category_service import CategoryService
from app.services.coach import PersonalCoach, RuleBasedCoach
from app.services.export_service import ExportService
from app.services.goal_service import GoalService
from app.services.habit_service import HabitService
from app.services.health_service import HealthService
from app.services.import_service import ImportService
from app.services.insight_service import InsightService
from app.services.journal_service import JournalService
from app.services.productivity_service import ProductivityService
from app.services.settings_service import SettingsService
from app.services.sleep_service import SleepService
from app.services.task_service import TaskService
from app.services.time_tracking_service import TimeTrackingService
from app.services.unit_of_work import UnitOfWorkFactory

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Container:
    """Every service, already wired.

    Held for the life of the process. Streamlit caches it as a *resource*,
    never as data, because it owns a connection pool.
    """

    settings: Settings
    database: Database
    clock: Clock
    user_id: int
    unit_of_work: UnitOfWorkFactory
    notifications: NotificationService

    categories: CategoryService
    tasks: TaskService
    habits: HabitService
    sleep: SleepService
    activities: ActivityService
    time_tracking: TimeTrackingService
    goals: GoalService
    journal: JournalService
    health: HealthService
    app_settings: SettingsService
    productivity: ProductivityService
    insights: InsightService
    analytics: AnalyticsService
    exports: ExportService
    imports: ImportService
    coach: PersonalCoach

    def dispose(self) -> None:
        """Release the database connections."""
        self.database.dispose()


def ensure_schema(database: Database, settings: Settings) -> None:
    """Bring the database up to the latest schema.

    Prefers Alembic so that development and production share one definition
    of the schema. Falls back to ``create_all`` only when the migration
    environment is unavailable - which happens in a test that built an
    in-memory database, and should not happen anywhere else.
    """
    try:
        run_migrations(database)
    except Exception:  # startup must explain itself rather than crash
        logger.warning(
            "Could not run migrations; creating the schema directly from the models",
            exc_info=settings.db_echo,
        )
        create_all(database)


def ensure_profile(database: Database, settings: Settings) -> int:
    """Return the profile id, creating a default profile on first run.

    A brand-new install has no profile, and every user-scoped repository
    needs one before it can do anything. Creating it here means the first
    page load works rather than erroring.
    """
    with database.session() as session:
        repository = ProfileRepository(session)
        profile = repository.first()
        if profile is not None:
            return profile.id

        profile = repository.add(UserProfile(display_name="Me", timezone=settings.timezone))
        logger.info("Created the default profile")
        return profile.id


def build_container(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    clock: Clock | None = None,
    notifications: NotificationService | None = None,
    migrate: bool = True,
    seed_categories: bool = True,
) -> Container:
    """Build the whole object graph.

    Args:
        settings: Configuration. Read from the environment when omitted.
        database: An existing database, for tests.
        clock: A clock, for tests.
        notifications: A delivery channel. Defaults to discarding them.
        migrate: Bring the schema up to date before wiring anything.
        seed_categories: Create the default categories on a fresh database.

    Returns:
        A fully wired :class:`Container`.
    """
    settings = settings or get_settings()
    setup_logging(settings)

    database = database or Database(settings)
    if migrate:
        ensure_schema(database, settings)

    user_id = ensure_profile(database, settings)
    unit_of_work = UnitOfWorkFactory(database, user_id)

    profile_timezone = _profile_timezone(database, user_id, settings)
    clock = clock or SystemClock(profile_timezone)
    notifications = notifications or NullNotificationService()

    app_settings = SettingsService(unit_of_work, clock)
    categories = CategoryService(unit_of_work, clock)
    if seed_categories:
        categories.seed_defaults()

    tasks = TaskService(unit_of_work, clock)
    habits = HabitService(unit_of_work, clock)
    sleep = SleepService(unit_of_work, clock)
    activities = ActivityService(unit_of_work, clock)
    time_tracking = TimeTrackingService(unit_of_work, clock)
    goals = GoalService(unit_of_work, clock)
    journal = JournalService(unit_of_work, clock)
    health = HealthService(unit_of_work, clock)

    productivity = ProductivityService(unit_of_work, clock, app_settings)
    insights = InsightService(unit_of_work, clock, productivity=productivity, sleep=sleep)
    analytics = AnalyticsService(
        unit_of_work,
        clock,
        habits=habits,
        health=health,
        goals=goals,
        time_tracking=time_tracking,
        productivity=productivity,
        insights=insights,
    )
    exports = ExportService(unit_of_work, clock)
    imports = ImportService(
        unit_of_work,
        clock,
        tasks=tasks,
        habits=habits,
        sleep=sleep,
        activities=activities,
        time_tracking=time_tracking,
        journal=journal,
        health=health,
        settings=settings,
    )
    coach = RuleBasedCoach(unit_of_work, clock, analytics=analytics, insights=insights)

    logger.info(
        "Container built for profile %s in %s (%s)",
        user_id,
        profile_timezone.key,
        settings.app_env.value,
    )

    return Container(
        settings=settings,
        database=database,
        clock=clock,
        user_id=user_id,
        unit_of_work=unit_of_work,
        notifications=notifications,
        categories=categories,
        tasks=tasks,
        habits=habits,
        sleep=sleep,
        activities=activities,
        time_tracking=time_tracking,
        goals=goals,
        journal=journal,
        health=health,
        app_settings=app_settings,
        productivity=productivity,
        insights=insights,
        analytics=analytics,
        exports=exports,
        imports=imports,
        coach=coach,
    )


def _profile_timezone(database: Database, user_id: int, settings: Settings) -> ZoneInfo:
    """Read the profile's timezone, falling back to the configured one.

    The profile wins over ``.env`` because the user set it from inside the
    app and expects that to be the one that counts.
    """
    with database.session() as session:
        profile = ProfileRepository(session).get(user_id)
        name = profile.timezone if profile else settings.timezone

    try:
        return ZoneInfo(name)
    except Exception:  # a bad stored value must not stop the application
        logger.warning(
            "Profile timezone %r is unusable; falling back to %s", name, settings.timezone
        )
        return settings.tzinfo


__all__ = ["Container", "build_container", "ensure_profile", "ensure_schema"]
