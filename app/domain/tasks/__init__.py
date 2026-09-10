"""Task status rules, completion arithmetic and recurrence."""

from app.domain.tasks.recurrence import (
    MAX_GENERATED_OCCURRENCES,
    RecurrenceSpec,
    next_occurrence,
    occurrences_between,
)
from app.domain.tasks.rules import (
    ALLOWED_TRANSITIONS,
    TaskCompletion,
    TaskSnapshot,
    is_overdue,
    summarize_tasks,
    validate_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "MAX_GENERATED_OCCURRENCES",
    "RecurrenceSpec",
    "TaskCompletion",
    "TaskSnapshot",
    "is_overdue",
    "next_occurrence",
    "occurrences_between",
    "summarize_tasks",
    "validate_transition",
]
