"""HR management API.

- Employee master (extends the existing employees table, no duplicate master).
- Office/geofence attendance, manual attendance and corrections.
- Leave balances and applications; on-duty requests.
- Salary components, structures and monthly payroll.
- The HR dashboard.

Permissions are enforced on every endpoint. An employee may act for themselves
with `hr:attendance_self`; team-wide actions need the corresponding manager/HR
right. Decisions go through the central Approvals module (`hr_approvals.py`).
"""
from calendar import monthrange
from datetime import date, date as date_cls, datetime, time, timedelta, timezone
from decimal import Decimal
import csv
import io
from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.downloads import safe_filename
from ..core.rbac import current_user, is_admin, require, role_permissions
from ..models.core import ApprovalRequest, AuditLog, User
from ..models.hr import (Announcement, Attendance, AttendanceCorrection, AttendanceRule, Branch,
                         Department, EmployeeAsset, EmployeeDocument, Holiday, HRNotification,
                         ImportBatch, LeaveApplication, LeaveBalance, LeaveType, LetterTemplate,
                         ODRequest, PayrollEntry, PayrollPeriod, PeriodLock, SalaryComponent,
                         SalaryStructure, SalaryStructureLine, SavedFilter, Shift, WorkLocation)
from ..models.users import Employee
from ..services import hr as hr_svc
from ..services import hr_documents
from ..services import hr_notify
from ..services import hr_reports
from ..services import payroll as payroll_svc
from ..services.audit import audit
from ..services.exports import safe_text
from ..services.salary_slip import build_slip

router = APIRouter(prefix="/api/hr", tags=["hr"])

CENT = Decimal("0.01")


def _m(value) -> str | None:
    """Money leaves the API as a string, as it does everywhere else in Herbanova.

    Handing JSON floats to the browser loses paise on large payroll totals.
    """
    if value is None:
        return None
    return str(Decimal(value).quantize(CENT))


def _perms(db: Session, user) -> set[str]:
    return role_permissions(db, user)


def _can(db: Session, user, *keys) -> bool:
    p = _perms(db, user)
    return is_admin(db, user) or any(k in p for k in keys)


def _require_hr_view(db: Session, user) -> None:
    """Team-wide readers and self-service staff. Every caller still scopes rows."""
    if not _can(db, user, "hr:read", "hr:attendance_self"):
        raise HTTPException(403, "Your role cannot view HR records")


def _self_employee(db: Session, user) -> Employee:
    emp = hr_svc.employee_for_user(db, user)
    if not emp:
        raise HTTPException(409, "Your login is not linked to an employee record")
    return emp


def _employee_or_403(db: Session, user, employee_id: int | None) -> Employee:
    """A self-service user may only name their own record; a manager their team.

    Scope comes from the reporting chain, not from the request body, and is
    enforced for every route that accepts an employee_id.
    """
    me = hr_svc.employee_for_user(db, user)
    scope = hr_svc.scoped_employee_ids(db, user)
    if employee_id:
        if scope is not None and employee_id not in scope:
            raise HTTPException(403, "That employee is outside your team")
        emp = db.get(Employee, employee_id)
        if not emp:
            raise HTTPException(404, "Employee not found")
        return emp
    if scope is None:
        if me:
            return me
        raise HTTPException(404, "Employee not found")
    if not me:
        raise HTTPException(409, "Your login is not linked to an employee record")
    return me


def _refuse_confidential_write(db: Session, user, data: dict) -> None:
    """Only confidential HR rights or payroll may set bank/ID values."""
    if any(data.get(k) is not None for k in hr_svc.CONFIDENTIAL_EMPLOYEE_FIELDS) \
            and not _can(db, user, "hr:confidential", "hr:payroll_prepare"):
        raise HTTPException(403, "Confidential HR rights are required to change bank or ID "
                                 "details")


def _assert_period_open(db: Session, scope: str, day: date, user,
                        override_reason: str | None = None,
                        action: str = "") -> None:
    """Refuse a change inside a locked month.

    The lock is the accounting cut-off: after payroll has been settled the month
    is closed. Only the Administrator may reopen a single entry, and only with a
    recorded reason; that override is written to the audit trail.
    """
    lock = hr_svc.active_period_lock(db, scope, day)
    if lock is None:
        if override_reason:
            raise HTTPException(422, f"The {scope} period {day:%B %Y} is not locked; "
                                     "remove the override reason")
        return
    if override_reason:
        if not is_admin(db, user):
            raise HTTPException(403, "Only the Administrator may override a locked period")
        audit(db, user.id, f"hr.{scope}.lock_override", f"period_lock:{lock.id}",
              {"day": str(day), "action": action, "reason": override_reason})
        return
    raise HTTPException(423, f"The {scope} period {day:%B %Y} is locked: {lock.reason}")


def _assert_range_open(db: Session, scope: str, first: date, last: date, user,
                       override_reason: str | None = None, action: str = "") -> None:
    lock = hr_svc.active_lock_for_range(db, scope, first, last)
    if lock is None:
        if override_reason:
            raise HTTPException(422, f"The {scope} period is not locked; "
                                     "remove the override reason")
        return
    if override_reason:
        if not is_admin(db, user):
            raise HTTPException(403, "Only the Administrator may override a locked period")
        audit(db, user.id, f"hr.{scope}.lock_override", f"period_lock:{lock.id}",
              {"from": str(first), "to": str(last), "action": action,
               "reason": override_reason})
        return
    raise HTTPException(423, f"The {scope} period {lock.year}-{lock.month:02d} is locked: "
                             f"{lock.reason}")


# --------------------------------------------------------------- schemas
class EmployeeIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    full_name: str = Field(min_length=2, max_length=120)
    department: str | None = Field(default=None, max_length=60)
    designation: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    joining_date: date | None = None
    manager_id: int | None = None
    branch_id: int | None = None
    office_id: int | None = None
    department_id: int | None = None
    shift_id: int | None = None
    hr_admin_id: int | None = None
    employment_type: str | None = Field(default=None, max_length=30)
    work_schedule: str | None = Field(default=None, max_length=80)
    date_of_exit: date | None = None
    date_of_birth: date | None = None
    probation_end_date: date | None = None
    confirmation_date: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    exit_reason: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    emergency_name: str | None = Field(default=None, max_length=120)
    emergency_phone: str | None = Field(default=None, max_length=40)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_no: str | None = Field(default=None, max_length=30)
    bank_ifsc: str | None = Field(default=None, max_length=11)
    pan: str | None = Field(default=None, max_length=10)
    uan: str | None = Field(default=None, max_length=20)
    esi_no: str | None = Field(default=None, max_length=20)
    attendance_policy: str | None = Field(default=None, max_length=80)
    leave_policy: str | None = Field(default=None, max_length=80)

    @field_validator("code")
    @classmethod
    def norm_code(cls, v): return v.strip().upper()

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        # The settings employee form and this one write the same table, so the
        # same address rule applies whichever entry point created the record.
        if v and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("invalid email address")
        return v


class EmployeePatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    department: str | None = None
    designation: str | None = None
    phone: str | None = None
    email: str | None = None
    joining_date: date | None = None
    manager_id: int | None = None
    branch_id: int | None = None
    office_id: int | None = None
    department_id: int | None = None
    shift_id: int | None = None
    hr_admin_id: int | None = None
    employment_type: str | None = None
    work_schedule: str | None = None
    date_of_exit: date | None = None
    date_of_birth: date | None = None
    probation_end_date: date | None = None
    confirmation_date: date | None = None
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    exit_reason: str | None = Field(default=None, max_length=200)
    address: str | None = None
    emergency_name: str | None = None
    emergency_phone: str | None = None
    bank_name: str | None = None
    bank_account_no: str | None = None
    bank_ifsc: str | None = None
    pan: str | None = None
    uan: str | None = None
    esi_no: str | None = None
    attendance_policy: str | None = None
    leave_policy: str | None = None
    status: str | None = None

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        if v and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("invalid email address")
        return v


EMPLOYEE_FIELDS = ["id", "code", "full_name", "department", "designation", "phone", "email",
                   "joining_date", "manager_id", "status", "branch_id", "office_id",
                   "department_id", "shift_id", "hr_admin_id", "employment_type",
                   "work_schedule", "date_of_exit", "date_of_birth", "probation_end_date",
                   "confirmation_date", "notice_period_days", "exit_reason", "address",
                   "emergency_name", "emergency_phone", "bank_name", "bank_account_no",
                   "bank_ifsc", "pan", "uan", "esi_no", "attendance_policy", "leave_policy"]


def _employee_dict(db: Session, e: Employee, viewer=None) -> dict:
    d = {k: getattr(e, k) for k in EMPLOYEE_FIELDS}
    # The login link is stored on both sides; read the user side too so an
    # older one-way link still shows as linked and is never offered as free.
    user = (db.get(User, e.user_id) if e.user_id
            else db.scalar(select(User).where(User.employee_id == e.id)))
    d["user_id"] = user.id if user else None
    d["has_photo"] = bool(e.photo_path)
    # Bank and ID numbers leave the server masked unless the viewer holds the
    # confidential right or is looking at their own record.
    full = True if viewer is None else hr_svc.may_view_confidential(db, viewer, e)
    d["confidential_visible"] = full
    if not full:
        for key in hr_svc.CONFIDENTIAL_EMPLOYEE_FIELDS:
            d[key] = hr_svc.mask_secret(d.get(key))
    return d


def _normalise_employee_location(db: Session, data: dict,
                                 current: Employee | None = None) -> None:
    """Keep branch and office consistent: an office decides its own branch.

    A PATCH that touches neither field is left alone, so editing a phone number
    never re-validates historic location data.
    """
    if "branch_id" not in data and "office_id" not in data:
        return
    branch_id = data["branch_id"] if "branch_id" in data else (
        current.branch_id if current else None)
    office_id = data["office_id"] if "office_id" in data else (
        current.office_id if current else None)
    if branch_id is not None:
        branch = db.get(Branch, branch_id)
        if not branch:
            raise HTTPException(404, "Branch not found")
        if (current is None or current.branch_id != branch_id) and branch.status != "active":
            raise HTTPException(422, "That branch is inactive; choose an active branch")
    if office_id is not None:
        office = db.get(WorkLocation, office_id)
        if not office:
            raise HTTPException(404, "Office not found")
        if (current is None or current.office_id != office_id) and office.status != "active":
            raise HTTPException(422, "That office is inactive; choose an active office")
        if office.branch_id is not None:
            if branch_id is not None and branch_id != office.branch_id:
                raise HTTPException(422, "That office belongs to a different branch")
            data["branch_id"] = office.branch_id


def _employee_rows(db: Session, emps: list[Employee], viewer=None) -> list[dict]:
    """Directory rows plus the names and attendance policy the People screen shows."""
    branches = {b.id: b for b in db.scalars(select(Branch)).all()}
    offices = {o.id: o for o in db.scalars(select(WorkLocation)).all()}
    rules = list(db.scalars(select(AttendanceRule)
                            .where(AttendanceRule.active.is_(True))).all())
    today = hr_svc.business_today()
    out = []
    for e in emps:
        d = _employee_dict(db, e, viewer)
        d["branch_name"] = branches[e.branch_id].name if e.branch_id in branches else None
        d["office_name"] = offices[e.office_id].name if e.office_id in offices else None
        req = hr_svc.resolve_attendance_requirement(db, e, today, rules, offices)
        d["attendance_required"] = req.required
        d["attendance_self_service"] = req.self_service
        d["attendance_rule"] = req.source
        out.append(d)
    return out


def _next_occurrence(d: date, today: date) -> date:
    """The next time this month/day comes round, on or after today."""
    try:
        nxt = d.replace(year=today.year)
    except ValueError:                      # 29 February in a common year
        nxt = date(today.year, 2, 28)
    if nxt < today:
        try:
            nxt = d.replace(year=today.year + 1)
        except ValueError:
            nxt = date(today.year + 1, 2, 28)
    return nxt


@router.get("/dashboard")
def dashboard(day: date | None = None, from_date: date | None = None,
              to_date: date | None = None, branch_id: int | None = None,
              office_id: int | None = None, db: Session = Depends(get_db),
              user=Depends(require("hr:read"))):
    """One screen for the HR home page, scoped to the viewer's team.

    The tiles describe the selected range (default: this month to today); the
    "today" figures describe `day`. Every list is capped for the payload; the
    counts are complete.
    """
    today = hr_svc.business_today()
    day = day or today
    from_date = from_date or today.replace(day=1)
    to_date = to_date or today
    if to_date < from_date:
        raise HTTPException(422, "The range end cannot be before its start")
    if (to_date - from_date).days > 366:
        raise HTTPException(422, "Choose a range of at most 366 days")

    scope = hr_svc.scoped_employee_ids(db, user)
    all_emps = db.scalars(select(Employee)).all()
    if scope is not None:
        all_emps = [e for e in all_emps if e.id in scope]
    if branch_id:
        all_emps = [e for e in all_emps if e.branch_id == branch_id]
    if office_id:
        all_emps = [e for e in all_emps if e.office_id == office_id]
    emp_ids = {e.id for e in all_emps}
    active = [e for e in all_emps if e.status == "active"]
    active_ids = {e.id for e in active}
    rules = list(db.scalars(select(AttendanceRule)
                            .where(AttendanceRule.active.is_(True))).all())
    offices = {o.id: o for o in db.scalars(select(WorkLocation)).all()}
    required_today = {e.id for e in active
                      if hr_svc.resolve_attendance_requirement(db, e, day, rules,
                                                               offices).required}

    day_rows = db.scalars(select(Attendance).where(
        Attendance.date == day, Attendance.employee_id.in_(emp_ids or {-1}))).all()
    att = {}
    for row in day_rows:
        att[row.status] = att.get(row.status, 0) + 1

    month_start = today.replace(day=1)
    new_joiners_month = sum(1 for e in all_emps
                            if e.joining_date and month_start <= e.joining_date <= today)
    exits_month = sum(1 for e in all_emps
                      if e.date_of_exit and month_start <= e.date_of_exit <= today)
    exits_range = sum(1 for e in all_emps
                      if e.date_of_exit and from_date <= e.date_of_exit <= to_date)
    # Attrition for the range: leavers / people who were on the rolls at its start.
    opening = sum(1 for e in all_emps if e.joining_date and e.joining_date <= from_date
                  and (e.date_of_exit is None or e.date_of_exit >= from_date))
    attrition = round(exits_range * 100 / opening, 1) if opening else None

    probation_due = [e for e in active if e.probation_end_date
                     and today <= e.probation_end_date <= today + timedelta(days=30)]
    expiring_docs = db.scalars(select(EmployeeDocument).where(
        EmployeeDocument.status == "active",
        EmployeeDocument.expires_on.is_not(None),
        EmployeeDocument.expires_on >= today,
        EmployeeDocument.expires_on <= today + timedelta(days=60),
        EmployeeDocument.employee_id.in_(emp_ids or {-1}))).all()

    pending_hr = db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.status == "pending",
        ApprovalRequest.record_type.like("hr_%"))).all()
    if scope is not None:
        pending_hr = [a for a in pending_hr
                      if a.requested_by == user.id
                      or int((a.detail or {}).get("employee_id") or -1) in scope]
    now_local = datetime.now(hr_svc.IST)

    def age_days(dt: datetime) -> int:
        if dt is None:
            return 0
        local = dt.astimezone(hr_svc.IST) if dt.tzinfo else dt
        return max(0, (now_local.date() - local.date()).days)

    stale = [a for a in pending_hr if age_days(a.requested_at) > 3]

    trend_rows = db.execute(
        select(Attendance.date, Attendance.status, func.count())
        .where(Attendance.date >= from_date, Attendance.date <= to_date,
               Attendance.employee_id.in_(emp_ids or {-1}))
        .group_by(Attendance.date, Attendance.status)).all()
    trend = {}
    for d, status, n in trend_rows:
        bucket = trend.setdefault(d, {"date": d, "present": 0, "absent": 0,
                                      "leave": 0, "od": 0, "late": 0})
        if status in ("present", "late"):
            bucket["present"] += n
        if status == "late":
            bucket["late"] += n
        elif status == "absent":
            bucket["absent"] += n
        elif status in ("paid_leave", "unpaid_leave"):
            bucket["leave"] += n
        elif status == "od":
            bucket["od"] += n
    attendance_trend = []
    cursor = from_date
    while cursor <= to_date:
        attendance_trend.append(trend.get(cursor, {
            "date": cursor, "present": 0, "absent": 0, "leave": 0, "od": 0, "late": 0}))
        cursor += timedelta(days=1)

    leave_rows = db.scalars(select(LeaveApplication).where(
        LeaveApplication.status == "approved",
        LeaveApplication.date_from <= to_date,
        LeaveApplication.date_to >= from_date,
        LeaveApplication.employee_id.in_(emp_ids or {-1}))).all()
    leave_types = {t.id: t for t in db.scalars(select(LeaveType)).all()}
    leave_by_type = {}
    for app in leave_rows:
        t = leave_types.get(app.leave_type_id)
        key = t.code if t else str(app.leave_type_id)
        entry = leave_by_type.setdefault(key, {
            "code": key, "name": t.name if t else "Unknown", "days": Decimal(0),
            "applications": 0})
        entry["days"] += app.days
        entry["applications"] += 1

    birthdays = []
    anniversaries = []
    for e in active:
        if e.date_of_birth:
            nxt = _next_occurrence(e.date_of_birth, today)
            if (nxt - today).days <= 30:
                birthdays.append({"employee_id": e.id, "code": e.code,
                                  "full_name": e.full_name, "date": nxt,
                                  "days_away": (nxt - today).days,
                                  "turning": nxt.year - e.date_of_birth.year})
        if e.joining_date:
            nxt = _next_occurrence(e.joining_date, today)
            years = nxt.year - e.joining_date.year
            if years >= 1 and (nxt - today).days <= 30:
                anniversaries.append({"employee_id": e.id, "code": e.code,
                                      "full_name": e.full_name, "date": nxt,
                                      "days_away": (nxt - today).days, "years": years})
    birthdays.sort(key=lambda x: x["date"])
    anniversaries.sort(key=lambda x: x["date"])

    holidays = db.scalars(select(Holiday).where(
        Holiday.date >= today, Holiday.date <= today + timedelta(days=90))
        .order_by(Holiday.date)).all()

    missing_punch_rows = db.scalars(select(Attendance).where(
        Attendance.date >= from_date, Attendance.date < min(today, to_date + timedelta(days=1)),
        Attendance.employee_id.in_(emp_ids or {-1}),
        Attendance.status.in_(("present", "late")),
        (Attendance.check_in.is_(None)) | (Attendance.check_out.is_(None)))).all()
    negative_rows = db.scalars(select(LeaveBalance).where(
        LeaveBalance.year == today.year,
        LeaveBalance.employee_id.in_(emp_ids or {-1}),
        LeaveBalance.entitled + LeaveBalance.carried - LeaveBalance.used
        - LeaveBalance.pending < 0)).all()
    emp_by_id = {e.id: e for e in all_emps}
    incomplete = []
    for e in active:
        missing = []
        if not e.department:
            missing.append("department")
        if not e.designation:
            missing.append("designation")
        if not e.joining_date:
            missing.append("joining date")
        if not e.manager_id:
            missing.append("manager")
        if not e.phone:
            missing.append("phone")
        if not e.email:
            missing.append("email")
        if not e.office_id:
            missing.append("office")
        if missing:
            incomplete.append({"employee_id": e.id, "code": e.code,
                               "full_name": e.full_name, "missing": missing})

    dept_rows = db.execute(
        select(Employee.department, func.count())
        .where(Employee.id.in_(active_ids or {-1})).group_by(Employee.department)).all()
    branch_rows = db.execute(
        select(Branch.name, func.count()).join(Employee, Employee.branch_id == Branch.id)
        .where(Employee.id.in_(active_ids or {-1})).group_by(Branch.name)).all()
    office_rows = db.execute(
        select(WorkLocation.name, func.count())
        .join(Employee, Employee.office_id == WorkLocation.id)
        .where(Employee.id.in_(active_ids or {-1})).group_by(WorkLocation.name)).all()

    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.year == day.year, PayrollPeriod.month == day.month))
    payable = db.scalar(select(func.coalesce(func.sum(PayrollEntry.net), 0))
                        .where(PayrollEntry.period_id == period.id)) if period else Decimal(0)
    payroll_visible = _can(db, user, "hr:confidential", "hr:payroll_prepare")

    def brief(a: ApprovalRequest) -> dict:
        return {"approval_id": a.id, "request_type": a.record_type,
                "document_number": a.document_number, "subject": a.subject,
                "age_days": age_days(a.requested_at)}

    return {
        "date": day, "from_date": from_date, "to_date": to_date,
        "total_employees": len(all_emps), "active_employees": len(active),
        "inactive_employees": len(all_emps) - len(active),
        "present_today": att.get("present", 0) + att.get("late", 0),
        "absent_today": att.get("absent", 0),
        "on_leave_today": att.get("paid_leave", 0) + att.get("unpaid_leave", 0),
        "on_od_today": att.get("od", 0),
        "late_today": att.get("late", 0),
        "early_today": att.get("early_departure", 0),
        "pending_approvals": len(pending_hr),
        "pending_leave": sum(1 for a in pending_hr if a.record_type == "hr_leave"),
        "pending_other": sum(1 for a in pending_hr if a.record_type != "hr_leave"),
        "new_joiners_month": new_joiners_month,
        "exits_month": exits_month,
        "exits_in_range": exits_range,
        "attrition_pct": attrition,
        "probation_ending_soon": len(probation_due),
        "documents_expiring": len(expiring_docs),
        "payroll_visible": payroll_visible,
        "payroll_status": period.status if (period and payroll_visible) else None,
        "salary_payable": _m(payable) if payroll_visible else None,
        "filters": {"branch_id": branch_id, "office_id": office_id},
        "attendance_required_today": len(required_today),
        "attendance_exempt_today": len(active) - len(required_today),
        "attendance_trend": attendance_trend,
        "by_department": [{"department": d or "Unassigned", "employees": n}
                          for d, n in dept_rows],
        "by_branch": [{"branch": b, "employees": n} for b, n in branch_rows],
        "by_office": [{"office": o, "employees": n} for o, n in office_rows],
        "leave_by_type": [{"code": v["code"], "name": v["name"],
                           "days": str(v["days"]), "applications": v["applications"]}
                          for v in leave_by_type.values()],
        "birthdays": birthdays,
        "anniversaries": anniversaries,
        "holidays": [{"date": h.date, "name": h.name} for h in holidays],
        "needs_attention": {
            "missing_punches": {
                "count": len(missing_punch_rows),
                "rows": [{"attendance_id": r.id, "employee_id": r.employee_id,
                          "employee": emp_by_id[r.employee_id].full_name
                          if r.employee_id in emp_by_id else "?",
                          "date": r.date} for r in missing_punch_rows[:20]]},
            "negative_leave": {
                "count": len(negative_rows),
                "rows": [{"employee_id": r.employee_id, "leave_type_id": r.leave_type_id,
                          "year": r.year,
                          "employee": emp_by_id[r.employee_id].full_name
                          if r.employee_id in emp_by_id else "?"} for r in negative_rows[:20]]},
            "stale_approvals": {"count": len(stale),
                                "rows": [brief(a) for a in stale[:20]]},
            "incomplete_records": {"count": len(incomplete),
                                   "rows": incomplete[:20]},
        },
    }


