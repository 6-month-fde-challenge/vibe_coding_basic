"""Configurable categories for tasks, habits, activities and time entries.

One table with a ``kind`` discriminator rather than four near-identical
tables. This is the mechanism that keeps "Cricket" out of the business logic:
it is a row a user can rename or delete, not an ``if activity == "cricket"``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin, UserOwnedMixin
from app.database.types import str_enum
from app.models.enums import CategoryKind

if TYPE_CHECKING:
    from app.models.activity import Activity
    from app.models.habit import Habit
    from app.models.task import Task
    from app.models.time_entry import TimeEntry
    from app.models.user import UserProfile


class Category(IdMixin, TimestampMixin, UserOwnedMixin, Base):
    """A user-defined label within one part of the application.

    Attributes:
        kind: Which feature the category belongs to.
        name: Display name, unique per user and kind.
        is_productive: Only meaningful for :attr:`CategoryKind.TIME`. Drives
            the "productive hours" figure without hard-coding a list of
            category names into the analytics layer.
    """

    __tablename__ = "category"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "name", name="uq_category_user_kind_name"),
    )

    kind: Mapped[CategoryKind] = mapped_column(str_enum(CategoryKind), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_productive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    user: Mapped[UserProfile] = relationship(back_populates="categories")
    tasks: Mapped[list[Task]] = relationship(back_populates="category")
    habits: Mapped[list[Habit]] = relationship(back_populates="category")
    activities: Mapped[list[Activity]] = relationship(back_populates="category")
    time_entries: Mapped[list[TimeEntry]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        """Return a debugging representation naming the kind and label."""
        return f"<Category id={self.id} kind={self.kind} name={self.name!r}>"
