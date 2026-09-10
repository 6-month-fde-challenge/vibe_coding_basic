"""What each command actually does.

One function per verb, each taking the wired container and the parsed
arguments and returning a process exit code. They call the *same services*
the web UI calls - which is the whole point of keeping business rules out
of the presentation layer, and is why this CLI is about six hundred lines
rather than a second implementation of the application.

Anything that can go wrong in a way the user can fix raises
:class:`~app.core.errors.CommandError`, which :mod:`app.cli.__main__`
turns into a message and a non-zero exit code.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from app.bootstrap import Container
from app.cli import formatters as fmt
from app.core.errors import CommandError
from app.core.logging_config import get_logger
from app.models.enums import (
    CategoryKind,
    HabitDirection,
    HabitFrequency,
    HabitType,
    TaskPriority,
    TaskStatus,
)
from app.schemas.activity import CategoryRead, TimeEntryInput
from app.schemas.common import DateRange
from app.schemas.habit import HabitCreate, HabitLogInput, HabitLogRead, HabitRead
from app.schemas.task import TaskCreate

logger = get_logger(__name__)

#: A command handler.
Handler = Callable[[Container, argparse.Namespace], int]

#: Exit codes. Zero is success; the rest tell a script what went wrong.
EXIT_OK = 0
EXIT_USER_ERROR = 1

#: How much history `list` and `stats` draw as a streak bar.
BAR_DAYS = 21

_WEEKDAY_NAMES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

_HABIT_TYPES = {
    "boolean": HabitType.BOOLEAN,
    "count": HabitType.COUNT,
    "duration": HabitType.DURATION,
    "quantity": HabitType.QUANTITY,
    "time": HabitType.TIME,
}

_FREQUENCIES = {
    "daily": HabitFrequency.DAILY,
    "weekdays": HabitFrequency.WEEKDAYS,
    "weekends": HabitFrequency.WEEKENDS,
    "specific-days": HabitFrequency.SPECIFIC_DAYS,
    "times-per-week": HabitFrequency.TIMES_PER_WEEK,
}

_PRIORITIES = {
    "low": TaskPriority.LOW,
    "medium": TaskPriority.MEDIUM,
    "high": TaskPriority.HIGH,
    "critical": TaskPriority.CRITICAL,
}


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _day(container: Container, args: argparse.Namespace) -> date:
    """Return the date the command applies to, defaulting to today.

    "Today" comes from the *profile's* timezone, not the machine's, so a
    late-night log lands on the day the user thinks it did.
    """
    chosen = getattr(args, "date", None)
    return chosen if chosen is not None else container.clock.today()


def _clock(value: str | None, field: str) -> time | None:
    """Parse an ``HH:MM`` argument.

    Raises:
        CommandError: If the string is not a clock time.
    """
    if value is None:
        return None
    try:
        hours, _, minutes = value.strip().partition(":")
        return time(hour=int(hours), minute=int(minutes or 0))
    except (TypeError, ValueError) as error:
        raise CommandError(
            f"{value!r} is not a time",
            hint=f"Give --{field} as HH:MM, for example 06:30.",
        ) from error


def _weekdays(value: str | None) -> list[int] | None:
    """Parse ``mon,wed,fri`` into weekday numbers.

    Raises:
        CommandError: If a name is not a weekday.
    """
    if not value:
        return None
    days = []
    for part in value.split(","):
        key = part.strip()[:3].lower()
        if key not in _WEEKDAY_NAMES:
            raise CommandError(
                f"{part.strip()!r} is not a weekday",
                hint="Use short names separated by commas: mon,tue,wed,thu,fri,sat,sun.",
            )
        days.append(_WEEKDAY_NAMES[key])
    return sorted(set(days))


def _resolve_habit(container: Container, name: str) -> HabitRead:
    """Find exactly one habit by name or prefix.

    Raises:
        CommandError: If nothing matches, or more than one thing does. An
            ambiguous prefix lists the candidates rather than guessing -
            silently ticking off the wrong habit is worse than an error.
    """
    matches = container.habits.find_by_name(name)
    if not matches:
        known = [habit.name for habit in container.habits.list_habits()]
        hint = f"Known habits: {', '.join(known)}." if known else "You have no habits yet."
        raise CommandError(f"No habit matching {name!r}", hint=hint)
    if len(matches) > 1:
        raise CommandError(
            f"{name!r} matches more than one habit",
            hint="Did you mean: " + ", ".join(habit.name for habit in matches) + "?",
        )
    return matches[0]


def _confirm(question: str) -> bool:
    """Ask a yes/no question on stdin.

    Returns ``False`` when stdin is not a terminal, so a piped or
    scripted run never hangs waiting for an answer that will not come.
    """
    if not sys.stdin.isatty():
        return False
    answer = input(f"{question} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


# --------------------------------------------------------------------------
# Habit commands
# --------------------------------------------------------------------------


def cmd_add(container: Container, args: argparse.Namespace) -> int:
    """Create a habit."""
    habit_type = _HABIT_TYPES[args.habit_type]
    frequency = _FREQUENCIES[args.frequency]

    needs_amount = habit_type not in {HabitType.BOOLEAN, HabitType.TIME}
    if needs_amount and args.target is None:
        raise CommandError(
            f"A {args.habit_type} habit needs a target",
            hint=f'Try: habits add "{args.name}" --type {args.habit_type} --target 20',
        )
    if habit_type is HabitType.TIME and args.target_time is None:
        raise CommandError(
            "A time habit needs a target time",
            hint=f'Try: habits add "{args.name}" --type time --at 06:30 --before',
        )

    category_id = None
    if args.category:
        category = _find_category(container, CategoryKind.HABIT, args.category)
        category_id = category.id

    habit = container.habits.create(
        HabitCreate(
            name=args.name,
            habit_type=habit_type,
            direction=HabitDirection.BEFORE if args.before else HabitDirection.AT_LEAST,
            frequency=frequency,
            target_value=args.target,
            min_target=args.min_target,
            unit=args.unit,
            target_time=_clock(args.target_time, "at"),
            specific_days=_weekdays(args.days),
            rest_days=_weekdays(args.rest),
            times_per_week=args.per_week,
            category_id=category_id,
            start_date=args.since or container.clock.today(),
        )
    )
    since = "" if args.since is None else f" Backfillable from {args.since.isoformat()}."
    print(f"Added {habit.name!r} - {habit.target_label}.{since}")
    return EXIT_OK


def cmd_list(container: Container, args: argparse.Namespace) -> int:
    """List habits with today's state and their streaks."""
    marks = fmt.symbols(args.plain)
    day = _day(container, args)
    views = container.habits.today_view(day)

    if not views:
        print("No habits yet. Add one:")
        print('  habits add "Read 20 pages" --type count --target 20 --unit pages')
        return EXIT_OK

    start = day - timedelta(days=BAR_DAYS - 1)
    body = []
    for view in views:
        if view.is_done:
            state = marks.done
        elif not view.is_due_today:
            state = marks.rest
        else:
            state = marks.todo
        completions = container.habits.completion_dates(view.habit.id, since=start)
        body.append(
            [
                state,
                fmt.truncate(view.habit.name, 22),
                view.habit.target_label,
                f"{view.streak.current_streak}d",
                fmt.percent(view.streak.completion_rate),
                fmt.streak_bar(completions, start, day, marks),
            ]
        )

    if not args.quiet:
        print(f"Habits on {day.isoformat()}  (last {BAR_DAYS} days on the right)\n")
    print(fmt.table(["", "Habit", "Target", "Streak", "Rate", "Recent"], body))
    return EXIT_OK


