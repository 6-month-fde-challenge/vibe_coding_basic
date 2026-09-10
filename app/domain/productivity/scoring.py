"""The daily productivity score.

Two properties matter more than the exact number:

*Explainable.* The score is returned with its components, so the UI can
print the arithmetic rather than a mystery figure out of 100.

*Honest about gaps.* A user who does not track exercise should not score
zero for exercise. Missing components are dropped and the remaining weights
are rescaled over what is actually known - and the result says which
components were skipped, so a 90 built from two inputs cannot masquerade as
a 90 built from six.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.productivity.weights import COMPONENT_LABELS, ProductivityWeights

#: Focus and mood are recorded on a 1-10 scale.
_RATING_MAX = 10.0
#: Sleeping well past the target is not more productive than hitting it, so
#: the sleep component is capped rather than rewarded without limit.
_MAX_ACHIEVEMENT = 1.0


@dataclass(frozen=True, slots=True)
class DayMetrics:
    """The raw inputs to one day's score.

    Every field is optional. ``None`` means "not tracked", which is
    different from ``0.0`` meaning "tracked, and none happened".

    Attributes:
        task_rate: Fraction of the day's tasks completed, 0-1.
        habit_rate: Fraction of the day's due habits completed, 0-1.
        sleep_minutes: Minutes slept.
        sleep_target_minutes: The user's nightly target.
        exercise_minutes: Minutes of logged activity.
        exercise_target_minutes: The user's daily target.
        learning_minutes: Minutes across the categories marked productive
            learning - study, coding and teaching by default.
        learning_target_minutes: The combined daily target for those.
        focus_rating: The 1-10 focus score from the journal.
    """

    task_rate: float | None = None
    habit_rate: float | None = None
    sleep_minutes: float | None = None
    sleep_target_minutes: float | None = None
    exercise_minutes: float | None = None
    exercise_target_minutes: float | None = None
    learning_minutes: float | None = None
    learning_target_minutes: float | None = None
    focus_rating: float | None = None


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    """One line of the score's explanation.

    Attributes:
        key: Machine name, matching a field of :class:`ProductivityWeights`.
        label: Human-readable name.
        weight: The rescaled weight actually applied.
        achievement: How much of this component was achieved, 0-1.
        points: ``weight * achievement * 100``.
        detail: A short phrase such as ``"7h 10m of 7h 30m"``.
    """

    key: str
    label: str
    weight: float
    achievement: float
    points: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProductivityScore:
    """A day's score together with the arithmetic behind it.

    Attributes:
        total: The score, 0-100.
        components: One entry per component that contributed.
        skipped: Component keys with no data, excluded from the score.
        coverage: Share of the original weight that had data behind it. A
            low number means the score is confident about very little.
    """

    total: float = 0.0
    components: tuple[ScoreComponent, ...] = ()
    skipped: tuple[str, ...] = ()
    coverage: float = 0.0

    @property
    def has_data(self) -> bool:
        """Whether any component contributed."""
        return bool(self.components)

    def as_breakdown(self) -> list[dict[str, float | str]]:
        """Return the components as plain dictionaries, for JSON storage."""
        return [
            {
                "key": component.key,
                "label": component.label,
                "weight": round(component.weight, 4),
                "achievement": round(component.achievement, 4),
                "points": round(component.points, 2),
                "detail": component.detail,
            }
            for component in self.components
        ]


@dataclass(slots=True)
class _RawComponent:
    """An achievement measured before the weights are rescaled."""

    key: str
    achievement: float
    detail: str = ""
    parts: list[str] = field(default_factory=list)


def _ratio(value: float | None, target: float | None) -> float | None:
    """Achievement of a value against a target, capped at 1.0."""
    if value is None or target is None or target <= 0:
        return None
    return min(_MAX_ACHIEVEMENT, max(0.0, value / target))


def _format_minutes(minutes: float) -> str:
    """Render minutes compactly for a breakdown line."""
    total = round(minutes)
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _collect(metrics: DayMetrics) -> list[_RawComponent]:
    """Turn raw metrics into per-component achievements, skipping unknowns."""
    collected: list[_RawComponent] = []

    if metrics.task_rate is not None:
        collected.append(
            _RawComponent(
                key="task_completion",
                achievement=min(_MAX_ACHIEVEMENT, max(0.0, metrics.task_rate)),
                detail=f"{metrics.task_rate * 100:.0f}% of tasks",
            )
        )

    if metrics.habit_rate is not None:
        collected.append(
            _RawComponent(
                key="habit_completion",
                achievement=min(_MAX_ACHIEVEMENT, max(0.0, metrics.habit_rate)),
                detail=f"{metrics.habit_rate * 100:.0f}% of habits due",
            )
        )

    sleep = _ratio(metrics.sleep_minutes, metrics.sleep_target_minutes)
    if sleep is not None and metrics.sleep_minutes is not None:
        target = metrics.sleep_target_minutes or 0
        collected.append(
            _RawComponent(
                key="sleep",
                achievement=sleep,
                detail=f"{_format_minutes(metrics.sleep_minutes)} of {_format_minutes(target)}",
            )
        )

    exercise = _ratio(metrics.exercise_minutes, metrics.exercise_target_minutes)
    if exercise is not None and metrics.exercise_minutes is not None:
        target = metrics.exercise_target_minutes or 0
        collected.append(
            _RawComponent(
                key="exercise",
                achievement=exercise,
                detail=f"{_format_minutes(metrics.exercise_minutes)} of {_format_minutes(target)}",
            )
        )

    learning = _ratio(metrics.learning_minutes, metrics.learning_target_minutes)
    if learning is not None and metrics.learning_minutes is not None:
        target = metrics.learning_target_minutes or 0
        collected.append(
            _RawComponent(
                key="learning",
                achievement=learning,
                detail=f"{_format_minutes(metrics.learning_minutes)} of {_format_minutes(target)}",
            )
        )

    if metrics.focus_rating is not None:
        collected.append(
            _RawComponent(
                key="focus",
                achievement=min(_MAX_ACHIEVEMENT, max(0.0, metrics.focus_rating / _RATING_MAX)),
                detail=f"{metrics.focus_rating:.0f}/10 focus",
            )
        )

    return collected


def score_day(metrics: DayMetrics, weights: ProductivityWeights) -> ProductivityScore:
    """Score one day and return the arithmetic with it.

    Args:
        metrics: The day's raw inputs. Any of them may be ``None``.
        weights: The configured component weights.

    Returns:
        A :class:`ProductivityScore`. An input with no data at all scores
        zero with empty components rather than raising - a brand-new install
        has to render something.
    """
    weight_map = weights.as_mapping()
    collected = _collect(metrics)
    present_keys = {component.key for component in collected}
    skipped = tuple(key for key in weight_map if key not in present_keys)

    available_weight = sum(weight_map[component.key] for component in collected)
    if not collected or available_weight <= 0:
        return ProductivityScore(skipped=tuple(weight_map))

    components: list[ScoreComponent] = []
    total = 0.0
    for raw in collected:
        # Rescale over the components that actually have data, so a partly
        # tracked day is still scored out of 100.
        rescaled = weight_map[raw.key] / available_weight
        points = rescaled * raw.achievement * 100.0
        total += points
        components.append(
            ScoreComponent(
                key=raw.key,
                label=COMPONENT_LABELS.get(raw.key, raw.key),
                weight=rescaled,
                achievement=raw.achievement,
                points=points,
                detail=raw.detail,
            )
        )

    return ProductivityScore(
        total=round(total, 1),
        components=tuple(components),
        skipped=skipped,
        coverage=available_weight / (weights.total or 1.0),
    )
