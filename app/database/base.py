"""Declarative base and the mixins every table shares.

The metadata carries an explicit constraint naming convention. Without one,
SQLite invents anonymous constraint names and Alembic cannot later drop or
alter them - which turns the first schema change into a manual rebuild.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.database.types import UTCDateTime

#: ``ix_`` index, ``uq_`` unique, ``ck_`` check, ``fk_`` foreign key, ``pk_``
#: primary key. Alembic's ``render_as_batch`` needs these to alter SQLite.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every ORM model.

    ``type_annotation_map`` is what lets a model write ``Mapped[datetime]``
    and get a UTC-normalising column, instead of repeating the column type on
    every single timestamp.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this as a class attribute
        datetime: UTCDateTime(timezone=True),
    }

    def __repr__(self) -> str:
        """Return a concise, non-sensitive representation for logs."""
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"


class IdMixin:
    """Surrogate integer primary key."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)


class TimestampMixin:
    """``created_at`` / ``updated_at``, maintained by the database."""

    @declared_attr
    @classmethod
    def created_at(cls) -> Mapped[datetime]:
        """When the row was first written (UTC)."""
        return mapped_column(
            UTCDateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            index=True,
        )

    @declared_attr
    @classmethod
    def updated_at(cls) -> Mapped[datetime]:
        """When the row was last modified (UTC)."""
        return mapped_column(
            UTCDateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )


class UserOwnedMixin:
    """A row that belongs to one profile.

    The application is single-user today. Carrying ``user_id`` from the start
    means adding a second user is a data migration rather than a schema
    rewrite, and it gives every hot query a selective leading index column.
    """

    @declared_attr
    @classmethod
    def user_id(cls) -> Mapped[int]:
        """Owning profile."""
        return mapped_column(
            ForeignKey("user_profile.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


def as_dict(instance: Base, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """Return a model's column values as a plain dictionary.

    Used by the export layer so that adding a column does not mean editing
    every exporter. Dates and datetimes are rendered ISO-8601.

    Args:
        instance: Any mapped instance.
        exclude: Column names to leave out.
    """
    skip = exclude or set()
    payload: dict[str, Any] = {}
    for column in instance.__table__.columns:
        if column.name in skip:
            continue
        value = getattr(instance, column.name)
        if isinstance(value, datetime | date):
            payload[column.name] = value.isoformat()
        else:
            payload[column.name] = value
    return payload
