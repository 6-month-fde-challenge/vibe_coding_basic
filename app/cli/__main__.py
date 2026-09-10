"""The command-line entry point.

    python main.py today
    habits done "Read 20 pages" --value 24

This module owns exactly three things: parsing, the top-level
``try/except/finally``, and the process exit code. Everything else is a
command handler in :mod:`app.cli.commands`, which talks only to services.

Two details are load-bearing rather than decorative.

*Everything is inside the try*, including ``parse_args``. Argparse runs
type converters during parsing, so a converter that raised outside this
block would print a traceback before the handler could stop it. Argparse's
own ``--help`` and usage exits raise ``SystemExit``, which is a
``BaseException`` and therefore passes straight through the handlers -
while still running the ``finally``.

*The ``finally`` closes the database.* A CLI run holds an open SQLite
connection with WAL files beside it; exiting without disposing the pool
leaves ``-wal`` and ``-shm`` files behind, and the next command - or the
Streamlit app - can find the database locked. Closing it is guaranteed
here: on success, on a handled error, on a crash and on Ctrl-C alike.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from app.bootstrap import Container, build_container
from app.cli.commands import EXIT_USER_ERROR, dispatch
from app.cli.parser import build_parser
from app.core.errors import AppError, CommandError
from app.core.logging_config import get_logger, setup_logging

logger = get_logger(__name__)

#: Exit codes beyond the two in ``commands``. 130 is the conventional
#: "terminated by Ctrl-C"; 70 is an internal software fault.
EXIT_INTERRUPTED = 130
EXIT_INTERNAL = 70


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return a process exit code.

    Args:
        argv: Arguments to parse. Defaults to ``sys.argv[1:]``, and is
            passed explicitly by the tests.

    Returns:
        ``0`` on success, ``1`` for something the user can fix, ``70``
        for a bug, ``130`` for Ctrl-C.
    """
    container: Container | None = None
    command = "none"

    try:
        setup_logging()
        parser = build_parser()
        args = parser.parse_args(argv)

        if args.command is None:
            parser.print_help()
            return 0

        command = args.command
        container = build_container()
        return dispatch(container, args)

    except CommandError as error:
        # The user typed something this application cannot act on. Say
        # what, and where possible say what to type instead.
        logger.warning("Command %r rejected: %s", command, error)
        print(f"error: {error.user_message()}", file=sys.stderr)
        if error.hint:
            print(f"       {error.hint}", file=sys.stderr)
        return EXIT_USER_ERROR

    except AppError as error:
        # A business rule or the database refused. These carry their own
        # user-facing sentence; the technical detail goes to the log.
        logger.warning("Command %r failed: %s", command, error)
        print(f"error: {error.user_message()}", file=sys.stderr)
        return EXIT_USER_ERROR

    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return EXIT_INTERRUPTED

    except Exception:
        # Anything else is a bug. The traceback belongs in the log, not
        # on a user's terminal.
        logger.exception("Command %r crashed", command)
        print(
            "error: something went wrong. The details are in logs/habit_tracker.log.",
            file=sys.stderr,
        )
        return EXIT_INTERNAL

    finally:
        # Guaranteed cleanup, whichever way we left the block above -
        # including the SystemExit argparse raises for --help and usage.
        if container is not None:
            container.dispose()
        logger.info("Command %r finished", command)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
