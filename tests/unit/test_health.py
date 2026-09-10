"""BMR, TDEE and body-composition arithmetic."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import ValidationError
from app.domain.health.bmr import (
    MAX_AGE_YEARS,
    MAX_WEIGHT_KG,
    MIN_WEIGHT_KG,
    age_from_birth_date,
    calculate_bmr,
    harris_benedict,
    katch_mcardle,
    mifflin_st_jeor,
)
from app.domain.health.body import WeightPoint, bmi, weight_trend
from app.domain.health.tdee import calculate_tdee, estimate_activity_calories
from app.models.enums import ActivityIntensity, ActivityLevel, BmrFormula, Sex, members


class TestMifflinStJeor:
    def test_male_matches_the_published_formula(self):
        # 10(70) + 6.25(175) - 5(25) + 5
        assert mifflin_st_jeor(70, 175, 25, Sex.MALE) == pytest.approx(1673.75)

    def test_female_matches_the_published_formula(self):
        # 10(60) + 6.25(165) - 5(30) - 161
        assert mifflin_st_jeor(60, 165, 30, Sex.FEMALE) == pytest.approx(1320.25)

    def test_the_two_sexes_differ_by_the_constant(self):
        male = mifflin_st_jeor(70, 175, 25, Sex.MALE)
        female = mifflin_st_jeor(70, 175, 25, Sex.FEMALE)
        assert male - female == pytest.approx(166.0)

    def test_unspecified_sex_is_refused_with_an_explanation(self):
        with pytest.raises(ValidationError) as caught:
            mifflin_st_jeor(70, 175, 25, Sex.UNSPECIFIED)
        assert "Katch-McArdle" in caught.value.user_message()

    @pytest.mark.parametrize(
        ("weight", "height", "age"),
        [
            (MIN_WEIGHT_KG - 0.1, 175, 25),
            (MAX_WEIGHT_KG + 1, 175, 25),
            (70, 49, 25),
            (70, 281, 25),
            (70, 175, 9),
            (70, 175, MAX_AGE_YEARS + 1),
            (0, 175, 25),
            (-70, 175, 25),
        ],
    )
    def test_out_of_range_inputs_are_refused(self, weight, height, age):
        with pytest.raises(ValidationError):
            mifflin_st_jeor(weight, height, age, Sex.MALE)

    @pytest.mark.parametrize(
        ("weight", "height", "age"),
        [(MIN_WEIGHT_KG, 50.0, 10), (MAX_WEIGHT_KG, 280.0, MAX_AGE_YEARS)],
    )
    def test_the_boundaries_themselves_are_accepted(self, weight, height, age):
        assert mifflin_st_jeor(weight, height, age, Sex.MALE) > 0


class TestOtherFormulas:
    def test_harris_benedict_is_close_to_but_not_equal_to_mifflin(self):
        mifflin = mifflin_st_jeor(70, 175, 25, Sex.MALE)
        harris = harris_benedict(70, 175, 25, Sex.MALE)
        assert harris != mifflin
        assert abs(harris - mifflin) < 250

    def test_katch_mcardle_uses_lean_mass_only(self):
        leaner = katch_mcardle(70, 10)
        fatter = katch_mcardle(70, 30)
        assert leaner > fatter

    def test_katch_mcardle_rejects_an_impossible_body_fat(self):
        with pytest.raises(ValidationError):
            katch_mcardle(70, 95)

    def test_katch_mcardle_needs_no_sex(self):
        result = calculate_bmr(formula=BmrFormula.KATCH_MCARDLE, weight_kg=70, body_fat_percent=18)
        assert result.rounded() > 0


class TestCalculateBmr:
    def test_result_carries_its_inputs_and_caveat(self):
        result = calculate_bmr(
            formula=BmrFormula.MIFFLIN_ST_JEOR,
            weight_kg=70,
            height_cm=175,
            age_years=25,
            sex=Sex.MALE,
        )
        assert result.formula is BmrFormula.MIFFLIN_ST_JEOR
        assert result.inputs["weight_kg"] == 70
        assert "not a medical measurement" in result.note

    def test_missing_height_names_the_missing_field(self):
        with pytest.raises(ValidationError) as caught:
            calculate_bmr(
                formula=BmrFormula.MIFFLIN_ST_JEOR, weight_kg=70, age_years=25, sex=Sex.MALE
            )
        assert "height" in caught.value.user_message().lower()

    def test_katch_mcardle_without_body_fat_is_refused(self):
        with pytest.raises(ValidationError):
            calculate_bmr(formula=BmrFormula.KATCH_MCARDLE, weight_kg=70)


class TestAge:
    def test_before_the_birthday_the_year_has_not_ticked_over(self):
        assert age_from_birth_date(date(2000, 12, 31), date(2026, 9, 10)) == 25

    def test_on_the_birthday_it_has(self):
        assert age_from_birth_date(date(2000, 9, 10), date(2026, 9, 10)) == 26

    def test_leap_day_birthday_in_a_common_year(self):
        assert age_from_birth_date(date(2000, 2, 29), date(2026, 2, 28)) == 25

    def test_a_future_birth_date_is_refused(self):
        with pytest.raises(ValidationError):
            age_from_birth_date(date(2027, 1, 1), date(2026, 9, 10))


class TestTdee:
    def test_multiplier_comes_from_the_activity_level(self):
        bmr = calculate_bmr(
            formula=BmrFormula.MIFFLIN_ST_JEOR,
            weight_kg=70,
            height_cm=175,
            age_years=25,
            sex=Sex.MALE,
        )
        result = calculate_tdee(bmr, ActivityLevel.SEDENTARY)
        assert result.kcal_per_day == pytest.approx(bmr.kcal_per_day * 1.2)

    def test_more_activity_means_more_energy(self):
        bmr = calculate_bmr(
            formula=BmrFormula.MIFFLIN_ST_JEOR,
            weight_kg=70,
            height_cm=175,
            age_years=25,
            sex=Sex.MALE,
        )
        levels = members(ActivityLevel)
        values = [calculate_tdee(bmr, level).kcal_per_day for level in levels]
        assert values == sorted(values)

    def test_activity_calories_scale_with_intensity(self):
        low = estimate_activity_calories(
            weight_kg=70, duration_minutes=60, intensity=ActivityIntensity.LOW
        )
        high = estimate_activity_calories(
            weight_kg=70, duration_minutes=60, intensity=ActivityIntensity.HIGH
        )
        assert high > low

    def test_zero_duration_is_refused(self):
        with pytest.raises(ValidationError):
            estimate_activity_calories(
                weight_kg=70, duration_minutes=0, intensity=ActivityIntensity.LOW
            )


class TestBody:
    def test_bmi_matches_the_definition(self):
        assert bmi(70, 175) == pytest.approx(70 / 1.75**2)

    def test_bmi_refuses_a_zero_height(self):
        with pytest.raises(ValidationError):
            bmi(70, 0)

    def test_weight_trend_on_an_empty_series(self):
        trend = weight_trend([])
        assert not trend.has_data
        assert trend.change_kg is None

    def test_weight_trend_normalises_to_a_weekly_rate(self):
        trend = weight_trend(
            [
                WeightPoint(date(2026, 9, 1), 72.0),
                WeightPoint(date(2026, 9, 15), 70.6),
            ]
        )
        assert trend.change_kg == pytest.approx(-1.4)
        assert trend.change_per_week_kg == pytest.approx(-0.7)

    def test_a_single_point_has_no_rate(self):
        trend = weight_trend([WeightPoint(date(2026, 9, 1), 72.0)])
        assert trend.change_kg == 0
        assert trend.change_per_week_kg is None

    def test_points_are_sorted_before_measuring(self):
        forwards = weight_trend(
            [WeightPoint(date(2026, 9, 1), 72.0), WeightPoint(date(2026, 9, 8), 71.0)]
        )
        backwards = weight_trend(
            [WeightPoint(date(2026, 9, 8), 71.0), WeightPoint(date(2026, 9, 1), 72.0)]
        )
        assert forwards.change_kg == backwards.change_kg
