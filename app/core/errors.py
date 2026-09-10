"""Application exception hierarchy.

One base class means a caller can write a single ``except AppError`` and still
branch on the specific subclass when it wants to. Every error carries
structured ``details`` so the log gets the facts while the UI gets a sentence
a human can act on - see :meth:`AppError.user_message`.

Note:
    The import/export errors are named ``DataImportError`` and
    ``DataExportError`` rather than ``ImportError``/``ExportError``. Defining a
    class called ``ImportError`` would shadow the builtin inside every module
    that imports it, which turns an unrelated failed import into a confusing
    bug report.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every error this application raises deliberately.

    Attributes:
        message: Technical description, written for the log.
        details: Structured context (ids, field names, offending values).
        user_hint: Optional plain-language sentence shown in the UI instead of
            ``message``.
    """

    #: Fallback shown to the user when a subclass supplies no ``user_hint``.
    default_user_message = "Something went wrong. The details have been written to the log."

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        user_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.user_hint = user_hint

    def user_message(self) -> str:
        """Return a message safe to show a non-technical user."""
        return self.user_hint or self.default_user_message

    def __str__(self) -> str:
        """Return the message with its structured details appended."""
        if not self.details:
            return self.message
        rendered = ", ".join(f"{key}={value!r}" for key, value in sorted(self.details.items()))
        return f"{self.message} ({rendered})"


class ValidationError(AppError):
    """Input failed a business rule before it ever reached the database."""

    default_user_message = "That input is not valid."

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        value: Any = None,
        details: dict[str, Any] | None = None,
        user_hint: str | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details or {})
        if field is not None:
            merged["field"] = field
        if value is not None:
            merged["value"] = value
        super().__init__(message, details=merged, user_hint=user_hint or message)
        self.field = field
        self.value = value


class NotFoundError(AppError):
    """A record was requested by id or name and does not exist."""

    default_user_message = "That record could not be found."

    def __init__(
        self,
        entity: str,
        identifier: Any,
        *,
        user_hint: str | None = None,
    ) -> None:
        super().__init__(
            f"{entity} not found",
            details={"entity": entity, "identifier": identifier},
            user_hint=user_hint or f"No {entity.lower()} matching {identifier!r}.",
        )
        self.entity = entity
        self.identifier = identifier


class ConflictError(AppError):
    """The requested change collides with a record that already exists.

    Used for duplicate habit names, a second habit log for the same day, and
    overlapping time entries.
    """

    default_user_message = "That conflicts with something already recorded."

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        user_hint: str | None = None,
    ) -> None:
        super().__init__(message, details=details, user_hint=user_hint or message)


class DatabaseError(AppError):
    """The database refused an operation or could not be reached."""

    default_user_message = "The database could not complete that request. Please try again."


class ConfigurationError(AppError):
    """The application is misconfigured and cannot start correctly."""

    default_user_message = "The application is misconfigured. Check your .env file."


class DataImportError(AppError):
    """An import file was unreadable, malformed, or failed schema validation."""

    default_user_message = "That file could not be imported."


class DataExportError(AppError):
    """An export could not be produced."""

    default_user_message = "That export could not be produced."


class CommandError(AppError):
    """A command-line invocation was wrong in a way argparse cannot catch.

    A malformed ``--date``, a habit name that matches nothing, an amount
    the command needs but was not given. Argparse handles *shape*; this
    handles meaning.

    Attributes:
        hint: An optional second line suggesting what to type instead.
    """

    default_user_message = "That command could not be run."

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details, user_hint=message)
        self.hint = hint


__all__ = [
    "AppError",
    "CommandError",
    "ConfigurationError",
    "ConflictError",
    "DataExportError",
    "DataImportError",
    "DatabaseError",
    "NotFoundError",
    "ValidationError",
]
