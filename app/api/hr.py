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
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import current_user, is_admin, require, role_permissions
from ..models.core import ApprovalRequest, User
from ..models.hr import (Attendance, AttendanceCorrection, Branch, Department, Holiday,
                         LeaveApplication, LeaveBalance, LeaveType, ODRequest, PayrollEntry,
                         PayrollPeriod, SalaryComponent, SalaryStructure, SalaryStructureLine,
                         Shift, WorkLocation)
from ..models.users import Employee
from ..services import hr as hr_svc
from ..services import payroll as payroll_svc
from ..services.audit import audit
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
                   "work_schedule", "date_of_exit", "probation_end_date", "confirmation_date",
                   "notice_period_days", "exit_reason", "address", "emergency_name",
                   "emergency_phone", "bank_name", "bank_account_no", "bank_ifsc", "pan",
                   "uan", "esi_no", "attendance_policy", "leave_policy"]


def _employee_dict(db: Session, e: Employee, viewer=None) -> dict:
    d = {k: getattr(e, k) for k in EMPLOYEE_FIELDS}
    # The login link is stored on both sides; read the user side too so an
    # older one-way link still shows as linked and is never offered as free.
    user = (db.get(User, e.user_id) if e.user_id
            else db.scalar(select(User).where(User.employee_id == e.id)))
    d["user_id"] = user.id if user else None
    # Bank and ID numbers leave the server masked unless the viewer holds the
    # confidential right or is looking at their own record.
    full = True if viewer is None else hr_svc.may_view_confidential(db, viewer, e)
    d["confidential_visible"] = full
    if not full:
        for key in hr_svc.CONFIDENTIAL_EMPLOYEE_FIELDS:
            d[key] = hr_svc.mask_secret(d.get(key))
    return d


@router.get("/dashboard")
def dashboard(day: date | None = None, db: Session = Depends(get_db),
              user=Depends(require("hr:read"))):
    day = day or date.today()
    total = db.scalar(select(func.count()).select_from(Employee)) or 0
    active = db.scalar(select(func.count()).select_from(Employee)
                       .where(Employee.status == "active")) or 0
    att = dict(db.execute(select(Attendance.status, func.count())
                          .where(Attendance.date == day)
                          .group_by(Attendance.status)).all())
    pending = db.scalar(select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.status == "pending",
        ApprovalRequest.record_type.like("hr_%"))) or 0
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.year == day.year, PayrollPeriod.month == day.month))
    payable = db.scalar(select(func.coalesce(func.sum(PayrollEntry.net), 0))
                        .where(PayrollEntry.period_id == period.id)) if period else Decimal(0)
    dept_rows = db.execute(
        select(Employee.department, func.count())
        .where(Employee.status == "active").group_by(Employee.department)).all()
    branch_rows = db.execute(
        select(Branch.name, func.count()).join(Employee, Employee.branch_id == Branch.id)
        .where(Employee.status == "active").group_by(Branch.name)).all()
    # Payroll totals are salary data: only the confidential/payroll roles see them.
    payroll_visible = _can(db, user, "hr:confidential", "hr:payroll_prepare")
    return {
        "date": day, "total_employees": total, "active_employees": active,
        "inactive_employees": total - active,
        "present_today": att.get("present", 0) + att.get("late", 0),
        "absent_today": att.get("absent", 0),
        "on_leave_today": att.get("paid_leave", 0) + att.get("unpaid_leave", 0),
        "on_od_today": att.get("od", 0),
        "late_today": att.get("late", 0), "early_today": att.get("early_departure", 0),
        "pending_approvals": pending,
        "payroll_visible": payroll_visible,
        "payroll_status": period.status if (period and payroll_visible) else None,
        "salary_payable": _m(payable) if payroll_visible else None,
        "by_department": [{"department": d or "Unassigned", "employees": n}
                          for d, n in dept_rows],
        "by_branch": [{"branch": b, "employees": n} for b, n in branch_rows],
    }


