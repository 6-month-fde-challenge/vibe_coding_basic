"""The goals page: long-running goals and weekly numeric targets."""

from __future__ import annotations

import streamlit as st

from app.core.timeutils import week_start
from app.models.enums import GoalCategory, GoalStatus, TaskPriority, WeeklyMetric, members
from app.schemas.goal import GoalCreate, GoalRead, GoalUpdate, MilestoneInput, WeeklyGoalInput
from app.ui.components.forms import confirm_button, enum_select
from app.ui.components.metrics import empty_state
from app.ui.formatting import PRIORITY_BADGES, minutes, percent
from app.ui.state import flush_action_message, get_container, run_action


def render() -> None:
    """Draw the goals page."""
    st.title("Goals")
    flush_action_message()

    goals_tab, weekly_tab, new_tab = st.tabs(["Goals", "This week", "New goal"])
    with goals_tab:
        _goals()
    with weekly_tab:
        _weekly()
    with new_tab:
        _new_goal()


def _goals() -> None:
    """Every goal, with progress and pace."""
    container = get_container()
    show_all = st.toggle("Include finished and abandoned goals", value=False)
    goals = container.goals.list_goals(open_only=not show_all)

    if not goals:
        empty_state("No goals yet.", "Create one on the New goal tab.")
        return

    for goal in goals:
        _goal_card(goal)


def _goal_card(goal: GoalRead) -> None:
    """One goal with its milestones."""
    container = get_container()
    pace = container.goals.pace(goal.id)

    with st.container(border=True):
        header, meta = st.columns([4, 2])
        header.markdown(f"**{goal.title}**")
        caption = [goal.category.value.title(), PRIORITY_BADGES[goal.priority]]
        if goal.target_date:
            caption.append(f"due {goal.target_date.isoformat()}")
        if pace.days_remaining is not None:
            caption.append(
                f"{pace.days_remaining} days left"
                if pace.days_remaining >= 0
                else f"{abs(pace.days_remaining)} days overdue"
            )
        header.caption(" · ".join(caption))

        if pace.is_overdue:
            meta.error("Overdue", icon="🔴")
        elif pace.is_behind:
            meta.warning("Behind schedule", icon="🟡")
        elif goal.status is GoalStatus.COMPLETED:
            meta.success("Complete", icon="🟢")
        else:
            meta.info(goal.status.value.replace("_", " ").title(), icon="🔵")

        st.progress(
            min(1.0, goal.progress_percent / 100),
            text=f"{goal.progress_percent:.0f}% complete",
        )

        if goal.description:
            st.caption(goal.description)

        for milestone in goal.milestones:
            left, right = st.columns([6, 1], vertical_alignment="center")
            mark = "✓" if milestone.is_completed else "→"
            left.write(f"{mark} {milestone.title}")
            if right.button(
                "Undo" if milestone.is_completed else "Done",
                key=f"milestone_{milestone.id}",
                use_container_width=True,
            ):
                run_action(
                    "toggle milestone",
                    container.goals.toggle_milestone,
                    milestone.id,
                    success=f"{milestone.title!r} updated.",
                )

        with st.expander("Edit goal"):
            _edit_goal(goal)


def _edit_goal(goal: GoalRead) -> None:
    """Edit, add milestones, or delete."""
    container = get_container()

    with st.form(f"edit_goal_{goal.id}", border=False):
        title = st.text_input("Title", value=goal.title)
        left, right = st.columns(2)
        status = enum_select(
            "Status",
            members(GoalStatus),
            key=f"goal_status_{goal.id}",
            current=goal.status,
            parent=left,
        )
        progress = right.slider(
            "Progress",
            0,
            100,
            int(goal.progress_percent),
            help="Ignored when the goal has milestones - those decide the figure.",
        )
        if st.form_submit_button("Save"):
            run_action(
                "update goal",
                container.goals.update,
                goal.id,
                GoalUpdate(title=title, status=status, progress_percent=float(progress)),
                success="Goal updated.",
            )

    with st.form(f"add_milestone_{goal.id}", border=False, clear_on_submit=True):
        milestone_title = st.text_input("New milestone", placeholder="Deploy the API")
        if st.form_submit_button("Add milestone") and milestone_title.strip():
            run_action(
                "add milestone",
                container.goals.add_milestone,
                goal.id,
                MilestoneInput(title=milestone_title),
                success="Milestone added.",
            )

    if confirm_button("Delete goal", key=f"delete_goal_{goal.id}"):
        run_action(
            "delete goal",
            container.goals.delete,
            goal.id,
            success=f"{goal.title!r} deleted.",
        )


def _weekly() -> None:
    """Weekly numeric targets, fed by the daily records."""
    container = get_container()
    monday = week_start(container.clock.today())
    st.caption(f"Week beginning {monday.isoformat()}")

    targets = container.goals.list_weekly(monday)
    if targets:
        for target in targets:
            label = target.metric.value.replace("_", " ").title()
            value = (
                minutes(target.achieved_value)
                if target.metric.unit == "minutes"
                else f"{target.achieved_value:.0f}"
            )
            goal_value = (
                minutes(target.target_value)
                if target.metric.unit == "minutes"
                else f"{target.target_value:.0f}"
            )
            st.progress(
                target.progress_fraction,
                text=f"{'✅' if target.is_met else '▶'} {label}: {value} of {goal_value} "
                f"({percent(target.progress_fraction)})",
            )
    else:
        st.caption("No weekly targets set. Add one below.")

    st.divider()
    with st.form("weekly_goal", clear_on_submit=True):
        left, right = st.columns([3, 2])
        metric = enum_select("Metric", members(WeeklyMetric), key="weekly_metric", parent=left)
        amount = right.number_input("Target", min_value=1.0, value=600.0, step=30.0)
        st.caption("Minute-based metrics take minutes; count-based metrics take a count.")
        if st.form_submit_button("Set weekly target", type="primary"):
            run_action(
                "set weekly goal",
                container.goals.set_weekly,
                WeeklyGoalInput(week_start=monday, metric=metric, target_value=float(amount)),
                success="Weekly target set.",
            )


def _new_goal() -> None:
    """The goal creation form."""
    container = get_container()

    with st.form("new_goal", clear_on_submit=True):
        title = st.text_input("Title", max_chars=200)
        description = st.text_area("Description", height=80)

        left, middle, right = st.columns(3)
        category = enum_select(
            "Category", members(GoalCategory), key="new_goal_category", parent=left
        )
        priority = enum_select(
            "Priority",
            members(TaskPriority),
            key="new_goal_priority",
            current=TaskPriority.MEDIUM,
            format_func=lambda value: PRIORITY_BADGES[value],
            parent=middle,
        )
        target_date = right.date_input("Target date", value=None)

        milestone_text = st.text_area(
            "Milestones (one per line)",
            placeholder="Python async fundamentals\nREST fundamentals\nBuild API\nDeploy API",
            height=110,
        )

        if st.form_submit_button("Create goal", type="primary") and title.strip():
            milestones = [
                MilestoneInput(title=line.strip(), sort_order=(index + 1) * 10)
                for index, line in enumerate(milestone_text.splitlines())
                if line.strip()
            ]
            run_action(
                "create goal",
                container.goals.create,
                GoalCreate(
                    title=title,
                    description=description or None,
                    category=category,
                    priority=priority,
                    start_date=container.clock.today(),
                    target_date=target_date,
                    milestones=milestones,
                ),
                success=f"Created {title.strip()!r}.",
            )


__all__ = ["render"]
