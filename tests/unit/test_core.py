"""Time handling, errors, goals, allocation and the schema contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import (
    AppError,
    ConflictError,
    DatabaseError,
    NotFoundError,
    ValidationError,
)
from app.core.logging_config import safe_preview
from app.core.timeutils import (
    FixedClock,
    combine_local,
    date_range,
    day_bounds_utc,
    days_between,
    format_duration,
    iso_week_label,
    local_date_of,
    minutes_between,
    month_bounds,
    month_label,
    to_local,
    week_bounds,
    week_start,
    weekday_name,
)
from app.domain.goals.progress import (
    MilestoneSnapshot,
    compute_pace,
    derive_status,
    progress_from_milestones,
    validate_progress,
)
from app.domain.timetracking.allocation import (
    Interval,
    TimeSlice,
    build_allocation,
    find_overlap,
    intervals_overlap,
)
from app.models.enums import GoalStatus, TaskPriority, TaskStatus
from app.schemas.common import DateRange, Page, Pagination
from app.schemas.habit import HabitCreate
from app.schemas.task import TaskCreate

KOLKATA = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 9, 10)


class TestTimeUtils:
    def test_a_local_day_is_a_half_open_utc_interval(self):
        start, end = day_bounds_utc(TODAY, KOLKATA)
        assert end - start == timedelta(days=1)
        assert start.tzinfo is UTC

    def test_kolkata_midnight_is_the_previous_evening_in_utc(self):
        start, _ = day_bounds_utc(TODAY, KOLKATA)
        assert start == datetime(2026, 9, 9, 18, 30, tzinfo=UTC)

    def test_a_dst_day_is_not_assumed_to_be_24_hours(self):
        london = ZoneInfo("Europe/London")
        # 2026-10-25: clocks go back, so the local day is 25 hours long.
        start, end = day_bounds_utc(date(2026, 10, 25), london)
        assert end - start == timedelta(hours=25)

    def test_an_instant_lands_on_the_right_local_day(self):
        instant = datetime(2026, 9, 9, 19, 0, tzinfo=UTC)  # 00:30 in Kolkata
        assert local_date_of(instant, KOLKATA) == TODAY

    def test_combine_local_produces_utc(self):
        result = combine_local(TODAY, time(6, 30), KOLKATA)
        assert result == datetime(2026, 9, 10, 1, 0, tzinfo=UTC)

    def test_to_local_round_trips(self):
        instant = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
        assert to_local(instant, KOLKATA).time() == time(6, 30)

    def test_minutes_between_is_real_elapsed_time(self):
        start = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
        end = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
        assert minutes_between(start, end) == pytest.approx(420.0)

    def test_week_start_is_monday_by_default(self):
        assert week_start(TODAY) == date(2026, 9, 7)

    def test_week_start_can_be_sunday(self):
        assert week_start(TODAY, first_weekday=6) == date(2026, 9, 6)

    def test_week_bounds_span_seven_days(self):
        start, end = week_bounds(TODAY)
        assert (end - start).days == 6

    def test_month_bounds(self):
        assert month_bounds(TODAY) == (date(2026, 9, 1), date(2026, 9, 30))

    def test_month_bounds_in_february(self):
        assert month_bounds(date(2026, 2, 15))[1] == date(2026, 2, 28)

    def test_date_range_is_inclusive(self):
        assert len(list(date_range(TODAY, TODAY + timedelta(days=2)))) == 3

    def test_an_inverted_date_range_is_empty(self):
        assert list(date_range(TODAY, TODAY - timedelta(days=1))) == []

    def test_days_between_is_inclusive_and_never_negative(self):
        assert days_between(TODAY, TODAY) == 1
        assert days_between(TODAY, TODAY - timedelta(days=5)) == 0

    def test_labels(self):
        assert weekday_name(TODAY) == "Thursday"
        assert iso_week_label(TODAY) == "2026-W37"
        assert month_label(TODAY) == "2026-09"

    @pytest.mark.parametrize(
        ("minutes", "expected"),
        [(0, "0m"), (45, "45m"), (60, "1h"), (452, "7h 32m"), (None, "-"), (-5, "-")],
    )
    def test_duration_formatting(self, minutes, expected):
        assert format_duration(minutes) == expected

    def test_a_fixed_clock_does_not_move(self):
        clock = FixedClock(datetime(2026, 9, 10, 12, 0, tzinfo=UTC), KOLKATA)
        assert clock.today() == TODAY
        assert clock.now() == clock.now()


class TestErrors:
    def test_every_error_is_an_app_error(self):
        for error in (
            ValidationError("bad"),
            NotFoundError("Task", 1),
            ConflictError("clash"),
            DatabaseError("down"),
        ):
            assert isinstance(error, AppError)

    def test_details_are_rendered_for_the_log(self):
        error = ValidationError("Bad value", field="weight_kg", value=-1)
        assert "weight_kg" in str(error)
        assert "-1" in str(error)

    def test_the_user_message_is_a_sentence_not_a_dump(self):
        error = NotFoundError("Task", 42)
        assert error.user_message() == "No task matching 42."

    def test_a_database_error_does_not_leak_internals(self):
        message = DatabaseError("relation does not exist").user_message()
        assert "relation" not in message

    def test_safe_preview_truncates(self):
        assert safe_preview("a" * 100, limit=10).endswith("(100 chars)")

    def test_safe_preview_of_nothing(self):
        assert safe_preview(None) == "<empty>"


class TestGoals:
    def test_progress_from_milestones(self):
        milestones = [
            MilestoneSnapshot("a", True),
            MilestoneSnapshot("b", True),
            MilestoneSnapshot("c", False),
            MilestoneSnapshot("d", False),
        ]
        assert progress_from_milestones(milestones) == pytest.approx(50.0)

    def test_no_milestones_means_no_opinion(self):
        assert progress_from_milestones([]) is None

    def test_progress_outside_the_range_is_refused(self):
        with pytest.raises(ValidationError):
            validate_progress(120)
        with pytest.raises(ValidationError):
            validate_progress(-1)

    def test_reaching_a_hundred_completes_the_goal(self):
        assert derive_status(100, GoalStatus.IN_PROGRESS) is GoalStatus.COMPLETED

    def test_starting_work_starts_the_goal(self):
        assert derive_status(10, GoalStatus.NOT_STARTED) is GoalStatus.IN_PROGRESS

    def test_a_paused_goal_is_left_where_the_user_put_it(self):
        assert derive_status(100, GoalStatus.ON_HOLD) is GoalStatus.ON_HOLD
        assert derive_status(50, GoalStatus.ABANDONED) is GoalStatus.ABANDONED

    def test_reducing_progress_reopens_a_completed_goal(self):
        assert derive_status(80, GoalStatus.COMPLETED) is GoalStatus.IN_PROGRESS

    def test_pace_flags_a_goal_that_has_fallen_behind(self):
        pace = compute_pace(
            progress_percent=10,
            start_date=TODAY - timedelta(days=80),
            target_date=TODAY + timedelta(days=20),
            today=TODAY,
            status=GoalStatus.IN_PROGRESS,
        )
        assert pace.is_behind
        assert pace.elapsed_fraction == pytest.approx(0.8)
        assert pace.days_remaining == 20

    def test_a_goal_on_track_is_not_flagged(self):
        pace = compute_pace(
            progress_percent=80,
            start_date=TODAY - timedelta(days=80),
            target_date=TODAY + timedelta(days=20),
            today=TODAY,
            status=GoalStatus.IN_PROGRESS,
        )
        assert not pace.is_behind

    def test_a_goal_with_no_deadline_cannot_be_late(self):
        pace = compute_pace(
            progress_percent=0,
            start_date=None,
            target_date=None,
            today=TODAY,
            status=GoalStatus.IN_PROGRESS,
        )
        assert pace.elapsed_fraction is None
        assert not pace.is_behind
        assert not pace.is_overdue

    def test_a_missed_deadline_is_overdue(self):
        pace = compute_pace(
            progress_percent=50,
            start_date=TODAY - timedelta(days=30),
            target_date=TODAY - timedelta(days=1),
            today=TODAY,
            status=GoalStatus.IN_PROGRESS,
        )
        assert pace.is_overdue
        assert pace.days_remaining == -1

    def test_a_completed_goal_is_never_overdue(self):
        pace = compute_pace(
            progress_percent=100,
            start_date=TODAY - timedelta(days=30),
            target_date=TODAY - timedelta(days=5),
            today=TODAY,
            status=GoalStatus.COMPLETED,
        )
        assert not pace.is_overdue


class TestAllocation:
    def test_an_empty_allocation(self):
        allocation = build_allocation([])
        assert not allocation.has_data
        assert allocation.productive_share == 0.0

    def test_slices_are_ordered_largest_first(self):
        allocation = build_allocation([TimeSlice(1, "Coding", 60), TimeSlice(2, "Study", 120)])
        assert [item.category_name for item in allocation.slices] == ["Study", "Coding"]

    def test_duplicate_categories_are_merged(self):
        allocation = build_allocation([TimeSlice(1, "Coding", 60), TimeSlice(1, "Coding", 30)])
        assert len(allocation.slices) == 1
        assert allocation.total_minutes == pytest.approx(90)

    def test_the_productive_share(self):
        allocation = build_allocation(
            [
                TimeSlice(1, "Coding", 60, is_productive=True),
                TimeSlice(2, "TV", 60, is_productive=False),
            ]
        )
        assert allocation.productive_share == pytest.approx(0.5)

    def test_untracked_time_is_never_negative(self):
        allocation = build_allocation([TimeSlice(1, "Work", 900)], available_minutes=600)
        assert allocation.untracked_minutes == 0.0

    def test_share_of_an_unknown_category(self):
        allocation = build_allocation([TimeSlice(1, "Coding", 60)])
        assert allocation.share_of(999) == 0.0

    def test_back_to_back_intervals_do_not_overlap(self):
        first = Interval(
            datetime(2026, 9, 10, 9, tzinfo=UTC), datetime(2026, 9, 10, 10, tzinfo=UTC)
        )
        second = Interval(
            datetime(2026, 9, 10, 10, tzinfo=UTC), datetime(2026, 9, 10, 11, tzinfo=UTC)
        )
        assert not intervals_overlap(first, second)

    def test_partly_covering_intervals_do_overlap(self):
        first = Interval(
            datetime(2026, 9, 10, 9, tzinfo=UTC), datetime(2026, 9, 10, 11, tzinfo=UTC)
        )
        second = Interval(
            datetime(2026, 9, 10, 10, tzinfo=UTC), datetime(2026, 9, 10, 12, tzinfo=UTC)
        )
        assert intervals_overlap(first, second)

    def test_an_interval_does_not_clash_with_itself(self):
        existing = Interval(
            datetime(2026, 9, 10, 9, tzinfo=UTC),
            datetime(2026, 9, 10, 11, tzinfo=UTC),
            identifier=7,
        )
        candidate = Interval(existing.start, existing.end, identifier=7)
        assert find_overlap(candidate, [existing]) is None

    def test_find_overlap_returns_the_clashing_interval(self):
        existing = Interval(
            datetime(2026, 9, 10, 9, tzinfo=UTC),
            datetime(2026, 9, 10, 11, tzinfo=UTC),
            identifier=1,
        )
        candidate = Interval(
            datetime(2026, 9, 10, 10, tzinfo=UTC),
            datetime(2026, 9, 10, 12, tzinfo=UTC),
            identifier=2,
        )
        assert find_overlap(candidate, [existing]) is existing


class TestSchemas:
    def test_a_date_range_must_be_ordered(self):
        with pytest.raises(PydanticValidationError):
            DateRange(start=TODAY, end=TODAY - timedelta(days=1))

    def test_last_n_days_is_inclusive(self):
        period = DateRange.last_n_days(TODAY, 7)
        assert period.days == 7
        assert period.end == TODAY

    def test_the_previous_period_is_the_same_length(self):
        period = DateRange.last_n_days(TODAY, 7)
        previous = period.previous()
        assert previous.days == period.days
        assert previous.end == period.start - timedelta(days=1)

    def test_pagination_is_bounded(self):
        with pytest.raises(PydanticValidationError):
            Pagination(limit=100_000)

    def test_the_next_page_advances_by_the_limit(self):
        assert Pagination(limit=20, offset=0).next_page().offset == 20

    def test_page_arithmetic(self):
        page = Page[int](items=[1, 2, 3], total=10, limit=3, offset=3)
        assert page.page_number == 2
        assert page.page_count == 4
        assert page.has_more

    def test_the_last_page_has_no_more(self):
        page = Page[int](items=[10], total=10, limit=3, offset=9)
        assert not page.has_more

    def test_a_recurring_task_needs_a_due_date(self):
        from app.models.enums import RecurrenceRule

        with pytest.raises(PydanticValidationError):
            TaskCreate(title="Standup", recurrence=RecurrenceRule.DAILY)

    def test_a_task_needs_a_title(self):
        with pytest.raises(PydanticValidationError):
            TaskCreate(title="")

    def test_unknown_fields_are_rejected(self):
        with pytest.raises(PydanticValidationError):
            TaskCreate(title="Fine", nonsense=True)  # type: ignore[call-arg]

    def test_a_measured_habit_needs_a_target(self):
        from app.models.enums import HabitType

        with pytest.raises(PydanticValidationError):
            HabitCreate(name="Read", habit_type=HabitType.COUNT)

    def test_a_time_habit_needs_a_target_time(self):
        from app.models.enums import HabitType

        with pytest.raises(PydanticValidationError):
            HabitCreate(name="Wake early", habit_type=HabitType.TIME)

    def test_a_minimum_above_the_target_is_refused(self):
        from app.models.enums import HabitType

        with pytest.raises(PydanticValidationError):
            HabitCreate(name="Read", habit_type=HabitType.COUNT, target_value=10, min_target=20)

    def test_a_specific_days_habit_needs_days(self):
        from app.models.enums import HabitFrequency

        with pytest.raises(PydanticValidationError):
            HabitCreate(name="Gym", frequency=HabitFrequency.SPECIFIC_DAYS)


class TestEnums:
    def test_priority_weights_are_ordered(self):
        weights = [priority.weight for priority in TaskPriority]
        assert weights == sorted(weights)

    def test_terminal_statuses(self):
        assert TaskStatus.COMPLETED.is_terminal
        assert TaskStatus.CANCELLED.is_terminal
        assert not TaskStatus.TODO.is_terminal

    def test_only_completed_counts_as_done(self):
        assert TaskStatus.COMPLETED.counts_as_done
        assert not TaskStatus.SKIPPED.counts_as_done
