"""Deterministic, rule-based insights and recommendations.

No language model is involved and none is required. Each rule is a small
pure function from a :class:`InsightContext` to an optional
:class:`Insight`, registered in a list. Adding a rule means writing one
function; an LLM-backed generator would slot in later as an *additional*
producer behind the same ``Insight`` type, not as a replacement for this
one.

Every insight carries its evidence, because "you study 38% more on weekdays"
is only useful if the user can see the two numbers behind it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.timeutils import format_duration, weekday_name
from app.domain.analytics.statistics import percentage_change
from app.models.enums import InsightSeverity

#: Rules stay quiet below these thresholds. Named constants rather than
#: magic numbers scattered through the rule bodies.
MIN_DAYS_FOR_TREND = 7
NOTABLE_PERCENT = 15.0
NOTABLE_SLEEP_DRIFT_MINUTES = 20.0
STREAK_WORTH_MENTIONING = 5
CONSECUTIVE_MISSES_BEFORE_NUDGE = 3
LOW_COMPLETION_RATE = 0.5


@dataclass(frozen=True, slots=True)
class Insight:
    """One observation about the data.

    Attributes:
        key: Stable identifier of the rule that produced it.
        message: The sentence shown to the user.
        severity: How it should be presented.
        evidence: The numbers behind the sentence.
    """

    key: str
    message: str
    severity: InsightSeverity = InsightSeverity.NEUTRAL
    evidence: dict[str, float | str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A suggested adjustment.

    Deliberately non-medical and non-judgemental: it names what was
    observed, suggests one concrete change, and stops.
    """

    key: str
    message: str
    rationale: str
    evidence: dict[str, float | str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HabitFacts:
    """Per-habit figures the rules read."""

    name: str
    current_streak: int
    longest_streak: int
    completion_rate: float
    consecutive_misses: int = 0


@dataclass(frozen=True, slots=True)
class InsightContext:
    """Everything the rules are allowed to look at.

    Assembled by the analytics service from repository aggregates. Keeping
    it a plain dataclass is what lets every rule be unit-tested with three
    lines of setup and no database.
    """

    today: date
    productivity_by_day: Mapping[date, float] = field(default_factory=dict)
    weekday_productivity: Mapping[int, float] = field(default_factory=dict)
    habits: Sequence[HabitFacts] = ()

    sleep_avg_current: float | None = None
    sleep_avg_previous: float | None = None
    sleep_target_minutes: float | None = None
    sleep_nights_below_target: int = 0

    study_weekday_avg: float | None = None
    study_weekend_avg: float | None = None

    completion_by_task_count: Mapping[int, float] = field(default_factory=dict)
    tasks_planned_today: int | None = None

    minutes_by_category_current: Mapping[str, float] = field(default_factory=dict)
    minutes_by_category_previous: Mapping[str, float] = field(default_factory=dict)

    bedtime_shift_minutes: float | None = None


InsightRule = Callable[[InsightContext], Insight | None]
RecommendationRule = Callable[[InsightContext], Recommendation | None]


# --------------------------------------------------------------------------
# Insight rules
# --------------------------------------------------------------------------


def _rule_weekday_vs_weekend_study(context: InsightContext) -> Insight | None:
    """Compare study time on weekdays against weekends."""
    weekday = context.study_weekday_avg
    weekend = context.study_weekend_avg
    if not weekday or not weekend:
        return None

    change = percentage_change(weekend, weekday)
    if change is None or abs(change) < NOTABLE_PERCENT:
        return None

    more, less = ("weekdays", "weekends") if change > 0 else ("weekends", "weekdays")
    return Insight(
        key="study_weekday_vs_weekend",
        message=(
            f"You study {abs(change):.0f}% more on {more} than {less} "
            f"({format_duration(weekday)}/day against {format_duration(weekend)}/day)."
        ),
        severity=InsightSeverity.NEUTRAL,
        evidence={"weekday_minutes": weekday, "weekend_minutes": weekend, "change": change},
    )


def _rule_sleep_change(context: InsightContext) -> Insight | None:
    """Report a week-on-week change in average sleep."""
    current = context.sleep_avg_current
    previous = context.sleep_avg_previous
    if current is None or previous is None:
        return None

    delta = current - previous
    if abs(delta) < NOTABLE_SLEEP_DRIFT_MINUTES:
        return None

    if delta < 0:
        message = (
            f"Your average sleep dropped by {format_duration(abs(delta))} this period "
            f"(now {format_duration(current)} a night)."
        )
        severity = InsightSeverity.ATTENTION
    else:
        message = (
            f"Your average sleep rose by {format_duration(delta)} this period "
            f"(now {format_duration(current)} a night)."
        )
        severity = InsightSeverity.POSITIVE

    return Insight(
        key="sleep_change",
        message=message,
        severity=severity,
        evidence={"current_minutes": current, "previous_minutes": previous, "delta": delta},
    )


def _rule_bedtime_drift(context: InsightContext) -> Insight | None:
    """Report a shift in typical bedtime."""
    shift = context.bedtime_shift_minutes
    if shift is None or abs(shift) < NOTABLE_SLEEP_DRIFT_MINUTES:
        return None

    direction = "later" if shift > 0 else "earlier"
    return Insight(
        key="bedtime_drift",
        message=(
            f"Your typical bedtime has moved {format_duration(abs(shift))} {direction} "
            "compared with the previous period."
        ),
        severity=InsightSeverity.ATTENTION if shift > 0 else InsightSeverity.POSITIVE,
        evidence={"shift_minutes": shift},
    )


def _rule_best_streak(context: InsightContext) -> Insight | None:
    """Celebrate the longest running streak."""
    running = [habit for habit in context.habits if habit.current_streak >= STREAK_WORTH_MENTIONING]
    if not running:
        return None

    best = max(running, key=lambda habit: habit.current_streak)
    suffix = " - your longest ever." if best.current_streak >= best.longest_streak else "."
    return Insight(
        key="best_streak",
        message=f"Your {best.name} streak is currently {best.current_streak} days{suffix}",
        severity=InsightSeverity.POSITIVE,
        evidence={"habit": best.name, "streak": best.current_streak},
    )


def _rule_weakest_habit(context: InsightContext) -> Insight | None:
    """Name the habit with the lowest completion rate."""
    tracked = [habit for habit in context.habits if habit.completion_rate < LOW_COMPLETION_RATE]
    if not tracked:
        return None

    weakest = min(tracked, key=lambda habit: habit.completion_rate)
    return Insight(
        key="weakest_habit",
        message=(
            f"{weakest.name} is your least consistent habit at "
            f"{weakest.completion_rate * 100:.0f}% of the days it was due."
        ),
        severity=InsightSeverity.ATTENTION,
        evidence={"habit": weakest.name, "rate": weakest.completion_rate},
    )


def _rule_most_productive_weekday(context: InsightContext) -> Insight | None:
    """Name the day of the week that scores highest."""
    if len(context.weekday_productivity) < 3:
        return None

    weekday, score = max(context.weekday_productivity.items(), key=lambda item: item[1])
    # 2024-01-01 was a Monday; offsetting from it turns 0-6 into a name.
    name = weekday_name(date(2024, 1, 1) + timedelta(days=weekday))
    return Insight(
        key="most_productive_weekday",
        message=f"Your most productive day is {name}, averaging {score:.0f}/100.",
        severity=InsightSeverity.NEUTRAL,
        evidence={"weekday": name, "score": score},
    )


def _rule_task_load_sweet_spot(context: InsightContext) -> Insight | None:
    """Find the planned-task count with the best completion rate."""
    if len(context.completion_by_task_count) < 2:
        return None

    best_count, best_rate = max(context.completion_by_task_count.items(), key=lambda item: item[1])
    if best_rate < LOW_COMPLETION_RATE:
        return None

    return Insight(
        key="task_load_sweet_spot",
        message=(
            f"You complete {best_rate * 100:.0f}% of your tasks on days you plan "
            f"{best_count} of them."
        ),
        severity=InsightSeverity.NEUTRAL,
        evidence={"task_count": best_count, "rate": best_rate},
    )


def _rule_category_shift(context: InsightContext) -> Insight | None:
    """Report the biggest change in where time went."""
    current = context.minutes_by_category_current
    previous = context.minutes_by_category_previous
    if not current or not previous:
        return None

    changes: list[tuple[str, float, float, float]] = []
    for name, now in current.items():
        before = previous.get(name)
        change = percentage_change(before, now)
        if before is not None and change is not None:
            changes.append((name, before, now, change))

    if not changes:
        return None

    name, before, now, change = max(changes, key=lambda item: abs(item[3]))
    if abs(change) < NOTABLE_PERCENT:
        return None

    verb = "more" if change > 0 else "less"
    return Insight(
        key="category_shift",
        message=(
            f"You spent {abs(change):.0f}% {verb} time on {name} this period "
            f"({format_duration(now)} against {format_duration(before)})."
        ),
        severity=InsightSeverity.NEUTRAL,
        evidence={"category": name, "previous": before, "current": now, "change": change},
    )


#: Registered in the order they should be shown.
INSIGHT_RULES: tuple[InsightRule, ...] = (
    _rule_best_streak,
    _rule_sleep_change,
    _rule_bedtime_drift,
    _rule_weekday_vs_weekend_study,
    _rule_most_productive_weekday,
    _rule_task_load_sweet_spot,
    _rule_category_shift,
    _rule_weakest_habit,
)


# --------------------------------------------------------------------------
# Recommendation rules
# --------------------------------------------------------------------------


def _recommend_lower_habit_target(context: InsightContext) -> Recommendation | None:
    """Suggest easing a target that has been missed several days running."""
    struggling = [
        habit
        for habit in context.habits
        if habit.consecutive_misses >= CONSECUTIVE_MISSES_BEFORE_NUDGE
    ]
    if not struggling:
        return None

    worst = max(struggling, key=lambda habit: habit.consecutive_misses)
    return Recommendation(
        key="lower_habit_target",
        message=f"Consider lowering today's {worst.name} target, or setting a minimum you can hit.",
        rationale=(
            f"You have missed {worst.name} {worst.consecutive_misses} days in a row. "
            "A target that is reachable on a bad day keeps the chain alive."
        ),
        evidence={"habit": worst.name, "consecutive_misses": worst.consecutive_misses},
    )


def _recommend_earlier_bedtime(context: InsightContext) -> Recommendation | None:
    """Suggest an earlier bedtime when sleep is persistently short."""
    target = context.sleep_target_minutes
    current = context.sleep_avg_current
    if target is None or current is None:
        return None
    if context.sleep_nights_below_target < CONSECUTIVE_MISSES_BEFORE_NUDGE:
        return None
    if current >= target:
        return None

    shortfall = target - current
    return Recommendation(
        key="earlier_bedtime",
        message=(
            f"Try setting a bedtime {format_duration(shortfall)} earlier than your usual one."
        ),
        rationale=(
            f"You have slept under your {format_duration(target)} target on "
            f"{context.sleep_nights_below_target} nights recently, averaging "
            f"{format_duration(current)}."
        ),
        evidence={"shortfall_minutes": shortfall, "nights": context.sleep_nights_below_target},
    )


def _recommend_fewer_tasks(context: InsightContext) -> Recommendation | None:
    """Suggest planning fewer tasks when the load looks too heavy."""
    planned = context.tasks_planned_today
    if planned is None or not context.completion_by_task_count:
        return None

    best_count, best_rate = max(context.completion_by_task_count.items(), key=lambda item: item[1])
    if planned <= best_count or best_rate < LOW_COMPLETION_RATE:
        return None

    return Recommendation(
        key="fewer_tasks",
        message=f"Consider trimming today's list from {planned} tasks to about {best_count}.",
        rationale=(
            f"Your completion rate is highest ({best_rate * 100:.0f}%) on days you plan "
            f"{best_count} tasks."
        ),
        evidence={"planned": planned, "suggested": best_count, "rate": best_rate},
    )


RECOMMENDATION_RULES: tuple[RecommendationRule, ...] = (
    _recommend_earlier_bedtime,
    _recommend_lower_habit_target,
    _recommend_fewer_tasks,
)


def generate_insights(context: InsightContext, *, limit: int = 6) -> list[Insight]:
    """Run every insight rule and return those that fired.

    Args:
        context: The facts the rules may inspect.
        limit: Maximum number returned, so the page never becomes a wall of
            observations.
    """
    produced: list[Insight] = []
    for rule in INSIGHT_RULES:
        insight = rule(context)
        if insight is not None:
            produced.append(insight)
        if len(produced) >= limit:
            break
    return produced


def generate_recommendations(context: InsightContext, *, limit: int = 3) -> list[Recommendation]:
    """Run every recommendation rule and return those that fired."""
    produced: list[Recommendation] = []
    for rule in RECOMMENDATION_RULES:
        recommendation = rule(context)
        if recommendation is not None:
            produced.append(recommendation)
        if len(produced) >= limit:
            break
    return produced