def cmd_done(container: Container, args: argparse.Namespace) -> int:
    """Tick a habit off for a day."""
    habit = _resolve_habit(container, args.name)
    day = _day(container, args)

    if habit.habit_type is HabitType.BOOLEAN:
        payload = HabitLogInput(habit_id=habit.id, log_date=day, checked=True, notes=args.note)
    elif habit.habit_type is HabitType.TIME:
        moment = _clock(args.value_time, "at")
        if moment is None:
            raise CommandError(
                f"{habit.name!r} records a time of day",
                hint=f'Try: habits done "{habit.name}" --at 06:15',
            )
        payload = HabitLogInput(habit_id=habit.id, log_date=day, value_time=moment, notes=args.note)
    else:
        if args.value is None:
            raise CommandError(
                f"{habit.name!r} records an amount",
                hint=f'Try: habits done "{habit.name}" --value 20',
            )
        payload = HabitLogInput(habit_id=habit.id, log_date=day, value=args.value, notes=args.note)

    log = _log_or_explain(container, habit, payload)
    streak = container.habits.streak(habit.id)
    verdict = "done" if log.completed else "logged, short of target"
    print(f"{habit.name}: {verdict} for {day.isoformat()}. Streak: {streak.current_streak} days.")
    return EXIT_OK


