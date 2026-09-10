"""The command-line interface, end to end.

These drive ``dispatch`` against a real temporary database and capture
stdout, so they test what a user actually sees - the exit code, the
message, and the state left behind.

``main()`` itself is tested separately for the parts only it owns: the
exception funnel and the guaranteed cleanup in its ``finally`` block.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from app.bootstrap import Container
from app.cli.commands import EXIT_OK, dispatch
from app.cli.formatters import ASCII_SYMBOLS, UNICODE_SYMBOLS, symbols, table, truncate
from app.cli.parser import build_parser, parse_day
from app.core.errors import CommandError

pytestmark = pytest.mark.integration


@pytest.fixture
def run(container: Container, capsys: pytest.CaptureFixture[str]):
    """Return a callable that runs one CLI invocation and captures output."""

    def _run(*argv: str) -> tuple[int, str, str]:
        args = build_parser().parse_args(argv)
        code = dispatch(container, args)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


class TestParser:
    def test_no_command_parses_to_none(self):
        assert build_parser().parse_args([]).command is None

    def test_the_habit_verbs_all_parse(self):
        parser = build_parser()
        for argv in (
            ["add", "Read"],
            ["list"],
            ["done", "Read"],
            ["undo", "Read"],
            ["stats", "Read"],
            ["remove", "Read"],
            ["today"],
            ["week"],
            ["sleep", "23:30", "06:30"],
            ["time", "Coding", "90"],
            ["task", "Write docs"],
            ["tasks"],
            ["complete", "1"],
        ):
            assert parser.parse_args(argv).command == argv[0]

    def test_an_unknown_command_exits_with_usage(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["frobnicate"])

    def test_an_iso_date(self):
        assert parse_day("2026-09-07") == date(2026, 9, 7)

    def test_the_friendly_date_words(self):
        today = date.today()  # noqa: DTZ011 - parse_day's own reference
        assert parse_day("today") == today
        assert parse_day("yesterday") == today - timedelta(days=1)
        assert parse_day("-3") == today - timedelta(days=3)

    def test_a_nonsense_date_is_refused_with_a_hint(self):
        with pytest.raises(CommandError) as caught:
            parse_day("next tuesday")
        assert caught.value.hint is not None
        assert "YYYY-MM-DD" in caught.value.hint

    def test_argparse_turns_a_bad_date_into_a_usage_error_not_a_traceback(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Parsing happens before the entry point can catch anything."""
        with pytest.raises(SystemExit) as caught:
            build_parser().parse_args(["done", "Read", "--date", "next tuesday"])
        assert caught.value.code == 2
        assert "not a date I understand" in capsys.readouterr().err

    def test_a_global_flag_works_on_either_side_of_the_subcommand(self):
        parser = build_parser()
        assert parser.parse_args(["--plain", "list"]).plain is True
        assert parser.parse_args(["list", "--plain"]).plain is True
        assert parser.parse_args(["list"]).plain is False


class TestFormatters:
    def test_a_table_aligns_its_columns(self):
        rendered = table(["a", "bbbb"], [["xxxx", "y"]])
        assert rendered.splitlines()[0].startswith("a     bbbb")

    def test_an_empty_table_renders_nothing(self):
        assert table(["a"], []) == ""

    def test_plain_mode_forces_ascii(self):
        assert symbols(plain=True) is ASCII_SYMBOLS

    def test_the_ascii_set_is_pure_ascii(self):
        """The fallback must survive a cp1252 or cp437 console."""
        for value in dataclasses.astuple(ASCII_SYMBOLS):
            value.encode("ascii")

    def test_the_unicode_set_is_not(self):
        assert UNICODE_SYMBOLS is not ASCII_SYMBOLS

    def test_truncate_fits_the_limit(self):
        assert len(truncate("a very long habit name indeed", 12)) == 12


