"""The habits page: define habits, log them, watch the streaks."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from app.models.enums import CategoryKind, HabitDirection, HabitFrequency, HabitType, members
from app.schemas.habit import HabitCreate, HabitLogInput, HabitTodayRead
from app.ui.components.charts import streak_strip
from app.ui.components.forms import (
    category_picker,
    confirm_button,
    enum_select,
    weekday_multiselect,
)
from app.ui.components.metrics import Tile, empty_state, tile_row
from app.ui.formatting import percent, streak_label
from app.ui.state import date_navigator, flush_action_message, get_container, run_action

#: How much history the per-habit strip shows.
STRIP_DAYS = 28

#: Plain-English names for the habit types, shown on the creation form.
_HABIT_TYPE_LABELS: dict[HabitType, str] = {
    HabitType.BOOLEAN: "Did it or not",
    HabitType.COUNT: "A count (pushups, pages)",
    HabitType.DURATION: "A duration (minutes)",
    HabitType.QUANTITY: "A quantity (litres, grams)",
    HabitType.TIME: "A time of day (wake before 06:30)",
}


def render() -> None:
    """Draw the habits page."""
    st.title("Habits")
    flush_action_message()

    log_tab, manage_tab, new_tab = st.tabs(["Log", "Manage", "New habit"])
    with log_tab:
        _log_tab()
    with manage_tab:
        _manage_tab()
    with new_tab:
        _new_habit()


def _log_tab() -> None:
    """Today's habits, in the order they are due."""
    container = get_container()
    day = date_navigator()
    views = container.habits.today_view(day)

    if not views:
        empty_state("No habits yet.", "Create one on the New habit tab.")
        return

    due = [item for item in views if item.is_due_today]
    done = sum(1 for item in due if item.is_done)
    best = max((item.streak.current_streak for item in views), default=0)

    tile_row(
        [
            Tile("Due today", str(len(due))),
            Tile("Completed", str(done)),
            Tile("Best streak", f"{best} days"),
            Tile("Tracked habits", str(len(views))),
        ]
    )
    st.write("")

    for item in views:
        _habit_card(item, day)


def _habit_card(item: HabitTodayRead, day: date) -> None:
    """One habit, with the control its type actually needs."""
    container = get_container()
    habit = item.habit

    with st.container(border=True):
        header, action = st.columns([3, 2], vertical_alignment="center")
        icon = f"{habit.icon} " if habit.icon else ""
        header.markdown(f"{icon}**{habit.name}**")
        header.caption(
            f"{habit.target_label} · "
            f"{streak_label(item.streak.current_streak, item.streak.longest_streak)} · "
            f"{percent(item.streak.completion_rate)} of days due"
        )

        if not item.is_due_today:
            action.caption("Rest day" if item.is_rest_day else "Not due today")
        elif habit.habit_type is HabitType.BOOLEAN:
            if action.button(
                "Undo" if item.is_done else "Mark done",
                key=f"habit_toggle_{habit.id}",
                use_container_width=True,
                type="secondary" if item.is_done else "primary",
            ):
                run_action(
                    "toggle habit",
                    container.habits.toggle,
                    habit.id,
                    day,
                    success=f"{habit.name} updated.",
                )
        elif habit.habit_type is HabitType.TIME:
            _time_habit_form(item, day)
        else:
            _measured_habit_form(item, day)

        with st.expander("History", expanded=False):
            _history(habit.id, day)


def _measured_habit_form(item: HabitTodayRead, day: date) -> None:
    """A number field for a COUNT / DURATION / QUANTITY habit."""
    container = get_container()
    habit = item.habit
    current = item.log.value if item.log and item.log.value is not None else 0.0

    with st.form(f"habit_value_{habit.id}", border=False):
        left, right = st.columns([3, 2])
        value = left.number_input(
            habit.unit or "Amount",
            min_value=0.0,
            value=float(current),
            step=1.0,
            label_visibility="collapsed",
        )
        if right.form_submit_button("Save", use_container_width=True):
            run_action(
                "log habit",
                container.habits.log,
                HabitLogInput(habit_id=habit.id, log_date=day, value=float(value)),
                success=f"{habit.name} logged.",
            )


def _time_habit_form(item: HabitTodayRead, day: date) -> None:
    """A clock field for a TIME habit, such as "wake before 06:30"."""
    container = get_container()
    habit = item.habit
    current = item.log.value_time if item.log else habit.target_time

    with st.form(f"habit_time_{habit.id}", border=False):
        left, right = st.columns([3, 2])
        value = left.time_input("Time", value=current, label_visibility="collapsed", step=300)
        if right.form_submit_button("Save", use_container_width=True):
            run_action(
                "log habit",
                container.habits.log,
                HabitLogInput(habit_id=habit.id, log_date=day, value_time=value),
                success=f"{habit.name} logged.",
            )


