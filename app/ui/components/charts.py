"""The chart layer.

Rules that hold for every figure in this module, so no page has to
remember them:

* One y-axis, ever. Two measures of different scale become two charts.
* Categorical colour follows the entity, not its rank, so filtering never
  repaints the survivors.
* Sequential magnitude is one hue, light to dark - never a rainbow.
* Thin marks, hairline grid, a legend whenever two or more series share a
  plot, and direct labels used selectively rather than on every point.
* Every chart is paired with a table view by its caller when its colours
  are below the contrast floor, so identity never rests on colour alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

from app.core.timeutils import format_duration
from app.schemas.analytics import HeatmapRead, SeriesPoint
from app.ui.theme import MAX_SEGMENTS, Palette, active_palette, plotly_layout, series_colors

#: Line weight and marker size, per the mark spec.
_LINE_WIDTH = 2
_MARKER_SIZE = 8
#: Gap drawn in the surface colour between adjacent fills.
_FILL_GAP = 2

_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _render(figure: go.Figure, key: str) -> None:
    """Show a figure with the app's standard configuration."""
    st.plotly_chart(
        figure,
        use_container_width=True,
        key=key,
        config={"displayModeBar": False, "responsive": True},
    )


def line_series(
    series: Mapping[str, Sequence[SeriesPoint]],
    *,
    title: str,
    key: str,
    y_title: str = "",
    height: int = 300,
    as_duration: bool = False,
) -> None:
    """Plot one or more daily series over time.

    Args:
        series: Name to points. Gaps in the data stay gaps - a missing day
            is not joined through, because that would draw data that does
            not exist.
        title: Chart title.
        key: Unique Streamlit key.
        y_title: Axis label.
        height: Chart height in pixels.
        as_duration: Format hover values as durations rather than numbers.
    """
    palette = active_palette()
    colours = series_colors(list(series), palette)

    figure = go.Figure()
    for name, points in series.items():
        if not points:
            continue
        figure.add_trace(
            go.Scatter(
                x=[point.day for point in points],
                y=[point.value for point in points],
                name=name,
                mode="lines+markers",
                connectgaps=False,
                line={"width": _LINE_WIDTH, "color": colours[name], "shape": "linear"},
                marker={
                    "size": _MARKER_SIZE,
                    "color": colours[name],
                    "line": {"width": _FILL_GAP, "color": palette.surface},
                },
                hovertemplate=(
                    f"<b>{name}</b><br>%{{x|%a %d %b}}<br>"
                    + ("%{customdata}" if as_duration else "%{y:.1f}")
                    + "<extra></extra>"
                ),
                customdata=[format_duration(point.value) for point in points]
                if as_duration
                else None,
            )
        )

    if not figure.data:
        st.caption("Nothing recorded in this period yet.")
        return

    layout = plotly_layout(palette, height=height)
    layout["title"] = {"text": title, "font": {"size": 14, "color": palette.text_secondary}}
    layout["yaxis"]["title"]["text"] = y_title
    layout["hovermode"] = "x unified"
    layout["showlegend"] = len(figure.data) > 1
    figure.update_layout(**layout)
    _render(figure, key)


def bar_categories(
    values: Mapping[str, float],
    *,
    title: str,
    key: str,
    y_title: str = "",
    height: int = 300,
    as_duration: bool = True,
    highlight: str | None = None,
) -> None:
    """Compare a handful of named quantities.

    One series means one colour for every bar. Colouring bars darker where
    bigger would double-encode the length that is already on screen, so
    emphasis is done by greying the rest instead.
    """
    if not values:
        st.caption("Nothing recorded in this period yet.")
        return

    palette = active_palette()
    ordered = sorted(values.items(), key=lambda item: item[1], reverse=True)
    names = [name for name, _ in ordered]
    amounts = [amount for _, amount in ordered]

    if highlight is None:
        colours = [palette.slot(0)] * len(names)
    else:
        colours = [palette.slot(0) if name == highlight else palette.grid for name in names]

    figure = go.Figure(
        go.Bar(
            x=amounts,
            y=names,
            orientation="h",
            marker={"color": colours, "cornerradius": 4},
            text=[format_duration(value) if as_duration else f"{value:,.0f}" for value in amounts],
            textposition="outside",
            textfont={"color": palette.text_secondary, "size": 11},
            hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
        )
    )

    layout = plotly_layout(palette, height=height)
    layout["title"] = {"text": title, "font": {"size": 14, "color": palette.text_secondary}}
    layout["xaxis"]["title"]["text"] = y_title
    layout["yaxis"]["autorange"] = "reversed"
    layout["yaxis"]["gridcolor"] = "rgba(0,0,0,0)"
    layout["bargap"] = 0.35
    layout["showlegend"] = False
    figure.update_layout(**layout)
    _render(figure, key)


