"""The dashboard, reviews, heatmap and the coach, against real data."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from app.bootstrap import Container
from app.domain.productivity.weights import ProductivityWeights
from app.models.enums import HeatmapMetric
from app.schemas.common import DateRange
from app.schemas.sleep import SleepInput

pytestmark = pytest.mark.integration


class TestDailySummary:
    def test_an_empty_day_renders_without_raising(self, container: Container, today: date):
        summary = container.analytics.daily_summary(today)
        assert not summary.has_any_data
        assert summary.tasks.total == 0
        assert summary.score.total == 0.0

    def test_the_summary_reflects_what_was_recorded(self, populated: Container, today: date):
        summary = populated.analytics.daily_summary(today)
        assert summary.tasks.completed == 1
        assert summary.tasks.total == 2
        assert summary.habits.due == 1
        assert summary.habits.completed == 1
        assert summary.sleep_minutes == pytest.approx(420.0)
        assert summary.study_minutes == pytest.approx(120.0)
        assert summary.coding_minutes == pytest.approx(90.0)
        assert summary.exercise_minutes == pytest.approx(60.0)

    def test_the_weekday_name_is_right(self, container: Container, today: date):
        assert container.analytics.daily_summary(today).weekday == "Thursday"

    def test_the_score_is_explainable_and_adds_up(self, populated: Container, today: date):
        summary = populated.analytics.daily_summary(today)
        assert summary.score.has_data
        assert sum(item.points for item in summary.score.components) == pytest.approx(
            summary.score.total, abs=0.05
        )

    def test_free_time_is_what_is_left(self, populated: Container, today: date):
        summary = populated.analytics.daily_summary(today)
        assert summary.free_minutes is not None
        assert 0 <= summary.free_minutes <= 24 * 60


class TestDashboard:
    def test_the_whole_payload_assembles(self, populated: Container, today: date):
        view = populated.analytics.dashboard(today)
        assert view.summary.log_date == today
        assert view.habits_today
        assert view.allocation.total_minutes > 0
        assert view.generated_at is not None

    def test_the_timeline_is_chronological(self, populated: Container, today: date):
        view = populated.analytics.dashboard(today)
        times = [item.at for item in view.timeline]
        assert times == sorted(times)

    def test_the_timeline_includes_the_wake_time(self, populated: Container, today: date):
        view = populated.analytics.dashboard(today)
        assert any(item.label == "Woke up" for item in view.timeline)

    def test_an_entry_without_clock_times_is_left_off_the_timeline(
        self, populated: Container, today: date
    ):
        # The fixture logs time by duration only, so nothing but sleep has a clock.
        view = populated.analytics.dashboard(today)
        assert not [item for item in view.timeline if item.kind == "time"]


class TestPeriodsAndReviews:
    def test_the_weekly_review_assembles_on_an_empty_database(
        self, container: Container, today: date
    ):
        review = container.analytics.weekly_review(today)
        assert review.summary.days == 7
        assert review.summary.tasks_total == 0

    def test_the_weekly_review_compares_against_the_previous_week(
        self, populated: Container, today: date
    ):
        review = populated.analytics.weekly_review(today)
        assert review.previous is not None
        assert review.comparisons
        assert review.summary.study_minutes > 0

    def test_habit_performance_never_exceeds_one_hundred_percent(
        self, populated: Container, today: date
    ):
        review = populated.analytics.weekly_review(today)
        for item in review.habit_performance:
            assert 0.0 <= item.completion_rate <= 1.0

    def test_the_monthly_review_assembles(self, populated: Container, today: date):
        review = populated.analytics.monthly_review(today)
        assert review.summary.start == today.replace(day=1)
        assert review.score_series

    def test_period_summary_over_a_week(self, populated: Container, today: date):
        period = DateRange.last_n_days(today, 7)
        summary = populated.analytics.period_summary(period)
        assert summary.days == 7
        assert summary.study_minutes == pytest.approx(7 * 120)
        assert summary.average_sleep_minutes == pytest.approx(420.0)


class TestHeatmap:
    def test_an_empty_heatmap_says_so(self, container: Container):
        heatmap = container.analytics.heatmap(days=30)
        assert not heatmap.has_data

    def test_a_populated_heatmap_covers_the_window(self, populated: Container):
        heatmap = populated.analytics.heatmap(days=30)
        assert heatmap.has_data
        assert len(heatmap.points) == 30
        assert heatmap.max_value > 0

    def test_days_with_no_record_stay_blank(self, populated: Container):
        heatmap = populated.analytics.heatmap(days=60)
        blank = [point for point in heatmap.points if point.value is None]
        assert blank  # the fixture only covers a week

    @pytest.mark.parametrize("metric", list(HeatmapMetric))
    def test_every_metric_produces_a_grid(self, populated: Container, metric: HeatmapMetric):
        heatmap = populated.analytics.heatmap(metric, days=14)
        assert heatmap.metric is metric
        assert len(heatmap.points) == 14


class TestScoring:
    def test_scores_are_cached_on_the_daily_log(self, populated: Container, today: date):
        populated.productivity.score_for_day(today)
        cached = populated.productivity.cached_scores(DateRange(start=today, end=today))
        assert today in cached

    def test_recomputing_a_range_scores_every_day_with_data(
        self, populated: Container, today: date
    ):
        period = DateRange.last_n_days(today, 7)
        assert populated.productivity.recompute_range(period) == 7

    def test_changing_the_weights_changes_the_score(self, populated: Container, today: date):
        before = populated.productivity.score_for_day(today).total
        populated.app_settings.set_weights(
            ProductivityWeights(
                task_completion=0.9,
                habit_completion=0.02,
                sleep=0.02,
                exercise=0.02,
                learning=0.02,
                focus=0.02,
            )
        )
        after = populated.productivity.score_for_day(today).total
        assert before != after

    def test_stored_weights_survive_a_round_trip(self, container: Container):
        weights = ProductivityWeights(
            task_completion=0.3,
            habit_completion=0.3,
            sleep=0.1,
            exercise=0.1,
            learning=0.1,
            focus=0.1,
        )
        container.app_settings.set_weights(weights)
        assert container.app_settings.weights().task_completion == pytest.approx(0.3)

    def test_corrupt_stored_weights_fall_back_to_the_defaults(self, container: Container):
        from app.domain.productivity.weights import SETTINGS_KEY

        container.app_settings.set(SETTINGS_KEY, {"task_completion": "not a number"})
        assert container.app_settings.weights().total == pytest.approx(1.0)

    def test_an_unknown_setting_key_is_refused(self, container: Container):
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            container.app_settings.set("nonsense.key", 1)


class TestInsightsAndCoach:
    def test_insights_run_without_raising_on_an_empty_database(
        self, container: Container, today: date
    ):
        period = DateRange.last_n_days(today, 7)
        assert container.insights.insights(period) == []
        assert container.insights.recommendations(period) == []

    def test_insights_are_produced_from_real_data(self, populated: Container, today: date):
        period = DateRange.last_n_days(today, 7)
        context = populated.insights.build_context(period)
        assert context.habits
        assert context.sleep_avg_current == pytest.approx(420.0)

    def test_the_coach_summarises_an_empty_day_gracefully(self, container: Container, today: date):
        assert "Nothing recorded" in container.coach.generate_daily_summary(today)

    def test_the_coach_summarises_a_real_day(self, populated: Container, today: date):
        summary = populated.coach.generate_daily_summary(today)
        assert "Thursday" in summary
        assert "tasks" in summary

    def test_the_coach_writes_a_weekly_review(self, populated: Container, today: date):
        review = populated.coach.generate_weekly_review(today)
        assert "Week of" in review

    def test_the_coach_satisfies_the_protocol(self, container: Container):
        from app.services.coach import PersonalCoach

        assert isinstance(container.coach, PersonalCoach)


class TestTimezoneBoundaries:
    def test_a_late_night_record_lands_on_the_right_local_day(
        self, container: Container, today: date
    ):
        """23:30 in Kolkata is 18:00 UTC the same day - the local day wins."""
        container.sleep.record(
            SleepInput(log_date=today, sleep_time=time(23, 30), wake_time=time(6, 30))
        )
        record = container.sleep.get_for_date(today)
        assert record is not None
        # Stored in UTC, on the previous UTC day.
        assert record.sleep_at.date() == today - timedelta(days=1)
        # But filed under the local wake date.
        assert record.log_date == today
