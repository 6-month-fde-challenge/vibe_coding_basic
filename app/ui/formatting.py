"""Turning numbers into the strings the pages print.

Presentation only. Nothing here reaches a database or decides a rule; it
exists so that "7h 32m" is spelled the same way on all eleven pages.
"""

from __future__ import annotations

from datetime import date, time

from app.core.timeutils import format_duration
from app.models.enums import TaskPriority, TaskStatus

#: Icons paired with every status colour, so colour never stands alone.
STATUS_BADGES: dict[TaskStatus, str] = {
    TaskStatus.TODO: "⚪ To do",
    TaskStatus.IN_PROGRESS: "🔵 In progress",
    TaskStatus.COMPLETED: "🟢 Completed",
    TaskStatus.SKIPPED: "🟡 Skipped",
    TaskStatus.CANCELLED: "⚫ Cancelled",
}

PRIORITY_BADGES: dict[TaskPriority, str] = {
    TaskPriority.LOW: "Low",
    TaskPriority.MEDIUM: "Medium",
    TaskPriority.HIGH: "High",
    TaskPriority.CRITICAL: "Critical",
}


def minutes(value: float | None) -> str:
    """Render minutes as ``7h 32m``."""
    return format_duration(value)


def hours(value: float | None, places: int = 1) -> str:
    """Render minutes as a decimal count of hours."""
    if value is None:
        return "-"
    return f"{value / 60:.{places}f}h"


def percent(fraction: float | None, places: int = 0) -> str:
    """Render a 0-1 fraction as a percentage."""
    if fraction is None:
        return "-"
    return f"{fraction * 100:.{places}f}%"


def score(value: float | None) -> str:
    """Render a productivity score out of 100."""
    return "-" if value is None else f"{value:.0f}"


def signed(value: float | None, unit: str = "", places: int = 0) -> str:
    """Render a change with an explicit sign."""
    if value is None:
        return "-"
    return f"{value:+.{places}f}{unit}"


def clock(value: time | None) -> str:
    """Render a clock time as ``HH:MM``."""
    return "-" if value is None else value.strftime("%H:%M")


def day_label(value: date | None) -> str:
    """Render a date as ``Thu 10 Sep 2026``."""
    return "-" if value is None else value.strftime("%a %d %b %Y")


def short_day(value: date) -> str:
    """Render a date as ``10 Sep``."""
    return value.strftime("%d %b")


def streak_label(current: int, longest: int) -> str:
    """Render a streak pair, marking a personal best."""
    if current == 0:
        return "no streak"
    best = " (best ever)" if current >= longest and current > 1 else ""
    return f"{current}-day streak{best}"


def ratio(done: int, total: int) -> str:
    """Render a ``done / total`` pair."""
    return f"{done} / {total}"


def truncate(text: str | None, limit: int = 60) -> str:
    """Shorten text for a table cell."""
    if not text:
        return ""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def target_gap(actual: float | None, target: float | None) -> str:
    """Describe how far a figure is from its target, in plain words."""
    if actual is None or target is None:
        return ""
    difference = actual - target
    if abs(difference) < 1:
        return "on target"
    if difference > 0:
        return f"{minutes(difference)} over target"
    return f"{minutes(abs(difference))} under target"
