"""JSON export."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from typing import Any

from app.core.errors import DataExportError

#: Bumped when the backup layout changes, so an importer can refuse a file
#: it does not understand instead of half-reading it.
BACKUP_FORMAT_VERSION = 1


def _default(value: Any) -> str:
    """Serialise the types ``json`` does not handle."""
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, set | frozenset):
        return str(sorted(value))
    raise TypeError(f"Cannot serialise {type(value).__name__} to JSON")


def rows_to_json(rows: Sequence[Mapping[str, Any]], *, indent: int = 2) -> str:
    """Render rows as a JSON array.

    Raises:
        DataExportError: If a value cannot be serialised.
    """
    try:
        return json.dumps(list(rows), default=_default, indent=indent, ensure_ascii=False)
    except TypeError as error:
        raise DataExportError(
            "Could not serialise the data to JSON", details={"cause": str(error)}
        ) from error


def backup_to_json(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    app_version: str,
    timezone: str,
    generated_at: datetime | None = None,
) -> str:
    """Render a full backup, with the metadata an import needs.

    The envelope carries the format version, the app version and the
    timezone the dates were recorded in - without that last one, a backup
    restored in another timezone silently shifts every day boundary.

    Args:
        tables: Table name to rows.
        app_version: The application version that produced the file.
        timezone: IANA timezone the local dates belong to.
        generated_at: Timestamp, defaulting to now.

    Returns:
        Pretty-printed JSON text.
    """
    envelope = {
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": app_version,
        "timezone": timezone,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "tables": {name: list(rows) for name, rows in tables.items()},
        "counts": {name: len(rows) for name, rows in tables.items()},
    }
    try:
        return json.dumps(envelope, default=_default, indent=2, ensure_ascii=False)
    except TypeError as error:
        raise DataExportError(
            "Could not serialise the backup", details={"cause": str(error)}
        ) from error
