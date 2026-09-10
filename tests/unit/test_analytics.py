"""Statistics, aggregations, trends and the insight rules."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domain.analytics.aggregations import (
    build_heatmap,
    distribution,
    fill_missing_days,
    group_by_month,
    group_by_week,
    rolling_totals,
)
from app.domain.analytics.insights import (
    HabitFacts,
    InsightContext,
    generate_insights,
    generate_recommendations,
)
from app.domain.analytics.statistics import (
    clamp,
    linear_slope,
    mean,
    median,
    moving_average,
    percentage_change,
    safe_divide,
    stdev,
)
from app.domain.analytics.trends import (
    best_and_worst,
    compare,
    compare_periods,
    detect_trend,
    weekday_averages,
)
from app.models.enums import InsightSeverity, TrendDirection

TODAY = date(2026, 9, 10)


class TestStatistics:
    def test_everything_is_safe_on_empty_input(self):
        assert mean([]) is None
        assert median([]) is None
        assert stdev([]) is None
        assert linear_slope([]) is None

    def test_stdev_needs_two_points(self):
        assert stdev([5.0]) is None
        assert stdev([4.0, 6.0]) == pytest.approx(1.0)

    def test_safe_divide_returns_the_default_on_zero(self):
        assert safe_divide(10, 0) == 0.0
        assert safe_divide(10, 0, default=-1) == -1
        assert safe_divide(10, 4) == pytest.approx(2.5)

    def test_percentage_change(self):
        assert percentage_change(100, 150) == pytest.approx(50.0)
        assert percentage_change(100, 50) == pytest.approx(-50.0)

    def test_percentage_change_is_undefined_from_zero(self):
        assert percentage_change(0, 50) is None
        assert percentage_change(None, 50) is None
        assert percentage_change(50, None) is None

    def test_percentage_change_from_a_negative_baseline(self):
        assert percentage_change(-100, -50) == pytest.approx(50.0)

    def test_moving_average_leaves_the_start_undefined(self):
        result = moving_average([1, 2, 3, 4, 5], window=3)
        assert result[:2] == [None, None]
        assert result[2] == pytest.approx(2.0)
        assert result[4] == pytest.approx(4.0)

    def test_moving_average_with_a_useless_window(self):
        assert moving_average([1, 2, 3], window=0) == [None, None, None]

    def test_slope_of_a_rising_line(self):
        assert linear_slope([1, 2, 3, 4]) == pytest.approx(1.0)

    def test_slope_of_a_flat_line(self):
        assert linear_slope([5, 5, 5]) == pytest.approx(0.0)

    def test_clamp(self):
        assert clamp(1.5) == 1.0
        assert clamp(-0.5) == 0.0
        assert clamp(5, 0, 10) == 5


class TestAggregations:
    def test_filling_gaps_makes_them_visible(self):
        series = {TODAY: 5.0}
        filled = fill_missing_days(series, TODAY - timedelta(days=2), TODAY)
        assert len(filled) == 3
        assert filled[TODAY - timedelta(days=1)] is None

    def test_filling_gaps_with_zero_for_counts(self):
        filled = fill_missing_days({}, TODAY, TODAY, default=0.0)
        assert filled[TODAY] == 0.0

    def test_group_by_week(self):
        series = {date(2026, 9, 7) + timedelta(days=n): float(n) for n in range(14)}
        buckets = group_by_week(series)
        assert len(buckets) == 2
        assert buckets[0].key == "2026-W37"
        assert buckets[0].days_with_data == 7
        assert buckets[0].coverage == pytest.approx(1.0)

    def test_group_by_month_knows_how_long_a_month_is(self):
        series = {date(2026, 2, day): 1.0 for day in (1, 15, 28)}
        buckets = group_by_month(series)
        assert buckets[0].key == "2026-02"
        assert buckets[0].days_in_bucket == 28
        assert buckets[0].total == pytest.approx(3.0)

    def test_grouping_nothing_produces_nothing(self):
        assert group_by_week({}) == []
        assert group_by_month({}) == []

    def test_heatmap_lays_days_out_by_week_and_weekday(self):
        start, end = date(2026, 9, 7), date(2026, 9, 20)  # two full Mon-Sun weeks
        cells = build_heatmap({date(2026, 9, 9): 42.0}, start, end)
        assert len(cells) == 14
        marked = next(cell for cell in cells if cell.day == date(2026, 9, 9))
        assert marked.weekday == 2
        assert marked.week_index == 0
        assert marked.value == 42.0
        assert cells[0].value is None

    def test_heatmap_of_an_inverted_range_is_empty(self):
        assert build_heatmap({}, TODAY, TODAY - timedelta(days=1)) == []

    def test_rolling_totals_slide_the_window(self):
        series = {TODAY - timedelta(days=n): 1.0 for n in range(5)}
        totals = rolling_totals(series, TODAY - timedelta(days=4), TODAY, window=3)
        assert totals[TODAY - timedelta(days=4)] == pytest.approx(1.0)
        assert totals[TODAY] == pytest.approx(3.0)

    def test_rolling_totals_with_a_useless_window(self):
        assert rolling_totals({}, TODAY, TODAY, window=0) == {}

    def test_distribution_buckets_values(self):
        counts = distribution([1, 5, 9, 14], buckets=[5, 10])
        assert counts["<5"] == 1
        assert counts["5-10"] == 2
        assert counts["10+"] == 1

    def test_distribution_without_buckets(self):
        assert distribution([1, 2], buckets=[]) == {}


class TestTrends:
    def test_a_small_change_is_flat(self):
        assert compare("Sleep", 100, 102).direction is TrendDirection.FLAT

    def test_a_large_rise_is_up(self):
        result = compare("Study", 100, 150)
        assert result.direction is TrendDirection.UP
        assert result.change == pytest.approx(50)

    def test_a_large_fall_is_down(self):
        assert compare("Sleep", 100, 50).direction is TrendDirection.DOWN

    def test_a_missing_side_is_flat_and_says_so(self):
        result = compare("Coding", None, 50)
        assert result.direction is TrendDirection.FLAT
        assert not result.has_both

    def test_compare_periods_covers_keys_from_both_sides(self):
        results = compare_periods({"a": 1.0}, {"b": 2.0})
        assert {item.label for item in results} == {"a", "b"}

    def test_compare_periods_uses_the_supplied_labels(self):
        results = compare_periods({"a": 1.0}, {"a": 2.0}, labels={"a": "Study"})
        assert results[0].label == "Study"

    def test_detect_trend_on_an_empty_series(self):
        trend = detect_trend("Sleep", [])
        assert trend.points == 0
        assert trend.direction is TrendDirection.FLAT

    def test_detect_trend_finds_a_rise(self):
        assert detect_trend("Study", [10, 20, 30, 40]).direction is TrendDirection.UP

    def test_detect_trend_ignores_noise(self):
        assert detect_trend("Sleep", [420, 421, 419, 420]).direction is TrendDirection.FLAT

    def test_best_and_worst(self):
        series = {TODAY: 80.0, TODAY - timedelta(days=1): 40.0}
        best, worst = best_and_worst(series)
        assert best is not None
        assert worst is not None
        assert best.day == TODAY
        assert worst.value == 40.0

    def test_best_and_worst_of_nothing(self):
        assert best_and_worst({}) == (None, None)

    def test_weekday_averages_group_by_day_of_week(self):
        series = {
            date(2026, 9, 7): 10.0,  # Monday
            date(2026, 9, 14): 20.0,  # Monday
            date(2026, 9, 8): 50.0,  # Tuesday
        }
        averages = weekday_averages(series)
        assert averages[0] == pytest.approx(15.0)
        assert averages[1] == pytest.approx(50.0)
        assert 5 not in averages


class TestInsights:
    def test_an_empty_context_produces_nothing(self):
        assert generate_insights(InsightContext(today=TODAY)) == []
        assert generate_recommendations(InsightContext(today=TODAY)) == []

    def test_a_long_streak_is_celebrated(self):
        context = InsightContext(
            today=TODAY,
            habits=[
                HabitFacts("Meditation", current_streak=9, longest_streak=12, completion_rate=0.9)
            ],
        )
        insights = generate_insights(context)
        assert any("Meditation" in item.message and "9 days" in item.message for item in insights)

    def test_a_personal_best_says_so(self):
        context = InsightContext(
            today=TODAY,
            habits=[
                HabitFacts("Coding", current_streak=12, longest_streak=12, completion_rate=0.9)
            ],
        )
        assert "longest ever" in generate_insights(context)[0].message

    def test_a_short_streak_is_not_mentioned(self):
        context = InsightContext(
            today=TODAY,
            habits=[HabitFacts("Reading", current_streak=2, longest_streak=3, completion_rate=0.9)],
        )
        assert not [item for item in generate_insights(context) if item.key == "best_streak"]

    def test_a_sleep_drop_is_flagged_for_attention(self):
        context = InsightContext(today=TODAY, sleep_avg_current=380, sleep_avg_previous=440)
        insight = next(item for item in generate_insights(context) if item.key == "sleep_change")
        assert insight.severity is InsightSeverity.ATTENTION
        assert "dropped" in insight.message

    def test_a_sleep_rise_is_positive(self):
        context = InsightContext(today=TODAY, sleep_avg_current=460, sleep_avg_previous=400)
        insight = next(item for item in generate_insights(context) if item.key == "sleep_change")
        assert insight.severity is InsightSeverity.POSITIVE

    def test_a_tiny_sleep_change_is_not_worth_saying(self):
        context = InsightContext(today=TODAY, sleep_avg_current=430, sleep_avg_previous=425)
        assert not [item for item in generate_insights(context) if item.key == "sleep_change"]

    def test_the_weekday_weekend_study_split(self):
        context = InsightContext(today=TODAY, study_weekday_avg=120, study_weekend_avg=60)
        insight = next(
            item for item in generate_insights(context) if item.key == "study_weekday_vs_weekend"
        )
        assert "100% more on weekdays" in insight.message

    def test_the_task_load_sweet_spot(self):
        context = InsightContext(today=TODAY, completion_by_task_count={5: 0.9, 12: 0.3})
        insight = next(
            item for item in generate_insights(context) if item.key == "task_load_sweet_spot"
        )
        assert "5" in insight.message

    def test_insights_carry_their_evidence(self):
        context = InsightContext(today=TODAY, sleep_avg_current=380, sleep_avg_previous=440)
        insight = next(item for item in generate_insights(context) if item.key == "sleep_change")
        assert insight.evidence["current_minutes"] == 380

    def test_the_number_of_insights_is_capped(self):
        context = InsightContext(
            today=TODAY,
            habits=[HabitFacts("A", 9, 9, 0.2), HabitFacts("B", 1, 1, 0.1)],
            sleep_avg_current=380,
            sleep_avg_previous=440,
            bedtime_shift_minutes=45,
            study_weekday_avg=120,
            study_weekend_avg=40,
            weekday_productivity={0: 80.0, 1: 60.0, 2: 70.0},
            completion_by_task_count={5: 0.9, 12: 0.3},
        )
        assert len(generate_insights(context, limit=3)) == 3


class TestRecommendations:
    def test_repeated_misses_suggest_easing_the_target(self):
        context = InsightContext(
            today=TODAY,
            habits=[HabitFacts("Study", 0, 10, 0.4, consecutive_misses=4)],
        )
        recommendation = generate_recommendations(context)[0]
        assert "Study" in recommendation.message
        assert "4 days in a row" in recommendation.rationale

    def test_one_miss_is_not_a_pattern(self):
        context = InsightContext(
            today=TODAY, habits=[HabitFacts("Study", 0, 10, 0.4, consecutive_misses=1)]
        )
        assert generate_recommendations(context) == []

    def test_short_sleep_suggests_an_earlier_bedtime(self):
        context = InsightContext(
            today=TODAY,
            sleep_avg_current=390,
            sleep_target_minutes=450,
            sleep_nights_below_target=5,
        )
        recommendation = generate_recommendations(context)[0]
        assert recommendation.key == "earlier_bedtime"
        assert "1h" in recommendation.message

    def test_sleeping_enough_produces_no_nudge(self):
        context = InsightContext(
            today=TODAY,
            sleep_avg_current=470,
            sleep_target_minutes=450,
            sleep_nights_below_target=5,
        )
        assert not [
            item for item in generate_recommendations(context) if item.key == "earlier_bedtime"
        ]

    def test_an_overloaded_day_suggests_trimming(self):
        context = InsightContext(
            today=TODAY, completion_by_task_count={5: 0.9, 12: 0.3}, tasks_planned_today=12
        )
        recommendation = next(
            item for item in generate_recommendations(context) if item.key == "fewer_tasks"
        )
        assert "12" in recommendation.message
        assert "5" in recommendation.message

    def test_a_light_day_is_left_alone(self):
        context = InsightContext(
            today=TODAY, completion_by_task_count={5: 0.9}, tasks_planned_today=3
        )
        assert not [item for item in generate_recommendations(context) if item.key == "fewer_tasks"]
