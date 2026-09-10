"""The journal page: morning check-in, evening review, and the diary."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.schemas.common import Pagination
from app.schemas.journal import EveningReview, JournalInput, MorningCheckIn
from app.ui.components.forms import optional_rating
from app.ui.components.metrics import empty_state
from app.ui.formatting import day_label, truncate
from app.ui.state import date_navigator, flush_action_message, get_container, run_action

PAGE_SIZE = 10


def render() -> None:
    """Draw the journal page."""
    st.title("Journal")
    flush_action_message()

    # One date control for the whole page: the three forms below all
    # describe the same day, and a picker per tab would let them drift.
    day = date_navigator()

    morning_tab, evening_tab, entry_tab, history_tab = st.tabs(
        ["Morning check-in", "Evening review", "Full entry", "History"]
    )
    with morning_tab:
        _morning(day)
    with evening_tab:
        _evening(day)
    with entry_tab:
        _entry(day)
    with history_tab:
        _history()


def _morning(day: date) -> None:
    """Six questions, under a minute."""
    container = get_container()
    log = container.journal.get_daily_log(day)

    if log and log.checkin_done:
        st.success("Checked in already today. Saving again replaces it.", icon="☀️")

    with st.form("morning_checkin"):
        left, right = st.columns(2)
        sleep_quality = left.slider("How did you sleep?", 1, 10, 7)
        energy = right.slider("Energy level?", 1, 10, log.morning_energy if log else 7)

        main_goal = st.text_input(
            "Today's main goal", value=(log.main_goal if log else "") or "", max_chars=255
        )

        existing = (log.priorities if log and log.priorities else []) + ["", "", ""]
        first, second, third = st.columns(3)
        priorities = [
            first.text_input("Priority 1", value=existing[0]),
            second.text_input("Priority 2", value=existing[1]),
            third.text_input("Priority 3", value=existing[2]),
        ]

        study_col, exercise_col = st.columns(2)
        study = study_col.number_input(
            "Planned study (minutes)",
            min_value=0,
            max_value=720,
            value=log.planned_study_minutes if log and log.planned_study_minutes else 120,
            step=15,
        )
        exercise = exercise_col.number_input(
            "Planned exercise (minutes)",
            min_value=0,
            max_value=480,
            value=log.planned_exercise_minutes if log and log.planned_exercise_minutes else 45,
            step=15,
        )

        if st.form_submit_button("Save check-in", type="primary"):
            run_action(
                "morning check-in",
                container.journal.morning_checkin,
                MorningCheckIn(
                    log_date=day,
                    sleep_quality=int(sleep_quality),
                    energy=int(energy),
                    main_goal=main_goal or None,
                    priorities=[item for item in priorities if item.strip()],
                    planned_study_minutes=int(study),
                    planned_exercise_minutes=int(exercise),
                ),
                success="Check-in saved. Have a good one.",
            )


def _evening(day: date) -> None:
    """The end-of-day verdict, with the day's own numbers alongside."""
    container = get_container()
    summary = container.analytics.daily_summary(day)
    log = container.journal.get_daily_log(day)

    st.info(container.coach.generate_daily_summary(day), icon="📋")

    with st.form("evening_review"):
        accomplishments = st.text_area("What did you accomplish?", height=100)

        mood_col, energy_col, focus_col, rating_col = st.columns(4)
        mood = mood_col.slider("Mood", 1, 10, summary.journal_mood or 7)
        energy = energy_col.slider("Energy", 1, 10, 7)
        focus = focus_col.slider("Focus", 1, 10, summary.journal_focus or 7)
        rating = rating_col.slider("Day overall", 1, 10, (log.day_rating if log else None) or 7)

        wrong = st.text_area("What went wrong?", height=80)
        improve = st.text_area("What should improve tomorrow?", height=80)

        if st.form_submit_button("Save review", type="primary"):
            run_action(
                "evening review",
                container.journal.evening_review,
                EveningReview(
                    log_date=day,
                    accomplishments=accomplishments or None,
                    mood=int(mood),
                    energy=int(energy),
                    focus=int(focus),
                    day_rating=int(rating),
                    what_went_wrong=wrong or None,
                    improve_tomorrow=improve or None,
                ),
                success="Review saved.",
            )


def _entry(day: date) -> None:
    """The full journal form, every field optional."""
    container = get_container()
    existing = container.journal.get_for_date(day)

    st.caption(day_label(day))
    ratings = st.columns(5)
    with ratings[0]:
        mood = optional_rating("Mood", key="j_mood", current=existing.mood if existing else None)
    with ratings[1]:
        energy = optional_rating(
            "Energy", key="j_energy", current=existing.energy if existing else None
        )
    with ratings[2]:
        stress = optional_rating(
            "Stress", key="j_stress", current=existing.stress if existing else None
        )
    with ratings[3]:
        motivation = optional_rating(
            "Motivation", key="j_motivation", current=existing.motivation if existing else None
        )
    with ratings[4]:
        focus = optional_rating(
            "Focus", key="j_focus", current=existing.focus if existing else None
        )

    with st.form("journal_entry"):
        reflection = st.text_area(
            "Reflection", value=(existing.reflection if existing else "") or "", height=120
        )
        left, right = st.columns(2)
        accomplishments = left.text_area(
            "Accomplished", value=(existing.accomplishments if existing else "") or "", height=90
        )
        challenges = right.text_area(
            "Challenges", value=(existing.challenges if existing else "") or "", height=90
        )
        gratitude = st.text_area(
            "Gratitude", value=(existing.gratitude if existing else "") or "", height=70
        )
        notes = st.text_area("Notes", value=(existing.notes if existing else "") or "", height=70)

        if st.form_submit_button("Save entry", type="primary"):
            run_action(
                "save journal entry",
                container.journal.save,
                JournalInput(
                    entry_date=day,
                    mood=mood,
                    energy=energy,
                    stress=stress,
                    motivation=motivation,
                    focus=focus,
                    reflection=reflection or None,
                    accomplishments=accomplishments or None,
                    challenges=challenges or None,
                    gratitude=gratitude or None,
                    notes=notes or None,
                ),
                success=f"Journal saved for {day.isoformat()}.",
            )


def _history() -> None:
    """Search and browse past entries."""
    container = get_container()
    term = st.text_input("Search your journal", placeholder="a word you remember writing")
    page_number = st.number_input("Page", min_value=1, value=1, step=1)
    pagination = Pagination(limit=PAGE_SIZE, offset=(int(page_number) - 1) * PAGE_SIZE)

    page = (
        container.journal.search(term, pagination)
        if term.strip()
        else container.journal.history(pagination)
    )

    if not page.items:
        empty_state("Nothing written yet." if not term else "No entries match that search.")
        return

    st.caption(f"{page.total} entries · page {page.page_number} of {page.page_count}")
    for entry in page.items:
        with st.expander(f"{day_label(entry.entry_date)} — {truncate(entry.reflection, 60)}"):
            scores = " · ".join(
                f"{label} {value}/10"
                for label, value in (
                    ("Mood", entry.mood),
                    ("Energy", entry.energy),
                    ("Stress", entry.stress),
                    ("Motivation", entry.motivation),
                    ("Focus", entry.focus),
                )
                if value is not None
            )
            if scores:
                st.caption(scores)
            for label, text in (
                ("Reflection", entry.reflection),
                ("Accomplished", entry.accomplishments),
                ("Challenges", entry.challenges),
                ("Gratitude", entry.gratitude),
                ("Notes", entry.notes),
            ):
                if text:
                    st.markdown(f"**{label}**")
                    st.write(text)


__all__ = ["render"]
