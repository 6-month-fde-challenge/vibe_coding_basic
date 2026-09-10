"""Command-line entry point for the daily habit tracker.

    python main.py add "Read 20 pages" --type count --target 20 --unit pages
    python main.py done "Read 20 pages" --value 24
    python main.py list
    python main.py stats "Read 20 pages"
    python main.py today

Deliberately three lines of its own: this file exists so the tool can be
run straight from a clone with no install step. The implementation lives
in the ``app.cli`` package, and ``pip install -e .`` also puts it on the
path as ``habits``.
"""

from __future__ import annotations

import sys

from app.cli.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
