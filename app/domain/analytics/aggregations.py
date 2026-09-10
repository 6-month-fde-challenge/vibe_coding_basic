"""Grouping a daily series into weeks, months and heatmap cells.

These are the shape transformations that sit between "the database gave me
one row per day" and "the chart needs one point per week". They are pure so
that the same rollup can be tested against a hand-written dictionary.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from app.core.timeutils import iso_week_label, month_label, week_start


@dataclass(frozen=True, slots=True)
class Bucket:
    """A group of days reduced to one number.

    Attributes:
        key: Sortable label, such as ``2026-W37`` or ``2026-09``.
        start: First date in the bucket.
        end: Last date in the bucket.
        total: Sum of the values inside it.
        average: Mean of the values that were present.
        days_with_data: How many days contributed.
        days_in_bucket: How many days the bucket spans.
    """

    key: str
    start: date
    end: date
    total: float
    average: float | None
    days_with_data: int
    days_in_bucket: int

    @property
    def coverage(self) -> float:
        """Share of the bucket's days that had data."""
        return self.days_with_data / self.days_in_bucket if self.days_in_bucket else 0.0


@dataclass(frozen=True, slots=True)
class HeatmapCell:
    """One square of the calendar heatmap."""

    day: date
    value: float | None
    week_index: int
    weekday: int


def fill_missing_days(
    series: Mapping[date, float],
    start: date,
    end: date,
    *,
    default: float | None = None,
) -> dict[date, float | None]:
    """Expand a sparse daily series to every date in a range.

    A chart that silently skips missing days draws a line through a gap and
    implies data that does not exist. Filling with ``None`` makes the gap
    visible; filling with ``0.0`` is right for counts.
    """
    return {day: series.get(day, default) for day in _walk(start, end)}


def _walk(start: date, end: date) -> list[date]:
    """Return every date in the inclusive range."""
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def group_by_week(
    series: Mapping[date, float],
    *,
    first_weekday: int = 0,
) -> list[Bucket]:
    """Roll a daily series up into weeks.

    Args:
        series: Daily values.
        first_weekday: ``0`` for Monday.

    Returns:
        One bucket per week that had at least one value, in date order.
    """
    grouped: dict[date, list[float]] = {}
    for day, value in series.items():
        grouped.setdefault(week_start(day, first_weekday), []).append(value)

    return [
        Bucket(
            key=iso_week_label(start),
            start=start,
            end=start + timedelta(days=6),
            total=sum(values),
            average=statistics.fmean(values) if values else None,
            days_with_data=len(values),
            days_in_bucket=7,
        )
        for start, values in sorted(grouped.items())
    ]


def group_by_month(series: Mapping[date, float]) -> list[Bucket]:
    """Roll a daily series up into calendar months."""
    grouped: dict[date, list[float]] = {}
    for day, value in series.items():
        grouped.setdefault(day.replace(day=1), []).append(value)

    buckets: list[Bucket] = []
    for start, values in sorted(grouped.items()):
        next_month = (start + timedelta(days=32)).replace(day=1)
        end = next_month - timedelta(days=1)
        buckets.append(
            Bucket(
                key=month_label(start),
                start=start,
                end=end,
                total=sum(values),
                average=statistics.fmean(values) if values else None,
                days_with_data=len(values),
                days_in_bucket=(end - start).days + 1,
            )
        )
    return buckets


def build_heatmap(
    series: Mapping[date, float],
    start: date,
    end: date,
    *,
    first_weekday: int = 0,
) -> list[HeatmapCell]:
    """Lay a daily series out as GitHub-style calendar cells.

    The grid is columns of weeks and rows of weekdays, so ``week_index`` is
    the x coordinate and ``weekday`` the y coordinate. Days with no data get
    ``None`` rather than zero, so "nothing recorded" and "recorded a zero"
    stay distinguishable in the colour scale.
    """
    if end < start:
        return []

    grid_start = week_start(start, first_weekday)
    cells: list[HeatmapCell] = []
    for day in _walk(grid_start, end):
        if day < start:
            continue
        offset = (day - grid_start).days
        cells.append(
            HeatmapCell(
                day=day,
                value=series.get(day),
                week_index=offset // 7,
                weekday=(day.weekday() - first_weekday) % 7,
            )
        )
    return cells


def rolling_totals(
    series: Mapping[date, float], start: date, end: date, window: int
) -> dict[date, float]:
    """Trailing sum over ``window`` days, evaluated at every date in range.

    Computed with a sliding window rather than a nested loop, so a year of
    30-day totals is one pass, not 365 slices.
    """
    if window <= 0 or end < start:
        return {}

    running = 0.0
    totals: dict[date, float] = {}
    for day in _walk(start, end):
        running += series.get(day, 0.0)
        expired = day - timedelta(days=window)
        if expired >= start:
            running -= series.get(expired, 0.0)
        totals[day] = running
    return totals


def distribution(values: Sequence[float], buckets: Sequence[float]) -> dict[str, int]:
    """Count how many values fall into each half-open bucket.

    Args:
        values: The observations.
        buckets: Ascending upper bounds. A final ``"+"`` bucket catches
            everything above the last bound.

    Returns:
        Counts keyed by a readable range label.
    """
    if not buckets:
        return {}

    labels = [f"<{buckets[0]:g}"]
    labels += [f"{low:g}-{high:g}" for low, high in pairwise(buckets)]
    labels.append(f"{buckets[-1]:g}+")

    counts = dict.fromkeys(labels, 0)
    for value in values:
        index = next((i for i, bound in enumerate(buckets) if value < bound), len(buckets))
        counts[labels[index]] += 1
    return counts
