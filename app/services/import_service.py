"""Importing data back in.

Imported files are untrusted input. Every row goes through the same
validated schema and the same service the UI uses, so an import cannot
create a record the application would have refused to create by hand. The
file itself is size-capped and its structure checked before a single row is
read.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any

from app.config.settings import Settings, get_settings
from app.core.errors import AppError, DataImportError
from app.core.logging_config import get_logger
from app.core.timeutils import Clock
from app.export.json_exporter import BACKUP_FORMAT_VERSION
from app.schemas.activity import ActivityInput, TimeEntryInput
from app.schemas.habit import HabitCreate, HabitLogInput
from app.schemas.health import BodyMeasurementInput
from app.schemas.journal import JournalInput
from app.schemas.sleep import SleepInput
from app.schemas.task import TaskCreate
from app.services.activity_service import ActivityService
from app.services.base import BaseService
from app.services.habit_service import HabitService
from app.services.health_service import HealthService
from app.services.journal_service import JournalService
from app.services.sleep_service import SleepService
from app.services.task_service import TaskService
from app.services.time_tracking_service import TimeTrackingService
from app.services.unit_of_work import UnitOfWorkFactory

logger = get_logger(__name__)

#: Refuse a file with more rows than this before parsing it row by row.
MAX_IMPORT_ROWS = 100_000
#: Stop after this many bad rows - a file that is wrong in ten thousand
#: places is the wrong file, and reporting every error helps nobody.
MAX_REPORTED_ERRORS = 25

#: Datasets the importer accepts.
IMPORTABLE: tuple[str, ...] = (
    "habits",
    "habit_logs",
    "tasks",
    "sleep_records",
    "activities",
    "time_entries",
    "journal_entries",
    "body_measurements",
)


@dataclass(slots=True)
class ImportReport:
    """What an import did.

    Attributes:
        dataset: Which dataset was imported.
        created: Rows that produced a new record.
        skipped: Rows deliberately ignored, such as duplicates.
        failed: Rows rejected by validation.
        errors: Up to :data:`MAX_REPORTED_ERRORS` messages, each naming its
            row number so the user can find it in the file.
    """

    dataset: str
    created: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Rows considered."""
        return self.created + self.skipped + self.failed

    @property
    def ok(self) -> bool:
        """Whether every row was accepted."""
        return self.failed == 0

    def note_error(self, row_number: int, message: str) -> None:
        """Record a rejected row."""
        self.failed += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(f"Row {row_number}: {message}")


