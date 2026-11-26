"""clock.py edge cases from DESIGN.md section 12.

All inputs are built in UTC. Boston is UTC-5 (EST) or UTC-4 (EDT).
Asia server is UTC+8 with a 04:00 reset, so the reset is 20:00 UTC every day:
3:00 PM EST in winter, 4:00 PM EDT in summer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from gplanner.clock import Clock
from gplanner.config import Settings


@pytest.fixture
def clock() -> Clock:
    return Clock(Settings.load({}))


def utc(y: int, mo: int, d: int, h: int, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def assert_local(dt: datetime, y: int, mo: int, d: int, h: int, offset_hours: int) -> None:
    """Check the wall-clock reading and UTC offset, not just the instant."""
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (y, mo, d, h, 0)
    assert dt.utcoffset() == timedelta(hours=offset_hours)


# 1-3: winter afternoon around the 3 PM EST reset (Wed 25 Nov 2026)


def test_259pm_est_is_still_today(clock: Clock) -> None:
    now = utc(2026, 11, 25, 19, 59)  # 2:59 PM EST
    assert clock.server_day(now) == date(2026, 11, 25)
    assert_local(clock.next_reset_local(now), 2026, 11, 25, 15, -5)


def test_301pm_est_is_already_tomorrow(clock: Clock) -> None:
    now = utc(2026, 11, 25, 20, 1)  # 3:01 PM EST
    assert clock.server_day(now) == date(2026, 11, 26)
    assert_local(clock.next_reset_local(now), 2026, 11, 26, 15, -5)


def test_exact_reset_instant_rolls_over(clock: Clock) -> None:
    now = utc(2026, 11, 25, 20, 0, 0)  # 3:00:00 PM EST
    assert clock.server_day(now) == date(2026, 11, 26)
    assert clock.server_day(now - timedelta(microseconds=1)) == date(2026, 11, 25)
    assert_local(clock.next_reset_local(now), 2026, 11, 26, 15, -5)


# 4: summer, where the reset is 4 PM EDT, not 3 PM


def test_summer_reset_is_4pm_edt(clock: Clock) -> None:
    at_301 = utc(2026, 7, 15, 19, 1)  # Wed 3:01 PM EDT
    at_401 = utc(2026, 7, 15, 20, 1)  # Wed 4:01 PM EDT
    assert clock.server_day(at_301) == date(2026, 7, 15)
    assert clock.server_day(at_401) == date(2026, 7, 16)
    assert_local(clock.next_reset_local(at_301), 2026, 7, 15, 16, -4)


# 5-6: DST ends Sun 1 Nov 2026 at 2 AM EDT


def test_dst_end_reset_moves_from_4pm_to_3pm(clock: Clock) -> None:
    sat_noon_edt = utc(2026, 10, 31, 16)
    sun_noon_est = utc(2026, 11, 1, 17)
    assert_local(clock.next_reset_local(sat_noon_edt), 2026, 10, 31, 16, -4)
    assert_local(clock.next_reset_local(sun_noon_est), 2026, 11, 1, 15, -5)


@pytest.mark.parametrize(
    ("now", "fold"),
    [
        (utc(2026, 11, 1, 5, 30), 0),  # 1:30 AM EDT
        (utc(2026, 11, 1, 6, 30), 1),  # 1:30 AM EST, the repeated hour
    ],
)
def test_ambiguous_130am_on_dst_end(clock: Clock, now: datetime, fold: int) -> None:
    local = clock.to_local(now)
    assert (local.hour, local.minute, local.fold) == (1, 30, fold)
    assert clock.server_day(now) == date(2026, 11, 1)
    assert_local(clock.next_reset_local(now), 2026, 11, 1, 15, -5)


# 7: DST starts Sun 14 Mar 2027 at 2 AM EST


def test_dst_start_reset_moves_from_3pm_to_4pm(clock: Clock) -> None:
    sat_noon_est = utc(2027, 3, 13, 17)
    sun_159am_est = utc(2027, 3, 14, 6, 59)  # just before clocks jump
    assert_local(clock.next_reset_local(sat_noon_est), 2027, 3, 13, 15, -5)
    assert_local(clock.next_reset_local(sun_159am_est), 2027, 3, 14, 16, -4)


# 8: Saturday afternoon into Sunday (Sunday = everything open)


def test_saturday_afternoon_into_sunday(clock: Clock) -> None:
    before = clock.server_day(utc(2026, 11, 28, 19, 59))  # Sat 2:59 PM EST
    after = clock.server_day(utc(2026, 11, 28, 20, 1))  # Sat 3:01 PM EST
    assert before == date(2026, 11, 28)
    assert before.weekday() == 5
    assert after == date(2026, 11, 29)
    assert after.weekday() == 6


# 9-10: Sunday afternoon into Monday, and the weekly window


def test_sunday_afternoon_into_monday(clock: Clock) -> None:
    before = utc(2026, 11, 29, 19, 59)  # Sun 2:59 PM EST
    after = utc(2026, 11, 29, 20, 1)  # Sun 3:01 PM EST
    assert clock.server_day(before) == date(2026, 11, 29)
    assert not clock.is_server_monday(before)
    assert clock.server_day(after) == date(2026, 11, 30)
    assert clock.is_server_monday(after)
    assert_local(clock.next_reset_local(after), 2026, 11, 30, 15, -5)


def test_server_monday_ends_monday_afternoon(clock: Clock) -> None:
    assert clock.is_server_monday(utc(2026, 11, 30, 19, 59))  # Mon 2:59 PM EST
    assert not clock.is_server_monday(utc(2026, 11, 30, 20, 1))  # Mon 3:01 PM EST


# 11-12: to_local and naive datetimes


def test_to_local_in_est_and_edt(clock: Clock) -> None:
    assert_local(clock.to_local(utc(2026, 11, 25, 20)), 2026, 11, 25, 15, -5)
    assert_local(clock.to_local(utc(2026, 7, 15, 20)), 2026, 7, 15, 16, -4)


def test_naive_datetimes_rejected(clock: Clock) -> None:
    naive = datetime(2026, 11, 25, 20, 0)  # noqa: DTZ001
    with pytest.raises(ValueError):
        clock.to_local(naive)
    with pytest.raises(ValueError):
        clock.server_day(naive)
    with pytest.raises(ValueError):
        clock.next_reset_local(naive)
    with pytest.raises(ValueError):
        clock.is_server_monday(naive)


def test_default_now_is_used_when_omitted(clock: Clock) -> None:
    reset = clock.next_reset_utc()
    assert reset.tzinfo is UTC
    assert timedelta(0) < reset - datetime.now(UTC) <= timedelta(days=1)


# 13: everything comes from config


def test_offset_and_reset_hour_come_from_config() -> None:
    now = utc(2026, 11, 25, 20, 1)  # 3:01 PM EST; Asia server day is already 26 Nov

    america = Clock(Settings.load({"SERVER_UTC_OFFSET": "-5", "RESET_HOUR": "4"}))
    assert america.server_day(now) == date(2026, 11, 25)
    assert_local(america.next_reset_local(now), 2026, 11, 26, 4, -5)

    later_reset = Clock(Settings.load({"RESET_HOUR": "5"}))
    assert later_reset.server_day(now) == date(2026, 11, 25)
    assert_local(later_reset.next_reset_local(now), 2026, 11, 25, 16, -5)

    berlin = Clock(Settings.load({"LOCAL_TZ": "Europe/Berlin"}))
    assert_local(berlin.next_reset_local(now), 2026, 11, 26, 21, 1)
