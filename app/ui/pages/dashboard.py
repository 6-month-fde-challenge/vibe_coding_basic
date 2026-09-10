"""The daily dashboard.

Answers the three questions the product exists to answer, in order: what
did I do, where did the time go, and am I improving. Every figure on this
page comes from one call to
:meth:`~app.services.analytics_service.AnalyticsService.dashboard`, so the
page is a layout and nothing else.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from app.models.enums import CategoryKind
from app.schemas.common import DateRange
from app.schemas.dashboard import DashboardView
from app.ui.components.charts import donut_allocation, line_series
from app.ui.components.metrics import Tile, empty_state, hero_score, score_breakdown, tile_row
from app.ui.formatting import day_label, minutes, ratio, target_gap
from app.ui.state import date_navigator, flush_action_message, get_container, run_action
from app.ui.theme import score_status

#: How much recent history the trend strip shows.
TREND_DAYS = 14


def render() -> None:
    """Draw the dashboard."""
    container = get_container()
    st.title("Dashboard")
    flush_action_message()

    day = date_navigator()
    view = container.analytics.dashboard(day)

    st.caption(day_label(day))
    if not view.summary.has_any_data:
        empty_state(
            "Nothing recorded for this day yet.",
            "Use Quick add below, or run `python scripts/seed_data.py` for a demo dataset.",
        )

    _overview(view)
    st.divider()
    _quick_add(day)
    st.divider()

    left, right = st.columns([3, 2])
    with left:
        _trend(day)
        _timeline(view)
    with right:
        _allocation(view)
        _habits(view)

    st.divider()
    _insights(day)


def _overview(view: DashboardView) -> None:
    """The score plus the day's headline numbers."""
    summary = view.summary
    profile = get_container().health.get_profile()

    score_column, tiles_column = st.columns([1, 3])
    with score_column:
        hero_score(summary.score.total if summary.score.has_data else None)
        with st.popover("How is this scored?", use_container_width=True):
            score_breakdown(summary.score)

    with tiles_column:
        tile_row(
            [
                Tile(
                    "Sleep",
                    minutes(summary.sleep_minutes),
                    target_gap(summary.sleep_minutes, profile.target_sleep_minutes),
                    _status_for(summary.sleep_minutes, profile.target_sleep_minutes),
                ),
                Tile(
                    "Tasks",
                    ratio(summary.tasks.completed, summary.tasks.total),
                    f"{summary.tasks.overdue} overdue"
                    if summary.tasks.overdue
                    else "nothing overdue",
                    score_status(summary.tasks.rate * 100 if summary.tasks.total else None),
                ),
                Tile(
                    "Habits",
                    ratio(summary.habits.completed, summary.habits.due),
                    "due today",
                    score_status(summary.habits.rate * 100 if summary.habits.due else None),
                ),
                Tile(
                    "Exercise",
                    minutes(summary.exercise_minutes),
                    target_gap(summary.exercise_minutes, profile.target_exercise_minutes),
                    _status_for(summary.exercise_minutes, profile.target_exercise_minutes),
                ),
            ]
        )
        st.write("")
        tile_row(
            [
                Tile(
                    "Studying",
                    minutes(summary.study_minutes),
                    target_gap(summary.study_minutes, profile.target_study_minutes),
                    _status_for(summary.study_minutes, profile.target_study_minutes),
                ),
                Tile(
                    "Coding",
                    minutes(summary.coding_minutes),
                    target_gap(summary.coding_minutes, profile.target_coding_minutes),
                    _status_for(summary.coding_minutes, profile.target_coding_minutes),
                ),
                Tile(
                    "Teaching",
                    minutes(summary.teaching_minutes),
                    target_gap(summary.teaching_minutes, profile.target_teaching_minutes),
                    _status_for(summary.teaching_minutes, profile.target_teaching_minutes),
                ),
                Tile(
                    "Free time",
                    minutes(summary.free_minutes),
                    "outside sleep and tracked time",
                ),
            ]
        )

    if view.health.is_available:
        st.caption(
            f"Estimated BMR {view.health.bmr_kcal} kcal, TDEE {view.health.tdee_kcal} kcal. "
            f"{view.health.note}"
        )


