"""Personal Habit & Daily Life Tracker.

A modular personal-tracking application. Imports run strictly one way::

    ui  ->  services  ->  repositories  ->  models  ->  database
             |
             +------->  domain  (pure functions; imports none of the above)

Nothing below the ``ui`` package may import Streamlit, and nothing in
``domain`` may import SQLAlchemy. Those two rules are what let the same
business logic sit behind a FastAPI process later without being rewritten.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
