"""Habit business rules: definitions, logging and streaks."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.errors import ConflictError, ValidationError
from app.core.logging_config import get_logger
from app.domain.habits.completion import CompletionResult, HabitTarget, evaluate
from app.domain.habits.schedule import HabitSchedule
from app.domain.habits.streaks import StreakSummary, current_streak, longest_streak, summarize
from app.models.enums import HabitType
from app.models.habit import Habit, HabitLog
from app.schemas.habit import (
    HabitCreate,
    HabitLogInput,
    HabitLogRead,
    HabitRead,
    HabitStreakRead,
    HabitTodayRead,
    HabitUpdate,
)
from app.services.base import BaseService

logger = get_logger(__name__)

#: Analysis window for the completion-rate figures on the habits page.
DEFAULT_ANALYSIS_DAYS = 90


def schedule_of(habit: Habit) -> HabitSchedule:
    """Build the domain schedule from a habit row.

    The one place a persisted habit is translated into the value object the
    streak engine understands. Everything else takes the schedule.
    """
    return HabitSchedule.build(
        frequency=habit.frequency,
        specific_days=habit.specific_days,
        rest_days=habit.rest_days,
        times_per_week=habit.times_per_week,
        start_date=habit.start_date,
        end_date=habit.end_date,
    )


def target_of(habit: Habit) -> HabitTarget:
    """Build the domain target from a habit row."""
    return HabitTarget(
        habit_type=habit.habit_type,
        direction=habit.direction,
        target_value=habit.target_value,
        target_time=habit.target_time,
        min_target=habit.min_target,
    )


class HabitService(BaseService):
    """Habits, their daily logs, and everything derived from them."""

    # -- definitions -------------------------------------------------------

    def list_habits(self, *, active_only: bool = True) -> list[HabitRead]:
        """Return the configured habits."""
        with self.uow() as uow:
            rows = (
                uow.habits.list_active()
                if active_only
                else uow.habits.list_all_habits(include_inactive=True)
            )
            return [HabitRead.model_validate(row) for row in rows]

    def get(self, habit_id: int) -> HabitRead:
        """Return one habit."""
        with self.uow() as uow:
            return HabitRead.model_validate(uow.habits.get_or_raise(habit_id))

    def create(self, payload: HabitCreate) -> HabitRead:
        """Create a habit.

        Raises:
            ConflictError: If the name is already taken. Duplicate names
                make every streak display ambiguous, so this is refused
                rather than silently allowed.
        """
        with self.uow() as uow:
            if uow.habits.name_exists(payload.name):
                raise ConflictError(
                    "A habit with that name already exists",
                    details={"name": payload.name},
                    user_hint=f"You already track a habit called {payload.name!r}.",
                )
            if payload.category_id is not None:
                uow.categories.get_or_raise(payload.category_id)

            habit = Habit(
                user_id=self.user_id,
                name=payload.name,
                description=payload.description,
                category_id=payload.category_id,
                habit_type=payload.habit_type,
                direction=payload.direction,
                frequency=payload.frequency,
                target_value=payload.target_value,
                min_target=payload.min_target,
                ideal_target=payload.ideal_target,
                target_time=payload.target_time,
                unit=payload.unit,
                specific_days=payload.specific_days,
                rest_days=payload.rest_days,
                times_per_week=payload.times_per_week,
                start_date=payload.start_date or self.today(),
                end_date=payload.end_date,
                reminder_enabled=payload.reminder_enabled,
                reminder_time=payload.reminder_time,
                color=payload.color,
                icon=payload.icon,
            )
            uow.habits.add(habit)
            uow.commit()
            logger.info("Habit %s created", habit.id)
            return HabitRead.model_validate(habit)

    def update(self, habit_id: int, payload: HabitUpdate) -> HabitRead:
        """Apply a partial edit to a habit."""
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(habit_id)
            changes = payload.model_dump(exclude_unset=True)

            new_name = changes.get("name")
            if new_name and uow.habits.name_exists(new_name, exclude_id=habit_id):
                raise ConflictError(
                    "A habit with that name already exists",
                    details={"name": new_name},
                    user_hint=f"You already track a habit called {new_name!r}.",
                )
            if changes.get("category_id") is not None:
                uow.categories.get_or_raise(changes["category_id"])

            for field, value in changes.items():
                setattr(habit, field, value)

            uow.commit()
            logger.info("Habit %s updated: %s", habit_id, ", ".join(sorted(changes)))
            return HabitRead.model_validate(habit)

    def archive(self, habit_id: int) -> HabitRead:
        """Retire a habit without deleting its history.

        Preferred over deletion: the logs are the record of what actually
        happened, and losing them to a tidy-up is not recoverable.
        """
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(habit_id)
            habit.is_active = False
            habit.end_date = habit.end_date or self.today()
            uow.commit()
            logger.info("Habit %s archived", habit_id)
            return HabitRead.model_validate(habit)

    def delete(self, habit_id: int) -> None:
        """Delete a habit and every log it owns."""
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(habit_id)
            uow.habits.delete(habit)
            uow.commit()
            logger.warning("Habit %s deleted along with its logs", habit_id)

    # -- logging -----------------------------------------------------------

    def log(self, payload: HabitLogInput) -> HabitLogRead:
        """Record or update one habit's reading for one day.

        Updating an existing log is allowed and is the normal way to correct
        a mistake. Inserting a *second* log for the same habit and day is
        not, and the unique constraint backs that up in the database rather
        than trusting this method to be the only writer.

        Raises:
            ValidationError: If the date is in the future, the habit was not
                yet started, or the reading does not match the habit type.
        """
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(payload.habit_id)
            self._validate_log_date(habit, payload.log_date)

            result = self._evaluate(habit, payload)
            existing = uow.habits.get_log(habit.id, payload.log_date)

            if existing is None:
                log = HabitLog(
                    habit_id=habit.id,
                    log_date=payload.log_date,
                    value=payload.value,
                    value_time=payload.value_time,
                    completed=result.completed,
                    is_rest_day=payload.is_rest_day,
                    notes=payload.notes,
                    logged_at=self.clock.now(),
                )
                uow.habits.add_log(log)
                logger.info(
                    "Habit %s logged for %s (done=%s)",
                    habit.id,
                    payload.log_date.isoformat(),
                    result.completed,
                )
            else:
                logger.warning(
                    "Habit %s already had a log for %s; updating it",
                    habit.id,
                    payload.log_date.isoformat(),
                )
                existing.value = payload.value
                existing.value_time = payload.value_time
                existing.completed = result.completed
                existing.is_rest_day = payload.is_rest_day
                existing.notes = payload.notes
                existing.logged_at = self.clock.now()
                log = existing

            uow.commit()
            return HabitLogRead.model_validate(log)

    def toggle(self, habit_id: int, day: date | None = None) -> HabitLogRead | None:
        """Tick or untick a boolean habit for a day.

        Returns:
            The resulting log, or ``None`` if the tick was removed.

        Raises:
            ValidationError: If the habit measures an amount, which cannot
                be toggled.
        """
        target = day or self.today()
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(habit_id)
            if habit.habit_type is not HabitType.BOOLEAN:
                raise ValidationError(
                    "This habit records an amount, so it cannot be toggled",
                    field="habit_type",
                    value=habit.habit_type.value,
                    user_hint=f"Enter a value for {habit.name} instead of ticking it.",
                )
            self._validate_log_date(habit, target)

            existing = uow.habits.get_log(habit_id, target)
            if existing is not None and existing.completed:
                uow.habits.delete_log(existing)
                uow.commit()
                logger.info("Habit %s unticked for %s", habit_id, target.isoformat())
                return None

        return self.log(HabitLogInput(habit_id=habit_id, log_date=target, checked=True))

    def remove_log(self, habit_id: int, day: date) -> bool:
        """Delete one day's log. Returns whether anything was removed."""
        with self.uow() as uow:
            uow.habits.get_or_raise(habit_id)
            existing = uow.habits.get_log(habit_id, day)
            if existing is None:
                return False
            uow.habits.delete_log(existing)
            uow.commit()
            logger.info("Habit %s log for %s removed", habit_id, day.isoformat())
            return True

    # -- streaks and today's view -----------------------------------------

    def streak(self, habit_id: int, *, analysis_days: int = DEFAULT_ANALYSIS_DAYS) -> StreakSummary:
        """Return the full consistency picture for one habit."""
        today = self.today()
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(habit_id)
            schedule = schedule_of(habit)
            dates = uow.habits.completed_dates(habit_id)
        window_start = _window_start(habit, today, analysis_days)
        return summarize(dates, schedule, today, window_start=window_start)

    def current_streak_only(self, habit_id: int) -> int:
        """Return just the current streak, reading as few rows as possible.

        Uses the paged descending iterator, so a habit with years of history
        and a short streak costs one small query.
        """
        today = self.today()
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(habit_id)
            schedule = schedule_of(habit)
            dates = uow.habits.iter_completed_dates_desc(habit_id, on_or_before=today)
            return current_streak(dates, schedule, today)

    def today_view(self, day: date | None = None) -> list[HabitTodayRead]:
        """Return every active habit with its state for one day.

        Three queries in total - habits, that day's logs, and the completion
        dates behind the streaks - rather than three per habit.
        """
        target = day or self.today()
        window_start = target - timedelta(days=DEFAULT_ANALYSIS_DAYS - 1)
        views: list[HabitTodayRead] = []

        with self.uow() as uow:
            habits = uow.habits.list_active()
            logs_today = uow.habits.logs_for_day(target)
            window_logs = uow.habits.logs_between(window_start, target)

        # Group the window once, in memory, rather than issuing one query
        # per habit inside the loop below.
        completions: dict[int, list[date]] = {}
        for log in window_logs:
            if log.completed:
                completions.setdefault(log.habit_id, []).append(log.log_date)

        for habit in habits:
            schedule = schedule_of(habit)
            summary = summarize(
                completions.get(habit.id, []),
                schedule,
                target,
                window_start=_window_start(habit, target, DEFAULT_ANALYSIS_DAYS),
            )
            todays_log = logs_today.get(habit.id)
            views.append(
                HabitTodayRead(
                    habit=HabitRead.model_validate(habit),
                    log=HabitLogRead.model_validate(todays_log) if todays_log else None,
                    is_due_today=schedule.is_expected_on(target),
                    is_rest_day=schedule.is_rest_day(target),
                    streak=_streak_read(habit.id, summary),
                )
            )
        return views

    def find_by_name(self, name: str, *, active_only: bool = False) -> list[HabitRead]:
        """Return habits matching a name, exactly or by prefix.

        Typing a full habit name at a prompt is friction, so the CLI
        accepts a prefix. An exact match always wins outright: a habit
        called "Read" must not become ambiguous the day "Read papers" is
        added.

        Args:
            name: The full name or a prefix, matched case-insensitively.
            active_only: Ignore archived habits.

        Returns:
            The matches. Empty for none, one entry for a resolved name,
            several when a prefix is ambiguous.
        """
        needle = name.strip().casefold()
        habits = self.list_habits(active_only=active_only)

        exact = [habit for habit in habits if habit.name.casefold() == needle]
        if exact:
            return exact
        return [habit for habit in habits if habit.name.casefold().startswith(needle)]

    def completion_dates(self, habit_id: int, *, since: date | None = None) -> list[date]:
        """Return the dates one habit was completed on, oldest first.

        Exposed so the UI can draw a history strip without reaching past
        the service layer into a repository.
        """
        with self.uow() as uow:
            uow.habits.get_or_raise(habit_id)
            return uow.habits.completed_dates(habit_id, since=since)

    def longest(self, habit_id: int) -> int:
        """Return the longest streak this habit has ever had."""
        with self.uow() as uow:
            habit = uow.habits.get_or_raise(habit_id)
            return longest_streak(uow.habits.completed_dates(habit_id), schedule_of(habit))

    def completion_rate_for_day(self, day: date) -> tuple[int, int]:
        """Return ``(completed, due)`` habit counts for one day."""
        with self.uow() as uow:
            habits = uow.habits.list_active()
            logs = uow.habits.logs_for_day(day)

        due = 0
        done = 0
        for habit in habits:
            schedule = schedule_of(habit)
            if not schedule.is_expected_on(day):
                continue
            due += 1
            log = logs.get(habit.id)
            if log is not None and log.completed:
                done += 1
        return done, due

    # -- internals ---------------------------------------------------------

    def _validate_log_date(self, habit: Habit, day: date) -> None:
        """Reject a log date the habit cannot accept."""
        today = self.today()
        if day > today:
            raise ValidationError(
                "Cannot log a habit in the future",
                field="log_date",
                value=day.isoformat(),
                user_hint="You can only record a habit for today or a past date.",
            )
        if habit.start_date and day < habit.start_date:
            raise ValidationError(
                "That date is before the habit started",
                field="log_date",
                value=day.isoformat(),
                user_hint=(
                    f"{habit.name} started on {habit.start_date.isoformat()}. "
                    "Change its start date if you want to backfill further."
                ),
            )
        if habit.end_date and day > habit.end_date:
            raise ValidationError(
                "That date is after the habit ended",
                field="log_date",
                value=day.isoformat(),
                user_hint=f"{habit.name} ended on {habit.end_date.isoformat()}.",
            )

    def _evaluate(self, habit: Habit, payload: HabitLogInput) -> CompletionResult:
        """Apply the completion rule, treating a rest day as satisfied."""
        if payload.is_rest_day:
            return CompletionResult(completed=True, ratio=1.0)
        return evaluate(
            target_of(habit),
            value=payload.value,
            value_time=payload.value_time,
            checked=payload.checked,
        )


def _window_start(habit: Habit, today: date, analysis_days: int) -> date:
    """First date of the analysis window for one habit."""
    earliest = today - timedelta(days=analysis_days - 1)
    if habit.start_date and habit.start_date > earliest:
        return habit.start_date
    return earliest


def _streak_read(habit_id: int, summary: StreakSummary) -> HabitStreakRead:
    """Convert a domain streak summary into its read schema."""
    return HabitStreakRead(
        habit_id=habit_id,
        current_streak=summary.current_streak,
        longest_streak=summary.longest_streak,
        completion_rate=summary.completion_rate,
        missed_days=summary.missed_days,
        weekly_consistency=summary.weekly_consistency,
        monthly_consistency=summary.monthly_consistency,
        last_completed_on=summary.last_completed_on,
    )


__all__ = ["DEFAULT_ANALYSIS_DAYS", "HabitService", "schedule_of", "target_of"]