def _log_or_explain(container: Container, habit: HabitRead, payload: HabitLogInput) -> HabitLogRead:
    """Log a habit day, turning "before the start date" into advice.

    The service is right to refuse it - a habit cannot have been done
    before it existed - but the fix is a flag the user may not know about,
    so the CLI names it.
    """
    if habit.start_date is not None and payload.log_date < habit.start_date:
        raise CommandError(
            f"{habit.name!r} only starts on {habit.start_date.isoformat()}",
            hint=(
                f"To backfill, recreate it with --since {payload.log_date.isoformat()}, "
                "or pick a later date."
            ),
        )
    return container.habits.log(payload)


def cmd_undo(container: Container, args: argparse.Namespace) -> int:
    """Remove a habit's log for a day."""
    habit = _resolve_habit(container, args.name)
    day = _day(container, args)

    if not container.habits.remove_log(habit.id, day):
        print(f"{habit.name} had nothing logged for {day.isoformat()}.")
        return EXIT_OK

    streak = container.habits.streak(habit.id)
    print(f"{habit.name}: log for {day.isoformat()} removed. Streak: {streak.current_streak} days.")
    return EXIT_OK


def cmd_stats(container: Container, args: argparse.Namespace) -> int:
    """Show streaks and consistency for one habit."""
    marks = fmt.symbols(args.plain)
    habit = _resolve_habit(container, args.name)
    summary = container.habits.streak(habit.id, analysis_days=args.days)
    today = container.clock.today()
    start = today - timedelta(days=args.days - 1)
    completions = container.habits.completion_dates(habit.id, since=start)

    print(fmt.heading(habit.name))
    print(
        fmt.rows(
            [
                ("Target", habit.target_label, ""),
                ("Current streak", f"{summary.current_streak} days", ""),
                ("Longest streak", f"{summary.longest_streak} days", ""),
                ("Completed", f"{summary.total_completions} of {summary.expected_days} due", ""),
                (
                    "Completion",
                    fmt.percent(summary.completion_rate),
                    fmt.status_for(summary.completion_rate, marks),
                ),
                ("Missed", f"{summary.missed_days} days", ""),
                (
                    "Last 7 days",
                    fmt.percent(summary.weekly_consistency),
                    fmt.status_for(summary.weekly_consistency, marks),
                ),
                (
                    "Last 30 days",
                    fmt.percent(summary.monthly_consistency),
                    fmt.status_for(summary.monthly_consistency, marks),
                ),
                (
                    "Last completed",
                    summary.last_completed_on.isoformat() if summary.last_completed_on else "never",
                    "",
                ),
            ]
        )
    )
    print(f"\n{start.isoformat()} to {today.isoformat()}")
    print(fmt.streak_bar(completions, start, today, marks))
    return EXIT_OK


