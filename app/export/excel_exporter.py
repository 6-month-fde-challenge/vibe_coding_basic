"""Excel export.

``openpyxl`` is imported lazily. It is the heaviest dependency in the
project and most sessions never press the Excel button.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from typing import Any

from app.core.errors import DataExportError

#: Excel refuses sheet names longer than this, or containing these.
_MAX_SHEET_NAME = 31
_ILLEGAL_SHEET_CHARS = set(r"[]:*?/\'")


def _sheet_name(name: str, used: set[str]) -> str:
    """Return a legal, unique worksheet name."""
    cleaned = "".join("_" if char in _ILLEGAL_SHEET_CHARS else char for char in name)
    cleaned = cleaned[:_MAX_SHEET_NAME] or "Sheet"
    candidate = cleaned
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = cleaned[: _MAX_SHEET_NAME - len(tail)] + tail
        suffix += 1
    used.add(candidate)
    return candidate


def _cell(value: Any) -> Any:
    """Coerce a value into something a worksheet cell can hold."""
    if value is None:
        return None
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return str(value)
    return value


def tables_to_excel(tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> bytes:
    """Write several tables into one workbook, a sheet per table.

    Args:
        tables: Table name to rows.

    Returns:
        ``.xlsx`` bytes.

    Raises:
        DataExportError: If ``openpyxl`` is not installed, or the workbook
            cannot be written.
    """
    try:
        from openpyxl import Workbook
    except ImportError as error:
        raise DataExportError(
            "Excel export needs the openpyxl package",
            details={"cause": str(error)},
            user_hint="Install openpyxl, or export as CSV instead.",
        ) from error

    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()

    for name, rows in tables.items():
        sheet = workbook.create_sheet(_sheet_name(name, used))
        if not rows:
            sheet.append(["(no records)"])
            continue

        columns: dict[str, None] = {}
        for row in rows:
            for key in row:
                columns.setdefault(key, None)
        header = list(columns)

        sheet.append(header)
        for row in rows:
            sheet.append([_cell(row.get(key)) for key in header])
        sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    try:
        workbook.save(buffer)
    except OSError as error:  # pragma: no cover - filesystem failure
        raise DataExportError(
            "Could not write the workbook", details={"cause": type(error).__name__}
        ) from error
    return buffer.getvalue()
