"""Populate the database with a realistic demo dataset.

    python scripts/seed_data.py --days 90

Writes through the *services*, not the tables, so everything it creates
obeys the same rules the UI does - a seeded streak is a real streak, and a
seeded score is computed by the same engine that scores today.

The generated person is deliberately imperfect: they sleep badly on
Wednesdays, skip the gym when work runs long, and let one habit slide. A
demo dataset where everything is at 100% teaches you nothing about whether
the analytics work.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, time, timedelta

from app.bootstrap import Container, build_container
from app.core.logging_config import get_logger, setup_logging
from app.core.timeutils import week_start
from app.models.enums import (
    ActivityIntensity,
    ActivityLevel,
    CategoryKind,
    GoalCategory,
    HabitDirection,
    HabitFrequency,
    HabitType,
    Sex,
    TaskPriority,
    WeeklyMetric,
)
from app.schemas.activity import ActivityInput, TimeEntryInput
from app.schemas.common import DateRange
from app.schemas.goal import GoalCreate, MilestoneInput, WeeklyGoalInput
from app.schemas.habit import HabitCreate, HabitLogInput
from app.schemas.health import BodyMeasurementInput, ProfileUpdate
from app.schemas.journal import EveningReview, JournalInput, MorningCheckIn
from app.schemas.sleep import SleepInput
from app.schemas.task import TaskCreate

logger = get_logger(__name__)

DEFAULT_DAYS = 90
#: Fixed so two runs of the script produce the same demo data.
SEED = 20260910

TASK_TITLES = (
    "Review pull requests",
    "Write the weekly update",
    "Plan tomorrow",
    "Answer student questions",
    "Refactor the parser",
    "Read one paper",
    "Call home",
    "Grocery run",
    "Fix the failing test",
    "Draft the lesson plan",
    "Tidy the inbox",
    "Update the CV",
)


@dataclass(frozen=True, slots=True)
class HabitSpec:
    """One demo habit, and how reliably the fictional person does it.

    A dataclass rather than a dictionary so the seeder type-checks like
    everything else - the dictionary version needed nine ``type: ignore``
    comments to stay quiet, which is a sign the shape was wrong.
    """

    name: str
    habit_type: HabitType
    reliability: float
    icon: str
    target_value: float | None = None
    min_target: float | None = None
    unit: str | None = None
    target_time: time | None = None
    direction: HabitDirection = HabitDirection.AT_LEAST
    frequency: HabitFrequency = HabitFrequency.DAILY
    times_per_week: int | None = None


HABIT_SPECS: tuple[HabitSpec, ...] = (
    HabitSpec("Meditation", HabitType.DURATION, 0.78, "🧘", 20.0, 10.0, "minutes"),
    HabitSpec("Drink water", HabitType.QUANTITY, 0.85, "💧", 3.0, 2.0, "litres"),
    HabitSpec("Read", HabitType.COUNT, 0.62, "📖", 20.0, unit="pages"),
    HabitSpec(
        "Wake up early",
        HabitType.TIME,
        0.70,
        "🌅",
        target_time=time(6, 30),
        direction=HabitDirection.BEFORE,
    ),
    HabitSpec("No social media", HabitType.BOOLEAN, 0.55, "📵"),
    HabitSpec(
        "Personal project",
        HabitType.BOOLEAN,
        0.80,
        "🛠️",
        frequency=HabitFrequency.WEEKDAYS,
    ),
    HabitSpec(
        "Walk 30 minutes",
        HabitType.DURATION,
        0.60,
        "🚶",
        30.0,
        unit="minutes",
        frequency=HabitFrequency.TIMES_PER_WEEK,
        times_per_week=4,
    ),
)

#: ``category -> (weekday mean minutes, weekend mean minutes, spread)``.
TIME_PATTERN: dict[str, tuple[float, float, float]] = {
    "Studying": (110, 70, 40),
    "Coding": (95, 45, 45),
    "Teaching": (55, 15, 25),
    "Work": (300, 20, 90),
    "Reading": (25, 45, 20),
    "Entertainment": (60, 130, 45),
    "Personal": (45, 90, 30),
}

ACTIVITY_PATTERN: tuple[tuple[str, float, float, ActivityIntensity], ...] = (
    ("Cricket", 0.22, 85, ActivityIntensity.HIGH),
    ("Walking", 0.55, 35, ActivityIntensity.LOW),
    ("Gym", 0.25, 55, ActivityIntensity.HIGH),
    ("Running", 0.15, 30, ActivityIntensity.MODERATE),
    ("Yoga", 0.18, 40, ActivityIntensity.LOW),
)


def seed(container: Container, days: int, rng: random.Random) -> None:
    """Generate ``days`` of history ending today."""
    today = container.clock.today()
    start = today - timedelta(days=days - 1)

    _seed_profile(container, today)
    habits = _seed_habits(container, start)
    _seed_days(container, start, today, habits, rng)
    _seed_goals(container, today)
    _score(container, start, today)


def _seed_profile(container: Container, today: date) -> None:
    """Give the demo person a body and some targets."""
    container.health.update_profile(
        ProfileUpdate(
            display_name="Demo",
            birth_date=date(today.year - 24, 5, 17),
            sex=Sex.MALE,
            height_cm=176.0,
            activity_level=ActivityLevel.MODERATELY_ACTIVE,
            target_sleep_minutes=450,
            target_study_minutes=120,
            target_coding_minutes=90,
            target_teaching_minutes=60,
            target_exercise_minutes=45,
            target_bedtime=time(23, 15),
            target_wake_time=time(6, 30),
        )
    )


def _seed_habits(container: Container, start: date) -> list[tuple[int, HabitSpec]]:
    """Create the demo habits, skipping any that already exist."""
    existing = {habit.name: habit.id for habit in container.habits.list_habits(active_only=False)}
    created: list[tuple[int, HabitSpec]] = []

    for spec in HABIT_SPECS:
        habit_id = existing.get(spec.name)
        if habit_id is None:
            habit_id = container.habits.create(
                HabitCreate(
                    name=spec.name,
                    habit_type=spec.habit_type,
                    direction=spec.direction,
                    frequency=spec.frequency,
                    target_value=spec.target_value,
                    min_target=spec.min_target,
                    target_time=spec.target_time,
                    unit=spec.unit,
                    times_per_week=spec.times_per_week,
                    icon=spec.icon,
                    start_date=start,
                )
            ).id
        created.append((habit_id, spec))
    return created


def _seed_days(
    container: Container,
    start: date,
    today: date,
    habits: list[tuple[int, HabitSpec]],
    rng: random.Random,
) -> None:
    """Walk the window and record a plausible day at each step."""
    time_categories = {
        category.name: category.id for category in container.categories.list_kind(CategoryKind.TIME)
    }
    activity_categories = {
        category.name: category.id
        for category in container.categories.list_kind(CategoryKind.ACTIVITY)
    }

    day = start
    while day <= today:
        weekend = day.weekday() >= 5
        _seed_sleep(container, day, rng)
        _seed_time(container, day, weekend, time_categories, rng)
        _seed_activity(container, day, activity_categories, rng)
        _seed_tasks(container, day, weekend, rng)
        _seed_habit_logs(container, day, habits, rng)
        _seed_journal(container, day, rng)

        if day.day % 7 == 1:
            container.health.record_measurement(
                BodyMeasurementInput(
                    measured_on=day,
                    weight_kg=round(72.0 - (day - start).days * 0.012 + rng.uniform(-0.4, 0.4), 1),
                    body_fat_percent=round(rng.uniform(16.5, 18.5), 1),
                )
            )

        day += timedelta(days=1)


def _seed_sleep(container: Container, day: date, rng: random.Random) -> None:
    """One night, worse mid-week because that is what happens."""
    if rng.random() < 0.06:
        return  # a night that simply never got logged

    penalty = 45 if day.weekday() == 2 else 0
    bonus = 40 if day.weekday() >= 5 else 0
    duration = int(rng.gauss(430 + bonus - penalty, 45))
    duration = max(300, min(560, duration))

    wake_minutes = int(rng.gauss(6 * 60 + 30 + (60 if day.weekday() >= 5 else 0), 30))
    wake = time(hour=(wake_minutes // 60) % 24, minute=wake_minutes % 60)
    sleep_minutes = (wake_minutes - duration) % (24 * 60)
    asleep = time(hour=sleep_minutes // 60, minute=sleep_minutes % 60)

    container.sleep.record(
        SleepInput(
            log_date=day,
            sleep_time=asleep,
            wake_time=wake,
            quality=max(1, min(10, int(rng.gauss(7.2, 1.4)))),
            interruptions=rng.choice([0, 0, 0, 1, 1, 2]),
        )
    )


def _seed_time(
    container: Container,
    day: date,
    weekend: bool,
    categories: dict[str, int],
    rng: random.Random,
) -> None:
    """A day's tracked time, following the weekday/weekend pattern."""
    for name, (weekday_mean, weekend_mean, spread) in TIME_PATTERN.items():
        category_id = categories.get(name)
        if category_id is None:
            continue
        mean = weekend_mean if weekend else weekday_mean
        if mean <= 0 or rng.random() < 0.18:
            continue
        amount = int(rng.gauss(mean, spread))
        if amount < 10:
            continue
        container.time_tracking.log(
            TimeEntryInput(
                log_date=day, category_id=category_id, duration_minutes=float(min(amount, 600))
            )
        )