# --------------------------------------------------------------- employees
EMPLOYEE_SORTS = {"code": Employee.code, "name": Employee.full_name,
                  "department": Employee.department, "joining_date": Employee.joining_date,
                  "status": Employee.status}


def _employee_filters(stmt, *, scope, q=None, department=None, branch_id=None, status=None,
                      office_id=None, department_id=None, manager_id=None,
                      employment_type=None, joined_from=None, joined_to=None,
                      exit_from=None, exit_to=None, probation_due=False, incomplete=False):
    """The directory filters, shared by the list, the CSV export and saved views."""
    today = hr_svc.business_today()
    if scope is not None:
        stmt = stmt.where(Employee.id.in_(scope or {-1}))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Employee.code.ilike(like) | Employee.full_name.ilike(like)
                          | Employee.department.ilike(like) | Employee.designation.ilike(like))
    for column, value in ((Employee.department, department),
                          (Employee.branch_id, branch_id), (Employee.status, status),
                          (Employee.office_id, office_id),
                          (Employee.department_id, department_id),
                          (Employee.manager_id, manager_id),
                          (Employee.employment_type, employment_type)):
        if value is not None and value != "":
            stmt = stmt.where(column == value)
    if joined_from:
        stmt = stmt.where(Employee.joining_date >= joined_from)
    if joined_to:
        stmt = stmt.where(Employee.joining_date <= joined_to)
    if exit_from:
        stmt = stmt.where(Employee.date_of_exit >= exit_from)
    if exit_to:
        stmt = stmt.where(Employee.date_of_exit <= exit_to)
    if probation_due:
        stmt = stmt.where(Employee.status == "active",
                          Employee.probation_end_date.is_not(None),
                          Employee.probation_end_date >= today,
                          Employee.probation_end_date <= today + timedelta(days=30))
    if incomplete:
        stmt = stmt.where(
            Employee.status == "active",
            or_(Employee.department.is_(None), Employee.department == "",
                Employee.designation.is_(None), Employee.designation == "",
                Employee.joining_date.is_(None), Employee.manager_id.is_(None),
                Employee.phone.is_(None), Employee.phone == "",
                Employee.email.is_(None), Employee.email == "",
                Employee.office_id.is_(None)))
    return stmt


@router.get("/employees")
def list_employees(response: Response, q: str | None = None, department: str | None = None,
                   branch_id: int | None = None, status: str | None = None,
                   office_id: int | None = None, department_id: int | None = None,
                   manager_id: int | None = None, employment_type: str | None = None,
                   joined_from: date | None = None, joined_to: date | None = None,
                   exit_from: date | None = None, exit_to: date | None = None,
                   probation_due: bool = False, incomplete: bool = False,
                   sort: Literal["code", "name", "department", "joining_date", "status"] = "code",
                   order: Literal["asc", "desc"] = "asc",
                   page: int | None = Query(None, ge=1),
                   page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
                   user=Depends(require("hr:read"))):
    scope = hr_svc.scoped_employee_ids(db, user)
    stmt = _employee_filters(
        select(Employee), scope=scope, q=q, department=department, branch_id=branch_id,
        status=status, office_id=office_id, department_id=department_id,
        manager_id=manager_id, employment_type=employment_type, joined_from=joined_from,
        joined_to=joined_to, exit_from=exit_from, exit_to=exit_to,
        probation_due=probation_due, incomplete=incomplete)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    column = EMPLOYEE_SORTS[sort]
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc(), Employee.code)
    if page:
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    return _employee_rows(db, list(db.scalars(stmt).all()), user)


@router.get("/employees/export.csv")
def export_employees(response: Response, q: str | None = None, department: str | None = None,
                     branch_id: int | None = None, status: str | None = None,
                     office_id: int | None = None, department_id: int | None = None,
                     manager_id: int | None = None, employment_type: str | None = None,
                     joined_from: date | None = None, joined_to: date | None = None,
                     exit_from: date | None = None, exit_to: date | None = None,
                     probation_due: bool = False, incomplete: bool = False,
                     db: Session = Depends(get_db), user=Depends(require("hr:read"))):
    """The directory as CSV. Confidential columns are masked per viewer, as in the API."""
    scope = hr_svc.scoped_employee_ids(db, user)
    stmt = _employee_filters(
        select(Employee), scope=scope, q=q, department=department, branch_id=branch_id,
        status=status, office_id=office_id, department_id=department_id,
        manager_id=manager_id, employment_type=employment_type, joined_from=joined_from,
        joined_to=joined_to, exit_from=exit_from, exit_to=exit_to,
        probation_due=probation_due, incomplete=incomplete).order_by(Employee.code)
    emps = db.scalars(stmt).all()
    managers = {e.id: e.full_name for e in db.scalars(select(Employee)).all()}
    out = io.StringIO()
    writer = csv.writer(out)
    columns = ["code", "full_name", "department", "designation", "status", "joining_date",
               "date_of_exit", "manager", "phone", "email", "employment_type", "branch",
               "office", "attendance_required", "bank_account_no", "bank_ifsc", "pan", "uan",
               "esi_no"]
    writer.writerow(columns)
    for d in _employee_rows(db, list(emps), user):
        writer.writerow([safe_text(v) for v in (
            d["code"], d["full_name"], d["department"] or "", d["designation"] or "",
            d["status"], d["joining_date"] or "", d["date_of_exit"] or "",
            managers.get(d["manager_id"], ""),
            d["phone"] or "", d["email"] or "", d["employment_type"] or "",
            d["branch_name"] or "", d["office_name"] or "",
            "yes" if d["attendance_required"] else "no",
            d["bank_account_no"] or "", d["bank_ifsc"] or "", d["pan"] or "",
            d["uan"] or "", d["esi_no"] or "")])
    audit(db, user.id, "hr.employee.export", "employee:export", {"rows": len(emps)})
    db.commit()
    # The BOM lets Excel read Hindi names and ₹ amounts as UTF-8. Formula-like
    # text is prefixed with an apostrophe so a name cannot run in a spreadsheet.
    return Response(content=("\ufeff" + out.getvalue()).encode("utf-8"),
                    media_type="text/csv; charset=utf-8", headers={
                        "Content-Disposition": 'attachment; filename="employees.csv"',
                        "Cache-Control": "no-store"})


# ------------------------------------------------- saved views and bulk import
class SavedFilterIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    params: dict = Field(default_factory=dict)
    view: Literal["employees"] = "employees"


@router.get("/saved-filters")
def list_saved_filters(view: str = "employees", db: Session = Depends(get_db),
                       user=Depends(require("hr:read"))):
    rows = db.scalars(select(SavedFilter).where(
        SavedFilter.user_id == user.id, SavedFilter.view == view)
        .order_by(SavedFilter.name)).all()
    return [{"id": r.id, "name": r.name, "view": r.view, "params": r.params} for r in rows]


@router.post("/saved-filters", status_code=201)
def save_filter(body: SavedFilterIn, db: Session = Depends(get_db),
                user=Depends(require("hr:read"))):
    row = SavedFilter(user_id=user.id, view=body.view, name=body.name.strip(),
                      params=body.params)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A saved view with that name already exists")
    db.commit()
    return {"id": row.id, "name": row.name, "view": row.view, "params": row.params}


@router.delete("/saved-filters/{filter_id}")
def delete_saved_filter(filter_id: int, db: Session = Depends(get_db),
                        user=Depends(require("hr:read"))):
    row = db.get(SavedFilter, filter_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Saved view not found")
    db.delete(row)
    db.commit()
    return {"deleted": True}


IMPORT_COLUMNS = ["code", "full_name", "department", "designation", "phone", "email",
                  "joining_date", "date_of_birth", "employment_type", "manager_code",
                  "branch_code", "office_code", "department_code", "bank_account_no",
                  "bank_ifsc", "pan", "uan", "esi_no"]
# Columns the directory export adds but an import cannot set: they are derived,
# display names, or catalogue lookups by name. Accepting them keeps an exported
# file re-importable instead of rejecting it as an unknown format.
EXPORT_ONLY_COLUMNS = ["status", "date_of_exit", "manager", "branch", "office",
                       "attendance_required"]
_ESCAPABLE = ("=", "+", "-", "@", "\t", "\r")


def _unescape(value: str) -> str:
    """Undo the apostrophe the exporter puts in front of formula-like text."""
    if value.startswith("'") and len(value) > 1 and value[1] in _ESCAPABLE:
        return value[1:]
    return value


class ImportIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    csv_text: str = Field(min_length=1)
    commit: bool = False


def _parse_row(row: dict, seen_codes: set[str]) -> tuple[dict, list[str]]:
    errors = []
    data: dict = {}
    code = (row.get("code") or "").strip().upper()
    name = (row.get("full_name") or "").strip()
    if len(code) < 2:
        errors.append("code is required (2-30 characters)")
    elif code in seen_codes:
        errors.append(f"code {code} appears twice in the file")
    if len(name) < 2:
        errors.append("full_name is required")
    data["code"], data["full_name"] = code, name
    for field in ("department", "designation", "phone", "employment_type"):
        value = (row.get(field) or "").strip()
        data[field] = value or None
    email = (row.get("email") or "").strip()
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        errors.append("email is not a valid address")
    data["email"] = email or None
    for field in ("joining_date", "date_of_birth"):
        value = (row.get(field) or "").strip()
        if value:
            try:
                data[field] = date.fromisoformat(value)
            except ValueError:
                errors.append(f"{field} must be YYYY-MM-DD")
        else:
            data[field] = None
    for field in ("bank_account_no", "bank_ifsc", "pan", "uan", "esi_no"):
        value = (row.get(field) or "").strip()
        data[field] = value or None
    return data, errors


@router.get("/employees/import-template.csv")
def import_template(_=Depends(require("hr:write"))):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(IMPORT_COLUMNS)
    writer.writerow(["EMP001", "Example Name", "Sales", "Associate", "9876543210",
                     "person@example.com", "2026-01-15", "1995-06-30", "full_time",
                     "", "", "", "", "", "", "", "", ""])
    return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="employee-import-template.csv"'})


@router.post("/employees/import")
def import_employees(body: ImportIn, db: Session = Depends(get_db),
                     actor=Depends(require("hr:write"))):
    """Validate a CSV; with commit=true create the valid rows and leave an undo record."""
    if len(body.csv_text) > 2_000_000:
        raise HTTPException(413, "The import file is too large (2 MB maximum)")
    text = body.csv_text.lstrip("\ufeff")
    if not text.strip():
        raise HTTPException(422, "The import file is empty")
    if "\x00" in text:
        raise HTTPException(422, "The import file is not a text CSV file")
    try:
        reader = csv.DictReader(io.StringIO(text))
        headers = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = headers
        records = list(reader)
    except csv.Error as exc:
        raise HTTPException(422, f"The file is not valid CSV: {exc}")
    if not any(headers):
        raise HTTPException(422, "The import file is empty")
    repeated = sorted({h for h in headers if h and headers.count(h) > 1})
    if repeated:
        raise HTTPException(422, f"Repeated columns: {', '.join(repeated)}")
    missing = [h for h in ("code", "full_name") if h not in headers]
    if missing:
        raise HTTPException(422, "Missing required columns: " + ", ".join(missing))
    unknown = [h for h in headers if h and h not in IMPORT_COLUMNS
               and h not in EXPORT_ONLY_COLUMNS]
    if unknown:
        raise HTTPException(422, f"Unknown columns: {', '.join(unknown[:5])}")
    extra = next((row.get(None) for row in records if row.get(None)), None)
    if extra is not None:
        raise HTTPException(422, "A row has more values than the header")
    if not any(any((v or "").strip() for v in row.values() if isinstance(v, str))
               for row in records):
        raise HTTPException(422, "The import file has a header but no employee rows")
    has_confidential = any((row.get(k) or "").strip() for row in records
                           for k in ("bank_account_no", "bank_ifsc", "pan", "uan", "esi_no"))
    if has_confidential and not _can(db, actor, "hr:confidential", "hr:payroll_prepare"):
        raise HTTPException(403, "Confidential HR rights are required to import bank or ID data")

    existing_codes = {c for c in db.scalars(select(Employee.code)).all()}
    seen: set[str] = set()
    parsed, errors = [], []
    managers = {e.code: e.id for e in db.scalars(select(Employee)).all()}
    branches = {b.code: b.id for b in db.scalars(select(Branch)).all()}
    offices = {o.code: o.id for o in db.scalars(select(WorkLocation)).all()}
    departments = {d.code: d.id for d in db.scalars(select(Department)).all()}
    for number, row in enumerate(records, start=2):
        row = {key: _unescape(value) if isinstance(value, str) else value
               for key, value in row.items() if key is not None}
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        data, row_errors = _parse_row(row, seen)
        if data.get("code"):
            seen.add(data["code"])
            if data["code"] in existing_codes and not row_errors:
                row_errors.append(f"employee code {data['code']} already exists")
        manager_code = (row.get("manager_code") or "").strip().upper()
        if manager_code:
            if manager_code in managers:
                data["manager_id"] = managers[manager_code]
            else:
                row_errors.append(f"manager code {manager_code} not found")
        for key, source in (("branch_id", branches), ("office_id", offices),
                            ("department_id", departments)):
            value = (row.get(key.replace("_id", "_code")) or "").strip().upper()
            if value:
                if value in source:
                    data[key] = source[value]
                else:
                    row_errors.append(f"{key.replace('_id', '')} code {value} not found")
        if row_errors:
            errors.append({"row": number, "code": data.get("code"), "errors": row_errors})
        else:
            parsed.append(data)

    created_ids: list[int] = []
    if body.commit and parsed:
        for data in parsed:
            e = Employee(**data)
            db.add(e)
            db.flush()
            created_ids.append(e.id)
        batch = ImportBatch(kind="employee", filename=body.filename, total_rows=len(parsed) + len(errors),
                            created_rows=len(created_ids), error_rows=len(errors),
                            created_ids=created_ids, errors=errors, created_by=actor.id)
        db.add(batch)
        db.flush()
        audit(db, actor.id, "hr.employee.import", f"import:{batch.id}",
              {"filename": body.filename, "created": len(created_ids),
               "errors": len(errors)})
        db.commit()
        batch_id = batch.id
    else:
        db.rollback()
        batch_id = None
    return {"commit": body.commit, "batch_id": batch_id, "valid_rows": len(parsed),
            "error_rows": len(errors), "errors": errors,
            "preview": [{"code": d["code"], "full_name": d["full_name"],
                         "department": d.get("department")} for d in parsed[:20]]}


@router.post("/employees/import-batches/{batch_id}/undo")
def undo_import(batch_id: int, db: Session = Depends(get_db),
                actor=Depends(require("hr:write"))):
    """Undo a committed import by deactivating what it created. Rows are kept."""
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Import not found")
    if batch.status == "undone":
        raise HTTPException(409, "This import has already been undone")
    deactivated = 0
    for emp_id in batch.created_ids or []:
        emp = db.get(Employee, emp_id)
        if emp and emp.status == "active":
            emp.status = "inactive"
            deactivated += 1
    batch.status = "undone"
    batch.undone_at = datetime.now(timezone.utc)
    batch.undone_by = actor.id
    audit(db, actor.id, "hr.employee.import_undo", f"import:{batch.id}",
          {"employees_deactivated": deactivated})
    db.commit()
    return {"batch_id": batch.id, "status": batch.status, "employees_deactivated": deactivated}


@router.post("/employees", status_code=201)
def create_employee(body: EmployeeIn, db: Session = Depends(get_db),
                    actor=Depends(require("hr:write"))):
    if body.manager_id and not db.get(Employee, body.manager_id):
        raise HTTPException(404, "Manager not found")
    data = body.model_dump()
    _normalise_employee_location(db, data)
    _refuse_confidential_write(db, actor, data)
    if data.get("shift_id") is None:
        # New staff go on the general office shift, which is what the late /
        # early-departure calculation needs. An explicit choice still wins.
        general = hr_svc.default_shift(db)
        if general:
            data["shift_id"] = general.id
    e = Employee(**data)
    db.add(e)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Employee code already exists")
    audit(db, actor.id, "employee.create", f"employee:{e.id}",
          {"code": e.code, "full_name": e.full_name})
    db.commit()
    return _employee_dict(db, e, actor)


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: int, body: EmployeePatch, db: Session = Depends(get_db),
                    actor=Depends(require("hr:write"))):
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    data = body.model_dump(exclude_unset=True)
    _normalise_employee_location(db, data, e)
    _refuse_confidential_write(db, actor, data)
    if data.get("status") not in (None, "active", "inactive"):
        raise HTTPException(422, "status must be active or inactive")
    if data.get("manager_id"):
        if not db.get(Employee, data["manager_id"]):
            raise HTTPException(404, "Manager not found")
        if data["manager_id"] == employee_id:
            raise HTTPException(422, "An employee cannot report to themselves")
    changed = {}
    for k, v in data.items():
        if getattr(e, k) != v:
            old = getattr(e, k)
            changed[k] = {
                "old": hr_svc.mask_secret(old) if k in hr_svc.CONFIDENTIAL_EMPLOYEE_FIELDS
                else (str(old) if old is not None else None),
                "new": hr_svc.mask_secret(v) if k in hr_svc.CONFIDENTIAL_EMPLOYEE_FIELDS
                else (str(v) if v is not None else None)}
            setattr(e, k, v)
    if changed:
        audit(db, actor.id, "employee.update", f"employee:{e.id}",
              {"code": e.code, **changed})
    db.commit()
    return _employee_dict(db, e, actor)


