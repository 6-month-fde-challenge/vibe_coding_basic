"""Turning read models into terminal output.

Presentation only - nothing here reaches a database or decides a rule.

The one non-obvious job is encoding. A Windows console often runs on
cp1252, where printing a green circle raises ``UnicodeEncodeError`` and
kills the command. So the symbol set is chosen at import time by asking
the *actual* stdout whether it can encode them, with an ASCII fallback
that says the same thing.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.timeutils import format_duration

#: Width of the boxed report headings.
WIDTH = 56
RULE = "-" * WIDTH


@dataclass(frozen=True, slots=True)
class Symbols:
    """The glyphs used to mark state, in one of two sets."""

    good: str
    warn: str
    bad: str
    done: str
    todo: str
    rest: str
    filled: str
    empty: str


UNICODE_SYMBOLS = Symbols(
    good="🟢", warn="🟡", bad="🔴", done="✓", todo="·", rest="~", filled="█", empty="░"
)
ASCII_SYMBOLS = Symbols(
    good="[ok]", warn="[--]", bad="[!!]", done="x", todo=".", rest="~", filled="#", empty="."
)


def _console_supports(sample: str) -> bool:
    """Whether stdout can actually encode a string.

    Asks the stream rather than guessing from the platform: a Windows
    terminal set to UTF-8 handles these fine, and a redirected pipe on
    Linux might not.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        sample.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def symbols(plain: bool = False) -> Symbols:
    """Return the symbol set this terminal can print."""
    if plain or not _console_supports("🟢✓█"):
        return ASCII_SYMBOLS
    return UNICODE_SYMBOLS


def heading(title: str) -> str:
    """Render a centred, ruled heading."""
    return f"{RULE}\n{title.upper().center(WIDTH)}\n{RULE}"


def status_for(fraction: float | None, marks: Symbols) -> str:
    """Map an achievement fraction to a status mark."""
    if fraction is None:
        return " "
    if fraction >= 0.9:
        return marks.good
    if fraction >= 0.6:
        return marks.warn
    return marks.bad


def rows(pairs: Sequence[tuple[str, str, str]], label_width: int = 14) -> str:
    """Render aligned ``label / value / mark`` rows.

    This is the shape the brief's overview sketch uses, and it is the
    reason the report reads at a glance rather than as a wall of prose.
    """
    lines = []
    value_width = max((len(value) for _, value, _ in pairs), default=0)
    for label, value, mark in pairs:
        lines.append(f"{label:<{label_width}} {value:<{value_width}}  {mark}".rstrip())
    return "\n".join(lines)


def table(headers: Sequence[str], body: Sequence[Sequence[str]]) -> str:
    """Render a plain aligned table.

    No box-drawing characters: they are the first thing a narrow terminal
    or a copy-paste into a document breaks.
    """
    if not body:
        return ""
    columns = [len(header) for header in headers]
    for row in body:
        for index, cell in enumerate(row):
            columns[index] = max(columns[index], len(cell))

    def render(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(columns[index]) for index, cell in enumerate(cells)).rstrip()

    lines = [render(headers), "  ".join("-" * width for width in columns)]
    lines.extend(render(row) for row in body)
    return "\n".join(lines)


def streak_bar(completions: Sequence[date], start: date, end: date, marks: Symbols) -> str:
    """Render a run of days as a row of marks, oldest first."""
    done = set(completions)
    cells = []
    cursor = start
    while cursor <= end:
        cells.append(marks.done if cursor in done else marks.todo)
        cursor += timedelta(days=1)
    return "".join(cells)


def progress(fraction: float, marks: Symbols, width: int = 20) -> str:
    """Render a fraction as a text progress bar."""
    filled = max(0, min(width, round(fraction * width)))
    return marks.filled * filled + marks.empty * (width - filled)


def minutes(value: float | None) -> str:
    """Render minutes as ``7h 32m``."""
    return format_duration(value)


def percent(fraction: float | None) -> str:
    """Render a 0-1 fraction as a percentage."""
    return "-" if fraction is None else f"{fraction * 100:.0f}%"


def truncate(text: str | None, limit: int) -> str:
    """Shorten text to fit a column."""
    if not text:
        return ""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."
