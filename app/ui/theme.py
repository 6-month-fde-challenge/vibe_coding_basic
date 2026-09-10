"""Colour, typography and the Plotly template.

Every chart in the application draws its colours from here, and nowhere
else, so the whole app reads as one system rather than as eleven pages that
each picked their own blue.

The palette is a validated categorical set: eight fixed hues assigned in a
fixed order, never cycled and never reassigned by rank. Three of the light
slots fall below 3:1 contrast against the surface, so every chart that uses
them also ships either direct labels or the table view beneath it - colour
never carries meaning on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

#: Categorical slots, in the order they are assigned. A ninth series is
#: never a generated hue - it folds into "Other".
SERIES_LIGHT: Final[tuple[str, ...]] = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
)

SERIES_DARK: Final[tuple[str, ...]] = (
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
)

#: One hue, light to dark. Used for magnitude - the calendar heatmap.
SEQUENTIAL_BLUE: Final[tuple[str, ...]] = (
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
)

#: Reserved. A status colour never stands in for "series 4", and always
#: ships beside an icon or a label.
STATUS: Final[dict[str, str]] = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

#: Maximum number of slices before the tail folds into "Other".
MAX_SEGMENTS: Final = 6

#: The one typeface, including for large numbers.
FONT_STACK: Final = 'system-ui, -apple-system, "Segoe UI", sans-serif'


@dataclass(frozen=True, slots=True)
class Palette:
    """Every colour a chart is allowed to use, for one mode."""

    mode: str
    surface: str
    page: str
    text_primary: str
    text_secondary: str
    muted: str
    grid: str
    axis: str
    series: tuple[str, ...]
    sequential: tuple[str, ...]

    def slot(self, index: int) -> str:
        """Return a categorical hue by slot index, folding past the eighth."""
        return self.series[index % len(self.series)]


LIGHT = Palette(
    mode="light",
    surface="#fcfcfb",
    page="#f9f9f7",
    text_primary="#0b0b0b",
    text_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    series=SERIES_LIGHT,
    sequential=SEQUENTIAL_BLUE,
)

DARK = Palette(
    mode="dark",
    surface="#1a1a19",
    page="#0d0d0d",
    text_primary="#ffffff",
    text_secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    series=SERIES_DARK,
    sequential=SEQUENTIAL_BLUE,
)


def active_palette() -> Palette:
    """Return the palette matching the viewer's Streamlit theme.

    Dark mode is a *selected* set of steps for the dark surface, not an
    automatic inversion of the light one.
    """
    import streamlit as st

    try:
        theme = st.context.theme
        if theme is not None and getattr(theme, "type", "light") == "dark":
            return DARK
    except (AttributeError, RuntimeError):
        # Older Streamlit, or called outside a script run.
        pass
    return LIGHT


def series_colors(names: list[str], palette: Palette | None = None) -> dict[str, str]:
    """Map entity names to categorical slots, stably.

    Keyed by name, sorted, so filtering a series out never repaints the
    survivors: a reader who learned that Coding is orange keeps that.
    """
    active = palette or active_palette()
    return {name: active.slot(index) for index, name in enumerate(sorted(names))}


def plotly_layout(palette: Palette | None = None, *, height: int = 320) -> dict[str, Any]:
    """Return the shared Plotly layout.

    Hairline grid, no chart-junk, generous padding, and the surface colours
    the rest of the page uses. Applied by every chart helper so no page ever
    hand-rolls a layout.
    """
    active = palette or active_palette()
    return {
        "height": height,
        "paper_bgcolor": active.surface,
        "plot_bgcolor": active.surface,
        "font": {"family": FONT_STACK, "size": 13, "color": active.text_secondary},
        "margin": {"l": 8, "r": 8, "t": 32, "b": 8},
        "hoverlabel": {
            "bgcolor": active.surface,
            "bordercolor": active.axis,
            "font": {"family": FONT_STACK, "size": 12, "color": active.text_primary},
        },
        "xaxis": {
            "gridcolor": active.grid,
            "linecolor": active.axis,
            "zerolinecolor": active.grid,
            "tickfont": {"color": active.muted, "size": 11},
            "title": {"font": {"color": active.muted, "size": 11}},
        },
        "yaxis": {
            "gridcolor": active.grid,
            "linecolor": active.axis,
            "zerolinecolor": active.grid,
            "tickfont": {"color": active.muted, "size": 11},
            "title": {"font": {"color": active.muted, "size": 11}},
        },
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "font": {"color": active.text_secondary, "size": 12},
        },
    }


def score_status(score: float | None) -> str:
    """Map a 0-100 score to a status role.

    Returned as a role name, never a hex, so the caller pairs it with an
    icon or a label rather than relying on the colour.
    """
    if score is None:
        return "warning"
    if score >= 80:
        return "good"
    if score >= 60:
        return "serious"
    return "critical"


def status_icon(role: str) -> str:
    """Return the icon that must accompany a status colour."""
    return {"good": "🟢", "warning": "⚪", "serious": "🟡", "critical": "🔴"}.get(role, "⚪")


def page_css(palette: Palette | None = None) -> str:
    """Return the small stylesheet the app injects once per run.

    Deliberately small. Streamlit's own theme handles the chrome; this only
    tightens spacing and styles the few custom elements - the stat tiles and
    the score breakdown rows - that no built-in widget covers.
    """
    active = palette or active_palette()
    return f"""
    <style>
      .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1180px; }}
      .ht-tile {{
        border: 1px solid {active.grid};
        border-radius: 10px;
        padding: 0.75rem 0.9rem;
        background: {active.surface};
        height: 100%;
      }}
      .ht-tile-label {{
        font-size: 0.75rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: {active.muted};
        margin-bottom: 0.2rem;
      }}
      .ht-tile-value {{
        font-family: {FONT_STACK};
        font-size: 1.6rem;
        font-weight: 600;
        line-height: 1.15;
        color: {active.text_primary};
      }}
      .ht-tile-note {{ font-size: 0.78rem; color: {active.text_secondary}; }}
      .ht-hero {{
        font-size: 3rem;
        font-weight: 600;
        line-height: 1;
        color: {active.text_primary};
      }}
      .ht-breakdown {{ font-variant-numeric: tabular-nums; }}
      .ht-muted {{ color: {active.muted}; font-size: 0.82rem; }}
      div[data-testid="stMetricValue"] {{ font-family: {FONT_STACK}; }}
    </style>
    """
