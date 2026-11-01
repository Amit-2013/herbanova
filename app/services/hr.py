"""Shared HR helpers: geofence distance, attendance upsert, leave balances,
working-day calendar and approval request creation.

Rules live here so the API and the approval handlers cannot drift apart.
"""
import math
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import is_admin, role_permissions
from ..models.core import ApprovalRequest
from ..models.hr import (Attendance, Holiday, LeaveApplication, LeaveBalance, LeaveType, PeriodLock,
                         Shift, WorkLocation)
from ..models.users import Employee

ZERO = Decimal(0)

# Bank, PAN, UAN and ESI are personal identifiers the brief restricts to the
# Administrator, the MD-equivalent confidential right and the HR roles the
# Administrator allows. Everyone else sees the last four characters only.
CONFIDENTIAL_EMPLOYEE_FIELDS = ("bank_account_no", "bank_ifsc", "pan", "uan", "esi_no")
FULL_HR_SCOPE_KEYS = ("hr:write", "hr:payroll_prepare", "hr:confidential")

# Office timings are wall-clock times in the business's time zone. Attendance is
# stored as a UTC instant, so late/early must be compared after converting to
# India time; otherwise a 09:30 shift reads as a 04:00 UTC start.
IST = timezone(timedelta(hours=5, minutes=30))


def business_today() -> date:
    return datetime.now(IST).date()


def local_time(dt: datetime) -> datetime:
    """The attendance instant as the office wall clock sees it."""
    return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)


