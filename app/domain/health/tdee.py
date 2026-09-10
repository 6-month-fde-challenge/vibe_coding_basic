"""Total daily energy expenditure, and the optional calorie estimate."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ValidationError
from app.domain.health.bmr import BmrResult
from app.models.enums import ActivityIntensity, ActivityLevel

#: kcal burned per kg of body mass per hour, per MET. The standard constant.
_KCAL_PER_KG_PER_MET_HOUR = 1.05


@dataclass(frozen=True, slots=True)
class TdeeResult:
    """A TDEE estimate and the parts it was built from."""

    kcal_per_day: float
    bmr: BmrResult
    activity_level: ActivityLevel
    multiplier: float
    note: str = "Estimate. Real expenditure varies day to day by hundreds of kcal."

    def rounded(self) -> int:
        """Return the estimate rounded to whole kilocalories."""
        return round(self.kcal_per_day)


def calculate_tdee(bmr: BmrResult, activity_level: ActivityLevel) -> TdeeResult:
    """Scale a BMR estimate by the activity multiplier.

    Args:
        bmr: The basal estimate to scale.
        activity_level: Lifestyle activity level.

    Returns:
        The scaled estimate, carrying its inputs.
    """
    multiplier = activity_level.multiplier
    return TdeeResult(
        kcal_per_day=bmr.kcal_per_day * multiplier,
        bmr=bmr,
        activity_level=activity_level,
        multiplier=multiplier,
    )


def estimate_activity_calories(
    *,
    weight_kg: float,
    duration_minutes: float,
    intensity: ActivityIntensity,
) -> float:
    """Estimate the calories burned by one bout of activity.

    Uses the MET model: ``kcal = MET * 1.05 * weight_kg * hours``. Offered
    only as a default the user can overwrite - a wrist tracker's number, or
    none at all, is better than this one.

    Args:
        weight_kg: Body mass in kilograms.
        duration_minutes: How long the activity lasted.
        intensity: Perceived effort, mapped to a coarse MET value.

    Returns:
        Estimated kilocalories.

    Raises:
        ValidationError: If the duration or weight is not positive.
    """
    if duration_minutes <= 0:
        raise ValidationError(
            "Duration must be positive", field="duration_minutes", value=duration_minutes
        )
    if weight_kg <= 0:
        raise ValidationError("Weight must be positive", field="weight_kg", value=weight_kg)
    hours = duration_minutes / 60.0
    return intensity.met_estimate * _KCAL_PER_KG_PER_MET_HOUR * weight_kg * hours
