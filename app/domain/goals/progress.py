"""Goal progress and pace."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.core.errors import ValidationError
from app.models.enums import GoalStatus

MIN_PROGRESS = 0.0
MAX_PROGRESS = 100.0


@dataclass(frozen=True, slots=True)
class MilestoneSnapshot:
    """The little that progress arithmetic needs from a milestone."""

    title: str
    is_completed: bool


@dataclass(frozen=True, slots=True)
class GoalPace:
    """Whether a goal is keeping up with its own deadline.

    Attributes:
        elapsed_fraction: How much of the goal's window has passed, 0-1.
        progress_fraction: How much of the work is done, 0-1.
        days_remaining: Days left until the target date, negative if passed.
        is_behind: Progress is more than ten points behind elapsed time.
        is_overdue: The target date has passed and the goal is not complete.
    """

    elapsed_fraction: float | None
    progress_fraction: float
    days_remaining: int | None
    is_behind: bool
    is_overdue: bool


#: How far behind schedule a goal may drift before it is flagged. Ten points
#: of slack, so a goal is not "behind" the morning after it is created.
_BEHIND_TOLERANCE = 0.10


def validate_progress(value: float) -> float:
    """Return ``value`` if it is a legal percentage.

    Raises:
        ValidationError: If it falls outside 0-100.
    """
    if not MIN_PROGRESS <= value <= MAX_PROGRESS:
        raise ValidationError(
            "Progress must be between 0 and 100",
            field="progress_percent",
            value=value,
        )
    return value


def progress_from_milestones(milestones: Sequence[MilestoneSnapshot]) -> float | None:
    """Return progress implied by completed milestones, as a percentage.

    Returns ``None`` when there are no milestones, which is the signal to
    keep whatever the user set by hand instead of overwriting it with zero.
    """
    if not milestones:
        return None
    done = sum(1 for milestone in milestones if milestone.is_completed)
    return (done / len(milestones)) * MAX_PROGRESS


def compute_pace(
    *,
    progress_percent: float,
    start_date: date | None,
    target_date: date | None,
    today: date,
    status: GoalStatus,
) -> GoalPace:
    """Compare how far along a goal is against how much time has gone.

    Args:
        progress_percent: Current progress, 0-100.
        start_date: When work began.
        target_date: When it is due.
        today: The user's local today.
        status: The goal's current status.

    Returns:
        The pace picture. ``elapsed_fraction`` is ``None`` when the goal has
        no dates to measure against, and nothing is flagged as behind in
        that case - a goal without a deadline cannot be late.
    """
    progress_fraction = max(0.0, min(1.0, progress_percent / MAX_PROGRESS))
    days_remaining = (target_date - today).days if target_date else None
    is_complete = status is GoalStatus.COMPLETED
    is_overdue = bool(target_date and target_date < today and not is_complete)

    if start_date is None or target_date is None or target_date <= start_date:
        return GoalPace(
            elapsed_fraction=None,
            progress_fraction=progress_fraction,
            days_remaining=days_remaining,
            is_behind=False,
            is_overdue=is_overdue,
        )

    total_days = (target_date - start_date).days
    gone = (today - start_date).days
    elapsed = max(0.0, min(1.0, gone / total_days))
    behind = (not is_complete) and (elapsed - progress_fraction) > _BEHIND_TOLERANCE

    return GoalPace(
        elapsed_fraction=elapsed,
        progress_fraction=progress_fraction,
        days_remaining=days_remaining,
        is_behind=behind,
        is_overdue=is_overdue,
    )


def derive_status(progress_percent: float, current: GoalStatus) -> GoalStatus:
    """Move a goal's status to match its progress, without fighting the user.

    Only two transitions are automatic: reaching 100% completes an open
    goal, and putting work into a not-started one starts it. A paused or
    abandoned goal is left exactly where the user put it.
    """
    if current in {GoalStatus.ON_HOLD, GoalStatus.ABANDONED}:
        return current
    if progress_percent >= MAX_PROGRESS:
        return GoalStatus.COMPLETED
    if progress_percent > MIN_PROGRESS and current is GoalStatus.NOT_STARTED:
        return GoalStatus.IN_PROGRESS
    if progress_percent < MAX_PROGRESS and current is GoalStatus.COMPLETED:
        return GoalStatus.IN_PROGRESS
    return current
