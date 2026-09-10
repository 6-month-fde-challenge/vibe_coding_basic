"""Summarising logged physical activity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.models.enums import ActivityIntensity


@dataclass(frozen=True, slots=True)
class ActivityRecord:
    """The little the summary needs from a logged activity."""

    log_date: date
    category_id: int
    category_name: str
    duration_minutes: float
    intensity: ActivityIntensity = ActivityIntensity.MODERATE
    calories: float | None = None


@dataclass(frozen=True, slots=True)
class ActivitySummary:
    """Aggregated activity over a window.

    Attributes:
        sessions: How many bouts were logged.
        total_minutes: Total time moving.
        active_days: Distinct days with at least one session.
        total_calories: Sum of recorded or estimated calories.
        minutes_by_category: Totals keyed by category name, largest first.
        minutes_by_intensity: Totals keyed by intensity.
        longest_session_minutes: The single longest bout.
    """

    sessions: int = 0
    total_minutes: float = 0.0
    active_days: int = 0
    total_calories: float = 0.0
    minutes_by_category: tuple[tuple[str, float], ...] = ()
    minutes_by_intensity: tuple[tuple[ActivityIntensity, float], ...] = ()
    longest_session_minutes: float = 0.0

    @property
    def has_data(self) -> bool:
        """Whether anything was logged."""
        return self.sessions > 0

    @property
    def average_session_minutes(self) -> float | None:
        """Mean length of a session."""
        return self.total_minutes / self.sessions if self.sessions else None

    def minutes_per_active_day(self) -> float | None:
        """Mean minutes across the days that had any activity."""
        return self.total_minutes / self.active_days if self.active_days else None


def summarize_activities(records: Sequence[ActivityRecord]) -> ActivitySummary:
    """Aggregate a list of activity records.

    Safe on an empty list, which is what a new install and a rest week both
    look like.
    """
    if not records:
        return ActivitySummary()

    by_category: dict[str, float] = {}
    by_intensity: dict[ActivityIntensity, float] = {}
    for record in records:
        by_category[record.category_name] = (
            by_category.get(record.category_name, 0.0) + record.duration_minutes
        )
        by_intensity[record.intensity] = (
            by_intensity.get(record.intensity, 0.0) + record.duration_minutes
        )

    return ActivitySummary(
        sessions=len(records),
        total_minutes=sum(record.duration_minutes for record in records),
        active_days=len({record.log_date for record in records}),
        total_calories=sum(record.calories or 0.0 for record in records),
        minutes_by_category=tuple(
            sorted(by_category.items(), key=lambda item: item[1], reverse=True)
        ),
        minutes_by_intensity=tuple(
            sorted(by_intensity.items(), key=lambda item: item[1], reverse=True)
        ),
        longest_session_minutes=max(record.duration_minutes for record in records),
    )