def donut_allocation(
    values: Mapping[str, float],
    *,
    title: str,
    key: str,
    height: int = 320,
    centre_label: str = "",
) -> None:
    """Show a part-to-whole split at a glance.

    Capped at six segments: past that, adjacent slices blur and the tail is
    folded into "Other". Each slice is direct-labelled, which is also the
    relief the palette's contrast warning requires.
    """
    if not values:
        st.caption("No time tracked in this period yet.")
        return

    palette = active_palette()
    ordered = sorted(values.items(), key=lambda item: item[1], reverse=True)
    head = ordered[: MAX_SEGMENTS - 1] if len(ordered) > MAX_SEGMENTS else ordered
    tail = ordered[MAX_SEGMENTS - 1 :] if len(ordered) > MAX_SEGMENTS else []
    if tail:
        head = [*head, ("Other", sum(amount for _, amount in tail))]

    names = [name for name, _ in head]
    amounts = [amount for _, amount in head]
    colours = series_colors(names, palette)

    figure = go.Figure(
        go.Pie(
            labels=names,
            values=amounts,
            hole=0.62,
            sort=False,
            direction="clockwise",
            marker={
                "colors": [colours[name] for name in names],
                "line": {"color": palette.surface, "width": _FILL_GAP},
            },
            textinfo="label+percent",
            textposition="outside",
            textfont={"color": palette.text_secondary, "size": 11},
            hovertemplate="<b>%{label}</b><br>%{customdata}<br>%{percent}<extra></extra>",
            customdata=[format_duration(value) for value in amounts],
        )
    )

    layout = plotly_layout(palette, height=height)
    layout["title"] = {"text": title, "font": {"size": 14, "color": palette.text_secondary}}
    layout["showlegend"] = False
    if centre_label:
        layout["annotations"] = [
            {
                "text": centre_label,
                "showarrow": False,
                "font": {"size": 15, "color": palette.text_primary},
            }
        ]
    figure.update_layout(**layout)
    _render(figure, key)


def calendar_heatmap(
    heatmap: HeatmapRead,
    *,
    title: str,
    key: str,
    height: int = 220,
) -> None:
    """Draw the GitHub-style activity calendar.

    Magnitude, so one hue light to dark. Days with no record are left as
    gaps rather than coloured as zeros - "did nothing" and "recorded
    nothing" are different facts.
    """
    if not heatmap.has_data:
        st.caption("No history to chart yet. Log a few days and this fills in.")
        return

    palette = active_palette()
    weeks = max(point.week_index for point in heatmap.points) + 1
    grid: list[list[float | None]] = [[None] * weeks for _ in range(7)]
    labels: list[list[str]] = [[""] * weeks for _ in range(7)]

    for point in heatmap.points:
        grid[point.weekday][point.week_index] = point.value
        shown = "no record" if point.value is None else f"{point.value:.0f}"
        labels[point.weekday][point.week_index] = f"{point.day:%a %d %b %Y}<br>{shown}"

    colourscale = [
        [index / (len(palette.sequential) - 1), colour]
        for index, colour in enumerate(palette.sequential)
    ]

    figure = go.Figure(
        go.Heatmap(
            z=grid,
            text=labels,
            hovertemplate="%{text}<extra></extra>",
            colorscale=colourscale,
            showscale=True,
            xgap=3,
            ygap=3,
            zmin=0,
            zmax=max(heatmap.max_value, 1.0),
            colorbar={
                "thickness": 8,
                "len": 0.7,
                "outlinewidth": 0,
                "tickfont": {"color": palette.muted, "size": 10},
            },
            hoverongaps=False,
        )
    )

    layout = plotly_layout(palette, height=height)
    layout["title"] = {"text": title, "font": {"size": 14, "color": palette.text_secondary}}
    # A calendar has no axes to speak of: the squares are the chart. Every
    # rule, tick and gridline is turned off so nothing competes with them.
    layout["yaxis"] = {
        **layout["yaxis"],
        "tickmode": "array",
        "tickvals": list(range(7)),
        "ticktext": list(_WEEKDAY_LABELS),
        "autorange": "reversed",
        "showgrid": False,
        "zeroline": False,
        "showline": False,
        "ticks": "",
    }
    layout["xaxis"] = {
        **layout["xaxis"],
        "showticklabels": False,
        "showgrid": False,
        "zeroline": False,
        "showline": False,
        "ticks": "",
    }
    figure.update_layout(**layout)
    _render(figure, key)


