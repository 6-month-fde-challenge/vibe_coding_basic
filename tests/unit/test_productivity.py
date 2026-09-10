"""The productivity score and its weights."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.domain.productivity.scoring import DayMetrics, score_day
from app.domain.productivity.weights import ProductivityWeights

FULL = DayMetrics(
    task_rate=1.0,
    habit_rate=1.0,
    sleep_minutes=450,
    sleep_target_minutes=450,
    exercise_minutes=45,
    exercise_target_minutes=45,
    learning_minutes=270,
    learning_target_minutes=270,
    focus_rating=10,
)


class TestWeights:
    def test_the_defaults_sum_to_one(self):
        assert ProductivityWeights().total == pytest.approx(1.0)

    def test_weights_that_do_not_sum_to_one_are_refused(self):
        with pytest.raises(PydanticValidationError):
            ProductivityWeights(
                task_completion=0.5,
                habit_completion=0.5,
                sleep=0.5,
                exercise=0.5,
                learning=0.5,
                focus=0.5,
            )

    def test_a_negative_weight_is_refused(self):
        with pytest.raises(PydanticValidationError):
            ProductivityWeights(task_completion=-0.1)

    def test_rescaling_is_explicit_and_normalises(self):
        weights = ProductivityWeights.rescaled(
            task_completion=2,
            habit_completion=2,
            sleep=1,
            exercise=1,
            learning=1,
            focus=1,
        )
        assert weights.total == pytest.approx(1.0)
        assert weights.task_completion == pytest.approx(0.25)

    def test_rescaling_all_zeroes_is_refused(self):
        with pytest.raises(ValueError, match="greater than zero"):
            ProductivityWeights.rescaled(
                task_completion=0,
                habit_completion=0,
                sleep=0,
                exercise=0,
                learning=0,
                focus=0,
            )

    def test_weights_are_immutable(self):
        weights = ProductivityWeights()
        with pytest.raises(PydanticValidationError):
            weights.sleep = 0.9


class TestScoring:
    def test_a_perfect_day_scores_one_hundred(self):
        assert score_day(FULL, ProductivityWeights()).total == pytest.approx(100.0)

    def test_an_empty_day_scores_zero_without_raising(self):
        result = score_day(DayMetrics(), ProductivityWeights())
        assert result.total == 0.0
        assert not result.has_data
        assert len(result.skipped) == 6

    def test_the_breakdown_adds_up_to_the_total(self):
        result = score_day(
            DayMetrics(
                task_rate=0.5,
                habit_rate=0.75,
                sleep_minutes=400,
                sleep_target_minutes=450,
                focus_rating=8,
            ),
            ProductivityWeights(),
        )
        assert sum(item.points for item in result.components) == pytest.approx(
            result.total, abs=0.05
        )

    def test_missing_components_are_named_not_scored_as_zero(self):
        partial = score_day(DayMetrics(task_rate=1.0, habit_rate=1.0), ProductivityWeights())
        assert partial.total == pytest.approx(100.0)
        assert set(partial.skipped) == {"sleep", "exercise", "learning", "focus"}
        assert partial.coverage == pytest.approx(0.45)

    def test_a_tracked_zero_is_not_the_same_as_untracked(self):
        untracked = score_day(DayMetrics(task_rate=1.0), ProductivityWeights())
        tracked_zero = score_day(
            DayMetrics(task_rate=1.0, exercise_minutes=0.0, exercise_target_minutes=45),
            ProductivityWeights(),
        )
        assert untracked.total > tracked_zero.total

    def test_overshooting_a_target_is_capped(self):
        modest = score_day(
            DayMetrics(sleep_minutes=450, sleep_target_minutes=450), ProductivityWeights()
        )
        excessive = score_day(
            DayMetrics(sleep_minutes=900, sleep_target_minutes=450), ProductivityWeights()
        )
        assert modest.total == excessive.total == pytest.approx(100.0)

    def test_weights_change_the_answer(self):
        metrics = DayMetrics(task_rate=1.0, habit_rate=0.0)
        task_heavy = ProductivityWeights(
            task_completion=0.9,
            habit_completion=0.02,
            sleep=0.02,
            exercise=0.02,
            learning=0.02,
            focus=0.02,
        )
        habit_heavy = ProductivityWeights(
            task_completion=0.02,
            habit_completion=0.9,
            sleep=0.02,
            exercise=0.02,
            learning=0.02,
            focus=0.02,
        )
        assert score_day(metrics, task_heavy).total > score_day(metrics, habit_heavy).total

    def test_a_component_with_a_zero_target_is_skipped(self):
        result = score_day(
            DayMetrics(task_rate=1.0, sleep_minutes=400, sleep_target_minutes=0),
            ProductivityWeights(),
        )
        assert "sleep" in result.skipped

    def test_out_of_range_rates_are_clamped(self):
        result = score_day(DayMetrics(task_rate=5.0), ProductivityWeights())
        assert result.total == pytest.approx(100.0)

    def test_negative_rates_are_clamped_to_zero(self):
        result = score_day(DayMetrics(task_rate=-2.0), ProductivityWeights())
        assert result.total == pytest.approx(0.0)

    def test_the_breakdown_serialises_for_storage(self):
        breakdown = score_day(FULL, ProductivityWeights()).as_breakdown()
        assert len(breakdown) == 6
        assert set(breakdown[0]) == {"key", "label", "weight", "achievement", "points", "detail"}

    def test_components_carry_a_readable_detail(self):
        result = score_day(
            DayMetrics(sleep_minutes=430, sleep_target_minutes=450), ProductivityWeights()
        )
        assert result.components[0].detail == "7h 10m of 7h 30m"
