"""The notification abstraction.

No reminders are delivered yet. What exists is the seam: a protocol, a
value object, and an implementation that writes to the log. Adding email or
Telegram later means writing one class, not threading a new dependency
through the services - and crucially, nothing here imports Streamlit, so a
future scheduler can run reminders with no UI process at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class NotificationKind(StrEnum):
    """What a reminder is about."""

    WAKE_UP = "WAKE_UP"
    SLEEP = "SLEEP"
    HABIT = "HABIT"
    TASK_DEADLINE = "TASK_DEADLINE"
    STUDY = "STUDY"
    EXERCISE = "EXERCISE"
    WEEKLY_REVIEW = "WEEKLY_REVIEW"


@dataclass(frozen=True, slots=True)
class Notification:
    """One message waiting to be delivered.

    Attributes:
        kind: What it is about.
        title: Short headline.
        body: The message itself.
        due_at: When it should be delivered.
        context: Structured detail - ids, counts - never free user text.
    """

    kind: NotificationKind
    title: str
    body: str
    due_at: datetime | None = None
    context: dict[str, str | int | float] = field(default_factory=dict)


@runtime_checkable
class NotificationService(Protocol):
    """Anything that can deliver a notification.

    Deliberately narrow. A channel that needs configuration takes it in its
    own constructor; callers only ever see this one method.
    """

    def send(self, notification: Notification) -> bool:
        """Deliver one notification.

        Returns:
            Whether delivery succeeded. Implementations must not raise for
            an ordinary delivery failure - a reminder that fails to send is
            not a reason to fail the request that produced it.
        """
        ...


class NullNotificationService:
    """Discards everything. The default, and what the tests use."""

    def send(self, notification: Notification) -> bool:
        """Do nothing and report success."""
        return True
