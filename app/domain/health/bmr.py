"""Basal metabolic rate.

Every number this module produces is an **estimate** from a published
population equation. It is not a measurement, it is not medical advice, and
the UI is required to say so wherever a figure from here is displayed. That
is why :class:`BmrResult` carries the formula and the inputs with it: a bare
float would lose the caveat on its first hop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.errors import ValidationError
from app.models.enums import BmrFormula, Sex

#: Plausible input ranges. Outside these the equations stop meaning anything,
#: so the app refuses rather than printing a confident nonsense number.
MIN_WEIGHT_KG = 20.0
MAX_WEIGHT_KG = 500.0
MIN_HEIGHT_CM = 50.0
MAX_HEIGHT_CM = 280.0
MIN_AGE_YEARS = 10
MAX_AGE_YEARS = 120
MIN_BODY_FAT_PERCENT = 3.0
MAX_BODY_FAT_PERCENT = 70.0


@dataclass(frozen=True, slots=True)
class BmrResult:
    """A BMR estimate together with everything needed to explain it.

    Attributes:
        kcal_per_day: The estimate, in kilocalories per day.
        formula: Which published equation produced it.
        inputs: The values fed in, for display and for audit.
        note: The standing caveat, carried with the number by design.
    """

    kcal_per_day: float
    formula: BmrFormula
    inputs: dict[str, float | str] = field(default_factory=dict)
    note: str = "Estimate from a population equation, not a medical measurement."

    def rounded(self) -> int:
        """Return the estimate rounded to whole kilocalories."""
        return round(self.kcal_per_day)


def age_from_birth_date(birth_date: date, on: date) -> int:
    """Return a whole-year age.

    Args:
        birth_date: Date of birth.
        on: The date to compute the age at.

    Returns:
        Completed years of age.

    Raises:
        ValidationError: If ``birth_date`` is after ``on``.
    """
    if birth_date > on:
        raise ValidationError(
            "Birth date is in the future",
            field="birth_date",
            value=birth_date.isoformat(),
        )
    had_birthday = (on.month, on.day) >= (birth_date.month, birth_date.day)
    return on.year - birth_date.year - (0 if had_birthday else 1)


def _validate(weight_kg: float, height_cm: float, age_years: int) -> None:
    """Reject inputs outside the range the equations are defined over."""
    if not MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG:
        raise ValidationError(
            f"Weight must be between {MIN_WEIGHT_KG:.0f} and {MAX_WEIGHT_KG:.0f} kg",
            field="weight_kg",
            value=weight_kg,
        )
    if not MIN_HEIGHT_CM <= height_cm <= MAX_HEIGHT_CM:
        raise ValidationError(
            f"Height must be between {MIN_HEIGHT_CM:.0f} and {MAX_HEIGHT_CM:.0f} cm",
            field="height_cm",
            value=height_cm,
        )
    if not MIN_AGE_YEARS <= age_years <= MAX_AGE_YEARS:
        raise ValidationError(
            f"Age must be between {MIN_AGE_YEARS} and {MAX_AGE_YEARS} years",
            field="age_years",
            value=age_years,
        )


def _require_known_sex(sex: Sex) -> Sex:
    """Reject ``UNSPECIFIED``, which the two-constant equations cannot use."""
    if sex is Sex.UNSPECIFIED:
        raise ValidationError(
            "This formula needs a sex of MALE or FEMALE",
            field="sex",
            value=sex.value,
            user_hint=(
                "Mifflin-St Jeor and Harris-Benedict are defined with a separate "
                "constant per sex. Set one in your profile, or switch to the "
                "Katch-McArdle formula, which uses body fat instead."
            ),
        )
    return sex


def mifflin_st_jeor(weight_kg: float, height_cm: float, age_years: int, sex: Sex) -> float:
    """Return the Mifflin-St Jeor BMR estimate in kcal/day.

    ``10W + 6.25H - 5A + 5`` for men and ``... - 161`` for women, with W in
    kilograms, H in centimetres and A in years.
    """
    _validate(weight_kg, height_cm, age_years)
    _require_known_sex(sex)
    base = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * age_years)
    return base + (5.0 if sex is Sex.MALE else -161.0)


def harris_benedict(weight_kg: float, height_cm: float, age_years: int, sex: Sex) -> float:
    """Return the revised (Roza-Shizgal) Harris-Benedict estimate in kcal/day."""
    _validate(weight_kg, height_cm, age_years)
    _require_known_sex(sex)
    if sex is Sex.MALE:
        return 88.362 + (13.397 * weight_kg) + (4.799 * height_cm) - (5.677 * age_years)
    return 447.593 + (9.247 * weight_kg) + (3.098 * height_cm) - (4.330 * age_years)


def katch_mcardle(weight_kg: float, body_fat_percent: float) -> float:
    """Return the Katch-McArdle estimate in kcal/day.

    ``370 + 21.6 * lean body mass``. Needs a body-fat percentage, and in
    exchange is the only one of the three that does not need a sex.
    """
    if not MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG:
        raise ValidationError(
            f"Weight must be between {MIN_WEIGHT_KG:.0f} and {MAX_WEIGHT_KG:.0f} kg",
            field="weight_kg",
            value=weight_kg,
        )
    if not MIN_BODY_FAT_PERCENT <= body_fat_percent <= MAX_BODY_FAT_PERCENT:
        raise ValidationError(
            f"Body fat must be between {MIN_BODY_FAT_PERCENT:.0f}% and {MAX_BODY_FAT_PERCENT:.0f}%",
            field="body_fat_percent",
            value=body_fat_percent,
        )
    lean_mass = weight_kg * (1.0 - body_fat_percent / 100.0)
    return 370.0 + (21.6 * lean_mass)


def calculate_bmr(
    *,
    formula: BmrFormula,
    weight_kg: float,
    height_cm: float | None = None,
    age_years: int | None = None,
    sex: Sex = Sex.UNSPECIFIED,
    body_fat_percent: float | None = None,
) -> BmrResult:
    """Dispatch to the requested formula and wrap the answer.

    Keyword-only on purpose: five positional numbers in a row is exactly the
    call that gets height and weight the wrong way round.

    Args:
        formula: Which equation to use.
        weight_kg: Body mass in kilograms.
        height_cm: Height in centimetres. Required except for Katch-McArdle.
        age_years: Age in whole years. Required except for Katch-McArdle.
        sex: Required by Mifflin-St Jeor and Harris-Benedict.
        body_fat_percent: Required by Katch-McArdle.

    Returns:
        The estimate, the formula used and the inputs.

    Raises:
        ValidationError: If a required input is missing or out of range.
    """
    if formula is BmrFormula.KATCH_MCARDLE:
        if body_fat_percent is None:
            raise ValidationError(
                "Katch-McArdle needs a body fat percentage",
                field="body_fat_percent",
                user_hint="Add a body-fat figure to your latest measurement, "
                "or choose a different formula.",
            )
        value = katch_mcardle(weight_kg, body_fat_percent)
        return BmrResult(
            kcal_per_day=value,
            formula=formula,
            inputs={"weight_kg": weight_kg, "body_fat_percent": body_fat_percent},
        )

    if height_cm is None or age_years is None:
        missing = "height" if height_cm is None else "age"
        raise ValidationError(
            f"{formula.value} needs a {missing}",
            field=f"{missing}_cm" if missing == "height" else "age_years",
            user_hint=f"Add your {missing} in Settings to see a BMR estimate.",
        )

    calculator = mifflin_st_jeor if formula is BmrFormula.MIFFLIN_ST_JEOR else harris_benedict
    value = calculator(weight_kg, height_cm, age_years, sex)
    return BmrResult(
        kcal_per_day=value,
        formula=formula,
        inputs={
            "weight_kg": weight_kg,
            "height_cm": height_cm,
            "age_years": age_years,
            "sex": sex.value,
        },
    )
