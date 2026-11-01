"""HR report definitions, shared by the API and the scheduled HR pack.

Every report returns the same shape: a title, the filters used, the table
columns, the rows and a list of gaps. A gap is a fact the data cannot show
(no attendance rows, no payroll period, nobody in scope) and is rendered as
"No data yet" rather than filled with invented zeroes.

Money is formatted here, so JSON, CSV and PDF always show the same figure.
"""
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
import csv
from xml.sax.saxutils import escape

from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import is_admin, role_permissions
from ..models.hr import (Attendance, Branch, Department, EmployeeDocument,
                         LeaveBalance, LeaveType, PayrollEntry, PayrollPeriod)
from ..models.users import Employee
from . import hr as hr_svc

CENT = Decimal("0.01")
ONE_DP = Decimal("0.1")

REPORTS: tuple[tuple[str, str], ...] = (
    ("headcount", "Headcount"),
    ("joiners-leavers", "Joiners and leavers"),
    ("attendance-summary", "Attendance summary"),
    ("late-absentee", "Late and absentee"),
    ("leave-balance", "Leave balances"),
    ("department-cost", "Department cost"),
    ("document-expiry", "Document expiry"),
)
REPORT_TITLES = dict(REPORTS)

HEADCOUNT_COLUMNS = [
    ("code", "Employee code"), ("full_name", "Name"), ("department", "Department"),
    ("designation", "Designation"), ("branch", "Branch"),
    ("employment_type", "Employment type"), ("joining_date", "Joined on"),
    ("status", "Status"),
]
MOVEMENT_COLUMNS = [
    ("event", "Event"), ("event_date", "Date"), ("code", "Employee code"),
    ("full_name", "Name"), ("department", "Department"),
    ("designation", "Designation"), ("reason", "Reason / exit reason"),
]
ATTENDANCE_COLUMNS = [
    ("code", "Employee code"), ("full_name", "Name"), ("department", "Department"),
    ("present", "Present"), ("absent", "Absent"), ("late", "Late"),
    ("half_day", "Half day"), ("leave", "Leave"), ("od", "On duty"),
    ("late_minutes", "Late minutes"),
]
LATE_COLUMNS = [
    ("code", "Employee code"), ("full_name", "Name"), ("department", "Department"),
    ("late_days", "Late days"), ("late_minutes", "Late minutes"),
    ("absent_days", "Absent days"), ("early_days", "Early departures"),
]
BALANCE_COLUMNS = [
    ("code", "Employee code"), ("full_name", "Name"), ("department", "Department"),
    ("leave_type", "Leave type"), ("entitled", "Entitled"), ("carried", "Carried"),
    ("used", "Used"), ("pending", "Pending"), ("available", "Available"),
]
COST_COLUMNS = [
    ("department", "Department"), ("employees", "Employees"), ("gross", "Gross"),
    ("deductions", "Deductions"), ("net", "Net"),
]
DOCUMENT_COLUMNS = [
    ("code", "Employee code"), ("full_name", "Name"), ("doc_type", "Document type"),
    ("title", "Title"), ("expires_on", "Expires on"), ("days_left", "Days left"),
]


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(CENT))


def _days(value) -> str:
    return str(Decimal(value or 0).quantize(ONE_DP))


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _range(first: date, last: date) -> tuple[date, date]:
    if last < first:
        raise HTTPException(422, "The range end cannot be before its start")
    if (last - first).days > 366:
        raise HTTPException(422, "Choose a range of at most 366 days")
    return first, last


def _scoped_employees(db: Session, user) -> list[Employee]:
    scope = hr_svc.scoped_employee_ids(db, user) if user is not None else None
    rows = db.scalars(select(Employee).order_by(Employee.code)).all()
    return [e for e in rows if scope is None or e.id in scope]


def _departments(db: Session) -> dict[int, str]:
    return {d.id: d.name for d in db.scalars(select(Department)).all()}


def _department(emp: Employee, names: dict[int, str]) -> str:
    return names.get(emp.department_id) or emp.department or "Unassigned"


