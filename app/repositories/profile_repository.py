"""Persistence for the profile, body measurements and app settings."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from app.models.user import AppSetting, BodyMeasurement, UserProfile
from app.repositories.base import BaseRepository, UserScopedRepository


class ProfileRepository(BaseRepository[UserProfile]):
    """The profile table.

    Not user-scoped, for the obvious reason that it is what defines a user.
    """

    model = UserProfile

    def first(self) -> UserProfile | None:
        """Return the single profile, or ``None`` on a fresh database."""
        return self.session.scalars(select(UserProfile).order_by(UserProfile.id).limit(1)).first()

    def get_by_name(self, display_name: str) -> UserProfile | None:
        """Return a profile by display name."""
        statement = select(UserProfile).where(UserProfile.display_name == display_name)
        return self.session.scalars(statement).first()


class BodyMeasurementRepository(UserScopedRepository[BodyMeasurement]):
    """Weigh-in history."""

    model = BodyMeasurement

    def latest(self) -> BodyMeasurement | None:
        """Return the most recent measurement.

        Ordered on the indexed ``measured_on`` column and limited to one, so
        this is an index seek rather than a sort of the whole history.
        """
        statement = self.scoped().order_by(BodyMeasurement.measured_on.desc()).limit(1)
        return self.session.scalars(statement).first()

    def get_for_date(self, measured_on: date) -> BodyMeasurement | None:
        """Return the measurement recorded on a given date."""
        statement = self.scoped().where(BodyMeasurement.measured_on == measured_on)
        return self.session.scalars(statement).first()

    def list_between(self, start: date, end: date) -> list[BodyMeasurement]:
        """Return measurements inside an inclusive date range, oldest first."""
        statement = (
            self.scoped()
            .where(BodyMeasurement.measured_on >= start, BodyMeasurement.measured_on <= end)
            .order_by(BodyMeasurement.measured_on)
        )
        return list(self.session.scalars(statement))

    def upsert(self, measurement: BodyMeasurement) -> BodyMeasurement:
        """Insert a measurement, or update the one already on that date.

        One weigh-in per day is the rule the unique constraint enforces;
        this method is what stops the UI having to catch an integrity error
        every time somebody corrects a typo.
        """
        existing = self.get_for_date(measurement.measured_on)
        if existing is None:
            return self.add(measurement)

        existing.weight_kg = measurement.weight_kg
        existing.body_fat_percent = measurement.body_fat_percent
        existing.waist_cm = measurement.waist_cm
        existing.notes = measurement.notes
        self.flush()
        return existing


class SettingsRepository(BaseRepository[AppSetting]):
    """The key/value settings table."""

    model = AppSetting

    def get_value(self, key: str) -> Any | None:
        """Return a stored value, or ``None`` if the key is unset."""
        statement = select(AppSetting).where(AppSetting.key == key)
        row = self.session.scalars(statement).first()
        return row.value if row else None

    def set_value(self, key: str, value: Any, description: str | None = None) -> AppSetting:
        """Insert or update one setting."""
        statement = select(AppSetting).where(AppSetting.key == key)
        row = self.session.scalars(statement).first()
        if row is None:
            row = AppSetting(key=key, value=value, description=description)
            return self.add(row)

        row.value = value
        if description is not None:
            row.description = description
        self.flush()
        return row

    def delete_key(self, key: str) -> bool:
        """Remove one setting. Returns whether anything was deleted."""
        statement = select(AppSetting).where(AppSetting.key == key)
        row = self.session.scalars(statement).first()
        if row is None:
            return False
        self.delete(row)
        return True

    def all_values(self) -> dict[str, Any]:
        """Return every setting as a plain dictionary."""
        return {row.key: row.value for row in self.session.scalars(select(AppSetting))}


__all__ = [
    "BodyMeasurementRepository",
    "ProfileRepository",
    "SettingsRepository",
]