def _history(habit_id: int, day: date) -> None:
    """The last four weeks of one habit."""
    container = get_container()
    summary = container.habits.streak(habit_id)
    start = day - timedelta(days=STRIP_DAYS - 1)

    completions = container.habits.completion_dates(habit_id, since=start)
    streak_strip(completions, start=start, end=day, key=f"strip_{habit_id}")
    st.caption(
        f"Current {summary.current_streak} · longest {summary.longest_streak} · "
        f"missed {summary.missed_days} · weekly {percent(summary.weekly_consistency)} · "
        f"monthly {percent(summary.monthly_consistency)}"
    )


def _manage_tab() -> None:
    """Edit, archive or delete a habit."""
    container = get_container()
    habits = container.habits.list_habits(active_only=False)
    if not habits:
        empty_state("No habits to manage yet.")
        return

    st.dataframe(
        [
            {
                "Habit": habit.name,
                "Type": habit.habit_type.value.title(),
                "Target": habit.target_label,
                "Frequency": habit.frequency.value.replace("_", " ").title(),
                "Active": "Yes" if habit.is_active else "No",
                "Started": habit.start_date.isoformat() if habit.start_date else "",
            }
            for habit in habits
        ],
        hide_index=True,
        use_container_width=True,
    )

    names = {habit.name: habit for habit in habits}
    chosen = st.selectbox("Habit", list(names))
    habit = names[chosen]

    left, right = st.columns(2)
    with left:
        if habit.is_active and st.button("Archive", use_container_width=True):
            run_action(
                "archive habit",
                container.habits.archive,
                habit.id,
                success=f"{habit.name} archived. Its history is kept.",
            )
    with right:
        if confirm_button(
            "Delete permanently",
            key=f"delete_habit_{habit.id}",
            help_text="This deletes every log for the habit too",
        ):
            run_action(
                "delete habit",
                container.habits.delete,
                habit.id,
                success=f"{habit.name} deleted.",
            )


def _new_habit() -> None:
    """The habit definition form."""
    container = get_container()
    category = category_picker(CategoryKind.HABIT, key="new_habit_category")

    habit_type = enum_select(
        "What kind of habit?",
        members(HabitType),
        key="new_habit_type",
        format_func=lambda value: _HABIT_TYPE_LABELS[value],
    )
    frequency = enum_select("How often?", members(HabitFrequency), key="new_habit_frequency")

    specific_days: list[int] = []
    if frequency is HabitFrequency.SPECIFIC_DAYS:
        specific_days = weekday_multiselect(key="new_habit_days", label="On these days")
    rest_days = weekday_multiselect(key="new_habit_rest", label="Rest days (never a miss)")

    with st.form("new_habit", clear_on_submit=True):
        name = st.text_input("Name", max_chars=120)
        description = st.text_area("Description", height=70)

        target_value: float | None = None
        min_target: float | None = None
        unit: str | None = None
        target_time = None
        direction = HabitDirection.AT_LEAST
        times_per_week: int | None = None

        if habit_type is HabitType.TIME:
            left, right = st.columns(2)
            target_time = left.time_input("Target time", step=300)
            direction = enum_select(
                "Rule",
                [HabitDirection.BEFORE, HabitDirection.AFTER],
                key="new_habit_time_rule",
                parent=right,
            )
        elif habit_type is not HabitType.BOOLEAN:
            left, middle, right = st.columns(3)
            target_value = left.number_input("Target", min_value=0.0, value=20.0, step=1.0)
            min_target = middle.number_input(
                "Minimum that still counts", min_value=0.0, value=0.0, step=1.0
            )
            unit = right.text_input("Unit", value="minutes", max_chars=24)
            direction = enum_select(
                "Rule",
                [HabitDirection.AT_LEAST, HabitDirection.AT_MOST],
                key="new_habit_amount_rule",
            )

        if frequency is HabitFrequency.TIMES_PER_WEEK:
            times_per_week = int(
                st.number_input("Times per week", min_value=1, max_value=7, value=3)
            )

        if st.form_submit_button("Create habit", type="primary") and name.strip():
            run_action(
                "create habit",
                container.habits.create,
                HabitCreate(
                    name=name,
                    description=description or None,
                    category_id=category.id if category else None,
                    habit_type=habit_type,
                    direction=direction,
                    frequency=frequency,
                    target_value=target_value,
                    min_target=min_target or None,
                    unit=unit or None,
                    target_time=target_time,
                    specific_days=specific_days or None,
                    rest_days=rest_days or None,
                    times_per_week=times_per_week,
                    start_date=container.clock.today(),
                ),
                success=f"Created {name.strip()!r}.",
            )


__all__ = ["render"]