def shift_late_minutes(shift: Shift | None, check_in: datetime | None) -> int:
    """Minutes after the shift start, less the configured grace period."""
    if shift is None or check_in is None:
        return 0
    local = local_time(check_in)
    start = local.replace(hour=shift.start_time.hour, minute=shift.start_time.minute,
                          second=0, microsecond=0)
    return max(0, int((local - start).total_seconds() // 60) - (shift.grace_minutes or 0))


def shift_early_minutes(shift: Shift | None, check_out: datetime | None) -> int:
    """Minutes before the shift end. Overnight shifts end on the next day."""
    if shift is None or check_out is None:
        return 0
    local = local_time(check_out)
    end = local.replace(hour=shift.end_time.hour, minute=shift.end_time.minute,
                        second=0, microsecond=0)
    start = local.replace(hour=shift.start_time.hour, minute=shift.start_time.minute,
                          second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    return max(0, int((end - local).total_seconds() // 60))


def default_shift(db: Session) -> Shift | None:
    """The general office shift employees are placed on unless another is chosen."""
    return db.scalar(select(Shift).where(Shift.name == "General", Shift.status == "active"))


def employee_for_user(db: Session, user) -> Employee | None:
    if not getattr(user, "employee_id", None):
        return None
    return db.get(Employee, user.employee_id)


def team_employee_ids(db: Session, manager_id: int) -> set[int]:
    """The manager and everyone below them in the reporting chain.

    Depth is bounded by the set itself, so a bad manager_id cycle cannot loop.
    """
    ids = {manager_id}
    frontier = [manager_id]
    while frontier:
        children = set(db.scalars(select(Employee.id).where(
            Employee.manager_id.in_(frontier))).all())
        frontier = list(children - ids)
        ids |= children
    return ids


def scoped_employee_ids(db: Session, user) -> set[int] | None:
    """Which employees the viewer may act on. None means the whole company.

    HR administrators (hr:write / payroll / confidential) and the Administrator
    see everyone; a reporting manager sees their reporting chain; everyone else
    sees only themselves. An unlinked login sees nobody.
    """
    if is_admin(db, user):
        return None
    perms = role_permissions(db, user)
    if any(k in perms for k in FULL_HR_SCOPE_KEYS):
        return None
    me = employee_for_user(db, user)
    if not me:
        return set()
    if {"hr:attendance_manage", "hr:leave_approve"} & perms:
        return team_employee_ids(db, me.id)
    return {me.id}


def may_view_confidential(db: Session, user, employee: Employee) -> bool:
    """Full bank/ID values: Administrator, confidential HR rights, or the person."""
    if is_admin(db, user):
        return True
    if role_permissions(db, user) & {"hr:confidential", "hr:payroll_prepare"}:
        return True
    me = employee_for_user(db, user)
    return bool(me and me.id == employee.id)


def mask_secret(value, keep: int = 4) -> str | None:
    if value is None or value == "":
        return value
    text = str(value)
    if len(text) <= keep:
        return "*" * len(text)
    return "•" * (len(text) - keep) + text[-keep:]


def distance_m(lat1, lon1, lat2, lon2) -> float:
    """Haversine distance in metres."""
    r = 6371000
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geofence_result(office: WorkLocation | None, lat, lon) -> str:
    if office is None or office.latitude is None or office.longitude is None:
        return "na"
    if lat is None or lon is None:
        return "unavailable"
    radius = office.geofence_radius_m or 200
    return "inside" if distance_m(lat, lon, office.latitude, office.longitude) <= radius else "outside"


def get_or_create_attendance(db: Session, employee_id: int, day: date) -> Attendance:
    row = db.scalar(select(Attendance).where(Attendance.employee_id == employee_id,
                                             Attendance.date == day))
    if row is None:
        row = Attendance(employee_id=employee_id, date=day, status="present")
        db.add(row)
        db.flush()
    return row


def leave_working_days(db: Session, employee: Employee, first: date,
                       last: date) -> list[date]:
    """Leave is counted in working days: weekly offs and holidays are skipped."""
    offs = weekly_off_days(db, employee)
    holidays = holidays_for(db, employee, first, last)
    out, day = [], first
    while day <= last:
        if is_working_day(employee, offs, holidays, day):
            out.append(day)
        day += timedelta(days=1)
    return out


def apply_attendance_for_leave(db: Session, application: LeaveApplication,
                               leave_type: LeaveType, employee: Employee) -> None:
    """Approved leave is reflected in attendance without duplicating the leave row.

    Only working days are touched: a Friday-to-Monday application must not mark
    the weekend as leave. A half-day application keeps the day's status and
    records which half was leave.
    """
    status = "paid_leave" if leave_type.kind == "paid" else "unpaid_leave"
    portion = getattr(application, "portion", None) or "full"
    for day in leave_working_days(db, employee, application.date_from,
                                  application.date_to):
        row = get_or_create_attendance(db, application.employee_id, day)
        if row.status != "od":
            row.status = status
            row.leave_portion = None if portion == "full" else portion
            row.remarks = f"Leave {leave_type.code} (application {application.id})" \
                + ("" if portion == "full" else f", {portion.replace('_', ' ')}")


def apply_attendance_for_od(db: Session, od) -> None:
    day = od.date
    end = od.end_date or od.date
    while day <= end:
        row = get_or_create_attendance(db, od.employee_id, day)
        if row.status not in ("paid_leave", "unpaid_leave"):
            row.status = "od"
            row.remarks = f"On duty: {od.purpose} (OD {od.id})"
        day += timedelta(days=1)


def leave_balance(db: Session, employee_id: int, leave_type_id: int, year: int) -> LeaveBalance:
    bal = db.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == employee_id,
        LeaveBalance.leave_type_id == leave_type_id, LeaveBalance.year == year))
    if bal is None:
        lt = db.get(LeaveType, leave_type_id)
        bal = LeaveBalance(employee_id=employee_id, leave_type_id=leave_type_id, year=year,
                           entitled=lt.default_days if lt else ZERO)
        db.add(bal)
        db.flush()
    return bal


def weekly_off_days(db: Session, employee: Employee) -> set[int]:
    """Weekday numbers the employee's shift treats as the weekly off."""
    shift = db.get(Shift, employee.shift_id) if employee.shift_id else None
    return set(shift.weekly_offs if shift else [5, 6])


def holidays_for(db: Session, employee: Employee, first: date, last: date) -> set[date]:
    """Holidays that apply to this employee's branch and office.

    A holiday row with neither branch nor location applies company-wide.
    """
    rows = db.scalars(select(Holiday).where(
        Holiday.date >= first, Holiday.date <= last)).all()
    return {h.date for h in rows
            if (h.location_id is None or h.location_id == employee.office_id)
            and (h.branch_id is None or h.branch_id == employee.branch_id)}


def is_working_day(employee: Employee, offs: set[int], holidays: set[date],
                   day: date) -> bool:
    return day.weekday() not in offs and day not in holidays


def working_days(db: Session, employee: Employee, year: int, month: int) -> list[date]:
    offs = weekly_off_days(db, employee)
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    holidays = holidays_for(db, employee, first, last)
    out, day = [], first
    while day <= last:
        if is_working_day(employee, offs, holidays, day):
            out.append(day)
        day += timedelta(days=1)
    return out


def active_period_lock(db: Session, scope: str, day: date) -> PeriodLock | None:
    """The active lock covering that day's month, if any."""
    return db.scalar(select(PeriodLock).where(
        PeriodLock.scope == scope, PeriodLock.year == day.year,
        PeriodLock.month == day.month, PeriodLock.active.is_(True)))


def active_lock_for_range(db: Session, scope: str, first: date,
                          last: date) -> PeriodLock | None:
    """The first active lock whose month overlaps the range, if any."""
    for lock in db.scalars(select(PeriodLock).where(
            PeriodLock.scope == scope, PeriodLock.active.is_(True))
            .order_by(PeriodLock.year, PeriodLock.month)).all():
        lock_first = date(lock.year, lock.month, 1)
        lock_last = date(lock.year, lock.month, monthrange(lock.year, lock.month)[1])
        if lock_first <= last and lock_last >= first:
            return lock
    return None


def request_approval(db: Session, *, record_type: str, record_id: int, requested_by: int,
                     reasons: list[str], detail: dict, document_number: str | None = None,
                     subject: str | None = None, requested_dates: str | None = None,
                     approver_role: str | None = None) -> ApprovalRequest:
    ar = ApprovalRequest(
        record_type=record_type, record_id=record_id, reasons=reasons,
        requested_by=requested_by, detail=detail,
        request_no=f"AP-{datetime.now():%Y%m%d}-{record_id:05d}"[:40],
        document_number=document_number, subject=subject, requested_dates=requested_dates,
        pending_approver_role=approver_role)
    db.add(ar)
    db.flush()
    from . import hr_notify
    hr_notify.notify_request(db, ar, employee_id=(detail or {}).get("employee_id"))
    return ar


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