def _headcount(db, user, *, from_date, to_date, year, month, days):
    as_of = to_date or hr_svc.business_today()
    emps = _scoped_employees(db, user)
    roster = [e for e in emps
              if (e.joining_date is None or e.joining_date <= as_of)
              and (e.date_of_exit is None or e.date_of_exit >= as_of)]
    names = _departments(db)
    branches = {b.id: b.name for b in db.scalars(select(Branch)).all()}
    rows = [{"code": e.code, "full_name": e.full_name,
             "department": _department(e, names), "designation": e.designation or "",
             "employment_type": e.employment_type or "",
             "branch": branches.get(e.branch_id, ""),
             "joining_date": _iso(e.joining_date),
             "status": e.status} for e in roster]
    by_department: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for row in rows:
        by_department[row["department"]] = by_department.get(row["department"], 0) + 1
        key = row["employment_type"] or "Not recorded"
        by_type[key] = by_type.get(key, 0) + 1
    summary = {"as_of": as_of.isoformat(), "headcount": len(rows),
               "by_department": [{"department": k, "employees": v}
                                 for k, v in sorted(by_department.items())],
               "by_employment_type": [{"type": k, "employees": v}
                                      for k, v in sorted(by_type.items())]}
    gaps = [] if rows else ["No employees are on the rolls on this date."]
    filters = {"as_of": as_of.isoformat()}
    return "Headcount", filters, HEADCOUNT_COLUMNS, rows, summary, gaps


def _joiners_leavers(db, user, *, from_date, to_date, year, month, days):
    last = to_date or hr_svc.business_today()
    first = from_date or date(last.year, 1, 1)
    first, last = _range(first, last)
    emps = _scoped_employees(db, user)
    names = _departments(db)
    joiners = [e for e in emps if e.joining_date and first <= e.joining_date <= last]
    leavers = [e for e in emps if e.date_of_exit and first <= e.date_of_exit <= last]
    opening = [e for e in emps if e.joining_date and e.joining_date <= first
               and (e.date_of_exit is None or e.date_of_exit >= first)]
    rows = []
    for e in sorted(joiners, key=lambda x: x.joining_date):
        rows.append({"event": "Joiner", "event_date": _iso(e.joining_date),
                     "code": e.code, "full_name": e.full_name,
                     "department": _department(e, names),
                     "designation": e.designation or "", "reason": ""})
    for e in sorted(leavers, key=lambda x: x.date_of_exit):
        rows.append({"event": "Leaver", "event_date": _iso(e.date_of_exit),
                     "code": e.code, "full_name": e.full_name,
                     "department": _department(e, names),
                     "designation": e.designation or "", "reason": e.exit_reason or ""})
    attrition = round(len(leavers) * 100 / len(opening), 1) if opening else None
    summary = {"from_date": first.isoformat(), "to_date": last.isoformat(),
               "joiners": len(joiners), "leavers": len(leavers),
               "opening_headcount": len(opening), "attrition_pct": attrition}
    gaps = [] if rows else ["No joiners or leavers in this range."]
    filters = {"from_date": first.isoformat(), "to_date": last.isoformat()}
    return ("Joiners and leavers", filters, MOVEMENT_COLUMNS, rows, summary, gaps)


def _attendance_rows(db, emps, first: date, last: date) -> list[Attendance]:
    ids = {e.id for e in emps}
    return db.scalars(select(Attendance).where(
        Attendance.employee_id.in_(ids or {-1}),
        Attendance.date >= first, Attendance.date <= last)).all()


