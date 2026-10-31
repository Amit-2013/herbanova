"""HR management: offices, shifts, attendance, leave, on-duty, payroll.

All tables are additive. Approved attendance/leave/OD are the only inputs to
payroll; payroll entries are unique per employee and period so a period cannot
be paid twice. Money is Numeric, never float. Rates and amounts are configured
rows, never constants in code.
"""
from datetime import date, datetime, time
from datetime import date as DateType  # the OD and attendance classes have a column named `date`
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        JSON, Numeric, String, Time, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base

MONEY = Numeric(14, 2)
HOURS = Numeric(6, 2)
LAT = Numeric(9, 6)


class Branch(Base):
    __tablename__ = "hr_branches"
    # Index names below match the ones the migrations created, so
    # `alembic revision --autogenerate` reports no drift against the live schema.
    __table_args__ = (
        UniqueConstraint("code", name="hr_branches_code_key"),
        Index("ix_hr_branches_code", "code"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="active")


class WorkLocation(Base):
    """An office or worksite. The geofence is a centre plus a radius, validated
    on the server for GPS check-ins; GPS is evidence, not proof of identity."""
    __tablename__ = "hr_work_locations"
    __table_args__ = (
        CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
                        name="ck_hr_lat"),
        CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
                        name="ck_hr_lon"),
        CheckConstraint("geofence_radius_m IS NULL OR geofence_radius_m > 0",
                        name="ck_hr_radius"),
        CheckConstraint("attendance_mode IN ('office','gps','both')", name="ck_hr_mode"),
        UniqueConstraint("code", name="hr_work_locations_code_key"),
        Index("ix_hr_work_locations_code", "code"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("hr_branches.id"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[Decimal | None] = mapped_column(LAT)
    longitude: Mapped[Decimal | None] = mapped_column(LAT)
    geofence_radius_m: Mapped[int | None] = mapped_column(Integer, default=200)
    attendance_mode: Mapped[str] = mapped_column(String(10), default="office")
    status: Mapped[str] = mapped_column(String(20), default="active")


class Shift(Base):
    __tablename__ = "hr_shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    start_time: Mapped[time] = mapped_column(Time, default=time(9, 0))
    end_time: Mapped[time] = mapped_column(Time, default=time(18, 0))
    grace_minutes: Mapped[int] = mapped_column(Integer, default=10)
    full_day_hours: Mapped[Decimal] = mapped_column(HOURS, default=Decimal("8"))
    half_day_hours: Mapped[Decimal] = mapped_column(HOURS, default=Decimal("4"))
    weekly_offs: Mapped[list] = mapped_column(JSON, default=lambda: [5, 6])  # Mon=0 .. Sun=6
    status: Mapped[str] = mapped_column(String(20), default="active")


class Holiday(Base):
    __tablename__ = "hr_holidays"
    __table_args__ = (UniqueConstraint("date", "name", name="uq_hr_holiday"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(120))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("hr_branches.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("hr_work_locations.id"))


class Department(Base):
    __tablename__ = "hr_departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Attendance(Base):
    __tablename__ = "hr_attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_hr_attendance_employee_date"),
        CheckConstraint(
            "status IN ('present','absent','half_day','weekly_off','holiday','paid_leave',"
            "'unpaid_leave','od','late','early_departure','correction_pending')",
            name="ck_hr_attendance_status"),
        CheckConstraint("source IN ('web','office','gps','manual','system')",
                        name="ck_hr_attendance_source"),
        CheckConstraint("geofence_result IN ('inside','outside','unavailable','manual','na')",
                        name="ck_hr_geofence_result"),
        # Explicit names = the names the migration created (schema parity).
        Index("ix_hr_attendance_employee", "employee_id"),
        Index("ix_hr_attendance_date", "date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="present")
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    office_id: Mapped[int | None] = mapped_column(ForeignKey("hr_work_locations.id"))
    source: Mapped[str] = mapped_column(String(10), default="web")
    latitude: Mapped[Decimal | None] = mapped_column(LAT)
    longitude: Mapped[Decimal | None] = mapped_column(LAT)
    geofence_result: Mapped[str] = mapped_column(String(12), default="na")
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_minutes: Mapped[int] = mapped_column(Integer, default=0)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    remarks: Mapped[str | None] = mapped_column(String(300))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class AttendanceCorrection(Base):
    __tablename__ = "hr_attendance_corrections"
    __table_args__ = (
        Index("ix_hr_attendance_corrections_attendance", "attendance_id"),
        Index("ix_hr_attendance_corrections_employee", "employee_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    attendance_id: Mapped[int] = mapped_column(ForeignKey("hr_attendance.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str | None] = mapped_column(String(20))
    old_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    old_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeaveType(Base):
    __tablename__ = "hr_leave_types"
    __table_args__ = (CheckConstraint("kind IN ('paid','unpaid')", name="ck_hr_leave_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10), default="paid")
    requires_document: Mapped[bool] = mapped_column(Boolean, default=False)
    default_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    carry_forward: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LeaveBalance(Base):
    __tablename__ = "hr_leave_balances"
    __table_args__ = (UniqueConstraint("employee_id", "leave_type_id", "year",
                                       name="uq_hr_leave_balance"),
                      Index("ix_hr_leave_balances_employee", "employee_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("hr_leave_types.id"))
    year: Mapped[int] = mapped_column(Integer)
    entitled: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    used: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    pending: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    carried: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)


class LeaveApplication(Base):
    __tablename__ = "hr_leave_applications"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','cancelled')",
                        name="ck_hr_leave_status"),
        CheckConstraint("date_to >= date_from", name="ck_hr_leave_dates"),
        Index("ix_hr_leave_applications_employee", "employee_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("hr_leave_types.id"))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    days: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    reason: Mapped[str] = mapped_column(String(300))
    document: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ODRequest(Base):
    __tablename__ = "hr_od_requests"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','cancelled')",
                                      name="ck_hr_od_status"),
                      Index("ix_hr_od_requests_employee", "employee_id"),
                      Index("ix_hr_od_requests_date", "date"))
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    date: Mapped[date] = mapped_column(Date)
    # nullable=True is explicit: inside this class body the attribute name `date`
    # shadows datetime.date, so the Optional annotation alone would not be read
    # as optional by SQLAlchemy and autogenerate would try to add NOT NULL.
    end_date: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    duration: Mapped[str] = mapped_column(String(20), default="full_day")
    visit_type: Mapped[str] = mapped_column(String(40))
    purpose: Mapped[str] = mapped_column(String(300))
    party_type: Mapped[str | None] = mapped_column(String(20))
    party_name: Mapped[str | None] = mapped_column(String(150))
    worksite: Mapped[str | None] = mapped_column(String(150))
    destination: Mapped[str | None] = mapped_column(String(200))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    document: Mapped[str | None] = mapped_column(String(300))
    remarks: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    regularisation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_remarks: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalWorkflow(Base):
    __tablename__ = "hr_approval_workflows"
    __table_args__ = (UniqueConstraint("request_type", "level", name="uq_hr_workflow"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    request_type: Mapped[str] = mapped_column(String(30))
    level: Mapped[int] = mapped_column(Integer, default=1)
    approver_role: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ------------------------------------------------------------------ payroll
class SalaryComponent(Base):
    __tablename__ = "hr_salary_components"
    __table_args__ = (
        CheckConstraint("kind IN ('earning','deduction')", name="ck_hr_component_kind"),
        CheckConstraint("calc_type IN ('fixed','percent_basic','percent_gross')",
                        name="ck_hr_component_calc"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))
    calc_type: Mapped[str] = mapped_column(String(20), default="fixed")
    default_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    statutory: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SalaryStructure(Base):
    __tablename__ = "hr_salary_structures"
    __table_args__ = (Index("ix_hr_salary_structures_employee", "employee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    payment_mode: Mapped[str] = mapped_column(String(20), default="bank")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["SalaryStructureLine"]] = relationship(
        back_populates="structure", lazy="selectin", cascade="all, delete-orphan")


class SalaryStructureLine(Base):
    __tablename__ = "hr_salary_structure_lines"
    __table_args__ = (UniqueConstraint("structure_id", "component_id",
                                       name="uq_hr_structure_component"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    structure_id: Mapped[int] = mapped_column(ForeignKey("hr_salary_structures.id"))
    component_id: Mapped[int] = mapped_column(ForeignKey("hr_salary_components.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    structure: Mapped[SalaryStructure] = relationship(back_populates="lines")


class PayrollPeriod(Base):
    __tablename__ = "hr_payroll_periods"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_hr_payroll_period"),
        CheckConstraint("status IN ('draft','under_review','approved','processed','paid')",
                        name="ck_hr_payroll_period_status"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_hr_payroll_month"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    prepared_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(300))
    entries: Mapped[list["PayrollEntry"]] = relationship(
        back_populates="period", lazy="selectin", cascade="all, delete-orphan")


class PayrollEntry(Base):
    __tablename__ = "hr_payroll_entries"
    __table_args__ = (UniqueConstraint("period_id", "employee_id", name="uq_hr_payroll_entry"),
                      Index("ix_hr_payroll_entries_employee", "employee_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("hr_payroll_periods.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    working_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    payable_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    present_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    paid_leave_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    lop_days: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    gross: Mapped[Decimal] = mapped_column(MONEY, default=0)
    deductions: Mapped[Decimal] = mapped_column(MONEY, default=0)
    net: Mapped[Decimal] = mapped_column(MONEY, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    note: Mapped[str | None] = mapped_column(String(300))
    period: Mapped[PayrollPeriod] = relationship(back_populates="entries")
    lines: Mapped[list["PayrollEntryLine"]] = relationship(
        back_populates="entry", lazy="selectin", cascade="all, delete-orphan")


class PayrollEntryLine(Base):
    __tablename__ = "hr_payroll_entry_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("hr_payroll_entries.id"))
    component_id: Mapped[int | None] = mapped_column(ForeignKey("hr_salary_components.id"))
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    basis: Mapped[str | None] = mapped_column(String(200))
    entry: Mapped[PayrollEntry] = relationship(back_populates="lines")


class PayrollCorrection(Base):
    __tablename__ = "hr_payroll_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("hr_payroll_periods.id"))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(300))
    old_net: Mapped[Decimal | None] = mapped_column(MONEY)
    new_net: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
