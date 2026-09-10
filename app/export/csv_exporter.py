"""CSV export."""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.errors import DataExportError

#: Excel opens a UTF-8 CSV as mojibake unless it starts with a BOM.
_BOM = "﻿"


def rows_to_csv(rows: Sequence[Mapping[str, Any]], *, columns: Sequence[str] | None = None) -> str:
    """Render rows as CSV text.

    Args:
        rows: The records. An empty sequence produces a header-only file
            when ``columns`` is given, and an empty string otherwise.
        columns: Column order. Defaults to the union of every row's keys,
            with the first row's order taking precedence, so a column that
            only some rows carry is never silently dropped.

    Returns:
        CSV text, BOM-prefixed so spreadsheet software reads UTF-8.
    """
    header = list(columns) if columns is not None else _infer_columns(rows)
    if not header:
        return ""

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _render(row.get(key)) for key in header})
    return _BOM + buffer.getvalue()


def tables_to_csv_zip(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> bytes:
    """Bundle several tables into one zip of CSV files.

    Args:
        tables: Table name to rows.

    Returns:
        Zip archive bytes.

    Raises:
        DataExportError: If the archive cannot be written.
    """
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, rows in tables.items():
                archive.writestr(f"{name}.csv", rows_to_csv(rows))
    except (OSError, zipfile.BadZipFile) as error:  # pragma: no cover - filesystem failure
        raise DataExportError(
            "Could not build the CSV archive", details={"cause": type(error).__name__}
        ) from error
    return buffer.getvalue()


def _infer_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return the union of every row's keys, first-seen order preserved."""
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    return list(seen)


def _render(value: Any) -> Any:
    """Flatten a value into something CSV can hold."""
    if value is None:
        return ""
    if isinstance(value, list | tuple):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return str(value)
    return value
