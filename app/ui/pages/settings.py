"""The settings page: profile, targets, weights, categories, data."""

from __future__ import annotations

from zoneinfo import available_timezones

import streamlit as st

from app.domain.productivity.weights import COMPONENT_LABELS, ProductivityWeights
from app.models.enums import CategoryKind, members
from app.schemas.activity import CategoryCreate
from app.schemas.common import DateRange
from app.schemas.health import ProfileUpdate
from app.services.export_service import EXPORTABLE
from app.services.import_service import IMPORTABLE, ImportReport
from app.services.time_tracking_service import OVERLAP_SETTING_KEY
from app.ui.components.forms import confirm_button, enum_select
from app.ui.state import flush_action_message, get_container, reset_container, run_action

#: Common timezones offered first; the full IANA list is behind the search.
_COMMON_ZONES = ("Asia/Kolkata", "UTC", "Europe/London", "America/New_York", "Asia/Singapore")


def render() -> None:
    """Draw the settings page."""
    st.title("Settings")
    flush_action_message()

    profile_tab, scoring_tab, categories_tab, data_tab = st.tabs(
        ["Profile & targets", "Scoring", "Categories", "Data"]
    )
    with profile_tab:
        _profile()
    with scoring_tab:
        _scoring()
    with categories_tab:
        _categories()
    with data_tab:
        _data()


def _profile() -> None:
    """Name, timezone, week start and the daily targets."""
    container = get_container()
    profile = container.health.get_profile()

    with st.form("profile_settings"):
        left, right = st.columns(2)
        name = left.text_input("Display name", value=profile.display_name)

        zones = list(_COMMON_ZONES) + sorted(available_timezones() - set(_COMMON_ZONES))
        timezone = right.selectbox(
            "Timezone",
            zones,
            index=zones.index(profile.timezone) if profile.timezone in zones else 0,
            help="Defines your day boundary, so it changes which day a late-night record lands on.",
        )

        weekday_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        week_start = st.selectbox("Week starts on", weekday_names, index=profile.week_start)

        st.markdown("**Daily targets**")
        first, second, third = st.columns(3)
        sleep = first.number_input(
            "Sleep (minutes)", 0, 1440, profile.target_sleep_minutes, step=15
        )
        study = second.number_input(
            "Study (minutes)", 0, 1440, profile.target_study_minutes, step=15
        )
        coding = third.number_input(
            "Coding (minutes)", 0, 1440, profile.target_coding_minutes, step=15
        )

        fourth, fifth = st.columns(2)
        teaching = fourth.number_input(
            "Teaching (minutes)", 0, 1440, profile.target_teaching_minutes, step=15
        )
        exercise = fifth.number_input(
            "Exercise (minutes)", 0, 1440, profile.target_exercise_minutes, step=15
        )

        if st.form_submit_button("Save profile", type="primary"):
            changed_timezone = timezone != profile.timezone
            saved = run_action(
                "update profile",
                container.health.update_profile,
                ProfileUpdate(
                    display_name=name,
                    timezone=timezone,
                    week_start=weekday_names.index(week_start),
                    target_sleep_minutes=int(sleep),
                    target_study_minutes=int(study),
                    target_coding_minutes=int(coding),
                    target_teaching_minutes=int(teaching),
                    target_exercise_minutes=int(exercise),
                ),
                success="Profile saved.",
                rerun=not changed_timezone,
            )
            if saved is not None and changed_timezone:
                # The clock is built once at startup from the profile, so a
                # timezone change has to rebuild the container.
                reset_container()
                st.rerun()


def _scoring() -> None:
    """The productivity weights, with a live preview."""
    container = get_container()
    weights = container.app_settings.weights()

    st.caption(
        "The daily score is a weighted average of six components. Weights must sum to 1.0. "
        "Components with no data are dropped and the rest are rescaled, so a partly tracked "
        "day is still scored out of 100."
    )

    values: dict[str, float] = {}
    columns = st.columns(3)
    for index, (key, label) in enumerate(COMPONENT_LABELS.items()):
        values[key] = columns[index % 3].number_input(
            label,
            min_value=0.0,
            max_value=1.0,
            value=getattr(weights, key),
            step=0.05,
            key=f"weight_{key}",
        )

    total = sum(values.values())
    if abs(total - 1.0) > 0.01:
        st.warning(f"Weights currently sum to {total:.2f}. They need to sum to 1.00.", icon="⚠️")

    left, middle, right = st.columns(3)
    if left.button("Save weights", type="primary", use_container_width=True):
        run_action(
            "save weights",
            lambda: container.app_settings.set_weights_from_values(**values),
            success="Weights saved.",
        )
    if middle.button("Balance them for me", use_container_width=True):
        run_action(
            "rescale weights",
            lambda: container.app_settings.set_weights(ProductivityWeights.rescaled(**values)),
            success="Weights rescaled to sum to 1.00.",
        )
    if right.button("Reset to defaults", use_container_width=True):
        run_action(
            "reset weights",
            container.app_settings.reset_weights,
            success="Weights reset.",
        )

    st.divider()
    st.markdown("**Recompute past scores**")
    st.caption("Changing the weights does not rewrite history until you ask it to.")
    days = st.slider("How far back", 7, 365, 90)
    if st.button("Recompute"):
        today = container.clock.today()
        count = run_action(
            "recompute scores",
            container.productivity.recompute_range,
            DateRange.last_n_days(today, days),
            success=None,
            rerun=False,
        )
        if count is not None:
            st.success(f"{count} day(s) rescored.", icon="✅")

    st.divider()
    st.markdown("**Time tracking**")
    prevent = st.toggle(
        "Refuse overlapping time entries",
        value=bool(container.app_settings.get(OVERLAP_SETTING_KEY, False)),
        help="Off by default - people genuinely do two things at once.",
    )
    if st.button("Save time-tracking setting"):
        run_action(
            "save overlap setting",
            container.app_settings.set,
            OVERLAP_SETTING_KEY,
            prevent,
            success="Setting saved.",
        )


