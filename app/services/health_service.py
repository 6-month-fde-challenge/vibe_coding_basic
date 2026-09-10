"""Profile, body measurements and health estimates."""

from __future__ import annotations

from datetime import date
from zoneinfo import available_timezones

from app.core.errors import AppError, ValidationError
from app.core.logging_config import get_logger
from app.domain.health.bmr import age_from_birth_date, calculate_bmr
from app.domain.health.body import WeightPoint, bmi, weight_trend
from app.domain.health.tdee import calculate_tdee
from app.models.enums import BmrFormula
from app.models.user import BodyMeasurement
from app.schemas.common import DateRange
from app.schemas.health import (
    BodyMeasurementInput,
    BodyMeasurementRead,
    HealthSnapshot,
    ProfileRead,
    ProfileUpdate,
    WeightTrendRead,
)
from app.services.base import BaseService

logger = get_logger(__name__)


class HealthService(BaseService):
    """Profile settings, weigh-ins, and the BMR/TDEE estimates.

    Every number this service returns for energy expenditure is an
    estimate, and :class:`HealthSnapshot` carries that note with it rather
    than relying on the page to remember.
    """

    # -- profile -----------------------------------------------------------

    def get_profile(self) -> ProfileRead:
        """Return the user profile."""
        with self.uow() as uow:
            return ProfileRead.model_validate(uow.profiles.get_or_raise(self.user_id))

    def update_profile(self, payload: ProfileUpdate) -> ProfileRead:
        """Apply a partial edit to the profile.

        Raises:
            ValidationError: If the timezone is not a name ``zoneinfo``
                recognises. A bad timezone silently shifts every day
                boundary in the application, so it is caught here.
        """
        changes = payload.model_dump(exclude_unset=True)
        if "timezone" in changes and changes["timezone"] is not None:
            _validate_timezone(changes["timezone"])

        with self.uow() as uow:
            profile = uow.profiles.get_or_raise(self.user_id)
            for field, value in changes.items():
                setattr(profile, field, value)
            uow.commit()
            logger.info("Profile updated: %s", ", ".join(sorted(changes)))
            return ProfileRead.model_validate(profile)

    # -- measurements ------------------------------------------------------

    def record_measurement(self, payload: BodyMeasurementInput) -> BodyMeasurementRead:
        """Save a weigh-in, replacing any already recorded that day."""
        if payload.measured_on > self.today():
            raise ValidationError(
                "Cannot record a measurement in the future",
                field="measured_on",
                value=payload.measured_on.isoformat(),
            )

        with self.uow() as uow:
            saved = uow.measurements.upsert(
                BodyMeasurement(
                    user_id=self.user_id,
                    measured_on=payload.measured_on,
                    weight_kg=payload.weight_kg,
                    body_fat_percent=payload.body_fat_percent,
                    waist_cm=payload.waist_cm,
                    notes=payload.notes,
                )
            )
            uow.commit()
            logger.info("Body measurement recorded for %s", payload.measured_on.isoformat())
            return BodyMeasurementRead.model_validate(saved)

    def latest_measurement(self) -> BodyMeasurementRead | None:
        """Return the most recent weigh-in."""
        with self.uow() as uow:
            row = uow.measurements.latest()
            return BodyMeasurementRead.model_validate(row) if row else None

    def measurements_between(self, period: DateRange) -> list[BodyMeasurementRead]:
        """Return weigh-ins inside a date range."""
        with self.uow() as uow:
            return [
                BodyMeasurementRead.model_validate(row)
                for row in uow.measurements.list_between(period.start, period.end)
            ]

    def delete_measurement(self, measurement_id: int) -> None:
        """Remove one weigh-in."""
        with self.uow() as uow:
            row = uow.measurements.get_or_raise(measurement_id)
            uow.measurements.delete(row)
            uow.commit()

    def weight_trend(self, period: DateRange) -> WeightTrendRead:
        """Summarise weight movement across a range."""
        with self.uow() as uow:
            rows = uow.measurements.list_between(period.start, period.end)
        trend = weight_trend(
            [
                WeightPoint(
                    measured_on=row.measured_on,
                    weight_kg=row.weight_kg,
                    body_fat_percent=row.body_fat_percent,
                )
                for row in rows
            ]
        )
        return WeightTrendRead(
            points=trend.points,
            first_kg=trend.first.weight_kg if trend.first else None,
            latest_kg=trend.latest.weight_kg if trend.latest else None,
            change_kg=trend.change_kg,
            change_per_week_kg=trend.change_per_week_kg,
        )

    # -- estimates ---------------------------------------------------------

    def snapshot(self, on: date | None = None) -> HealthSnapshot:
        """Return the current BMR/TDEE estimate, or say why there is none.

        A missing height or weight is not an error - it is a profile that
        has not been filled in yet. The snapshot reports the gap in
        ``unavailable_reason`` so the page can ask for exactly the missing
        field instead of showing a zero.
        """
        target = on or self.today()
        with self.uow() as uow:
            profile = uow.profiles.get_or_raise(self.user_id)
            measurement = uow.measurements.latest()

            formula = profile.bmr_formula
            height = profile.height_cm
            age = (
                age_from_birth_date(profile.birth_date, target)
                if profile.birth_date is not None
                else None
            )
            weight = measurement.weight_kg if measurement else None
            body_fat = measurement.body_fat_percent if measurement else None
            activity_level = profile.activity_level

        body_mass_index = bmi(weight, height) if weight and height else None

        if weight is None:
            return HealthSnapshot(
                weight_kg=None,
                height_cm=height,
                age_years=age,
                bmi=None,
                bmr_kcal=None,
                tdee_kcal=None,
                formula=formula,
                activity_level=activity_level,
                unavailable_reason="Record a weight in Health Metrics to see an estimate.",
            )

        try:
            estimate = calculate_bmr(
                formula=formula,
                weight_kg=weight,
                height_cm=height,
                age_years=age,
                sex=profile.sex,
                body_fat_percent=body_fat,
            )
        except AppError as error:
            logger.info("BMR estimate unavailable: %s", error)
            return HealthSnapshot(
                weight_kg=weight,
                height_cm=height,
                age_years=age,
                bmi=body_mass_index,
                bmr_kcal=None,
                tdee_kcal=None,
                formula=formula,
                activity_level=activity_level,
                unavailable_reason=error.user_message(),
            )

        tdee = calculate_tdee(estimate, activity_level)
        return HealthSnapshot(
            weight_kg=weight,
            height_cm=height,
            age_years=age,
            bmi=body_mass_index,
            bmr_kcal=estimate.rounded(),
            tdee_kcal=tdee.rounded(),
            formula=formula,
            activity_level=activity_level,
        )

    def compare_formulas(self, on: date | None = None) -> dict[BmrFormula, int | None]:
        """Return every formula's estimate, so the spread is visible.

        Showing three numbers that disagree by a few hundred kilocalories is
        the most honest presentation of what a BMR estimate is worth.
        """
        target = on or self.today()
        with self.uow() as uow:
            profile = uow.profiles.get_or_raise(self.user_id)
            measurement = uow.measurements.latest()

        if measurement is None:
            return dict.fromkeys(BmrFormula)

        age = (
            age_from_birth_date(profile.birth_date, target)
            if profile.birth_date is not None
            else None
        )
        results: dict[BmrFormula, int | None] = {}
        for formula in BmrFormula:
            try:
                results[formula] = calculate_bmr(
                    formula=formula,
                    weight_kg=measurement.weight_kg,
                    height_cm=profile.height_cm,
                    age_years=age,
                    sex=profile.sex,
                    body_fat_percent=measurement.body_fat_percent,
                ).rounded()
            except AppError:
                results[formula] = None
        return results


def _validate_timezone(name: str) -> None:
    """Reject a timezone name ``zoneinfo`` cannot resolve.

    Raises:
        ValidationError: If the name is unknown.
    """
    if name not in available_timezones():
        raise ValidationError(
            "Unknown timezone",
            field="timezone",
            value=name,
            user_hint=f"{name!r} is not an IANA timezone name. Try 'Asia/Kolkata' or 'UTC'.",
        )


__all__ = ["HealthService"]
