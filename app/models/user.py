"""Profile, body measurements and the key/value settings table."""

from __future__ import annotations

from datetime import date as date_type
from datetime import time as time_type
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, Float, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin
from app.database.types import JSONColumn, str_enum
from app.models.enums import ActivityLevel, BmrFormula, Sex

if TYPE_CHECKING:
    from app.models.activity import Activity
    from app.models.category import Category
    from app.models.goal import Goal, WeeklyGoal
    from app.models.habit import Habit
    from app.models.journal import DailyLog, JournalEntry
    from app.models.sleep import SleepRecord
    from app.models.task import Task
    from app.models.time_entry import TimeEntry


class UserProfile(IdMixin, TimestampMixin, Base):
    """The person the tracker is tracking.

    One row today. Every other table already carries ``user_id``, so a second
    profile is an insert rather than a migration of the whole schema.
    """

    __tablename__ = "user_profile"
    __table_args__ = (
        CheckConstraint("height_cm IS NULL OR height_cm BETWEEN 50 AND 280", name="height_range"),
        CheckConstraint("week_start BETWEEN 0 AND 6", name="week_start_range"),
    )

    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Me")
    birth_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    sex: Mapped[Sex] = mapped_column(str_enum(Sex), nullable=False, default=Sex.UNSPECIFIED)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_level: Mapped[ActivityLevel] = mapped_column(
        str_enum(ActivityLevel), nullable=False, default=ActivityLevel.MODERATELY_ACTIVE
    )
    bmr_formula: Mapped[BmrFormula] = mapped_column(
        str_enum(BmrFormula), nullable=False, default=BmrFormula.MIFFLIN_ST_JEOR
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    #: 0 = Monday, matching ``datetime.date.weekday``.
    week_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- daily targets, used by the dashboard and the scoring engine -------
    target_sleep_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=450)
    target_study_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    target_coding_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    target_teaching_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    target_exercise_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    target_bedtime: Mapped[time_type | None] = mapped_column(Time, nullable=True)
    target_wake_time: Mapped[time_type | None] = mapped_column(Time, nullable=True)

    measurements: Mapped[list[BodyMeasurement]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    categories: Mapped[list[Category]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    habits: Mapped[list[Habit]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    sleep_records: Mapped[list[SleepRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    time_entries: Mapped[list[TimeEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    goals: Mapped[list[Goal]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    weekly_goals: Mapped[list[WeeklyGoal]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    journal_entries: Mapped[list[JournalEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    daily_logs: Mapped[list[DailyLog]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class BodyMeasurement(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """A weigh-in, kept as history so trends and Katch-McArdle both work."""

    __tablename__ = "body_measurement"
    __table_args__ = (
        UniqueConstraint("user_id", "measured_on", name="uq_body_measurement_user_date"),
        CheckConstraint("weight_kg > 0 AND weight_kg < 500", name="weight_range"),
        CheckConstraint(
            "body_fat_percent IS NULL OR body_fat_percent BETWEEN 1 AND 70",
            name="body_fat_range",
        ),
    )

    measured_on: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    body_fat_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    waist_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="measurements")


class AppSetting(IdMixin, TimestampMixin, Base):
    """Key/value store for configuration a user can change at runtime.

    Productivity weights, the chosen theme and unit preferences live here.
    Anything the *code* needs before the database exists lives in ``.env``
    instead - see :mod:`app.config.settings`.
    """

    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_app_settings_key"),)

    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value: Mapped[Any] = mapped_column(JSONColumn, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
