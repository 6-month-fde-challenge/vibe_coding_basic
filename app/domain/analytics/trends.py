"""Comparing periods and detecting direction in a series."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.analytics.statistics import linear_slope, mean, percentage_change
from app.models.enums import TrendDirection

#: A change smaller than this is noise, not a trend.
FLAT_THRESHOLD_PERCENT = 5.0


@dataclass(frozen=True, slots=True)
class Comparison:
    """One metric measured over two periods.

    Attributes:
        label: What was measured.
        previous: Value in the earlier period.
        current: Value in the later period.
        change: ``current - previous``.
        change_percent: Relative change, or ``None`` when undefined.
        direction: Up, down or flat, using
            :data:`FLAT_THRESHOLD_PERCENT` as the deadband.
    """

    label: str
    previous: float | None
    current: float | None
    change: float | None
    change_percent: float | None
    direction: TrendDirection

    @property
    def has_both(self) -> bool:
        """Whether both periods had data."""
        return self.previous is not None and self.current is not None


@dataclass(frozen=True, slots=True)
class SeriesTrend:
    """Direction of a single series over time.

    Attributes:
        label: What was measured.
        slope_per_day: Least-squares slope, in units per day.
        direction: Up, down or flat.
        first: First value in the series.
        last: Last value in the series.
        average: Mean over the series.
        points: How many values were analysed.
    """

    label: str
    slope_per_day: float | None
    direction: TrendDirection
    first: float | None
    last: float | None
    average: float | None
    points: int


@dataclass(frozen=True, slots=True)
class DayExtreme:
    """The best or worst day in a window."""

    day: date
    value: float


def _direction_from_percent(change_percent: float | None) -> TrendDirection:
    """Classify a percentage change, with a deadband around zero."""
    if change_percent is None or abs(change_percent) < FLAT_THRESHOLD_PERCENT:
        return TrendDirection.FLAT
    return TrendDirection.UP if change_percent > 0 else TrendDirection.DOWN


def compare(label: str, previous: float | None, current: float | None) -> Comparison:
    """Compare one metric across two periods."""
    change = None if previous is None or current is None else current - previous
    change_percent = percentage_change(previous, current)
    return Comparison(
        label=label,
        previous=previous,
        current=current,
        change=change,
        change_percent=change_percent,
        direction=_direction_from_percent(change_percent),
    )


def compare_periods(
    previous: Mapping[str, float | None],
    current: Mapping[str, float | None],
    *,
    labels: Mapping[str, str] | None = None,
) -> list[Comparison]:
    """Compare every metric present in either period.

    Args:
        previous: Earlier period's metrics, keyed by metric name.
        current: Later period's metrics, same keys.
        labels: Optional display names.

    Returns:
        One comparison per key, in the order the keys first appear.
    """
    names = list(previous) + [key for key in current if key not in previous]
    display = labels or {}
    return [compare(display.get(key, key), previous.get(key), current.get(key)) for key in names]


def detect_trend(label: str, values: Sequence[float]) -> SeriesTrend:
    """Fit a direction to a series.

    The deadband is expressed relative to the series' own mean, so a slope
    of two minutes a day is "flat" for sleep and meaningful for meditation.
    """
    if not values:
        return SeriesTrend(
            label=label,
            slope_per_day=None,
            direction=TrendDirection.FLAT,
            first=None,
            last=None,
            average=None,
            points=0,
        )

    slope = linear_slope(values)
    average = mean(values)
    direction = TrendDirection.FLAT
    if slope is not None and average:
        span_change_percent = (slope * len(values)) / abs(average) * 100.0
        direction = _direction_from_percent(span_change_percent)

    return SeriesTrend(
        label=label,
        slope_per_day=slope,
        direction=direction,
        first=values[0],
        last=values[-1],
        average=average,
        points=len(values),
    )


def best_and_worst(series: Mapping[date, float]) -> tuple[DayExtreme | None, DayExtreme | None]:
    """Return the highest and lowest scoring days in a mapping.

    Ties are broken by the earlier date, so the answer is stable between
    page loads.
    """
    if not series:
        return None, None
    ordered = sorted(series.items())
    best_day, best_value = max(ordered, key=lambda item: item[1])
    worst_day, worst_value = min(ordered, key=lambda item: item[1])
    return DayExtreme(best_day, best_value), DayExtreme(worst_day, worst_value)


def weekday_averages(series: Mapping[date, float]) -> dict[int, float]:
    """Average a daily series by day of week.

    Returns:
        Mapping of weekday number (0=Monday) to mean value. Weekdays with no
        data are absent rather than zero.
    """
    buckets: dict[int, list[float]] = {}
    for day, value in series.items():
        buckets.setdefault(day.weekday(), []).append(value)
    return {weekday: sum(values) / len(values) for weekday, values in buckets.items()}