def cmd_remove(container: Container, args: argparse.Namespace) -> int:
    """Archive or delete a habit."""
    habit = _resolve_habit(container, args.name)

    if args.archive:
        container.habits.archive(habit.id)
        print(f"{habit.name!r} archived. Its history is kept.")
        return EXIT_OK

    if not args.yes and not _confirm(
        f"Delete {habit.name!r} and every log it has? This cannot be undone."
    ):
        print("Cancelled. Use --archive to retire it and keep the history.")
        return EXIT_OK

    container.habits.delete(habit.id)
    print(f"{habit.name!r} deleted, along with its logs.")
    return EXIT_OK


# --------------------------------------------------------------------------
# Day and week commands
# --------------------------------------------------------------------------


def cmd_today(container: Container, args: argparse.Namespace) -> int:
    """Print the day's overview and score."""
    marks = fmt.symbols(args.plain)
    day = _day(container, args)
    summary = container.analytics.daily_summary(day)
    profile = container.health.get_profile()

    print(fmt.heading(f"{summary.weekday} {day.isoformat()}"))

    if not summary.has_any_data:
        print("Nothing recorded yet.\n")
        print("  habits done <name>          tick a habit off")
        print("  habits sleep 23:30 06:30    log last night")
        print("  habits time Coding 90       log 90 minutes of coding")
        return EXIT_OK

    # A component the score skipped was not tracked at all, so it gets no
    # mark rather than a red one. "Nothing recorded" and "recorded a zero"
    # are different facts, and the row must agree with the breakdown
    # printed underneath it.
    skipped = set(summary.score.skipped)

    def ratio(actual: float | None, target: float, key: str) -> float | None:
        if key in skipped or actual is None or not target:
            return None
        return min(1.0, actual / target)

    print(
        fmt.rows(
            [
                (
                    "Sleep",
                    fmt.minutes(summary.sleep_minutes),
                    fmt.status_for(
                        ratio(summary.sleep_minutes, profile.target_sleep_minutes, "sleep"), marks
                    ),
                ),
                (
                    "Tasks",
                    f"{summary.tasks.completed} / {summary.tasks.total}",
                    fmt.status_for(summary.tasks.rate if summary.tasks.total else None, marks),
                ),
                (
                    "Habits",
                    f"{summary.habits.completed} / {summary.habits.due}",
                    fmt.status_for(summary.habits.rate if summary.habits.due else None, marks),
                ),
                (
                    "Exercise",
                    fmt.minutes(summary.exercise_minutes),
                    fmt.status_for(
                        ratio(
                            summary.exercise_minutes, profile.target_exercise_minutes, "exercise"
                        ),
                        marks,
                    ),
                ),
                (
                    "Studying",
                    fmt.minutes(summary.study_minutes),
                    fmt.status_for(
                        ratio(summary.study_minutes, profile.target_study_minutes, "learning"),
                        marks,
                    ),
                ),
                (
                    "Coding",
                    fmt.minutes(summary.coding_minutes),
                    fmt.status_for(
                        ratio(summary.coding_minutes, profile.target_coding_minutes, "learning"),
                        marks,
                    ),
                ),
                (
                    "Teaching",
                    fmt.minutes(summary.teaching_minutes),
                    fmt.status_for(
                        ratio(
                            summary.teaching_minutes, profile.target_teaching_minutes, "learning"
                        ),
                        marks,
                    ),
                ),
                ("Free time", fmt.minutes(summary.free_minutes), ""),
            ]
        )
    )

    print(f"\n{fmt.RULE}")
    if summary.score.has_data:
        print(f"Daily score: {summary.score.total:.0f}/100")
        for component in summary.score.components:
            print(f"  {component.label:<20} +{component.points:>5.1f}   {component.detail}")
        if summary.score.skipped:
            missing = ", ".join(key.replace("_", " ") for key in summary.score.skipped)
            print(f"  (not counted: {missing})")
    else:
        print("Not enough recorded yet to score the day.")
    print(fmt.RULE)
    return EXIT_OK


