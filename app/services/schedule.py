"""When a scheduled email should run next.

All arithmetic is in the schedule's own timezone (`Asia/Kolkata` by default) and
converted to UTC for storage. India has no daylight saving, but `zoneinfo` means
a schedule moved to a DST zone still lands on the right local wall-clock time.

A working day is Monday to Friday and not listed in `hr_holidays`. Weekends are
therefore never "shifted": a daily schedule that chooses Saturday sends on
Saturday. Only a holiday triggers the schedule's `shift` or `skip` rule.

A monthly rule of day 29-31 on a shorter month uses that month's last day, so
February is never skipped.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.hr import Holiday
from ..models.email import FREQUENCIES, HOLIDAY_RULES, MONTH_RULES

UTC = timezone.utc
DEFAULT_TZ = "Asia/Kolkata"
HORIZON_DAYS = 800


class ScheduleError(ValueError):
    """A schedule that cannot be interpreted; the API turns this into a 422."""


def parse_time(value: str) -> time:
    try:
        hour, minute = str(value).strip().split(":")
        parsed = time(int(hour), int(minute))
    except (TypeError, ValueError):
        raise ScheduleError(f"Time {value!r} must be HH:MM, 24-hour")
    if not (0 <= parsed.hour <= 23 and 0 <= parsed.minute <= 59):
        raise ScheduleError(f"Time {value!r} is outside a day")
    return parsed


def parse_times(values) -> list[time]:
    if not values:
        raise ScheduleError("A schedule needs at least one time of day")
    out = sorted({parse_time(v) for v in values})
    return out


def _expand_field(field: str, low: int, high: int, label: str) -> set[int]:
    values: set[int] = set()
    for item in field.split(","):
        item = item.strip()
        step = 1
        if "/" in item:
            item, raw_step = item.split("/", 1)
            try:
                step = int(raw_step)
            except ValueError:
                raise ScheduleError(f"Cron {label} step is not a number: {raw_step!r}")
            if step < 1:
                raise ScheduleError(f"Cron {label} step must be positive")
        if item == "*":
            start, end = low, high
        elif "-" in item:
            raw_start, raw_end = item.split("-", 1)
            try:
                start, end = int(raw_start), int(raw_end)
            except ValueError:
                raise ScheduleError(f"Cron {label} range is not numeric: {item!r}")
        else:
            try:
                start = end = int(item)
            except ValueError:
                raise ScheduleError(f"Cron {label} value is not a number: {item!r}")
        if start < low or end > high or start > end:
            raise ScheduleError(f"Cron {label} value {item!r} is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expression: str) -> dict:
    parts = (expression or "").split()
    if len(parts) != 5:
        raise ScheduleError("A custom schedule needs a five-field cron: minute hour day month weekday")
    return {
        "minutes": sorted(_expand_field(parts[0], 0, 59, "minute")),
        "hours": sorted(_expand_field(parts[1], 0, 23, "hour")),
        "days": _expand_field(parts[2], 1, 31, "day of month"),
        "months": _expand_field(parts[3], 1, 12, "month"),
        # Cron weekday: 0 or 7 is Sunday and 1 is Monday; Python counts Monday
        # as 0, so shift into Python's week before comparing with date.weekday().
        "weekdays": {(7 if d == 0 else d) - 1
                     for d in _expand_field(parts[4], 0, 7, "weekday")},
        "day_all": parts[2].strip() == "*",
        "weekday_all": parts[4].strip() == "*",
    }


def validate(schedule) -> None:
    """Raise ScheduleError for anything the worker could not honour."""
    frequency = getattr(schedule, "frequency", None)
    if frequency not in FREQUENCIES:
        raise ScheduleError(f"Unknown frequency {frequency!r}")
    if getattr(schedule, "holiday_rule", "shift") not in HOLIDAY_RULES:
        raise ScheduleError("holiday_rule must be 'shift' or 'skip'")
    try:
        ZoneInfo(getattr(schedule, "timezone", DEFAULT_TZ) or DEFAULT_TZ)
    except Exception:
        raise ScheduleError("Unknown timezone")
    if frequency == "custom":
        parse_cron(getattr(schedule, "custom_cron", ""))
        return
    parse_times(getattr(schedule, "times", None))
    if frequency in ("weekdays", "weekly"):
        days = getattr(schedule, "weekdays", None) or []
        if frequency == "weekly" and not days:
            raise ScheduleError("A weekly schedule needs at least one weekday")
        if any(int(d) < 0 or int(d) > 6 for d in days):
            raise ScheduleError("Weekdays must be 0 (Monday) to 6 (Sunday)")
    if frequency == "monthly":
        rule = getattr(schedule, "month_rule", None)
        if rule not in MONTH_RULES:
            raise ScheduleError("A monthly schedule needs day, last_day or first_working_day")
        if rule == "day" and not 1 <= int(getattr(schedule, "month_day", 0) or 0) <= 31:
            raise ScheduleError("A monthly day must be between 1 and 31")


def holidays_between(db: Session, start: date, end: date) -> set[date]:
    rows = db.scalars(select(Holiday).where(Holiday.date >= start,
                                            Holiday.date <= end)).all()
    return {h.date for h in rows}


def is_working_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def _last_day(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _first_working_day(day: date, holidays: set[date]) -> date:
    cursor = day.replace(day=1)
    while cursor.month == day.month:
        if is_working_day(cursor, holidays):
            return cursor
        cursor += timedelta(days=1)
    return day


def _monthly_matches(schedule, day: date, holidays: set[date]) -> bool:
    rule = getattr(schedule, "month_rule", None)
    if rule == "last_day":
        return day == _last_day(day)
    if rule == "first_working_day":
        return day == _first_working_day(day, holidays)
    wanted = min(int(getattr(schedule, "month_day", 1) or 1), _last_day(day).day)
    return day.day == wanted


def _cron_matches(schedule, day: date) -> bool:
    cron = parse_cron(getattr(schedule, "custom_cron", ""))
    if day.month not in cron["months"]:
        return False
    day_ok = day.day in cron["days"]
    weekday_ok = day.weekday() in cron["weekdays"]
    if cron["day_all"] and cron["weekday_all"]:
        return True
    if cron["day_all"]:
        return weekday_ok
    if cron["weekday_all"]:
        return day_ok
    return day_ok or weekday_ok


def _times_for(schedule) -> list[time]:
    if getattr(schedule, "frequency", None) == "custom":
        cron = parse_cron(getattr(schedule, "custom_cron", ""))
        return [time(h, m) for h in cron["hours"] for m in cron["minutes"]]
    return parse_times(getattr(schedule, "times", None))


def _day_matches(schedule, day: date, holidays: set[date]) -> bool:
    frequency = getattr(schedule, "frequency", None)
    if frequency == "daily":
        return True
    if frequency == "weekdays":
        return day.weekday() < 5
    if frequency == "weekly":
        return day.weekday() in {int(d) for d in (getattr(schedule, "weekdays", None) or [])}
    if frequency == "monthly":
        return _monthly_matches(schedule, day, holidays)
    if frequency == "custom":
        return _cron_matches(schedule, day)
    return False


def _next_working_day(day: date, holidays: set[date]) -> date:
    cursor = day + timedelta(days=1)
    for _ in range(60):
        if is_working_day(cursor, holidays):
            return cursor
        cursor += timedelta(days=1)
    return cursor


def next_run(schedule, after: datetime, holidays: set[date] | None = None) -> datetime | None:
    """The next UTC instant this schedule should fire, strictly after `after`."""
    holidays = holidays or set()
    if after.tzinfo is None:
        raise ScheduleError("next_run needs an aware datetime")
    zone = ZoneInfo(getattr(schedule, "timezone", DEFAULT_TZ) or DEFAULT_TZ)
    after_utc = after.astimezone(UTC)
    local_after = after_utc.astimezone(zone)
    start = local_after.date()
    times = _times_for(schedule)

    for offset in range(HORIZON_DAYS):
        day = start + timedelta(days=offset)
        if not _day_matches(schedule, day, holidays):
            continue
        holiday = day in holidays
        if holiday and getattr(schedule, "holiday_rule", "shift") == "skip":
            continue
        target = _next_working_day(day, holidays) if holiday else day
        for slot in times:
            if holiday and getattr(schedule, "holiday_rule", "shift") == "skip":
                break
            local = datetime.combine(target, slot, tzinfo=zone)
            utc = local.astimezone(UTC)
            if utc > after_utc:
                return utc
    return None


def run_key(schedule_id: int, slot: datetime) -> str:
    return f"schedule:{schedule_id}:{slot.astimezone(UTC):%Y%m%dT%H%M%SZ}"


def describe(schedule) -> str:
    """A short, human sentence for the schedule list."""
    frequency = getattr(schedule, "frequency", None)
    times = getattr(schedule, "times", None) or []
    slot_text = ", ".join(times[:3]) + ("…" if len(times) > 3 else "")
    if frequency == "daily":
        base = f"Every day at {slot_text}"
    elif frequency == "weekdays":
        base = f"Monday to Friday at {slot_text}"
    elif frequency == "weekly":
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        picked = ", ".join(names[int(d)] for d in (getattr(schedule, "weekdays", None) or []))
        base = f"Weekly on {picked} at {slot_text}"
    elif frequency == "monthly":
        rule = getattr(schedule, "month_rule", None)
        if rule == "last_day":
            base = f"Last day of the month at {slot_text}"
        elif rule == "first_working_day":
            base = f"First working day of the month at {slot_text}"
        else:
            base = f"Day {getattr(schedule, 'month_day', '')} of the month at {slot_text}"
    elif frequency == "custom":
        base = f"Cron {getattr(schedule, 'custom_cron', '')}"
    else:
        base = str(frequency)
    return f"{base} · {getattr(schedule, 'timezone', DEFAULT_TZ)}"
