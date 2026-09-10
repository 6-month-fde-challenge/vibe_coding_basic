"""Time-tracking business rules."""

from __future__ import annotations

from datetime import date, datetime

from app.core.errors import ConflictError, ValidationError
from app.core.logging_config import get_logger
from app.core.timeutils import to_local
from app.domain.timetracking.allocation import (
    Allocation,
    Interval,
    TimeSlice,
    build_allocation,
    find_overlap,
)
from app.models.enums import CategoryKind
from app.models.time_entry import TimeEntry
from app.schemas.activity import (
    AllocationRead,
    AllocationSliceRead,
    TimeEntryFilter,
    TimeEntryInput,
    TimeEntryRead,
)
from app.schemas.common import DateRange, Page
from app.services.activity_service import resolve_interval
from app.services.base import BaseService
from app.services.unit_of_work import UnitOfWork

logger = get_logger(__name__)

#: Setting key controlling whether two timed entries may overlap.
OVERLAP_SETTING_KEY = "time_tracking.prevent_overlap"
#: Waking minutes in a day, used for the "untracked" figure. Assumes eight
#: hours of sleep when no sleep record exists for the day.
DEFAULT_WAKING_MINUTES = 16 * 60


class TimeTrackingService(BaseService):
    """Recording blocks of time and reporting where they went."""

    def list_for_day(self, day: date | None = None) -> list[TimeEntryRead]:
        """Return one day's entries."""
        with self.uow() as uow:
            return [
                TimeEntryRead.model_validate(row)
                for row in uow.time_entries.list_for_day(day or self.today())
            ]

    def search(self, criteria: TimeEntryFilter) -> Page[TimeEntryRead]:
        """Filtered, paginated time history."""
        with self.uow() as uow:
            rows, total = uow.time_entries.search(criteria)
            return Page[TimeEntryRead](
                items=[TimeEntryRead.model_validate(row) for row in rows],
                total=total,
                limit=criteria.pagination.limit,
                offset=criteria.pagination.offset,
            )

    def log(self, payload: TimeEntryInput) -> TimeEntryRead:
        """Record a block of time.

        Raises:
            ValidationError: If the date is in the future or the category is
                not a time category.
            ConflictError: If overlap prevention is on and the entry clashes
                with another timed entry on the same day.
        """
        if payload.log_date > self.today():
            raise ValidationError(
                "Cannot track time in the future",
                field="log_date",
                value=payload.log_date.isoformat(),
                user_hint="Pick today or an earlier date.",
            )

        started_at, ended_at, minutes = resolve_interval(
            log_date=payload.log_date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            duration_minutes=payload.duration_minutes,
            tz=self.tz,
        )

        with self.uow() as uow:
            category = uow.categories.get_or_raise(payload.category_id)
            if category.kind is not CategoryKind.TIME:
                raise ValidationError(
                    "That category cannot be used for time tracking",
                    field="category_id",
                    value=payload.category_id,
                    user_hint=f"{category.name!r} is a {category.kind.value.lower()} category.",
                )

            if started_at is not None and ended_at is not None and self._overlap_enabled(uow):
                self._reject_overlap(uow, payload.log_date, started_at, ended_at)

            entry = TimeEntry(
                user_id=self.user_id,
                log_date=payload.log_date,
                category_id=payload.category_id,
                started_at=started_at,
                ended_at=ended_at,
                duration_minutes=minutes,
                description=payload.description,
            )
            uow.time_entries.add(entry)
            uow.commit()
            logger.info(
                "Time entry %s logged on %s (%.0f minutes)",
                entry.id,
                payload.log_date.isoformat(),
                minutes,
            )
            return TimeEntryRead.model_validate(entry)

    def delete(self, entry_id: int) -> None:
        """Remove a time entry."""
        with self.uow() as uow:
            entry = uow.time_entries.get_or_raise(entry_id)
            uow.time_entries.delete(entry)
            uow.commit()
            logger.info("Time entry %s deleted", entry_id)

    # -- reporting ---------------------------------------------------------

    def allocation(
        self, period: DateRange, *, available_minutes: float | None = None
    ) -> Allocation:
        """Break a period's tracked time down by category."""
        with self.uow() as uow:
            rows = uow.time_entries.minutes_by_category(period.start, period.end)
        slices = [
            TimeSlice(
                category_id=category_id,
                category_name=name,
                minutes=minutes,
                is_productive=productive,
            )
            for category_id, name, productive, minutes in rows
        ]
        return build_allocation(slices, available_minutes=available_minutes)

    def allocation_read(self, period: DateRange) -> AllocationRead:
        """Allocation in the shape the UI renders."""
        allocation = self.allocation(period)
        total = allocation.total_minutes or 1.0
        return AllocationRead(
            slices=[
                AllocationSliceRead(
                    category_id=item.category_id,
                    category_name=item.category_name,
                    minutes=item.minutes,
                    is_productive=item.is_productive,
                    share=item.minutes / total,
                )
                for item in allocation.slices
            ],
            total_minutes=allocation.total_minutes,
            productive_minutes=allocation.productive_minutes,
            productive_share=allocation.productive_share,
        )

    def minutes_for_categories(self, period: DateRange, category_ids: list[int]) -> float:
        """Total minutes across a range for a set of categories."""
        with self.uow() as uow:
            return uow.time_entries.total_minutes_for_categories(
                period.start, period.end, category_ids
            )

    def minutes_for_category_name(self, period: DateRange, name: str) -> float:
        """Total minutes for one named time category.

        Used by the dashboard's study / coding / teaching tiles. Resolving
        the name to an id here keeps the *name* out of everything below the
        service layer.
        """
        with self.uow() as uow:
            category = uow.categories.get_by_name(CategoryKind.TIME, name)
            if category is None:
                return 0.0
            return uow.time_entries.total_minutes_for_categories(
                period.start, period.end, [category.id]
            )

    def quick_add(
        self, category_name: str, minutes: float, day: date | None = None
    ) -> TimeEntryRead:
        """Log time against a category by name.

        The Quick Add path: "Studied, two hours", with no clock times.

        Raises:
            ValidationError: If no time category has that name.
        """
        target = day or self.today()
        with self.uow() as uow:
            category = uow.categories.get_by_name(CategoryKind.TIME, category_name)
            if category is None:
                raise ValidationError(
                    "No such time category",
                    field="category_name",
                    value=category_name,
                    user_hint=f"Add a time category called {category_name!r} in Settings first.",
                )
            category_id = category.id

        return self.log(
            TimeEntryInput(log_date=target, category_id=category_id, duration_minutes=minutes)
        )

    # -- internals ---------------------------------------------------------

    def _overlap_enabled(self, uow: UnitOfWork) -> bool:
        """Whether overlapping timed entries are refused.

        Off by default: plenty of people genuinely study while a podcast
        plays, and refusing that by default makes the tracker argumentative.
        """
        return bool(uow.settings.get_value(OVERLAP_SETTING_KEY) or False)

    def _reject_overlap(
        self, uow: UnitOfWork, day: date, started_at: datetime, ended_at: datetime
    ) -> None:
        """Raise if the candidate interval clashes with an existing one."""
        existing = [
            Interval(start=row.started_at, end=row.ended_at, identifier=row.id)
            for row in uow.time_entries.entries_with_interval_on(day)
            if row.started_at is not None and row.ended_at is not None
        ]
        clash = find_overlap(Interval(start=started_at, end=ended_at), existing)
        if clash is None:
            return

        local_start = to_local(clash.start, self.tz).strftime("%H:%M")
        local_end = to_local(clash.end, self.tz).strftime("%H:%M")
        raise ConflictError(
            "Time entry overlaps an existing one",
            details={"conflicting_entry_id": clash.identifier},
            user_hint=f"That overlaps an entry from {local_start} to {local_end}.",
        )


__all__ = ["DEFAULT_WAKING_MINUTES", "OVERLAP_SETTING_KEY", "TimeTrackingService"]
