"""Streamlit entry point.

    streamlit run app/main.py

Deliberately thin. It sets the page config, injects the stylesheet, builds
the navigation and hands control to a page module. Everything else - the
container, the services, the database - is assembled by
:func:`app.bootstrap.build_container` behind the resource cache, so this
file has no knowledge of any of it.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from app import __version__
from app.core.errors import AppError
from app.core.logging_config import get_logger
from app.ui.pages import (
    activities,
    analytics,
    dashboard,
    goals,
    habits,
    health,
    journal,
    settings,
    sleep,
    tasks,
    time_tracking,
)
from app.ui.state import error_boundary, get_container
from app.ui.theme import page_css

logger = get_logger(__name__)

#: Sidebar navigation. Order matters: the daily loop first, the reference
#: pages after it, settings last.
NAVIGATION: tuple[tuple[str, str, Callable[[], None]], ...] = (
    ("Dashboard", "🏠", dashboard.render),
    ("Tasks", "📋", tasks.render),
    ("Habits", "🔁", habits.render),
    ("Sleep", "😴", sleep.render),
    ("Activities", "🏏", activities.render),
    ("Time tracking", "⏱️", time_tracking.render),
    ("Goals", "🎯", goals.render),
    ("Journal", "📔", journal.render),
    ("Analytics", "📊", analytics.render),
    ("Health metrics", "🩺", health.render),
    ("Settings", "⚙️", settings.render),
)


def configure_page() -> None:
    """Set the page config and inject the stylesheet."""
    st.set_page_config(
        page_title="Habit Tracker",
        page_icon="🌱",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={"about": f"Personal Habit & Daily Life Tracker v{__version__}"},
    )
    st.markdown(page_css(), unsafe_allow_html=True)


def sidebar_footer() -> None:
    """Show who is logged in, in which timezone, and on what data."""
    container = get_container()
    profile = container.health.get_profile()

    with st.sidebar:
        st.divider()
        st.caption(f"**{profile.display_name}** · {profile.timezone}")
        st.caption(f"Today is {container.clock.today().isoformat()}")
        st.caption(f"v{__version__} · {container.settings.app_env.value}")
        st.caption("All data stays on this machine.")


def main() -> None:
    """Build the navigation and run the selected page."""
    configure_page()

    try:
        get_container()
    except AppError as error:
        logger.exception("Application failed to start")
        st.error(error.user_message(), icon="🔥")
        st.stop()
    except Exception:
        logger.exception("Application failed to start")
        st.error(
            "The application could not start. Check `logs/habit_tracker.log` for details.",
            icon="🔥",
        )
        st.stop()

    pages = [
        st.Page(render, title=title, icon=icon, url_path=title.lower().replace(" ", "-"))
        for title, icon, render in NAVIGATION
    ]
    selected = st.navigation(pages, position="sidebar")
    sidebar_footer()

    with error_boundary(f"rendering the {selected.title} page"):
        selected.run()


main()
