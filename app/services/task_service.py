"""Task business rules."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.errors import ValidationError
from app.core.logging_config import get_logger
from app.domain.tasks.recurrence import RecurrenceSpec, occurrences_between
from app.domain.tasks.rules import (
    TaskCompletion,
    TaskSnapshot,
    summarize_tasks,
    validate_transition,
)
from app.models.enums import RecurrenceRule, TaskStatus
from app.models.task import Task
from app.repositories.task_repository import OVERDUE_WINDOW_DAYS
from app.schemas.common import Page, Pagination
from app.schemas.task import TaskCreate, TaskFilter, TaskRead, TaskUpdate
from app.services.base import BaseService
from app.services.unit_of_work import UnitOfWork

logger = get_logger(__name__)

#: How far ahead recurring occurrences are materialised. Far enough that the
#: week view is always populated, near enough that a daily habit-like task
#: does not create three years of rows on the first run.
GENERATION_HORIZON_DAYS = 30


class TaskService(BaseService):
    """Creating, editing, completing and generating tasks."""

    # -- reads -------------------------------------------------------------

    def get(self, task_id: int) -> TaskRead:
        """Return one task.

        Raises:
            NotFoundError: If it does not exist or is not owned.
        """
        with self.uow() as uow:
            return TaskRead.model_validate(uow.tasks.get_or_raise(task_id))

    def list_for_day(self, day: date | None = None) -> list[TaskRead]:
        """Return the tasks on one day's list, overdue ones included."""
        target = day or self.today()
        with self.uow() as uow:
            return [TaskRead.model_validate(task) for task in uow.tasks.list_for_day(target)]

    def search(self, criteria: TaskFilter) -> Page[TaskRead]:
        """Run the task list's filter, one page at a time."""
        with self.uow() as uow:
            rows, total = uow.tasks.search(criteria)
            return Page[TaskRead](
                items=[TaskRead.model_validate(row) for row in rows],
                total=total,
                limit=criteria.pagination.limit,
                offset=criteria.pagination.offset,
            )

    def list_open(self, limit: int = 20) -> list[TaskRead]:
        """Return the most pressing open tasks."""
        with self.uow() as uow:
            return [TaskRead.model_validate(task) for task in uow.tasks.list_open(limit=limit)]

    def day_completion(self, day: date | None = None) -> TaskCompletion:
        """Summarise how a day's tasks came out."""
        target = day or self.today()
        with self.uow() as uow:
            snapshots = [
                _snapshot(task) for task in uow.tasks.list_for_day(target, include_overdue=False)
            ]
        return summarize_tasks(snapshots)

    def count_overdue(self, day: date | None = None) -> int:
        """Count open tasks whose due date has passed."""
        with self.uow() as uow:
            return uow.tasks.count_overdue(day or self.today())

    # -- writes ------------------------------------------------------------

    def create(self, payload: TaskCreate) -> TaskRead:
        """Create a task, and its first occurrences if it recurs."""
        with self.uow() as uow:
            if payload.category_id is not None:
                uow.categories.get_or_raise(payload.category_id)

            task = Task(
                user_id=self.user_id,
                title=payload.title,
                description=payload.description,
                priority=payload.priority,
                status=TaskStatus.TODO,
                category_id=payload.category_id,
                due_date=payload.due_date,
                due_time=payload.due_time,
                estimated_minutes=payload.estimated_minutes,
                recurrence=payload.recurrence,
                recurrence_interval=payload.recurrence_interval,
                recurrence_days=payload.recurrence_days,
                recurrence_until=payload.recurrence_until,
                tags=payload.tags,
                notes=payload.notes,
            )
            uow.tasks.add(task)

            if task.is_recurring_template:
                self._generate_for_template(uow, task, horizon=GENERATION_HORIZON_DAYS)

            uow.commit()
            logger.info("Task %s created", task.id)
            return TaskRead.model_validate(task)

    def update(self, task_id: int, payload: TaskUpdate) -> TaskRead:
        """Apply a partial edit to a task."""
        with self.uow() as uow:
            task = uow.tasks.get_or_raise(task_id)
            changes = payload.model_dump(exclude_unset=True)

            if "category_id" in changes and changes["category_id"] is not None:
                uow.categories.get_or_raise(changes["category_id"])

            for field, value in changes.items():
                setattr(task, field, value)

            uow.commit()
            logger.info("Task %s updated: %s", task_id, ", ".join(sorted(changes)))
            return TaskRead.model_validate(task)

    def set_status(self, task_id: int, status: TaskStatus) -> TaskRead:
        """Move a task to a new status, enforcing the legal transitions.

        Raises:
            ValidationError: If the transition is not allowed.
        """
        with self.uow() as uow:
            task = uow.tasks.get_or_raise(task_id)
            validate_transition(task.status, status)

            task.status = status
            task.completed_at = self.clock.now() if status is TaskStatus.COMPLETED else None
            uow.commit()
            logger.info("Task %s moved to %s", task_id, status.value)
            return TaskRead.model_validate(task)

    def complete(self, task_id: int, *, actual_minutes: int | None = None) -> TaskRead:
        """Mark a task complete, optionally recording how long it took."""
        with self.uow() as uow:
            task = uow.tasks.get_or_raise(task_id)
            validate_transition(task.status, TaskStatus.COMPLETED)

            task.status = TaskStatus.COMPLETED
            task.completed_at = self.clock.now()
            if actual_minutes is not None:
                if actual_minutes < 0:
                    raise ValidationError(
                        "Actual duration cannot be negative",
                        field="actual_minutes",
                        value=actual_minutes,
                    )
                task.actual_minutes = actual_minutes

            uow.commit()
            logger.info("Task %s completed", task_id)
            return TaskRead.model_validate(task)

    def reopen(self, task_id: int) -> TaskRead:
        """Return a finished task to the to-do list."""
        return self.set_status(task_id, TaskStatus.TODO)

    def delete(self, task_id: int) -> None:
        """Delete a task and, for a template, its generated occurrences."""
        with self.uow() as uow:
            task = uow.tasks.get_or_raise(task_id)
            uow.tasks.delete(task)
            uow.commit()
            logger.info("Task %s deleted", task_id)

    # -- recurrence --------------------------------------------------------

    def generate_occurrences(self, *, horizon_days: int = GENERATION_HORIZON_DAYS) -> int:
        """Materialise upcoming occurrences for every recurring template.

        Idempotent: dates that already have an occurrence are skipped, so
        this can safely run on every application start.

        Returns:
            How many occurrences were created.
        """
        created = 0
        with self.uow() as uow:
            for template in uow.tasks.list_recurring_templates():
                created += self._generate_for_template(uow, template, horizon=horizon_days)
            if created:
                uow.commit()
                logger.info("Generated %d recurring task occurrences", created)
            else:
                uow.rollback()
        return created

    def _generate_for_template(self, uow: UnitOfWork, template: Task, *, horizon: int) -> int:
        """Create missing occurrences for one template inside the horizon."""
        if template.due_date is None or template.recurrence is RecurrenceRule.NONE:
            return 0

        start = max(self.today(), template.due_date)
        end = self.today() + timedelta(days=horizon)
        spec = RecurrenceSpec.build(
            rule=template.recurrence,
            interval=template.recurrence_interval,
            weekdays=template.recurrence_days,
            until=template.recurrence_until,
        )

        existing = uow.tasks.occurrence_dates(template.id, start, end)
        created = 0
        for due in occurrences_between(spec, template.due_date, start, end):
            if due in existing:
                continue
            uow.tasks.add(
                Task(
                    user_id=self.user_id,
                    title=template.title,
                    description=template.description,
                    priority=template.priority,
                    status=TaskStatus.TODO,
                    category_id=template.category_id,
                    due_date=due,
                    due_time=template.due_time,
                    estimated_minutes=template.estimated_minutes,
                    recurrence=RecurrenceRule.NONE,
                    parent_task_id=template.id,
                    tags=template.tags,
                    sort_order=template.sort_order,
                )
            )
            created += 1
        return created

    # -- quick add ---------------------------------------------------------

    def quick_add(self, title: str, *, day: date | None = None) -> TaskRead:
        """Create a task from nothing but a title.

        The Quick Add path. Anything that would make this slower than typing
        the title belongs on the full form instead.
        """
        if not title.strip():
            raise ValidationError("A task needs a title", field="title", value=title)
        return self.create(TaskCreate(title=title.strip(), due_date=day or self.today()))

    def overdue_page(self, pagination: Pagination) -> Page[TaskRead]:
        """Return overdue open tasks, one page at a time."""
        today = self.today()
        criteria = TaskFilter(
            statuses=[TaskStatus.TODO, TaskStatus.IN_PROGRESS],
            due_to=today - timedelta(days=1),
            pagination=pagination,
        )
        return self.search(criteria)


def _snapshot(task: Task) -> TaskSnapshot:
    """Reduce an ORM task to the value object the domain rules take."""
    return TaskSnapshot(
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        estimated_minutes=task.estimated_minutes,
        actual_minutes=task.actual_minutes,
    )


#: Re-exported so the UI can explain the day list without importing a
#: repository - the layering rule holds even for a constant.
__all__ = ["GENERATION_HORIZON_DAYS", "OVERDUE_WINDOW_DAYS", "TaskService"]