@router.get("/employees/{employee_id}")
def get_employee(employee_id: int, db: Session = Depends(get_db),
                 user=Depends(require("hr:read"))):
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    scope = hr_svc.scoped_employee_ids(db, user)
    if scope is not None and e.id not in scope:
        raise HTTPException(403, "That employee is outside your team")
    return _employee_dict(db, e, user)


# ------------------------------------------------- profile: photo, documents, history
PHOTO_DIR = Path(__file__).resolve().parents[2] / "var" / "hr_photos"
PHOTO_TYPES = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
               "WEBP": ("webp", "image/webp")}


def _scoped_employee(db: Session, user, employee_id: int) -> Employee:
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    scope = hr_svc.scoped_employee_ids(db, user)
    if scope is not None and e.id not in scope:
        raise HTTPException(403, "That employee is outside your team")
    return e


def _may_edit_profile(db: Session, user, e: Employee) -> bool:
    me = hr_svc.employee_for_user(db, user)
    return _can(db, user, "hr:write") or bool(me and me.id == e.id)


@router.post("/employees/{employee_id}/photo")
async def upload_photo(employee_id: int, file: UploadFile = File(...),
                       db: Session = Depends(get_db), user=Depends(current_user)):
    """A profile photo, served only through this authenticated endpoint.

    Photos are personal data, so they are not written under the public /ui
    mount; the read route applies the same team scope as the profile.
    """
    e = _scoped_employee(db, user, employee_id)
    if not _may_edit_profile(db, user, e):
        raise HTTPException(403, "You may change only your own photo")
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise HTTPException(413, "The photo must be 2 MB or smaller")
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            fmt = image.format
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError,
            ValueError):
        # A file that is not an image, or one cut short mid-stream, must be a
        # clear refusal rather than an unhandled error.
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image")
    if fmt not in PHOTO_TYPES:
        raise HTTPException(422, "Upload a JPEG, PNG or WebP image")
    ext, _media = PHOTO_TYPES[fmt]
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    for old in PHOTO_DIR.glob(f"employee_{e.id}.*"):
        old.unlink(missing_ok=True)
    target = PHOTO_DIR / f"employee_{e.id}.{ext}"
    target.write_bytes(data)
    e.photo_path = f"hr_photos/{target.name}"
    audit(db, user.id, "hr.employee.photo", f"employee:{e.id}", {"format": fmt})
    db.commit()
    return {"employee_id": e.id, "has_photo": True, "url": f"/api/hr/employees/{e.id}/photo"}


@router.get("/employees/{employee_id}/photo")
def get_photo(employee_id: int, db: Session = Depends(get_db),
              user=Depends(require("hr:read"))):
    e = _scoped_employee(db, user, employee_id)
    if not e.photo_path:
        raise HTTPException(404, "No photo on file")
    path = PHOTO_DIR / Path(e.photo_path).name
    if not path.exists():
        raise HTTPException(404, "Photo file is missing")
    suffix = path.suffix.lower()
    media = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-store"})


@router.delete("/employees/{employee_id}/photo")
def delete_photo(employee_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    e = _scoped_employee(db, user, employee_id)
    if not _may_edit_profile(db, user, e):
        raise HTTPException(403, "You may change only your own photo")
    for old in PHOTO_DIR.glob(f"employee_{e.id}.*"):
        old.unlink(missing_ok=True)
    e.photo_path = None
    audit(db, user.id, "hr.employee.photo_delete", f"employee:{e.id}", {})
    db.commit()
    return {"employee_id": e.id, "has_photo": False}


class DocumentIn(BaseModel):
    doc_type: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=120)
    number: str | None = Field(default=None, max_length=60)
    issued_on: date | None = None
    expires_on: date | None = None
    file_path: str | None = Field(default=None, max_length=300)
    status: Literal["active", "expired", "replaced"] = "active"

    @model_validator(mode="after")
    def dates(self):
        if self.issued_on and self.expires_on and self.expires_on < self.issued_on:
            raise ValueError("expiry cannot be before the issue date")
        return self


def _document_dict(doc: EmployeeDocument, full: bool) -> dict:
    return {"id": doc.id, "employee_id": doc.employee_id, "doc_type": doc.doc_type,
            "title": doc.title,
            "number": doc.number if full else hr_svc.mask_secret(doc.number),
            "number_masked": (not full) and bool(doc.number),
            "issued_on": doc.issued_on, "expires_on": doc.expires_on,
            "status": doc.status, "has_file": bool(doc.file_path),
            "file_path": doc.file_path if full else None,
            "created_at": doc.created_at}


@router.get("/employees/{employee_id}/documents")
def list_documents(employee_id: int, db: Session = Depends(get_db),
                   user=Depends(require("hr:read"))):
    e = _scoped_employee(db, user, employee_id)
    full = hr_svc.may_view_confidential(db, user, e)
    rows = db.scalars(select(EmployeeDocument)
                      .where(EmployeeDocument.employee_id == e.id)
                      .order_by(EmployeeDocument.expires_on.desc().nullslast(),
                                EmployeeDocument.id.desc())).all()
    return [_document_dict(d, full) for d in rows]


@router.post("/employees/{employee_id}/documents", status_code=201)
def add_document(employee_id: int, body: DocumentIn, db: Session = Depends(get_db),
                 actor=Depends(require("hr:write"))):
    e = _scoped_employee(db, actor, employee_id)
    doc = EmployeeDocument(employee_id=e.id, uploaded_by=actor.id, **body.model_dump())
    db.add(doc)
    db.flush()
    audit(db, actor.id, "hr.document.add", f"document:{doc.id}",
          {"employee": e.code, "doc_type": doc.doc_type,
           "number": hr_svc.mask_secret(doc.number)})
    db.commit()
    return _document_dict(doc, full=True)


@router.patch("/employees/{employee_id}/documents/{document_id}")
def update_document(employee_id: int, document_id: int, body: DocumentIn,
                    db: Session = Depends(get_db), actor=Depends(require("hr:write"))):
    e = _scoped_employee(db, actor, employee_id)
    doc = db.get(EmployeeDocument, document_id)
    if not doc or doc.employee_id != e.id:
        raise HTTPException(404, "Document not found")
    for key, value in body.model_dump().items():
        setattr(doc, key, value)
    audit(db, actor.id, "hr.document.update", f"document:{doc.id}",
          {"employee": e.code, "doc_type": doc.doc_type,
           "number": hr_svc.mask_secret(doc.number)})
    db.commit()
    return _document_dict(doc, full=True)


class AssetIn(BaseModel):
    asset_type: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    serial_no: str | None = Field(default=None, max_length=80)
    issued_on: date
    condition_note: str | None = Field(default=None, max_length=200)


class AssetReturnIn(BaseModel):
    returned_on: date
    condition_note: str | None = Field(default=None, max_length=200)


def _asset_dict(a: EmployeeAsset) -> dict:
    return {"id": a.id, "employee_id": a.employee_id, "asset_type": a.asset_type,
            "name": a.name, "serial_no": a.serial_no, "issued_on": a.issued_on,
            "returned_on": a.returned_on, "condition_note": a.condition_note}


@router.get("/employees/{employee_id}/assets")
def list_assets(employee_id: int, db: Session = Depends(get_db),
                user=Depends(require("hr:read"))):
    e = _scoped_employee(db, user, employee_id)
    rows = db.scalars(select(EmployeeAsset).where(EmployeeAsset.employee_id == e.id)
                      .order_by(EmployeeAsset.issued_on.desc())).all()
    return [_asset_dict(a) for a in rows]


@router.post("/employees/{employee_id}/assets", status_code=201)
def issue_asset(employee_id: int, body: AssetIn, db: Session = Depends(get_db),
                actor=Depends(require("hr:write"))):
    e = _scoped_employee(db, actor, employee_id)
    asset = EmployeeAsset(employee_id=e.id, created_by=actor.id, **body.model_dump())
    db.add(asset)
    db.flush()
    audit(db, actor.id, "hr.asset.issue", f"asset:{asset.id}",
          {"employee": e.code, "name": asset.name, "serial_no": asset.serial_no})
    db.commit()
    return _asset_dict(asset)


