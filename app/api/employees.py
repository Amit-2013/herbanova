"""Employee master (FR-02, AUD-025).

Employees are deactivated, never deleted, so history stays intact. At most one
login per employee (users.employee_id is unique); the login is created or
linked through /api/users, not here.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.users import Employee
from ..services.audit import audit

router = APIRouter(prefix="/api/employees", tags=["employees"])


class EmployeeIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    full_name: str = Field(min_length=2, max_length=120)
    department: str | None = Field(default=None, max_length=60)
    designation: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    joining_date: date | None = None
    manager_id: int | None = None

    @field_validator("code")
    @classmethod
    def norm_code(cls, v): return v.strip().upper()

    @field_validator("email")
    @classmethod
    def check_email(cls, v):
        if v and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("invalid email address")
        return v


class EmployeePatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    department: str | None = Field(default=None, max_length=60)
    designation: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    joining_date: date | None = None
    manager_id: int | None = None
    status: str | None = None          # active | inactive


class EmployeeOut(BaseModel):
    id: int
    code: str
    full_name: str
    department: str | None
    designation: str | None
    phone: str | None
    email: str | None
    joining_date: date | None
    manager_id: int | None
    status: str
    user_id: int | None
    username: str | None = None
    model_config = {"from_attributes": True}


def _with_username(db: Session, e: Employee) -> EmployeeOut:
    out = EmployeeOut.model_validate(e)
    from ..models.core import User
    # The login link is stored on both sides; read the user side too so an
    # older one-way link still shows as linked and is never offered as free.
    user = (db.get(User, e.user_id) if e.user_id
            else db.scalar(select(User).where(User.employee_id == e.id)))
    if user:
        out.user_id = user.id
        out.username = user.username
    return out


@router.get("", response_model=list[EmployeeOut])
def list_employees(db: Session = Depends(get_db), _=Depends(require("employee:read"))):
    rows = db.scalars(select(Employee).order_by(Employee.code)).all()
    return [_with_username(db, e) for e in rows]


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, db: Session = Depends(get_db),
                 _=Depends(require("employee:read"))):
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    return _with_username(db, e)


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeIn, db: Session = Depends(get_db),
                    actor=Depends(require("employee:write"))):
    if body.manager_id and not db.get(Employee, body.manager_id):
        raise HTTPException(404, "Manager not found")
    e = Employee(**body.model_dump())
    db.add(e)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Employee code already exists")
    audit(db, actor.id, "employee.create", f"employee:{e.id}",
          {"code": e.code, "full_name": e.full_name})
    db.commit()
    return _with_username(db, e)


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, body: EmployeePatch, db: Session = Depends(get_db),
                    actor=Depends(require("employee:write"))):
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("status") not in (None, "active", "inactive"):
        raise HTTPException(422, "status must be active or inactive")
    if data.get("manager_id"):
        if not db.get(Employee, data["manager_id"]):
            raise HTTPException(404, "Manager not found")
        if data["manager_id"] == e.id:
            raise HTTPException(422, "An employee cannot report to themselves")
    changed = {k: v for k, v in data.items() if getattr(e, k) != v}
    for k, v in changed.items():
        setattr(e, k, v)
    if changed:
        audit(db, actor.id, "employee.update", f"employee:{e.id}",
              {"code": e.code, **{k: str(v) for k, v in changed.items()}})
    db.commit()
    return _with_username(db, e)
