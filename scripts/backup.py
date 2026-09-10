"""Back up the database.

    python scripts/backup.py
    python scripts/backup.py --json-only --output backups/

Two artefacts, because they fail differently:

*A file copy* of the SQLite database, taken through SQLite's own backup API
so it is consistent even if something is mid-write. Restoring it is exact,
but it is only readable by this application.

*A JSON export*, which is portable, diffable, and readable in ten years by
something that has never heard of SQLAlchemy - but which is a re-import
rather than a byte-for-byte restore.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.bootstrap import build_container
from app.config.settings import PROJECT_ROOT
from app.core.logging_config import get_logger, setup_logging

logger = get_logger(__name__)

DEFAULT_OUTPUT = PROJECT_ROOT / "backups"


def timestamp() -> str:
    """Return a filename-safe UTC timestamp."""
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def copy_sqlite(source: Path, destination: Path) -> Path:
    """Copy a live SQLite database consistently.

    Uses ``sqlite3.Connection.backup`` rather than copying the file, which
    would capture a torn page if a write were in flight - and with WAL
    enabled would also miss whatever is still in the log.

    Args:
        source: The database file.
        destination: Directory to write into.

    Returns:
        The path written.
    """
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{source.stem}_{timestamp()}.db"

    with sqlite3.connect(source) as origin, sqlite3.connect(target) as copy:
        origin.backup(copy)

    logger.info("Database copied to %s", target)
    return target


def write_json(content: str, destination: Path) -> Path:
    """Write a JSON backup to a timestamped file."""
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"habit_tracker_backup_{timestamp()}.json"
    target.write_text(content, encoding="utf-8")
    logger.info("JSON backup written to %s", target)
    return target


def prune(destination: Path, keep: int) -> int:
    """Delete the oldest backups, keeping the newest ``keep`` of each kind.

    Returns:
        How many files were removed.
    """
    removed = 0
    for pattern in ("*.db", "*.json"):
        files = sorted(
            destination.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True
        )
        for stale in files[keep:]:
            stale.unlink()
            removed += 1
            logger.info("Pruned old backup %s", stale.name)
    return removed


def main() -> int:
    """Entry point.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(description="Back up the habit tracker database.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory.")
    parser.add_argument("--json-only", action="store_true", help="Skip the SQLite file copy.")
    parser.add_argument("--db-only", action="store_true", help="Skip the JSON export.")
    parser.add_argument(
        "--keep", type=int, default=10, help="How many backups of each kind to retain."
    )
    arguments = parser.parse_args()

    setup_logging()
    container = build_container()
    written: list[Path] = []

    if not arguments.json_only:
        source = container.database.sqlite_path
        if source is None:
            print("The configured database is not a SQLite file; skipping the file copy.")
        elif not source.exists():
            print(f"No database file at {source}. Nothing to copy.")
        else:
            written.append(copy_sqlite(source, arguments.output))

    if not arguments.db_only:
        written.append(write_json(container.exports.full_backup(), arguments.output))

    if arguments.keep > 0:
        pruned = prune(arguments.output, arguments.keep)
        if pruned:
            print(f"Pruned {pruned} old backup file(s).")

    if not written:
        print("Nothing was written.")
        return 1

    for path in written:
        size_kb = path.stat().st_size / 1024
        print(f"Wrote {path} ({size_kb:,.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
