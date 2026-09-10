"""The command-line grammar.

Argparse checks the *shape* of an invocation - that ``done`` was given a
name, that ``--value`` is a number. Anything that needs to know what the
words mean (is that a real habit? is that date in the future?) is checked
in :mod:`app.cli.commands` and reported as a
:class:`~app.core.errors.CommandError`.

Keeping the grammar in its own module means the whole CLI surface can be
read in one screen, and ``build_parser()`` can be called by a test without
starting the application.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from app import __version__
from app.core.errors import CommandError

PROGRAM = "habits"

DESCRIPTION = "Daily habit tracker - add habits, tick them off, watch the streaks."

EPILOG = """\
examples:
  habits add "Read 20 pages" --type count --target 20 --unit pages
  habits done "Read 20 pages" --value 24
  habits done "Meditate" --date 2026-09-07
  habits list
  habits stats "Read 20 pages"
  habits today
  habits sleep 23:30 06:30
  habits time Coding 90

The same data is also browsable in a web UI: streamlit run app/main.py
"""

#: Habit measurement types, as the CLI spells them.
HABIT_TYPES = ("boolean", "count", "duration", "quantity", "time")
#: How often a habit is due.
FREQUENCIES = ("daily", "weekdays", "weekends", "specific-days", "times-per-week")
#: Task priorities.
PRIORITIES = ("low", "medium", "high", "critical")


def parse_day(value: str) -> date:
    """Parse a ``--date`` argument.

    Accepts ``YYYY-MM-DD``, ``today``, ``yesterday``, or a negative number
    of days such as ``-3``. Typing the ISO date for "the day before
    yesterday" is exactly the friction that stops people backfilling.

    Args:
        value: The raw argument.

    Returns:
        The resolved calendar date.

    Raises:
        CommandError: If the string is not a date this understands.
    """
    text = value.strip().lower()
    today = date.today()  # noqa: DTZ011 - the profile timezone is applied by the caller

    if text in {"today", "t"}:
        return today
    if text in {"yesterday", "y"}:
        return today - timedelta(days=1)
    if text.startswith("-") and text[1:].isdigit():
        return today - timedelta(days=int(text[1:]))

    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise CommandError(
            f"{value!r} is not a date I understand",
            hint="Use YYYY-MM-DD, 'today', 'yesterday', or '-3' for three days ago.",
        ) from error


def day_argument(value: str) -> date:
    """Adapt :func:`parse_day` for use as an argparse ``type=``.

    Argparse only converts ``ValueError`` and ``ArgumentTypeError`` into a
    tidy usage message; anything else escapes as a traceback, and parsing
    happens *before* the entry point's try block can catch it. So the
    :class:`~app.core.errors.CommandError` is translated here, hint and
    all, and the user gets a usage message instead of a stack trace.
    """
    try:
        return parse_day(value)
    except CommandError as error:
        message = error.user_message()
        raise argparse.ArgumentTypeError(
            f"{message}. {error.hint}" if error.hint else message
        ) from error


def _global_flags() -> argparse.ArgumentParser:
    """Return the flags every subcommand also accepts.

    Argparse puts options on whichever parser defines them, so by default
    ``habits --plain list`` works and ``habits list --plain`` does not -
    which is not how anyone types. Attaching this parent to every
    subcommand accepts both.

    ``SUPPRESS`` is what stops the subparser's default from overwriting a
    value given before the subcommand: without it, ``habits --plain list``
    would parse ``--plain`` and then have the subparser reset it to False.
    """
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print only what was asked for, no headings.",
    )
    shared.add_argument(
        "--plain",
        action="store_true",
        default=argparse.SUPPRESS,
        help="ASCII only. Use this if your terminal mangles the symbols.",
    )
    return shared


def build_parser() -> argparse.ArgumentParser:
    """Build the full command-line grammar."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    parser.add_argument(
        "--quiet", action="store_true", help="Print only what was asked for, no headings."
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="ASCII only. Use this if your terminal mangles the symbols.",
    )

    commands = parser.add_subparsers(dest="command", metavar="command")
    shared = _global_flags()

    _add_habit_commands(commands, shared)
    _add_day_commands(commands, shared)
    _add_task_commands(commands, shared)

    return parser