def _categories() -> None:
    """Add, rename and retire the user's categories."""
    container = get_container()

    kind = enum_select("Which categories?", members(CategoryKind), key="settings_category_kind")
    categories = container.categories.list_kind(kind, active_only=False)

    st.dataframe(
        [
            {
                "Name": item.name,
                "Productive": "Yes" if item.is_productive else "No",
                "Active": "Yes" if item.is_active else "No",
                "Order": item.sort_order,
            }
            for item in categories
        ],
        hide_index=True,
        use_container_width=True,
    )

    with st.form("new_category", clear_on_submit=True):
        left, middle, right = st.columns([3, 2, 2])
        name = left.text_input("New category name", max_chars=80)
        icon = middle.text_input("Icon", max_chars=4, placeholder="🏏")
        productive = right.checkbox(
            "Counts as productive", help="Only meaningful for time categories"
        )
        if st.form_submit_button("Add category") and name.strip():
            run_action(
                "create category",
                container.categories.create,
                CategoryCreate(kind=kind, name=name, icon=icon or None, is_productive=productive),
                success=f"Added {name.strip()!r}.",
            )

    if categories:
        chosen = st.selectbox("Manage", [item.name for item in categories], key="manage_category")
        target = next(item for item in categories if item.name == chosen)
        left, right = st.columns(2)
        if target.is_active and left.button("Deactivate", use_container_width=True):
            run_action(
                "deactivate category",
                container.categories.deactivate,
                target.id,
                success=f"{target.name} hidden from the forms. History is unchanged.",
            )
        with right:
            if confirm_button(
                "Delete",
                key=f"delete_category_{target.id}",
                help_text="Only possible when nothing uses it",
            ):
                run_action(
                    "delete category",
                    container.categories.delete,
                    target.id,
                    success=f"{target.name} deleted.",
                )


def _data() -> None:
    """Export, import and backup."""
    container = get_container()

    st.markdown("**Export**")
    st.caption("Your data is yours. Everything here is a plain file you can open elsewhere.")

    dataset = st.selectbox("Dataset", EXPORTABLE)
    left, middle, right = st.columns(3)
    left.download_button(
        "Download CSV",
        data=container.exports.export_csv(dataset),
        file_name=f"{dataset}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    middle.download_button(
        "Download JSON",
        data=container.exports.export_json(dataset),
        file_name=f"{dataset}.json",
        mime="application/json",
        use_container_width=True,
    )
    right.download_button(
        "Download Excel (all)",
        data=container.exports.export_excel(list(EXPORTABLE)),
        file_name="habit_tracker.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.divider()
    st.markdown("**Full backup**")
    st.download_button(
        "Download complete backup (JSON)",
        data=container.exports.full_backup(),
        file_name=f"habit_tracker_backup_{container.clock.today().isoformat()}.json",
        mime="application/json",
    )

    st.divider()
    st.markdown("**Import**")
    st.caption(
        f"Files are capped at {container.settings.max_upload_mb} MB. Every row is validated by "
        "the same rules the forms use, so an import cannot create a record you could not have "
        "typed by hand."
    )

    import_dataset = st.selectbox("Import into", IMPORTABLE, key="import_dataset")
    uploaded = st.file_uploader("CSV or JSON", type=["csv", "json"], key="import_file")

    if uploaded is not None and st.button("Import file", type="primary"):
        content = uploaded.getvalue()
        service = (
            container.imports.import_csv
            if uploaded.name.lower().endswith(".csv")
            else container.imports.import_json
        )
        report = run_action(
            "import data", service, import_dataset, content, success=None, rerun=False
        )
        if report is not None:
            _show_report(report)

    st.divider()
    st.markdown("**Restore a backup**")
    backup_file = st.file_uploader("Backup JSON", type=["json"], key="restore_file")
    if backup_file is not None and st.button("Restore backup"):
        reports = run_action(
            "restore backup",
            container.imports.restore_backup,
            backup_file.getvalue(),
            success=None,
            rerun=False,
        )
        if reports:
            for report in reports:
                _show_report(report)
            st.cache_data.clear()


def _show_report(report: ImportReport) -> None:
    """Render one import report."""
    if report.ok:
        st.success(
            f"{report.dataset}: {report.created} created, {report.skipped} skipped.", icon="✅"
        )
    else:
        st.warning(
            f"{report.dataset}: {report.created} created, {report.skipped} skipped, "
            f"{report.failed} rejected.",
            icon="⚠️",
        )
        for message in report.errors:
            st.caption(message)


__all__ = ["render"]
