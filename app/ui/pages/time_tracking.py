"""The time-tracking page."""

from __future__ import annotations

import streamlit as st

from app.models.enums import CategoryKind
from app.schemas.activity import TimeEntryFilter, TimeEntryInput
from app.schemas.common import DateRange, Pagination
from app.ui.components.charts import donut_allocation, stacked_days
from app.ui.components.forms import category_picker, duration_input, period_picker, time_pair
from app.ui.components.metrics import Tile, empty_state, tile_row
from app.ui.formatting import minutes, percent
from app.ui.state import date_navigator, flush_action_message, get_container, run_action

PAGE_SIZE = 25


def render() -> None:
    """Draw the time-tracking page."""
    st.title("Time tracking")
    flush_action_message()

    log_tab, allocation_tab, history_tab = st.tabs(["Log time", "Allocation", "History"])
    with log_tab:
        _log()
    with allocation_tab:
        _allocation()
    with history_tab:
        _history()


def _log() -> None:
    """Record a block of time."""
    container = get_container()
    day = date_navigator()

    category = category_picker(CategoryKind.TIME, key="time_category")
    if category is None:
        return

    start, end = time_pair(key="time_times")
    duration = duration_input(key="time_duration", default=60)
    description = st.text_input("What were you working on?", max_chars=255)

    if st.button("Log time", type="primary"):
        run_action(
            "log time",
            container.time_tracking.log,
            TimeEntryInput(
                log_date=day,
                category_id=category.id,
                start_time=start,
                end_time=end,
                duration_minutes=None if start and end else float(duration),
                description=description or None,
            ),
            success=f"{int(duration)} minutes of {category.name} logged.",
        )

    st.divider()
    entries = container.time_tracking.list_for_day(day)
    if not entries:
        st.caption("Nothing tracked for this day yet.")
        return

    lookup = container.categories.name_lookup(CategoryKind.TIME)
    total = sum(entry.duration_minutes for entry in entries)
    st.caption(f"{minutes(total)} tracked on {day.isoformat()}")

    for entry in entries:
        left, right = st.columns([5, 1], vertical_alignment="center")
        left.write(f"**{lookup.get(entry.category_id, '?')}** · {minutes(entry.duration_minutes)}")
        if entry.description:
            left.caption(entry.description)
        if right.button("Delete", key=f"del_time_{entry.id}", use_container_width=True):
            run_action(
                "delete time entry",
                container.time_tracking.delete,
                entry.id,
                success="Entry deleted.",
            )


def _allocation() -> None:
    """Where the time went across a period."""
    container = get_container()
    period = period_picker(key="time_period", default_days=30)
    allocation = container.time_tracking.allocation_read(period)

    if not allocation.slices:
        empty_state("Nothing tracked in this period.")
        return

    tile_row(
        [
            Tile("Tracked", minutes(allocation.total_minutes)),
            Tile("Productive", minutes(allocation.productive_minutes)),
            Tile("Productive share", percent(allocation.productive_share)),
            Tile("Per day", minutes(allocation.total_minutes / period.days)),
        ]
    )
    st.write("")

    left, right = st.columns([2, 3])
    with left:
        donut_allocation(
            {item.category_name: item.minutes for item in allocation.slices},
            title="Share of tracked time",
            key="time_donut",
            centre_label=minutes(allocation.total_minutes),
        )
    with right:
        _stacked(period)

    st.dataframe(
        [
            {
                "Category": item.category_name,
                "Time": minutes(item.minutes),
                "Share": percent(item.share),
                "Productive": "Yes" if item.is_productive else "No",
            }
            for item in allocation.slices
        ],
        hide_index=True,
        use_container_width=True,
    )


def _stacked(period: DateRange) -> None:
    """Per-day stacked minutes for the biggest categories."""
    container = get_container()
    entries = container.time_tracking.search(
        TimeEntryFilter(
            date_from=period.start,
            date_to=period.end,
            pagination=Pagination(limit=500),
        )
    )
    if not entries.items:
        return

    lookup = container.categories.name_lookup(CategoryKind.TIME)
    days = sorted({entry.log_date for entry in entries.items})
    totals: dict[str, float] = {}
    for entry in entries.items:
        name = lookup.get(entry.category_id, "Other")
        totals[name] = totals.get(name, 0.0) + entry.duration_minutes

    top = [name for name, _ in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:5]]
    series: dict[str, list[float]] = {name: [0.0] * len(days) for name in top}
    index = {day: position for position, day in enumerate(days)}

    for entry in entries.items:
        name = lookup.get(entry.category_id, "Other")
        if name in series:
            series[name][index[entry.log_date]] += entry.duration_minutes

    stacked_days(days, series, title="Daily breakdown (top categories)", key="time_stacked")


def _history() -> None:
    """Filtered, paginated entries."""
    container = get_container()
    period = period_picker(key="time_history_period", default_days=30)
    search = st.text_input("Search descriptions", placeholder="e.g. FastAPI")
    page_number = st.number_input("Page", min_value=1, value=1, step=1)

    page = container.time_tracking.search(
        TimeEntryFilter(
            date_from=period.start,
            date_to=period.end,
            search=search or None,
            pagination=Pagination(limit=PAGE_SIZE, offset=(int(page_number) - 1) * PAGE_SIZE),
        )
    )
    if not page.items:
        empty_state("No entries match.")
        return

    lookup = container.categories.name_lookup(CategoryKind.TIME)
    st.caption(f"{page.total} entries · page {page.page_number} of {page.page_count}")
    st.dataframe(
        [
            {
                "Date": entry.log_date.isoformat(),
                "Category": lookup.get(entry.category_id, ""),
                "Time": minutes(entry.duration_minutes),
                "Description": entry.description or "",
            }
            for entry in page.items
        ],
        hide_index=True,
        use_container_width=True,
    )


__all__ = ["render"]
