"""Persistence for tasks."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Select, func, or_, select

from app.models.enums import RecurrenceRule, TaskStatus
from app.models.task import Task
from app.repositories.base import UserScopedRepository
from app.schemas.common import Pagination
from app.schemas.task import TaskFilter

#: Statuses that mean "still needs doing".
OPEN_STATUSES = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)

#: How far back a day's list reaches for still-open overdue tasks.
OVERDUE_WINDOW_DAYS = 14
#: Hard cap on the rows one day's list returns.
DAY_LIST_LIMIT = 60


class TaskRepository(UserScopedRepository[Task]):
    """Task queries.

    Every listing method is either bounded by a date range or paginated.
    There is deliberately no ``list all tasks``: with a hundred thousand
    rows that call is a page that never loads.
    """

    model = Task

    # -- day and range reads ----------------------------------------------

    def list_for_day(
        self,
        day: date,
        *,
        include_overdue: bool = True,
        overdue_within_days: int = OVERDUE_WINDOW_DAYS,
        limit: int = DAY_LIST_LIMIT,
    ) -> list[Task]:
        """Return the tasks that belong on one day's list.

        Includes anything due that day plus, optionally, open tasks whose
        due date has recently passed - an overdue task the user cannot see
        is an overdue task they will not do.

        The overdue tail is *bounded*: after a few months of use, "every
        task ever left open" is hundreds of rows and turns the day's list
        into an unusable wall. Older ones are still reachable from the
        filtered view, and :meth:`count_overdue` still counts them all.

        Args:
            day: The day being shown.
            include_overdue: Fold in recently overdue open tasks.
            overdue_within_days: How far back the overdue tail reaches.
            limit: Hard cap on rows returned.
        """
        due_today = Task.due_date == day
        if include_overdue:
            overdue = (
                (Task.due_date < day)
                & (Task.due_date >= day - timedelta(days=overdue_within_days))
                & Task.status.in_(OPEN_STATUSES)
            )
            criteria = or_(due_today, overdue)
        else:
            criteria = due_today

        # A recurring template is a rule, not a to-do: only its generated
        # occurrences belong on a day's list.
        not_a_template = or_(
            Task.recurrence == RecurrenceRule.NONE, Task.parent_task_id.isnot(None)
        )
        statement = (
            self.scoped()
            .where(criteria, not_a_template)
            .order_by(Task.status, Task.priority.desc(), Task.sort_order, Task.id)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def list_between(self, start: date, end: date) -> list[Task]:
        """Return tasks due inside an inclusive date range."""
        statement = (
            self.scoped()
            .where(Task.due_date >= start, Task.due_date <= end)
            .order_by(Task.due_date, Task.sort_order)
        )
        return list(self.session.scalars(statement))

    def list_open(self, *, limit: int = 50) -> list[Task]:
        """Return the oldest open tasks, capped."""
        statement = (
            self.scoped()
            .where(Task.status.in_(OPEN_STATUSES))
            .order_by(Task.due_date.is_(None), Task.due_date, Task.priority.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    # -- filtered search ---------------------------------------------------

    def search(self, criteria: TaskFilter) -> tuple[list[Task], int]:
        """Run the task list's filter and return one page plus the total."""
        statement = self._apply_filter(self.scoped(), criteria)
        statement = statement.order_by(
            Task.due_date.is_(None), Task.due_date, Task.priority.desc(), Task.id.desc()
        )
        return self.paginate(statement, criteria.pagination)

    def _apply_filter(
        self, statement: Select[tuple[Task]], criteria: TaskFilter
    ) -> Select[tuple[Task]]:
        """Translate a :class:`TaskFilter` into ``WHERE`` clauses."""
        if criteria.statuses:
            statement = statement.where(Task.status.in_(criteria.statuses))
        if criteria.priorities:
            statement = statement.where(Task.priority.in_(criteria.priorities))
        if criteria.category_ids:
            statement = statement.where(Task.category_id.in_(criteria.category_ids))
        if criteria.due_from:
            statement = statement.where(Task.due_date >= criteria.due_from)
        if criteria.due_to:
            statement = statement.where(Task.due_date <= criteria.due_to)
        if criteria.search:
            pattern = f"%{criteria.search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(Task.title).like(pattern),
                    func.lower(func.coalesce(Task.description, "")).like(pattern),
                )
            )
        if not criteria.include_occurrences:
            statement = statement.where(Task.parent_task_id.is_(None))
        return statement

    # -- recurrence support ------------------------------------------------

    def list_recurring_templates(self) -> list[Task]:
        """Return the templates that spawn occurrences."""
        statement = self.scoped().where(
            Task.parent_task_id.is_(None), Task.recurrence != RecurrenceRule.NONE
        )
        return list(self.session.scalars(statement))

    def occurrence_dates(self, template_id: int, start: date, end: date) -> set[date]:
        """Return the dates a template already has occurrences for.

        Selecting only the date column keeps generation from loading whole
        task rows just to find out which days are already covered.
        """
        statement = select(Task.due_date).where(
            Task.parent_task_id == template_id,
            Task.due_date >= start,
            Task.due_date <= end,
        )
        return {value for value in self.session.scalars(statement) if value is not None}

    # -- aggregates --------------------------------------------------------

    def count_by_status(self, start: date, end: date) -> dict[TaskStatus, int]:
        """Count tasks per status inside a date range.

        Aggregated by the database. Counting these in Python would mean
        transferring every row to count them.
        """
        statement = (
            select(Task.status, func.count())
            .where(
                Task.user_id == self.user_id,
                Task.due_date >= start,
                Task.due_date <= end,
            )
            .group_by(Task.status)
        )
        return dict(self.session.execute(statement).tuples().all())

    def completed_per_day(self, start: date, end: date) -> dict[date, int]:
        """Count completed tasks per due date inside a range."""
        statement = (
            select(Task.due_date, func.count())
            .where(
                Task.user_id == self.user_id,
                Task.status == TaskStatus.COMPLETED,
                Task.due_date >= start,
                Task.due_date <= end,
            )
            .group_by(Task.due_date)
        )
        return {day: count for day, count in self.session.execute(statement) if day is not None}

    def planned_per_day(self, start: date, end: date) -> dict[date, int]:
        """Count all non-cancelled tasks per due date inside a range."""
        statement = (
            select(Task.due_date, func.count())
            .where(
                Task.user_id == self.user_id,
                Task.status != TaskStatus.CANCELLED,
                Task.due_date >= start,
                Task.due_date <= end,
            )
            .group_by(Task.due_date)
        )
        return {day: count for day, count in self.session.execute(statement) if day is not None}

    def count_overdue(self, today: date) -> int:
        """Count open tasks whose due date has passed."""
        return self.count_owned(Task.status.in_(OPEN_STATUSES), Task.due_date < today)

    def next_occurrence_page(self, pagination: Pagination) -> tuple[list[Task], int]:
        """Return generated occurrences, newest first, one page at a time."""
        statement = self.scoped().where(Task.parent_task_id.isnot(None)).order_by(Task.id.desc())
        return self.paginate(statement, pagination)