def _quick_add(day: date) -> None:
    """The fast-entry strip.

    Tracking has to take less time than the activity being tracked, so the
    four most common records are one field and one click each.
    """
    container = get_container()
    st.subheader("Quick add", anchor=False)

    task_col, time_col, sleep_col = st.columns([2, 2, 2])

    with task_col, st.form("quick_task", clear_on_submit=True, border=False):
        title = st.text_input("Task", placeholder="Write the README", label_visibility="collapsed")
        if st.form_submit_button("Add task", use_container_width=True) and title.strip():
            run_action(
                "quick add task",
                container.tasks.quick_add,
                title,
                day=day,
                success=f"Added {title.strip()!r}.",
            )

    with time_col, st.form("quick_time", clear_on_submit=True, border=False):
        categories = container.categories.list_kind(CategoryKind.TIME)
        names = [category.name for category in categories]
        inner_left, inner_right = st.columns([3, 2])
        chosen = inner_left.selectbox("Category", names, label_visibility="collapsed")
        amount = inner_right.number_input(
            "Minutes", min_value=5, max_value=720, value=60, step=15, label_visibility="collapsed"
        )
        if st.form_submit_button("Log time", use_container_width=True) and chosen:
            run_action(
                "quick add time",
                container.time_tracking.quick_add,
                chosen,
                float(amount),
                day=day,
                success=f"Logged {int(amount)} minutes of {chosen}.",
            )

    with sleep_col, st.form("quick_sleep", clear_on_submit=False, border=False):
        inner_left, inner_right = st.columns(2)
        asleep = inner_left.text_input(
            "Slept", value="23:20", label_visibility="collapsed", placeholder="23:20"
        )
        woke = inner_right.text_input(
            "Woke", value="06:30", label_visibility="collapsed", placeholder="06:30"
        )
        if st.form_submit_button("😴 Log sleep", use_container_width=True):
            run_action(
                "quick log sleep",
                container.sleep.quick_log,
                asleep,
                woke,
                day=day,
                success=f"Sleep recorded for {day.isoformat()}.",
            )


def _trend(day: date) -> None:
    """A fortnight of daily scores."""
    container = get_container()
    period = DateRange(start=day - timedelta(days=TREND_DAYS - 1), end=day)
    points = container.analytics.score_series(period)

    st.subheader("Recent scores", anchor=False)
    if not points:
        st.caption("No scored days yet in this window.")
        return
    line_series({"Daily score": points}, title="", key="dash_trend", y_title="Score", height=240)


def _timeline(view: DashboardView) -> None:
    """The chronological day."""
    st.subheader("Timeline", anchor=False)
    if not view.timeline:
        st.caption("Record start and end times on an activity to build a timeline.")
        return

    rows = [
        {
            "Time": item.at.strftime("%H:%M"),
            "What": item.label,
            "Detail": item.detail or "",
            "Length": minutes(item.minutes) if item.minutes else "",
        }
        for item in view.timeline
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)


def _allocation(view: DashboardView) -> None:
    """Where the tracked time went."""
    st.subheader("Time allocation", anchor=False)
    allocation = view.allocation
    if not allocation.slices:
        st.caption("Nothing tracked today.")
        return

    donut_allocation(
        {item.category_name: item.minutes for item in allocation.slices},
        title="",
        key="dash_allocation",
        centre_label=minutes(allocation.total_minutes),
        height=280,
    )
    # The table view is the relief for the palette's contrast warning, and
    # is genuinely the faster read for exact figures.
    st.dataframe(
        [
            {
                "Category": item.category_name,
                "Time": minutes(item.minutes),
                "Share": f"{item.share * 100:.0f}%",
                "Productive": "Yes" if item.is_productive else "No",
            }
            for item in allocation.slices
        ],
        hide_index=True,
        use_container_width=True,
    )


def _habits(view: DashboardView) -> None:
    """Today's habits, tickable in place."""
    container = get_container()
    st.subheader("Habits today", anchor=False)

    due = [item for item in view.habits_today if item.is_due_today]
    if not due:
        st.caption("No habits due today.")
        return

    for item in due:
        left, right = st.columns([4, 1], vertical_alignment="center")
        streak = item.streak.current_streak
        flame = f" 🔥 {streak}" if streak else ""
        left.write(f"{'✅' if item.is_done else '⬜'} **{item.habit.name}**{flame}")
        left.caption(item.habit.target_label)

        if item.habit.habit_type.is_measured:
            # Measured habits need a number, which belongs on the Habits
            # page rather than crammed into a dashboard row.
            right.caption("on Habits")
        elif right.button(
            "Undo" if item.is_done else "Done",
            key=f"dash_habit_{item.habit.id}",
            use_container_width=True,
        ):
            run_action(
                "toggle habit",
                container.habits.toggle,
                item.habit.id,
                view.summary.log_date,
                success=f"{item.habit.name} updated.",
            )


def _insights(day: date) -> None:
    """Rule-based observations and nudges for the current week."""
    container = get_container()
    period = DateRange.last_n_days(day, 7)

    insights = container.insights.insights(period)
    recommendations = container.insights.recommendations(period)
    if not insights and not recommendations:
        return

    st.subheader("What the data says", anchor=False)
    left, right = st.columns(2)
    with left:
        for insight in insights:
            st.write(f"• {insight.message}")
    with right:
        for item in recommendations:
            with st.container(border=True):
                st.write(item.message)
                st.caption(item.rationale)


def _status_for(actual: float | None, target: float | None) -> str | None:
    """Map an actual-against-target pair to a status role."""
    if actual is None or not target:
        return None
    return score_status(min(100.0, (actual / target) * 100.0))
