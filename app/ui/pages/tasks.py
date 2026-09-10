"""The task page: create, filter, complete."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.models.enums import CategoryKind, RecurrenceRule, TaskPriority, TaskStatus, members
from app.schemas.common import Pagination
from app.schemas.task import TaskCreate, TaskFilter, TaskRead, TaskUpdate
from app.services.task_service import OVERDUE_WINDOW_DAYS
from app.ui.components.forms import category_picker, enum_select, weekday_multiselect
from app.ui.components.metrics import Tile, empty_state, tile_row
from app.ui.formatting import PRIORITY_BADGES, STATUS_BADGES, minutes, truncate
from app.ui.state import date_navigator, flush_action_message, get_container, run_action

#: Rows per page in the history table.
PAGE_SIZE = 25


def render() -> None:
    """Draw the tasks page."""
    st.title("Tasks")
    flush_action_message()

    today_tab, all_tab, new_tab = st.tabs(["Today", "All tasks", "New task"])
    with today_tab:
        _today()
    with all_tab:
        _browse()
    with new_tab:
        _create_form()


def _today() -> None:
    """The day's list, with one-click completion."""
    container = get_container()
    day = date_navigator()
    tasks = container.tasks.list_for_day(day)
    completion = container.tasks.day_completion(day)

    tile_row(
        [
            Tile("Planned", str(completion.total)),
            Tile("Completed", str(completion.completed)),
            Tile("Pending", str(completion.pending)),
            Tile("Overdue", str(container.tasks.count_overdue(day))),
        ]
    )
    st.write("")

    if not tasks:
        empty_state("Nothing on the list for this day.", "Add one on the New task tab.")
        return

    shown_overdue = sum(1 for task in tasks if task.due_date and task.due_date < day)
    hidden = container.tasks.count_overdue(day) - shown_overdue
    if hidden > 0:
        st.caption(
            f"{hidden} older overdue task(s) are not shown here - the day's list only reaches "
            f"back {OVERDUE_WINDOW_DAYS} days. Find them on the All tasks tab."
        )

    for task in tasks:
        _task_row(task, day)


def _task_row(task: TaskRead, day: date) -> None:
    """One row of the day's list."""
    container = get_container()
    with st.container(border=True):
        text_col, meta_col, action_col = st.columns([5, 2, 2], vertical_alignment="center")

        overdue = task.due_date is not None and task.due_date < day and task.is_open
        title = f"~~{task.title}~~" if task.status is TaskStatus.COMPLETED else f"**{task.title}**"
        text_col.markdown(title)
        caption = [PRIORITY_BADGES[task.priority]]
        if task.due_date:
            caption.append(f"due {task.due_date.isoformat()}")
        if overdue:
            caption.append("⚠️ overdue")
        if task.estimated_minutes:
            caption.append(f"est. {minutes(task.estimated_minutes)}")
        text_col.caption(" · ".join(caption))

        meta_col.write(STATUS_BADGES[task.status])

        if task.status is TaskStatus.COMPLETED:
            if action_col.button("Reopen", key=f"reopen_{task.id}", use_container_width=True):
                run_action(
                    "reopen task",
                    container.tasks.reopen,
                    task.id,
                    success=f"{task.title!r} reopened.",
                )
        elif action_col.button("Done", key=f"done_{task.id}", use_container_width=True):
            run_action(
                "complete task",
                container.tasks.complete,
                task.id,
                success=f"{task.title!r} completed.",
            )

        with st.expander("Edit", expanded=False):
            _edit_form(task)


def _edit_form(task: TaskRead) -> None:
    """Inline edit and delete for one task."""
    container = get_container()
    with st.form(f"edit_task_{task.id}", border=False):
        title = st.text_input("Title", value=task.title)
        notes = st.text_area("Notes", value=task.notes or "", height=80)
        left, right = st.columns(2)
        priority = enum_select(
            "Priority",
            members(TaskPriority),
            key=f"edit_priority_{task.id}",
            current=task.priority,
            format_func=lambda value: PRIORITY_BADGES[value],
            parent=left,
        )
        actual = right.number_input(
            "Actual minutes", min_value=0, max_value=24 * 60, value=task.actual_minutes or 0, step=5
        )

        save, delete = st.columns(2)
        if save.form_submit_button("Save", use_container_width=True):
            run_action(
                "update task",
                container.tasks.update,
                task.id,
                TaskUpdate(
                    title=title,
                    notes=notes or None,
                    priority=priority,
                    actual_minutes=int(actual) or None,
                ),
                success="Task updated.",
            )
        if delete.form_submit_button("Delete", use_container_width=True):
            run_action(
                "delete task",
                container.tasks.delete,
                task.id,
                success=f"{task.title!r} deleted.",
            )