@router.post("/assets/{asset_id}/return")
def return_asset(asset_id: int, body: AssetReturnIn, db: Session = Depends(get_db),
                 actor=Depends(require("hr:write"))):
    asset = db.get(EmployeeAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    _scoped_employee(db, actor, asset.employee_id)
    if asset.returned_on:
        raise HTTPException(409, "This asset is already returned")
    if body.returned_on < asset.issued_on:
        raise HTTPException(422, "The return date cannot be before the issue date")
    asset.returned_on = body.returned_on
    asset.condition_note = body.condition_note
    audit(db, actor.id, "hr.asset.return", f"asset:{asset.id}",
          {"employee_id": asset.employee_id, "returned_on": str(body.returned_on)})
    db.commit()
    return _asset_dict(asset)


@router.get("/employees/{employee_id}/profile")
def employee_profile(employee_id: int, db: Session = Depends(get_db),
                     user=Depends(require("hr:read"))):
    e = _scoped_employee(db, user, employee_id)
    full = hr_svc.may_view_confidential(db, user, e)
    documents = db.scalars(select(EmployeeDocument)
                           .where(EmployeeDocument.employee_id == e.id)
                           .order_by(EmployeeDocument.id.desc())).all()
    assets = db.scalars(select(EmployeeAsset)
                        .where(EmployeeAsset.employee_id == e.id)
                        .order_by(EmployeeAsset.issued_on.desc())).all()
    history = db.execute(
        select(AuditLog, User.username).join(User, User.id == AuditLog.actor_id, isouter=True)
        .where(AuditLog.record == f"employee:{e.id}")
        .order_by(AuditLog.id.desc()).limit(30)).all()
    return {
        "employee": _employee_dict(db, e, user),
        "documents": [_document_dict(d, full) for d in documents],
        "assets": [_asset_dict(a) for a in assets],
        "history": [{"at": log.at, "action": log.action, "actor": actor or "system",
                     "changes": log.changes or {}} for log, actor in history],
        "can_edit": _can(db, user, "hr:write"),
        "can_edit_confidential": full,
        "attendance_requirement": hr_svc.resolve_attendance_requirement(
            db, e, hr_svc.business_today()).as_dict(),
    }


@router.get("/employees/{employee_id}/history")
def employee_history(employee_id: int, db: Session = Depends(get_db),
                     user=Depends(require("hr:read"))):
    e = _scoped_employee(db, user, employee_id)
    rows = db.execute(
        select(AuditLog, User.username).join(User, User.id == AuditLog.actor_id, isouter=True)
        .where(AuditLog.record == f"employee:{e.id}")
        .order_by(AuditLog.id.desc()).limit(200)).all()
    return [{"at": log.at, "action": log.action, "actor": actor or "system",
             "changes": log.changes or {}} for log, actor in rows]


# --------------------------------------------------------------- config
class BranchIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    address: str | None = None
    hr_admin_id: int | None = None


class BranchPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    address: str | None = None
    hr_admin_id: int | None = None
    status: Literal["active", "inactive"] | None = None


class OfficeIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    branch_id: int | None = None
    address: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    geofence_radius_m: int | None = Field(default=200, gt=0, le=100000)
    attendance_mode: Literal["office", "gps", "both"] = "both"
    hr_admin_id: int | None = None

    @model_validator(mode="after")
    def both_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Give both the latitude and the longitude, or neither")
        return self


class OfficePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    branch_id: int | None = None
    address: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    geofence_radius_m: int | None = Field(default=None, gt=0, le=100000)
    attendance_mode: Literal["office", "gps", "both"] | None = None
    hr_admin_id: int | None = None
    status: Literal["active", "inactive"] | None = None


class AttendanceRuleIn(BaseModel):
    """Attendance requirements can target any mix of branch, office, role and person."""
    branch_id: int | None = None
    office_id: int | None = None
    designation: str | None = Field(default=None, max_length=80)
    employee_id: int | None = None
    required: bool = True
    self_service: bool = True
    shift_id: int | None = None
    attendance_mode: Literal["office", "gps", "both"] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    priority: int = Field(default=100, ge=1, le=1000)
    active: bool = True
    note: str | None = Field(default=None, max_length=200)

    @field_validator("designation")
    @classmethod
    def clean_designation(cls, value):
        return value.strip() or None if value else None

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.effective_from and self.effective_to \
                and self.effective_to < self.effective_from:
            raise ValueError("The end date cannot be before the start date")
        return self


class AttendanceRulePatch(BaseModel):
    branch_id: int | None = None
    office_id: int | None = None
    designation: str | None = Field(default=None, max_length=80)
    employee_id: int | None = None
    required: bool | None = None
    self_service: bool | None = None
    shift_id: int | None = None
    attendance_mode: Literal["office", "gps", "both"] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    active: bool | None = None
    note: str | None = Field(default=None, max_length=200)

    @field_validator("designation")
    @classmethod
    def clean_designation(cls, value):
        return value.strip() or None if value else None


def _normalise_weekly_offs(value):
    if value is None:
        return value
    if any(day < 0 or day > 6 for day in value):
        raise ValueError("weekly_offs must be weekday numbers 0 (Monday) to 6 (Sunday)")
    return sorted(set(value))


def _site_counts(db: Session) -> tuple[dict[int, int], dict[int, int]]:
    """Active employees per branch and per office, in two queries."""
    branch_counts = dict(db.execute(
        select(Employee.branch_id, func.count()).where(
            Employee.status == "active", Employee.branch_id.is_not(None))
        .group_by(Employee.branch_id)).all())
    office_counts = dict(db.execute(
        select(Employee.office_id, func.count()).where(
            Employee.status == "active", Employee.office_id.is_not(None))
        .group_by(Employee.office_id)).all())
    return branch_counts, office_counts


def _employee_names(db: Session) -> dict[int, str]:
    return {e.id: e.full_name for e in db.scalars(select(Employee)).all()}


def _branch_dict(b: Branch, counts: dict[int, int], names: dict[int, str]) -> dict:
    return {"id": b.id, "code": b.code, "name": b.name, "address": b.address,
            "hr_admin_id": b.hr_admin_id, "hr_admin": names.get(b.hr_admin_id),
            "active_employees": counts.get(b.id, 0), "status": b.status}


def _office_dict(o: WorkLocation, branches: dict[int, Branch], counts: dict[int, int],
                 names: dict[int, str]) -> dict:
    return {"id": o.id, "code": o.code, "name": o.name, "branch_id": o.branch_id,
            "branch": branches[o.branch_id].name if o.branch_id in branches else None,
            "address": o.address, "latitude": o.latitude, "longitude": o.longitude,
            "geofence_radius_m": o.geofence_radius_m, "attendance_mode": o.attendance_mode,
            "hr_admin_id": o.hr_admin_id, "hr_admin": names.get(o.hr_admin_id),
            "active_employees": counts.get(o.id, 0), "status": o.status}


def _require_site_admin(db: Session, hr_admin_id: int | None) -> None:
    if hr_admin_id is not None and not db.get(Employee, hr_admin_id):
        raise HTTPException(404, "The responsible employee was not found")


@router.get("/branches")
def list_branches(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    branch_counts, _ = _site_counts(db)
    names = _employee_names(db)
    return [_branch_dict(b, branch_counts, names) for b in
            db.scalars(select(Branch).order_by(Branch.code)).all()]


@router.post("/branches", status_code=201)
def create_branch(body: BranchIn, db: Session = Depends(get_db),
                  actor=Depends(require("hr:write"))):
    _require_site_admin(db, body.hr_admin_id)
    b = Branch(**body.model_dump())
    db.add(b)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Branch code exists")
    audit(db, actor.id, "hr.branch.create", f"branch:{b.id}",
          {"code": b.code, "hr_admin_id": b.hr_admin_id})
    db.commit()
    branch_counts, _ = _site_counts(db)
    return _branch_dict(b, branch_counts, _employee_names(db))


@router.patch("/branches/{branch_id}")
def update_branch(branch_id: int, body: BranchPatch, db: Session = Depends(get_db),
                  actor=Depends(require("hr:write"))):
    """Edit a branch, including the person responsible for HR there.

    A branch with active staff cannot be switched off until those people are
    reassigned; deactivating it would otherwise hide live attendance policy.
    """
    b = db.get(Branch, branch_id)
    if not b:
        raise HTTPException(404, "Branch not found")
    data = body.model_dump(exclude_unset=True)
    _require_site_admin(db, data.get("hr_admin_id"))
    if data.get("status") == "inactive":
        used = db.scalar(select(func.count()).select_from(Employee).where(
            Employee.branch_id == b.id, Employee.status == "active")) or 0
        if used:
            raise HTTPException(409, f"{used} active employee(s) are assigned to this branch. "
                                     "Reassign them before deactivating it.")
    changed = {}
    for key, value in data.items():
        old = getattr(b, key)
        if old != value:
            changed[key] = {"old": str(old) if old is not None else None,
                            "new": str(value) if value is not None else None}
            setattr(b, key, value)
    if changed:
        audit(db, actor.id, "hr.branch.update", f"branch:{b.id}", {"code": b.code, **changed})
        db.commit()
    branch_counts, _ = _site_counts(db)
    return _branch_dict(b, branch_counts, _employee_names(db))


@router.get("/offices")
def list_offices(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    _, office_counts = _site_counts(db)
    branches = {b.id: b for b in db.scalars(select(Branch)).all()}
    names = _employee_names(db)
    return [_office_dict(o, branches, office_counts, names) for o in
            db.scalars(select(WorkLocation).order_by(WorkLocation.code)).all()]


@router.post("/offices", status_code=201)
def create_office(body: OfficeIn, db: Session = Depends(get_db),
                  actor=Depends(require("hr:write"))):
    if body.branch_id is not None and not db.get(Branch, body.branch_id):
        raise HTTPException(404, "Branch not found")
    _require_site_admin(db, body.hr_admin_id)
    o = WorkLocation(**body.model_dump())
    db.add(o)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Office code exists")
    audit(db, actor.id, "hr.office.create", f"office:{o.id}",
          {"code": o.code, "branch_id": o.branch_id, "latitude": str(o.latitude),
           "longitude": str(o.longitude), "radius": o.geofence_radius_m,
           "mode": o.attendance_mode, "hr_admin_id": o.hr_admin_id})
    db.commit()
    branches = {b.id: b for b in db.scalars(select(Branch)).all()}
    _, office_counts = _site_counts(db)
    return _office_dict(o, branches, office_counts, _employee_names(db))


@router.patch("/offices/{office_id}")
def update_office(office_id: int, body: OfficePatch, db: Session = Depends(get_db),
                  actor=Depends(require("hr:write"))):
    """Edit an office, its geofence and its attendance mode.

    Changing the branch, or switching the office off, is refused while active
    employees still point at it: those people must be reassigned first.
    """
    o = db.get(WorkLocation, office_id)
    if not o:
        raise HTTPException(404, "Office not found")
    data = body.model_dump(exclude_unset=True)
    if "branch_id" in data and data["branch_id"] is not None \
            and not db.get(Branch, data["branch_id"]):
        raise HTTPException(404, "Branch not found")
    _require_site_admin(db, data.get("hr_admin_id"))
    lat = data.get("latitude", o.latitude)
    lon = data.get("longitude", o.longitude)
    if (lat is None) != (lon is None):
        raise HTTPException(422, "Give both the latitude and the longitude, or neither")
    used = db.scalar(select(func.count()).select_from(Employee).where(
        Employee.office_id == o.id, Employee.status == "active")) or 0
    if "branch_id" in data and data["branch_id"] != o.branch_id and used:
        raise HTTPException(409, f"{used} active employee(s) work at this office. Reassign "
                                 "them before moving it to another branch.")
    if data.get("status") == "inactive" and used:
        raise HTTPException(409, f"{used} active employee(s) work at this office. Reassign "
                                 "them before deactivating it.")
    changed = {}
    for key, value in data.items():
        old = getattr(o, key)
        if old != value:
            def shown(v):
                return str(v) if v is not None else None
            changed[key] = {"old": shown(old), "new": shown(value)}
            setattr(o, key, value)
    if changed:
        try:
            db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, "Office code exists")
        audit(db, actor.id, "hr.office.update", f"office:{o.id}", {"code": o.code, **changed})
        db.commit()
    branches = {b.id: b for b in db.scalars(select(Branch)).all()}
    _, office_counts = _site_counts(db)
    return _office_dict(o, branches, office_counts, _employee_names(db))


# ----------------------------------------------------- attendance requirements
RULE_TARGET_FIELDS = ("branch_id", "office_id", "designation", "employee_id")


def _rule_value(data: dict, current: AttendanceRule | None, key: str):
    return data[key] if key in data else getattr(current, key, None)


def _validate_rule_targets(db: Session, data: dict, current: AttendanceRule | None = None) -> None:
    """Refuse a rule that points at a site or person it could never match."""
    def value(key):
        return _rule_value(data, current, key)

    branch_id, office_id = value("branch_id"), value("office_id")
    employee_id = value("employee_id")
    branch = db.get(Branch, branch_id) if branch_id else None
    if branch_id and not branch:
        raise HTTPException(404, "Branch not found")
    office = db.get(WorkLocation, office_id) if office_id else None
    if office_id and not office:
        raise HTTPException(404, "Office not found")
    if branch and office and office.branch_id and office.branch_id != branch.id:
        raise HTTPException(422, "That office belongs to a different branch")
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee_id and not employee:
        raise HTTPException(404, "Employee not found")
    shift_id = value("shift_id")
    if shift_id and not db.get(Shift, shift_id):
        raise HTTPException(404, "Shift not found")
    if employee and office_id and employee.office_id and employee.office_id != office_id:
        raise HTTPException(422, "That employee is not assigned to this office, so the rule "
                                 "would never match")
    if employee and branch_id and employee.branch_id and employee.branch_id != branch_id:
        raise HTTPException(422, "That employee is not assigned to this branch, so the rule "
                                 "would never match")
    first, last = value("effective_from"), value("effective_to")
    if first and last and last < first:
        raise HTTPException(422, "The end date cannot be before the start date")
    if value("active"):
        for other in db.scalars(select(AttendanceRule)
                                .where(AttendanceRule.active.is_(True))).all():
            if current is not None and other.id == current.id:
                continue
            same_targets = all(
                (getattr(other, key) or None) == (value(key) or None)
                for key in RULE_TARGET_FIELDS)
            if same_targets:
                if not any(value(key) for key in RULE_TARGET_FIELDS):
                    raise HTTPException(409, "An active company-wide rule already exists; "
                                             "edit that rule instead")
                raise HTTPException(409, f"Rule #{other.id} already targets exactly these "
                                         "employees; edit it instead")


def _rule_dict(rule: AttendanceRule, branches: dict | None = None,
               offices: dict | None = None, shifts: dict | None = None,
               employees: dict | None = None) -> dict:
    branches = branches or {}
    offices = offices or {}
    shifts = shifts or {}
    employees = employees or {}
    return {"id": rule.id, "branch_id": rule.branch_id,
            "branch": branches[rule.branch_id].name if rule.branch_id in branches else None,
            "office_id": rule.office_id,
            "office": offices[rule.office_id].name if rule.office_id in offices else None,
            "designation": rule.designation, "employee_id": rule.employee_id,
            "employee": employees.get(rule.employee_id), "required": rule.required,
            "self_service": rule.self_service, "shift_id": rule.shift_id,
            "shift": shifts[rule.shift_id].name if rule.shift_id in shifts else None,
            "attendance_mode": rule.attendance_mode,
            "effective_from": rule.effective_from, "effective_to": rule.effective_to,
            "priority": rule.priority, "active": rule.active, "note": rule.note,
            "source": hr_svc.rule_label(rule)}


def _rule_dicts(db: Session, rules: list[AttendanceRule]) -> list[dict]:
    branches = {b.id: b for b in db.scalars(select(Branch)).all()}
    offices = {o.id: o for o in db.scalars(select(WorkLocation)).all()}
    shifts = {s.id: s for s in db.scalars(select(Shift)).all()}
    employees = _employee_names(db)
    return [_rule_dict(r, branches, offices, shifts, employees) for r in rules]


@router.get("/attendance-rules")
def list_attendance_rules(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    rules = db.scalars(select(AttendanceRule)
                       .order_by(AttendanceRule.priority, AttendanceRule.id)).all()
    return _rule_dicts(db, list(rules))


@router.get("/attendance-rules/resolve")
def resolve_attendance_rule(employee_id: int | None = None, day: date | None = None,
                            db: Session = Depends(get_db), user=Depends(current_user)):
    """The policy that applies to an employee today, and where it came from."""
    _require_hr_view(db, user)
    if employee_id:
        employee = _scoped_employee(db, user, employee_id)
    else:
        employee = hr_svc.employee_for_user(db, user)
        if not employee:
            raise HTTPException(404, "No employee record is linked to this login")
    when = day or hr_svc.business_today()
    req = hr_svc.resolve_attendance_requirement(db, employee, when)
    office = db.get(WorkLocation, employee.office_id) if employee.office_id else None
    shift = db.get(Shift, req.shift_id) if req.shift_id else None
    return {"employee_id": employee.id, "employee": employee.full_name, "date": when,
            "office_id": employee.office_id, "office": office.name if office else None,
            "branch_id": employee.branch_id, "shift": shift.name if shift else None,
            **req.as_dict()}


@router.post("/attendance-rules", status_code=201)
def create_attendance_rule(body: AttendanceRuleIn, db: Session = Depends(get_db),
                           actor=Depends(require("hr:write"))):
    data = body.model_dump()
    _validate_rule_targets(db, data)
    rule = AttendanceRule(**data, created_by=actor.id)
    db.add(rule)
    db.flush()
    audit(db, actor.id, "hr.attendance_rule.create", f"attendance_rule:{rule.id}",
          {"targets": {k: data.get(k) for k in RULE_TARGET_FIELDS},
           "required": rule.required, "self_service": rule.self_service})
    db.commit()
    return _rule_dicts(db, [rule])[0]


@router.patch("/attendance-rules/{rule_id}")
def update_attendance_rule(rule_id: int, body: AttendanceRulePatch,
                           db: Session = Depends(get_db),
                           actor=Depends(require("hr:write"))):
    rule = db.get(AttendanceRule, rule_id)
    if not rule:
        raise HTTPException(404, "Attendance rule not found")
    data = body.model_dump(exclude_unset=True)
    _validate_rule_targets(db, data, rule)
    changed = {}
    for key, value in data.items():
        old = getattr(rule, key)
        if old != value:
            changed[key] = {"old": str(old) if old is not None else None,
                            "new": str(value) if value is not None else None}
            setattr(rule, key, value)
    if changed:
        audit(db, actor.id, "hr.attendance_rule.update", f"attendance_rule:{rule.id}", changed)
        db.commit()
    return _rule_dicts(db, [rule])[0]


@router.delete("/attendance-rules/{rule_id}", status_code=204)
def delete_attendance_rule(rule_id: int, db: Session = Depends(get_db),
                           actor=Depends(require("hr:write"))):
    rule = db.get(AttendanceRule, rule_id)
    if not rule:
        raise HTTPException(404, "Attendance rule not found")
    audit(db, actor.id, "hr.attendance_rule.delete", f"attendance_rule:{rule.id}",
          {"targets": {k: getattr(rule, k) for k in RULE_TARGET_FIELDS},
           "note": rule.note})
    db.delete(rule)
    db.commit()
    return Response(status_code=204)


class ShiftIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    start_time: time = time(9, 0)
    end_time: time = time(18, 0)
    grace_minutes: int = Field(default=10, ge=0, le=120)
    full_day_hours: Decimal = Field(default=Decimal("8"), gt=0)
    half_day_hours: Decimal = Field(default=Decimal("4"), gt=0)
    weekly_offs: list[int] = Field(default_factory=lambda: [5, 6])
    status: Literal["active", "inactive"] = "active"

    @field_validator("weekly_offs")
    @classmethod
    def valid_weekly_offs(cls, value):
        return _normalise_weekly_offs(value)

    @model_validator(mode="after")
    def valid_times(self):
        if self.start_time == self.end_time:
            raise ValueError("A shift must have different start and end times")
        return self


class ShiftPatch(BaseModel):
    """Editable shift policy. Omitted fields keep their current value."""
    name: str | None = Field(default=None, min_length=2, max_length=80)
    start_time: time | None = None
    end_time: time | None = None
    grace_minutes: int | None = Field(default=None, ge=0, le=120)
    full_day_hours: Decimal | None = Field(default=None, gt=0, le=24)
    half_day_hours: Decimal | None = Field(default=None, gt=0, le=24)
    weekly_offs: list[int] | None = None
    status: Literal["active", "inactive"] | None = None

    @field_validator("weekly_offs")
    @classmethod
    def valid_weekly_offs(cls, value):
        return _normalise_weekly_offs(value)


class HolidayIn(BaseModel):
    date: date
    name: str
    branch_id: int | None = None
    location_id: int | None = None


class HolidayPatch(BaseModel):
    """Send only what changes. An explicit null clears the branch or office."""
    # The field is named date, which shadows the type in this class body, so the
    # annotation uses the alias.
    date: date_cls | None = None
    name: str | None = Field(default=None, min_length=2, max_length=120)
    branch_id: int | None = None
    location_id: int | None = None


class DepartmentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    status: Literal["active", "inactive"] | None = None


def _shift_dict(s: Shift) -> dict:
    return {"id": s.id, "name": s.name,
            "start_time": s.start_time.strftime("%H:%M"),
            "end_time": s.end_time.strftime("%H:%M"),
            "grace_minutes": s.grace_minutes, "full_day_hours": s.full_day_hours,
            "half_day_hours": s.half_day_hours, "weekly_offs": s.weekly_offs,
            "status": s.status}


@router.get("/shifts")
def list_shifts(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    return [_shift_dict(s) for s in db.scalars(select(Shift).order_by(Shift.name)).all()]


@router.post("/shifts", status_code=201)
def create_shift(body: ShiftIn, db: Session = Depends(get_db),
                 actor=Depends(require("hr:write"))):
    s = Shift(**body.model_dump())
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Shift name exists")
    audit(db, actor.id, "hr.shift.create", f"shift:{s.id}", {"name": s.name})
    db.commit()
    return {"id": s.id, "name": s.name}


@router.patch("/shifts/{shift_id}")
def update_shift(shift_id: int, body: ShiftPatch, db: Session = Depends(get_db),
                 actor=Depends(require("hr:write"))):
    """Edit office timings, grace and weekly offs. Existing attendance keeps the
    late/early minutes it was recorded with; future check-ins use the new policy."""
    s = db.get(Shift, shift_id)
    if not s:
        raise HTTPException(404, "Shift not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("start_time", s.start_time) == data.get("end_time", s.end_time):
        raise HTTPException(422, "A shift must have different start and end times")
    changed: dict[str, dict] = {}
    for key, value in data.items():
        old = getattr(s, key)
        if old != value:
            def shown(v):
                if v is None:
                    return None
                return v.strftime("%H:%M") if isinstance(v, time) else str(v)
            changed[key] = {"old": shown(old), "new": shown(value)}
            setattr(s, key, value)
    if changed:
        try:
            db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, "Shift name exists")
        audit(db, actor.id, "hr.shift.update", f"shift:{s.id}", {"name": s.name, **changed})
        db.commit()
    return _shift_dict(s)


@router.get("/holidays")
def list_holidays(year: int | None = None, db: Session = Depends(get_db),
                  _=Depends(require("hr:read"))):
    stmt = select(Holiday)
    if year:
        stmt = stmt.where(Holiday.date >= date(year, 1, 1), Holiday.date <= date(year, 12, 31))
    return [{"id": h.id, "date": h.date, "name": h.name, "branch_id": h.branch_id,
             "location_id": h.location_id} for h in db.scalars(stmt.order_by(Holiday.date)).all()]


def _check_holiday_scope(db: Session, branch_id: int | None,
                         location_id: int | None) -> None:
    if branch_id is not None and not db.get(Branch, branch_id):
        raise HTTPException(404, "Branch not found")
    if location_id is not None:
        office = db.get(WorkLocation, location_id)
        if not office:
            raise HTTPException(404, "Office not found")
        if branch_id is not None and office.branch_id is not None \
                and office.branch_id != branch_id:
            raise HTTPException(422, "That office belongs to a different branch")


def _holiday_dict(h: Holiday) -> dict:
    return {"id": h.id, "date": h.date, "name": h.name,
            "branch_id": h.branch_id, "location_id": h.location_id}


@router.post("/holidays", status_code=201)
def create_holiday(body: HolidayIn, db: Session = Depends(get_db),
                   actor=Depends(require("hr:write"))):
    _check_holiday_scope(db, body.branch_id, body.location_id)
    h = Holiday(**body.model_dump())
    db.add(h)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Holiday already exists")
    audit(db, actor.id, "hr.holiday.create", f"holiday:{h.id}",
          {"date": str(h.date), "name": h.name})
    db.commit()
    return _holiday_dict(h)


@router.patch("/holidays/{holiday_id}")
def update_holiday(holiday_id: int, body: HolidayPatch, db: Session = Depends(get_db),
                   actor=Depends(require("hr:write"))):
    """Correct a holiday. Attendance already marked keeps the status it was
    recorded with; a new date applies to future marking only."""
    h = db.get(Holiday, holiday_id)
    if not h:
        raise HTTPException(404, "Holiday not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "No changes were supplied")
    if data.get("date", h.date) is None or data.get("name", h.name) is None:
        raise HTTPException(422, "A holiday needs a date and a name")
    branch_id = data["branch_id"] if "branch_id" in data else h.branch_id
    location_id = data["location_id"] if "location_id" in data else h.location_id
    _check_holiday_scope(db, branch_id, location_id)
    changes = {}
    for key, value in data.items():
        old = getattr(h, key)
        if old != value:
            changes[key] = {"old": str(old) if old is not None else None,
                            "new": str(value) if value is not None else None}
            setattr(h, key, value)
    if changes:
        try:
            db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, "Holiday already exists")
        audit(db, actor.id, "hr.holiday.update", f"holiday:{h.id}",
              {"name": h.name, **changes})
        db.commit()
    return _holiday_dict(h)


@router.get("/departments")
def list_departments(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    return [{"id": d.id, "code": d.code, "name": d.name, "status": d.status}
            for d in db.scalars(select(Department).order_by(Department.name)).all()]


@router.post("/departments", status_code=201)
def create_department(body: BranchIn, db: Session = Depends(get_db),
                      actor=Depends(require("hr:write"))):
    d = Department(code=body.code.upper(), name=body.name)
    db.add(d)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Department already exists")
    audit(db, actor.id, "hr.department.create", f"department:{d.id}", {"name": d.name})
    db.commit()
    return {"id": d.id, "code": d.code, "name": d.name}


@router.patch("/departments/{department_id}")
def update_department(department_id: int, body: DepartmentPatch, db: Session = Depends(get_db),
                      actor=Depends(require("hr:write"))):
    """Rename or retire a department. The code is permanent.

    Employees linked by department_id show the new name in the directory; the
    denormalised name on those rows is updated with the master, never inferred
    for anyone else.
    """
    d = db.get(Department, department_id)
    if not d:
        raise HTTPException(404, "Department not found")
    data = body.model_dump(exclude_unset=True)
    if not data or all(v is None for v in data.values()):
        raise HTTPException(422, "No changes were supplied")
    changes: dict = {}
    if data.get("name") is not None and data["name"] != d.name:
        if db.scalar(select(Department).where(Department.name == data["name"],
                                              Department.id != d.id)):
            raise HTTPException(409, "Department name exists")
        changes["name"] = {"old": d.name, "new": data["name"]}
        d.name = data["name"]
        linked = db.scalars(select(Employee).where(
            Employee.department_id == d.id)).all()
        for emp in linked:
            emp.department = d.name
        changes["employees_renamed"] = len(linked)
    if data.get("status") is not None and data["status"] != d.status:
        changes["status"] = {"old": d.status, "new": data["status"]}
        d.status = data["status"]
    if changes:
        try:
            db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, "Department name exists")
        audit(db, actor.id, "hr.department.update", f"department:{d.id}",
              {"code": d.code, **changes})
        db.commit()
    return {"id": d.id, "code": d.code, "name": d.name, "status": d.status}


# --------------------------------------------------------------- attendance
class CheckInIn(BaseModel):
    office_id: int | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    source: Literal["web", "office", "gps", "manual"] = "web"
    remarks: str | None = Field(default=None, max_length=300)


class CheckOutIn(BaseModel):
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    remarks: str | None = None


class ManualAttendanceIn(BaseModel):
    employee_id: int
    date: date
    status: Literal["present", "absent", "half_day", "weekly_off", "holiday", "paid_leave",
                    "unpaid_leave", "od", "late", "early_departure"]
    check_in: datetime | None = None
    check_out: datetime | None = None
    office_id: int | None = None
    overtime_minutes: int = Field(default=0, ge=0, le=1440)
    remarks: str = Field(min_length=3, max_length=300)
    override_reason: str | None = Field(default=None, min_length=5, max_length=300)


class CorrectionIn(BaseModel):
    new_status: str | None = None
    new_check_in: datetime | None = None
    new_check_out: datetime | None = None
    reason: str = Field(min_length=3, max_length=300)


ATTENDANCE_STATUSES = ("present", "absent", "half_day", "weekly_off", "holiday",
                       "paid_leave", "unpaid_leave", "od", "late", "early_departure")


class BulkAttendanceIn(BaseModel):
    employee_ids: list[int] = Field(min_length=1, max_length=500)
    date_from: date
    date_to: date
    status: Literal[*ATTENDANCE_STATUSES]
    remarks: str = Field(min_length=3, max_length=300)
    overtime_minutes: int = Field(default=0, ge=0, le=1440)
    skip_non_working: bool = True
    override_reason: str | None = Field(default=None, min_length=5, max_length=300)

    @model_validator(mode="after")
    def check_range(self):
        if self.date_to < self.date_from:
            raise ValueError("date_to cannot be before date_from")
        days = (self.date_to - self.date_from).days + 1
        if days > 62:
            raise ValueError("Mark at most 62 days in one operation")
        if len(set(self.employee_ids)) * days > 5000:
            raise ValueError("At most 5000 employee-days per operation; narrow the range")
        if len(set(self.employee_ids)) != len(self.employee_ids):
            raise ValueError("employee_ids contains duplicates")
        return self


class PeriodLockIn(BaseModel):
    scope: Literal["attendance", "payroll"]
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    reason: str = Field(min_length=5, max_length=300)


class PeriodUnlockIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


def _period_lock_dict(lock: PeriodLock, users: dict[int, User]) -> dict:
    def who(user_id):
        u = users.get(user_id) if user_id else None
        return u.username if u else (str(user_id) if user_id else None)

    return {"id": lock.id, "scope": lock.scope, "year": lock.year, "month": lock.month,
            "active": lock.active, "reason": lock.reason,
            "locked_by": who(lock.locked_by), "locked_at": lock.locked_at,
            "unlocked_by": who(lock.unlocked_by), "unlocked_at": lock.unlocked_at,
            "unlock_reason": lock.unlock_reason}


@router.get("/period-locks")
def list_period_locks(scope: str | None = None, year: int | None = None,
                      db: Session = Depends(get_db), user=Depends(require("hr:read"))):
    stmt = select(PeriodLock)
    if scope:
        stmt = stmt.where(PeriodLock.scope == scope)
    if year:
        stmt = stmt.where(PeriodLock.year == year)
    locks = db.scalars(stmt.order_by(PeriodLock.year.desc(), PeriodLock.month.desc())).all()
    # Payroll lock metadata is part of the payroll record, so it follows the
    # payroll rights rather than general HR read access.
    if not _can(db, user, "hr:payroll_prepare", "hr:payroll_approve", "hr:confidential"):
        locks = [l for l in locks if l.scope != "payroll"]
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return [_period_lock_dict(l, users) for l in locks]


@router.post("/period-locks", status_code=201)
def lock_period(body: PeriodLockIn, db: Session = Depends(get_db),
                user=Depends(current_user)):
    perm = "hr:write" if body.scope == "attendance" else "hr:payroll_prepare"
    if not _can(db, user, perm):
        raise HTTPException(403, f"Your role cannot lock a {body.scope} period")
    lock = db.scalar(select(PeriodLock).where(
        PeriodLock.scope == body.scope, PeriodLock.year == body.year,
        PeriodLock.month == body.month).with_for_update())
    if lock and lock.active:
        raise HTTPException(409, f"That {body.scope} month is already locked")
    reason = body.reason.strip()
    if lock:
        lock.active = True
        lock.locked_by = user.id
        lock.locked_at = datetime.now(timezone.utc)
        lock.reason = reason
        lock.unlocked_by = lock.unlocked_at = lock.unlock_reason = None
    else:
        lock = PeriodLock(scope=body.scope, year=body.year, month=body.month,
                          active=True, locked_by=user.id, reason=reason)
        db.add(lock)
    db.flush()
    audit(db, user.id, "hr.period_lock.lock", f"period_lock:{lock.id}",
          {"scope": lock.scope, "year": lock.year, "month": lock.month, "reason": reason})
    db.commit()
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return _period_lock_dict(lock, users)


@router.post("/period-locks/{lock_id}/unlock")
def unlock_period(lock_id: int, body: PeriodUnlockIn, db: Session = Depends(get_db),
                  user=Depends(current_user)):
    if not is_admin(db, user):
        raise HTTPException(403, "Only the Administrator may unlock a period")
    lock = db.scalars(select(PeriodLock).where(PeriodLock.id == lock_id)
                      .with_for_update()).first()
    if not lock:
        raise HTTPException(404, "Period lock not found")
    if not lock.active:
        raise HTTPException(409, "That period is not locked")
    lock.active = False
    lock.unlocked_by = user.id
    lock.unlocked_at = datetime.now(timezone.utc)
    lock.unlock_reason = body.reason.strip()
    audit(db, user.id, "hr.period_lock.unlock", f"period_lock:{lock.id}",
          {"scope": lock.scope, "year": lock.year, "month": lock.month,
           "reason": lock.unlock_reason})
    db.commit()
    users = {u.id: u for u in db.scalars(select(User)).all()}
    return _period_lock_dict(lock, users)


@router.get("/attendance")
def list_attendance(from_date: date | None = None, to_date: date | None = None,
                    employee_id: int | None = None, status: str | None = None,
                    department: str | None = None, branch_id: int | None = None,
                    office_id: int | None = None, db: Session = Depends(get_db),
                    user=Depends(current_user)):
    # Team attendance needs a manager/HR right; a staff member sees only their
    # own days, and a manager only their reporting chain.
    perms = _perms(db, user)
    if not is_admin(db, user) and "hr:read" not in perms \
            and "hr:attendance_self" not in perms:
        raise HTTPException(403, "Your role cannot view attendance")
    scope = hr_svc.scoped_employee_ids(db, user)
    stmt = select(Attendance)
    if scope is not None:
        if employee_id and employee_id not in scope:
            raise HTTPException(403, "That employee is outside your team")
        stmt = stmt.where(Attendance.employee_id.in_(scope or {-1}))
    elif employee_id:
        stmt = stmt.where(Attendance.employee_id == employee_id)
    if from_date:
        stmt = stmt.where(Attendance.date >= from_date)
    if to_date:
        stmt = stmt.where(Attendance.date <= to_date)
    if status:
        stmt = stmt.where(Attendance.status == status)
    rows = db.scalars(stmt.order_by(Attendance.date.desc(), Attendance.employee_id)).all()
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    if department:
        rows = [r for r in rows if emps.get(r.employee_id) and
                emps[r.employee_id].department == department]
    if branch_id:
        rows = [r for r in rows if emps.get(r.employee_id) and
                emps[r.employee_id].branch_id == branch_id]
    if office_id:
        rows = [r for r in rows if emps.get(r.employee_id) and
                emps[r.employee_id].office_id == office_id]
    return [{"id": r.id, "employee_id": r.employee_id,
             "employee": emps[r.employee_id].full_name if r.employee_id in emps else "?",
             "employee_code": emps[r.employee_id].code if r.employee_id in emps else "",
             "branch_id": emps[r.employee_id].branch_id if r.employee_id in emps else None,
             "employee_office_id": emps[r.employee_id].office_id
             if r.employee_id in emps else None,
             "date": r.date, "status": r.status, "check_in": r.check_in, "check_out": r.check_out,
             "office_id": r.office_id, "source": r.source, "geofence_result": r.geofence_result,
             "late_minutes": r.late_minutes, "early_minutes": r.early_minutes,
             "worked_minutes": r.worked_minutes, "overtime_minutes": r.overtime_minutes,
             "leave_portion": r.leave_portion, "remarks": r.remarks} for r in rows]


@router.get("/attendance/monthly")
def monthly_attendance(year: int, month: int, employee_id: int | None = None,
                       department: str | None = None, branch_id: int | None = None,
                       office_id: int | None = None, db: Session = Depends(get_db),
                       user=Depends(current_user)):
    """One month of statuses per employee, plus the counts the calendar needs.

    Days with no attendance row are returned with a null status and no numbers:
    an unrecorded day is a gap, never an assumed absence. A day the policy
    exempts is marked as not required instead.
    """
    return hr_svc.monthly_attendance(db, user, year=year, month=month,
                                     employee_id=employee_id, department=department,
                                     branch_id=branch_id, office_id=office_id)


@router.post("/attendance/bulk")
def bulk_attendance(body: BulkAttendanceIn, db: Session = Depends(get_db),
                    user=Depends(require("hr:attendance_manage"))):
    """Mark one status across employees and days in a single audited action."""
    scope = hr_svc.scoped_employee_ids(db, user)
    ids = set(body.employee_ids)
    if scope is not None:
        outside = ids - scope
        if outside:
            raise HTTPException(403, f"{len(outside)} selected employee(s) are outside "
                                     "your team")
    employees = db.scalars(select(Employee).where(Employee.id.in_(ids))).all()
    if len(employees) != len(ids):
        missing = sorted(ids - {e.id for e in employees})
        raise HTTPException(404, f"Employee(s) not found: {missing}")
    rules = list(db.scalars(select(AttendanceRule)
                            .where(AttendanceRule.active.is_(True))).all())
    exempt = [e for e in employees
              if not hr_svc.resolve_attendance_requirement(db, e, body.date_from,
                                                           rules).required]
    if exempt:
        shown = ", ".join(f"{e.code} {e.full_name}" for e in exempt[:5])
        raise HTTPException(409, f"Attendance is not required for {len(exempt)} selected "
                                 f"employee(s): {shown}. Remove them from this action.")
    _assert_range_open(db, "attendance", body.date_from, body.date_to, user,
                       body.override_reason, action="bulk attendance")
    existing = {(r.employee_id, r.date): r for r in db.scalars(select(Attendance).where(
        Attendance.employee_id.in_(ids), Attendance.date >= body.date_from,
        Attendance.date <= body.date_to)).all()}
    created = updated = skipped = 0
    for emp in employees:
        offs = hr_svc.weekly_off_days(db, emp)
        holidays = hr_svc.holidays_for(db, emp, body.date_from, body.date_to)
        day = body.date_from
        while day <= body.date_to:
            if body.skip_non_working and not hr_svc.is_working_day(emp, offs, holidays, day):
                skipped += 1
                day += timedelta(days=1)
                continue
            row = existing.get((emp.id, day))
            if row is None:
                row = Attendance(employee_id=emp.id, date=day)
                db.add(row)
                created += 1
            else:
                updated += 1
            row.status = body.status
            row.source = "manual"
            row.geofence_result = "manual"
            row.remarks = body.remarks
            row.overtime_minutes = body.overtime_minutes
            row.approved_by = user.id
            day += timedelta(days=1)
    db.flush()
    audit(db, user.id, "hr.attendance.bulk", "attendance:bulk",
          {"employees": len(employees), "from": str(body.date_from),
           "to": str(body.date_to), "status": body.status, "created": created,
           "updated": updated, "skipped": skipped,
           "overtime_minutes": body.overtime_minutes,
           "override_reason": body.override_reason})
    db.commit()
    return {"employees": len(employees), "status": body.status, "created": created,
            "updated": updated, "skipped": skipped}


@router.post("/attendance/check-in", status_code=201)
def check_in(body: CheckInIn, db: Session = Depends(get_db),
             user=Depends(require("hr:attendance_self"))):
    emp = _self_employee(db, user)
    today = hr_svc.business_today()
    req = hr_svc.require_self_service(db, emp, today)
    _assert_period_open(db, "attendance", today, user, action="check-in")
    existing = db.scalar(select(Attendance).where(Attendance.employee_id == emp.id,
                                                  Attendance.date == today))
    if existing:
        raise HTTPException(409, "Attendance for today has already been recorded")
    if (req.attendance_mode or "office") == "gps" \
            and (body.latitude is None or body.longitude is None):
        raise HTTPException(422, "This work location requires GPS coordinates for check-in.")
    office = db.get(WorkLocation, body.office_id or emp.office_id) if (body.office_id or emp.office_id) else None
    if office and office.status != "active":
        raise HTTPException(409, "That office is not active")
    result = hr_svc.geofence_result(office, body.latitude, body.longitude)
    if result == "outside" and not (body.remarks and len(body.remarks.strip()) >= 3):
        raise HTTPException(409, "You are outside the permitted geofence. Give a reason for the "
                                 "exception; it will need approval.")
    now = datetime.now(timezone.utc)
    shift = hr_svc.requirement_shift(db, req)
    late = hr_svc.shift_late_minutes(shift, now)
    row = Attendance(employee_id=emp.id, date=today, status="present", check_in=now,
                     office_id=office.id if office else None, source=body.source,
                     latitude=body.latitude, longitude=body.longitude,
                     geofence_result=result, late_minutes=late, remarks=body.remarks)
    db.add(row)
    db.flush()
    if result == "outside":
        hr_svc.request_approval(db, record_type="hr_geofence_exception", record_id=row.id,
                                requested_by=user.id, reasons=["geofence"],
                                detail={"attendance_id": row.id, "employee_id": emp.id,
                                        "remarks": body.remarks},
                                document_number=f"ATT-{today:%Y%m%d}-{emp.code}",
                                subject=f"Location exception for {emp.full_name}",
                                requested_dates=str(today), approver_role="hr_manager")
    audit(db, user.id, "hr.attendance.check_in", f"attendance:{row.id}",
          {"employee": emp.code, "geofence": result, "late_minutes": late,
           "source": body.source})
    db.commit()
    return {"id": row.id, "date": row.date, "status": row.status, "check_in": row.check_in,
            "geofence_result": row.geofence_result, "late_minutes": row.late_minutes}


@router.post("/attendance/check-out")
def check_out(body: CheckOutIn, db: Session = Depends(get_db),
              user=Depends(require("hr:attendance_self"))):
    emp = _self_employee(db, user)
    today = hr_svc.business_today()
    req = hr_svc.require_self_service(db, emp, today)
    _assert_period_open(db, "attendance", today, user, action="check-out")
    row = db.scalar(select(Attendance).where(Attendance.employee_id == emp.id,
                                             Attendance.date == today).with_for_update())
    if not row or not row.check_in:
        raise HTTPException(409, "No check-in has been recorded for today")
    if row.check_out:
        raise HTTPException(409, "Check-out has already been recorded for today")
    now = datetime.now(timezone.utc)
    row.check_out = now
    row.worked_minutes = int((now - row.check_in).total_seconds() // 60)
    shift = hr_svc.requirement_shift(db, req)
    row.early_minutes = hr_svc.shift_early_minutes(shift, now)
    audit(db, user.id, "hr.attendance.check_out", f"attendance:{row.id}",
          {"employee": emp.code, "worked_minutes": row.worked_minutes})
    db.commit()
    return {"id": row.id, "status": row.status, "check_out": row.check_out,
            "worked_minutes": row.worked_minutes, "early_minutes": row.early_minutes}


@router.post("/attendance/manual", status_code=201)
def manual_attendance(body: ManualAttendanceIn, db: Session = Depends(get_db),
                      user=Depends(require("hr:attendance_manage"))):
    emp = _scoped_employee(db, user, body.employee_id)
    req = hr_svc.require_attendance(db, emp, body.date)
    if body.check_in and body.check_out and body.check_out <= body.check_in:
        raise HTTPException(422, "Check-out must be later than check-in")
    _assert_period_open(db, "attendance", body.date, user, body.override_reason,
                        action="manual attendance")
    row = db.scalar(select(Attendance).where(Attendance.employee_id == emp.id,
                                             Attendance.date == body.date).with_for_update())
    old = None
    if row is None:
        row = Attendance(employee_id=emp.id, date=body.date)
        db.add(row)
    else:
        old = {"status": row.status, "check_in": str(row.check_in) if row.check_in else None,
               "check_out": str(row.check_out) if row.check_out else None,
               "overtime_minutes": row.overtime_minutes}
    row.status = body.status
    row.check_in = body.check_in
    row.check_out = body.check_out
    row.office_id = body.office_id
    row.source = "manual"
    row.geofence_result = "manual"
    row.remarks = body.remarks
    row.overtime_minutes = body.overtime_minutes
    row.approved_by = user.id
    row.worked_minutes = 0
    row.late_minutes = row.early_minutes = 0
    if body.check_in and body.check_out:
        row.worked_minutes = int((body.check_out - body.check_in).total_seconds() // 60)
        shift = hr_svc.requirement_shift(db, req)
        row.late_minutes = hr_svc.shift_late_minutes(shift, body.check_in)
        row.early_minutes = hr_svc.shift_early_minutes(shift, body.check_out)
    db.flush()
    audit(db, user.id, "hr.attendance.manual", f"attendance:{row.id}",
          {"employee": emp.code, "date": str(body.date), "old": old,
           "new": {"status": body.status, "check_in": str(body.check_in) if body.check_in else None,
                   "check_out": str(body.check_out) if body.check_out else None,
                   "overtime_minutes": body.overtime_minutes, "remarks": body.remarks},
           "override_reason": body.override_reason})
    db.commit()
    return {"id": row.id, "date": row.date, "status": row.status,
            "worked_minutes": row.worked_minutes, "overtime_minutes": row.overtime_minutes}


@router.post("/attendance/{attendance_id}/correction", status_code=201)
def request_correction(attendance_id: int, body: CorrectionIn, db: Session = Depends(get_db),
                       user=Depends(require("hr:attendance_self"))):
    row = db.get(Attendance, attendance_id)
    if not row:
        raise HTTPException(404, "Attendance record not found")
    me = hr_svc.employee_for_user(db, user)
    if _can(db, user, "hr:attendance_manage"):
        scope = hr_svc.scoped_employee_ids(db, user)
        if scope is not None and row.employee_id not in scope:
            raise HTTPException(403, "That employee is outside your team")
    elif not me or me.id != row.employee_id:
        raise HTTPException(403, "You can only request a correction for your own attendance")
    row_employee = db.get(Employee, row.employee_id)
    if row_employee:
        hr_svc.require_attendance(db, row_employee, row.date)
    _assert_period_open(db, "attendance", row.date, user, action="correction request")
    corr = AttendanceCorrection(
        attendance_id=row.id, employee_id=row.employee_id, requested_by=user.id,
        old_status=row.status, new_status=body.new_status, old_check_in=row.check_in,
        new_check_in=body.new_check_in, old_check_out=row.check_out,
        new_check_out=body.new_check_out, reason=body.reason.strip())
    db.add(corr)
    db.flush()
    hr_svc.request_approval(
        db, record_type="hr_attendance_correction", record_id=corr.id, requested_by=user.id,
        reasons=["attendance_correction"],
        detail={"attendance_id": row.id, "employee_id": row.employee_id,
                "old_status": row.status, "new_status": body.new_status,
                "reason": body.reason.strip()},
        document_number=f"ATT-{row.date:%Y%m%d}-{row.employee_id}",
        subject=f"Attendance correction for {row.date}", requested_dates=str(row.date),
        approver_role="hr_manager")
    row.status = "correction_pending"
    audit(db, user.id, "hr.attendance.correction_request", f"attendance:{row.id}",
          {"employee_id": row.employee_id, "reason": body.reason.strip()})
    db.commit()
    return {"id": corr.id, "status": corr.status}


@router.get("/attendance/corrections")
def list_corrections(status: str | None = None, db: Session = Depends(get_db),
                     user=Depends(require("hr:read"))):
    stmt = select(AttendanceCorrection)
    if status:
        stmt = stmt.where(AttendanceCorrection.status == status)
    scope = hr_svc.scoped_employee_ids(db, user)
    if scope is not None:
        stmt = stmt.where(AttendanceCorrection.employee_id.in_(scope or {-1}))
    rows = db.scalars(stmt.order_by(AttendanceCorrection.id.desc())).all()
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    return [{"id": r.id, "attendance_id": r.attendance_id, "employee": emps[r.employee_id].full_name if r.employee_id in emps else "?",
             "reason": r.reason, "status": r.status, "old_status": r.old_status,
             "new_status": r.new_status, "created_at": r.created_at,
             "decided_at": r.decided_at, "remarks": r.remarks} for r in rows]


# --------------------------------------------------------------- leave
class LeaveTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["paid", "unpaid"] = "paid"
    requires_document: bool = False
    default_days: Decimal = Field(default=Decimal(0), ge=0)
    carry_forward: bool = False
    encashable: bool = False
    max_carry_forward: Decimal = Field(default=Decimal(0), ge=0)
    half_day_allowed: bool = True


class LeaveTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    requires_document: bool | None = None
    default_days: Decimal | None = Field(default=None, ge=0)
    carry_forward: bool | None = None
    encashable: bool | None = None
    max_carry_forward: Decimal | None = Field(default=None, ge=0)
    half_day_allowed: bool | None = None
    active: bool | None = None


class LeaveIn(BaseModel):
    leave_type_id: int
    date_from: date
    date_to: date
    portion: Literal["full", "first_half", "second_half"] = "full"
    reason: str = Field(min_length=3, max_length=300)
    document: str | None = Field(default=None, max_length=300)
    employee_id: int | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.date_to < self.date_from:
            raise ValueError("end date cannot be before start date")
        if self.portion != "full" and self.date_from != self.date_to:
            raise ValueError("a half-day application must be for a single date")
        if (self.date_to - self.date_from).days > 90:
            raise ValueError("a single application cannot exceed 90 days")
        return self


def _leave_type_audit(t: LeaveType) -> dict:
    # The audit column is JSON; Decimals are stored as strings, as money is.
    return {k: (str(v) if isinstance(v, Decimal) else v)
            for k, v in _leave_type_dict(t).items()}


def _leave_type_dict(t: LeaveType) -> dict:
    return {"id": t.id, "code": t.code, "name": t.name, "kind": t.kind,
            "requires_document": t.requires_document, "default_days": t.default_days,
            "carry_forward": t.carry_forward, "encashable": t.encashable,
            "max_carry_forward": t.max_carry_forward,
            "half_day_allowed": t.half_day_allowed, "active": t.active}


@router.get("/leave/types")
def leave_types(db: Session = Depends(get_db), user=Depends(current_user)):
    _require_hr_view(db, user)
    return [_leave_type_dict(t)
            for t in db.scalars(select(LeaveType).order_by(LeaveType.code)).all()]


@router.post("/leave/types", status_code=201)
def create_leave_type(body: LeaveTypeIn, db: Session = Depends(get_db),
                      actor=Depends(require("hr:write"))):
    t = LeaveType(**body.model_dump())
    db.add(t)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Leave type code exists")
    audit(db, actor.id, "hr.leave_type.create", f"leave_type:{t.id}", {"code": t.code})
    db.commit()
    return {"id": t.id, "code": t.code, "name": t.name}


@router.patch("/leave/types/{type_id}")
def update_leave_type(type_id: int, body: LeaveTypePatch, db: Session = Depends(get_db),
                      actor=Depends(require("hr:write"))):
    """The Administrator's leave rules: carry-forward cap, encashment, half days."""
    t = db.get(LeaveType, type_id)
    if not t:
        raise HTTPException(404, "Leave type not found")
    before = _leave_type_audit(t)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "No changes were supplied")
    if changes.get("max_carry_forward") is not None and not (changes.get("carry_forward", t.carry_forward)):
        raise HTTPException(422, "A carry-forward cap needs carry_forward enabled")
    for key, value in changes.items():
        setattr(t, key, value)
    audit(db, actor.id, "hr.leave_type.update", f"leave_type:{t.id}",
          {"code": t.code, "before": before, "after": _leave_type_audit(t)})
    db.commit()
    return _leave_type_dict(t)


@router.get("/leave/balances")
def leave_balances(employee_id: int | None = None, year: int | None = None,
                   db: Session = Depends(get_db), user=Depends(current_user)):
    _require_hr_view(db, user)
    emp = _employee_or_403(db, user, employee_id)
    year = year or date.today().year
    rows = []
    for t in db.scalars(select(LeaveType).where(LeaveType.active.is_(True))).all():
        bal = hr_svc.leave_balance(db, emp.id, t.id, year)
        rows.append({"leave_type_id": t.id, "code": t.code, "name": t.name,
                     "entitled": bal.entitled, "used": bal.used, "pending": bal.pending,
                     "carried": bal.carried,
                     "available": bal.entitled + bal.carried - bal.used - bal.pending})
    db.commit()
    return {"employee_id": emp.id, "year": year, "balances": rows}


@router.get("/leave/applications")
def list_leave(status: str | None = None, employee_id: int | None = None,
               db: Session = Depends(get_db), user=Depends(current_user)):
    _require_hr_view(db, user)
    stmt = select(LeaveApplication)
    scope = hr_svc.scoped_employee_ids(db, user)
    if scope is not None:
        if employee_id and employee_id not in scope:
            raise HTTPException(403, "That employee is outside your team")
        stmt = stmt.where(LeaveApplication.employee_id.in_(scope or {-1}))
    elif employee_id:
        stmt = stmt.where(LeaveApplication.employee_id == employee_id)
    if status:
        stmt = stmt.where(LeaveApplication.status == status)
    rows = db.scalars(stmt.order_by(LeaveApplication.id.desc())).all()
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    types = {t.id: t for t in db.scalars(select(LeaveType)).all()}
    return [{"id": r.id, "employee_id": r.employee_id,
             "employee": emps[r.employee_id].full_name if r.employee_id in emps else "?",
             "employee_code": emps[r.employee_id].code if r.employee_id in emps else "",
             "leave_type": types[r.leave_type_id].name if r.leave_type_id in types else "?",
             "leave_type_code": types[r.leave_type_id].code if r.leave_type_id in types else "",
             "date_from": r.date_from, "date_to": r.date_to, "days": r.days,
             "portion": r.portion, "reason": r.reason, "status": r.status,
             "remarks": r.remarks, "created_at": r.created_at,
             "decided_at": r.decided_at} for r in rows]


@router.post("/leave/applications", status_code=201)
def apply_leave(body: LeaveIn, db: Session = Depends(get_db),
                user=Depends(require("hr:attendance_self"))):
    emp = _employee_or_403(db, user, body.employee_id)
    lt = db.get(LeaveType, body.leave_type_id)
    if not lt or not lt.active:
        raise HTTPException(404, "Leave type not found")
    if lt.requires_document and not body.document:
        raise HTTPException(422, "This leave type needs a supporting document")
    if body.date_from.year != body.date_to.year:
        raise HTTPException(422, "A leave application must stay within one calendar year; "
                                 "balances are kept per year")
    if body.portion != "full" and not lt.half_day_allowed:
        raise HTTPException(422, f"{lt.code} does not allow half days")
    working = hr_svc.leave_working_days(db, emp, body.date_from, body.date_to)
    if not working:
        raise HTTPException(422, "The selected dates contain no working days")
    days = Decimal(len(working)) if body.portion == "full" else Decimal("0.5")
    overlap = db.scalar(select(LeaveApplication).where(
        LeaveApplication.employee_id == emp.id,
        LeaveApplication.status.in_(("pending", "approved")),
        LeaveApplication.date_from <= body.date_to,
        LeaveApplication.date_to >= body.date_from))
    if overlap:
        raise HTTPException(409, "This leave overlaps an existing application")
    bal = hr_svc.leave_balance(db, emp.id, lt.id, body.date_from.year)
    balance_before = bal.entitled + bal.carried - bal.used - bal.pending
    if lt.kind == "paid" and balance_before < days:
        raise HTTPException(422, f"Only {balance_before} day(s) of {lt.code} are available")
    app = LeaveApplication(employee_id=emp.id, leave_type_id=lt.id, date_from=body.date_from,
                           date_to=body.date_to, days=days, portion=body.portion,
                           reason=body.reason.strip(),
                           document=body.document, created_by=user.id)
    db.add(app)
    db.flush()
    bal.pending += days
    hr_svc.request_approval(
        db, record_type="hr_leave", record_id=app.id, requested_by=user.id,
        reasons=["leave"], detail={"employee_id": emp.id, "leave_type": lt.code,
                                   "days": str(days), "portion": body.portion,
                                   "reason": app.reason},
        document_number=f"LV-{app.id:05d}",
        subject=f"{emp.full_name}: {lt.name}",
        requested_dates=f"{body.date_from} to {body.date_to}",
        approver_role="reporting_manager")
    audit(db, user.id, "hr.leave.apply", f"leave:{app.id}",
          {"employee": emp.code, "leave_type": lt.code, "days": str(days),
           "portion": body.portion, "working_days": [str(d) for d in working]})
    db.commit()
    return {"id": app.id, "status": app.status, "days": app.days,
            "portion": app.portion, "balance_before": balance_before,
            "balance_after": balance_before - days}


@router.post("/leave/applications/{application_id}/cancel")
def cancel_leave(application_id: int, db: Session = Depends(get_db),
                 user=Depends(require("hr:attendance_self"))):
    app = db.scalars(select(LeaveApplication).where(LeaveApplication.id == application_id)
                     .with_for_update()).first()
    if not app:
        raise HTTPException(404, "Leave application not found")
    me = hr_svc.employee_for_user(db, user)
    if not _can(db, user, "hr:write") and (not me or me.id != app.employee_id):
        raise HTTPException(403, "You can only cancel your own leave")
    if app.status != "pending":
        raise HTTPException(409, "Only a pending application can be cancelled")
    bal = hr_svc.leave_balance(db, app.employee_id, app.leave_type_id, app.date_from.year)
    bal.pending = max(Decimal(0), bal.pending - app.days)
    app.status = "cancelled"
    pending = db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.record_type == "hr_leave", ApprovalRequest.record_id == app.id,
        ApprovalRequest.status == "pending"))
    if pending:
        pending.status = "withdrawn"
    audit(db, user.id, "hr.leave.cancel", f"leave:{app.id}", {"employee_id": app.employee_id})
    db.commit()
    return {"id": app.id, "status": app.status}


class BalanceAdjustIn(BaseModel):
    employee_id: int
    leave_type_id: int
    year: int = Field(ge=2000, le=2100)
    entitled: Decimal | None = Field(default=None, ge=0, le=365)
    used: Decimal | None = Field(default=None, ge=0, le=365)
    carried: Decimal | None = Field(default=None, ge=0, le=365)
    reason: str = Field(min_length=5, max_length=300)

    @model_validator(mode="after")
    def one_change(self):
        if all(getattr(self, key) is None for key in ("entitled", "used", "carried")):
            raise ValueError("Supply at least one of entitled, used or carried")
        return self


def _balance_dict(bal: LeaveBalance, t: LeaveType) -> dict:
    return {"employee_id": bal.employee_id, "leave_type_id": t.id, "code": t.code,
            "name": t.name, "year": bal.year, "entitled": bal.entitled, "used": bal.used,
            "pending": bal.pending, "carried": bal.carried,
            "available": bal.entitled + bal.carried - bal.used - bal.pending}


@router.post("/leave/balances/adjust")
def adjust_leave_balance(body: BalanceAdjustIn, db: Session = Depends(get_db),
                         actor=Depends(require("hr:write"))):
    """An audited correction to one person's entitlement or usage.

    `pending` is not editable: it belongs to applications awaiting a decision
    and changes only through those decisions.
    """
    emp = db.get(Employee, body.employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    lt = db.get(LeaveType, body.leave_type_id)
    if not lt:
        raise HTTPException(404, "Leave type not found")
    bal = hr_svc.leave_balance(db, emp.id, lt.id, body.year)
    before = _balance_dict(bal, lt)
    for key in ("entitled", "used", "carried"):
        value = getattr(body, key)
        if value is not None:
            setattr(bal, key, value)
    db.flush()
    audit(db, actor.id, "hr.leave_balance.adjust",
          f"leave_balance:{emp.id}:{lt.id}:{body.year}",
          {"employee": emp.code, "leave_type": lt.code, "year": body.year,
           "before": {k: str(v) for k, v in before.items()
                      if k in ("entitled", "used", "pending", "carried")},
           "after": {k: str(getattr(bal, k))
                     for k in ("entitled", "used", "pending", "carried")},
           "reason": body.reason.strip()})
    db.commit()
    return _balance_dict(bal, lt)


@router.get("/leave/calendar")
def leave_calendar(year: int, month: int, department: str | None = None,
                   db: Session = Depends(get_db), user=Depends(require("hr:read"))):
    """Pending and approved leave for a month, scoped to the viewer's team."""
    if not 1 <= month <= 12:
        raise HTTPException(422, "month must be between 1 and 12")
    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    scope = hr_svc.scoped_employee_ids(db, user)
    stmt = select(Employee).where(Employee.status == "active")
    if scope is not None:
        stmt = stmt.where(Employee.id.in_(scope or {-1}))
    if department:
        stmt = stmt.where(Employee.department == department)
    employees = list(db.scalars(stmt.order_by(Employee.code)).all())
    if len(employees) > 400:
        raise HTTPException(422, "More than 400 employees match; filter by department")
    ids = [e.id for e in employees]
    apps = db.scalars(select(LeaveApplication).where(
        LeaveApplication.employee_id.in_(ids or [-1]),
        LeaveApplication.status.in_(("pending", "approved")),
        LeaveApplication.date_from <= last, LeaveApplication.date_to >= first)
        .order_by(LeaveApplication.date_from, LeaveApplication.employee_id)).all()
    types = {t.id: t for t in db.scalars(select(LeaveType)).all()}
    holidays = db.scalars(select(Holiday).where(
        Holiday.date >= first, Holiday.date <= last).order_by(Holiday.date)).all()
    by_id = {e.id: e for e in employees}
    return {
        "year": year, "month": month,
        "employees": [{"employee_id": e.id, "code": e.code, "name": e.full_name,
                       "department": e.department} for e in employees],
        "entries": [{"id": a.id, "employee_id": a.employee_id,
                     "employee": by_id[a.employee_id].full_name,
                     "leave_type": types[a.leave_type_id].name
                     if a.leave_type_id in types else "?",
                     "leave_type_code": types[a.leave_type_id].code
                     if a.leave_type_id in types else "",
                     "date_from": a.date_from, "date_to": a.date_to, "days": a.days,
                     "portion": a.portion, "status": a.status} for a in apps],
        "holidays": [{"id": h.id, "date": h.date, "name": h.name,
                      "branch_id": h.branch_id, "location_id": h.location_id}
                     for h in holidays],
    }


class CarryForwardIn(BaseModel):
    from_year: int = Field(ge=2000, le=2099)
    dry_run: bool = True


@router.post("/leave/carry-forward")
def carry_forward(body: CarryForwardIn, db: Session = Depends(get_db),
                  actor=Depends(require("hr:write"))):
    """Apply each leave type's carry-forward cap to the following year.

    Unused days are entitled + carried - used - pending, floored at zero and
    capped by the type's max_carry_forward. A dry run returns the same figures
    without writing anything.
    """
    next_year = body.from_year + 1
    types = {t.id: t for t in db.scalars(select(LeaveType).where(
        LeaveType.carry_forward.is_(True), LeaveType.active.is_(True))).all()}
    if not types:
        return {"from_year": body.from_year, "to_year": next_year,
                "dry_run": body.dry_run, "rows": [], "total_carried_days": 0,
                "note": "No active leave type has carry-forward enabled."}
    balances = db.scalars(select(LeaveBalance).where(
        LeaveBalance.year == body.from_year,
        LeaveBalance.leave_type_id.in_(list(types)))).all()
    rows = []
    total = Decimal(0)
    for bal in balances:
        emp = db.get(Employee, bal.employee_id)
        if not emp or emp.status != "active":
            continue
        lt = types[bal.leave_type_id]
        unused = max(Decimal(0), bal.entitled + bal.carried - bal.used - bal.pending)
        carry = min(unused, lt.max_carry_forward or Decimal(0))
        total += carry
        if not body.dry_run:
            following = hr_svc.leave_balance(db, bal.employee_id, bal.leave_type_id,
                                             next_year)
            following.carried = carry
        rows.append({"employee_id": emp.id, "employee": emp.full_name, "code": emp.code,
                     "leave_type": lt.name, "leave_type_code": lt.code,
                     "unused_days": unused, "max_carry_forward": lt.max_carry_forward,
                     "carried": carry})
    if not body.dry_run:
        db.flush()
        audit(db, actor.id, "hr.leave.carry_forward", f"leave_carry:{body.from_year}",
              {"from_year": body.from_year, "to_year": next_year,
               "rows": len(rows), "total_carried_days": str(total)})
        db.commit()
    return {"from_year": body.from_year, "to_year": next_year,
            "dry_run": body.dry_run, "rows": rows, "total_carried_days": total}


# --------------------------------------------------------------- on duty
class ODIn(BaseModel):
    employee_id: int | None = None
    date: date
    end_date: date | None = None
    duration: str = "full_day"
    visit_type: str = Field(min_length=2, max_length=40)
    purpose: str = Field(min_length=3, max_length=300)
    party_type: str | None = Field(default=None, max_length=20)
    party_name: str | None = Field(default=None, max_length=150)
    worksite: str | None = Field(default=None, max_length=150)
    destination: str | None = Field(default=None, max_length=200)
    document: str | None = Field(default=None, max_length=300)
    remarks: str | None = Field(default=None, max_length=300)
    regularisation: bool = False

    @model_validator(mode="after")
    def dates(self):
        if self.end_date and self.end_date < self.date:
            raise ValueError("end date cannot be before the OD date")
        return self


@router.get("/od")
def list_od(status: str | None = None, employee_id: int | None = None,
            db: Session = Depends(get_db), user=Depends(current_user)):
    _require_hr_view(db, user)
    scope = hr_svc.scoped_employee_ids(db, user)
    stmt = select(ODRequest)
    if scope is not None:
        if employee_id and employee_id not in scope:
            raise HTTPException(403, "That employee is outside your team")
        stmt = stmt.where(ODRequest.employee_id.in_(scope or {-1}))
    elif employee_id:
        stmt = stmt.where(ODRequest.employee_id == employee_id)
    if status:
        stmt = stmt.where(ODRequest.status == status)
    rows = db.scalars(stmt.order_by(ODRequest.id.desc())).all()
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    return [{"id": r.id, "employee_id": r.employee_id,
             "employee": emps[r.employee_id].full_name if r.employee_id in emps else "?",
             "date": r.date, "end_date": r.end_date, "duration": r.duration,
             "visit_type": r.visit_type, "purpose": r.purpose, "party_name": r.party_name,
             "destination": r.destination, "status": r.status, "regularisation": r.regularisation,
             "decision_remarks": r.decision_remarks, "created_at": r.created_at} for r in rows]


@router.post("/od", status_code=201)
def create_od(body: ODIn, db: Session = Depends(get_db),
              user=Depends(require("hr:attendance_self"))):
    emp = _employee_or_403(db, user, body.employee_id)
    od = ODRequest(employee_id=emp.id, date=body.date, end_date=body.end_date,
                   duration=body.duration, visit_type=body.visit_type,
                   purpose=body.purpose.strip(), party_type=body.party_type,
                   party_name=body.party_name, worksite=body.worksite,
                   destination=body.destination, manager_id=emp.manager_id,
                   document=body.document, remarks=body.remarks,
                   regularisation=body.regularisation, created_by=user.id)
    db.add(od)
    db.flush()
    hr_svc.request_approval(
        db, record_type="hr_od", record_id=od.id, requested_by=user.id,
        reasons=["od"], detail={"employee_id": emp.id, "visit_type": od.visit_type,
                                "purpose": od.purpose},
        document_number=f"OD-{od.id:05d}", subject=f"{emp.full_name}: {od.visit_type}",
        requested_dates=str(od.date), approver_role="reporting_manager")
    audit(db, user.id, "hr.od.create", f"od:{od.id}",
          {"employee": emp.code, "date": str(od.date), "visit_type": od.visit_type})
    db.commit()
    return {"id": od.id, "status": od.status}


# --------------------------------------------------------------- salary config
STATUTORY_HEADS = (("pf", "Provident fund"), ("esi", "Employee state insurance"),
                   ("pt", "Professional tax"), ("tds", "Tax deducted at source"))
STATUTORY_HEAD_KEYS = tuple(key for key, _ in STATUTORY_HEADS)


class ComponentIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["earning", "deduction"]
    calc_type: Literal["fixed", "percent_basic", "percent_gross"] = "fixed"
    default_rate: Decimal = Field(default=0, ge=0)
    taxable: bool = True
    statutory: bool = False
    statutory_head: Literal[*STATUTORY_HEAD_KEYS] | None = None
    sort_order: int = 0

    @model_validator(mode="after")
    def head_needs_statutory(self):
        if self.statutory_head and not self.statutory:
            raise ValueError("a statutory head needs statutory = true")
        return self


class ComponentPatch(BaseModel):
    """Only the fields sent are changed; sending statutory_head: null clears it."""
    name: str | None = Field(default=None, min_length=2, max_length=80)
    calc_type: Literal["fixed", "percent_basic", "percent_gross"] | None = None
    default_rate: Decimal | None = Field(default=None, ge=0)
    taxable: bool | None = None
    statutory: bool | None = None
    statutory_head: Literal[*STATUTORY_HEAD_KEYS] | None = None
    active: bool | None = None
    sort_order: int | None = None


class StructureLineIn(BaseModel):
    component_id: int
    amount: Decimal = Field(default=0, ge=0)
    percent: Decimal | None = Field(default=None, ge=0, le=100)


class StructureIn(BaseModel):
    employee_id: int
    effective_from: date
    payment_mode: str = "bank"
    lines: list[StructureLineIn] = Field(min_length=1)


@router.get("/salary/components")
def list_components(db: Session = Depends(get_db), _=Depends(require("hr:payroll_prepare"))):
    return [{"id": c.id, "code": c.code, "name": c.name, "kind": c.kind,
             "calc_type": c.calc_type, "default_rate": c.default_rate, "taxable": c.taxable,
             "statutory": c.statutory, "statutory_head": c.statutory_head,
             "active": c.active, "sort_order": c.sort_order}
            for c in db.scalars(select(SalaryComponent).order_by(SalaryComponent.sort_order)).all()]


def _component_audit(c) -> dict:
    return {"code": c.code, "name": c.name, "kind": c.kind, "calc_type": c.calc_type,
            "default_rate": str(c.default_rate), "taxable": c.taxable,
            "statutory": c.statutory, "statutory_head": c.statutory_head,
            "active": c.active, "sort_order": c.sort_order}


@router.patch("/salary/components/{component_id}")
def update_component(component_id: int, body: ComponentPatch, db: Session = Depends(get_db),
                     actor=Depends(require("hr:write"))):
    """Change a payroll rule. Every field is optional; nothing is inferred.

    The rate itself lives in default_rate (or on each structure line), so this
    endpoint never invents a statutory percentage.
    """
    if not _can(db, actor, "hr:confidential", "hr:payroll_prepare"):
        raise HTTPException(403, "Confidential HR rights are required to change salary data")
    c = db.get(SalaryComponent, component_id)
    if not c:
        raise HTTPException(404, "Salary component not found")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "Nothing to change")
    before = _component_audit(c)
    for key, value in data.items():
        setattr(c, key, value)
    if c.statutory_head and not c.statutory:
        raise HTTPException(422, "A statutory head needs statutory = true")
    if c.kind == "earning" and c.statutory_head:
        raise HTTPException(422, "Statutory heads apply to deductions only")
    audit(db, actor.id, "hr.salary_component.update", f"component:{c.id}",
          {"before": before, "after": _component_audit(c)})
    db.commit()
    return {"id": c.id, **_component_audit(c)}


@router.post("/salary/components", status_code=201)
def create_component(body: ComponentIn, db: Session = Depends(get_db),
                     actor=Depends(require("hr:write"))):
    if not _can(db, actor, "hr:confidential", "hr:payroll_prepare"):
        raise HTTPException(403, "Confidential HR rights are required to change salary data")
    if body.kind == "earning" and body.statutory_head:
        raise HTTPException(422, "Statutory heads apply to deductions only")
    c = SalaryComponent(**body.model_dump())
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Component code exists")
    audit(db, actor.id, "hr.salary_component.create", f"component:{c.id}",
          {"code": c.code, "calc_type": c.calc_type})
    db.commit()
    return {"id": c.id, "code": c.code}


@router.get("/salary/structures")
def list_structures(employee_id: int | None = None, db: Session = Depends(get_db),
                    _=Depends(require("hr:payroll_prepare"))):
    stmt = select(SalaryStructure)
    if employee_id:
        stmt = stmt.where(SalaryStructure.employee_id == employee_id)
    rows = db.scalars(stmt.order_by(SalaryStructure.id.desc())).all()
    comps = {c.id: c for c in db.scalars(select(SalaryComponent)).all()}
    return [{"id": s.id, "employee_id": s.employee_id, "effective_from": s.effective_from,
             "effective_to": s.effective_to, "status": s.status, "payment_mode": s.payment_mode,
             "lines": [{"component_id": l.component_id,
                        "component": comps[l.component_id].name if l.component_id in comps else "?",
                        "kind": comps[l.component_id].kind if l.component_id in comps else "?",
                        "amount": l.amount, "percent": l.percent} for l in s.lines]}
            for s in rows]


@router.post("/salary/structures", status_code=201)
def create_structure(body: StructureIn, db: Session = Depends(get_db),
                     actor=Depends(require("hr:write"))):
    if not _can(db, actor, "hr:confidential", "hr:payroll_prepare"):
        raise HTTPException(403, "Confidential HR rights are required to change salary data")
    emp = db.get(Employee, body.employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    component_ids = [line.component_id for line in body.lines]
    if len(component_ids) != len(set(component_ids)):
        raise HTTPException(422, "Each salary component can appear only once")
    # Close the previous active structure the day before the revision.
    prev = db.scalar(select(SalaryStructure).where(
        SalaryStructure.employee_id == emp.id, SalaryStructure.status == "active")
        .order_by(SalaryStructure.effective_from.desc()))
    if prev and prev.effective_from >= body.effective_from:
        raise HTTPException(
            409, "A structure already starts on or after this date; choose a later effective date")
    if prev:
        prev.effective_to = body.effective_from - timedelta(days=1)
    s = SalaryStructure(employee_id=emp.id, effective_from=body.effective_from,
                        payment_mode=body.payment_mode, created_by=actor.id)
    db.add(s)
    db.flush()
    for line in body.lines:
        if not db.get(SalaryComponent, line.component_id):
            raise HTTPException(422, "Unknown salary component")
        db.add(SalaryStructureLine(structure_id=s.id, component_id=line.component_id,
                                   amount=line.amount, percent=line.percent))
    audit(db, actor.id, "hr.salary_structure.create", f"structure:{s.id}",
          {"employee": emp.code, "effective_from": str(s.effective_from),
           "lines": len(body.lines)})
    db.commit()
    return {"id": s.id, "employee_id": s.employee_id, "effective_from": s.effective_from}


# --------------------------------------------------------------- payroll
class PeriodIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class CorrectionIn2(BaseModel):
    employee_id: int | None = None
    reason: str = Field(min_length=3, max_length=300)
    new_net: Decimal | None = None


@router.get("/payroll/periods")
def list_periods(db: Session = Depends(get_db), _=Depends(require("hr:payroll_prepare"))):
    rows = db.scalars(select(PayrollPeriod).order_by(PayrollPeriod.year.desc(),
                                                     PayrollPeriod.month.desc())).all()
    return [{"id": p.id, "year": p.year, "month": p.month, "status": p.status,
             "entries": len(p.entries),
             "gross": _m(sum((e.gross for e in p.entries), Decimal(0))),
             "net": _m(sum((e.net for e in p.entries), Decimal(0))),
             "prepared_at": p.prepared_at, "approved_at": p.approved_at,
             "processed_at": p.processed_at, "paid_at": p.paid_at, "notes": p.notes}
            for p in rows]


@router.post("/payroll/periods", status_code=201)
def create_period(body: PeriodIn, db: Session = Depends(get_db),
                  actor=Depends(require("hr:payroll_prepare"))):
    p = PayrollPeriod(year=body.year, month=body.month)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Payroll for this period already exists")
    audit(db, actor.id, "hr.payroll.period_create", f"payroll:{p.id}",
          {"year": p.year, "month": p.month})
    db.commit()
    return {"id": p.id, "status": p.status}


@router.get("/payroll/periods/{period_id}")
def get_period(period_id: int, db: Session = Depends(get_db),
               _=Depends(require("hr:payroll_prepare"))):
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    return {"id": p.id, "year": p.year, "month": p.month, "status": p.status,
            "skipped": payroll_svc.skipped_employees(db, p),
            "entries": [{"id": e.id, "employee_id": e.employee_id,
                         "employee": emps[e.employee_id].full_name if e.employee_id in emps else "?",
                         "employee_code": emps[e.employee_id].code if e.employee_id in emps else "",
                         "department": emps[e.employee_id].department if e.employee_id in emps else None,
                         "working_days": e.working_days, "payable_days": e.payable_days,
                         "present_days": e.present_days, "paid_leave_days": e.paid_leave_days,
                         "lop_days": e.lop_days, "gross": _m(e.gross),
                         "deductions": _m(e.deductions), "net": _m(e.net),
                         "status": e.status, "note": e.note,
                         "lines": [{"name": l.name, "kind": l.kind, "amount": _m(l.amount),
                                    "basis": l.basis} for l in e.lines]}
                        for e in p.entries]}


@router.post("/payroll/periods/{period_id}/prepare")
def prepare_payroll(period_id: int, db: Session = Depends(get_db),
                    actor=Depends(require("hr:payroll_prepare"))):
    p = db.scalars(select(PayrollPeriod).where(PayrollPeriod.id == period_id)
                   .with_for_update()).first()
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status not in ("draft", "under_review"):
        raise HTTPException(409, f"Payroll is {p.status}; it cannot be recalculated")
    _assert_period_open(db, "payroll", date(p.year, p.month, 1), actor, action="prepare")
    for old in list(p.entries):
        db.delete(old)
    db.flush()
    entries = payroll_svc.run_payroll(db, p)
    p.status = "under_review"
    p.prepared_by = actor.id
    p.prepared_at = datetime.now(timezone.utc)
    skipped = payroll_svc.skipped_employees(db, p, entries=entries)
    audit(db, actor.id, "hr.payroll.prepare", f"payroll:{p.id}",
          {"year": p.year, "month": p.month, "entries": len(entries),
           "skipped": [s["code"] for s in skipped],
           "net": str(sum((e.net for e in entries), Decimal(0)))})
    db.commit()
    return {"id": p.id, "status": p.status, "entries": len(entries),
            "skipped": skipped,
            "net": _m(sum((e.net for e in entries), Decimal(0)))}


@router.post("/payroll/periods/{period_id}/submit")
def submit_payroll(period_id: int, db: Session = Depends(get_db),
                   actor=Depends(require("hr:payroll_prepare"))):
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status != "under_review":
        raise HTTPException(409, "Only a reviewed payroll can be submitted for approval")
    _assert_period_open(db, "payroll", date(p.year, p.month, 1), actor, action="submit")
    existing = db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.record_type == "hr_payroll", ApprovalRequest.record_id == p.id,
        ApprovalRequest.status == "pending"))
    if existing:
        raise HTTPException(409, "This payroll is already awaiting approval")
    ar = hr_svc.request_approval(
        db, record_type="hr_payroll", record_id=p.id, requested_by=actor.id,
        reasons=["payroll"], detail={"year": p.year, "month": p.month,
                                     "entries": len(p.entries),
                                     "net": str(sum((e.net for e in p.entries), Decimal(0)))},
        document_number=f"PAY-{p.year}{p.month:02d}",
        subject=f"Payroll for {p.year}-{p.month:02d}",
        requested_dates=f"{p.year}-{p.month:02d}", approver_role="admin")
    audit(db, actor.id, "hr.payroll.submit", f"payroll:{p.id}",
          {"year": p.year, "month": p.month})
    db.commit()
    return {"id": p.id, "status": p.status, "approval_id": ar.id}


@router.post("/payroll/periods/{period_id}/process")
def process_payroll(period_id: int, db: Session = Depends(get_db),
                    actor=Depends(require("hr:payroll_approve"))):
    p = db.scalars(select(PayrollPeriod).where(PayrollPeriod.id == period_id)
                   .with_for_update()).first()
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status != "approved":
        raise HTTPException(409, "Only an approved payroll can be processed")
    _assert_period_open(db, "payroll", date(p.year, p.month, 1), actor, action="process")
    p.status = "processed"
    p.processed_at = datetime.now(timezone.utc)
    for e in p.entries:
        e.status = "processed"
    audit(db, actor.id, "hr.payroll.process", f"payroll:{p.id}",
          {"year": p.year, "month": p.month})
    db.commit()
    return {"id": p.id, "status": p.status}


@router.post("/payroll/periods/{period_id}/pay")
def pay_payroll(period_id: int, db: Session = Depends(get_db),
                actor=Depends(require("hr:payroll_approve"))):
    p = db.scalars(select(PayrollPeriod).where(PayrollPeriod.id == period_id)
                   .with_for_update()).first()
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status != "processed":
        raise HTTPException(409, "Only a processed payroll can be marked paid")
    _assert_period_open(db, "payroll", date(p.year, p.month, 1), actor, action="pay")
    p.status = "paid"
    p.paid_at = datetime.now(timezone.utc)
    for e in p.entries:
        e.status = "paid"
    audit(db, actor.id, "hr.payroll.pay", f"payroll:{p.id}",
          {"year": p.year, "month": p.month})
    db.commit()
    return {"id": p.id, "status": p.status}


@router.get("/payroll/periods/{period_id}/register")
def payroll_register(period_id: int, db: Session = Depends(get_db),
                     _=Depends(require("hr:payroll_prepare"))):
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    return [{"employee_code": emps[e.employee_id].code if e.employee_id in emps else "",
             "employee": emps[e.employee_id].full_name if e.employee_id in emps else "?",
             "department": emps[e.employee_id].department if e.employee_id in emps else "",
             "payable_days": e.payable_days, "lop_days": e.lop_days,
             "gross": _m(e.gross), "deductions": _m(e.deductions), "net": _m(e.net),
             "status": e.status}
            for e in p.entries]


@router.get("/payroll/entries/{entry_id}/slip")
def salary_slip(entry_id: int, db: Session = Depends(get_db),
                _=Depends(require("hr:confidential"))):
    entry = db.get(PayrollEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Payroll entry not found")
    emp = db.get(Employee, entry.employee_id)
    period = db.get(PayrollPeriod, entry.period_id)
    body = build_slip(entry, emp, period)
    code = safe_filename(emp.code, f"employee-{emp.id}")
    return Response(content=body, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="salary-slip-{code}-{period.year}-{period.month:02d}.pdf"',
        "Cache-Control": "no-store"})


# ------------------------------------------------------- statutory, bank, recon
RELEASED_PAYROLL_STATUSES = ("processed", "paid")


def _payroll_components(db: Session) -> dict[int, SalaryComponent]:
    return {c.id: c for c in db.scalars(select(SalaryComponent)).all()}


def _bank_rows(period, employees: dict[int, Employee]):
    """Payable rows and skipped rows for the bank file.

    A skipped reason names the missing field, never its value: the audit trail
    and the preview must not contain account numbers.
    """
    rows, skipped = [], []
    for entry in sorted(period.entries, key=lambda e: employees[e.employee_id].code
                        if e.employee_id in employees else ""):
        emp = employees.get(entry.employee_id)
        if emp is None:
            skipped.append({"entry_id": entry.id, "employee_code": "",
                            "employee": "?", "reason": "Employee record is missing"})
            continue
        if Decimal(entry.net or 0) <= 0:
            skipped.append({"entry_id": entry.id, "employee_code": emp.code,
                            "employee": emp.full_name, "reason": "Net payable is zero"})
        elif not emp.bank_account_no or not emp.bank_ifsc:
            skipped.append({"entry_id": entry.id, "employee_code": emp.code,
                            "employee": emp.full_name,
                            "reason": "Bank account or IFSC is not recorded"})
        else:
            rows.append({"entry_id": entry.id, "employee": emp, "net": entry.net})
    return rows, skipped


def _payroll_check(key: str, label: str, report_value, source_label: str, source_value,
                   unit: str = "amount") -> dict:
    if unit == "amount":
        ok = abs(Decimal(report_value or 0) - Decimal(source_value or 0)) < Decimal("0.005")
        report_value, source_value = _m(report_value), _m(source_value)
    else:
        ok = report_value == source_value
    return {"key": key, "label": label, "report_value": report_value,
            "source_label": source_label, "source_value": source_value,
            "unit": unit, "ok": bool(ok)}


@router.get("/payroll/periods/{period_id}/statutory")
def statutory_summary(period_id: int, db: Session = Depends(get_db),
                      _=Depends(require("hr:payroll_prepare"))):
    """PF / ESI / PT / TDS totals grouped by each component's configured head.

    Nothing is computed here: a component's amount is whatever payroll put on
    the entry line, and its head is whatever the Administrator configured. A
    head with no component is returned as a gap, not as zero.
    """
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    comps = _payroll_components(db)
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    grouped: dict[str, list[dict]] = {head: [] for head in STATUTORY_HEAD_KEYS}
    unmapped: list[dict] = []
    other: list[dict] = []
    for entry in p.entries:
        emp = emps.get(entry.employee_id)
        for line in entry.lines:
            if line.kind != "deduction":
                continue
            comp = comps.get(line.component_id) if line.component_id else None
            row = {"entry_id": entry.id,
                   "employee_code": emp.code if emp else "",
                   "employee": emp.full_name if emp else "?",
                   "component": comp.name if comp else line.name,
                   "component_code": comp.code if comp else None,
                   "amount": _m(line.amount)}
            if comp is not None and comp.statutory and comp.statutory_head in grouped:
                grouped[comp.statutory_head].append(row)
            elif comp is not None and comp.statutory:
                unmapped.append(row)
            else:
                other.append(row)

    gaps: list[str] = []
    heads = []
    for head, label in STATUTORY_HEADS:
        configured = [c for c in comps.values()
                      if c.statutory and c.statutory_head == head and c.active]
        inactive = [c for c in comps.values()
                    if c.statutory and c.statutory_head == head and not c.active]
        lines = grouped[head]
        heads.append({"head": head, "label": label, "configured": bool(configured),
                      "components": [c.code for c in configured],
                      "amount": _m(sum((Decimal(l["amount"]) for l in lines), Decimal(0))),
                      "employees": len({l["entry_id"] for l in lines}),
                      "lines": lines})
        if not configured:
            gaps.append(f"No active salary component is configured as {label}"
                        + ("; the existing one is inactive." if inactive
                           else "; the summary cannot be produced."))
    if unmapped:
        codes = sorted({r["component_code"] for r in unmapped if r["component_code"]})
        gaps.append("Statutory component(s) with no statutory head: "
                    + ", ".join(codes) + ". Their amounts are excluded from every summary.")

    def total(rows: list[dict]) -> str:
        return _m(sum((Decimal(r["amount"]) for r in rows), Decimal(0)))

    return {"period_id": p.id, "year": p.year, "month": p.month, "status": p.status,
            "gross": _m(sum((e.gross for e in p.entries), Decimal(0))),
            "deductions": _m(sum((e.deductions for e in p.entries), Decimal(0))),
            "net": _m(sum((e.net for e in p.entries), Decimal(0))),
            "heads": heads,
            "unmapped_statutory": {"amount": total(unmapped), "lines": unmapped},
            "other_deductions": {"amount": total(other), "lines": other},
            "gaps": gaps}


@router.get("/payroll/periods/{period_id}/bank-file")
def payroll_bank_file(period_id: int, format: Literal["csv", "json"] = "csv",
                      db: Session = Depends(get_db),
                      user=Depends(require("hr:payroll_prepare"))):
    """The salary upload file for the bank.

    Full account numbers leave the server only through this endpoint, only to a
    holder of hr:confidential, and only after the payroll has been approved.
    The JSON preview masks them. Every generation is audited by row counts.
    """
    if not _can(db, user, "hr:confidential"):
        raise HTTPException(403, "Confidential HR rights are required to export bank details")
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status in ("draft", "under_review"):
        raise HTTPException(409, "Approve the payroll before generating a bank file")
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    rows, skipped = _bank_rows(p, emps)
    total = sum((Decimal(r["net"] or 0) for r in rows), Decimal(0))
    audit(db, user.id, "hr.payroll.bank_file", f"payroll:{p.id}",
          {"year": p.year, "month": p.month, "rows": len(rows),
           "skipped": len(skipped), "total": str(total), "format": format})
    db.commit()
    if format == "json":
        return {"period_id": p.id, "year": p.year, "month": p.month,
                "rows": [{"employee_code": r["employee"].code,
                          "employee": r["employee"].full_name,
                          "bank_name": r["employee"].bank_name,
                          "ifsc": r["employee"].bank_ifsc,
                          "account_masked": hr_svc.mask_secret(r["employee"].bank_account_no),
                          "amount": _m(r["net"])} for r in rows],
                "skipped": skipped, "total": _m(total), "count": len(rows)}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["employee_code", "beneficiary_name", "bank_name", "ifsc",
                     "account_number", "amount", "narration", "reference"])
    narration = f"Salary {p.year}-{p.month:02d}"
    for row in rows:
        emp = row["employee"]
        writer.writerow([safe_text(emp.code), safe_text(emp.full_name),
                         safe_text(emp.bank_name or ""), safe_text(emp.bank_ifsc or ""),
                         safe_text(emp.bank_account_no or ""),
                         f"{Decimal(row['net']):.2f}", safe_text(narration),
                         safe_text(f"PAY-{p.year}{p.month:02d}-{emp.code}")])
    return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="bank-file-{p.year}-{p.month:02d}.csv"',
        "Cache-Control": "no-store"})


