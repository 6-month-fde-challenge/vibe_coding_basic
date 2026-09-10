"""A notification channel that writes to the application log.

Useful in development, and it proves the abstraction works without pulling
in an SMTP client or an HTTP dependency.
"""

from __future__ import annotations

from app.core.logging_config import get_logger
from app.notifications.base import Notification

logger = get_logger(__name__)


class ConsoleNotificationService:
    """Logs each notification at INFO."""

    def send(self, notification: Notification) -> bool:
        """Write the notification to the log.

        Only the kind and the title are logged; the body may quote a habit
        name the user would not want in a shared log file.
        """
        logger.info(
            "Notification [%s] %s (due %s)",
            notification.kind.value,
            notification.title,
            notification.due_at.isoformat() if notification.due_at else "now",
        )
        return True
