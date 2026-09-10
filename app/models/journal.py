"""The journal entry and the per-day rollup log."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin
from app.database.types import JSONColumn

if TYPE_CHECKING:
    from app.models.user import UserProfile

#: Every subjective rating in the journal uses the same 1-10 scale.
_RATING_CHECK = "BETWEEN 1 AND 10"


class JournalEntry(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """How the day felt, in the user's own words and on 1-10 scales."""

    __tablename__ = "journal_entry"
    __table_args__ = (
        UniqueConstraint("user_id", "entry_date", name="uq_journal_entry_user_date"),
        Index("ix_journal_entry_user_date", "user_id", "entry_date"),
        CheckConstraint(f"mood IS NULL OR mood {_RATING_CHECK}", name="mood_range"),
        CheckConstraint(f"energy IS NULL OR energy {_RATING_CHECK}", name="energy_range"),
        CheckConstraint(f"stress IS NULL OR stress {_RATING_CHECK}", name="stress_range"),
        CheckConstraint(
            f"motivation IS NULL OR motivation {_RATING_CHECK}", name="motivation_range"
        ),
        CheckConstraint(f"focus IS NULL OR focus {_RATING_CHECK}", name="focus_range"),
    )

    entry_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    motivation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    focus: Mapped[int | None] = mapped_column(Integer, nullable=True)

    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    accomplishments: Mapped[str | None] = mapped_column(Text, nullable=True)
    challenges: Mapped[str | None] = mapped_column(Text, nullable=True)
    gratitude: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="journal_entries")

    def __repr__(self) -> str:
        """Return a debugging representation naming the date only.

        Deliberately excludes the text: this object ends up in log records.
        """
        return f"<JournalEntry date={self.entry_date}>"


class DailyLog(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """The spine of a single day: intentions in the morning, verdict at night.

    Holds what the morning check-in captured (a plan) and the evening review
    concluded (a verdict), plus a cached productivity score. The score is
    cached because the calendar heatmap needs 365 of them at once, and
    recomputing each from its underlying tasks, habits and sleep would be
    365 round trips.
    """

    __tablename__ = "daily_log"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_daily_log_user_date"),
        Index("ix_daily_log_user_date", "user_id", "log_date"),
        CheckConstraint(
            "productivity_score IS NULL OR productivity_score BETWEEN 0 AND 100",
            name="score_range",
        ),
        CheckConstraint(
            f"day_rating IS NULL OR day_rating {_RATING_CHECK}", name="day_rating_range"
        ),
        CheckConstraint(
            "planned_study_minutes IS NULL OR planned_study_minutes >= 0",
            name="planned_study_non_negative",
        ),
        CheckConstraint(
            "planned_exercise_minutes IS NULL OR planned_exercise_minutes >= 0",
            name="planned_exercise_non_negative",
        ),
    )

    log_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    # --- morning check-in -------------------------------------------------
    main_goal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Up to three short strings; a list because the order is the priority.
    priorities: Mapped[list[str] | None] = mapped_column(JSONColumn, nullable=True)
    planned_study_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_exercise_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    morning_energy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checkin_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --- evening review ---------------------------------------------------
    day_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    what_went_wrong: Mapped[str | None] = mapped_column(Text, nullable=True)
    improve_tomorrow: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --- cached scoring ---------------------------------------------------
    productivity_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    #: Per-component contributions, so the score stays explainable after the
    #: fact even if the weights are later changed.
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    score_computed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="daily_logs")

    def __repr__(self) -> str:
        """Return a debugging representation naming the date and score."""
        return f"<DailyLog date={self.log_date} score={self.productivity_score}>"
