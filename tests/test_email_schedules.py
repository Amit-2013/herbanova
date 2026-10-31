"""Schedule arithmetic: the calendar rules the brief asks for, tested directly.

No database is needed except for the holiday lookup, which the caller supplies
as a set here. Every expectation is a wall-clock time in the schedule's own
timezone converted to UTC, so a DST zone is proven, not assumed.
"""
from datetime import date, datetime, timezone

import pytest

from app.services import schedule


class Stub:
    def __init__(self, **overrides):
        self.id = 7
        self.frequency = "daily"
        self.timezone = "Asia/Kolkata"
        self.weekdays = []
        self.times = ["09:00"]
        self.month_day = None
        self.month_rule = None
        self.custom_cron = None
        self.holiday_rule = "shift"
        for key, value in overrides.items():
            setattr(self, key, value)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_daily_sends_at_the_local_slot():
    assert schedule.next_run(Stub(), utc(2026, 11, 1, 0, 0)) == utc(2026, 11, 1, 3, 30)


def test_daily_after_todays_slot_waits_for_tomorrow():
    assert schedule.next_run(Stub(), utc(2026, 11, 1, 4, 0)) == utc(2026, 11, 2, 3, 30)


def test_daily_takes_the_earliest_of_several_slots():
    schedule_obj = Stub(times=["18:00", "09:00", "09:00"])
    assert schedule.next_run(schedule_obj, utc(2026, 11, 1, 2, 0)) == utc(2026, 11, 1, 3, 30)


def test_weekdays_skip_the_weekend():
    # 2026-10-30 is a Friday; the next weekday slot is Monday 2 November.
    assert schedule.next_run(Stub(frequency="weekdays"), utc(2026, 10, 30, 4, 0)) \
        == utc(2026, 11, 2, 3, 30)


def test_weekly_runs_only_on_the_chosen_weekday():
    schedule_obj = Stub(frequency="weekly", weekdays=[0])       # Monday
    assert schedule.next_run(schedule_obj, utc(2026, 10, 28, 0, 0)) == utc(2026, 11, 2, 3, 30)


def test_monthly_last_day_handles_a_short_month():
    schedule_obj = Stub(frequency="monthly", month_rule="last_day")
    assert schedule.next_run(schedule_obj, utc(2027, 2, 10, 0, 0)) == utc(2027, 2, 28, 3, 30)


def test_monthly_day_29_to_31_clamps_to_the_month_end():
    schedule_obj = Stub(frequency="monthly", month_rule="day", month_day=31)
    assert schedule.next_run(schedule_obj, utc(2027, 4, 1, 0, 0)) == utc(2027, 4, 30, 3, 30)
    assert schedule.next_run(schedule_obj, utc(2027, 4, 30, 4, 0)) == utc(2027, 5, 31, 3, 30)


def test_monthly_first_working_day_steps_over_a_holiday_and_weekend():
    holidays = {date(2027, 1, 1)}                               # Friday
    schedule_obj = Stub(frequency="monthly", month_rule="first_working_day")
    assert schedule.next_run(schedule_obj, utc(2026, 12, 20, 0, 0), holidays) \
        == utc(2027, 1, 4, 3, 30)


def test_holiday_shift_moves_to_the_next_working_day_at_the_same_time():
    holidays = {date(2026, 11, 6)}                              # Friday
    schedule_obj = Stub(holiday_rule="shift")
    assert schedule.next_run(schedule_obj, utc(2026, 11, 5, 4, 0), holidays) \
        == utc(2026, 11, 9, 3, 30)                              # Monday


def test_holiday_skip_drops_that_day_only():
    holidays = {date(2026, 11, 6)}
    schedule_obj = Stub(holiday_rule="skip")
    assert schedule.next_run(schedule_obj, utc(2026, 11, 5, 4, 0), holidays) \
        == utc(2026, 11, 7, 3, 30)                              # Saturday, a normal daily slot


def test_cron_subset_runs_on_the_named_weekday():
    schedule_obj = Stub(frequency="custom", custom_cron="0 9 * * 1")
    assert schedule.next_run(schedule_obj, utc(2026, 10, 28, 0, 0)) == utc(2026, 11, 2, 3, 30)


def test_a_dst_zone_keeps_the_local_wall_clock():
    summer = Stub(timezone="America/New_York")
    winter = Stub(timezone="America/New_York")
    assert schedule.next_run(summer, utc(2027, 7, 1, 0, 0)) == utc(2027, 7, 1, 13, 0)
    assert schedule.next_run(winter, utc(2027, 1, 1, 0, 0)) == utc(2027, 1, 1, 14, 0)


def test_run_key_is_stable_and_distinct_per_slot():
    slot = utc(2026, 11, 1, 3, 30)
    key = schedule.run_key(7, slot)
    assert key == "schedule:7:20261101T033000Z"
    assert schedule.run_key(8, slot) != key
    assert schedule.run_key(7, utc(2026, 11, 2, 3, 30)) != key


@pytest.mark.parametrize("overrides", [
    {"frequency": "hourly"},
    {"times": []},
    {"times": ["09:70"]},
    {"frequency": "weekly", "weekdays": []},
    {"frequency": "monthly", "month_rule": None},
    {"frequency": "monthly", "month_rule": "day", "month_day": 40},
    {"frequency": "custom", "custom_cron": "9 * * *"},
    {"frequency": "custom", "custom_cron": "61 * * * *"},
    {"timezone": "Mars/Phobos"},
])
def test_impossible_schedules_are_refused(overrides):
    with pytest.raises(schedule.ScheduleError):
        schedule.validate(Stub(**overrides))


def test_validate_accepts_the_shapes_the_screen_offers():
    for overrides in ({"frequency": "daily"},
                      {"frequency": "weekdays", "times": ["08:30", "17:45"]},
                      {"frequency": "weekly", "weekdays": [0, 4]},
                      {"frequency": "monthly", "month_rule": "last_day"},
                      {"frequency": "monthly", "month_rule": "first_working_day"},
                      {"frequency": "monthly", "month_rule": "day", "month_day": 31},
                      {"frequency": "custom", "custom_cron": "*/15 6-22 * * 1-5"}):
        schedule.validate(Stub(**overrides))


def test_description_is_readable():
    assert schedule.describe(Stub()) == "Every day at 09:00 · Asia/Kolkata"
    assert schedule.describe(Stub(frequency="weekly", weekdays=[0, 4])) \
        == "Weekly on Mon, Fri at 09:00 · Asia/Kolkata"
    assert schedule.describe(Stub(frequency="monthly", month_rule="last_day")) \
        == "Last day of the month at 09:00 · Asia/Kolkata"
