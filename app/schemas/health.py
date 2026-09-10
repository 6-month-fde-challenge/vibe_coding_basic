"""Profile, body-measurement and health-estimate schemas."""

from __future__ import annotations

from datetime import date, time

from pydantic import Field

from app.models.enums import ActivityLevel, BmrFormula, Sex
from app.schemas.common import ReadSchema, Schema


class ProfileUpdate(Schema):
    """Editable fields of the user profile."""

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    birth_date: date | None = None
    sex: Sex | None = None
    height_cm: float | None = Field(default=None, ge=50, le=280)
    activity_level: ActivityLevel | None = None
    bmr_formula: BmrFormula | None = None
    timezone: str | None = Field(default=None, max_length=64)
    week_start: int | None = Field(default=None, ge=0, le=6)
    target_sleep_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    target_study_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    target_coding_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    target_teaching_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    target_exercise_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    target_bedtime: time | None = None
    target_wake_time: time | None = None


class ProfileRead(ReadSchema):
    """The user profile."""

    id: int
    display_name: str
    birth_date: date | None
    sex: Sex
    height_cm: float | None
    activity_level: ActivityLevel
    bmr_formula: BmrFormula
    timezone: str
    week_start: int
    target_sleep_minutes: int
    target_study_minutes: int
    target_coding_minutes: int
    target_teaching_minutes: int
    target_exercise_minutes: int
    target_bedtime: time | None
    target_wake_time: time | None

    @property
    def learning_target_minutes(self) -> int:
        """Combined daily target for study, coding and teaching."""
        return self.target_study_minutes + self.target_coding_minutes + self.target_teaching_minutes


class BodyMeasurementInput(Schema):
    """A weigh-in."""

    measured_on: date
    weight_kg: float = Field(gt=0, lt=500)
    body_fat_percent: float | None = Field(default=None, ge=1, le=70)
    waist_cm: float | None = Field(default=None, ge=30, le=250)
    notes: str | None = Field(default=None, max_length=1000)


class BodyMeasurementRead(ReadSchema):
    """A stored weigh-in."""

    id: int
    measured_on: date
    weight_kg: float
    body_fat_percent: float | None
    waist_cm: float | None
    notes: str | None


class HealthSnapshot(ReadSchema):
    """Current health estimates, with the caveats attached.

    ``bmr_kcal`` and ``tdee_kcal`` are ``None`` when the profile is missing
    an input they need. The UI shows what is missing rather than a zero.
    """

    weight_kg: float | None
    height_cm: float | None
    age_years: int | None
    bmi: float | None
    bmr_kcal: int | None
    tdee_kcal: int | None
    formula: BmrFormula
    activity_level: ActivityLevel
    unavailable_reason: str | None = None
    note: str = "BMR and TDEE are estimates from population equations, not measurements."

    @property
    def is_available(self) -> bool:
        """Whether an estimate could be produced."""
        return self.bmr_kcal is not None


class WeightTrendRead(ReadSchema):
    """Movement in body mass over a window."""

    points: int
    first_kg: float | None
    latest_kg: float | None
    change_kg: float | None
    change_per_week_kg: float | None