def streak_strip(
    completions: Sequence[date],
    *,
    start: date,
    end: date,
    key: str,
    height: int = 90,
) -> None:
    """Draw one habit's last few weeks as a row of squares."""
    palette = active_palette()
    done = set(completions)
    days: list[date] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)

    if not days:
        return

    figure = go.Figure(
        go.Bar(
            x=[f"{day:%d}" for day in days],
            y=[1] * len(days),
            marker={
                "color": [palette.slot(0) if day in done else palette.grid for day in days],
                "cornerradius": 3,
                "line": {"width": _FILL_GAP, "color": palette.surface},
            },
            hovertext=[f"{day:%a %d %b} - {'done' if day in done else 'missed'}" for day in days],
            hovertemplate="%{hovertext}<extra></extra>",
        )
    )

    layout = plotly_layout(palette, height=height)
    layout["margin"] = {"l": 0, "r": 0, "t": 4, "b": 4}
    layout["showlegend"] = False
    layout["yaxis"] = {**layout["yaxis"], "visible": False, "showgrid": False}
    layout["xaxis"] = {**layout["xaxis"], "showgrid": False, "tickfont": {"size": 9}}
    layout["bargap"] = 0.25
    figure.update_layout(**layout)
    _render(figure, key)


def comparison_bars(
    previous: Mapping[str, float],
    current: Mapping[str, float],
    *,
    title: str,
    key: str,
    height: int = 320,
    labels: tuple[str, str] = ("Previous", "Current"),
) -> None:
    """Compare the same metrics across two periods.

    Two series on one axis, in the first two categorical slots, with a
    legend - never two y-scales.
    """
    names = [name for name in current if name in previous]
    if not names:
        st.caption("Not enough history to compare periods yet.")
        return

    palette = active_palette()
    figure = go.Figure()
    for index, (label, values) in enumerate(((labels[0], previous), (labels[1], current))):
        figure.add_trace(
            go.Bar(
                name=label,
                x=names,
                y=[values.get(name, 0.0) for name in names],
                marker={
                    "color": palette.slot(index),
                    "cornerradius": 4,
                    "line": {"width": _FILL_GAP, "color": palette.surface},
                },
                hovertemplate=f"<b>{label}</b><br>%{{x}}: %{{y:,.0f}}<extra></extra>",
            )
        )

    layout = plotly_layout(palette, height=height)
    layout["title"] = {"text": title, "font": {"size": 14, "color": palette.text_secondary}}
    layout["barmode"] = "group"
    layout["bargap"] = 0.3
    layout["bargroupgap"] = 0.08
    figure.update_layout(**layout)
    _render(figure, key)


def stacked_days(
    days: Sequence[date],
    series: Mapping[str, Sequence[float]],
    *,
    title: str,
    key: str,
    height: int = 320,
) -> None:
    """Stack per-category minutes across a run of days."""
    if not days or not series:
        st.caption("Nothing tracked in this period yet.")
        return

    palette = active_palette()
    colours = series_colors(list(series), palette)

    figure = go.Figure()
    for name, values in series.items():
        figure.add_trace(
            go.Bar(
                name=name,
                x=list(days),
                y=list(values),
                marker={
                    "color": colours[name],
                    "line": {"width": _FILL_GAP, "color": palette.surface},
                },
                hovertemplate=f"<b>{name}</b><br>%{{x|%a %d %b}}<br>%{{y:.0f}} min<extra></extra>",
            )
        )

    layout = plotly_layout(palette, height=height)
    layout["title"] = {"text": title, "font": {"size": 14, "color": palette.text_secondary}}
    layout["barmode"] = "stack"
    layout["bargap"] = 0.25
    layout["yaxis"]["title"]["text"] = "Minutes"
    figure.update_layout(**layout)
    _render(figure, key)


def palette_of() -> Palette:
    """Expose the active palette to pages that need one colour."""
    return active_palette()
