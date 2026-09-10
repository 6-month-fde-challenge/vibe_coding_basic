"""The health metrics page: weight, BMR and TDEE.

Every energy figure on this page is an estimate from a published
population equation. The page says so more than once on purpose - the
numbers look authoritative and are not.
"""

from __future__ import annotations

import streamlit as st

from app.models.enums import ActivityLevel, BmrFormula, Sex, members
from app.schemas.analytics import SeriesPoint
from app.schemas.health import BodyMeasurementInput, ProfileUpdate
from app.ui.components.charts import line_series
from app.ui.components.forms import enum_select, period_picker
from app.ui.components.metrics import Tile, empty_state, tile_row
from app.ui.formatting import signed
from app.ui.state import flush_action_message, get_container, run_action

_FORMULA_LABELS = {
    BmrFormula.MIFFLIN_ST_JEOR: "Mifflin-St Jeor",
    BmrFormula.HARRIS_BENEDICT: "Harris-Benedict (revised)",
    BmrFormula.KATCH_MCARDLE: "Katch-McArdle (needs body fat)",
}


def render() -> None:
    """Draw the health page."""
    st.title("Health metrics")
    flush_action_message()

    today_tab, trend_tab, setup_tab = st.tabs(["Today", "Trend", "Body settings"])
    with today_tab:
        _today()
    with trend_tab:
        _trend()
    with setup_tab:
        _setup()


def _today() -> None:
    """The current estimate, or what is missing to produce one."""
    container = get_container()
    snapshot = container.health.snapshot()

    if not snapshot.is_available:
        st.warning(snapshot.unavailable_reason or "Not enough profile data yet.", icon="ℹ️")
    else:
        tile_row(
            [
                Tile("BMR", f"{snapshot.bmr_kcal:,} kcal", "at complete rest"),
                Tile(
                    "TDEE",
                    f"{snapshot.tdee_kcal:,} kcal",
                    f"{snapshot.activity_level.label.lower()} lifestyle",
                ),
                Tile("Weight", f"{snapshot.weight_kg:.1f} kg" if snapshot.weight_kg else "-"),
                Tile("BMI", f"{snapshot.bmi:.1f}" if snapshot.bmi else "-", "ignores composition"),
            ]
        )
        st.caption(snapshot.note)

    st.divider()
    st.subheader("Record a weigh-in", anchor=False)
    with st.form("measurement", clear_on_submit=True):
        left, middle, right = st.columns(3)
        measured_on = left.date_input("Date", value=container.clock.today())
        weight = middle.number_input("Weight (kg)", min_value=20.0, max_value=400.0, value=70.0)
        body_fat = right.number_input(
            "Body fat %", min_value=0.0, max_value=70.0, value=0.0, help="Leave at 0 to skip"
        )
        notes = st.text_input("Notes", max_chars=200)

        if st.form_submit_button("Save measurement", type="primary"):
            run_action(
                "record measurement",
                container.health.record_measurement,
                BodyMeasurementInput(
                    measured_on=measured_on,
                    weight_kg=float(weight),
                    body_fat_percent=float(body_fat) or None,
                    notes=notes or None,
                ),
                success="Measurement saved.",
            )

    st.divider()
    st.subheader("What the three formulas say", anchor=False)
    st.caption(
        "They disagree by a few hundred kilocalories, which is the most honest thing "
        "this page can show you about what an estimate is worth."
    )
    comparison = container.health.compare_formulas()
    st.dataframe(
        [
            {
                "Formula": _FORMULA_LABELS[formula],
                "BMR estimate": f"{value:,} kcal" if value else "needs more profile data",
            }
            for formula, value in comparison.items()
        ],
        hide_index=True,
        use_container_width=True,
    )


def _trend() -> None:
    """Weight over time."""
    container = get_container()
    period = period_picker(key="health_period", default_days=90)
    measurements = container.health.measurements_between(period)
    trend = container.health.weight_trend(period)

    if not measurements:
        empty_state("No measurements in this period.")
        return

    tile_row(
        [
            Tile("Measurements", str(trend.points)),
            Tile("First", f"{trend.first_kg:.1f} kg" if trend.first_kg else "-"),
            Tile("Latest", f"{trend.latest_kg:.1f} kg" if trend.latest_kg else "-"),
            Tile("Change", signed(trend.change_kg, " kg", 1), _per_week(trend.change_per_week_kg)),
        ]
    )
    st.write("")

    line_series(
        {
            "Weight (kg)": [
                SeriesPoint(day=row.measured_on, value=row.weight_kg) for row in measurements
            ]
        },
        title="Body mass",
        key="health_weight",
        y_title="kg",
    )

    st.dataframe(
        [
            {
                "Date": row.measured_on.isoformat(),
                "Weight (kg)": f"{row.weight_kg:.1f}",
                "Body fat %": f"{row.body_fat_percent:.1f}" if row.body_fat_percent else "",
                "Waist (cm)": f"{row.waist_cm:.0f}" if row.waist_cm else "",
                "Notes": row.notes or "",
            }
            for row in reversed(measurements)
        ],
        hide_index=True,
        use_container_width=True,
    )


def _setup() -> None:
    """The profile fields the estimates depend on."""
    container = get_container()
    profile = container.health.get_profile()

    with st.form("body_profile"):
        left, middle, right = st.columns(3)
        birth_date = left.date_input(
            "Date of birth", value=profile.birth_date, min_value=None, max_value=None
        )
        sex = enum_select(
            "Sex",
            members(Sex),
            key="profile_sex",
            current=profile.sex,
            help_text="Mifflin-St Jeor and Harris-Benedict use a constant per sex.",
            parent=middle,
        )
        height = right.number_input(
            "Height (cm)", min_value=50.0, max_value=280.0, value=profile.height_cm or 170.0
        )

        activity = enum_select(
            "Activity level",
            members(ActivityLevel),
            key="profile_activity",
            current=profile.activity_level,
            format_func=lambda value: f"{value.label} (x{value.multiplier})",
        )
        formula = enum_select(
            "BMR formula",
            members(BmrFormula),
            key="profile_formula",
            current=profile.bmr_formula,
            format_func=lambda value: _FORMULA_LABELS[value],
        )

        if st.form_submit_button("Save", type="primary"):
            run_action(
                "update body profile",
                container.health.update_profile,
                ProfileUpdate(
                    birth_date=birth_date,
                    sex=sex,
                    height_cm=float(height),
                    activity_level=activity,
                    bmr_formula=formula,
                ),
                success="Profile updated.",
            )


def _per_week(value: float | None) -> str:
    """Describe a rate of change per week."""
    if value is None:
        return "not enough span"
    return f"{signed(value, ' kg', 2)} per week"


__all__ = ["render"]