@router.get("/payroll/periods/{period_id}/reconciliation")
def payroll_reconciliation(period_id: int, db: Session = Depends(get_db),
                           _=Depends(require("hr:payroll_prepare"))):
    """Prove the register, the entry lines and the bank file agree."""
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    comps = _payroll_components(db)
    emps = {e.id: e for e in db.scalars(select(Employee)).all()}
    gross = sum((Decimal(e.gross or 0) for e in p.entries), Decimal(0))
    deductions = sum((Decimal(e.deductions or 0) for e in p.entries), Decimal(0))
    net = sum((Decimal(e.net or 0) for e in p.entries), Decimal(0))
    earning_lines = Decimal(0)
    deduction_lines = Decimal(0)
    by_head = {head: Decimal(0) for head in STATUTORY_HEAD_KEYS}
    unmapped = Decimal(0)
    other = Decimal(0)
    for entry in p.entries:
        for line in entry.lines:
            amount = Decimal(line.amount or 0)
            if line.kind == "earning":
                earning_lines += amount
                continue
            deduction_lines += amount
            comp = comps.get(line.component_id) if line.component_id else None
            if comp is not None and comp.statutory and comp.statutory_head in by_head:
                by_head[comp.statutory_head] += amount
            elif comp is not None and comp.statutory:
                unmapped += amount
            else:
                other += amount

    rows, skipped = _bank_rows(p, emps)
    by_entry = {e.id: e for e in p.entries}
    bank_total = sum((Decimal(r["net"] or 0) for r in rows), Decimal(0))
    held_total = sum((Decimal(by_entry[s["entry_id"]].net or 0) for s in skipped),
                     Decimal(0))
    checks = [
        _payroll_check("entries", "Employee entries", len(p.entries),
                       "Distinct employees on entry lines",
                       len({e.employee_id for e in p.entries}), unit="records"),
        _payroll_check("gross", "Gross earnings on the register", gross,
                       "Sum of earning lines", earning_lines),
        _payroll_check("deductions", "Deductions on the register", deductions,
                       "Sum of deduction lines", deduction_lines),
        _payroll_check("net", "Net payable on the register", net,
                       "Gross minus deductions", gross - deductions),
        _payroll_check("bank_file", "Net payable on the register", net,
                       "Bank file plus amounts held back", bank_total + held_total),
        _payroll_check("statutory", "Deductions on the register", deductions,
                       "Statutory heads plus other deductions",
                       sum(by_head.values(), Decimal(0)) + unmapped + other),
    ]
    gaps = []
    if skipped:
        gaps.append(f"{len(skipped)} employee(s) are held back from the bank file: "
                    + ", ".join(f"{s['employee_code']} ({s['reason']})" for s in skipped))
    unheaded = sorted(c.code for c in comps.values()
                      if c.statutory and c.statutory_head is None)
    if unheaded:
        gaps.append("Statutory components with no statutory head: " + ", ".join(unheaded))
    return {"period_id": p.id, "year": p.year, "month": p.month, "status": p.status,
            "gross": _m(gross), "deductions": _m(deductions), "net": _m(net),
            "checks": checks, "reconciled": all(c["ok"] for c in checks),
            "heads": {h: _m(v) for h, v in by_head.items()},
            "unmapped_statutory": _m(unmapped), "other_deductions": _m(other),
            "bank_file": {"rows": len(rows), "skipped": len(skipped),
                          "total": _m(bank_total), "held_back": _m(held_total)},
            "gaps": gaps,
            "accounts_note": "Payroll is carried into the profit and loss as gross salary "
                             "for this approved period, so it is never also recorded as an "
                             "expense. It is not posted as a voucher automatically; record "
                             "a journal in Accounts if it must reach the stored ledger. "
                             "The bank file total is the figure Accounts can match against "
                             "the bank statement."}