# --------------------------------------------------------------- employees
@router.get("/employees")
def list_employees(response: Response, q: str | None = None, department: str | None = None,
                   branch_id: int | None = None, status: str | None = None,
                   page: int | None = Query(None, ge=1),
                   page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
                   user=Depends(require("hr:read"))):
    stmt = select(Employee)
    scope = hr_svc.scoped_employee_ids(db, user)
    if scope is not None:
        stmt = stmt.where(Employee.id.in_(scope or {-1}))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Employee.code.ilike(like) | Employee.full_name.ilike(like)
                          | Employee.department.ilike(like) | Employee.designation.ilike(like))
    if department:
        stmt = stmt.where(Employee.department == department)
    if branch_id:
        stmt = stmt.where(Employee.branch_id == branch_id)
    if status:
        stmt = stmt.where(Employee.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    stmt = stmt.order_by(Employee.code)
    if page:
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    return [_employee_dict(db, e, user) for e in db.scalars(stmt).all()]


@router.post("/employees", status_code=201)
def create_employee(body: EmployeeIn, db: Session = Depends(get_db),
                    actor=Depends(require("hr:write"))):
    if body.manager_id and not db.get(Employee, body.manager_id):
        raise HTTPException(404, "Manager not found")
    data = body.model_dump()
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


# --------------------------------------------------------------- config
class BranchIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    address: str | None = None


class OfficeIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    branch_id: int | None = None
    address: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    geofence_radius_m: int | None = Field(default=200, gt=0, le=100000)
    attendance_mode: Literal["office", "gps", "both"] = "both"


def _normalise_weekly_offs(value):
    if value is None:
        return value
    if any(day < 0 or day > 6 for day in value):
        raise ValueError("weekly_offs must be weekday numbers 0 (Monday) to 6 (Sunday)")
    return sorted(set(value))


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


@router.get("/branches")
def list_branches(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    return [{"id": b.id, "code": b.code, "name": b.name, "address": b.address,
             "status": b.status} for b in db.scalars(select(Branch).order_by(Branch.code)).all()]


@router.post("/branches", status_code=201)
def create_branch(body: BranchIn, db: Session = Depends(get_db),
                  actor=Depends(require("hr:write"))):
    b = Branch(**body.model_dump())
    db.add(b)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Branch code exists")
    audit(db, actor.id, "hr.branch.create", f"branch:{b.id}", {"code": b.code})
    db.commit()
    return {"id": b.id, "code": b.code, "name": b.name, "address": b.address, "status": b.status}


@router.get("/offices")
def list_offices(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    return [{"id": o.id, "code": o.code, "name": o.name, "branch_id": o.branch_id,
             "address": o.address, "latitude": o.latitude, "longitude": o.longitude,
             "geofence_radius_m": o.geofence_radius_m, "attendance_mode": o.attendance_mode,
             "status": o.status} for o in db.scalars(select(WorkLocation).order_by(WorkLocation.code)).all()]


@router.post("/offices", status_code=201)
def create_office(body: OfficeIn, db: Session = Depends(get_db),
                  actor=Depends(require("hr:write"))):
    o = WorkLocation(**body.model_dump())
    db.add(o)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Office code exists")
    audit(db, actor.id, "hr.office.create", f"office:{o.id}",
          {"code": o.code, "latitude": str(o.latitude), "longitude": str(o.longitude),
           "radius": o.geofence_radius_m})
    db.commit()
    return {"id": o.id, "code": o.code, "name": o.name, "attendance_mode": o.attendance_mode}


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


@router.post("/holidays", status_code=201)
def create_holiday(body: HolidayIn, db: Session = Depends(get_db),
                   actor=Depends(require("hr:write"))):
    h = Holiday(**body.model_dump())
    db.add(h)
    try:
        db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Holiday already exists")
    audit(db, actor.id, "hr.holiday.create", f"holiday:{h.id}",
          {"date": str(h.date), "name": h.name})
    db.commit()
    return {"id": h.id, "date": h.date, "name": h.name}


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
    remarks: str = Field(min_length=3, max_length=300)


class CorrectionIn(BaseModel):
    new_status: str | None = None
    new_check_in: datetime | None = None
    new_check_out: datetime | None = None
    reason: str = Field(min_length=3, max_length=300)


@router.get("/attendance")
def list_attendance(from_date: date | None = None, to_date: date | None = None,
                    employee_id: int | None = None, status: str | None = None,
                    department: str | None = None, db: Session = Depends(get_db),
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
    return [{"id": r.id, "employee_id": r.employee_id,
             "employee": emps[r.employee_id].full_name if r.employee_id in emps else "?",
             "employee_code": emps[r.employee_id].code if r.employee_id in emps else "",
             "date": r.date, "status": r.status, "check_in": r.check_in, "check_out": r.check_out,
             "office_id": r.office_id, "source": r.source, "geofence_result": r.geofence_result,
             "late_minutes": r.late_minutes, "early_minutes": r.early_minutes,
             "worked_minutes": r.worked_minutes, "remarks": r.remarks} for r in rows]


@router.post("/attendance/check-in", status_code=201)
def check_in(body: CheckInIn, db: Session = Depends(get_db),
             user=Depends(require("hr:attendance_self"))):
    emp = _self_employee(db, user)
    today = hr_svc.business_today()
    existing = db.scalar(select(Attendance).where(Attendance.employee_id == emp.id,
                                                  Attendance.date == today))
    if existing:
        raise HTTPException(409, "Attendance for today has already been recorded")
    office = db.get(WorkLocation, body.office_id or emp.office_id) if (body.office_id or emp.office_id) else None
    if office and office.status != "active":
        raise HTTPException(409, "That office is not active")
    result = hr_svc.geofence_result(office, body.latitude, body.longitude)
    if result == "outside" and not (body.remarks and len(body.remarks.strip()) >= 3):
        raise HTTPException(409, "You are outside the permitted geofence. Give a reason for the "
                                 "exception; it will need approval.")
    now = datetime.now(timezone.utc)
    shift = db.get(Shift, emp.shift_id) if emp.shift_id else None
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
    row = db.scalar(select(Attendance).where(Attendance.employee_id == emp.id,
                                             Attendance.date == today).with_for_update())
    if not row or not row.check_in:
        raise HTTPException(409, "No check-in has been recorded for today")
    if row.check_out:
        raise HTTPException(409, "Check-out has already been recorded for today")
    now = datetime.now(timezone.utc)
    row.check_out = now
    row.worked_minutes = int((now - row.check_in).total_seconds() // 60)
    shift = db.get(Shift, emp.shift_id) if emp.shift_id else None
    row.early_minutes = hr_svc.shift_early_minutes(shift, now)
    audit(db, user.id, "hr.attendance.check_out", f"attendance:{row.id}",
          {"employee": emp.code, "worked_minutes": row.worked_minutes})
    db.commit()
    return {"id": row.id, "status": row.status, "check_out": row.check_out,
            "worked_minutes": row.worked_minutes, "early_minutes": row.early_minutes}


@router.post("/attendance/manual", status_code=201)
def manual_attendance(body: ManualAttendanceIn, db: Session = Depends(get_db),
                      user=Depends(require("hr:attendance_manage"))):
    emp = db.get(Employee, body.employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    row = db.scalar(select(Attendance).where(Attendance.employee_id == emp.id,
                                             Attendance.date == body.date).with_for_update())
    old = None
    if row is None:
        row = Attendance(employee_id=emp.id, date=body.date)
        db.add(row)
    else:
        old = {"status": row.status, "check_in": str(row.check_in) if row.check_in else None,
               "check_out": str(row.check_out) if row.check_out else None}
    row.status = body.status
    row.check_in = body.check_in
    row.check_out = body.check_out
    row.office_id = body.office_id
    row.source = "manual"
    row.geofence_result = "manual"
    row.remarks = body.remarks
    row.approved_by = user.id
    if body.check_in and body.check_out:
        row.worked_minutes = int((body.check_out - body.check_in).total_seconds() // 60)
    db.flush()
    audit(db, user.id, "hr.attendance.manual", f"attendance:{row.id}",
          {"employee": emp.code, "date": str(body.date), "old": old,
           "new": {"status": body.status, "remarks": body.remarks}})
    db.commit()
    return {"id": row.id, "date": row.date, "status": row.status}


@router.post("/attendance/{attendance_id}/correction", status_code=201)
def request_correction(attendance_id: int, body: CorrectionIn, db: Session = Depends(get_db),
                       user=Depends(require("hr:attendance_self"))):
    row = db.get(Attendance, attendance_id)
    if not row:
        raise HTTPException(404, "Attendance record not found")
    me = hr_svc.employee_for_user(db, user)
    if not _can(db, user, "hr:attendance_manage") and (not me or me.id != row.employee_id):
        raise HTTPException(403, "You can only request a correction for your own attendance")
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
    default_days: Decimal = Field(default=0, ge=0)
    carry_forward: bool = False


class LeaveIn(BaseModel):
    leave_type_id: int
    date_from: date
    date_to: date
    reason: str = Field(min_length=3, max_length=300)
    document: str | None = Field(default=None, max_length=300)
    employee_id: int | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.date_to < self.date_from:
            raise ValueError("end date cannot be before start date")
        return self


@router.get("/leave/types")
def leave_types(db: Session = Depends(get_db), _=Depends(require("hr:read"))):
    return [{"id": t.id, "code": t.code, "name": t.name, "kind": t.kind,
             "requires_document": t.requires_document, "default_days": t.default_days,
             "carry_forward": t.carry_forward, "active": t.active}
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


@router.get("/leave/balances")
def leave_balances(employee_id: int | None = None, year: int | None = None,
                   db: Session = Depends(get_db), user=Depends(require("hr:read"))):
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
               db: Session = Depends(get_db), user=Depends(require("hr:read"))):
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
             "date_from": r.date_from, "date_to": r.date_to, "days": r.days,
             "reason": r.reason, "status": r.status, "remarks": r.remarks,
             "created_at": r.created_at, "decided_at": r.decided_at} for r in rows]


@router.post("/leave/applications", status_code=201)
def apply_leave(body: LeaveIn, db: Session = Depends(get_db),
                user=Depends(require("hr:attendance_self"))):
    emp = _employee_or_403(db, user, body.employee_id)
    lt = db.get(LeaveType, body.leave_type_id)
    if not lt or not lt.active:
        raise HTTPException(404, "Leave type not found")
    if lt.requires_document and not body.document:
        raise HTTPException(422, "This leave type needs a supporting document")
    days = Decimal((body.date_to - body.date_from).days + 1)
    overlap = db.scalar(select(LeaveApplication).where(
        LeaveApplication.employee_id == emp.id,
        LeaveApplication.status.in_(("pending", "approved")),
        LeaveApplication.date_from <= body.date_to,
        LeaveApplication.date_to >= body.date_from))
    if overlap:
        raise HTTPException(409, "This leave overlaps an existing application")
    bal = hr_svc.leave_balance(db, emp.id, lt.id, body.date_from.year)
    if lt.kind == "paid" and bal.entitled + bal.carried - bal.used - bal.pending < days:
        raise HTTPException(422, f"Only {bal.entitled + bal.carried - bal.used - bal.pending} "
                                 f"day(s) of {lt.code} are available")
    app = LeaveApplication(employee_id=emp.id, leave_type_id=lt.id, date_from=body.date_from,
                           date_to=body.date_to, days=days, reason=body.reason.strip(),
                           document=body.document, created_by=user.id)
    db.add(app)
    db.flush()
    bal.pending += days
    hr_svc.request_approval(
        db, record_type="hr_leave", record_id=app.id, requested_by=user.id,
        reasons=["leave"], detail={"employee_id": emp.id, "leave_type": lt.code,
                                   "days": str(days), "reason": app.reason},
        document_number=f"LV-{app.id:05d}",
        subject=f"{emp.full_name}: {lt.name}",
        requested_dates=f"{body.date_from} to {body.date_to}",
        approver_role="reporting_manager")
    audit(db, user.id, "hr.leave.apply", f"leave:{app.id}",
          {"employee": emp.code, "leave_type": lt.code, "days": str(days)})
    db.commit()
    return {"id": app.id, "status": app.status, "days": app.days}


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
            db: Session = Depends(get_db), user=Depends(require("hr:read"))):
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
class ComponentIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["earning", "deduction"]
    calc_type: Literal["fixed", "percent_basic", "percent_gross"] = "fixed"
    default_rate: Decimal = Field(default=0, ge=0)
    taxable: bool = True
    statutory: bool = False
    sort_order: int = 0


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
             "statutory": c.statutory, "active": c.active, "sort_order": c.sort_order}
            for c in db.scalars(select(SalaryComponent).order_by(SalaryComponent.sort_order)).all()]


@router.post("/salary/components", status_code=201)
def create_component(body: ComponentIn, db: Session = Depends(get_db),
                     actor=Depends(require("hr:write"))):
    if not _can(db, actor, "hr:confidential", "hr:payroll_prepare"):
        raise HTTPException(403, "Confidential HR rights are required to change salary data")
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
    # Close the previous active structure the day before the revision.
    prev = db.scalar(select(SalaryStructure).where(
        SalaryStructure.employee_id == emp.id, SalaryStructure.status == "active")
        .order_by(SalaryStructure.effective_from.desc()))
    if prev and prev.effective_from < body.effective_from:
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
    for old in list(p.entries):
        db.delete(old)
    db.flush()
    entries = payroll_svc.run_payroll(db, p)
    p.status = "under_review"
    p.prepared_by = actor.id
    p.prepared_at = datetime.now(timezone.utc)
    audit(db, actor.id, "hr.payroll.prepare", f"payroll:{p.id}",
          {"year": p.year, "month": p.month, "entries": len(entries),
           "net": str(sum((e.net for e in entries), Decimal(0)))})
    db.commit()
    return {"id": p.id, "status": p.status, "entries": len(entries),
            "net": _m(sum((e.net for e in entries), Decimal(0)))}


@router.post("/payroll/periods/{period_id}/submit")
def submit_payroll(period_id: int, db: Session = Depends(get_db),
                   actor=Depends(require("hr:payroll_prepare"))):
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status != "under_review":
        raise HTTPException(409, "Only a reviewed payroll can be submitted for approval")
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
    return Response(content=body, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="salary-slip-{emp.code}-{period.year}-{period.month:02d}.pdf"',
        "Cache-Control": "no-store"})


@router.post("/payroll/periods/{period_id}/corrections", status_code=201)
def request_payroll_correction(period_id: int, body: CorrectionIn2, db: Session = Depends(get_db),
                       actor=Depends(require("hr:payroll_prepare"))):
    p = db.get(PayrollPeriod, period_id)
    if not p:
        raise HTTPException(404, "Payroll period not found")
    if p.status in ("draft", "under_review"):
        raise HTTPException(409, "Correct the draft before it is approved")
    audit(db, actor.id, "hr.payroll.correction_request", f"payroll:{p.id}",
          {"employee_id": body.employee_id, "reason": body.reason.strip()})
    db.commit()
    return {"id": None, "status": "pending", "note": "Recorded in the audit trail. "
            "Finalised payroll is corrected through the authorised reversal workflow."}
