"""Body-composition arithmetic over a series of measurements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.core.errors import ValidationError


@dataclass(frozen=True, slots=True)
class WeightPoint:
    """One weigh-in, as the domain layer sees it."""

    measured_on: date
    weight_kg: float
    body_fat_percent: float | None = None


@dataclass(frozen=True, slots=True)
class WeightTrend:
    """Movement in body mass across a window of measurements."""

    first: WeightPoint | None
    latest: WeightPoint | None
    change_kg: float | None
    change_per_week_kg: float | None
    points: int

    @property
    def has_data(self) -> bool:
        """Whether there was anything to measure."""
        return self.points > 0


def bmi(weight_kg: float, height_cm: float) -> float:
    """Return body mass index.

    Presented alongside a note that BMI ignores body composition entirely,
    which is why the app never colour-codes it.

    Raises:
        ValidationError: If height or weight is not positive.
    """
    if height_cm <= 0:
        raise ValidationError("Height must be positive", field="height_cm", value=height_cm)
    if weight_kg <= 0:
        raise ValidationError("Weight must be positive", field="weight_kg", value=weight_kg)
    height_m = height_cm / 100.0
    return weight_kg / (height_m * height_m)


def weight_trend(points: Sequence[WeightPoint]) -> WeightTrend:
    """Summarise a series of weigh-ins.

    Args:
        points: Measurements in any order; sorted internally.

    Returns:
        First and latest points, the absolute change, and the change
        normalised to kilograms per week so that windows of different
        lengths can be compared.
    """
    if not points:
        return WeightTrend(
            first=None, latest=None, change_kg=None, change_per_week_kg=None, points=0
        )

    ordered = sorted(points, key=lambda point: point.measured_on)
    first, latest = ordered[0], ordered[-1]
    change = latest.weight_kg - first.weight_kg

    span_days = (latest.measured_on - first.measured_on).days
    per_week = (change / span_days) * 7.0 if span_days > 0 else None

    return WeightTrend(
        first=first,
        latest=latest,
        change_kg=change,
        change_per_week_kg=per_week,
        points=len(ordered),
    )