class TestHabitCommands:
    def test_add_then_list(self, run):
        code, out, _ = run("add", "Meditate", "--type", "duration", "--target", "20")
        assert code == EXIT_OK
        assert "Meditate" in out

        code, out, _ = run("list", "--plain")
        assert code == EXIT_OK
        assert "Meditate" in out

    def test_list_on_an_empty_database_suggests_the_next_step(self, run):
        code, out, _ = run("list")
        assert code == EXIT_OK
        assert "habits add" in out

    def test_a_measured_habit_without_a_target_is_refused(self, run):
        with pytest.raises(CommandError) as caught:
            run("add", "Read", "--type", "count")
        assert "target" in caught.value.user_message()

    def test_a_time_habit_without_a_time_is_refused(self, run):
        with pytest.raises(CommandError):
            run("add", "Wake early", "--type", "time")

    def test_done_ticks_a_boolean_habit_and_reports_the_streak(self, run):
        run("add", "Meditate")
        code, out, _ = run("done", "Meditate")
        assert code == EXIT_OK
        assert "Streak: 1 days" in out

    def test_done_accepts_a_prefix(self, run):
        run("add", "Meditate")
        code, out, _ = run("done", "Med")
        assert code == EXIT_OK
        assert "Meditate" in out

    def test_an_exact_name_beats_a_prefix_collision(self, run):
        run("add", "Read")
        run("add", "Read papers")
        code, out, _ = run("done", "Read")
        assert code == EXIT_OK
        assert out.startswith("Read:")

    def test_an_ambiguous_prefix_lists_the_candidates(self, run):
        run("add", "Read papers")
        run("add", "Read books")
        with pytest.raises(CommandError) as caught:
            run("done", "Read ")
        assert "Read papers" in (caught.value.hint or "")

    def test_an_unknown_habit_lists_the_known_ones(self, run):
        run("add", "Meditate")
        with pytest.raises(CommandError) as caught:
            run("done", "Jogging")
        assert "Meditate" in (caught.value.hint or "")

    def test_a_measured_habit_needs_a_value(self, run):
        run("add", "Read", "--type", "count", "--target", "20")
        with pytest.raises(CommandError) as caught:
            run("done", "Read")
        assert "--value" in (caught.value.hint or "")

    def test_a_value_short_of_target_says_so(self, run):
        run("add", "Read", "--type", "count", "--target", "20", "--unit", "pages")
        code, out, _ = run("done", "Read", "--value", "5")
        assert code == EXIT_OK
        assert "short of target" in out

    def test_a_time_habit_logs_a_clock_time(self, run):
        run("add", "Wake early", "--type", "time", "--at", "06:30", "--before")
        code, out, _ = run("done", "Wake early", "--at", "06:15")
        assert code == EXIT_OK
        assert "done" in out

    def test_backdating_with_a_date_word(self, run, today: date):
        run("add", "Meditate", "--since", "-7")
        code, out, _ = run("done", "Meditate", "--date", "yesterday")
        assert code == EXIT_OK
        assert (today - timedelta(days=1)).isoformat() in out

    def test_backdating_before_the_start_date_names_the_flag_that_fixes_it(self, run):
        run("add", "Meditate")
        with pytest.raises(CommandError) as caught:
            run("done", "Meditate", "--date", "yesterday")
        assert "--since" in (caught.value.hint or "")

    def test_a_future_date_is_refused_by_the_service(self, run, today: date):
        from app.core.errors import ValidationError

        run("add", "Meditate")
        with pytest.raises(ValidationError):
            run("done", "Meditate", "--date", (today + timedelta(days=1)).isoformat())

    def test_undo_removes_the_log(self, run):
        run("add", "Meditate")
        run("done", "Meditate")
        code, out, _ = run("undo", "Meditate")
        assert code == EXIT_OK
        assert "removed" in out

    def test_undo_on_a_day_with_nothing_is_not_an_error(self, run):
        run("add", "Meditate")
        code, out, _ = run("undo", "Meditate")
        assert code == EXIT_OK
        assert "nothing logged" in out

    def test_stats_reports_the_streak(self, run, today: date):
        run("add", "Meditate", "--since", "-30")
        for offset in range(3):
            run("done", "Meditate", "--date", (today - timedelta(days=offset)).isoformat())
        code, out, _ = run("stats", "Meditate", "--plain")
        assert code == EXIT_OK
        assert "Current streak" in out
        assert "3 days" in out

    def test_archive_keeps_the_history(self, run):
        run("add", "Meditate")
        run("done", "Meditate")
        code, out, _ = run("remove", "Meditate", "--archive")
        assert code == EXIT_OK
        assert "archived" in out

    def test_remove_with_yes_deletes(self, run):
        run("add", "Meditate")
        code, out, _ = run("remove", "Meditate", "--yes")
        assert code == EXIT_OK
        assert "deleted" in out

    def test_a_weekday_habit_reads_its_days(self, run):
        code, _, _ = run("add", "Standup", "--frequency", "specific-days", "--days", "mon,wed,fri")
        assert code == EXIT_OK

    def test_a_bad_weekday_name_is_refused(self, run):
        with pytest.raises(CommandError) as caught:
            run("add", "Standup", "--frequency", "specific-days", "--days", "mon,funday")
        assert "weekday" in caught.value.user_message()


