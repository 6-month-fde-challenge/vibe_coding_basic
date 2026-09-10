"""Task status rules, completion arithmetic and recurrence."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import ValidationError
from app.domain.tasks.recurrence import RecurrenceSpec, next_occurrence, occurrences_between
from app.domain.tasks.rules import (
    TaskSnapshot,
    is_overdue,
    summarize_tasks,
    validate_transition,
)
from app.models.enums import RecurrenceRule, TaskPriority, TaskStatus

TODAY = date(2026, 9, 10)


class TestTransitions:
    @pytest.mark.parametrize(
        ("current", "new"),
        [
            (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
            (TaskStatus.TODO, TaskStatus.COMPLETED),
            (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED),
            (TaskStatus.COMPLETED, TaskStatus.TODO),
            (TaskStatus.SKIPPED, TaskStatus.COMPLETED),
            (TaskStatus.CANCELLED, TaskStatus.TODO),
        ],
    )
    def test_legal_moves(self, current, new):
        validate_transition(current, new)

    @pytest.mark.parametrize(
        ("current", "new"),
        [
            (TaskStatus.CANCELLED, TaskStatus.COMPLETED),
            (TaskStatus.CANCELLED, TaskStatus.IN_PROGRESS),
            (TaskStatus.COMPLETED, TaskStatus.SKIPPED),
            (TaskStatus.COMPLETED, TaskStatus.CANCELLED),
        ],
    )
    def test_illegal_moves_are_refused(self, current, new):
        with pytest.raises(ValidationError):
            validate_transition(current, new)

    def test_a_move_to_the_same_status_is_a_no_op(self):
        validate_transition(TaskStatus.TODO, TaskStatus.TODO)

    def test_the_refusal_explains_itself(self):
        with pytest.raises(ValidationError) as caught:
            validate_transition(TaskStatus.CANCELLED, TaskStatus.COMPLETED)
        assert "cancelled" in caught.value.user_message().lower()


class TestCompletionSummary:
    def test_no_tasks(self):
        summary = summarize_tasks([])
        assert not summary.has_tasks
        assert summary.rate == 0.0

    def test_counts_and_rate(self):
        tasks = [
            TaskSnapshot(TaskStatus.COMPLETED),
            TaskSnapshot(TaskStatus.COMPLETED),
            TaskSnapshot(TaskStatus.TODO),
            TaskSnapshot(TaskStatus.SKIPPED),
        ]
        summary = summarize_tasks(tasks)
        assert summary.total == 4
        assert summary.completed == 2
        assert summary.pending == 1
        assert summary.skipped == 1
        assert summary.rate == pytest.approx(0.5)

    def test_cancelled_tasks_leave_the_denominator(self):
        tasks = [
            TaskSnapshot(TaskStatus.COMPLETED),
            TaskSnapshot(TaskStatus.CANCELLED),
            TaskSnapshot(TaskStatus.CANCELLED),
        ]
        summary = summarize_tasks(tasks)
        assert summary.total == 1
        assert summary.cancelled == 2
        assert summary.rate == pytest.approx(1.0)

    def test_everything_cancelled(self):
        summary = summarize_tasks([TaskSnapshot(TaskStatus.CANCELLED)])
        assert summary.total == 0
        assert summary.cancelled == 1

    def test_priority_weighting_favours_the_important_one(self):
        finished_critical = summarize_tasks(
            [
                TaskSnapshot(TaskStatus.COMPLETED, TaskPriority.CRITICAL),
                TaskSnapshot(TaskStatus.TODO, TaskPriority.LOW),
            ]
        )
        finished_trivial = summarize_tasks(
            [
                TaskSnapshot(TaskStatus.TODO, TaskPriority.CRITICAL),
                TaskSnapshot(TaskStatus.COMPLETED, TaskPriority.LOW),
            ]
        )
        assert finished_critical.rate == finished_trivial.rate
        assert finished_critical.weighted_rate > finished_trivial.weighted_rate

    def test_estimate_accuracy_only_uses_tasks_with_both_figures(self):
        summary = summarize_tasks(
            [
                TaskSnapshot(TaskStatus.COMPLETED, estimated_minutes=60, actual_minutes=90),
                TaskSnapshot(TaskStatus.COMPLETED, estimated_minutes=None, actual_minutes=30),
            ]
        )
        assert summary.estimate_accuracy == pytest.approx(1.5)

    def test_estimate_accuracy_is_none_without_data(self):
        assert summarize_tasks([TaskSnapshot(TaskStatus.TODO)]).estimate_accuracy is None


class TestOverdue:
    def test_an_open_task_past_its_date_is_overdue(self):
        task = TaskSnapshot(TaskStatus.TODO, due_date=date(2026, 9, 9))
        assert is_overdue(task, TODAY)

    def test_a_completed_task_is_never_overdue(self):
        task = TaskSnapshot(TaskStatus.COMPLETED, due_date=date(2026, 1, 1))
        assert not is_overdue(task, TODAY)

    def test_a_task_due_today_is_not_yet_overdue(self):
        assert not is_overdue(TaskSnapshot(TaskStatus.TODO, due_date=TODAY), TODAY)

    def test_a_task_with_no_due_date_is_never_overdue(self):
        assert not is_overdue(TaskSnapshot(TaskStatus.TODO), TODAY)


class TestRecurrence:
    def test_no_recurrence_produces_nothing(self):
        spec = RecurrenceSpec.build()
        assert next_occurrence(spec, TODAY, TODAY) is None

    def test_daily(self):
        spec = RecurrenceSpec.build(RecurrenceRule.DAILY)
        assert next_occurrence(spec, TODAY, TODAY) == date(2026, 9, 11)

    def test_every_third_day(self):
        spec = RecurrenceSpec.build(RecurrenceRule.CUSTOM, interval=3)
        assert next_occurrence(spec, TODAY, TODAY) == date(2026, 9, 13)

    def test_an_old_anchor_still_lands_on_the_right_phase(self):
        spec = RecurrenceSpec.build(RecurrenceRule.CUSTOM, interval=3)
        anchor = date(2026, 1, 1)
        result = next_occurrence(spec, anchor, TODAY)
        assert result is not None
        assert result > TODAY
        assert (result - anchor).days % 3 == 0

    def test_weekly(self):
        spec = RecurrenceSpec.build(RecurrenceRule.WEEKLY)
        assert next_occurrence(spec, TODAY, TODAY) == date(2026, 9, 17)

    def test_weekly_on_specific_days(self):
        # Anchor Monday 7th, firing Mondays and Wednesdays.
        spec = RecurrenceSpec.build(RecurrenceRule.WEEKLY, weekdays=[0, 2])
        anchor = date(2026, 9, 7)
        assert next_occurrence(spec, anchor, date(2026, 9, 7)) == date(2026, 9, 9)
        assert next_occurrence(spec, anchor, date(2026, 9, 9)) == date(2026, 9, 14)

    def test_fortnightly_skips_the_odd_week(self):
        spec = RecurrenceSpec.build(RecurrenceRule.WEEKLY, interval=2, weekdays=[0])
        anchor = date(2026, 9, 7)
        assert next_occurrence(spec, anchor, anchor) == date(2026, 9, 21)

    def test_monthly(self):
        spec = RecurrenceSpec.build(RecurrenceRule.MONTHLY)
        assert next_occurrence(spec, date(2026, 1, 15), date(2026, 1, 15)) == date(2026, 2, 15)

    def test_monthly_clamps_to_the_short_month(self):
        spec = RecurrenceSpec.build(RecurrenceRule.MONTHLY)
        assert next_occurrence(spec, date(2026, 1, 31), date(2026, 1, 31)) == date(2026, 2, 28)

    def test_monthly_clamps_in_a_leap_year(self):
        spec = RecurrenceSpec.build(RecurrenceRule.MONTHLY)
        assert next_occurrence(spec, date(2028, 1, 31), date(2028, 1, 31)) == date(2028, 2, 29)

    def test_monthly_wraps_the_year(self):
        spec = RecurrenceSpec.build(RecurrenceRule.MONTHLY)
        assert next_occurrence(spec, date(2026, 12, 5), date(2026, 12, 5)) == date(2027, 1, 5)

    def test_an_end_date_stops_it(self):
        spec = RecurrenceSpec.build(RecurrenceRule.DAILY, until=date(2026, 9, 10))
        assert next_occurrence(spec, TODAY, TODAY) is None

    def test_an_interval_below_one_is_refused(self):
        with pytest.raises(ValidationError):
            RecurrenceSpec.build(RecurrenceRule.DAILY, interval=0)

    def test_an_impossible_weekday_is_refused(self):
        with pytest.raises(ValidationError):
            RecurrenceSpec.build(RecurrenceRule.WEEKLY, weekdays=[9])

    def test_occurrences_between_is_inclusive_of_the_anchor(self):
        spec = RecurrenceSpec.build(RecurrenceRule.DAILY)
        found = list(occurrences_between(spec, TODAY, TODAY, TODAY.replace(day=13)))
        assert found == [date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 13)]

    def test_occurrences_between_respects_the_limit(self):
        spec = RecurrenceSpec.build(RecurrenceRule.DAILY)
        found = list(occurrences_between(spec, TODAY, TODAY, date(2027, 9, 10), limit=5))
        assert len(found) == 5

    def test_an_inverted_range_produces_nothing(self):
        spec = RecurrenceSpec.build(RecurrenceRule.DAILY)
        assert list(occurrences_between(spec, TODAY, TODAY, TODAY.replace(day=1))) == []

    def test_a_window_after_the_anchor_starts_at_the_right_phase(self):
        spec = RecurrenceSpec.build(RecurrenceRule.CUSTOM, interval=7)
        anchor = date(2026, 8, 1)
        found = list(occurrences_between(spec, anchor, date(2026, 9, 1), date(2026, 9, 30)))
        assert all((day - anchor).days % 7 == 0 for day in found)
        assert found[0] >= date(2026, 9, 1)
