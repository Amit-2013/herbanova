"""Module Phase 1: database-backed roles and the employee master (FR-02).

Roles carry their permission list as JSON (module:action keys from
app/core/permissions.py). The four system roles are seeded with the frozen
baseline sets; custom roles (for example 'Accounts') are created by an
administrator through /api/roles. Roles are never deleted - users reference
them - and the last active administrator cannot be removed or demoted.

Users keep a copy of their role name for history and audit readability, but
authorisation always resolves through role_id -> Role.permissions, so a
permission change takes effect immediately on the next request.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)   # the four seeded roles
    permissions: Mapped[list] = mapped_column(JSON, default=list)     # ["product:read", ...]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    users: Mapped[list["User"]] = relationship(back_populates="role_rel")


class Employee(Base):
    """Employee master. At most one login per employee (user_id is unique);
    users and employees are deactivated, never deleted (FR-02)."""
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(60))
    designation: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(120))
    joining_date: Mapped[date | None] = mapped_column(Date)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | inactive
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    # ---- HR master (module phase 7); all optional so existing rows stay valid
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("hr_branches.id"))
    office_id: Mapped[int | None] = mapped_column(ForeignKey("hr_work_locations.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("hr_departments.id"))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("hr_shifts.id"))
    hr_admin_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    employment_type: Mapped[str | None] = mapped_column(String(30))
    work_schedule: Mapped[str | None] = mapped_column(String(80))
    date_of_exit: Mapped[date | None] = mapped_column(Date)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    probation_end_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    exit_reason: Mapped[str | None] = mapped_column(String(200))
    photo_path: Mapped[str | None] = mapped_column(String(300))
    address: Mapped[str | None] = mapped_column(String(300))
    emergency_name: Mapped[str | None] = mapped_column(String(120))
    emergency_phone: Mapped[str | None] = mapped_column(String(40))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account_no: Mapped[str | None] = mapped_column(String(30))
    bank_ifsc: Mapped[str | None] = mapped_column(String(11))
    pan: Mapped[str | None] = mapped_column(String(10))
    uan: Mapped[str | None] = mapped_column(String(20))
    esi_no: Mapped[str | None] = mapped_column(String(20))
    attendance_policy: Mapped[str | None] = mapped_column(String(80))
    leave_policy: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())
