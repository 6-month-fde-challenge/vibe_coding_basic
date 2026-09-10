"""Stat tiles, hero numbers and the score breakdown.

The brief's dashboard is mostly *numbers*, not charts. A single figure is
better served by a stat tile than by a one-bar bar chart, so these come
first and the plots are reserved for the questions that need a shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import streamlit as st

from app.schemas.dashboard import ProductivityScoreRead
from app.ui.formatting import percent
from app.ui.formatting import score as fmt_score
from app.ui.theme import STATUS, active_palette, score_status, status_icon


@dataclass(frozen=True, slots=True)
class Tile:
    """One statistic on the overview strip.

    Attributes:
        label: Short caption.
        value: The figure, already formatted.
        note: Optional secondary line - a target, a delta, a rate.
        status: Optional status role, always rendered with its icon.
    """

    label: str
    value: str
    note: str = ""
    status: str | None = None


def tile_row(tiles: Sequence[Tile], columns: int = 4) -> None:
    """Render a row of stat tiles.

    Args:
        tiles: The statistics to show.
        columns: How many per row before wrapping.
    """
    if not tiles:
        return
    palette = active_palette()
    for start in range(0, len(tiles), columns):
        chunk = tiles[start : start + columns]
        for column, tile in zip(st.columns(len(chunk)), chunk, strict=True):
            icon = f"{status_icon(tile.status)} " if tile.status else ""
            colour = STATUS.get(tile.status or "", palette.text_primary)
            column.markdown(
                f"""<div class="ht-tile">
                      <div class="ht-tile-label">{tile.label}</div>
                      <div class="ht-tile-value" style="color:{colour}">{icon}{tile.value}</div>
                      <div class="ht-tile-note">{tile.note}</div>
                    </div>""",
                unsafe_allow_html=True,
            )


def hero_score(value: float | None, caption: str = "Daily score") -> None:
    """Render the day's score as a hero number.

    One number is not a chart. It gets the largest type on the page and an
    icon beside it, so the status reads without relying on the colour.
    """
    palette = active_palette()
    role = score_status(value)
    colour = STATUS.get(role, palette.text_primary)
    st.markdown(
        f"""<div>
              <div class="ht-tile-label">{caption}</div>
              <div class="ht-hero" style="color:{colour}">
                {status_icon(role)} {fmt_score(value)}<span
                  style="font-size:1.2rem;color:{palette.muted}"> / 100</span>
              </div>
            </div>""",
        unsafe_allow_html=True,
    )


def score_breakdown(score: ProductivityScoreRead) -> None:
    """Show the arithmetic behind a productivity score.

    The brief asks for an explainable score, and this is what makes it one:
    every component, its weight, what it achieved, and the points it
    contributed - adding up to the number above it.
    """
    if not score.has_data:
        st.caption("Not enough recorded today to score the day yet.")
        return

    palette = active_palette()
    rows = "".join(
        f"""<tr>
              <td style="padding:2px 12px 2px 0;color:{palette.text_secondary}">{item.label}</td>
              <td style="padding:2px 12px 2px 0;color:{palette.muted};font-size:0.82rem">
                {item.detail}
              </td>
              <td style="padding:2px 0;text-align:right;color:{palette.text_primary}">
                +{item.points:.0f}
              </td>
            </tr>"""
        for item in score.components
    )
    st.markdown(
        f"""<table class="ht-breakdown" style="width:100%;border-collapse:collapse">
              {rows}
              <tr><td colspan="3"><hr style="border:none;border-top:1px solid
                {palette.grid};margin:6px 0"></td></tr>
              <tr>
                <td style="color:{palette.text_secondary}"><strong>Total</strong></td>
                <td></td>
                <td style="text-align:right;color:{palette.text_primary}">
                  <strong>{score.total:.0f}</strong>
                </td>
              </tr>
            </table>""",
        unsafe_allow_html=True,
    )

    if score.skipped:
        missing = ", ".join(key.replace("_", " ") for key in score.skipped)
        st.caption(
            f"Not counted today: {missing}. "
            f"The score is out of 100 across the {percent(score.coverage)} of the weighting "
            "that had data behind it."
        )


def progress_line(label: str, value: float, target: float, unit: str = "") -> None:
    """Render a labelled progress bar against a target."""
    fraction = min(1.0, value / target) if target > 0 else 0.0
    st.progress(fraction, text=f"{label}: {value:.0f}{unit} of {target:.0f}{unit}")


def empty_state(message: str, hint: str | None = None) -> None:
    """Render a friendly empty state.

    A fresh install has no data, and a page that shows a broken chart on
    day one teaches the user the app is broken.
    """
    st.info(message, icon="🌱")
    if hint:
        st.caption(hint)
