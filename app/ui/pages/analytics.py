"""The analytics page: heatmap, weekly review, monthly trends."""

from __future__ import annotations

import streamlit as st

from app.models.enums import HeatmapMetric, TrendDirection, members
from app.schemas.analytics import HabitPerformanceRead
from app.ui.components.charts import (
    bar_categories,
    calendar_heatmap,
    comparison_bars,
    line_series,
)
from app.ui.components.forms import enum_select
from app.ui.components.metrics import Tile, empty_state, tile_row
from app.ui.formatting import day_label, minutes, percent, score, signed
from app.ui.state import flush_action_message, get_container, set_selected_date

#: Arrows paired with every trend colour, so direction never rests on hue.
_ARROWS = {TrendDirection.UP: "▲", TrendDirection.DOWN: "▼", TrendDirection.FLAT: "▬"}

_METRIC_LABELS = {
    HeatmapMetric.PRODUCTIVITY: "Productivity score",
    HeatmapMetric.HABIT_COMPLETION: "Habits completed",
    HeatmapMetric.TASK_COMPLETION: "Task completion %",
}


def render() -> None:
    """Draw the analytics page."""
    st.title("Analytics")
    flush_action_message()

    heatmap_tab, weekly_tab, monthly_tab = st.tabs(["Calendar", "Weekly review", "Monthly"])
    with heatmap_tab:
        _heatmap()
    with weekly_tab:
        _weekly()
    with monthly_tab:
        _monthly()


def _heatmap() -> None:
    """The twelve-month activity calendar."""
    container = get_container()

    left, right = st.columns([2, 3])
    metric = enum_select(
        "Colour by",
        members(HeatmapMetric),
        key="heatmap_metric",
        format_func=lambda value: _METRIC_LABELS[value],
        parent=left,
    )
    window = right.select_slider("Window", options=[90, 180, 365], value=365)

    heatmap = container.analytics.heatmap(metric, days=int(window))
    calendar_heatmap(heatmap, title=_METRIC_LABELS[metric], key="analytics_heatmap")

    if not heatmap.has_data:
        return

    recorded = [point for point in heatmap.points if point.value is not None]
    st.caption(
        f"{len(recorded)} of {len(heatmap.points)} days have a record. "
        "Blank squares mean nothing was recorded, which is different from a zero."
    )

    best = max(recorded, key=lambda point: point.value or 0)
    chosen = st.selectbox(
        "Open a day",
        [point.day for point in reversed(recorded)],
        format_func=day_label,
        index=0,
    )
    left, right = st.columns(2)
    left.caption("Best day in window")
    left.markdown(f"**{day_label(best.day)}** — scored {best.value:.0f}")
    if right.button("Show this day on the dashboard", use_container_width=True):
        set_selected_date(chosen)
        st.success(f"Selected {day_label(chosen)}. Open the Dashboard to see it.", icon="📅")


def _weekly() -> None:
    """The weekly review."""
    container = get_container()
    review = container.analytics.weekly_review()
    summary = review.summary

    st.subheader(f"Week of {summary.start.isoformat()} to {summary.end.isoformat()}", anchor=False)
    st.info(container.coach.generate_weekly_review(), icon="🗒️")

    tile_row(
        [
            Tile("Weekly score", score(summary.average_score)),
            Tile("Tasks", f"{summary.tasks_completed} / {summary.tasks_total}"),
            Tile("Habit consistency", percent(summary.habit_completion_rate)),
            Tile("Average sleep", minutes(summary.average_sleep_minutes)),
        ]
    )
    st.write("")
    tile_row(
        [
            Tile("Exercise", minutes(summary.exercise_minutes)),
            Tile("Study", minutes(summary.study_minutes)),
            Tile("Coding", minutes(summary.coding_minutes)),
            Tile("Teaching", minutes(summary.teaching_minutes)),
        ]
    )

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("**Wins**")
        for item in review.wins or ["Nothing stood out this week."]:
            st.write(f"• {item}")
    with right:
        st.markdown("**Problems**")
        for item in review.problems or ["Nothing slipped noticeably."]:
            st.write(f"• {item}")

    if review.suggested_focus:
        st.success(f"Suggested focus: {review.suggested_focus}", icon="🎯")

    st.divider()
    st.markdown("**Against last week**")
    st.dataframe(
        [
            {
                "Metric": item.label,
                "Last week": f"{item.previous:,.0f}" if item.previous is not None else "-",
                "This week": f"{item.current:,.0f}" if item.current is not None else "-",
                "Change": f"{_ARROWS[item.direction]} {signed(item.change_percent, '%')}",
            }
            for item in review.comparisons
        ],
        hide_index=True,
        use_container_width=True,
    )

    if review.previous:
        comparison_bars(
            {
                "Study": review.previous.study_minutes,
                "Coding": review.previous.coding_minutes,
                "Teaching": review.previous.teaching_minutes,
                "Exercise": review.previous.exercise_minutes,
            },
            {
                "Study": summary.study_minutes,
                "Coding": summary.coding_minutes,
                "Teaching": summary.teaching_minutes,
                "Exercise": summary.exercise_minutes,
            },
            title="Minutes, week on week",
            key="weekly_comparison",
            labels=("Last week", "This week"),
        )

    _habit_table(review.habit_performance)

    if review.insights:
        st.markdown("**Insights**")
        for insight in review.insights:
            st.write(f"• {insight.message}")
    if review.recommendations:
        st.markdown("**Suggestions**")
        for recommendation in review.recommendations:
            with st.container(border=True):
                st.write(recommendation.message)
                st.caption(recommendation.rationale)


def _monthly() -> None:
    """Monthly trends and the best and worst days."""
    container = get_container()
    review = container.analytics.monthly_review()
    summary = review.summary

    st.subheader(summary.start.strftime("%B %Y"), anchor=False)
    if not review.score_series:
        empty_state("No scored days this month yet.")
        return

    tile_row(
        [
            Tile("Average score", score(summary.average_score)),
            Tile("Tracked", minutes(summary.tracked_minutes)),
            Tile("Best day", day_label(review.best_day.day) if review.best_day else "-"),
            Tile("Toughest day", day_label(review.worst_day.day) if review.worst_day else "-"),
        ]
    )
    st.write("")

    line_series(
        {"Daily score": review.score_series},
        title="Score through the month",
        key="monthly_score",
        y_title="Score",
    )

    weekday_names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    bar_categories(
        {weekday_names[day]: value for day, value in review.weekday_averages.items()},
        title="Average score by day of week",
        key="monthly_weekday",
        as_duration=False,
    )

    if review.weekly_buckets:
        st.dataframe(
            [
                {
                    "Week": bucket.key,
                    "From": bucket.start.isoformat(),
                    "Average score": f"{bucket.average:.0f}" if bucket.average else "-",
                    "Days recorded": bucket.days_with_data,
                }
                for bucket in review.weekly_buckets
            ],
            hide_index=True,
            use_container_width=True,
        )

    _habit_table(review.habit_performance)

    for insight in review.insights:
        st.write(f"• {insight.message}")


def _habit_table(performance: list[HabitPerformanceRead]) -> None:
    """Per-habit performance, weakest first."""
    if not performance:
        return
    st.markdown("**Habit performance**")
    st.dataframe(
        [
            {
                "Habit": item.name,
                "Completed": f"{item.completed} / {item.expected}",
                "Rate": percent(item.completion_rate),
                "Current streak": item.current_streak,
                "Longest": item.longest_streak,
            }
            for item in performance
        ],
        hide_index=True,
        use_container_width=True,
    )


__all__ = ["render"]
