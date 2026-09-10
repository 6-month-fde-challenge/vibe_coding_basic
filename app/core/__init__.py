"""Cross-cutting concerns: errors, logging and time handling.

Nothing in this package may import from ``app.models``, ``app.repositories``,
``app.services`` or ``app.ui`` - it sits underneath all of them.
"""
