"""Payroll calculation.

Everything is driven by configured salary components and structure lines; no
statutory rate or amount is written in this module. Approved attendance, leave
and OD are the inputs. The result is transparent: every earning and deduction
is stored as a line with its basis.
"""
from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.hr import (Attendance, PayrollEntry, PayrollEntryLine, SalaryComponent,
                         SalaryStructure)
from ..models.users import Employee
from . import hr as hr_svc

ZERO = Decimal(0)
CENT = Decimal("0.01")
PAID_STATUSES = {"present", "late", "early_departure", "od", "weekly_off", "holiday",
                 "paid_leave"}
UNPAID_STATUSES = {"absent", "unpaid_leave", "correction_pending"}
NON_PRORATED = {"INCENTIVE", "OVERTIME", "BONUS", "REIMBURSEMENT"}


def money(v) -> Decimal:
    return Decimal(v or 0).quantize(CENT, ROUND_HALF_UP)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _structure(db: Session, employee_id: int, start: date, end: date) -> SalaryStructure | None:
    rows = db.scalars(select(SalaryStructure).where(
        SalaryStructure.employee_id == employee_id,
        SalaryStructure.status == "active",
        SalaryStructure.effective_from <= end).order_by(SalaryStructure.effective_from.desc())).all()
    for row in rows:
        if row.effective_to is None or row.effective_to >= start:
            return row
    return None


def run_payroll(db: Session, period) -> list[PayrollEntry]:
    start, end = _month_bounds(period.year, period.month)
    employees = db.scalars(select(Employee).where(Employee.status == "active")).all()
    components = {c.id: c for c in db.scalars(select(SalaryComponent)).all()}
    out: list[PayrollEntry] = []
    for emp in employees:
        if emp.joining_date and emp.joining_date > end:
            continue
        if emp.date_of_exit and emp.date_of_exit < start:
            continue
        structure = _structure(db, emp.id, start, end)
        if structure is None:
            continue
        working = hr_svc.working_days(db, emp, period.year, period.month)
        working_days = Decimal(len(working))
        rows = db.scalars(select(Attendance).where(
            Attendance.employee_id == emp.id, Attendance.date >= start,
            Attendance.date <= end)).all()
        present = Decimal(0)
        paid_leave = Decimal(0)
        for a in rows:
            half_leave = a.leave_portion in ("first_half", "second_half")
            if a.status in PAID_STATUSES:
                if a.status == "paid_leave":
                    # A half-day application covers half the day; the other half
                    # is counted as present, the same default used when a part of
                    # the month has no attendance row.
                    paid_leave += Decimal("0.5") if half_leave else 1
                    if half_leave:
                        present += Decimal("0.5")
                else:
                    present += Decimal("0.5") if a.status == "half_day" else 1
            elif a.status == "half_day":
                present += Decimal("0.5")
            elif a.status == "unpaid_leave" and half_leave:
                present += Decimal("0.5")
        if not rows:
            present = working_days
        payable = min(working_days, present + paid_leave)
        lop = max(ZERO, working_days - payable)
        ratio = (payable / working_days) if working_days > 0 else ZERO

        amounts: dict[str, Decimal] = {}
        basic = ZERO
        # First pass: fixed earning basis (basic drives percentages).
        for line in structure.lines:
            comp = components.get(line.component_id)
            if comp is None or not comp.active:
                continue
            if comp.kind == "earning" and comp.code == "BASIC":
                amount = line.amount if line.amount else comp.default_rate
                basic += money(amount * ratio)
        entry = PayrollEntry(period_id=period.id, employee_id=emp.id,
                             working_days=working_days, payable_days=payable,
                             present_days=present, paid_leave_days=paid_leave,
                             lop_days=lop, status="draft")
        db.add(entry)
        db.flush()
        gross = ZERO
        for line in structure.lines:
            comp = components.get(line.component_id)
            if comp is None or not comp.active or comp.kind != "earning":
                continue
            raw = line.amount if line.amount else comp.default_rate
            pct = line.percent if line.percent is not None else comp.default_rate
            if comp.calc_type == "percent_basic":
                amount = money(basic * pct / 100)
                basis = f"{pct}% of basic {money(basic)}"
            else:
                amount = money(raw if comp.code in NON_PRORATED else raw * ratio)
                basis = f"{money(raw)} prorated {payable}/{working_days}"\
                    if comp.code not in NON_PRORATED else f"{money(raw)}"
            amounts[comp.code] = amount
            gross += amount
            db.add(PayrollEntryLine(entry_id=entry.id, component_id=comp.id, name=comp.name,
                                    kind="earning", amount=amount, basis=basis))
        deductions = ZERO
        for line in structure.lines:
            comp = components.get(line.component_id)
            if comp is None or not comp.active or comp.kind != "deduction":
                continue
            raw = line.amount if line.amount else comp.default_rate
            pct = line.percent if line.percent is not None else comp.default_rate
            if comp.calc_type == "percent_basic":
                amount = money(basic * pct / 100)
                basis = f"{pct}% of basic {money(basic)}"
            elif comp.calc_type == "percent_gross":
                amount = money(gross * pct / 100)
                basis = f"{pct}% of gross {money(gross)}"
            else:
                amount = money(raw)
                basis = f"{money(raw)} fixed"
            amounts[comp.code] = amount
            deductions += amount
            db.add(PayrollEntryLine(entry_id=entry.id, component_id=comp.id, name=comp.name,
                                    kind="deduction", amount=amount, basis=basis))
        entry.gross, entry.deductions = money(gross), money(deductions)
        entry.net = money(gross - deductions)
        entry.note = None if rows else "No attendance recorded for this month; paid days defaulted to the working days."
        out.append(entry)
    return out