def _attendance_summary(db, user, *, from_date, to_date, year, month, days):
    last = to_date or hr_svc.business_today()
    first = from_date or last.replace(day=1)
    first, last = _range(first, last)
    emps = _scoped_employees(db, user)
    names = _departments(db)
    rows_by_emp = {e.id: e for e in emps}
    buckets: dict[int, dict] = {}
    for att in _attendance_rows(db, emps, first, last):
        b = buckets.setdefault(att.employee_id, {
            "present": 0, "absent": 0, "late": 0, "half_day": 0, "leave": 0,
            "od": 0, "late_minutes": 0})
        status = att.status
        if status == "present":
            b["present"] += 1
        elif status == "late":
            b["late"] += 1
        elif status == "absent":
            b["absent"] += 1
        elif status == "half_day":
            b["half_day"] += 1
        elif status in ("paid_leave", "unpaid_leave"):
            b["leave"] += 1
        elif status == "od":
            b["od"] += 1
        b["late_minutes"] += att.late_minutes or 0
    rows = []
    for emp_id, b in buckets.items():
        e = rows_by_emp[emp_id]
        rows.append({"code": e.code, "full_name": e.full_name,
                     "department": _department(e, names), **b})
    rows.sort(key=lambda r: (r["code"]))
    gaps = []
    if not rows:
        gaps.append("No attendance rows in this range.")
    else:
        missing = len([e for e in emps if e.status == "active" and e.id not in buckets])
        if missing:
            gaps.append(f"{missing} active employee(s) have no attendance rows in this range.")
    summary = {"from_date": first.isoformat(), "to_date": last.isoformat(),
               "employees_with_rows": len(rows),
               "present_days": sum(r["present"] for r in rows),
               "absent_days": sum(r["absent"] for r in rows),
               "late_days": sum(r["late"] for r in rows),
               "leave_days": sum(r["leave"] for r in rows)}
    filters = {"from_date": first.isoformat(), "to_date": last.isoformat()}
    return ("Attendance summary", filters, ATTENDANCE_COLUMNS, rows, summary, gaps)


def _late_absentee(db, user, *, from_date, to_date, year, month, days):
    last = to_date or hr_svc.business_today()
    first = from_date or last.replace(day=1)
    first, last = _range(first, last)
    emps = _scoped_employees(db, user)
    names = _departments(db)
    by_emp = {e.id: e for e in emps}
    buckets: dict[int, dict] = {}
    for att in _attendance_rows(db, emps, first, last):
        late = att.status == "late" or (att.late_minutes or 0) > 0
        if not (late or att.status == "absent" or att.status == "early_departure"):
            continue
        b = buckets.setdefault(att.employee_id, {"late_days": 0, "late_minutes": 0,
                                                 "absent_days": 0, "early_days": 0})
        if late:
            b["late_days"] += 1
        if att.status == "absent":
            b["absent_days"] += 1
        if att.status == "early_departure":
            b["early_days"] += 1
        b["late_minutes"] += att.late_minutes or 0
    rows = [{"code": by_emp[i].code, "full_name": by_emp[i].full_name,
             "department": _department(by_emp[i], names), **b}
            for i, b in buckets.items()]
    rows.sort(key=lambda r: (-r["absent_days"], -r["late_minutes"], r["code"]))
    gaps = [] if rows else ["No late, absent or early-departure rows in this range."]
    summary = {"from_date": first.isoformat(), "to_date": last.isoformat(),
               "flagged_employees": len(rows),
               "absent_days": sum(r["absent_days"] for r in rows),
               "late_days": sum(r["late_days"] for r in rows),
               "late_minutes": sum(r["late_minutes"] for r in rows)}
    filters = {"from_date": first.isoformat(), "to_date": last.isoformat()}
    return ("Late and absentee", filters, LATE_COLUMNS, rows, summary, gaps)


