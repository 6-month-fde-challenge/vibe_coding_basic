"""Service-layer behaviour against a real (temporary) database."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from app.bootstrap import Container
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import (
    CategoryKind,
    HabitFrequency,
    HabitType,
    RecurrenceRule,
    TaskStatus,
)
from app.schemas.activity import ActivityInput, CategoryCreate, TimeEntryInput
from app.schemas.common import DateRange, Pagination
from app.schemas.goal import GoalCreate, MilestoneInput, WeeklyGoalInput
from app.schemas.habit import HabitCreate, HabitLogInput, HabitUpdate
from app.schemas.health import BodyMeasurementInput, ProfileUpdate
from app.schemas.journal import EveningReview, JournalInput, MorningCheckIn
from app.schemas.sleep import SleepInput
from app.schemas.task import TaskCreate, TaskFilter, TaskUpdate
from tests.helpers import not_none

pytestmark = pytest.mark.integration


class TestBootstrap:
    def test_a_fresh_database_gets_a_profile(self, container: Container):
        assert container.health.get_profile().id == container.user_id

    def test_the_default_categories_are_seeded(self, container: Container):
        for kind in CategoryKind:
            assert container.categories.list_kind(kind)

    def test_seeding_twice_creates_nothing_new(self, container: Container):
        before = len(container.categories.list_kind(CategoryKind.TIME))
        container.categories.seed_defaults()
        assert len(container.categories.list_kind(CategoryKind.TIME)) == before


class TestTaskService:
    def test_create_and_read_back(self, container: Container, today: date):
        created = container.tasks.create(TaskCreate(title="Write tests", due_date=today))
        assert container.tasks.get(created.id).title == "Write tests"

    def test_a_missing_task_raises(self, container: Container):
        with pytest.raises(NotFoundError):
            container.tasks.get(999)

    def test_completion_records_the_time_and_duration(self, container: Container, today: date):
        created = container.tasks.create(TaskCreate(title="Ship it", due_date=today))
        completed = container.tasks.complete(created.id, actual_minutes=42)
        assert completed.status is TaskStatus.COMPLETED
        assert completed.completed_at is not None
        assert completed.actual_minutes == 42

    def test_reopening_clears_the_completion_time(self, container: Container, today: date):
        created = container.tasks.create(TaskCreate(title="Ship it", due_date=today))
        container.tasks.complete(created.id)
        reopened = container.tasks.reopen(created.id)
        assert reopened.status is TaskStatus.TODO
        assert reopened.completed_at is None

    def test_an_illegal_transition_is_refused(self, container: Container, today: date):
        created = container.tasks.create(TaskCreate(title="Drop it", due_date=today))
        container.tasks.set_status(created.id, TaskStatus.CANCELLED)
        with pytest.raises(ValidationError):
            container.tasks.set_status(created.id, TaskStatus.COMPLETED)

    def test_quick_add_needs_a_title(self, container: Container):
        with pytest.raises(ValidationError):
            container.tasks.quick_add("   ")

    def test_a_bad_category_is_refused(self, container: Container, today: date):
        with pytest.raises(NotFoundError):
            container.tasks.create(TaskCreate(title="x", due_date=today, category_id=9999))

    def test_search_paginates(self, container: Container, today: date):
        for index in range(12):
            container.tasks.create(TaskCreate(title=f"Task {index}", due_date=today))
        page = container.tasks.search(TaskFilter(pagination=Pagination(limit=5)))
        assert len(page.items) == 5
        assert page.total == 12
        assert page.page_count == 3

    def test_search_by_text(self, container: Container, today: date):
        container.tasks.create(TaskCreate(title="Refactor the parser", due_date=today))
        container.tasks.create(TaskCreate(title="Buy milk", due_date=today))
        page = container.tasks.search(TaskFilter(search="parser"))
        assert [item.title for item in page.items] == ["Refactor the parser"]

    def test_recurring_tasks_generate_occurrences(self, container: Container, today: date):
        container.tasks.create(
            TaskCreate(title="Daily standup", due_date=today, recurrence=RecurrenceRule.DAILY)
        )
        occurrences = container.tasks.search(TaskFilter(include_occurrences=True)).items
        generated = [task for task in occurrences if task.parent_task_id is not None]
        assert len(generated) >= 7

    def test_generation_is_idempotent(self, container: Container, today: date):
        container.tasks.create(
            TaskCreate(title="Daily standup", due_date=today, recurrence=RecurrenceRule.DAILY)
        )
        assert container.tasks.generate_occurrences() == 0

    def test_a_template_is_not_on_the_day_list(self, container: Container, today: date):
        container.tasks.create(
            TaskCreate(title="Daily standup", due_date=today, recurrence=RecurrenceRule.DAILY)
        )
        titles = [task.title for task in container.tasks.list_for_day(today)]
        # The occurrence appears once; the template itself does not.
        assert titles.count("Daily standup") == 1

    def test_deleting_a_template_takes_its_occurrences(self, container: Container, today: date):
        template = container.tasks.create(
            TaskCreate(title="Daily standup", due_date=today, recurrence=RecurrenceRule.DAILY)
        )
        container.tasks.delete(template.id)
        remaining = container.tasks.search(TaskFilter()).items
        assert not [task for task in remaining if task.title == "Daily standup"]

    def test_the_day_list_reaches_back_over_recent_overdue_tasks(
        self, container: Container, today: date
    ):
        container.tasks.create(TaskCreate(title="Old thing", due_date=today - timedelta(days=3)))
        titles = [task.title for task in container.tasks.list_for_day(today)]
        assert "Old thing" in titles

    def test_the_day_list_does_not_reach_back_forever(self, container: Container, today: date):
        container.tasks.create(TaskCreate(title="Ancient", due_date=today - timedelta(days=200)))
        titles = [task.title for task in container.tasks.list_for_day(today)]
        assert "Ancient" not in titles
        assert container.tasks.count_overdue(today) == 1

    def test_partial_update_leaves_other_fields_alone(self, container: Container, today: date):
        created = container.tasks.create(
            TaskCreate(title="Original", description="keep me", due_date=today)
        )
        updated = container.tasks.update(created.id, TaskUpdate(title="Renamed"))
        assert updated.title == "Renamed"
        assert updated.description == "keep me"


class TestHabitService:
    def _habit(
        self,
        container: Container,
        today: date,
        *,
        name: str = "Meditation",
        habit_type: HabitType = HabitType.DURATION,
        start_date: date | None = None,
    ):
        return container.habits.create(
            HabitCreate(
                name=name,
                habit_type=habit_type,
                target_value=20.0 if habit_type is not HabitType.BOOLEAN else None,
                unit="minutes" if habit_type is not HabitType.BOOLEAN else None,
                start_date=start_date or today - timedelta(days=30),
            )
        )

    def test_duplicate_names_are_refused(self, container: Container, today: date):
        self._habit(container, today)
        with pytest.raises(ConflictError):
            self._habit(container, today)

    def test_renaming_onto_an_existing_name_is_refused(self, container: Container, today: date):
        self._habit(container, today)
        other = self._habit(container, today, name="Reading")
        with pytest.raises(ConflictError):
            container.habits.update(other.id, HabitUpdate(name="Meditation"))

    def test_a_second_log_for_the_same_day_updates_rather_than_duplicates(
        self, container: Container, today: date
    ):
        habit = self._habit(container, today)
        container.habits.log(HabitLogInput(habit_id=habit.id, log_date=today, value=25))
        container.habits.log(HabitLogInput(habit_id=habit.id, log_date=today, value=30))
        logs = [view for view in container.habits.today_view(today) if view.habit.id == habit.id]
        assert logs[0].log is not None
        assert logs[0].log.value == 30

    def test_logging_in_the_future_is_refused(self, container: Container, today: date):
        habit = self._habit(container, today)
        with pytest.raises(ValidationError):
            container.habits.log(
                HabitLogInput(habit_id=habit.id, log_date=today + timedelta(days=1), value=25)
            )

    def test_logging_before_the_start_date_is_refused(self, container: Container, today: date):
        habit = self._habit(container, today, name="New habit", start_date=today)
        with pytest.raises(ValidationError):
            container.habits.log(
                HabitLogInput(habit_id=habit.id, log_date=today - timedelta(days=1), value=25)
            )

    def test_a_measured_habit_cannot_be_toggled(self, container: Container, today: date):
        habit = self._habit(container, today)
        with pytest.raises(ValidationError):
            container.habits.toggle(habit.id, today)

    def test_toggling_a_boolean_habit_both_ways(self, container: Container, today: date):
        habit = container.habits.create(
            HabitCreate(name="No phone", habit_type=HabitType.BOOLEAN, start_date=today)
        )
        assert container.habits.toggle(habit.id, today) is not None
        assert container.habits.toggle(habit.id, today) is None

    def test_a_short_value_does_not_complete_the_habit(self, container: Container, today: date):
        habit = self._habit(container, today)
        log = container.habits.log(HabitLogInput(habit_id=habit.id, log_date=today, value=5))
        assert not log.completed

    def test_the_streak_is_built_from_the_logs(self, container: Container, today: date):
        habit = self._habit(container, today)
        for offset in range(5):
            container.habits.log(
                HabitLogInput(habit_id=habit.id, log_date=today - timedelta(days=offset), value=25)
            )
        summary = container.habits.streak(habit.id)
        assert summary.current_streak == 5
        assert summary.longest_streak == 5

    def test_the_cheap_streak_path_agrees_with_the_full_one(
        self, container: Container, today: date
    ):
        habit = self._habit(container, today)
        for offset in range(4):
            container.habits.log(
                HabitLogInput(habit_id=habit.id, log_date=today - timedelta(days=offset), value=25)
            )
        assert (
            container.habits.current_streak_only(habit.id)
            == container.habits.streak(habit.id).current_streak
        )

    def test_archiving_keeps_the_history(self, container: Container, today: date):
        habit = self._habit(container, today)
        container.habits.log(HabitLogInput(habit_id=habit.id, log_date=today, value=25))
        container.habits.archive(habit.id)
        assert not container.habits.list_habits(active_only=True)
        assert container.habits.completion_dates(habit.id)

    def test_deleting_takes_the_logs_with_it(self, container: Container, today: date):
        habit = self._habit(container, today)
        container.habits.log(HabitLogInput(habit_id=habit.id, log_date=today, value=25))
        container.habits.delete(habit.id)
        with pytest.raises(NotFoundError):
            container.habits.get(habit.id)

    def test_a_weekday_habit_is_not_due_at_the_weekend(self, container: Container):
        saturday = date(2026, 9, 12)
        habit = container.habits.create(
            HabitCreate(
                name="Standup",
                frequency=HabitFrequency.WEEKDAYS,
                start_date=date(2026, 9, 1),
            )
        )
        views = container.habits.today_view(saturday)
        view = next(item for item in views if item.habit.id == habit.id)
        assert not view.is_due_today

    def test_a_rest_day_log_counts_as_complete(self, container: Container, today: date):
        habit = self._habit(container, today)
        log = container.habits.log(
            HabitLogInput(habit_id=habit.id, log_date=today, is_rest_day=True)
        )
        assert log.completed

    def test_removing_a_log(self, container: Container, today: date):
        habit = self._habit(container, today)
        container.habits.log(HabitLogInput(habit_id=habit.id, log_date=today, value=25))
        assert container.habits.remove_log(habit.id, today)
        assert not container.habits.remove_log(habit.id, today)


class TestSleepService:
    def test_a_night_across_midnight(self, container: Container, today: date):
        record = container.sleep.record(
            SleepInput(log_date=today, sleep_time=time(23, 30), wake_time=time(6, 30))
        )
        assert record.duration_minutes == pytest.approx(420.0)

    def test_recording_twice_replaces_rather_than_duplicates(
        self, container: Container, today: date
    ):
        container.sleep.record(
            SleepInput(log_date=today, sleep_time=time(23, 30), wake_time=time(6, 30))
        )
        second = container.sleep.record(
            SleepInput(log_date=today, sleep_time=time(0, 30), wake_time=time(7, 30))
        )
        assert second.duration_minutes == pytest.approx(420.0)
        assert len(container.sleep.list_between(DateRange(start=today, end=today))) == 1

    def test_a_future_night_is_refused(self, container: Container, today: date):
        with pytest.raises(ValidationError):
            container.sleep.record(
                SleepInput(
                    log_date=today + timedelta(days=1),
                    sleep_time=time(23, 0),
                    wake_time=time(7, 0),
                )
            )

    def test_an_impossible_night_is_refused(self, container: Container, today: date):
        with pytest.raises(ValidationError):
            container.sleep.record(
                SleepInput(log_date=today, sleep_time=time(6, 0), wake_time=time(6, 10))
            )

    def test_quick_log_parses_clock_strings(self, container: Container, today: date):
        record = container.sleep.quick_log("23:20", "06:30", day=today)
        assert record.duration_minutes == pytest.approx(430.0)

    def test_quick_log_rejects_nonsense(self, container: Container, today: date):
        with pytest.raises(ValidationError):
            container.sleep.quick_log("bedtime", "morning", day=today)

    def test_stats_over_a_week(self, container: Container, today: date):
        for offset in range(7):
            container.sleep.record(
                SleepInput(
                    log_date=today - timedelta(days=offset),
                    sleep_time=time(23, 30),
                    wake_time=time(6, 30),
                    quality=8,
                )
            )
        stats = container.sleep.stats(DateRange.last_n_days(today, 7))
        assert stats.nights == 7
        assert stats.average_minutes == pytest.approx(420.0)
        assert stats.consistency_score == pytest.approx(100.0)

    def test_stats_on_an_empty_window(self, container: Container, today: date):
        stats = container.sleep.stats(DateRange.last_n_days(today, 7))
        assert stats.nights == 0
        assert stats.average_minutes is None

    def test_deleting_a_night(self, container: Container, today: date):
        container.sleep.record(
            SleepInput(log_date=today, sleep_time=time(23, 30), wake_time=time(6, 30))
        )
        assert container.sleep.delete(today)
        assert not container.sleep.delete(today)


class TestTimeAndActivities:
    def test_time_is_logged_against_a_category(
        self, container: Container, today: date, time_categories: dict[str, int]
    ):
        container.time_tracking.log(
            TimeEntryInput(
                log_date=today, category_id=time_categories["Coding"], duration_minutes=90
            )
        )
        entries = container.time_tracking.list_for_day(today)
        assert entries[0].duration_minutes == pytest.approx(90)

    def test_a_start_and_end_pair_produces_the_duration(
        self, container: Container, today: date, time_categories: dict[str, int]
    ):
        entry = container.time_tracking.log(
            TimeEntryInput(
                log_date=today,
                category_id=time_categories["Coding"],
                start_time=time(9, 0),
                end_time=time(10, 30),
            )
        )
        assert entry.duration_minutes == pytest.approx(90.0)

    def test_an_entry_crossing_midnight_is_measured_forwards(
        self, container: Container, today: date, time_categories: dict[str, int]
    ):
        entry = container.time_tracking.log(
            TimeEntryInput(
                log_date=today,
                category_id=time_categories["Coding"],
                start_time=time(23, 0),
                end_time=time(0, 30),
            )
        )
        assert entry.duration_minutes == pytest.approx(90.0)

    def test_the_wrong_kind_of_category_is_refused(
        self, container: Container, today: date, activity_categories: dict[str, int]
    ):
        with pytest.raises(ValidationError):
            container.time_tracking.log(
                TimeEntryInput(
                    log_date=today,
                    category_id=activity_categories["Cricket"],
                    duration_minutes=60,
                )
            )

    def test_overlap_is_allowed_by_default(
        self, container: Container, today: date, time_categories: dict[str, int]
    ):
        for _ in range(2):
            container.time_tracking.log(
                TimeEntryInput(
                    log_date=today,
                    category_id=time_categories["Coding"],
                    start_time=time(9, 0),
                    end_time=time(10, 0),
                )
            )
        assert len(container.time_tracking.list_for_day(today)) == 2

    def test_overlap_is_refused_when_the_setting_is_on(
        self, container: Container, today: date, time_categories: dict[str, int]
    ):
        from app.services.time_tracking_service import OVERLAP_SETTING_KEY

        container.app_settings.set(OVERLAP_SETTING_KEY, True)
        container.time_tracking.log(
            TimeEntryInput(
                log_date=today,
                category_id=time_categories["Coding"],
                start_time=time(9, 0),
                end_time=time(11, 0),
            )
        )
        with pytest.raises(ConflictError):
            container.time_tracking.log(
                TimeEntryInput(
                    log_date=today,
                    category_id=time_categories["Studying"],
                    start_time=time(10, 0),
                    end_time=time(12, 0),
                )
            )

    def test_quick_add_by_category_name(self, container: Container, today: date):
        entry = container.time_tracking.quick_add("Studying", 120, day=today)
        assert entry.duration_minutes == pytest.approx(120)

    def test_quick_add_with_an_unknown_name(self, container: Container, today: date):
        with pytest.raises(ValidationError):
            container.time_tracking.quick_add("Alchemy", 60, day=today)

    def test_allocation_totals_and_share(
        self, container: Container, today: date, time_categories: dict[str, int]
    ):
        container.time_tracking.quick_add("Coding", 120, day=today)
        container.time_tracking.quick_add("Entertainment", 60, day=today)
        allocation = container.time_tracking.allocation(DateRange(start=today, end=today))
        assert allocation.total_minutes == pytest.approx(180)
        assert allocation.productive_share == pytest.approx(120 / 180)

    def test_an_activity_is_logged_and_summarised(
        self, container: Container, today: date, activity_categories: dict[str, int]
    ):
        container.activities.log(
            ActivityInput(
                log_date=today,
                category_id=activity_categories["Cricket"],
                duration_minutes=80,
            )
        )
        summary = container.activities.summary(DateRange(start=today, end=today))
        assert summary.sessions == 1
        assert summary.total_minutes == pytest.approx(80)
        assert summary.minutes_by_category[0][0] == "Cricket"

    def test_calorie_estimation_needs_a_weight(
        self, container: Container, today: date, activity_categories: dict[str, int]
    ):
        activity = container.activities.log(
            ActivityInput(
                log_date=today,
                category_id=activity_categories["Cricket"],
                duration_minutes=60,
                estimate_calories=True,
            )
        )
        assert activity.calories is None

        container.health.record_measurement(BodyMeasurementInput(measured_on=today, weight_kg=70))
        with_weight = container.activities.log(
            ActivityInput(
                log_date=today,
                category_id=activity_categories["Cricket"],
                duration_minutes=60,
                estimate_calories=True,
            )
        )
        assert with_weight.calories is not None
        assert with_weight.calories > 0


class TestCategoryService:
    def test_a_duplicate_name_within_a_kind_is_refused(self, container: Container):
        with pytest.raises(ConflictError):
            container.categories.create(CategoryCreate(kind=CategoryKind.TIME, name="Coding"))

    def test_the_same_name_in_a_different_kind_is_fine(self, container: Container):
        created = container.categories.create(CategoryCreate(kind=CategoryKind.TASK, name="Coding"))
        assert created.kind is CategoryKind.TASK

    def test_a_category_in_use_cannot_be_deleted(
        self, container: Container, today: date, time_categories: dict[str, int]
    ):
        container.time_tracking.quick_add("Coding", 60, day=today)
        with pytest.raises(ValidationError) as caught:
            container.categories.delete(time_categories["Coding"])
        assert "Deactivate" in caught.value.user_message()

    def test_an_unused_category_can_be_deleted(self, container: Container):
        created = container.categories.create(
            CategoryCreate(kind=CategoryKind.TIME, name="Woodwork")
        )
        container.categories.delete(created.id)
        assert not [
            item
            for item in container.categories.list_kind(CategoryKind.TIME)
            if item.name == "Woodwork"
        ]

    def test_deactivating_hides_it_from_the_forms(
        self, container: Container, time_categories: dict[str, int]
    ):
        container.categories.deactivate(time_categories["Coding"])
        active = [item.name for item in container.categories.list_kind(CategoryKind.TIME)]
        assert "Coding" not in active


class TestGoalService:
    def test_progress_follows_the_milestones(self, container: Container, today: date):
        goal = container.goals.create(
            GoalCreate(
                title="Learn FastAPI",
                target_date=today + timedelta(days=30),
                milestones=[
                    MilestoneInput(title="Async"),
                    MilestoneInput(title="REST"),
                    MilestoneInput(title="Build"),
                    MilestoneInput(title="Deploy"),
                ],
            )
        )
        assert goal.progress_percent == pytest.approx(0.0)

        updated = container.goals.toggle_milestone(goal.milestones[0].id)
        assert updated.progress_percent == pytest.approx(25.0)

    def test_completing_every_milestone_completes_the_goal(self, container: Container, today: date):
        goal = container.goals.create(
            GoalCreate(
                title="Two steps",
                milestones=[MilestoneInput(title="a"), MilestoneInput(title="b")],
            )
        )
        for milestone in goal.milestones:
            goal = container.goals.toggle_milestone(milestone.id)
        from app.models.enums import GoalStatus

        assert goal.status is GoalStatus.COMPLETED
        assert goal.completed_at is not None

    def test_a_goal_without_milestones_keeps_its_manual_progress(self, container: Container):
        from app.schemas.goal import GoalUpdate

        goal = container.goals.create(GoalCreate(title="Vague ambition"))
        updated = container.goals.update(goal.id, GoalUpdate(progress_percent=40))
        assert updated.progress_percent == pytest.approx(40.0)

    def test_a_target_date_before_the_start_is_refused(self, container: Container, today: date):
        with pytest.raises(ValueError, match="target date"):
            GoalCreate(
                title="Impossible",
                start_date=today,
                target_date=today - timedelta(days=1),
            )

    def test_a_missing_milestone_raises(self, container: Container):
        with pytest.raises(NotFoundError):
            container.goals.toggle_milestone(999)

    def test_a_weekly_target_is_measured_from_the_records(self, container: Container, today: date):
        from app.core.timeutils import week_start
        from app.models.enums import WeeklyMetric

        monday = week_start(today)
        container.time_tracking.quick_add("Studying", 180, day=today)
        container.goals.set_weekly(
            WeeklyGoalInput(week_start=monday, metric=WeeklyMetric.STUDY_MINUTES, target_value=600)
        )
        weekly = container.goals.list_weekly(monday)
        assert weekly[0].achieved_value == pytest.approx(180.0)
        assert not weekly[0].is_met

    def test_setting_the_same_weekly_metric_twice_replaces_it(
        self, container: Container, today: date
    ):
        from app.core.timeutils import week_start
        from app.models.enums import WeeklyMetric

        monday = week_start(today)
        for target in (300, 600):
            container.goals.set_weekly(
                WeeklyGoalInput(
                    week_start=monday, metric=WeeklyMetric.STUDY_MINUTES, target_value=target
                )
            )
        weekly = container.goals.list_weekly(monday)
        assert len(weekly) == 1
        assert weekly[0].target_value == pytest.approx(600)


class TestJournalService:
    def test_saving_and_reading_back(self, container: Container, today: date):
        container.journal.save(JournalInput(entry_date=today, mood=8, reflection="Good day"))
        entry = container.journal.get_for_date(today)
        assert entry is not None
        assert entry.mood == 8

    def test_saving_twice_replaces(self, container: Container, today: date):
        container.journal.save(JournalInput(entry_date=today, mood=8))
        container.journal.save(JournalInput(entry_date=today, mood=3))
        assert not_none(container.journal.get_for_date(today)).mood == 3

    def test_a_future_entry_is_refused(self, container: Container, today: date):
        with pytest.raises(ValidationError):
            container.journal.save(JournalInput(entry_date=today + timedelta(days=1)))

    def test_the_morning_check_in_records_the_plan(self, container: Container, today: date):
        log = container.journal.morning_checkin(
            MorningCheckIn(
                log_date=today,
                energy=8,
                main_goal="Ship it",
                priorities=["a", "b", ""],
                planned_study_minutes=120,
            )
        )
        assert log.checkin_done
        assert log.priorities == ["a", "b"]
        assert not_none(container.journal.get_for_date(today)).energy == 8

    def test_the_evening_review_records_the_verdict(self, container: Container, today: date):
        log = container.journal.evening_review(
            EveningReview(log_date=today, mood=9, focus=7, day_rating=8, accomplishments="Lots")
        )
        assert log.review_done
        assert log.day_rating == 8
        entry = not_none(container.journal.get_for_date(today))
        assert entry.mood == 9
        assert entry.accomplishments == "Lots"

    def test_search_finds_the_text(self, container: Container, today: date):
        container.journal.save(
            JournalInput(entry_date=today, reflection="A quiet day of refactoring")
        )
        page = container.journal.search("refactoring", Pagination())
        assert page.total == 1

    def test_search_needs_a_term(self, container: Container):
        with pytest.raises(ValidationError):
            container.journal.search("  ", Pagination())


class TestHealthService:
    def test_a_measurement_replaces_the_same_day(self, container: Container, today: date):
        container.health.record_measurement(BodyMeasurementInput(measured_on=today, weight_kg=72))
        container.health.record_measurement(BodyMeasurementInput(measured_on=today, weight_kg=71))
        latest = not_none(container.health.latest_measurement())
        assert latest.weight_kg == pytest.approx(71)

    def test_the_snapshot_explains_what_is_missing(self, container: Container):
        snapshot = container.health.snapshot()
        assert not snapshot.is_available
        assert "weight" in not_none(snapshot.unavailable_reason).lower()

    def test_a_complete_profile_produces_an_estimate(self, container: Container, today: date):
        from app.models.enums import Sex

        container.health.update_profile(
            ProfileUpdate(birth_date=date(2001, 1, 1), sex=Sex.MALE, height_cm=176)
        )
        container.health.record_measurement(BodyMeasurementInput(measured_on=today, weight_kg=72))
        snapshot = container.health.snapshot()
        assert snapshot.is_available
        assert not_none(snapshot.tdee_kcal) > not_none(snapshot.bmr_kcal)

    def test_an_unknown_timezone_is_refused(self, container: Container):
        with pytest.raises(ValidationError):
            container.health.update_profile(ProfileUpdate(timezone="Mars/Olympus"))

    def test_comparing_formulas_reports_what_it_cannot_compute(
        self, container: Container, today: date
    ):
        from app.models.enums import BmrFormula

        container.health.record_measurement(BodyMeasurementInput(measured_on=today, weight_kg=72))
        comparison = container.health.compare_formulas()
        assert comparison[BmrFormula.KATCH_MCARDLE] is None  # no body fat recorded
