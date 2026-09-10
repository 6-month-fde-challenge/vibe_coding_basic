"""Shared pytest fixtures.

Two levels of fixture, matching the two kinds of test:

*Unit tests* take plain values. The domain layer is pure, so most of it
needs nothing from this file at all.

*Integration tests* take a ``container`` built against a temporary SQLite
file and a frozen clock. Nothing in the suite touches the developer's real
database, and no test depends on what day it is run.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.bootstrap import Container, build_container
from app.config.settings import AppEnvironment, Settings
from app.core.timeutils import FixedClock
from app.database.connection import Database, create_all
from app.models.enums import CategoryKind, HabitType
from app.schemas.activity import ActivityInput, TimeEntryInput
from app.schemas.habit import HabitCreate, HabitLogInput
from app.schemas.sleep import SleepInput
from app.schemas.task import TaskCreate

#: Every test runs as if it were this moment, so "today" is a constant.
FROZEN_NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
TZ_NAME = "Asia/Kolkata"


@pytest.fixture(scope="session")
def timezone() -> ZoneInfo:
    """The timezone every test uses."""
    return ZoneInfo(TZ_NAME)


@pytest.fixture
def clock(timezone: ZoneInfo) -> FixedClock:
    """A clock pinned to :data:`FROZEN_NOW`."""
    return FixedClock(FROZEN_NOW, timezone)


@pytest.fixture
def today(clock: FixedClock) -> date:
    """The frozen local date."""
    return clock.today()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at a throwaway database and log directory."""
    return Settings(
        app_env=AppEnvironment.TESTING,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        log_dir=tmp_path / "logs",
        timezone=TZ_NAME,
        db_echo=False,
    )


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    """A fresh database with the schema created from the models.

    Built with ``create_all`` rather than Alembic: unit-adjacent tests
    should not depend on the migration history being replayable, and
    :mod:`tests.integration.test_migrations` covers that separately.
    """
    instance = Database(settings)
    create_all(instance)
    yield instance
    instance.dispose()


@pytest.fixture
def container(settings: Settings, database: Database, clock: FixedClock) -> Iterator[Container]:
    """A fully wired container against the throwaway database."""
    built = build_container(settings, database=database, clock=clock, migrate=False)
    yield built
    built.dispose()


@pytest.fixture
def time_categories(container: Container) -> dict[str, int]:
    """``{name: id}`` for the seeded time categories."""
    return {
        category.name: category.id for category in container.categories.list_kind(CategoryKind.TIME)
    }


@pytest.fixture
def activity_categories(container: Container) -> dict[str, int]:
    """``{name: id}`` for the seeded activity categories."""
    return {
        category.name: category.id
        for category in container.categories.list_kind(CategoryKind.ACTIVITY)
    }


@pytest.fixture
def populated(
    container: Container,
    today: date,
    time_categories: dict[str, int],
    activity_categories: dict[str, int],
) -> Container:
    """A container holding one deliberately imperfect week of data.

    Fixed, not random: a test that asserts a score of 84 has to be able to
    fail when the scoring changes, which it cannot if the input moves.
    """
    habit = container.habits.create(
        HabitCreate(
            name="Meditation",
            habit_type=HabitType.DURATION,
            target_value=20.0,
            unit="minutes",
            start_date=today - timedelta(days=6),
        )
    )
    # Six of the last seven days, with a gap two days ago.
    for offset in (6, 5, 4, 3, 1, 0):
        container.habits.log(
            HabitLogInput(habit_id=habit.id, log_date=today - timedelta(days=offset), value=25.0)
        )

    for offset in range(7):
        day = today - timedelta(days=offset)
        container.sleep.record(
            SleepInput(
                log_date=day,
                sleep_time=time(23, 30),
                wake_time=time(6, 30),
                quality=7,
            )
        )
        container.time_tracking.log(
            TimeEntryInput(
                log_date=day,
                category_id=time_categories["Studying"],
                duration_minutes=120.0,
            )
        )
        container.time_tracking.log(
            TimeEntryInput(
                log_date=day, category_id=time_categories["Coding"], duration_minutes=90.0
            )
        )
        container.activities.log(
            ActivityInput(
                log_date=day,
                category_id=activity_categories["Cricket"],
                duration_minutes=60.0,
            )
        )

    done = container.tasks.create(TaskCreate(title="Finish the report", due_date=today))
    container.tasks.complete(done.id)
    container.tasks.create(TaskCreate(title="Reply to email", due_date=today))

    return container