def _browse() -> None:
    """Filtered, paginated history."""
    container = get_container()

    with st.expander("Filters", expanded=True):
        left, middle, right = st.columns(3)
        status_labels = left.multiselect("Status", [STATUS_BADGES[value] for value in TaskStatus])
        statuses = [value for value in TaskStatus if STATUS_BADGES[value] in status_labels]
        priority_labels = middle.multiselect(
            "Priority", [PRIORITY_BADGES[value] for value in TaskPriority]
        )
        priorities = [value for value in TaskPriority if PRIORITY_BADGES[value] in priority_labels]
        search = right.text_input("Search", placeholder="title or description")

        date_left, date_right = st.columns(2)
        use_dates = date_left.checkbox("Filter by due date")
        due_from = date_left.date_input("From") if use_dates else None
        due_to = date_right.date_input("To") if use_dates else None

    page_number = st.number_input("Page", min_value=1, value=1, step=1)
    criteria = TaskFilter(
        statuses=statuses or None,
        priorities=priorities or None,
        search=search or None,
        due_from=due_from,
        due_to=due_to,
        pagination=Pagination(limit=PAGE_SIZE, offset=(int(page_number) - 1) * PAGE_SIZE),
    )

    page = container.tasks.search(criteria)
    if not page.items:
        empty_state("No tasks match those filters.")
        return

    st.caption(f"{page.total} matching tasks · page {page.page_number} of {page.page_count}")
    st.dataframe(
        [
            {
                "Title": truncate(task.title, 50),
                "Status": STATUS_BADGES[task.status],
                "Priority": PRIORITY_BADGES[task.priority],
                "Due": task.due_date.isoformat() if task.due_date else "",
                "Estimated": minutes(task.estimated_minutes) if task.estimated_minutes else "",
                "Actual": minutes(task.actual_minutes) if task.actual_minutes else "",
                "Tags": ", ".join(task.tags or []),
            }
            for task in page.items
        ],
        hide_index=True,
        use_container_width=True,
    )


def _create_form() -> None:
    """The full task form."""
    container = get_container()

    category = category_picker(CategoryKind.TASK, key="new_task_category")

    with st.form("new_task", clear_on_submit=True):
        title = st.text_input("Title", max_chars=200)
        description = st.text_area("Description", height=90)

        left, middle, right = st.columns(3)
        priority = enum_select(
            "Priority",
            members(TaskPriority),
            key="new_task_priority",
            current=TaskPriority.MEDIUM,
            format_func=lambda value: PRIORITY_BADGES[value],
            parent=left,
        )
        due = middle.date_input("Due date", value=container.clock.today())
        estimate = right.number_input("Estimate (minutes)", min_value=0, max_value=1440, step=15)

        recurrence = enum_select("Repeats", members(RecurrenceRule), key="new_task_recurrence")
        weekdays: list[int] = []
        interval = 1
        if recurrence is RecurrenceRule.WEEKLY:
            weekdays = weekday_multiselect(key="new_task_weekdays", label="On these days")
        if recurrence in {RecurrenceRule.CUSTOM, RecurrenceRule.WEEKLY, RecurrenceRule.MONTHLY}:
            interval = int(st.number_input("Every N periods", min_value=1, max_value=90, value=1))

        tags = st.text_input("Tags", placeholder="comma, separated")

        if st.form_submit_button("Create task", type="primary") and title.strip():
            run_action(
                "create task",
                container.tasks.create,
                TaskCreate(
                    title=title,
                    description=description or None,
                    priority=priority,
                    category_id=category.id if category else None,
                    due_date=due,
                    estimated_minutes=int(estimate) or None,
                    recurrence=recurrence,
                    recurrence_interval=interval,
                    recurrence_days=weekdays or None,
                    tags=[tag.strip() for tag in tags.split(",") if tag.strip()] or None,
                ),
                success=f"Created {title.strip()!r}.",
            )

    st.caption(
        "A repeating task creates a template plus the next 30 days of occurrences, "
        "so each day keeps its own completion history."
    )
    if st.button("Generate upcoming occurrences now"):
        created = run_action(
            "generate occurrences",
            container.tasks.generate_occurrences,
            success="Occurrences generated.",
            rerun=False,
        )
        if created is not None:
            st.info(f"{created} occurrence(s) created.")


__all__ = ["render"]
