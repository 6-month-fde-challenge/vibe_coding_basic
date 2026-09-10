"""Journal, morning check-in and evening review schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ReadSchema, Schema

MAX_PRIORITIES = 3
RATING_MIN = 1
RATING_MAX = 10


class JournalInput(Schema):
    """A day's journal entry.

    Every field is optional. A journal that demands ten answers before it
    will save anything is a journal nobody fills in.
    """

    entry_date: date
    mood: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    energy: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    stress: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    motivation: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    focus: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    reflection: str | None = Field(default=None, max_length=8000)
    accomplishments: str | None = Field(default=None, max_length=8000)
    challenges: str | None = Field(default=None, max_length=8000)
    gratitude: str | None = Field(default=None, max_length=8000)
    notes: str | None = Field(default=None, max_length=8000)


class JournalRead(ReadSchema):
    """A stored journal entry."""

    id: int
    entry_date: date
    mood: int | None
    energy: int | None
    stress: int | None
    motivation: int | None
    focus: int | None
    reflection: str | None
    accomplishments: str | None
    challenges: str | None
    gratitude: str | None
    notes: str | None


class MorningCheckIn(Schema):
    """The sixty-second start-of-day form.

    Six questions, all optional, one screen. The constraint in the brief is
    that it can be completed in under a minute, which is a design
    constraint on this schema as much as on the page that renders it.
    """

    log_date: date
    sleep_quality: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    energy: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    main_goal: str | None = Field(default=None, max_length=255)
    priorities: list[str] = Field(default_factory=list, max_length=MAX_PRIORITIES)
    planned_study_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    planned_exercise_minutes: int | None = Field(default=None, ge=0, le=24 * 60)


class EveningReview(Schema):
    """The end-of-day form."""

    log_date: date
    accomplishments: str | None = Field(default=None, max_length=8000)
    mood: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    energy: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    focus: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    day_rating: int | None = Field(default=None, ge=RATING_MIN, le=RATING_MAX)
    what_went_wrong: str | None = Field(default=None, max_length=8000)
    improve_tomorrow: str | None = Field(default=None, max_length=8000)


class DailyLogRead(ReadSchema):
    """The stored spine of one day."""

    id: int
    log_date: date
    main_goal: str | None
    priorities: list[str] | None
    planned_study_minutes: int | None
    planned_exercise_minutes: int | None
    morning_energy: int | None
    checkin_at: datetime | None
    day_rating: int | None
    what_went_wrong: str | None
    improve_tomorrow: str | None
    review_at: datetime | None
    productivity_score: float | None

    @property
    def checkin_done(self) -> bool:
        """Whether the morning check-in has been completed."""
        return self.checkin_at is not None

    @property
    def review_done(self) -> bool:
        """Whether the evening review has been completed."""
        return self.review_at is not None
