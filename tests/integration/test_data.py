"""Export, import, backup, database constraints and migrations."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.bootstrap import Container
from app.config.settings import Settings
from app.core.errors import DatabaseError, DataExportError, DataImportError
from app.database.connection import Database, run_migrations
from app.export.csv_exporter import rows_to_csv, tables_to_csv_zip
from app.export.excel_exporter import tables_to_excel
from app.export.json_exporter import BACKUP_FORMAT_VERSION, rows_to_json
from app.models.habit import HabitLog
from app.models.sleep import SleepRecord
from app.schemas.common import DateRange
from app.schemas.journal import JournalInput
from app.services.export_service import EXPORTABLE
from tests.helpers import not_none

pytestmark = pytest.mark.integration


class TestExporters:
    def test_csv_of_nothing_is_empty(self):
        assert rows_to_csv([]) == ""

    def test_csv_has_a_bom_so_excel_reads_utf8(self):
        assert rows_to_csv([{"name": "café"}]).startswith("﻿")

    def test_csv_covers_columns_that_only_some_rows_have(self):
        output = rows_to_csv([{"a": 1}, {"a": 2, "b": 3}])
        assert "a,b" in output

    def test_csv_flattens_a_list(self):
        assert "x; y" in rows_to_csv([{"tags": ["x", "y"]}])

    def test_json_renders_dates(self):
        output = rows_to_json([{"day": date(2026, 9, 10)}])
        assert json.loads(output)[0]["day"] == "2026-09-10"

    def test_json_refuses_what_it_cannot_serialise(self):
        with pytest.raises(DataExportError):
            rows_to_json([{"thing": object()}])

    def test_a_csv_archive_holds_one_file_per_table(self):
        import io
        import zipfile

        archive = tables_to_csv_zip({"tasks": [{"a": 1}], "habits": [{"b": 2}]})
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            assert sorted(zipped.namelist()) == ["habits.csv", "tasks.csv"]

    def test_excel_produces_a_workbook(self):
        content = tables_to_excel({"tasks": [{"title": "x"}]})
        assert content[:2] == b"PK"

    def test_excel_handles_an_empty_table(self):
        assert tables_to_excel({"tasks": []})


class TestExportService:
    def test_every_advertised_dataset_exports(self, populated: Container):
        for dataset in EXPORTABLE:
            assert isinstance(populated.exports.export_csv(dataset), str)

    def test_an_unknown_dataset_is_refused(self, container: Container):
        with pytest.raises(DataExportError):
            container.exports.export_csv("nonsense")

    def test_a_date_range_narrows_the_export(self, populated: Container, today: date):
        wide = populated.exports.export_json("sleep_records")
        narrow = populated.exports.export_json("sleep_records", DateRange(start=today, end=today))
        assert len(json.loads(wide)) > len(json.loads(narrow))

    def test_the_backup_envelope_carries_its_metadata(self, populated: Container):
        payload = json.loads(populated.exports.full_backup())
        assert payload["format_version"] == BACKUP_FORMAT_VERSION
        assert payload["timezone"] == "Asia/Kolkata"
        assert payload["counts"]["sleep_records"] == 7

    def test_the_backup_covers_every_table(self, populated: Container):
        from app.services.export_service import BACKUP_TABLES

        payload = json.loads(populated.exports.full_backup())
        assert set(payload["tables"]) == set(BACKUP_TABLES)


class TestImportService:
    def test_a_csv_round_trip_parses_cleanly(self, populated: Container, today: date):
        populated.journal.save(JournalInput(entry_date=today, mood=8, reflection="Steady"))
        exported = populated.exports.export_csv("journal_entries")
        report = populated.imports.import_csv("journal_entries", exported)
        assert report.failed == 0
        assert not_none(populated.journal.get_for_date(today)).mood == 8

    def test_importing_habits_skips_names_that_already_exist(self, populated: Container):
        exported = populated.exports.export_json("habits")
        report = populated.imports.import_json("habits", exported)
        assert report.created == 0
        assert report.skipped >= 1

    def test_a_full_restore_reports_per_dataset(self, populated: Container):
        backup = populated.exports.full_backup()
        reports = populated.imports.restore_backup(backup)
        assert {report.dataset for report in reports} >= {"habits", "sleep_records"}

    def test_a_bad_dataset_name_is_refused(self, container: Container):
        with pytest.raises(DataImportError):
            container.imports.import_csv("nonsense", "a,b\n1,2\n")

    def test_malformed_json_is_refused_with_a_line_number(self, container: Container):
        with pytest.raises(DataImportError) as caught:
            container.imports.import_json("tasks", "{ not json")
        assert "line" in caught.value.user_message()

    def test_a_json_object_where_an_array_was_expected(self, container: Container):
        with pytest.raises(DataImportError):
            container.imports.import_json("tasks", '{"a": 1}')

    def test_a_file_that_is_not_a_backup(self, container: Container):
        with pytest.raises(DataImportError):
            container.imports.restore_backup('{"tables": 3}')

    def test_a_future_backup_format_is_refused(self, container: Container):
        payload = json.dumps({"format_version": 999, "tables": {}})
        with pytest.raises(DataImportError) as caught:
            container.imports.restore_backup(payload)
        assert "newer version" in caught.value.user_message()

    def test_an_oversized_file_is_refused(self, container: Container):
        oversized = b"x" * (container.settings.max_upload_bytes + 1)
        with pytest.raises(DataImportError) as caught:
            container.imports.import_csv("tasks", oversized)
        assert "MB" in caught.value.user_message()

    def test_invalid_bytes_are_refused(self, container: Container):
        with pytest.raises(DataImportError):
            container.imports.import_csv("tasks", b"\xff\xfe\x00bad")

    def test_bad_rows_are_reported_by_row_number(self, container: Container):
        csv_text = "entry_date,mood\n2026-09-10,8\nnot-a-date,5\n"
        report = container.imports.import_csv("journal_entries", csv_text)
        assert report.created == 1
        assert report.failed == 1
        assert report.errors[0].startswith("Row 3")

    def test_import_obeys_the_same_rules_as_the_forms(self, container: Container, today: date):
        future = (today + timedelta(days=5)).isoformat()
        report = container.imports.import_csv("journal_entries", f"entry_date,mood\n{future},8\n")
        assert report.failed == 1

    def test_importing_tasks_from_csv(self, container: Container, today: date):
        csv_text = f"title,due_date,priority\nWrite docs,{today.isoformat()},HIGH\n"
        report = container.imports.import_csv("tasks", csv_text)
        assert report.created == 1
        assert container.tasks.list_for_day(today)[0].title == "Write docs"

    def test_importing_sleep_from_csv(self, container: Container, today: date):
        csv_text = f"log_date,sleep_time,wake_time,quality\n{today.isoformat()},23:30,06:30,8\n"
        report = container.imports.import_csv("sleep_records", csv_text)
        assert report.created == 1
        assert not_none(container.sleep.get_for_date(today)).duration_minutes == pytest.approx(420)

    def test_iso_timestamps_are_accepted_where_a_clock_time_is_expected(
        self, container: Container, today: date
    ):
        csv_text = (
            "log_date,sleep_at,wake_at\n"
            f"{today.isoformat()},2026-09-09T23:30:00+00:00,2026-09-10T06:30:00+00:00\n"
        )
        report = container.imports.import_csv("sleep_records", csv_text)
        assert report.created == 1


class TestDatabaseIntegrity:
    def test_a_habit_cannot_be_logged_twice_for_one_day(self, container: Container, today: date):
        from app.models.enums import HabitType
        from app.schemas.habit import HabitCreate

        habit = container.habits.create(
            HabitCreate(name="Water", habit_type=HabitType.BOOLEAN, start_date=today)
        )
        with container.unit_of_work() as uow:
            uow.session.add(HabitLog(habit_id=habit.id, log_date=today, completed=True))
            uow.commit()

        with (
            pytest.raises(DatabaseError),
            container.unit_of_work() as uow,
        ):
            uow.session.add(HabitLog(habit_id=habit.id, log_date=today, completed=True))
            uow.commit()

    def test_an_impossible_sleep_duration_is_refused_by_the_database(
        self, container: Container, today: date
    ):
        with (
            pytest.raises(DatabaseError),
            container.unit_of_work() as uow,
        ):
            uow.session.add(
                SleepRecord(
                    user_id=container.user_id,
                    log_date=today,
                    sleep_at=container.clock.now(),
                    wake_at=container.clock.now() + timedelta(minutes=5),
                    duration_minutes=-10,
                )
            )
            uow.commit()

    def test_foreign_keys_are_enforced(self, container: Container):
        with container.database.engine.connect() as connection:
            enabled = connection.execute(text("PRAGMA foreign_keys")).scalar()
        assert enabled == 1

    def test_deleting_a_habit_cascades_to_its_logs(self, container: Container, today: date):
        from app.models.enums import HabitType
        from app.schemas.habit import HabitCreate, HabitLogInput

        habit = container.habits.create(
            HabitCreate(name="Water", habit_type=HabitType.BOOLEAN, start_date=today)
        )
        container.habits.log(HabitLogInput(habit_id=habit.id, log_date=today, checked=True))
        container.habits.delete(habit.id)

        with container.database.engine.connect() as connection:
            remaining = connection.execute(text("SELECT count(*) FROM habit_log")).scalar()
        assert remaining == 0

    def test_the_expected_indexes_exist(self, container: Container):
        with container.database.engine.connect() as connection:
            names = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='index'")
                )
            }
        for expected in (
            "ix_habit_log_habit_date",
            "ix_task_user_status_due",
            "ix_time_entry_user_date",
            "ix_sleep_record_user_date",
        ):
            assert expected in names

    def test_a_failed_write_leaves_nothing_behind(self, container: Container, today: date):
        """A rejected create must not leave a half-written row."""
        from app.core.errors import NotFoundError
        from app.schemas.task import TaskCreate

        with pytest.raises(NotFoundError):
            container.tasks.create(TaskCreate(title="Doomed", due_date=today, category_id=98765))
        assert container.tasks.list_for_day(today) == []


class TestMigrations:
    def test_the_migrations_build_the_same_schema_as_the_models(self, tmp_path: Path):
        from app.database.base import Base

        settings = Settings(
            database_url=f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}",
            log_dir=tmp_path / "logs",
        )
        migrated = Database(settings)
        run_migrations(migrated)

        with migrated.engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
        migrated.dispose()

        expected = set(Base.metadata.tables) | {"alembic_version"}
        assert expected == tables

    def test_running_migrations_does_not_disable_the_application_loggers(self, tmp_path: Path):
        """Alembic's ``fileConfig`` switches off every logger it does not name.

        Startup runs migrations, so with the default
        ``disable_existing_loggers=True`` every application log line after
        startup disappeared silently - the log file held the first
        migration message and nothing else.
        """
        import logging

        from app.core.logging_config import setup_logging

        settings = Settings(
            database_url=f"sqlite:///{(tmp_path / 'logging.db').as_posix()}",
            log_dir=tmp_path / "logs",
        )
        setup_logging(settings, force=True)
        instance = Database(settings)
        run_migrations(instance)
        instance.dispose()

        for name in (
            "habit_tracker",
            "habit_tracker.services.habit_service",
            "habit_tracker.cli.commands",
        ):
            assert not logging.getLogger(name).disabled, f"{name} was disabled"

    def test_migrating_twice_is_a_no_op(self, tmp_path: Path):
        settings = Settings(
            database_url=f"sqlite:///{(tmp_path / 'twice.db').as_posix()}",
            log_dir=tmp_path / "logs",
        )
        instance = Database(settings)
        run_migrations(instance)
        run_migrations(instance)
        assert instance.healthcheck()
        instance.dispose()


class TestBackupScript:
    def test_a_sqlite_copy_is_readable(self, container: Container, tmp_path: Path):
        from scripts.backup import copy_sqlite

        source = container.database.sqlite_path
        assert source is not None
        copied = copy_sqlite(source, tmp_path / "out")
        assert copied.exists()
        assert copied.stat().st_size > 0

    def test_pruning_keeps_the_newest(self, tmp_path: Path):
        from scripts.backup import prune

        folder = tmp_path / "backups"
        folder.mkdir()
        for index in range(5):
            (folder / f"file_{index}.json").write_text("{}", encoding="utf-8")
        removed = prune(folder, keep=2)
        assert removed == 3
        assert len(list(folder.glob("*.json"))) == 2
