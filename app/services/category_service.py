"""Category management.

Categories are the mechanism that keeps subject-matter out of the code. The
default set below is *seed data*, not configuration the application reads:
delete "Cricket" and nothing breaks, because nothing refers to it by name.
"""

from __future__ import annotations

from app.core.errors import ConflictError, ValidationError
from app.core.logging_config import get_logger
from app.models.category import Category
from app.models.enums import CategoryKind
from app.schemas.activity import CategoryCreate, CategoryRead, CategoryUpdate
from app.services.base import BaseService

logger = get_logger(__name__)

#: ``(name, is_productive, icon)`` per kind. Seeded once on first run.
DEFAULT_CATEGORIES: dict[CategoryKind, tuple[tuple[str, bool, str], ...]] = {
    CategoryKind.TASK: (
        ("Work", False, "💼"),
        ("Study", False, "📚"),
        ("Personal", False, "🏠"),
        ("Health", False, "🩺"),
        ("Errands", False, "🧾"),
    ),
    CategoryKind.HABIT: (
        ("Health", False, "🩺"),
        ("Learning", False, "📚"),
        ("Fitness", False, "🏃"),
        ("Mindfulness", False, "🧘"),
        ("Focus", False, "🎯"),
    ),
    CategoryKind.ACTIVITY: (
        ("Cricket", False, "🏏"),
        ("Walking", False, "🚶"),
        ("Running", False, "🏃"),
        ("Gym", False, "🏋️"),
        ("Cycling", False, "🚴"),
        ("Yoga", False, "🧘"),
        ("Swimming", False, "🏊"),
        ("Other", False, "⚡"),
    ),
    CategoryKind.TIME: (
        ("Coding", True, "💻"),
        ("Teaching", True, "🧑‍🏫"),
        ("Studying", True, "📚"),
        ("Work", True, "💼"),
        ("Reading", True, "📖"),
        ("Exercise", True, "🏃"),
        ("Cricket", False, "🏏"),
        ("Personal", False, "🏠"),
        ("Entertainment", False, "🎬"),
        ("Travel", False, "🚗"),
        ("Other", False, "⚪"),
    ),
}

#: Time categories whose minutes count towards the "learning" score
#: component by default. Stored as names only because this is seed data;
#: the ids are resolved once and cached in ``app_settings``.
DEFAULT_LEARNING_CATEGORIES = ("Studying", "Coding", "Teaching", "Reading")


class CategoryService(BaseService):
    """Creating, editing and retiring the user's categories."""

    def list_kind(self, kind: CategoryKind, *, active_only: bool = True) -> list[CategoryRead]:
        """Return the categories of one kind."""
        with self.uow() as uow:
            return [
                CategoryRead.model_validate(row)
                for row in uow.categories.list_by_kind(kind, active_only=active_only)
            ]

    def all_kinds(self) -> dict[CategoryKind, list[CategoryRead]]:
        """Return every category, grouped by kind."""
        with self.uow() as uow:
            grouped: dict[CategoryKind, list[CategoryRead]] = {}
            for kind in CategoryKind:
                grouped[kind] = [
                    CategoryRead.model_validate(row)
                    for row in uow.categories.list_by_kind(kind, active_only=False)
                ]
            return grouped

    def create(self, payload: CategoryCreate) -> CategoryRead:
        """Create a category.

        Raises:
            ConflictError: If one of that kind already has the name.
        """
        with self.uow() as uow:
            if uow.categories.get_by_name(payload.kind, payload.name) is not None:
                raise ConflictError(
                    "That category already exists",
                    details={"kind": payload.kind.value, "name": payload.name},
                    user_hint=f"There is already a {payload.kind.value.lower()} "
                    f"category called {payload.name!r}.",
                )
            category = Category(
                user_id=self.user_id,
                kind=payload.kind,
                name=payload.name,
                color=payload.color,
                icon=payload.icon,
                is_productive=payload.is_productive,
                sort_order=payload.sort_order,
            )
            uow.categories.add(category)
            uow.commit()
            logger.info("Category %s created (%s)", category.id, payload.kind.value)
            return CategoryRead.model_validate(category)

    def update(self, category_id: int, payload: CategoryUpdate) -> CategoryRead:
        """Apply a partial edit to a category."""
        with self.uow() as uow:
            category = uow.categories.get_or_raise(category_id)
            changes = payload.model_dump(exclude_unset=True)

            new_name = changes.get("name")
            if new_name and new_name != category.name:
                clash = uow.categories.get_by_name(category.kind, new_name)
                if clash is not None:
                    raise ConflictError(
                        "That category name is taken",
                        details={"name": new_name},
                        user_hint=f"There is already a category called {new_name!r}.",
                    )

            for field, value in changes.items():
                setattr(category, field, value)

            uow.commit()
            logger.info("Category %s updated", category_id)
            return CategoryRead.model_validate(category)

    def delete(self, category_id: int) -> None:
        """Delete a category that nothing refers to.

        Raises:
            ValidationError: If records still use it. Deactivating is
                offered instead, so history is never silently rewritten.
        """
        with self.uow() as uow:
            category = uow.categories.get_or_raise(category_id)
            if uow.categories.is_in_use(category_id):
                raise ValidationError(
                    "Category is still in use",
                    field="category_id",
                    value=category_id,
                    user_hint=(
                        f"{category.name!r} is used by existing records. "
                        "Deactivate it instead - that hides it from the forms "
                        "without changing your history."
                    ),
                )
            uow.categories.delete(category)
            uow.commit()
            logger.info("Category %s deleted", category_id)

    def deactivate(self, category_id: int) -> CategoryRead:
        """Hide a category from the forms, keeping its history intact."""
        return self.update(category_id, CategoryUpdate(is_active=False))

    def productive_time_category_ids(self) -> list[int]:
        """Return the ids of time categories flagged productive."""
        with self.uow() as uow:
            return sorted(uow.categories.productive_ids())

    def learning_category_ids(self) -> list[int]:
        """Return the ids of the time categories that count as learning."""
        with self.uow() as uow:
            lookup = uow.categories.map_by_id(CategoryKind.TIME)
            return sorted(
                category_id
                for category_id, category in lookup.items()
                if category.name in DEFAULT_LEARNING_CATEGORIES
            )

    def name_lookup(self, kind: CategoryKind) -> dict[int, str]:
        """Return ``{id: name}`` for one kind, for rendering lists."""
        with self.uow() as uow:
            return {
                category_id: category.name
                for category_id, category in uow.categories.map_by_id(kind).items()
            }

    def seed_defaults(self) -> int:
        """Create the default categories that are missing.

        Idempotent, so it is safe to call on every start. Returns how many
        were created.
        """
        created = 0
        with self.uow() as uow:
            for kind, entries in DEFAULT_CATEGORIES.items():
                for order, (name, productive, icon) in enumerate(entries):
                    before = uow.categories.get_by_name(kind, name)
                    if before is None:
                        uow.categories.ensure(
                            kind,
                            name,
                            is_productive=productive,
                            icon=icon,
                            sort_order=(order + 1) * 10,
                        )
                        created += 1
            if created:
                uow.commit()
                logger.info("Seeded %d default categories", created)
            else:
                uow.rollback()
        return created


__all__ = [
    "DEFAULT_CATEGORIES",
    "DEFAULT_LEARNING_CATEGORIES",
    "CategoryService",
]