def _leave_balance(db, user, *, from_date, to_date, year, month, days):
    roll = year or hr_svc.business_today().year
    emps = _scoped_employees(db, user)
    by_emp = {e.id: e for e in emps}
    names = _departments(db)
    types = {t.id: t for t in db.scalars(select(LeaveType)).all()}
    balances = db.scalars(select(LeaveBalance).where(
        LeaveBalance.year == roll,
        LeaveBalance.employee_id.in_(set(by_emp) or {-1}))).all()
    rows = []
    for bal in balances:
        e = by_emp.get(bal.employee_id)
        if e is None:
            continue
        t = types.get(bal.leave_type_id)
        available = bal.entitled + bal.carried - bal.used - bal.pending
        rows.append({"code": e.code, "full_name": e.full_name,
                     "department": _department(e, names),
                     "leave_type": t.name if t else "Unknown",
                     "entitled": _days(bal.entitled), "carried": _days(bal.carried),
                     "used": _days(bal.used), "pending": _days(bal.pending),
                     "available": _days(available)})
    rows.sort(key=lambda r: (r["code"], r["leave_type"]))
    gaps = []
    if not rows:
        gaps.append(f"No leave balances have been set for {roll}.")
    else:
        missing = len([e for e in emps if e.status == "active" and e.id not in
                       {b.employee_id for b in balances}])
        if missing:
            gaps.append(f"{missing} active employee(s) have no leave balance for {roll}.")
    negative = sum(1 for r in rows if Decimal(r["available"]) < 0)
    summary = {"year": roll, "rows": len(rows), "negative_balances": negative}
    filters = {"year": roll}
    return ("Leave balances", filters, BALANCE_COLUMNS, rows, summary, gaps)


def _department_cost(db, user, *, from_date, to_date, year, month, days):
    if user is not None and not (is_admin(db, user) or
                                 role_permissions(db, user) & {"hr:confidential",
                                                               "hr:payroll_prepare"}):
        raise HTTPException(403, "Salary cost is confidential; your role cannot open it")
    latest = db.scalars(select(PayrollPeriod)
                        .order_by(PayrollPeriod.year.desc(),
                                  PayrollPeriod.month.desc())).first()
    if year is None and month is None and latest is not None:
        year, month = latest.year, latest.month
    else:
        year = year or hr_svc.business_today().year
        month = month or hr_svc.business_today().month
    if not 1 <= month <= 12:
        raise HTTPException(422, "Month must be between 1 and 12")
    period = db.scalar(select(PayrollPeriod).where(PayrollPeriod.year == year,
                                                   PayrollPeriod.month == month))
    filters = {"year": year, "month": month}
    if period is None:
        return ("Department cost", filters, COST_COLUMNS, [],
                {"year": year, "month": month, "gross": "0.00", "deductions": "0.00",
                 "net": "0.00", "employees": 0},
                [f"No payroll period exists for {year}-{month:02d}."])
    emps = {e.id: e for e in _scoped_employees(db, user)}
    names = _departments(db)
    entries = [e for e in db.scalars(select(PayrollEntry).where(
        PayrollEntry.period_id == period.id)).all() if e.employee_id in emps]
    buckets: dict[str, dict] = {}
    for entry in entries:
        dept = _department(emps[entry.employee_id], names)
        b = buckets.setdefault(dept, {"employees": 0, "gross": Decimal(0),
                                      "deductions": Decimal(0), "net": Decimal(0)})
        b["employees"] += 1
        b["gross"] += entry.gross or 0
        b["deductions"] += entry.deductions or 0
        b["net"] += entry.net or 0
    rows = [{"department": dept, "employees": b["employees"],
             "gross": _money(b["gross"]), "deductions": _money(b["deductions"]),
             "net": _money(b["net"])} for dept, b in sorted(buckets.items())]
    total_gross = sum(Decimal(r["gross"]) for r in rows)
    total_ded = sum(Decimal(r["deductions"]) for r in rows)
    total_net = sum(Decimal(r["net"]) for r in rows)
    gaps = []
    if not rows:
        gaps.append(f"Payroll for {year}-{month:02d} has no entries in your scope.")
    if period.status == "draft":
        gaps.append(f"Payroll for {year}-{month:02d} is still a draft; figures can change.")
    missing = len([e for e in emps.values() if e.status == "active"
                   and e.id not in {x.employee_id for x in entries}])
    if rows and missing:
        gaps.append(f"{missing} active employee(s) have no payroll entry in this period.")
    summary = {"year": year, "month": month, "period_status": period.status,
               "employees": len(entries), "gross": _money(total_gross),
               "deductions": _money(total_ded), "net": _money(total_net)}
    return ("Department cost", filters, COST_COLUMNS, rows, summary, gaps)