def _seed_activity(
    container: Container, day: date, categories: dict[str, int], rng: random.Random
) -> None:
    """Nought, one or occasionally two bouts of exercise."""
    for name, probability, mean, intensity in ACTIVITY_PATTERN:
        category_id = categories.get(name)
        if category_id is None or rng.random() > probability:
            continue
        container.activities.log(
            ActivityInput(
                log_date=day,
                category_id=category_id,
                duration_minutes=float(max(15, int(rng.gauss(mean, 15)))),
                intensity=intensity,
                estimate_calories=True,
            )
        )


def _seed_tasks(container: Container, day: date, weekend: bool, rng: random.Random) -> None:
    """A handful of tasks, most but not all of them done."""
    count = rng.randint(2, 4) if weekend else rng.randint(4, 9)
    completion_rate = 0.85 if count <= 6 else 0.62

    for title in rng.sample(TASK_TITLES, k=min(count, len(TASK_TITLES))):
        task = container.tasks.create(
            TaskCreate(
                title=title,
                due_date=day,
                priority=rng.choice(
                    [TaskPriority.LOW, TaskPriority.MEDIUM, TaskPriority.MEDIUM, TaskPriority.HIGH]
                ),
                estimated_minutes=rng.choice([15, 30, 45, 60, 90]),
            )
        )
        if rng.random() < completion_rate:
            container.tasks.complete(task.id, actual_minutes=rng.choice([10, 25, 40, 55, 100]))