def cmd_week(container: Container, args: argparse.Namespace) -> int:
    """Print the weekly review."""
    marks = fmt.symbols(args.plain)
    anchor = _day(container, args)
    review = container.analytics.weekly_review(anchor)
    summary = review.summary

    print(fmt.heading(f"week of {summary.start.isoformat()}"))
    print(
        fmt.rows(
            [
                (
                    "Weekly score",
                    f"{summary.average_score:.0f}/100" if summary.average_score else "-",
                    fmt.status_for(
                        summary.average_score / 100 if summary.average_score else None, marks
                    ),
                ),
                ("Tasks", f"{summary.tasks_completed} / {summary.tasks_total}", ""),
                (
                    "Habits",
                    fmt.percent(summary.habit_completion_rate),
                    fmt.status_for(summary.habit_completion_rate, marks),
                ),
                ("Sleep", f"{fmt.minutes(summary.average_sleep_minutes)} avg", ""),
                ("Exercise", fmt.minutes(summary.exercise_minutes), ""),
                ("Studying", fmt.minutes(summary.study_minutes), ""),
                ("Coding", fmt.minutes(summary.coding_minutes), ""),
                ("Teaching", fmt.minutes(summary.teaching_minutes), ""),
            ]
        )
    )

    if review.habit_performance:
        print("\nHabits")
        print(
            fmt.table(
                ["Habit", "Done", "Rate", "Streak"],
                [
                    [
                        fmt.truncate(item.name, 24),
                        f"{item.completed}/{item.expected}",
                        fmt.percent(item.completion_rate),
                        f"{item.current_streak}d",
                    ]
                    for item in review.habit_performance
                ],
            )
        )

    if review.wins:
        print("\nWins")
        for win in review.wins:
            print(f"  + {win}")
    if review.problems:
        print("\nWatch")
        for problem in review.problems:
            print(f"  - {problem}")
    if review.insights:
        print("\nInsights")
        for insight in review.insights:
            print(f"  * {insight.message}")
    if review.suggested_focus:
        print(f"\nNext week: {review.suggested_focus}")
    return EXIT_OK


def cmd_sleep(container: Container, args: argparse.Namespace) -> int:
    """Record a night's sleep."""
    day = _day(container, args)
    record = container.sleep.quick_log(args.asleep, args.awake, day=day)

    if args.quality is not None:
        from app.schemas.sleep import SleepInput

        record = container.sleep.record(
            SleepInput(
                log_date=day,
                sleep_time=_require_clock(args.asleep, "asleep"),
                wake_time=_require_clock(args.awake, "awake"),
                quality=args.quality,
            )
        )

    print(f"Slept {fmt.minutes(record.duration_minutes)} on the night before {day.isoformat()}.")
    return EXIT_OK


def cmd_time(container: Container, args: argparse.Namespace) -> int:
    """Log time against a category."""
    day = _day(container, args)
    category = _find_category(container, CategoryKind.TIME, args.category)

    entry = container.time_tracking.log(
        TimeEntryInput(
            log_date=day,
            category_id=category.id,
            duration_minutes=args.minutes,
            description=args.note,
        )
    )
    total = container.time_tracking.allocation(DateRange(start=day, end=day)).total_minutes
    print(
        f"Logged {fmt.minutes(entry.duration_minutes)} of {category.name} "
        f"on {day.isoformat()}. Tracked today: {fmt.minutes(total)}."
    )
    return EXIT_OK


