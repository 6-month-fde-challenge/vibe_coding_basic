"""Working out when a recurring task is next due.

Occurrences are *generated* rather than computed on the fly at read time.
That is a deliberate trade: a stored occurrence keeps its own completion
history, its own actual duration and its own notes, none of which survive
if "every weekday" is re-expanded from the template on every page load.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.errors import ValidationError
from app.models.enums import RecurrenceRule

#: Guards against a spec that never matches - for example a weekly rule with
#: an empty day list - turning generation into an infinite loop.
_MAX_SCAN_DAYS = 800
#: Ceiling on how many occurrences one call will generate.
MAX_GENERATED_OCCURRENCES = 366


@dataclass(frozen=True, slots=True)
class RecurrenceSpec:
    """How a task repeats.

    Attributes:
        rule: The repeat pattern.
        interval: Repeat every N days/weeks/months. Must be at least 1.
        weekdays: Weekday numbers (0=Monday) for a weekly rule that fires on
            particular days.
        until: Last date an occurrence may fall on.
    """

    rule: RecurrenceRule = RecurrenceRule.NONE
    interval: int = 1
    weekdays: frozenset[int] = frozenset()
    until: date | None = None

    @classmethod
    def build(
        cls,
        rule: RecurrenceRule = RecurrenceRule.NONE,
        interval: int = 1,
        weekdays: Sequence[int] | None = None,
        until: date | None = None,
    ) -> RecurrenceSpec:
        """Build a spec from the loose values stored on a task row.

        Raises:
            ValidationError: If the interval is below one, or a weekday
                number is outside ``0..6``.
        """
        if interval < 1:
            raise ValidationError(
                "Repeat interval must be at least 1", field="recurrence_interval", value=interval
            )
        days = frozenset(weekdays or ())
        if any(day < 0 or day > 6 for day in days):
            raise ValidationError(
                "Weekday numbers must be between 0 (Monday) and 6 (Sunday)",
                field="recurrence_days",
                value=sorted(days),
            )
        return cls(rule=rule, interval=interval, weekdays=days, until=until)

    @property
    def repeats(self) -> bool:
        """Whether this spec generates anything at all."""
        return self.rule is not RecurrenceRule.NONE


def _add_months(day: date, months: int) -> date:
    """Add whole months, clamping the day of month.

    31 January plus one month is 28 February (or the 29th), not an error and
    not 3 March.
    """
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    # Last day of the target month, found by stepping back from the first of
    # the following one.
    first_of_next = date(year + (month // 12), (month % 12) + 1, 1)
    last_day = (first_of_next - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def next_occurrence(spec: RecurrenceSpec, anchor: date, after: date) -> date | None:
    """Return the first occurrence strictly after ``after``.

    Args:
        spec: The repeat rule.
        anchor: The template's own due date - the phase of the repetition.
        after: The date to search beyond.

    Returns:
        The next due date, or ``None`` if the rule has run out.
    """
    if not spec.repeats:
        return None

    match spec.rule:
        case RecurrenceRule.DAILY | RecurrenceRule.CUSTOM:
            candidate = _next_by_step(anchor, after, timedelta(days=spec.interval))
        case RecurrenceRule.WEEKLY:
            candidate = _next_weekly(spec, anchor, after)
        case RecurrenceRule.MONTHLY:
            candidate = _next_monthly(spec, anchor, after)
        case _:  # pragma: no cover - RecurrenceRule.NONE handled above
            return None

    if candidate is None:
        return None
    if spec.until is not None and candidate > spec.until:
        return None
    return candidate


def _next_by_step(anchor: date, after: date, step: timedelta) -> date | None:
    """Advance from the anchor in fixed steps until past ``after``.

    Uses arithmetic rather than a loop so that an anchor years in the past
    costs the same as one from yesterday.
    """
    if step.days <= 0:  # pragma: no cover - guarded by RecurrenceSpec.build
        return None
    if anchor > after:
        return anchor
    gap_days = (after - anchor).days
    steps = gap_days // step.days + 1
    return anchor + step * steps


def _next_weekly(spec: RecurrenceSpec, anchor: date, after: date) -> date | None:
    """Next weekly occurrence, honouring an optional set of weekdays."""
    if not spec.weekdays:
        return _next_by_step(anchor, after, timedelta(days=7 * spec.interval))

    anchor_week = anchor - timedelta(days=anchor.weekday())
    cursor = after + timedelta(days=1)
    for _ in range(_MAX_SCAN_DAYS):
        if cursor.weekday() in spec.weekdays:
            week = cursor - timedelta(days=cursor.weekday())
            weeks_apart = (week - anchor_week).days // 7
            if weeks_apart >= 0 and weeks_apart % spec.interval == 0:
                return cursor
        cursor += timedelta(days=1)
    return None


def _next_monthly(spec: RecurrenceSpec, anchor: date, after: date) -> date | None:
    """Next monthly occurrence, clamping to the length of the month."""
    months_apart = (after.year - anchor.year) * 12 + (after.month - anchor.month)
    step = max(0, (months_apart // spec.interval) * spec.interval)
    for extra in range(0, spec.interval * 3 + 1, spec.interval):
        candidate = _add_months(anchor, step + extra)
        if candidate > after:
            return candidate
    return None  # pragma: no cover - unreachable for interval >= 1


def occurrences_between(
    spec: RecurrenceSpec,
    anchor: date,
    start: date,
    end: date,
    *,
    limit: int = MAX_GENERATED_OCCURRENCES,
) -> Iterator[date]:
    """Yield every occurrence inside the inclusive range.

    Args:
        spec: The repeat rule.
        anchor: The template's due date.
        start: First date of interest.
        end: Last date of interest.
        limit: Hard cap on how many dates are produced, so a daily rule over
            a decade cannot be asked for by accident.

    Yields:
        Due dates, in ascending order.
    """
    if not spec.repeats or end < start:
        return

    if anchor >= start:
        cursor: date | None = anchor
    else:
        cursor = next_occurrence(spec, anchor, start - timedelta(days=1))

    produced = 0
    while cursor is not None and cursor <= end and produced < limit:
        if cursor >= start:
            yield cursor
            produced += 1
        cursor = next_occurrence(spec, anchor, cursor)
