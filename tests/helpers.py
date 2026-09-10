"""Small helpers shared by the test modules."""

from __future__ import annotations


def not_none[T](value: T | None) -> T:
    """Assert a value is present and return it, narrowed.

    Reads better than scattering ``assert x is not None`` before every
    attribute access, and keeps the type checker happy about the same
    thing the assertion is already checking.
    """
    assert value is not None
    return value
