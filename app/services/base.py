"""Shared service scaffolding."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from app.core.timeutils import Clock
from app.services.unit_of_work import UnitOfWork, UnitOfWorkFactory


class BaseService:
    """Common dependencies for every service.

    Services receive a unit-of-work factory and a clock rather than reaching
    for a global. That is what makes them testable: a test hands over an
    in-memory database and a frozen clock, and nothing in the service knows
    the difference.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self.clock = clock

    def uow(self) -> UnitOfWork:
        """Return a new unit of work."""
        return self._unit_of_work()

    @property
    def user_id(self) -> int:
        """The profile every operation is scoped to."""
        return self._unit_of_work.user_id

    @property
    def tz(self) -> ZoneInfo:
        """The user's timezone."""
        return self.clock.timezone

    def today(self) -> date:
        """The user's local today."""
        return self.clock.today()