def cmd_categories(container: Container, args: argparse.Namespace) -> int:
    """List the configurable categories."""
    kinds = [CategoryKind(args.kind.upper())] if args.kind else list(CategoryKind)
    for kind in kinds:
        categories = container.categories.list_kind(kind)
        if not categories:
            continue
        print(f"\n{kind.value.title()}")
        print(
            fmt.table(
                ["Name", "Productive"],
                [[item.name, "yes" if item.is_productive else ""] for item in categories],
            )
        )
    return EXIT_OK


# --------------------------------------------------------------------------
# Task commands
# --------------------------------------------------------------------------


def cmd_task(container: Container, args: argparse.Namespace) -> int:
    """Add a task."""
    task = container.tasks.create(
        TaskCreate(
            title=args.title,
            due_date=_day(container, argparse.Namespace(date=args.due)),
            priority=_PRIORITIES[args.priority],
            estimated_minutes=args.estimate,
        )
    )
    print(f"Task #{task.id}: {task.title!r} due {task.due_date}.")
    return EXIT_OK


def cmd_tasks(container: Container, args: argparse.Namespace) -> int:
    """List the day's tasks."""
    marks = fmt.symbols(args.plain)
    day = _day(container, args)
    tasks = container.tasks.list_for_day(day)

    if not tasks:
        print(f"Nothing on the list for {day.isoformat()}.")
        return EXIT_OK

    body = [
        [
            marks.done if task.status is TaskStatus.COMPLETED else marks.todo,
            str(task.id),
            fmt.truncate(task.title, 40),
            task.priority.value.lower(),
            task.due_date.isoformat() if task.due_date else "",
        ]
        for task in tasks
    ]
    print(fmt.table(["", "id", "Task", "Priority", "Due"], body))
    return EXIT_OK


def cmd_complete(container: Container, args: argparse.Namespace) -> int:
    """Complete a task by id."""
    task = container.tasks.complete(args.task_id, actual_minutes=args.minutes)
    print(f"Completed #{task.id}: {task.title!r}.")
    return EXIT_OK


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def _find_category(container: Container, kind: CategoryKind, name: str) -> CategoryRead:
    """Resolve a category by name, listing the alternatives if it is wrong."""
    needle = name.strip().casefold()
    categories = container.categories.list_kind(kind)
    for category in categories:
        if category.name.casefold() == needle:
            return category
    for category in categories:
        if category.name.casefold().startswith(needle):
            return category
    raise CommandError(
        f"No {kind.value.lower()} category called {name!r}",
        hint="Available: " + ", ".join(item.name for item in categories),
    )


def _require_clock(value: str, field: str) -> time:
    """Parse a required ``HH:MM`` argument."""
    parsed = _clock(value, field)
    if parsed is None:  # pragma: no cover - argparse makes these required
        raise CommandError(f"{field} is required")
    return parsed


#: Every command the CLI knows, keyed by the word the user types.
COMMANDS: dict[str, Handler] = {
    "add": cmd_add,
    "list": cmd_list,
    "done": cmd_done,
    "undo": cmd_undo,
    "stats": cmd_stats,
    "remove": cmd_remove,
    "today": cmd_today,
    "week": cmd_week,
    "sleep": cmd_sleep,
    "time": cmd_time,
    "categories": cmd_categories,
    "task": cmd_task,
    "tasks": cmd_tasks,
    "complete": cmd_complete,
}


def dispatch(container: Container, args: argparse.Namespace) -> int:
    """Run the handler for a parsed invocation.

    Raises:
        CommandError: If the command word is not one this CLI implements.
            Argparse normally catches that, so reaching here means the
            registry and the parser have drifted apart.
    """
    handler = COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - guarded by argparse
        raise CommandError(
            f"Unknown command {args.command!r}",
            hint="Run `habits --help` to see the commands.",
        )
    logger.info("Running command %r", args.command)
    started = datetime.now(tz=container.clock.timezone)
    result = handler(container, args)
    logger.debug(
        "Command %r finished in %.0f ms",
        args.command,
        (datetime.now(tz=container.clock.timezone) - started).total_seconds() * 1000,
    )
    return result
