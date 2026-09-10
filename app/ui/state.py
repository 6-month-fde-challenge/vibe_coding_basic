"""Streamlit session plumbing: the container, caching and the error boundary.

Three caches, kept apart on purpose:

``@st.cache_resource``
    The container. It owns a connection pool, so exactly one exists per
    process and it is never copied.

``@st.cache_data``
    Read-heavy query results, keyed by their arguments. Only ever holds
    immutable schema objects - never an ORM row, never a session.

``st.session_state``
    Per-user UI state: which date is selected, which filter is open.

Mixing those up is the classic Streamlit bug: a cached session handed to a
second rerun on another thread.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import streamlit as st

from app.bootstrap import Container, build_container
from app.core.errors import AppError
from app.core.logging_config import get_logger

logger = get_logger(__name__)

#: Session-state keys, named once so a typo cannot silently create a second
#: piece of state that nothing ever reads.
SELECTED_DATE = "selected_date"
LAST_ACTION = "last_action_message"


@st.cache_resource(show_spinner="Starting the tracker...")
def get_container() -> Container:
    """Return the process-wide service container.

    Cached as a *resource*: it holds the database engine, and Streamlit
    reruns the whole script on every interaction. Caching it as data would
    copy the engine on each rerun and exhaust the connection pool.
    """
    container = build_container()
    logger.info("Streamlit container ready")
    return container


def reset_container() -> None:
    """Drop the cached container and every cached query.

    Called after a change that invalidates everything - restoring a backup,
    or changing the timezone.
    """
    get_container.clear()
    st.cache_data.clear()


def selected_date() -> date:
    """Return the date the user is looking at, defaulting to today."""
    container = get_container()
    if SELECTED_DATE not in st.session_state:
        st.session_state[SELECTED_DATE] = container.clock.today()
    value = st.session_state[SELECTED_DATE]
    return value if isinstance(value, date) else container.clock.today()


def set_selected_date(day: date) -> None:
    """Change the date the pages are showing."""
    st.session_state[SELECTED_DATE] = day


@contextmanager
def error_boundary(action: str) -> Iterator[None]:
    """Turn an exception into a message a person can act on.

    Application errors carry their own user-facing sentence. Anything else
    is a bug: the traceback goes to the log and the user gets an apology
    and a reference, never a stack trace.

    Args:
        action: What was being attempted, used in the log line.
    """
    try:
        yield
    except AppError as error:
        logger.warning("%s failed: %s", action, error)
        st.error(error.user_message(), icon="⚠️")
    except Exception:
        logger.exception("Unexpected failure during %s", action)
        st.error(
            "Something went wrong and has been written to the log. "
            "Nothing was saved - please try again.",
            icon="🔥",
        )


def run_action[T](
    action: str,
    fn: Callable[..., T],
    *args: Any,
    success: str | None = None,
    rerun: bool = True,
    **kwargs: Any,
) -> T | None:
    """Run a service call from a button, safely.

    Clears the data cache on success, because the write just invalidated
    whatever the page had cached, and reruns so the change is visible.

    Args:
        action: Short description, for the log.
        fn: The service method to call.
        *args: Positional arguments for it.
        success: Message to show, stored across the rerun.
        rerun: Whether to rerun the script after a successful call.
        **kwargs: Keyword arguments for it.

    Returns:
        Whatever the service returned, or ``None`` if it failed.
    """
    try:
        result = fn(*args, **kwargs)
    except AppError as error:
        logger.warning("%s failed: %s", action, error)
        st.error(error.user_message(), icon="⚠️")
        return None
    except Exception:
        logger.exception("Unexpected failure during %s", action)
        st.error("Something went wrong. The details are in the log.", icon="🔥")
        return None

    st.cache_data.clear()
    if success:
        st.session_state[LAST_ACTION] = success
    if rerun:
        st.rerun()
    return result


def flush_action_message() -> None:
    """Show and clear the message left by the last successful action."""
    message = st.session_state.pop(LAST_ACTION, None)
    if message:
        st.success(message, icon="✅")


def date_navigator(label: str = "Date") -> date:
    """Render the shared day picker and return the chosen date.

    Every day-scoped page uses this one control, so moving to yesterday on
    the dashboard and then opening the journal shows the same day.
    """
    container = get_container()
    today = container.clock.today()
    current = selected_date()

    left, middle, right = st.columns([1, 3, 1], vertical_alignment="bottom")
    with left:
        if st.button("◀", help="Previous day", use_container_width=True):
            set_selected_date(current - timedelta(days=1))
            st.rerun()
    with middle:
        chosen = st.date_input(label, value=current, max_value=today, format="YYYY-MM-DD")
    with right:
        forward_blocked = current >= today
        if st.button("▶", help="Next day", use_container_width=True, disabled=forward_blocked):
            set_selected_date(current + timedelta(days=1))
            st.rerun()

    if isinstance(chosen, date) and chosen != current:
        set_selected_date(chosen)
        return chosen
    return current
