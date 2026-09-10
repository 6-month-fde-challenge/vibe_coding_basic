"""Every page must render without raising.

The pages are thin, but "thin" is not "correct": a renamed field or a
duplicated widget key breaks a page in a way no service test would catch.
Streamlit's own :class:`AppTest` runs each page headlessly, which is enough
to catch both.

These run against the *real* configured database rather than the temporary
one, because that is what the container's resource cache gives a Streamlit
process. They only read.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit.testing.v1", reason="Streamlit test harness unavailable")

from streamlit import config as st_config
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.integration

PAGES = (
    "dashboard",
    "tasks",
    "habits",
    "sleep",
    "activities",
    "time_tracking",
    "goals",
    "journal",
    "analytics",
    "health",
    "settings",
)


@pytest.fixture(scope="module", autouse=True)
def _show_errors() -> None:
    """Let the harness see the real exception rather than the redaction.

    The shipped config hides error details from users, which is right for
    the app and useless for a test.
    """
    st_config.set_option("client.showErrorDetails", "full")


@pytest.mark.parametrize("page", PAGES)
def test_the_page_renders(page: str) -> None:
    """Run one page end to end and assert it raised nothing."""
    script = f"from app.ui.pages import {page}\n{page}.render()\n"
    result = AppTest.from_string(script, default_timeout=180).run()
    assert not result.exception, [item.value for item in result.exception]


def test_the_dashboard_produces_widgets() -> None:
    """A page that renders nothing at all has still failed."""
    script = "from app.ui.pages import dashboard\ndashboard.render()\n"
    result = AppTest.from_string(script, default_timeout=180).run()
    assert result.markdown
    assert result.button


def test_no_page_leaks_a_traceback_to_the_user() -> None:
    """The error boundary must be the only path an exception can take."""
    script = (
        "import streamlit as st\n"
        "from app.ui.state import error_boundary\n"
        "with error_boundary('deliberate failure'):\n"
        "    raise RuntimeError('boom')\n"
    )
    result = AppTest.from_string(script, default_timeout=60).run()
    assert not result.exception
    assert result.error
    assert "boom" not in result.error[0].value
