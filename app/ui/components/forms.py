"""Reusable form controls.

Every page that asks for a category, a duration or a date range uses these,
so the same question is asked the same way throughout - and changing how a
duration is entered is one edit rather than nine.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, time, timedelta
from enum import StrEnum
from typing import Any

import streamlit as st

from app.models.enums import CategoryKind
from app.schemas.activity import CategoryRead
from app.schemas.common import DateRange
from app.ui.state import get_container

#: Ranges offered by the period picker, as ``(label, days)``.
PRESET_RANGES: tuple[tuple[str, int], ...] = (
    ("Last 7 days", 7),
    ("Last 30 days", 30),
    ("Last 90 days", 90),
    ("Last 12 months", 365),
)

#: Quick durations offered next to a minutes field.
DURATION_PRESETS: tuple[int, ...] = (15, 30, 45, 60, 90, 120)


def category_picker(
    kind: CategoryKind,
    *,
    key: str,
    label: str = "Category",
    default_name: str | None = None,
) -> CategoryRead | None:
    """Render a category selector and return the chosen category.

    Returns ``None`` when no categories of that kind exist, and says so -
    which is what a user who deleted them all needs to be told.
    """
    container = get_container()
    options = container.categories.list_kind(kind)
    if not options:
        st.warning(
            f"No {kind.value.lower()} categories yet. Add one in Settings first.",
            icon="⚙️",
        )
        return None

    names = [category.name for category in options]
    index = names.index(default_name) if default_name in names else 0
    chosen = st.selectbox(label, names, index=index, key=key)
    return next(category for category in options if category.name == chosen)


def duration_input(
    *,
    key: str,
    label: str = "Duration (minutes)",
    default: int = 30,
) -> int:
    """Render a duration field with one-tap presets.

    Tracking has to be faster than the activity being tracked, so the
    common lengths are buttons rather than typing.
    """
    state_key = f"{key}__minutes"
    if state_key not in st.session_state:
        st.session_state[state_key] = default

    columns = st.columns(len(DURATION_PRESETS))
    for column, preset in zip(columns, DURATION_PRESETS, strict=True):
        if column.button(f"{preset}m", key=f"{key}__preset_{preset}", use_container_width=True):
            st.session_state[state_key] = preset

    return int(
        st.number_input(
            label,
            min_value=1,
            max_value=24 * 60,
            step=5,
            key=state_key,
        )
    )


def period_picker(*, key: str, default_days: int = 30) -> DateRange:
    """Render the shared date-range control and return the range."""
    container = get_container()
    today = container.clock.today()

    labels = [label for label, _ in PRESET_RANGES]
    default_label = next(
        (label for label, days in PRESET_RANGES if days == default_days), labels[1]
    )
    chosen = st.segmented_control(
        "Period",
        labels,
        default=default_label,
        key=key,
        label_visibility="collapsed",
    )
    days = dict(PRESET_RANGES).get(chosen or default_label, default_days)
    return DateRange(start=today - timedelta(days=days - 1), end=today)


def time_pair(
    *,
    key: str,
    start_label: str = "Start",
    end_label: str = "End",
    start_default: time = time(9, 0),
    end_default: time = time(10, 0),
) -> tuple[time | None, time | None]:
    """Render an optional start/end time pair.

    Both or neither: an entry with only a start time cannot be measured,
    and the schema rejects it, so the control refuses to produce one.
    """
    use_clock = st.checkbox("Record exact times", key=f"{key}__use_clock")
    if not use_clock:
        return None, None

    left, right = st.columns(2)
    start = left.time_input(start_label, value=start_default, key=f"{key}__start", step=300)
    end = right.time_input(end_label, value=end_default, key=f"{key}__end", step=300)
    return start, end


def rating_slider(label: str, *, key: str, default: int = 5, help_text: str | None = None) -> int:
    """Render a 1-10 rating slider."""
    return int(st.slider(label, min_value=1, max_value=10, value=default, key=key, help=help_text))


def optional_rating(label: str, *, key: str, current: int | None = None) -> int | None:
    """Render a rating that can be left unanswered.

    A journal that insists on ten answers is a journal nobody fills in, so
    "not answered" is a first-class option rather than a default of five
    pretending to be data.
    """
    answered = st.checkbox(
        label, value=current is not None, key=f"{key}__answered", help="Leave off to skip"
    )
    if not answered:
        return None
    return int(
        st.slider(
            label,
            min_value=1,
            max_value=10,
            value=current or 5,
            key=key,
            label_visibility="collapsed",
        )
    )


def weekday_multiselect(*, key: str, label: str = "Days", default: Sequence[int] = ()) -> list[int]:
    """Render a weekday chooser and return weekday numbers (0=Monday)."""
    names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    chosen = st.multiselect(
        label, names, default=[names[day] for day in default if 0 <= day <= 6], key=key
    )
    return [names.index(name) for name in chosen]


def confirm_button(
    label: str,
    *,
    key: str,
    help_text: str = "This cannot be undone",
) -> bool:
    """Render a destructive action behind an explicit confirmation.

    Deleting a habit takes its whole history with it, so it takes two
    deliberate clicks rather than one stray one.
    """
    armed_key = f"{key}__armed"
    if not st.session_state.get(armed_key):
        if st.button(label, key=f"{key}__arm", help=help_text):
            st.session_state[armed_key] = True
            st.rerun()
        return False

    st.warning(f"{help_text}. Confirm?", icon="⚠️")
    left, right = st.columns(2)
    if left.button("Yes, do it", key=f"{key}__confirm", type="primary"):
        st.session_state[armed_key] = False
        return True
    if right.button("Cancel", key=f"{key}__cancel"):
        st.session_state[armed_key] = False
        st.rerun()
    return False


def date_field(
    label: str, *, key: str, value: date | None = None, allow_future: bool = False
) -> date:
    """Render a date field bounded to the past unless told otherwise."""
    container = get_container()
    today = container.clock.today()
    chosen = st.date_input(
        label,
        value=value or today,
        max_value=None if allow_future else today,
        format="YYYY-MM-DD",
        key=key,
    )
    return chosen if isinstance(chosen, date) else today


def enum_select[E: StrEnum](
    label: str,
    options: Sequence[E],
    *,
    key: str,
    current: E | None = None,
    format_func: Callable[[E], str] | None = None,
    help_text: str | None = None,
    parent: Any = None,
) -> E:
    """Render a select box over an enum and return the enum member.

    Streamlit hands back whatever it was given, and a ``StrEnum`` *is* a
    string - so passing the members straight in loses the type on the way
    out. Rendering the labels and mapping back keeps the enum, which means
    no page has to remember to convert.

    Args:
        label: Field label.
        options: The members to offer, in display order.
        key: Unique Streamlit key.
        current: The member to preselect.
        format_func: How to render a member. Defaults to title case.
        help_text: Tooltip.
        parent: A column or container to render into, if not the page body.
    """
    render = format_func or _default_enum_label
    labels = [render(option) for option in options]
    index = options.index(current) if current in options else 0
    target = parent if parent is not None else st
    chosen = target.selectbox(label, labels, index=index, key=key, help=help_text)
    return options[labels.index(chosen)]


def _default_enum_label(value: StrEnum) -> str:
    """Render an enum member as ``Title case with spaces``."""
    return value.value.replace("_", " ").title()
