"""Logging setup for the whole application.

A single named logger (``habit_tracker``) with one child per module, rather
than :func:`logging.basicConfig`. ``basicConfig`` attaches handlers to the
*root* logger, which means Streamlit's own chatter - and every library's -
lands in the application log file too.

Privacy: journal text, reflections and notes are user-private. Log record
*counts* and ids, never free text. :func:`safe_preview` exists for the rare
case where a fragment genuinely helps diagnosis.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Final

from app.config.settings import Settings, get_settings

#: Root of the application's logger tree.
LOGGER_NAME: Final = "habit_tracker"

_LOG_FORMAT: Final = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
)
_DATE_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES: Final = 2 * 1024 * 1024
_BACKUP_COUNT: Final = 5

#: Marker attribute set on the logger once handlers are attached. Kept on the
#: logger object itself rather than in a module global so that a reloaded
#: module (Streamlit does reload) cannot lose track of handlers it already
#: attached and start duplicating every line.
_CONFIGURED_FLAG: Final = "_habit_tracker_configured"


def setup_logging(settings: Settings | None = None, *, force: bool = False) -> logging.Logger:
    """Configure the application logger and return it.

    Idempotent: Streamlit re-runs the script on every interaction, and
    attaching a second file handler each time would multiply every log line.

    Args:
        settings: Configuration to read the level and log directory from.
        force: Rebuild the handlers even if logging was already configured.

    Returns:
        The configured ``habit_tracker`` logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, _CONFIGURED_FLAG, False) and not force:
        return logger

    settings = settings or get_settings()
    log_dir: Path = settings.resolved_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "habit_tracker.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # The console is the developer's channel; the file is the audit trail.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)

    logger.setLevel(settings.log_level.value)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Application records must not also be re-emitted by the root logger.
    logger.propagate = False

    setattr(logger, _CONFIGURED_FLAG, True)
    logger.debug("Logging configured", extra={"log_dir": str(log_dir)})
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child of the application logger.

    Args:
        name: Usually ``__name__``. A leading ``app.`` is stripped so the log
            reads ``habit_tracker.services.task_service`` rather than
            ``habit_tracker.app.services.task_service``.
    """
    suffix = name.removeprefix("app.")
    if not suffix or suffix == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}")


def safe_preview(text: str | None, limit: int = 24) -> str:
    """Return a truncated, quoted preview of user text for a log record.

    Never log a whole journal entry. This exists so that when a preview is
    genuinely required for diagnosis there is one obvious, bounded way to do
    it.

    Args:
        text: The user text, possibly ``None``.
        limit: Maximum number of characters retained.
    """
    if not text:
        return "<empty>"
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return f"{collapsed!r}"
    return f"{collapsed[:limit]!r}... ({len(collapsed)} chars)"
