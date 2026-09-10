"""Repository base classes.

A repository owns *persistence*, not business rules. It knows how to select,
insert and delete rows efficiently; it does not know what a streak is.

Two bases:

``BaseRepository``
    For the handful of tables that are not owned by a profile.

``UserScopedRepository``
    For everything else. It carries the ``user_id`` and applies it to every
    query, so a forgotten filter cannot leak another profile's rows once
    multi-user support is added.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.database.base import Base
from app.schemas.common import Pagination


class BaseRepository[ModelT: Base]:
    """Persistence for one table.

    Subclasses set :attr:`model`. The session is injected rather than
    created, because transaction boundaries belong to the caller - see
    :class:`~app.services.unit_of_work.UnitOfWork`.
    """

    model: ClassVar[type[Any]]

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- reads -------------------------------------------------------------

    def get(self, entity_id: int) -> ModelT | None:
        """Return one row by primary key, or ``None``."""
        return self.session.get(self.model, entity_id)

    def get_or_raise(self, entity_id: int) -> ModelT:
        """Return one row by primary key.

        Raises:
            NotFoundError: If no such row exists.
        """
        found = self.get(entity_id)
        if found is None:
            raise NotFoundError(self.model.__name__, entity_id)
        return found

    def list_all(self, *, limit: int | None = None) -> list[ModelT]:
        """Return every row, optionally capped.

        Only safe for the small configuration tables. Anything that grows
        with use is read through a filtered, paginated method instead.
        """
        statement: Select[tuple[ModelT]] = select(self.model)
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))

    def count_where(self, *criteria: Any) -> int:
        """Count rows matching the criteria, without fetching them."""
        statement = select(func.count()).select_from(self.model)
        if criteria:
            statement = statement.where(*criteria)
        return int(self.session.scalar(statement) or 0)

    def paginate(
        self,
        statement: Select[tuple[ModelT]],
        pagination: Pagination,
    ) -> tuple[list[ModelT], int]:
        """Run a statement as one bounded page and return the total.

        The count is issued as a separate ``SELECT count(*)`` over the same
        criteria rather than by fetching everything and measuring it, which
        is the whole point of paginating.

        Returns:
            The page's rows, and the total number of matching rows.
        """
        count_statement = select(func.count()).select_from(statement.subquery())
        total = int(self.session.scalar(count_statement) or 0)
        page = statement.limit(pagination.limit).offset(pagination.offset)
        return list(self.session.scalars(page)), total

    # -- writes ------------------------------------------------------------

    def add(self, instance: ModelT) -> ModelT:
        """Stage a new row and flush so its primary key is populated."""
        self.session.add(instance)
        self.session.flush()
        return instance

    def add_all(self, instances: Sequence[ModelT]) -> list[ModelT]:
        """Stage many rows in one flush."""
        self.session.add_all(instances)
        self.session.flush()
        return list(instances)

    def delete(self, instance: ModelT) -> None:
        """Delete a row."""
        self.session.delete(instance)
        self.session.flush()

    def flush(self) -> None:
        """Send pending changes to the database without committing."""
        self.session.flush()


class UserScopedRepository[ModelT: Base](BaseRepository[ModelT]):
    """A repository whose every query is filtered to one profile."""

    def __init__(self, session: Session, user_id: int) -> None:
        super().__init__(session)
        self.user_id = user_id

    def scoped(self) -> Select[tuple[ModelT]]:
        """Return a ``SELECT`` already filtered to this profile."""
        return select(self.model).where(self.model.user_id == self.user_id)

    def get_or_raise(self, entity_id: int) -> ModelT:
        """Return one owned row by primary key.

        Raises:
            NotFoundError: If the row does not exist *or* belongs to another
                profile. The two cases are deliberately indistinguishable to
                the caller.
        """
        found = self.get(entity_id)
        if found is None or getattr(found, "user_id", None) != self.user_id:
            raise NotFoundError(self.model.__name__, entity_id)
        return found

    def count_owned(self, *criteria: Any) -> int:
        """Count this profile's rows matching the criteria."""
        return self.count_where(self.model.user_id == self.user_id, *criteria)

    def list_owned(self, *, limit: int | None = None) -> list[ModelT]:
        """Return this profile's rows, optionally capped.

        Only for the small configuration tables. Anything that grows with
        use is read through a filtered, paginated method instead.
        """
        statement = self.scoped()
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement))
