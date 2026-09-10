"""Performance smoke tests.

The brief asks for the application to stay responsive with 100,000 task
records and 100,000 habit logs. These tests build a database at that scale
once and then assert that the hot reads stay bounded - both in wall-clock
time and, more tellingly, in the number of queries issued.

Marked ``slow`` because building the fixture takes a while:

    pytest -m "not slow"        # skip them
    pytest -m slow              # only them
"""

from __future__ import annotations

import time as timing
from collections.abc import Callable, Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, event, func, insert, select

from app.bootstrap import Container
from app.models.enums import CategoryKind
from app.models.habit import Habit, HabitLog
from app.models.task import Task
from app.models.time_entry import TimeEntry
from app.schemas.common import DateRange, Pagination
from app.schemas.task import TaskFilter

pytestmark = [pytest.mark.integration, pytest.mark.slow]

#: Scale from section 46 of the brief.
TASK_ROWS = 100_000
HABIT_LOG_DAYS = 4_000
HABIT_COUNT = 25
TIME_ENTRY_ROWS = 50_000

#: A page load has a budget. These are generous - the point is to catch a
#: full-table scan appearing, not to benchmark the machine.
BUDGET_SECONDS = 1.5


class QueryCounter:
    """Counts statements executed on an engine, as a context manager."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.count = 0

    def __enter__(self) -> QueryCounter:
        """Start counting."""
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *_: object) -> None:
        """Stop counting."""
        event.remove(self.engine, "before_cursor_execute", self._record)

    def _record(self, *_: object, **__: object) -> None:
        self.count += 1


@pytest.fixture(scope="module")
def large(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Container]:
    """A database at the scale the brief names.

    Populated with bulk inserts rather than through the services: the point
    is to measure the *reads*, and writing a hundred thousand rows one
    validated call at a time would take minutes.
    """
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from app.bootstrap import build_container
    from app.config.settings import AppEnvironment, Settings
    from app.core.timeutils import FixedClock
    from app.database.connection import Database, create_all

    root = tmp_path_factory.mktemp("perf")
    settings = Settings(
        app_env=AppEnvironment.TESTING,
        database_url=f"sqlite:///{(root / 'perf.db').as_posix()}",
        log_dir=root / "logs",
        timezone="Asia/Kolkata",
    )
    database = Database(settings)
    create_all(database)
    clock = FixedClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC), ZoneInfo("Asia/Kolkata"))
    container = build_container(settings, database=database, clock=clock, migrate=False)

    today = clock.today()
    user_id = container.user_id

    with database.session() as session:
        habit_ids = []
        for index in range(HABIT_COUNT):
            habit = Habit(user_id=user_id, name=f"Habit {index}", start_date=date(2015, 1, 1))
            session.add(habit)
            session.flush()
            habit_ids.append(habit.id)

        session.execute(
            insert(HabitLog),
            [
                {
                    "habit_id": habit_ids[offset % HABIT_COUNT],
                    "log_date": today - timedelta(days=offset // HABIT_COUNT),
                    "completed": offset % 7 != 0,
                    "is_rest_day": False,
                }
                for offset in range(HABIT_LOG_DAYS * HABIT_COUNT)
            ],
        )

        session.execute(
            insert(Task),
            [
                {
                    "user_id": user_id,
                    "title": f"Task {index}",
                    "status": "COMPLETED" if index % 3 else "TODO",
                    "priority": "MEDIUM",
                    "recurrence": "NONE",
                    "recurrence_interval": 1,
                    "sort_order": 100,
                    "due_date": today - timedelta(days=index % 3000),
                }
                for index in range(TASK_ROWS)
            ],
        )

        category_id = container.categories.list_kind(CategoryKind.TIME)[0].id
        session.execute(
            insert(TimeEntry),
            [
                {
                    "user_id": user_id,
                    "category_id": category_id,
                    "log_date": today - timedelta(days=index % 3000),
                    "duration_minutes": 30.0,
                }
                for index in range(TIME_ENTRY_ROWS)
            ],
        )

    yield container
    container.dispose()


def elapsed[T](callable_: Callable[[], T]) -> tuple[float, T]:
    """Time one call and return the seconds taken with its result."""
    start = timing.perf_counter()
    result = callable_()
    return timing.perf_counter() - start, result


class TestReadsStayBounded:
    def test_the_row_counts_are_what_we_think(self, large: Container):
        with large.unit_of_work() as uow:
            assert uow.session.scalar(select(func.count()).select_from(Task)) == TASK_ROWS
            assert (
                uow.session.scalar(select(func.count()).select_from(HabitLog))
                == HABIT_LOG_DAYS * HABIT_COUNT
            )

    def test_a_days_task_list_is_fast(self, large: Container):
        today = large.clock.today()
        seconds, tasks = elapsed(lambda: large.tasks.list_for_day(today))
        assert seconds < BUDGET_SECONDS
        assert len(tasks) <= 60  # the day list is capped

    def test_a_paged_search_does_not_load_everything(self, large: Container):
        seconds, page = elapsed(
            lambda: large.tasks.search(TaskFilter(pagination=Pagination(limit=25)))
        )
        assert seconds < BUDGET_SECONDS
        assert len(page.items) == 25
        assert page.total == TASK_ROWS

    def test_the_current_streak_reads_a_bounded_number_of_rows(self, large: Container):
        habit = large.habits.list_habits()[0]
        with QueryCounter(large.database.engine) as counter:
            seconds, _ = elapsed(lambda: large.habits.current_streak_only(habit.id))
        assert seconds < BUDGET_SECONDS
        # One profile lookup, one habit lookup, and one or two pages of dates.
        assert counter.count <= 6

    def test_the_dashboard_issues_a_bounded_number_of_queries(self, large: Container):
        today = large.clock.today()
        with QueryCounter(large.database.engine) as counter:
            seconds, view = elapsed(lambda: large.analytics.dashboard(today))
        assert seconds < BUDGET_SECONDS * 4
        assert view.summary.log_date == today
        # Fixed cost: it must not grow with the number of habits or tasks.
        assert counter.count < 120

    def test_a_year_of_heatmap_is_a_handful_of_queries(self, large: Container):
        with QueryCounter(large.database.engine) as counter:
            seconds, heatmap = elapsed(lambda: large.analytics.heatmap(days=365))
        assert seconds < BUDGET_SECONDS * 4
        assert len(heatmap.points) == 365
        assert counter.count < 60

    def test_a_range_aggregate_is_grouped_in_the_database(self, large: Container):
        today = large.clock.today()
        period = DateRange.last_n_days(today, 90)
        with QueryCounter(large.database.engine) as counter:
            seconds, allocation = elapsed(lambda: large.time_tracking.allocation(period))
        assert seconds < BUDGET_SECONDS
        assert allocation.total_minutes > 0
        assert counter.count <= 3

    def test_counting_overdue_tasks_does_not_fetch_them(self, large: Container):
        today = large.clock.today()
        with QueryCounter(large.database.engine) as counter:
            seconds, count = elapsed(lambda: large.tasks.count_overdue(today))
        assert seconds < BUDGET_SECONDS
        assert count > 0
        assert counter.count <= 2
