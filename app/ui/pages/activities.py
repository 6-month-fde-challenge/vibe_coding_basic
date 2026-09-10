"""The activities page: exercise and sport."""

from __future__ import annotations

import streamlit as st

from app.models.enums import ActivityIntensity, CategoryKind, members
from app.schemas.activity import ActivityInput
from app.ui.components.charts import bar_categories
from app.ui.components.forms import (
    category_picker,
    duration_input,
    enum_select,
    period_picker,
    time_pair,
)
from app.ui.components.metrics import Tile, empty_state, tile_row
from app.ui.formatting import minutes
from app.ui.state import date_navigator, flush_action_message, get_container, run_action


def render() -> None:
    """Draw the activities page."""
    st.title("Activities")
    st.caption(
        "Activity types are categories you control - rename or add one in Settings and "
        "it appears here. Nothing in the code knows what cricket is."
    )
    flush_action_message()

    log_tab, history_tab = st.tabs(["Log activity", "History"])
    with log_tab:
        _log()
    with history_tab:
        _history()


def _log() -> None:
    """Record a bout of activity."""
    container = get_container()
    day = date_navigator()

    category = category_picker(CategoryKind.ACTIVITY, key="activity_category")
    if category is None:
        return

    start, end = time_pair(key="activity_times")
    duration = duration_input(key="activity_duration", default=45)

    left, right = st.columns(2)
    intensity = enum_select(
        "Intensity",
        members(ActivityIntensity),
        key="activity_intensity",
        current=ActivityIntensity.MODERATE,
        parent=left,
    )
    estimate = right.checkbox(
        "Estimate calories",
        help="Uses your latest weight and a MET model. A rough figure, not a measurement.",
    )
    notes = st.text_area("Notes", height=70)

    if st.button("Log activity", type="primary"):
        run_action(
            "log activity",
            container.activities.log,
            ActivityInput(
                log_date=day,
                category_id=category.id,
                start_time=start,
                end_time=end,
                duration_minutes=None if start and end else float(duration),
                intensity=intensity,
                estimate_calories=estimate,
                notes=notes or None,
            ),
            success=f"{category.name} logged.",
        )

    st.divider()
    today_rows = container.activities.list_for_day(day)
    if not today_rows:
        st.caption("Nothing logged for this day yet.")
        return

    lookup = container.categories.name_lookup(CategoryKind.ACTIVITY)
    for row in today_rows:
        left, right = st.columns([5, 1], vertical_alignment="center")
        left.write(
            f"**{lookup.get(row.category_id, 'Activity')}** · {minutes(row.duration_minutes)} · "
            f"{row.intensity.value.title()}"
        )
        if row.notes:
            left.caption(row.notes)
        if right.button("Delete", key=f"del_activity_{row.id}", use_container_width=True):
            run_action(
                "delete activity",
                container.activities.delete,
                row.id,
                success="Activity deleted.",
            )


def _history() -> None:
    """Totals across a period."""
    container = get_container()
    period = period_picker(key="activity_period", default_days=30)
    summary = container.activities.summary(period)

    if not summary.has_data:
        empty_state("No activity recorded in this period.")
        return

    tile_row(
        [
            Tile("Sessions", str(summary.sessions)),
            Tile("Total", minutes(summary.total_minutes)),
            Tile("Active days", str(summary.active_days)),
            Tile("Longest session", minutes(summary.longest_session_minutes)),
        ]
    )
    st.write("")

    bar_categories(
        dict(summary.minutes_by_category),
        title="Minutes by activity",
        key="activity_by_category",
    )

    st.dataframe(
        [{"Activity": name, "Time": minutes(value)} for name, value in summary.minutes_by_category],
        hide_index=True,
        use_container_width=True,
    )

    if summary.total_calories:
        st.caption(
            f"Estimated {summary.total_calories:,.0f} kcal across the period. "
            "Calorie figures are model estimates, not measurements."
        )


__all__ = ["render"]
