"""The AI-coach extension point.

The application must not depend on a language model. So the seam is a
protocol with a deterministic implementation behind it: everything the
"coach" says today is assembled from the rule-based insight engine and the
day's own numbers.

Adding an LLM later means writing a second class satisfying
:class:`PersonalCoach` and choosing it in the container. No caller changes,
and the deterministic coach stays as the offline default - which is also
what keeps the privacy promise in section 42 of the brief intact by
default.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from app.core.timeutils import Clock, format_duration
from app.schemas.analytics import WeeklyReview
from app.schemas.common import DateRange
from app.schemas.dashboard import DailySummary
from app.services.analytics_service import AnalyticsService
from app.services.base import BaseService
from app.services.insight_service import InsightService
from app.services.unit_of_work import UnitOfWorkFactory


@runtime_checkable
class PersonalCoach(Protocol):
    """Anything that can talk about the user's day and week."""

    def generate_daily_summary(self, day: date | None = None) -> str:
        """Return a short prose summary of one day."""
        ...

    def generate_weekly_review(self, week_of: date | None = None) -> str:
        """Return a short prose summary of one week."""
        ...

    def recommend_improvements(self, day: date | None = None) -> list[str]:
        """Return concrete, optional suggestions."""
        ...


class RuleBasedCoach(BaseService):
    """A coach built entirely from the deterministic engines.

    Every sentence it produces can be traced to a number in the database,
    which is the property an LLM-backed version would have to work hard to
    keep.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        *,
        analytics: AnalyticsService,
        insights: InsightService,
    ) -> None:
        super().__init__(unit_of_work, clock)
        self.analytics = analytics
        self.insights = insights

    def generate_daily_summary(self, day: date | None = None) -> str:
        """Summarise one day in two or three sentences."""
        summary = self.analytics.daily_summary(day or self.today())
        return " ".join(_daily_sentences(summary))

    def generate_weekly_review(self, week_of: date | None = None) -> str:
        """Summarise one week in a short paragraph."""
        review = self.analytics.weekly_review(week_of or self.today())
        return " ".join(_weekly_sentences(review))

    def recommend_improvements(self, day: date | None = None) -> list[str]:
        """Return the rule-based recommendations for the current week."""
        target = day or self.today()
        period = DateRange.last_n_days(target, 7)
        return [item.message for item in self.insights.recommendations(period)]


def _daily_sentences(summary: DailySummary) -> list[str]:
    """Build the sentences of a daily summary."""
    parts: list[str] = []

    if not summary.has_any_data:
        return [f"Nothing recorded for {summary.weekday}, {summary.log_date.isoformat()} yet."]

    parts.append(
        f"{summary.weekday}: scored {summary.score.total:.0f} out of 100."
        if summary.score.has_data
        else f"{summary.weekday}: not enough recorded to score the day."
    )

    if summary.tasks.total:
        parts.append(f"You finished {summary.tasks.completed} of {summary.tasks.total} tasks.")
    if summary.habits.due:
        parts.append(
            f"{summary.habits.completed} of {summary.habits.due} habits were due and done."
        )
    if summary.sleep_minutes:
        parts.append(f"You slept {format_duration(summary.sleep_minutes)}.")

    learning = summary.study_minutes + summary.coding_minutes + summary.teaching_minutes
    if learning:
        parts.append(f"{format_duration(learning)} went on study, coding and teaching.")

    return parts


def _weekly_sentences(review: WeeklyReview) -> list[str]:
    """Build the sentences of a weekly review."""
    summary = review.summary
    parts = [
        f"Week of {summary.start.isoformat()}: "
        + (
            f"average score {summary.average_score:.0f}."
            if summary.average_score is not None
            else "not enough recorded to score the week."
        )
    ]

    parts.append(f"{summary.tasks_completed} of {summary.tasks_total} tasks completed.")
    parts.append(f"Habits ran at {summary.habit_completion_rate * 100:.0f}%.")

    if summary.average_sleep_minutes:
        parts.append(f"Sleep averaged {format_duration(summary.average_sleep_minutes)} a night.")
    if review.wins:
        parts.append("Wins: " + "; ".join(review.wins) + ".")
    if review.problems:
        parts.append("Watch: " + "; ".join(review.problems) + ".")
    if review.suggested_focus:
        parts.append(review.suggested_focus)

    return parts


__all__ = ["PersonalCoach", "RuleBasedCoach"]
