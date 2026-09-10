"""Health calculations: BMR, TDEE and body composition.

Everything in here is an estimate produced by a published equation. None of
it is medical advice, and the note travels with the number rather than being
left to the caller to remember.
"""

from app.domain.health.bmr import (
    BmrResult,
    age_from_birth_date,
    calculate_bmr,
    harris_benedict,
    katch_mcardle,
    mifflin_st_jeor,
)
from app.domain.health.body import WeightPoint, WeightTrend, bmi, weight_trend
from app.domain.health.tdee import TdeeResult, calculate_tdee, estimate_activity_calories

__all__ = [
    "BmrResult",
    "TdeeResult",
    "WeightPoint",
    "WeightTrend",
    "age_from_birth_date",
    "bmi",
    "calculate_bmr",
    "calculate_tdee",
    "estimate_activity_calories",
    "harris_benedict",
    "katch_mcardle",
    "mifflin_st_jeor",
    "weight_trend",
]
