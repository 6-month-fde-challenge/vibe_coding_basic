"""Category, activity and time-entry schemas."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import Field, model_validator

from app.models.enums import ActivityIntensity, CategoryKind
from app.schemas.common import Pagination, ReadSchema, Schema

MAX_DURATION_MINUTES = 24 * 60


class CategoryCreate(Schema):
    """A new user-defined category."""

    kind: CategoryKind
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=16)
    icon: str | None = Field(default=None, max_length=16)
    is_productive: bool = False
    sort_order: int = 100


class CategoryUpdate(Schema):
    """Edits to a category."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=16)
    icon: str | None = Field(default=None, max_length=16)
    is_productive: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class CategoryRead(ReadSchema):
    """A category as the UI sees it."""

    id: int
    kind: CategoryKind
    name: str
    color: str | None
    icon: str | None
    is_productive: bool
    is_active: bool
    sort_order: int


class _IntervalInput(Schema):
    """Shared validation for anything with an optional start/end pair."""

    log_date: date
    start_time: time | None = None
    end_time: time | None = None
    duration_minutes: float | None = Field(default=None, gt=0, le=MAX_DURATION_MINUTES)

    @model_validator(mode="after")
    def _needs_a_duration(self) -> _IntervalInput:
        """Require either a duration or both ends of an interval."""
        has_interval = self.start_time is not None and self.end_time is not None
        if not has_interval and self.duration_minutes is None:
            msg = "Give either a duration or both a start and an end time."
            raise ValueError(msg)
        if (self.start_time is None) != (self.end_time is None):
            msg = "Give both a start and an end time, or neither."
            raise ValueError(msg)
        return self


class ActivityInput(_IntervalInput):
    """A bout of exercise or sport."""

    category_id: int
    intensity: ActivityIntensity = ActivityIntensity.MODERATE
    calories: float | None = Field(default=None, ge=0, le=20000)
    estimate_calories: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class ActivityRead(ReadSchema):
    """A stored activity."""

    id: int
    log_date: date
    category_id: int
    started_at: datetime | None
    ended_at: datetime | None
    duration_minutes: float
    intensity: ActivityIntensity
    calories: float | None
    notes: str | None


class TimeEntryInput(_IntervalInput):
    """A block of tracked time."""

    category_id: int
    description: str | None = Field(default=None, max_length=255)


class TimeEntryRead(ReadSchema):
    """A stored time entry."""

    id: int
    log_date: date
    category_id: int
    started_at: datetime | None
    ended_at: datetime | None
    duration_minutes: float
    description: str | None


class TimeEntryFilter(Schema):
    """Filter criteria for the time-tracking history."""

    date_from: date | None = None
    date_to: date | None = None
    category_ids: list[int] | None = None
    search: str | None = Field(default=None, max_length=120)
    pagination: Pagination = Pagination()


class AllocationSliceRead(ReadSchema):
    """One category's share of a period."""

    category_id: int
    category_name: str
    minutes: float
    is_productive: bool
    share: float


class AllocationRead(ReadSchema):
    """A period's time allocation."""

    slices: list[AllocationSliceRead]
    total_minutes: float
    productive_minutes: float
    productive_share: float
