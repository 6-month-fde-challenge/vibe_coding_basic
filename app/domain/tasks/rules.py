"""Task status rules and day-level completion arithmetic."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.core.errors import ValidationError
from app.models.enums import TaskPriority, TaskStatus

#: Which status changes are legal. Reopening a completed task is allowed -
#: people tick the wrong row - but jumping straight from CANCELLED to
#: COMPLETED is not, because it hides the fact the task was ever dropped.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.TODO: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {TaskStatus.TODO, TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS}),
    TaskStatus.SKIPPED: frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.TODO}),
}


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """The little the completion arithmetic needs to know about a task."""

    status: TaskStatus
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None
    estimated_minutes: int | None = None
    actual_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class TaskCompletion:
    """How a set of tasks came out.

    Attributes:
        total: Tasks considered, excluding cancelled ones.
        completed: Tasks finished.
        pending: Tasks still open (todo or in progress).
        skipped: Tasks deliberately passed over.
        cancelled: Tasks withdrawn; excluded from ``total``.
        rate: ``completed / total``, from 0 to 1.
        weighted_rate: The same, weighting each task by its priority, so
            finishing the critical one counts for more than clearing three
            trivial ones.
        estimate_accuracy: Actual minutes over estimated minutes across the
            tasks that recorded both. ``None`` when nothing did.
    """

    total: int = 0
    completed: int = 0
    pending: int = 0
    skipped: int = 0
    cancelled: int = 0
    rate: float = 0.0
    weighted_rate: float = 0.0
    estimate_accuracy: float | None = None

    @property
    def has_tasks(self) -> bool:
        """Whether there was anything to complete."""
        return self.total > 0


def validate_transition(current: TaskStatus, new: TaskStatus) -> None:
    """Reject an illegal status change.

    Args:
        current: The task's present status.
        new: The status being requested.

    Raises:
        ValidationError: If the change is not in :data:`ALLOWED_TRANSITIONS`.
    """
    if current is new:
        return
    if new not in ALLOWED_TRANSITIONS[current]:
        raise ValidationError(
            f"Cannot move a task from {current.value} to {new.value}",
            field="status",
            value=new.value,
            user_hint=(
                f"A {current.value.lower().replace('_', ' ')} task cannot become "
                f"{new.value.lower().replace('_', ' ')}. Reopen it first."
            ),
        )


def summarize_tasks(tasks: Sequence[TaskSnapshot]) -> TaskCompletion:
    """Reduce a day's (or a week's) tasks to a completion picture.

    Cancelled tasks are excluded from the denominator on purpose: a day
    should not score worse because the user tidied up work that turned out
    not to be needed.
    """
    if not tasks:
        return TaskCompletion()

    cancelled = sum(1 for task in tasks if task.status is TaskStatus.CANCELLED)
    counted = [task for task in tasks if task.status is not TaskStatus.CANCELLED]
    if not counted:
        return TaskCompletion(cancelled=cancelled)

    completed = sum(1 for task in counted if task.status.counts_as_done)
    skipped = sum(1 for task in counted if task.status is TaskStatus.SKIPPED)
    pending = len(counted) - completed - skipped

    weight_total = sum(task.priority.weight for task in counted)
    weight_done = sum(task.priority.weight for task in counted if task.status.counts_as_done)

    estimated = sum(
        task.estimated_minutes or 0
        for task in counted
        if task.estimated_minutes and task.actual_minutes
    )
    actual = sum(
        task.actual_minutes or 0
        for task in counted
        if task.estimated_minutes and task.actual_minutes
    )

    return TaskCompletion(
        total=len(counted),
        completed=completed,
        pending=pending,
        skipped=skipped,
        cancelled=cancelled,
        rate=completed / len(counted),
        weighted_rate=(weight_done / weight_total) if weight_total else 0.0,
        estimate_accuracy=(actual / estimated) if estimated else None,
    )


def is_overdue(task: TaskSnapshot, today: date) -> bool:
    """Whether an open task's due date has passed."""
    if task.due_date is None or task.status.is_terminal:
        return False
    return task.due_date < today