def _add_habit_commands(
    commands: argparse._SubParsersAction, shared: argparse.ArgumentParser
) -> None:
    """Register the habit verbs - the core of the tool."""
    add = commands.add_parser("add", parents=[shared], help="Create a habit.")
    add.add_argument("name", help='Habit name, e.g. "Read 20 pages".')
    add.add_argument(
        "--type",
        dest="habit_type",
        choices=HABIT_TYPES,
        default="boolean",
        help="What the habit measures. Default: boolean (did it or not).",
    )
    add.add_argument("--target", type=float, help="Target amount, for a measured habit.")
    add.add_argument("--min", dest="min_target", type=float, help="Amount that still counts.")
    add.add_argument("--unit", help='Unit label, e.g. "pages", "minutes", "litres".')
    add.add_argument("--at", dest="target_time", help="Target time HH:MM, for a time habit.")
    add.add_argument(
        "--before",
        action="store_true",
        help="For a time habit: the target is a deadline, not a starting point.",
    )
    add.add_argument(
        "--frequency", choices=FREQUENCIES, default="daily", help="How often it is due."
    )
    add.add_argument(
        "--days",
        help="Weekdays for --frequency specific-days, e.g. mon,wed,fri.",
    )
    add.add_argument("--per-week", type=int, help="Count for --frequency times-per-week.")
    add.add_argument("--rest", help="Weekdays that are never a miss, e.g. sun.")
    add.add_argument("--category", help="Category name.")
    add.add_argument(
        "--since",
        type=day_argument,
        help="When you started. Set this to backfill history; nothing can be "
        "logged before it. Default: today.",
    )

    listing = commands.add_parser("list", parents=[shared], help="List habits with their streaks.")
    listing.add_argument("--all", action="store_true", help="Include archived habits.")
    listing.add_argument("--date", type=day_argument, help="Show the state on this date.")

    done = commands.add_parser("done", parents=[shared], help="Tick a habit off for a day.")
    done.add_argument("name", help="Habit name, or a unique prefix of one.")
    done.add_argument("--date", type=day_argument, help="Default: today.")
    done.add_argument("--value", type=float, help="Amount, for a measured habit.")
    done.add_argument("--at", dest="value_time", help="Time HH:MM, for a time habit.")
    done.add_argument("--note", help="A note against the day.")

    undo = commands.add_parser("undo", parents=[shared], help="Remove a habit's log for a day.")
    undo.add_argument("name", help="Habit name, or a unique prefix.")
    undo.add_argument("--date", type=day_argument, help="Default: today.")

    stats = commands.add_parser(
        "stats", parents=[shared], help="Streaks and completion rate for one habit."
    )
    stats.add_argument("name", help="Habit name, or a unique prefix.")
    stats.add_argument("--days", type=int, default=30, help="History window. Default: 30.")

    remove = commands.add_parser(
        "remove", parents=[shared], help="Delete a habit and all its logs."
    )
    remove.add_argument("name", help="Habit name, or a unique prefix.")
    remove.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    remove.add_argument(
        "--archive",
        action="store_true",
        help="Retire the habit but keep its history. Almost always the better option.",
    )


def _add_day_commands(
    commands: argparse._SubParsersAction, shared: argparse.ArgumentParser
) -> None:
    """Register the commands about a day or a week as a whole."""
    today = commands.add_parser("today", parents=[shared], help="The day's overview and score.")
    today.add_argument("--date", type=day_argument, help="Default: today.")

    week = commands.add_parser("week", parents=[shared], help="The weekly review.")
    week.add_argument("--date", type=day_argument, help="Any date in the week. Default: today.")

    sleep = commands.add_parser("sleep", parents=[shared], help="Record a night's sleep.")
    sleep.add_argument("asleep", help="Time you fell asleep, HH:MM.")
    sleep.add_argument("awake", help="Time you woke up, HH:MM.")
    sleep.add_argument("--date", type=day_argument, help="The morning you woke. Default: today.")
    sleep.add_argument("--quality", type=int, choices=range(1, 11), metavar="1-10")

    time_entry = commands.add_parser("time", parents=[shared], help="Log time against a category.")
    time_entry.add_argument("category", help='Category name, e.g. "Coding".')
    time_entry.add_argument("minutes", type=float, help="How many minutes.")
    time_entry.add_argument("--date", type=day_argument, help="Default: today.")
    time_entry.add_argument("--note", help="What you were working on.")

    categories = commands.add_parser(
        "categories", parents=[shared], help="List the configurable categories."
    )
    categories.add_argument(
        "--kind",
        choices=("task", "habit", "activity", "time"),
        help="Show only one kind.",
    )


def _add_task_commands(
    commands: argparse._SubParsersAction, shared: argparse.ArgumentParser
) -> None:
    """Register the small task verbs, so the day's figures are actionable."""
    task = commands.add_parser("task", parents=[shared], help="Add a task.")
    task.add_argument("title", help="What needs doing.")
    task.add_argument("--due", type=day_argument, help="Default: today.")
    task.add_argument("--priority", choices=PRIORITIES, default="medium")
    task.add_argument("--estimate", type=int, help="Estimated minutes.")

    tasks = commands.add_parser("tasks", parents=[shared], help="List the day's tasks.")
    tasks.add_argument("--date", type=day_argument, help="Default: today.")

    complete = commands.add_parser("complete", parents=[shared], help="Complete a task by its id.")
    complete.add_argument("task_id", type=int, help="The id shown by `tasks`.")
    complete.add_argument("--minutes", type=int, help="How long it actually took.")
