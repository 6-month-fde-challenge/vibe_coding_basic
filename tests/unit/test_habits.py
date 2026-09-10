"""Habit scheduling, completion rules and the streak engine."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from app.core.errors import ValidationError
from app.domain.habits.completion import HabitTarget, evaluate
from app.domain.habits.schedule import HabitSchedule
from app.domain.habits.streaks import current_streak, longest_streak, summarize
from app.models.enums import HabitDirection, HabitFrequency, HabitType

#: 2026-09-10 is a Thursday.
TODAY = date(2026, 9, 10)


def days(*offsets: int) -> list[date]:
    """Return dates that many days before :data:`TODAY`, oldest first."""
    return sorted(TODAY - timedelta(days=offset) for offset in offsets)


class TestSchedule:
    def test_daily_expects_every_day(self):
        schedule = HabitSchedule.build()
        assert all(schedule.is_expected_on(TODAY - timedelta(days=n)) for n in range(14))

    def test_weekdays_skips_the_weekend(self):
        schedule = HabitSchedule.build(frequency=HabitFrequency.WEEKDAYS)
        assert schedule.is_expected_on(date(2026, 9, 11))  # Friday
        assert not schedule.is_expected_on(date(2026, 9, 12))  # Saturday
        assert not schedule.is_expected_on(date(2026, 9, 13))  # Sunday

    def test_specific_days(self):
        schedule = HabitSchedule.build(
            frequency=HabitFrequency.SPECIFIC_DAYS, specific_days=[0, 2, 4]
        )
        assert schedule.is_expected_on(date(2026, 9, 14))  # Monday
        assert not schedule.is_expected_on(date(2026, 9, 15))  # Tuesday

    def test_a_rest_day_is_never_expected(self):
        schedule = HabitSchedule.build(rest_days=[6])
        assert not schedule.is_expected_on(date(2026, 9, 13))  # Sunday
        assert schedule.is_rest_day(date(2026, 9, 13))

    def test_nothing_is_expected_before_the_start_date(self):
        schedule = HabitSchedule.build(start_date=TODAY)
        assert not schedule.is_expected_on(TODAY - timedelta(days=1))
        assert schedule.is_expected_on(TODAY)

    def test_nothing_is_expected_after_the_end_date(self):
        schedule = HabitSchedule.build(end_date=TODAY - timedelta(days=1))
        assert not schedule.is_expected_on(TODAY)

    def test_a_flexible_habit_expects_no_particular_day(self):
        schedule = HabitSchedule.build(frequency=HabitFrequency.TIMES_PER_WEEK, times_per_week=3)
        assert schedule.is_flexible
        assert not schedule.is_expected_on(TODAY)

    def test_counting_expected_days_in_a_range(self):
        schedule = HabitSchedule.build(frequency=HabitFrequency.WEEKDAYS)
        # 2026-09-07 (Mon) to 2026-09-13 (Sun) is five weekdays.
        assert schedule.count_expected(date(2026, 9, 7), date(2026, 9, 13)) == 5

    def test_previous_expected_skips_backwards_over_the_weekend(self):
        schedule = HabitSchedule.build(frequency=HabitFrequency.WEEKDAYS)
        assert schedule.previous_expected(date(2026, 9, 13)) == date(2026, 9, 11)


class TestCompletion:
    def test_boolean_is_the_tick_box(self):
        target = HabitTarget(habit_type=HabitType.BOOLEAN)
        assert evaluate(target, checked=True).completed
        assert not evaluate(target, checked=False).completed

    def test_a_measured_habit_meets_its_target(self):
        target = HabitTarget(habit_type=HabitType.DURATION, target_value=20)
        assert evaluate(target, value=25).completed
        assert evaluate(target, value=20).completed
        assert not evaluate(target, value=19).completed

    def test_a_near_miss_still_reports_progress(self):
        target = HabitTarget(habit_type=HabitType.DURATION, target_value=20)
        result = evaluate(target, value=15)
        assert not result.completed
        assert result.ratio == pytest.approx(0.75)

    def test_a_minimum_target_keeps_the_chain_alive(self):
        target = HabitTarget(habit_type=HabitType.DURATION, target_value=20, min_target=10)
        result = evaluate(target, value=12)
        assert result.completed
        assert result.partial

    def test_a_ceiling_habit_passes_when_under_the_limit(self):
        target = HabitTarget(
            habit_type=HabitType.DURATION, direction=HabitDirection.AT_MOST, target_value=30
        )
        assert evaluate(target, value=10).completed
        assert evaluate(target, value=30).completed
        assert not evaluate(target, value=45).completed

    def test_a_ceiling_habit_at_zero_is_a_perfect_day(self):
        target = HabitTarget(
            habit_type=HabitType.DURATION, direction=HabitDirection.AT_MOST, target_value=0
        )
        assert evaluate(target, value=0).completed

    def test_wake_before_a_target_time(self):
        target = HabitTarget(
            habit_type=HabitType.TIME,
            direction=HabitDirection.BEFORE,
            target_time=time(6, 30),
        )
        assert evaluate(target, value_time=time(6, 15)).completed
        assert not evaluate(target, value_time=time(7, 0)).completed

    def test_being_slightly_late_scores_better_than_being_very_late(self):
        target = HabitTarget(
            habit_type=HabitType.TIME,
            direction=HabitDirection.BEFORE,
            target_time=time(6, 30),
        )
        slightly = evaluate(target, value_time=time(6, 40))
        very = evaluate(target, value_time=time(9, 0))
        assert slightly.ratio > very.ratio

    def test_after_a_target_time(self):
        target = HabitTarget(
            habit_type=HabitType.TIME, direction=HabitDirection.AFTER, target_time=time(22, 0)
        )
        assert evaluate(target, value_time=time(22, 30)).completed
        assert not evaluate(target, value_time=time(21, 0)).completed

    def test_a_measured_habit_without_a_value_is_refused(self):
        with pytest.raises(ValidationError):
            evaluate(HabitTarget(habit_type=HabitType.COUNT, target_value=30))

    def test_a_time_habit_without_a_time_is_refused(self):
        with pytest.raises(ValidationError):
            evaluate(HabitTarget(habit_type=HabitType.TIME, target_time=time(6, 30)))

    def test_a_negative_value_is_refused(self):
        with pytest.raises(ValidationError):
            evaluate(HabitTarget(habit_type=HabitType.COUNT, target_value=10), value=-5)


class TestCurrentStreak:
    def test_the_worked_example_from_the_readme(self):
        # Done 3rd-6th, missed the 7th, done 8th-9th, today unlogged.
        completions = [
            date(2026, 9, 3),
            date(2026, 9, 4),
            date(2026, 9, 5),
            date(2026, 9, 6),
            date(2026, 9, 8),
            date(2026, 9, 9),
        ]
        schedule = HabitSchedule.build()
        assert current_streak(reversed(completions), schedule, TODAY) == 2
        assert longest_streak(completions, schedule) == 4

    def test_today_being_unlogged_does_not_break_the_run(self):
        schedule = HabitSchedule.build()
        completions = days(1, 2, 3)
        assert current_streak(reversed(completions), schedule, TODAY) == 3

    def test_without_grace_an_unlogged_today_ends_the_run(self):
        schedule = HabitSchedule.build()
        completions = days(1, 2, 3)
        assert current_streak(reversed(completions), schedule, TODAY, grace_today=False) == 0

    def test_logging_today_extends_the_run(self):
        schedule = HabitSchedule.build()
        completions = days(0, 1, 2, 3)
        assert current_streak(reversed(completions), schedule, TODAY) == 4

    def test_a_gap_yesterday_ends_the_run(self):
        schedule = HabitSchedule.build()
        completions = days(2, 3, 4)
        assert current_streak(reversed(completions), schedule, TODAY) == 0

    def test_no_completions_at_all(self):
        assert current_streak([], HabitSchedule.build(), TODAY) == 0

    def test_a_weekday_habit_is_not_broken_by_the_weekend(self):
        schedule = HabitSchedule.build(frequency=HabitFrequency.WEEKDAYS)
        # Thu 10, Wed 9, Tue 8, Mon 7, then Fri 4 across the weekend.
        completions = [
            date(2026, 9, 4),
            date(2026, 9, 7),
            date(2026, 9, 8),
            date(2026, 9, 9),
            date(2026, 9, 10),
        ]
        assert current_streak(reversed(completions), schedule, TODAY) == 5

    def test_a_rest_day_is_not_a_miss(self):
        schedule = HabitSchedule.build(rest_days=[6])  # Sundays off
        completions = [
            date(2026, 9, 4),
            date(2026, 9, 5),
            date(2026, 9, 7),  # Sunday the 6th skipped
            date(2026, 9, 8),
            date(2026, 9, 9),
            date(2026, 9, 10),
        ]
        assert current_streak(reversed(completions), schedule, TODAY) == 6

    def test_a_future_dated_completion_is_ignored(self):
        schedule = HabitSchedule.build()
        completions = [*days(0, 1), TODAY + timedelta(days=2)]
        assert current_streak(sorted(completions, reverse=True), schedule, TODAY) == 2

    def test_a_bonus_completion_neither_helps_nor_breaks(self):
        schedule = HabitSchedule.build(frequency=HabitFrequency.WEEKDAYS)
        completions = [
            date(2026, 9, 5),  # a bonus Saturday
            date(2026, 9, 7),
            date(2026, 9, 8),
            date(2026, 9, 9),
            date(2026, 9, 10),
        ]
        assert current_streak(sorted(completions, reverse=True), schedule, TODAY) == 4

    def test_the_streak_stops_at_the_start_date(self):
        schedule = HabitSchedule.build(start_date=TODAY - timedelta(days=2))
        completions = days(0, 1, 2)
        assert current_streak(reversed(completions), schedule, TODAY) == 3

    def test_a_flexible_habit_counts_qualifying_weeks(self):
        schedule = HabitSchedule.build(frequency=HabitFrequency.TIMES_PER_WEEK, times_per_week=3)
        # Three in the current week (Mon 7 onwards) and three the week before.
        completions = [
            date(2026, 8, 31),
            date(2026, 9, 2),
            date(2026, 9, 4),
            date(2026, 9, 7),
            date(2026, 9, 9),
            date(2026, 9, 10),
        ]
        assert current_streak(sorted(completions, reverse=True), schedule, TODAY) == 2

    def test_the_iterator_is_consumed_lazily(self):
        """A long history with a short streak must not be read to the end."""
        schedule = HabitSchedule.build()
        pulled = 0

        def source():
            nonlocal pulled
            # Today and yesterday, then a gap, then a thousand older days.
            for day in [TODAY, TODAY - timedelta(days=1)]:
                pulled += 1
                yield day
            for offset in range(5, 1005):
                pulled += 1
                yield TODAY - timedelta(days=offset)

        assert current_streak(source(), schedule, TODAY) == 2
        assert pulled <= 3


class TestLongestStreak:
    def test_no_completions(self):
        assert longest_streak([], HabitSchedule.build()) == 0

    def test_one_completion(self):
        assert longest_streak([TODAY], HabitSchedule.build()) == 1

    def test_the_best_run_is_found_wherever_it_sits(self):
        completions = [
            date(2026, 8, 1),
            date(2026, 8, 2),
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
            date(2026, 9, 9),
            date(2026, 9, 10),
        ]
        assert longest_streak(completions, HabitSchedule.build()) == 5

    def test_duplicates_do_not_inflate_it(self):
        completions = [TODAY, TODAY, TODAY - timedelta(days=1)]
        assert longest_streak(completions, HabitSchedule.build()) == 2

    def test_order_does_not_matter(self):
        completions = days(0, 1, 2, 5, 6)
        assert longest_streak(completions, HabitSchedule.build()) == longest_streak(
            list(reversed(completions)), HabitSchedule.build()
        )


class TestSummary:
    def test_empty_history_is_safe(self):
        summary = summarize([], HabitSchedule.build(), TODAY)
        assert not summary.has_history
        assert summary.current_streak == 0
        assert summary.completion_rate == 0.0

    def test_rates_and_misses(self):
        schedule = HabitSchedule.build(start_date=TODAY - timedelta(days=6))
        completions = days(0, 1, 2, 4, 5, 6)  # missed three days ago
        summary = summarize(completions, schedule, TODAY)
        assert summary.expected_days == 7
        assert summary.total_completions == 6
        assert summary.missed_days == 1
        assert summary.completion_rate == pytest.approx(6 / 7)

    def test_today_is_not_counted_as_a_miss_yet(self):
        schedule = HabitSchedule.build(start_date=TODAY - timedelta(days=2))
        summary = summarize(days(1, 2), schedule, TODAY)
        assert summary.missed_days == 0

    def test_a_bonus_day_cannot_push_the_rate_over_one(self):
        schedule = HabitSchedule.build(
            frequency=HabitFrequency.WEEKDAYS, start_date=date(2026, 9, 7)
        )
        completions = [
            date(2026, 9, 7),
            date(2026, 9, 8),
            date(2026, 9, 9),
            date(2026, 9, 10),
            date(2026, 9, 12),  # a bonus Saturday
        ]
        summary = summarize(completions, schedule, date(2026, 9, 13))
        assert summary.completion_rate <= 1.0
