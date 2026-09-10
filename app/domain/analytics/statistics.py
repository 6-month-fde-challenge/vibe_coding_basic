"""Small statistical helpers that are safe on empty input.

Every function here returns ``None`` rather than raising when there is not
enough data. A tracker's most common dataset on day one is the empty one,
and a dashboard that raises ``StatisticsError`` on a fresh install is worse
than one that shows a dash.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float | None:
    """Arithmetic mean, or ``None`` for an empty sequence."""
    return statistics.fmean(values) if values else None


def median(values: Sequence[float]) -> float | None:
    """Median, or ``None`` for an empty sequence."""
    return statistics.median(values) if values else None


def stdev(values: Sequence[float]) -> float | None:
    """Population standard deviation, or ``None`` for fewer than two values."""
    return statistics.pstdev(values) if len(values) >= 2 else None


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide, returning ``default`` instead of raising on a zero divisor."""
    return numerator / denominator if denominator else default


def percentage_change(previous: float | None, current: float | None) -> float | None:
    """Relative change from ``previous`` to ``current``, as a percentage.

    Returns ``None`` when either side is unknown, or when the baseline is
    zero - "up from nothing" is a fact, not a percentage.
    """
    if previous is None or current is None or previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def moving_average(values: Sequence[float], window: int) -> list[float | None]:
    """Trailing moving average.

    Args:
        values: The series.
        window: Number of points to average over.

    Returns:
        A list the same length as ``values``. Positions with fewer than
        ``window`` preceding points are ``None`` rather than a short average,
        so a chart does not draw a misleadingly smooth start.
    """
    if window <= 0:
        return [None] * len(values)

    out: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        out.append(running / window if index >= window - 1 else None)
    return out


def linear_slope(values: Sequence[float]) -> float | None:
    """Least-squares slope of a series against its own index.

    Used to answer "is this drifting up or down" without pulling in a
    regression library. Returns ``None`` for fewer than two points.
    """
    count = len(values)
    if count < 2:
        return None

    x_mean = (count - 1) / 2.0
    y_mean = statistics.fmean(values)
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    return numerator / denominator if denominator else None


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Constrain a value to a closed interval."""
    return max(low, min(high, value))
