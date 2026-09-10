"""Exporting the user's data.

Everything the user has recorded belongs to them and must be portable. This
service produces the same set of tables in three formats, so "I want my data
out" is never blocked on a format nobody supports.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from app import __version__
from app.core.errors import DataExportError
from app.core.logging_config import get_logger
from app.database.base import Base, as_dict
from app.export.csv_exporter import rows_to_csv, tables_to_csv_zip
from app.export.excel_exporter import tables_to_excel
from app.export.json_exporter import backup_to_json, rows_to_json
from app.schemas.common import DateRange
from app.services.base import BaseService
from app.services.unit_of_work import UnitOfWork

logger = get_logger(__name__)

#: The tables a full backup contains, in dependency order so that an import
#: can replay them without tripping a foreign key.
BACKUP_TABLES: tuple[str, ...] = (
    "profile",
    "categories",
    "habits",
    "habit_logs",
    "tasks",
    "sleep_records",
    "activities",
    "time_entries",
    "goals",
    "goal_milestones",
    "weekly_goals",
    "journal_entries",
    "daily_logs",
    "body_measurements",
    "settings",
)

#: Datasets the user can export on their own, from the Settings page.
EXPORTABLE: tuple[str, ...] = (
    "tasks",
    "habits",
    "habit_logs",
    "sleep_records",
    "activities",
    "time_entries",
    "goals",
    "journal_entries",
)

#: An export larger than this is refused rather than silently truncated.
MAX_EXPORT_ROWS = 500_000


class ExportService(BaseService):
    """Producing CSV, JSON and Excel exports, and full backups."""

    def export_csv(self, dataset: str, period: DateRange | None = None) -> str:
        """Export one dataset as CSV text."""
        rows = self._collect(dataset, period)
        logger.info("Exported %d %s rows as CSV", len(rows), dataset)
        return rows_to_csv(rows)

    def export_json(self, dataset: str, period: DateRange | None = None) -> str:
        """Export one dataset as JSON text."""
        rows = self._collect(dataset, period)
        logger.info("Exported %d %s rows as JSON", len(rows), dataset)
        return rows_to_json(rows)

    def export_excel(self, datasets: Sequence[str], period: DateRange | None = None) -> bytes:
        """Export several datasets into one workbook."""
        tables = {name: self._collect(name, period) for name in datasets}
        logger.info("Exported %d datasets as Excel", len(tables))
        return tables_to_excel(tables)

    def export_csv_archive(self, datasets: Sequence[str], period: DateRange | None = None) -> bytes:
        """Export several datasets as a zip of CSV files."""
        tables = {name: self._collect(name, period) for name in datasets}
        return tables_to_csv_zip(tables)

    def full_backup(self) -> str:
        """Produce a complete JSON backup of everything.

        Carries the timezone the dates were recorded in, because restoring
        into a different one would otherwise shift every day boundary
        without anyone noticing.
        """
        with self.uow() as uow:
            tables = {name: self._collect_from(uow, name, None) for name in BACKUP_TABLES}
            timezone = uow.profiles.get_or_raise(self.user_id).timezone

        total = sum(len(rows) for rows in tables.values())
        logger.info("Full backup produced (%d rows across %d tables)", total, len(tables))
        return backup_to_json(
            tables,
            app_version=__version__,
            timezone=timezone,
            generated_at=self.clock.now(),
        )

    # -- internals ---------------------------------------------------------

    def _collect(self, dataset: str, period: DateRange | None) -> list[dict[str, Any]]:
        """Read one dataset, applying an optional date window."""
        with self.uow() as uow:
            return self._collect_from(uow, dataset, period)

    def _collect_from(
        self, uow: UnitOfWork, dataset: str, period: DateRange | None
    ) -> list[dict[str, Any]]:
        """Read one dataset inside an existing unit of work.

        Raises:
            DataExportError: If the dataset name is unknown, or the result
                would exceed :data:`MAX_EXPORT_ROWS`.
        """
        start: date | None = period.start if period else None
        end: date | None = period.end if period else None
        wide = DateRange(start=date(1970, 1, 1), end=date(2100, 1, 1))
        window = period or wide

        readers: dict[str, Callable[[], Sequence[Base]]] = {
            "profile": lambda: [uow.profiles.get_or_raise(self.user_id)],
            "categories": lambda: uow.categories.list_owned(limit=1000),
            "habits": lambda: uow.habits.list_all_habits(include_inactive=True),
            "habit_logs": lambda: uow.habits.logs_between(window.start, window.end),
            "tasks": lambda: uow.tasks.list_between(window.start, window.end),
            "sleep_records": lambda: uow.sleep.list_between(window.start, window.end),
            "activities": lambda: uow.activities.list_between(window.start, window.end),
            "time_entries": lambda: uow.time_entries.list_between(window.start, window.end),
            "goals": lambda: uow.goals.list_all_goals(),
            "goal_milestones": lambda: [
                milestone
                for goal in uow.goals.list_all_goals()
                for milestone in uow.goals.milestones_for(goal.id)
            ],
            "weekly_goals": lambda: uow.weekly_goals.list_between(window.start, window.end),
            "journal_entries": lambda: uow.journal.list_between(window.start, window.end),
            "daily_logs": lambda: uow.daily_logs.list_between(window.start, window.end),
            "body_measurements": lambda: uow.measurements.list_between(window.start, window.end),
            "settings": lambda: uow.settings.list_all(limit=500),
        }

        reader = readers.get(dataset)
        if reader is None:
            raise DataExportError(
                "Unknown dataset",
                details={"dataset": dataset},
                user_hint=f"{dataset!r} is not something this application can export.",
            )

        rows = reader()
        if len(rows) > MAX_EXPORT_ROWS:
            raise DataExportError(
                "Export too large",
                details={"dataset": dataset, "rows": len(rows)},
                user_hint=(
                    f"That would export {len(rows):,} rows. Narrow the date range and try again."
                ),
            )

        logger.debug("Collected %d rows from %s (%s to %s)", len(rows), dataset, start, end)
        return [as_dict(row) for row in rows]


__all__ = ["BACKUP_TABLES", "EXPORTABLE", "MAX_EXPORT_ROWS", "ExportService"]