class ImportService(BaseService):
    """Reading CSV and JSON back into the database."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        *,
        tasks: TaskService,
        habits: HabitService,
        sleep: SleepService,
        activities: ActivityService,
        time_tracking: TimeTrackingService,
        journal: JournalService,
        health: HealthService,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(unit_of_work, clock)
        self.tasks = tasks
        self.habits = habits
        self.sleep = sleep
        self.activities = activities
        self.time_tracking = time_tracking
        self.journal = journal
        self.health = health
        self.settings = settings or get_settings()

    # -- entry points ------------------------------------------------------

    def import_csv(self, dataset: str, content: bytes | str) -> ImportReport:
        """Import one dataset from CSV.

        Raises:
            DataImportError: If the dataset is unknown, the file is too
                large, or it is not readable as CSV.
        """
        self._check_dataset(dataset)
        text = self._decode(content)
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except csv.Error as error:
            raise DataImportError(
                "Could not read the CSV file",
                details={"cause": str(error)},
                user_hint="The file does not look like valid CSV.",
            ) from error
        return self._ingest(dataset, rows)

    def import_json(self, dataset: str, content: bytes | str) -> ImportReport:
        """Import one dataset from a JSON array."""
        self._check_dataset(dataset)
        payload = self._parse_json(self._decode(content))
        if not isinstance(payload, list):
            raise DataImportError(
                "Expected a JSON array",
                user_hint="This importer expects a list of records.",
            )
        return self._ingest(dataset, payload)

    def restore_backup(self, content: bytes | str) -> list[ImportReport]:
        """Restore a full backup produced by the export service.

        Records already present are skipped rather than duplicated, so a
        restore over a live database tops it up instead of doubling it.

        Raises:
            DataImportError: If the envelope is missing, its format version
                is newer than this build understands, or it carries no
                recognisable tables.
        """
        payload = self._parse_json(self._decode(content))
        if not isinstance(payload, dict) or "tables" not in payload:
            raise DataImportError(
                "This is not a backup file",
                user_hint="Choose a JSON backup produced by this application.",
            )

        version = payload.get("format_version")
        if not isinstance(version, int) or version > BACKUP_FORMAT_VERSION:
            raise DataImportError(
                "Unsupported backup format",
                details={"format_version": version},
                user_hint=("This backup was written by a newer version of the application."),
            )

        tables = payload["tables"]
        if not isinstance(tables, dict):
            raise DataImportError("Backup tables are malformed")

        source_tz = payload.get("timezone")
        if source_tz and source_tz != self.tz.key:
            logger.warning(
                "Restoring a backup recorded in %s into a profile set to %s",
                source_tz,
                self.tz.key,
            )

        reports: list[ImportReport] = []
        for dataset in IMPORTABLE:
            rows = tables.get(dataset)
            if isinstance(rows, list) and rows:
                reports.append(self._ingest(dataset, rows))

        logger.info(
            "Backup restored: %d rows created across %d datasets",
            sum(report.created for report in reports),
            len(reports),
        )
        return reports

    # -- ingestion ---------------------------------------------------------

    def _ingest(self, dataset: str, rows: Sequence[Mapping[str, Any]]) -> ImportReport:
        """Validate and apply every row of one dataset."""
        if len(rows) > MAX_IMPORT_ROWS:
            raise DataImportError(
                "File has too many rows",
                details={"rows": len(rows)},
                user_hint=f"This importer accepts up to {MAX_IMPORT_ROWS:,} rows at a time.",
            )

        handler = self._handlers()[dataset]
        report = ImportReport(dataset=dataset)

        for offset, row in enumerate(rows, start=2):  # row 1 is the header
            try:
                created = handler(row)
            except AppError as error:
                report.note_error(offset, error.user_message())
            except (ValueError, TypeError, KeyError) as error:
                report.note_error(offset, str(error))
            else:
                if created:
                    report.created += 1
                else:
                    report.skipped += 1

        logger.info(
            "Imported %s: %d created, %d skipped, %d failed",
            dataset,
            report.created,
            report.skipped,
            report.failed,
        )
        return report

    def _handlers(self) -> dict[str, Callable[[Mapping[str, Any]], bool]]:
        """Return the row handler for each importable dataset."""
        return {
            "habits": self._import_habit,
            "habit_logs": self._import_habit_log,
            "tasks": self._import_task,
            "sleep_records": self._import_sleep,
            "activities": self._import_activity,
            "time_entries": self._import_time_entry,
            "journal_entries": self._import_journal,
            "body_measurements": self._import_measurement,
        }

    # -- per-dataset handlers ---------------------------------------------

    def _import_habit(self, row: Mapping[str, Any]) -> bool:
        """Create a habit, skipping one whose name already exists."""
        name = _require_str(row, "name")
        existing = {habit.name for habit in self.habits.list_habits(active_only=False)}
        if name in existing:
            return False
        self.habits.create(
            HabitCreate.model_validate(
                {key: value for key, value in row.items() if key in HabitCreate.model_fields}
            )
        )
        return True

    def _import_habit_log(self, row: Mapping[str, Any]) -> bool:
        """Log a habit day, resolving the habit by name or id."""
        habit_id = _optional_int(row, "habit_id")
        if habit_id is None:
            name = _require_str(row, "habit_name")
            match = next(
                (
                    habit
                    for habit in self.habits.list_habits(active_only=False)
                    if habit.name == name
                ),
                None,
            )
            if match is None:
                msg = f"No habit named {name!r}"
                raise ValueError(msg)
            habit_id = match.id

        self.habits.log(
            HabitLogInput(
                habit_id=habit_id,
                log_date=_require_date(row, "log_date"),
                value=_optional_float(row, "value"),
                value_time=_optional_time(row, "value_time"),
                checked=_as_bool(row.get("completed", row.get("checked"))),
                is_rest_day=_as_bool(row.get("is_rest_day")),
                notes=_optional_str(row, "notes"),
            )
        )
        return True

    def _import_task(self, row: Mapping[str, Any]) -> bool:
        """Create a task."""
        self.tasks.create(
            TaskCreate.model_validate(
                {
                    "title": _require_str(row, "title"),
                    "description": _optional_str(row, "description"),
                    "due_date": _optional_date(row, "due_date"),
                    "due_time": _optional_time(row, "due_time"),
                    "estimated_minutes": _optional_int(row, "estimated_minutes"),
                    "notes": _optional_str(row, "notes"),
                    **({"priority": row["priority"]} if row.get("priority") else {}),
                }
            )
        )
        return True

    def _import_sleep(self, row: Mapping[str, Any]) -> bool:
        """Record a night."""
        self.sleep.record(
            SleepInput(
                log_date=_require_date(row, "log_date"),
                sleep_time=_require_time(row, "sleep_time", fallback="sleep_at"),
                wake_time=_require_time(row, "wake_time", fallback="wake_at"),
                bedtime=_optional_time(row, "bedtime"),
                quality=_optional_int(row, "quality"),
                interruptions=_optional_int(row, "interruptions") or 0,
                notes=_optional_str(row, "notes"),
            )
        )
        return True

    def _import_activity(self, row: Mapping[str, Any]) -> bool:
        """Log an activity."""
        category_id = _optional_int(row, "category_id")
        if category_id is None:
            return False
        self.activities.log(
            ActivityInput(
                log_date=_require_date(row, "log_date"),
                category_id=category_id,
                duration_minutes=_optional_float(row, "duration_minutes"),
                notes=_optional_str(row, "notes"),
                **({"intensity": row["intensity"]} if row.get("intensity") else {}),
            )
        )
        return True

    def _import_time_entry(self, row: Mapping[str, Any]) -> bool:
        """Log a block of time."""
        category_id = _optional_int(row, "category_id")
        if category_id is None:
            return False
        self.time_tracking.log(
            TimeEntryInput(
                log_date=_require_date(row, "log_date"),
                category_id=category_id,
                duration_minutes=_optional_float(row, "duration_minutes"),
                description=_optional_str(row, "description"),
            )
        )
        return True

    def _import_journal(self, row: Mapping[str, Any]) -> bool:
        """Save a journal entry."""
        self.journal.save(
            JournalInput(
                entry_date=_require_date(row, "entry_date"),
                mood=_optional_int(row, "mood"),
                energy=_optional_int(row, "energy"),
                stress=_optional_int(row, "stress"),
                motivation=_optional_int(row, "motivation"),
                focus=_optional_int(row, "focus"),
                reflection=_optional_str(row, "reflection"),
                accomplishments=_optional_str(row, "accomplishments"),
                challenges=_optional_str(row, "challenges"),
                gratitude=_optional_str(row, "gratitude"),
                notes=_optional_str(row, "notes"),
            )
        )
        return True

    def _import_measurement(self, row: Mapping[str, Any]) -> bool:
        """Record a weigh-in."""
        weight = _optional_float(row, "weight_kg")
        if weight is None:
            msg = "weight_kg is required"
            raise ValueError(msg)
        self.health.record_measurement(
            BodyMeasurementInput(
                measured_on=_require_date(row, "measured_on"),
                weight_kg=weight,
                body_fat_percent=_optional_float(row, "body_fat_percent"),
                waist_cm=_optional_float(row, "waist_cm"),
                notes=_optional_str(row, "notes"),
            )
        )
        return True

    # -- file handling -----------------------------------------------------

    def _check_dataset(self, dataset: str) -> None:
        """Reject a dataset this importer does not handle."""
        if dataset not in IMPORTABLE:
            raise DataImportError(
                "Unknown dataset",
                details={"dataset": dataset},
                user_hint=f"{dataset!r} cannot be imported. Choose one of: "
                + ", ".join(IMPORTABLE),
            )

    def _decode(self, content: bytes | str) -> str:
        """Size-check and decode an uploaded file.

        Raises:
            DataImportError: If the file exceeds the configured cap or is
                not valid UTF-8.
        """
        raw = content.encode("utf-8") if isinstance(content, str) else content
        if len(raw) > self.settings.max_upload_bytes:
            raise DataImportError(
                "File too large",
                details={"bytes": len(raw)},
                user_hint=f"Uploads are limited to {self.settings.max_upload_mb} MB.",
            )
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise DataImportError(
                "File is not valid UTF-8 text",
                details={"cause": str(error)},
                user_hint="Save the file as UTF-8 and try again.",
            ) from error

    def _parse_json(self, text: str) -> Any:
        """Parse JSON, translating the parser's error into a usable one."""
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise DataImportError(
                "Could not read the JSON file",
                details={"line": error.lineno, "column": error.colno},
                user_hint=f"The file is not valid JSON (line {error.lineno}).",
            ) from error


