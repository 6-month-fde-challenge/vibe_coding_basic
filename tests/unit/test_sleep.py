"""Sleep arithmetic, especially across midnight."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import ValidationError
from app.domain.sleep.calculations import (
    MAX_SLEEP_MINUTES,
    SleepWindow,
    clock_time_variance,
    consistency_score,
    median_clock_time,
    resolve_sleep_window,
    summarize_sleep,
)

KOLKATA = ZoneInfo("Asia/Kolkata")
LONDON = ZoneInfo("Europe/London")
LOG_DATE = date(2026, 9, 10)


def window(
    sleep_time: time,
    wake_time: time,
    tz: ZoneInfo = KOLKATA,
    *,
    log_date: date = LOG_DATE,
    bedtime: time | None = None,
) -> SleepWindow:
    """Resolve a night with the test's defaults."""
    return resolve_sleep_window(
        log_date=log_date,
        sleep_time=sleep_time,
        wake_time=wake_time,
        tz=tz,
        bedtime=bedtime,
    )


class TestCrossingMidnight:
    def test_the_worked_example_from_the_brief(self):
        # 23:30 -> 06:30 is seven hours, not minus seventeen.
        assert window(time(23, 30), time(6, 30)).duration_minutes == pytest.approx(420.0)

    def test_falling_asleep_is_placed_on_the_previous_evening(self):
        result = window(time(23, 30), time(6, 30))
        local_sleep = result.sleep_at.astimezone(KOLKATA)
        local_wake = result.wake_at.astimezone(KOLKATA)
        assert local_sleep.date() == LOG_DATE - timedelta(days=1)
        assert local_wake.date() == LOG_DATE

    def test_a_night_entirely_after_midnight_stays_on_the_log_date(self):
        result = window(time(1, 0), time(8, 0))
        assert result.sleep_at.astimezone(KOLKATA).date() == LOG_DATE
        assert result.duration_minutes == pytest.approx(420.0)

    def test_exactly_midnight_to_eight(self):
        assert window(time(0, 0), time(8, 0)).duration_minutes == pytest.approx(480.0)

    def test_bedtime_before_midnight_with_sleep_after_it(self):
        result = window(time(0, 30), time(7, 0), bedtime=time(23, 45))
        assert result.latency_minutes == pytest.approx(45.0)
        assert result.bedtime_at is not None
        assert result.bedtime_at < result.sleep_at

    def test_bedtime_and_sleep_on_the_same_evening(self):
        result = window(time(23, 30), time(6, 30), bedtime=time(23, 0))
        assert result.latency_minutes == pytest.approx(30.0)

    def test_stored_instants_are_utc(self):
        result = window(time(23, 30), time(6, 30))
        assert result.sleep_at.tzinfo is UTC
        assert result.wake_at.tzinfo is UTC

    def test_the_same_clock_times_in_another_timezone_are_the_same_length(self):
        kolkata = window(time(23, 30), time(6, 30), KOLKATA)
        london = window(time(23, 30), time(6, 30), LONDON)
        assert kolkata.duration_minutes == london.duration_minutes
        assert kolkata.sleep_at != london.sleep_at


class TestImplausibleNights:
    def test_a_twenty_minute_night_is_refused(self):
        with pytest.raises(ValidationError):
            window(time(6, 10), time(6, 30))

    def test_a_twenty_hour_night_is_refused(self):
        with pytest.raises(ValidationError) as caught:
            window(time(10, 0), time(6, 0), log_date=LOG_DATE)
        assert "hours" in caught.value.user_message()

    def test_the_upper_bound_itself_is_accepted(self):
        result = window(time(12, 30), time(6, 30))
        assert result.duration_minutes == pytest.approx(MAX_SLEEP_MINUTES)


class TestClockStatistics:
    def test_variance_treats_times_either_side_of_midnight_as_neighbours(self):
        spread = clock_time_variance([time(23, 50), time(0, 10)])
        assert spread == pytest.approx(10.0)

    def test_variance_needs_at_least_two_readings(self):
        assert clock_time_variance([time(23, 0)]) is None
        assert clock_time_variance([]) is None

    def test_median_bedtime_across_midnight(self):
        assert median_clock_time([time(23, 40), time(0, 0), time(0, 20)]) == time(0, 0)

    def test_median_of_nothing_is_nothing(self):
        assert median_clock_time([]) is None

    def test_consistency_is_perfect_for_identical_nights(self):
        assert consistency_score([420.0, 420.0, 420.0]) == pytest.approx(100.0)

    def test_consistency_falls_as_nights_scatter(self):
        scattered = consistency_score([300.0, 540.0])
        steady = consistency_score([410.0, 430.0])
        assert scattered is not None
        assert steady is not None
        assert scattered < steady

    def test_consistency_needs_two_nights(self):
        assert consistency_score([420.0]) is None


class TestSummary:
    def _windows(self, durations: list[float]) -> list[SleepWindow]:
        """Build synthetic windows of the given lengths."""
        out = []
        for index, minutes in enumerate(durations):
            day = LOG_DATE - timedelta(days=len(durations) - index - 1)
            wake = datetime(day.year, day.month, day.day, 6, 30, tzinfo=KOLKATA)
            out.append(
                SleepWindow(
                    log_date=day,
                    bedtime_at=None,
                    sleep_at=(wake - timedelta(minutes=minutes)).astimezone(UTC),
                    wake_at=wake.astimezone(UTC),
                    duration_minutes=minutes,
                )
            )
        return out

    def test_empty_input_is_safe(self):
        stats = summarize_sleep([], target_minutes=450, tz=KOLKATA)
        assert not stats.has_data
        assert stats.average_minutes is None
        assert stats.sleep_debt_minutes == 0.0

    def test_a_single_night(self):
        stats = summarize_sleep(self._windows([420.0]), target_minutes=450, tz=KOLKATA)
        assert stats.nights == 1
        assert stats.average_minutes == pytest.approx(420.0)
        assert stats.sleep_debt_minutes == pytest.approx(30.0)
        assert stats.consistency_score is None

    def test_debt_is_positive_when_under_target(self):
        stats = summarize_sleep(self._windows([400.0] * 5), target_minutes=450, tz=KOLKATA)
        assert stats.sleep_debt_minutes == pytest.approx(250.0)

    def test_debt_is_negative_when_over_target(self):
        stats = summarize_sleep(self._windows([500.0] * 3), target_minutes=450, tz=KOLKATA)
        assert stats.sleep_debt_minutes == pytest.approx(-150.0)

    def test_seven_day_average_uses_only_the_last_seven(self):
        durations = [300.0] * 10 + [480.0] * 7
        stats = summarize_sleep(self._windows(durations), target_minutes=450, tz=KOLKATA)
        assert stats.average_7d == pytest.approx(480.0)
        assert stats.average_minutes is not None
        assert stats.average_minutes < 480.0

    def test_order_of_input_does_not_matter(self):
        windows = self._windows([400.0, 450.0, 500.0])
        forwards = summarize_sleep(windows, target_minutes=450, tz=KOLKATA)
        backwards = summarize_sleep(list(reversed(windows)), target_minutes=450, tz=KOLKATA)
        assert forwards.average_minutes == backwards.average_minutes
        assert forwards.average_7d == backwards.average_7d
