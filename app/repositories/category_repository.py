"""Persistence for user-defined categories."""

from __future__ import annotations

from sqlalchemy import select

from app.models.category import Category
from app.models.enums import CategoryKind
from app.repositories.base import UserScopedRepository


class CategoryRepository(UserScopedRepository[Category]):
    """Categories for tasks, habits, activities and time entries."""

    model = Category

    def list_by_kind(self, kind: CategoryKind, *, active_only: bool = True) -> list[Category]:
        """Return one kind of category, in display order."""
        statement = self.scoped().where(Category.kind == kind)
        if active_only:
            statement = statement.where(Category.is_active.is_(True))
        return list(self.session.scalars(statement.order_by(Category.sort_order, Category.name)))

    def get_by_name(self, kind: CategoryKind, name: str) -> Category | None:
        """Return one category by kind and name."""
        statement = self.scoped().where(Category.kind == kind, Category.name == name)
        return self.session.scalars(statement).first()

    def map_by_id(self, kind: CategoryKind | None = None) -> dict[int, Category]:
        """Return categories keyed by id.

        The UI renders category names next to hundreds of rows. Fetching
        the lookup once and reading it from a dictionary is what keeps that
        from becoming one query per row.
        """
        statement = self.scoped()
        if kind is not None:
            statement = statement.where(Category.kind == kind)
        return {category.id: category for category in self.session.scalars(statement)}

    def productive_ids(self) -> set[int]:
        """Return the ids of time categories flagged productive."""
        statement = select(Category.id).where(
            Category.user_id == self.user_id,
            Category.kind == CategoryKind.TIME,
            Category.is_productive.is_(True),
        )
        return set(self.session.scalars(statement))

    def ensure(
        self,
        kind: CategoryKind,
        name: str,
        *,
        is_productive: bool = False,
        color: str | None = None,
        icon: str | None = None,
        sort_order: int = 100,
    ) -> Category:
        """Return the named category, creating it if it does not exist.

        Used by seeding and by import, where referring to a category by
        name is far more convenient than by id.
        """
        existing = self.get_by_name(kind, name)
        if existing is not None:
            return existing
        return self.add(
            Category(
                user_id=self.user_id,
                kind=kind,
                name=name,
                is_productive=is_productive,
                color=color,
                icon=icon,
                sort_order=sort_order,
            )
        )

    def is_in_use(self, category_id: int) -> bool:
        """Whether anything still references this category.

        Checked before deletion so the user gets an explanation instead of a
        foreign-key error.
        """
        from app.models.activity import Activity
        from app.models.habit import Habit
        from app.models.task import Task
        from app.models.time_entry import TimeEntry

        for model, column in (
            (Task, Task.category_id),
            (Habit, Habit.category_id),
            (Activity, Activity.category_id),
            (TimeEntry, TimeEntry.category_id),
        ):
            statement = select(model.id).where(column == category_id).limit(1)
            if self.session.scalars(statement).first() is not None:
                return True
        return False
