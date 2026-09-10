"""The sleep record table."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin

if TYPE_CHECKING:
    from app.models.user import UserProfile


class SleepRecord(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """One night's sleep, filed under the date the user woke up.

    Bedtime and wake time are stored as full UTC instants, not as clock
    times. That is what makes "23:30 to 06:30" seven hours instead of minus
    seventeen: the crossing of midnight is already baked into the pair of
    timestamps, so no branch in the code has to notice it.

    ``duration_minutes`` is derived from those two instants but persisted, so
    that a 30-day average is one ``AVG()`` rather than 30 subtractions in
    Python.
    """

    __tablename__ = "sleep_record"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_sleep_record_user_date"),
        Index("ix_sleep_record_user_date", "user_id", "log_date"),
        CheckConstraint("wake_at > sleep_at", name="wake_after_sleep"),
        CheckConstraint(
            "duration_minutes > 0 AND duration_minutes <= 1440", name="duration_plausible"
        ),
        CheckConstraint("quality IS NULL OR quality BETWEEN 1 AND 10", name="quality_range"),
        CheckConstraint("interruptions >= 0", name="interruptions_non_negative"),
    )

    #: The morning the user woke up. One row per user per night.
    log_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    #: When the user got into bed (may precede :attr:`sleep_at`).
    bedtime_at: Mapped[datetime | None] = mapped_column(nullable=True)
    #: When the user actually fell asleep.
    sleep_at: Mapped[datetime] = mapped_column(nullable=False)
    wake_at: Mapped[datetime] = mapped_column(nullable=False)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interruptions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="sleep_records")

    def __repr__(self) -> str:
        """Return a debugging representation naming the night and length."""
        return f"<SleepRecord date={self.log_date} minutes={self.duration_minutes:.0f}>"