def _document_expiry(db, user, *, from_date, to_date, year, month, days):
    window = max(1, min(days or 60, 365))
    today = hr_svc.business_today()
    last = today + timedelta(days=window)
    emps = {e.id: e for e in _scoped_employees(db, user)}
    documents = db.scalars(select(EmployeeDocument).where(
        EmployeeDocument.status == "active",
        EmployeeDocument.expires_on.is_not(None),
        EmployeeDocument.expires_on >= today,
        EmployeeDocument.expires_on <= last,
        EmployeeDocument.employee_id.in_(set(emps) or {-1}))
        .order_by(EmployeeDocument.expires_on)).all()
    rows = []
    for doc in documents:
        e = emps[doc.employee_id]
        rows.append({"code": e.code, "full_name": e.full_name,
                     "doc_type": doc.doc_type, "title": doc.title,
                     "expires_on": _iso(doc.expires_on),
                     "days_left": (doc.expires_on - today).days})
    gaps = [] if rows else [f"No active documents expire within {window} days."]
    summary = {"as_of": today.isoformat(), "window_days": window, "documents": len(rows)}
    filters = {"as_of": today.isoformat(), "days": window}
    return ("Document expiry", filters, DOCUMENT_COLUMNS, rows, summary, gaps)


BUILDERS = {
    "headcount": _headcount,
    "joiners-leavers": _joiners_leavers,
    "attendance-summary": _attendance_summary,
    "late-absentee": _late_absentee,
    "leave-balance": _leave_balance,
    "department-cost": _department_cost,
    "document-expiry": _document_expiry,
}


def build_report(db: Session, key: str, user=None, *, from_date: date | None = None,
                 to_date: date | None = None, year: int | None = None,
                 month: int | None = None, days: int | None = 60) -> dict:
    builder = BUILDERS.get(key)
    if builder is None:
        raise HTTPException(404, f"Unknown HR report: {key}")
    title, filters, columns, rows, summary, gaps = builder(
        db, user, from_date=from_date, to_date=to_date, year=year, month=month,
        days=days)
    return {"key": key, "title": title, "filters": filters,
            "columns": [{"key": k, "label": v} for k, v in columns],
            "rows": rows, "summary": summary, "gaps": gaps,
            "no_data": not rows}


def to_csv(report: dict) -> bytes:
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow([c["label"] for c in report["columns"]])
    for row in report["rows"]:
        writer.writerow([row.get(c["key"], "") for c in report["columns"]])
    return out.getvalue().encode("utf-8")


def _summary_line(report: dict) -> str:
    parts = []
    for key, value in report["summary"].items():
        if isinstance(value, (list, dict)):
            continue
        parts.append(f"{key.replace('_', ' ')}: {value if value is not None else 'n/a'}")
    return "; ".join(parts)


def to_pdf(report: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=report["title"])
    styles = getSampleStyleSheet()
    small = ParagraphStyle("cell", parent=styles["Normal"], fontSize=7.5, leading=9)
    small_head = ParagraphStyle("cellhead", parent=small, fontName="Helvetica-Bold")
    story = [Paragraph(escape(report["title"]), styles["Title"]),
             Paragraph(escape(_summary_line(report)), styles["Normal"])]
    filters = ", ".join(f"{k}: {v}" for k, v in report["filters"].items())
    if filters:
        story.append(Paragraph(escape(filters), small))
    story.append(Spacer(1, 4 * mm))
    data = [[Paragraph(escape(c["label"]), small_head) for c in report["columns"]]]
    for row in report["rows"]:
        data.append([Paragraph(escape(str(row.get(c["key"], ""))), small)
                     for c in report["columns"]])
    if len(data) == 1:
        story.append(Paragraph("No data yet.", styles["Normal"]))
    else:
        width = (doc.width) / len(report["columns"])
        table = Table(data, colWidths=[width] * len(report["columns"]), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f0")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c4be")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8faf9")]),
        ]))
        story.append(table)
    for gap in report["gaps"]:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("Gap: " + escape(gap), small))
    doc.build(story)
    return buffer.getvalue()