@router.get("/me/payslips")
def my_payslips(db: Session = Depends(get_db), user=Depends(current_user)):
    """Released payslips for the signed-in employee. Nobody else's are listed."""
    emp = hr_svc.employee_for_user(db, user)
    if not emp:
        return []
    rows = db.execute(
        select(PayrollEntry, PayrollPeriod)
        .join(PayrollPeriod, PayrollEntry.period_id == PayrollPeriod.id)
        .where(PayrollEntry.employee_id == emp.id,
               PayrollPeriod.status.in_(RELEASED_PAYROLL_STATUSES))
        .order_by(PayrollPeriod.year.desc(), PayrollPeriod.month.desc())).all()
    return [{"entry_id": e.id, "period_id": per.id, "year": per.year, "month": per.month,
             "gross": _m(e.gross), "deductions": _m(e.deductions), "net": _m(e.net),
             "status": e.status} for e, per in rows]


@router.get("/me/payslips/{entry_id}")
def my_payslip(entry_id: int, db: Session = Depends(get_db), user=Depends(current_user)):
    emp = _self_employee(db, user)
    entry = db.get(PayrollEntry, entry_id)
    if not entry or entry.employee_id != emp.id:
        raise HTTPException(404, "Payslip not found")
    period = db.get(PayrollPeriod, entry.period_id)
    if period.status not in RELEASED_PAYROLL_STATUSES:
        raise HTTPException(409, "This payslip has not been released yet")
    body = build_slip(entry, emp, period)
    code = safe_filename(emp.code, f"employee-{emp.id}")
    return Response(content=body, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="salary-slip-{code}-{period.year}-{period.month:02d}.pdf"',
        "Cache-Control": "no-store"})