# --------------------------------------------------------------------------
# Row coercion helpers
#
# CSV gives everything back as a string, JSON gives back native types, and a
# hand-edited file gives back whatever the user typed. These normalise all
# three into the types the schemas expect, and raise a message naming the
# field when they cannot.
# --------------------------------------------------------------------------


def _optional_str(row: Mapping[str, Any], key: str) -> str | None:
    """Return a trimmed string, or ``None`` for a blank."""
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_str(row: Mapping[str, Any], key: str) -> str:
    """Return a required string field."""
    value = _optional_str(row, key)
    if not value:
        msg = f"{key} is required"
        raise ValueError(msg)
    return value


def _optional_int(row: Mapping[str, Any], key: str) -> int | None:
    """Return an integer field, or ``None``."""
    value = _optional_str(row, key)
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError as error:
        msg = f"{key} is not a number"
        raise ValueError(msg) from error


def _optional_float(row: Mapping[str, Any], key: str) -> float | None:
    """Return a float field, or ``None``."""
    value = _optional_str(row, key)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as error:
        msg = f"{key} is not a number"
        raise ValueError(msg) from error


def _optional_date(row: Mapping[str, Any], key: str) -> date | None:
    """Return an ISO date field, or ``None``."""
    value = _optional_str(row, key)
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as error:
        msg = f"{key} is not an ISO date (YYYY-MM-DD)"
        raise ValueError(msg) from error


