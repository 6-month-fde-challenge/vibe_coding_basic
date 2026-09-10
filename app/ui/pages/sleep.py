"""The sleep page."""

from __future__ import annotations

from datetime import time

import streamlit as st

from app.schemas.analytics import SeriesPoint
from app.schemas.sleep import SleepInput
from app.ui.components.charts import line_series
from app.ui.components.forms import period_picker
from app.ui.components.metrics import Tile, empty_state, tile_row
from app.ui.formatting import clock, minutes, score
from app.ui.state import date_navigator, flush_action_message, get_container, run_action


def render() -> None:
    """Draw the sleep page."""
    st.title("Sleep")
    flush_action_message()

    log_tab, trends_tab = st.tabs(["Log a night", "Trends"])
    with log_tab:
        _log()
    with trends_tab:
        _trends()


def _log() -> None:
    """Record or correct one night."""
    container = get_container()
    day = date_navigator("Woke up on")
    existing = container.sleep.get_for_date(day)

    if existing:
        st.info(
            f"Recorded: {minutes(existing.duration_minutes)} "
            f"(quality {existing.quality or '-'}/10). Saving again replaces it.",
            icon="🌙",
        )

    with st.form("sleep_form"):
        left, middle, right = st.columns(3)
        bedtime = left.time_input("Got into bed", value=time(23, 0), step=300)
        asleep = middle.time_input("Fell asleep", value=time(23, 30), step=300)
        woke = right.time_input("Woke up", value=time(6, 30), step=300)

        quality_col, interruptions_col = st.columns(2)
        current_quality = existing.quality if existing else None
        quality = quality_col.slider("Quality", 1, 10, current_quality or 7)
        interruptions = interruptions_col.number_input(
            "Interruptions",
            min_value=0,
            max_value=20,
            value=existing.interruptions if existing else 0,
        )
        notes = st.text_area("Notes", value=(existing.notes if existing else "") or "", height=70)

        st.caption(
            "Times are wall-clock. A wake time earlier than the sleep time simply means "
            "the night crossed midnight - no special handling needed."
        )

        if st.form_submit_button("Save night", type="primary"):
            run_action(
                "record sleep",
                container.sleep.record,
                SleepInput(
                    log_date=day,
                    bedtime=bedtime,
                    sleep_time=asleep,
                    wake_time=woke,
                    quality=int(quality),
                    interruptions=int(interruptions),
                    notes=notes or None,
                ),
                success=f"Sleep saved for {day.isoformat()}.",
            )

    if existing and st.button("Delete this night"):
        run_action(
            "delete sleep",
            container.sleep.delete,
            day,
            success="Night deleted.",
        )


def _trends() -> None:
    """Averages, consistency and drift."""
    container = get_container()
    period = period_picker(key="sleep_period", default_days=30)
    stats = container.sleep.stats(period)

    if not stats.nights:
        empty_state("No nights recorded in this period.")
        return

    debt_hours = stats.sleep_debt_minutes / 60
    tile_row(
        [
            Tile("Nights", str(stats.nights)),
            Tile(
                "Average", minutes(stats.average_minutes), f"target {minutes(stats.target_minutes)}"
            ),
            Tile("7-day", minutes(stats.average_7d)),
            Tile("30-day", minutes(stats.average_30d)),
        ]
    )
    st.write("")
    tile_row(
        [
            Tile("Consistency", score(stats.consistency_score), "100 = identical nights"),
            Tile(
                "Sleep debt",
                f"{debt_hours:+.1f}h",
                "positive is a deficit against target",
                "critical" if debt_hours > 5 else "good",
            ),
            Tile(
                "Typical bedtime",
                clock(stats.median_bedtime),
                _variance(stats.bedtime_variance_minutes),
            ),
            Tile("Typical wake", clock(stats.median_wake), _variance(stats.wake_variance_minutes)),
        ]
    )

    st.divider()
    records = container.sleep.list_between(period)
    line_series(
        {
            "Sleep": [
                SeriesPoint(day=record.log_date, value=record.duration_minutes)
                for record in records
            ]
        },
        title="Nightly duration",
        key="sleep_duration",
        y_title="Minutes",
        as_duration=True,
    )

    st.dataframe(
        [
            {
                "Date": record.log_date.isoformat(),
                "Slept": minutes(record.duration_minutes),
                "Quality": record.quality or "",
                "Interruptions": record.interruptions,
                "Notes": record.notes or "",
            }
            for record in reversed(records)
        ],
        hide_index=True,
        use_container_width=True,
    )


def _variance(value: float | None) -> str:
    """Describe how much a clock time moves around."""
    if value is None:
        return "not enough nights"
    return f"±{value:.0f} min spread"


__all__ = ["render"]
