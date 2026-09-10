"""Journal, morning check-in and evening review."""

from __future__ import annotations

from datetime import date

from app.core.errors import ValidationError
from app.core.logging_config import get_logger
from app.models.journal import JournalEntry
from app.schemas.common import DateRange, Page, Pagination
from app.schemas.journal import (
    DailyLogRead,
    EveningReview,
    JournalInput,
    JournalRead,
    MorningCheckIn,
)
from app.services.base import BaseService

logger = get_logger(__name__)


class JournalService(BaseService):
    """The subjective record of a day.

    Journal text is the most private thing in the database. Nothing in this
    service logs it; the log records dates and field counts only.
    """

    def get_for_date(self, day: date) -> JournalRead | None:
        """Return one day's entry, if there is one."""
        with self.uow() as uow:
            entry = uow.journal.get_for_date(day)
            return JournalRead.model_validate(entry) if entry else None

    def list_between(self, period: DateRange) -> list[JournalRead]:
        """Return entries inside a date range."""
        with self.uow() as uow:
            return [
                JournalRead.model_validate(row)
                for row in uow.journal.list_between(period.start, period.end)
            ]

    def history(self, pagination: Pagination) -> Page[JournalRead]:
        """Return journal history, newest first, one page at a time."""
        with self.uow() as uow:
            rows, total = uow.journal.page(pagination)
            return Page[JournalRead](
                items=[JournalRead.model_validate(row) for row in rows],
                total=total,
                limit=pagination.limit,
                offset=pagination.offset,
            )

    def search(self, term: str, pagination: Pagination) -> Page[JournalRead]:
        """Free-text search across the journal."""
        if not term.strip():
            raise ValidationError("Enter something to search for", field="term", value=term)
        with self.uow() as uow:
            rows, total = uow.journal.search_text(term.strip(), pagination)
            return Page[JournalRead](
                items=[JournalRead.model_validate(row) for row in rows],
                total=total,
                limit=pagination.limit,
                offset=pagination.offset,
            )

    def save(self, payload: JournalInput) -> JournalRead:
        """Create or replace one day's journal entry."""
        if payload.entry_date > self.today():
            raise ValidationError(
                "Cannot write a journal entry for a future date",
                field="entry_date",
                value=payload.entry_date.isoformat(),
            )

        with self.uow() as uow:
            entry = uow.journal.get_for_date(payload.entry_date)
            if entry is None:
                entry = JournalEntry(user_id=self.user_id, entry_date=payload.entry_date)
                uow.journal.add(entry)

            fields = payload.model_dump(exclude={"entry_date"})
            for field, value in fields.items():
                setattr(entry, field, value)

            uow.commit()
            # The text itself is never logged - only how much of the form
            # was filled in.
            logger.info(
                "Journal entry saved for %s (%d fields set)",
                payload.entry_date.isoformat(),
                sum(1 for value in fields.values() if value is not None),
            )
            return JournalRead.model_validate(entry)

    def delete(self, day: date) -> bool:
        """Remove one day's journal entry."""
        with self.uow() as uow:
            entry = uow.journal.get_for_date(day)
            if entry is None:
                return False
            uow.journal.delete(entry)
            uow.commit()
            logger.info("Journal entry for %s deleted", day.isoformat())
            return True

    # -- daily log: check-in and review ------------------------------------

    def get_daily_log(self, day: date) -> DailyLogRead | None:
        """Return the day's rollup row, if one exists."""
        with self.uow() as uow:
            row = uow.daily_logs.get_for_date(day)
            return DailyLogRead.model_validate(row) if row else None

    def morning_checkin(self, payload: MorningCheckIn) -> DailyLogRead:
        """Record the morning plan.

        Writes the plan to the daily log and, when the form carried an
        energy rating, mirrors it into the journal so that the analytics
        engine has one place to read subjective ratings from.
        """
        if payload.log_date > self.today():
            raise ValidationError(
                "Cannot check in for a future day",
                field="log_date",
                value=payload.log_date.isoformat(),
            )

        with self.uow() as uow:
            log = uow.daily_logs.get_or_create(payload.log_date)
            log.main_goal = payload.main_goal
            log.priorities = [item for item in payload.priorities if item.strip()]
            log.planned_study_minutes = payload.planned_study_minutes
            log.planned_exercise_minutes = payload.planned_exercise_minutes
            log.morning_energy = payload.energy
            log.checkin_at = self.clock.now()

            if payload.energy is not None:
                entry = uow.journal.get_for_date(payload.log_date)
                if entry is None:
                    entry = JournalEntry(user_id=self.user_id, entry_date=payload.log_date)
                    uow.journal.add(entry)
                entry.energy = payload.energy

            uow.commit()
            logger.info("Morning check-in recorded for %s", payload.log_date.isoformat())
            return DailyLogRead.model_validate(log)

    def evening_review(self, payload: EveningReview) -> DailyLogRead:
        """Record the end-of-day verdict.

        The subjective ratings land in the journal, the verdict in the
        daily log. Splitting them keeps the score engine reading one table
        and the journal page reading another.
        """
        if payload.log_date > self.today():
            raise ValidationError(
                "Cannot review a day that has not happened",
                field="log_date",
                value=payload.log_date.isoformat(),
            )

        with self.uow() as uow:
            log = uow.daily_logs.get_or_create(payload.log_date)
            log.day_rating = payload.day_rating
            log.what_went_wrong = payload.what_went_wrong
            log.improve_tomorrow = payload.improve_tomorrow
            log.review_at = self.clock.now()

            entry = uow.journal.get_for_date(payload.log_date)
            if entry is None:
                entry = JournalEntry(user_id=self.user_id, entry_date=payload.log_date)
                uow.journal.add(entry)
            if payload.accomplishments is not None:
                entry.accomplishments = payload.accomplishments
            if payload.mood is not None:
                entry.mood = payload.mood
            if payload.energy is not None:
                entry.energy = payload.energy
            if payload.focus is not None:
                entry.focus = payload.focus

            uow.commit()
            logger.info("Evening review recorded for %s", payload.log_date.isoformat())
            return DailyLogRead.model_validate(log)

    def ratings(self, period: DateRange) -> dict[date, tuple[int | None, int | None]]:
        """Return ``(mood, focus)`` per date across a range."""
        with self.uow() as uow:
            return uow.journal.ratings_between(period.start, period.end)


__all__ = ["JournalService"]
