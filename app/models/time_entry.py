"""The time-tracking table."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import UserProfile


class TimeEntry(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """A block of time spent on one category.

    ``started_at`` may be null: the Quick Add screen lets the user record
    "two hours of study today" without pretending to know when it happened.
    Overlap checking only applies to entries that do carry a real interval.
    """

    __tablename__ = "time_entry"
    __table_args__ = (
        Index("ix_time_entry_user_date", "user_id", "log_date"),
        Index("ix_time_entry_user_category_date", "user_id", "category_id", "log_date"),
        Index("ix_time_entry_user_started", "user_id", "started_at"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at > started_at",
            name="end_after_start",
        ),
    )

    log_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("category.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="time_entries")
    category: Mapped[Category] = relationship(back_populates="time_entries")

    @property
    def has_interval(self) -> bool:
        """Whether both endpoints are known, making overlap checks meaningful."""
        return self.started_at is not None and self.ended_at is not None

    def __repr__(self) -> str:
        """Return a debugging representation naming date and length."""
        return f"<TimeEntry date={self.log_date} minutes={self.duration_minutes:.0f}>"