@router.post("/payroll/periods/{period_id}/corrections", status_code=201)
def request_payroll_correction(period_id: int, body: CorrectionIn2, db: Session = Depends(get_db),
                       actor=Depends(require("hr:payroll_prepare"))):
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status in ("draft", "under_review"):
        raise HTTPException(409, "Correct the draft before it is approved")
    _assert_period_open(db, "payroll", date(p.year, p.month, 1), actor,
                        action="correction request")
    audit(db, actor.id, "hr.payroll.correction_request", f"payroll:{p.id}",
          {"employee_id": body.employee_id, "reason": body.reason.strip()})
    db.commit()
    return {"id": None, "status": "pending", "note": "Recorded in the audit trail. "
            "Finalised payroll is corrected through the authorised reversal workflow."}


# ------------------------------------------------------------------ notices
class AnnouncementIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=1000)


class AnnouncementPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=3, max_length=1000)
    active: bool | None = None


def _note_row(note: HRNotification) -> dict:
    return {"id": note.id, "kind": note.kind, "title": note.title, "body": note.body,
            "link": note.link, "read_at": note.read_at.isoformat() if note.read_at else None,
            "created_at": note.created_at.isoformat() if note.created_at else None}


def _announcement_row(row: Announcement) -> dict:
    return {"id": row.id, "title": row.title, "body": row.body, "active": row.active,
            "published_by": row.published_by,
            "published_at": row.published_at.isoformat() if row.published_at else None}


