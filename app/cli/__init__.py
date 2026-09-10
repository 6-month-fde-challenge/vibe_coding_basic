"""The command-line interface.

A second front end over the same services the Streamlit app uses. It
exists to prove the point the architecture makes: the presentation layer
is replaceable, because none of the business rules live in it.

    python main.py --help

Modules:
    parser:     the command grammar (argparse)
    commands:   one handler per verb, calling services
    formatters: terminal rendering, with an ASCII fallback
    __main__:   parsing, the try/except/finally, the exit code
"""

from app.cli.commands import COMMANDS, dispatch
from app.cli.parser import build_parser

__all__ = ["COMMANDS", "build_parser", "dispatch"]