def _require_date(row: Mapping[str, Any], key: str) -> date:
    """Return a required ISO date field."""
    value = _optional_date(row, key)
    if value is None:
        msg = f"{key} is required"
        raise ValueError(msg)
    return value


def _optional_time(row: Mapping[str, Any], key: str) -> time | None:
    """Return a clock time, accepting ``HH:MM`` or a full ISO timestamp."""
    value = _optional_str(row, key)
    if value is None:
        return None
    candidate = value.split("T")[-1] if "T" in value else value
    candidate = candidate.split("+")[0].split("Z")[0]
    try:
        return time.fromisoformat(candidate)
    except ValueError as error:
        msg = f"{key} is not a time (HH:MM)"
        raise ValueError(msg) from error


def _require_time(row: Mapping[str, Any], key: str, *, fallback: str | None = None) -> time:
    """Return a required clock time, trying a fallback column."""
    value = _optional_time(row, key)
    if value is None and fallback:
        value = _optional_time(row, fallback)
    if value is None:
        msg = f"{key} is required"
        raise ValueError(msg)
    return value


def _as_bool(value: Any) -> bool:
    """Interpret the many spellings of yes."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "done", "completed"}


__all__ = ["IMPORTABLE", "MAX_IMPORT_ROWS", "ImportReport", "ImportService"]