def _seed_habit_logs(
    container: Container,
    day: date,
    habits: list[tuple[int, HabitSpec]],
    rng: random.Random,
) -> None:
    """Log each habit at its own reliability."""
    for habit_id, spec in habits:
        if rng.random() > spec.reliability:
            continue

        if spec.habit_type is HabitType.BOOLEAN:
            payload = HabitLogInput(habit_id=habit_id, log_date=day, checked=True)
        elif spec.habit_type is HabitType.TIME:
            minutes_past = int(rng.gauss(6 * 60 + 20, 25))
            payload = HabitLogInput(
                habit_id=habit_id,
                log_date=day,
                value_time=time(hour=(minutes_past // 60) % 24, minute=minutes_past % 60),
            )
        else:
            target = spec.target_value or 1.0
            payload = HabitLogInput(
                habit_id=habit_id,
                log_date=day,
                value=round(max(0.0, rng.gauss(target * 1.05, target * 0.3)), 1),
            )

        try:
            container.habits.log(payload)
        except Exception as error:  # a habit that had not started yet
            logger.debug("Skipped habit log for %s: %s", day, error)


def _seed_journal(container: Container, day: date, rng: random.Random) -> None:
    """A check-in most mornings and a review most evenings."""
    if rng.random() < 0.7:
        container.journal.morning_checkin(
            MorningCheckIn(
                log_date=day,
                energy=max(1, min(10, int(rng.gauss(7, 1.5)))),
                main_goal=rng.choice(
                    ["Ship the API", "Finish the chapter", "Clear the backlog", "Rest properly"]
                ),
                priorities=rng.sample(list(TASK_TITLES), k=3),
                planned_study_minutes=rng.choice([60, 90, 120, 150]),
                planned_exercise_minutes=rng.choice([0, 30, 45, 60]),
            )
        )

    if rng.random() < 0.6:
        container.journal.evening_review(
            EveningReview(
                log_date=day,
                mood=max(1, min(10, int(rng.gauss(7, 1.5)))),
                energy=max(1, min(10, int(rng.gauss(6.5, 1.6)))),
                focus=max(1, min(10, int(rng.gauss(6.8, 1.7)))),
                day_rating=max(1, min(10, int(rng.gauss(7, 1.4)))),
            )
        )

    if rng.random() < 0.25:
        container.journal.save(
            JournalInput(
                entry_date=day,
                reflection=rng.choice(
                    [
                        "Good deep-work block in the morning; afternoon got eaten by meetings.",
                        "Slept badly and it showed. Kept the streak alive anyway.",
                        "Taught for an hour and enjoyed it more than expected.",
                        "Too much time on the phone. Worth watching.",
                    ]
                ),
                gratitude=rng.choice(["Quiet morning", "A good coffee", "Friends", "Rain"]),
            )
        )


def _seed_goals(container: Container, today: date) -> None:
    """A couple of goals and a weekly study target."""
    if container.goals.list_goals():
        return

    container.goals.create(
        GoalCreate(
            title="Learn FastAPI",
            description="Build and deploy a small API end to end.",
            category=GoalCategory.LEARNING,
            start_date=today - timedelta(days=45),
            target_date=today + timedelta(days=20),
            milestones=[
                MilestoneInput(title="Python async fundamentals", is_completed=True, sort_order=10),
                MilestoneInput(title="REST fundamentals", is_completed=True, sort_order=20),
                MilestoneInput(title="Build API", sort_order=30),
                MilestoneInput(title="Deploy API", sort_order=40),
            ],
        )
    )
    container.goals.create(
        GoalCreate(
            title="Run 5k without stopping",
            category=GoalCategory.FITNESS,
            start_date=today - timedelta(days=30),
            target_date=today + timedelta(days=60),
            milestones=[
                MilestoneInput(title="Run 2k", is_completed=True, sort_order=10),
                MilestoneInput(title="Run 3.5k", sort_order=20),
                MilestoneInput(title="Run 5k", sort_order=30),
            ],
        )
    )

    container.goals.set_weekly(
        WeeklyGoalInput(
            week_start=week_start(today),
            metric=WeeklyMetric.STUDY_MINUTES,
            target_value=600.0,
            notes="Ten hours of study a week.",
        )
    )


def _score(container: Container, start: date, today: date) -> None:
    """Compute and cache every day's productivity score."""
    scored = container.productivity.recompute_range(DateRange(start=start, end=today))
    logger.info("Scored %d days", scored)


def main() -> int:
    """Entry point.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(description="Seed the tracker with demo data.")
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS, help="How many days of history to generate."
    )
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed, for repeatability.")
    parser.add_argument(
        "--yes", action="store_true", help="Do not ask before writing to the database."
    )
    arguments = parser.parse_args()

    if arguments.days < 1 or arguments.days > 730:
        print("--days must be between 1 and 730.")
        return 2

    setup_logging()
    container = build_container()

    print(f"Seeding {arguments.days} days into {container.database.engine.url}")
    if not arguments.yes:
        answer = input("This adds records to the database. Continue? [y/N] ").strip().lower()
        if answer != "y":
            print("Cancelled.")
            return 1

    seed(container, arguments.days, random.Random(arguments.seed))

    today = container.clock.today()
    summary = container.analytics.daily_summary(today)
    print(
        f"Done. Today scores {summary.score.total:.0f}/100 with "
        f"{summary.tasks.completed}/{summary.tasks.total} tasks and "
        f"{summary.habits.completed}/{summary.habits.due} habits."
    )
    print("Run:  streamlit run app/main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
