"""The physical-activity table."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin
from app.database.types import str_enum
from app.models.enums import ActivityIntensity

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import UserProfile


class Activity(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """A bout of exercise or sport.

    The *kind* of activity is a :class:`~app.models.category.Category` row of
    kind ``ACTIVITY``, not a column value. Cricket, swimming and "walking the
    dog" are therefore all data, and adding one needs no code change.
    """

    __tablename__ = "activity"
    __table_args__ = (
        Index("ix_activity_user_date", "user_id", "log_date"),
        Index("ix_activity_user_category_date", "user_id", "category_id", "log_date"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at > started_at",
            name="end_after_start",
        ),
        CheckConstraint("calories IS NULL OR calories >= 0", name="calories_non_negative"),
    )

    #: Local date the activity is filed under, so day queries never join to
    #: a timezone conversion.
    log_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("category.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    intensity: Mapped[ActivityIntensity] = mapped_column(
        str_enum(ActivityIntensity), nullable=False, default=ActivityIntensity.MODERATE
    )
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="activities")
    category: Mapped[Category] = relationship(back_populates="activities")

    def __repr__(self) -> str:
        """Return a debugging representation naming date and length."""
        return f"<Activity date={self.log_date} minutes={self.duration_minutes:.0f}>"
