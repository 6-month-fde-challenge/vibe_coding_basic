"""Where the day went: time allocation and overlap detection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TimeSlice:
    """Minutes booked against one category.

    Attributes:
        category_id: Identifier of the category.
        category_name: Display name.
        minutes: Total minutes.
        is_productive: Whether the category is marked productive. This is a
            per-category flag the user controls, not a judgement the code
            makes about "entertainment".
    """

    category_id: int
    category_name: str
    minutes: float
    is_productive: bool = False


@dataclass(frozen=True, slots=True)
class Allocation:
    """A period's time broken down by category.

    Attributes:
        slices: Per-category totals, largest first.
        total_minutes: Everything that was tracked.
        productive_minutes: Total across categories flagged productive.
        untracked_minutes: Waking hours with nothing booked against them,
            when a day length was supplied.
    """

    slices: tuple[TimeSlice, ...] = ()
    total_minutes: float = 0.0
    productive_minutes: float = 0.0
    untracked_minutes: float | None = None

    @property
    def has_data(self) -> bool:
        """Whether anything was tracked."""
        return self.total_minutes > 0

    @property
    def productive_share(self) -> float:
        """Productive minutes as a fraction of tracked minutes."""
        return self.productive_minutes / self.total_minutes if self.total_minutes else 0.0

    def share_of(self, category_id: int) -> float:
        """Fraction of tracked time booked against one category."""
        if not self.total_minutes:
            return 0.0
        for item in self.slices:
            if item.category_id == category_id:
                return item.minutes / self.total_minutes
        return 0.0

    def top(self, count: int = 3) -> tuple[TimeSlice, ...]:
        """Return the ``count`` largest slices."""
        return self.slices[:count]


@dataclass(frozen=True, slots=True)
class Interval:
    """A half-open time interval, used for overlap checks."""

    start: datetime
    end: datetime
    identifier: int | None = None


def build_allocation(
    slices: Sequence[TimeSlice],
    *,
    available_minutes: float | None = None,
) -> Allocation:
    """Aggregate per-category minutes into a single picture.

    Args:
        slices: Per-category totals. Duplicated categories are merged.
        available_minutes: Waking minutes in the period, if the caller wants
            an untracked figure. Never negative in the result.

    Returns:
        The allocation, with slices ordered largest first.
    """
    merged: dict[int, TimeSlice] = {}
    for item in slices:
        existing = merged.get(item.category_id)
        if existing is None:
            merged[item.category_id] = item
        else:
            merged[item.category_id] = TimeSlice(
                category_id=item.category_id,
                category_name=existing.category_name,
                minutes=existing.minutes + item.minutes,
                is_productive=existing.is_productive or item.is_productive,
            )

    ordered = tuple(sorted(merged.values(), key=lambda item: item.minutes, reverse=True))
    total = sum(item.minutes for item in ordered)
    productive = sum(item.minutes for item in ordered if item.is_productive)
    untracked = max(0.0, available_minutes - total) if available_minutes is not None else None

    return Allocation(
        slices=ordered,
        total_minutes=total,
        productive_minutes=productive,
        untracked_minutes=untracked,
    )


def intervals_overlap(first: Interval, second: Interval) -> bool:
    """Whether two half-open intervals share any time.

    Half-open means an entry ending at 15:00 and one starting at 15:00 do
    not overlap, which is what back-to-back blocks should do.
    """
    return first.start < second.end and second.start < first.end


def find_overlap(candidate: Interval, existing: Sequence[Interval]) -> Interval | None:
    """Return the first existing interval that clashes with ``candidate``.

    Args:
        candidate: The interval being added or edited.
        existing: Intervals already recorded, typically the same day's.

    Returns:
        The clashing interval, or ``None``. An interval is never considered
        to clash with itself, matched on :attr:`Interval.identifier`.
    """
    for other in existing:
        if candidate.identifier is not None and other.identifier == candidate.identifier:
            continue
        if intervals_overlap(candidate, other):
            return other
    return None