class TestDayCommands:
    def test_today_on_an_empty_database_offers_the_next_step(self, run):
        code, out, _ = run("today", "--plain")
        assert code == EXIT_OK
        assert "Nothing recorded yet" in out

    def test_today_reports_the_overview_and_the_score(self, run):
        run("add", "Meditate")
        run("done", "Meditate")
        run("sleep", "23:30", "06:30")
        code, out, _ = run("today", "--plain")
        assert code == EXIT_OK
        assert "Sleep" in out
        assert "7h" in out
        assert "Daily score" in out

    def test_the_score_breakdown_is_printed(self, run):
        run("add", "Meditate")
        run("done", "Meditate")
        _, out, _ = run("today", "--plain")
        assert "Habit consistency" in out

    def test_sleep_reports_the_duration_across_midnight(self, run):
        code, out, _ = run("sleep", "23:30", "06:30")
        assert code == EXIT_OK
        assert "7h" in out

    def test_a_malformed_sleep_time_is_refused(self, run):
        from app.core.errors import ValidationError

        with pytest.raises((CommandError, ValidationError)):
            run("sleep", "bedtime", "morning")

    def test_time_logs_against_a_category(self, run):
        code, out, _ = run("time", "Coding", "90")
        assert code == EXIT_OK
        assert "1h 30m" in out

    def test_an_unknown_category_lists_the_alternatives(self, run):
        with pytest.raises(CommandError) as caught:
            run("time", "Alchemy", "60")
        assert "Coding" in (caught.value.hint or "")

    def test_categories_lists_them(self, run):
        code, out, _ = run("categories", "--kind", "time")
        assert code == EXIT_OK
        assert "Coding" in out

    def test_week_assembles_on_an_empty_database(self, run):
        code, out, _ = run("week", "--plain")
        assert code == EXIT_OK
        assert "WEEK OF" in out


class TestTaskCommands:
    def test_add_list_and_complete(self, run):
        code, out, _ = run("task", "Write the README")
        assert code == EXIT_OK
        assert "#1" in out

        code, out, _ = run("tasks", "--plain")
        assert "Write the README" in out

        code, out, _ = run("complete", "1")
        assert code == EXIT_OK
        assert "Completed #1" in out

    def test_an_empty_day_says_so(self, run):
        code, out, _ = run("tasks")
        assert code == EXIT_OK
        assert "Nothing on the list" in out

    def test_completing_a_missing_task_is_reported(self, run):
        from app.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            run("complete", "999")


class TestMainEntryPoint:
    """The parts only ``main()`` owns: the funnel and the cleanup."""

    def test_no_arguments_prints_help_and_succeeds(self, capsys: pytest.CaptureFixture[str]):
        from app.cli.__main__ import main

        assert main([]) == 0
        assert "usage:" in capsys.readouterr().out

    def test_version(self, capsys: pytest.CaptureFixture[str]):
        from app.cli.__main__ import main

        with pytest.raises(SystemExit) as caught:
            main(["--version"])
        assert caught.value.code == 0

    def test_a_command_error_becomes_exit_one_and_a_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], container
    ):
        from app.cli import __main__ as entry

        monkeypatch.setattr(entry, "build_container", lambda: container)
        code = entry.main(["done", "Nothing at all"])
        assert code == 1
        captured = capsys.readouterr()
        assert "error:" in captured.err

    def test_an_unexpected_crash_becomes_exit_seventy_without_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], container
    ):
        from app.cli import __main__ as entry

        def explode(*_: object, **__: object) -> int:
            raise RuntimeError("boom")

        monkeypatch.setattr(entry, "build_container", lambda: container)
        monkeypatch.setattr(entry, "dispatch", explode)

        code = entry.main(["list"])
        assert code == entry.EXIT_INTERNAL
        captured = capsys.readouterr()
        assert "boom" not in captured.err
        assert "logs/habit_tracker.log" in captured.err

    def test_ctrl_c_becomes_exit_one_hundred_and_thirty(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], container
    ):
        from app.cli import __main__ as entry

        def interrupt(*_: object, **__: object) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr(entry, "build_container", lambda: container)
        monkeypatch.setattr(entry, "dispatch", interrupt)

        assert entry.main(["list"]) == entry.EXIT_INTERRUPTED
        assert "Cancelled" in capsys.readouterr().err

    def test_the_finally_block_disposes_the_container_even_on_a_crash(
        self, monkeypatch: pytest.MonkeyPatch, container
    ):
        """The point of the ``finally``: the connection pool is released."""
        from app.cli import __main__ as entry

        disposed: list[bool] = []
        monkeypatch.setattr(container.database, "dispose", lambda: disposed.append(True))
        monkeypatch.setattr(entry, "build_container", lambda: container)

        def explode(*_: object, **__: object) -> int:
            raise RuntimeError("boom")

        monkeypatch.setattr(entry, "dispatch", explode)

        entry.main(["list"])
        assert disposed == [True]

    def test_the_finally_block_runs_on_the_success_path_too(
        self, monkeypatch: pytest.MonkeyPatch, container
    ):
        from app.cli import __main__ as entry

        disposed: list[bool] = []
        monkeypatch.setattr(container.database, "dispose", lambda: disposed.append(True))
        monkeypatch.setattr(entry, "build_container", lambda: container)

        assert entry.main(["list"]) == 0
        assert disposed == [True]