@router.get("/notifications")
def my_notifications(unread_only: bool = False,
                     limit: int = Query(50, ge=1, le=200),
                     db: Session = Depends(get_db), user=Depends(current_user)):
    """The signed-in user's own bell. Another user's notes are never visible."""
    base = select(HRNotification).where(HRNotification.user_id == user.id)
    unread = db.scalar(select(func.count()).select_from(HRNotification).where(
        HRNotification.user_id == user.id, HRNotification.read_at.is_(None))) or 0
    query = base.where(HRNotification.read_at.is_(None)) if unread_only else base
    rows = db.scalars(query.order_by(HRNotification.created_at.desc(),
                                     HRNotification.id.desc()).limit(limit)).all()
    return {"unread": unread, "items": [_note_row(n) for n in rows]}


@router.post("/notifications/{note_id}/read")
def read_notification(note_id: int, db: Session = Depends(get_db),
                      user=Depends(current_user)):
    note = db.get(HRNotification, note_id)
    if not note or note.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    if not note.read_at:
        note.read_at = datetime.now(timezone.utc)
        db.commit()
    return _note_row(note)


@router.post("/notifications/read-all")
def read_all_notifications(db: Session = Depends(get_db), user=Depends(current_user)):
    unread = db.scalars(select(HRNotification).where(
        HRNotification.user_id == user.id, HRNotification.read_at.is_(None))).all()
    stamp = datetime.now(timezone.utc)
    for note in unread:
        note.read_at = stamp
    db.commit()
    return {"marked": len(unread)}


@router.post("/notifications/digest")
def run_hr_digest(db: Session = Depends(get_db), actor=Depends(require("hr:write"))):
    """Queue the daily digest once per recipient; a second run does not duplicate it."""
    result = hr_notify.run_digest(db)
    audit(db, actor.id, "hr.digest.run", "hr:digest",
          {"queued": result["queued"], "counts": result["counts"]})
    db.commit()
    email = {"sent": False, "reason": "Nothing to report today."}
    if result["notes"]:
        email = hr_notify.email_note(db, result["notes"][0],
                                     subject="Herbanova HR: daily digest")
    return {"queued": result["queued"], "skipped": result["skipped"],
            "counts": result["counts"], "rows": result["rows"], "email": email}


@router.get("/announcements")
def list_announcements(include_inactive: bool = False,
                       limit: int = Query(20, ge=1, le=100),
                       db: Session = Depends(get_db), user=Depends(current_user)):
    can_write = is_admin(db, user) or "hr:write" in role_permissions(db, user)
    query = select(Announcement)
    if not (include_inactive and can_write):
        query = query.where(Announcement.active.is_(True))
    rows = db.scalars(query.order_by(Announcement.published_at.desc(),
                                     Announcement.id.desc()).limit(limit)).all()
    return [_announcement_row(a) for a in rows]


@router.post("/announcements", status_code=201)
def create_announcement(body: AnnouncementIn, db: Session = Depends(get_db),
                        actor=Depends(require("hr:write"))):
    row = Announcement(title=body.title.strip(), body=body.body.strip(), published_by=actor.id)
    db.add(row)
    db.flush()
    people = db.scalars(select(User).where(User.is_active.is_(True),
                                           User.employee_id.is_not(None))).all()
    notes = hr_notify.notify(db, [u.id for u in people], "announcement",
                             f"Announcement: {row.title}", row.body, "/ui#hr")
    audit(db, actor.id, "hr.announcement.publish", f"announcement:{row.id}",
          {"title": row.title, "recipients": len(notes)})
    db.commit()
    email = {"sent": False, "reason": "No linked users to notify."}
    if notes:
        email = hr_notify.email_note(db, notes[0])
    return {**_announcement_row(row), "notified": len(notes), "email": email}


@router.patch("/announcements/{announcement_id}")
def patch_announcement(announcement_id: int, body: AnnouncementPatch,
                       db: Session = Depends(get_db), actor=Depends(require("hr:write"))):
    row = db.get(Announcement, announcement_id)
    if not row:
        raise HTTPException(404, "Announcement not found")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    for field, value in changes.items():
        setattr(row, field, value.strip() if isinstance(value, str) else value)
    audit(db, actor.id, "hr.announcement.update", f"announcement:{row.id}", changes)
    db.commit()
    return _announcement_row(row)


# ------------------------------------------------------------------ reports
@router.get("/reports")
def hr_report_catalog(db: Session = Depends(get_db), user=Depends(require("hr:reports"))):
    """The reports this role may open. Confidential cost is flagged separately."""
    confidential = is_admin(db, user) or bool(
        role_permissions(db, user) & {"hr:confidential", "hr:payroll_prepare"})
    return [{"key": key, "title": title,
             "confidential": key == "department-cost",
             "available": key != "department-cost" or confidential}
            for key, title in hr_reports.REPORTS]


@router.get("/reports/{report}")
def hr_report(report: str, from_date: date | None = None, to_date: date | None = None,
              year: int | None = None, month: int | None = None,
              days: int = Query(60, ge=1, le=365),
              branch_id: int | None = None, office_id: int | None = None,
              fmt: Literal["json", "csv", "pdf"] = Query("json", alias="format"),
              db: Session = Depends(get_db), user=Depends(require("hr:reports"))):
    """One HR report as JSON, CSV or PDF. Gaps are returned, never filled with zeroes."""
    built = hr_reports.build_report(db, report, user, from_date=from_date,
                                    to_date=to_date, year=year, month=month, days=days,
                                    branch_id=branch_id, office_id=office_id)
    if fmt == "json":
        return built
    if fmt == "csv":
        body = hr_reports.to_csv(built)
        media_type, extension = "text/csv; charset=utf-8", "csv"
    else:
        body = hr_reports.to_pdf(built)
        media_type, extension = "application/pdf", "pdf"
    audit(db, user.id, "hr.report.export", f"hr:report:{report}",
          {"format": fmt, "rows": len(built["rows"]), "filters": built["filters"]})
    db.commit()
    filename = f"hr-{report}-{hr_svc.business_today().isoformat()}.{extension}"
    return Response(content=body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store"})


# ------------------------------------------------------- letters and printouts
def _letter_row(template: LetterTemplate) -> dict:
    return {"id": template.id, "code": template.code, "name": template.name,
            "kind": template.kind, "body": template.body, "active": template.active,
            "updated_at": template.updated_at}


def _unknown_placeholders(body: str) -> list[str]:
    used = set(re.findall(r"\{([a-z_]+)\}", body))
    return sorted(token for token in used if token not in hr_documents.PLACEHOLDERS)


def _pdf_response(body: bytes, filename: str) -> Response:
    return Response(content=body, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store"})


@router.get("/letters/templates")
def list_letter_templates(db: Session = Depends(get_db), user=Depends(current_user)):
    """The editable letter bodies, with the placeholder names they may use."""
    _require_hr_view(db, user)
    rows = db.scalars(select(LetterTemplate).order_by(LetterTemplate.id)).all()
    return {"placeholders": list(hr_documents.PLACEHOLDERS),
            "templates": [_letter_row(t) for t in rows]}


class LetterTemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    body: str | None = Field(default=None, min_length=20, max_length=8000)
    active: bool | None = None

    @model_validator(mode="after")
    def one_change(self):
        if self.name is None and self.body is None and self.active is None:
            raise ValueError("Supply at least one of name, body or active")
        return self


@router.patch("/letters/templates/{template_id}")
def patch_letter_template(template_id: int, body: LetterTemplatePatch,
                          db: Session = Depends(get_db),
                          actor=Depends(require("hr:write"))):
    """Edit the wording. Unknown placeholders are refused rather than printed raw."""
    template = db.get(LetterTemplate, template_id)
    if not template:
        raise HTTPException(404, "Letter template not found")
    if body.body is not None:
        unknown = _unknown_placeholders(body.body)
        if unknown:
            raise HTTPException(422, "Unknown placeholder(s): " + ", ".join(
                "{" + token + "}" for token in unknown))
    if body.name is not None:
        template.name = body.name.strip()
    if body.body is not None:
        template.body = body.body.strip()
    if body.active is not None:
        template.active = body.active
    template.updated_by = actor.id
    db.flush()
    audit(db, actor.id, "hr.letter_template.update", f"letter_template:{template.id}",
          {"code": template.code, "name": template.name, "active": template.active,
           "body_changed": body.body is not None})
    db.commit()
    return {**_letter_row(template), "placeholders": list(hr_documents.PLACEHOLDERS)}


@router.get("/outputs/letter/{code}")
def employee_letter(code: str, employee_id: int | None = None,
                    exit_date: date | None = None, db: Session = Depends(get_db),
                    user=Depends(current_user)):
    """Fill one active template for an employee the caller may see.

    The letter is a draft: it is audited and marked unsigned. A date the body
    needs but the employee record does not hold is reported, not left blank.
    """
    _require_hr_view(db, user)
    emp = _employee_or_403(db, user, employee_id)
    template = db.scalar(select(LetterTemplate).where(
        LetterTemplate.code == code.upper(), LetterTemplate.active.is_(True)))
    if not template:
        raise HTTPException(404, "Letter template not found or retired")
    company = hr_documents.company_details(db)
    try:
        pdf = hr_documents.render_letter(template, emp, company, exit_date=exit_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, user.id, "hr.output.letter", f"employee:{emp.id}",
          {"template": template.code, "exit_date": str(exit_date) if exit_date else None})
    db.commit()
    return _pdf_response(pdf, f"{safe_filename(template.code.lower(), 'letter')}-letter-"
                              f"{safe_filename(emp.code, f'employee-{emp.id}')}.pdf")


@router.get("/outputs/id-card")
def employee_id_card(employee_id: int | None = None, db: Session = Depends(get_db),
                     user=Depends(current_user)):
    _require_hr_view(db, user)
    emp = _employee_or_403(db, user, employee_id)
    branch = db.get(Branch, emp.branch_id) if emp.branch_id else None
    office = db.get(WorkLocation, emp.office_id) if emp.office_id else None
    photo = None
    if emp.photo_path:
        candidate = PHOTO_DIR / Path(emp.photo_path).name
        photo = candidate if candidate.exists() else None
    pdf = hr_documents.build_id_card(
        emp, hr_documents.company_details(db),
        branch=branch.name if branch else "", office=office.name if office else "",
        photo_file=photo)
    audit(db, user.id, "hr.output.id_card", f"employee:{emp.id}", {"has_photo": bool(photo)})
    db.commit()
    return _pdf_response(pdf, f"id-card-{safe_filename(emp.code, f'employee-{emp.id}')}.pdf")


@router.get("/outputs/attendance-sheet")
def attendance_sheet(year: int, month: int, employee_id: int | None = None,
                     department: str | None = None, db: Session = Depends(get_db),
                     user=Depends(current_user)):
    """The monthly grid as a printable sheet. Scope is the same as the screen."""
    data = hr_svc.monthly_attendance(db, user, year=year, month=month,
                                     employee_id=employee_id, department=department)
    pdf = hr_documents.build_attendance_sheet(
        data, hr_documents.company_details(db), department=department)
    audit(db, user.id, "hr.output.attendance_sheet", "attendance:monthly",
          {"year": year, "month": month, "employee_id": employee_id,
           "department": department, "employees": len(data["employees"]),
           "missing_days": data["totals"]["missing_days"]})
    db.commit()
    return _pdf_response(pdf, f"attendance-sheet-{year}-{month:02d}.pdf")


@router.get("/outputs/leave-statement")
def leave_statement(employee_id: int | None = None, year: int | None = None,
                    db: Session = Depends(get_db), user=Depends(current_user)):
    """One employee's stored balances and applications for a year."""
    _require_hr_view(db, user)
    emp = _employee_or_403(db, user, employee_id)
    year = year or date.today().year
    if not 2000 <= year <= 2100:
        raise HTTPException(422, "year must be between 2000 and 2100")
    types = {t.id: t for t in db.scalars(select(LeaveType)).all()}
    stored = db.scalars(select(LeaveBalance).where(
        LeaveBalance.employee_id == emp.id, LeaveBalance.year == year)).all()
    balances = [{
        "name": types[b.leave_type_id].name if b.leave_type_id in types
        else "Retired leave type",
        "entitled": str(Decimal(b.entitled).normalize()),
        "carried": str(Decimal(b.carried).normalize()),
        "used": str(Decimal(b.used).normalize()),
        "pending": str(Decimal(b.pending).normalize()),
        "available": str(Decimal(b.entitled + b.carried - b.used
                                 - b.pending).normalize())} for b in stored]
    gaps = [f"No balance has been set for {t.name}."
            for t in sorted(types.values(), key=lambda x: x.name)
            if t.active and t.id not in {b.leave_type_id for b in stored}]
    applications = db.scalars(select(LeaveApplication).where(
        LeaveApplication.employee_id == emp.id,
        LeaveApplication.date_from >= date(year, 1, 1),
        LeaveApplication.date_from <= date(year, 12, 31))
        .order_by(LeaveApplication.date_from, LeaveApplication.id)).all()
    app_rows = [{"date_from": a.date_from.isoformat(), "date_to": a.date_to.isoformat(),
                 "leave_type": types[a.leave_type_id].name if a.leave_type_id in types
                 else "Retired leave type",
                 "days": str(Decimal(a.days).normalize()), "portion": a.portion,
                 "status": a.status} for a in applications]
    pdf = hr_documents.build_leave_statement(emp, year, balances, app_rows,
                                            hr_documents.company_details(db), gaps=gaps)
    audit(db, user.id, "hr.output.leave_statement", f"employee:{emp.id}",
          {"year": year, "applications": len(app_rows)})
    db.commit()
    return _pdf_response(pdf, f"leave-statement-"
                              f"{safe_filename(emp.code, f'employee-{emp.id}')}-{year}.pdf")
