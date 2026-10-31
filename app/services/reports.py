"""Central reporting service for Herbanova.

Reports are read-only. This module does not modify business transactions,
inventory, accounting entries, permissions, or database schema.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.core import (
    ApprovalRequest,
    Batch,
    Distributor,
    Invoice,
    InvoiceLine,
    Lead,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    StockMovement,
)
from ..models.accounts import Payment
from ..models.hr import (
    Attendance,
    AttendanceCorrection,
    Branch,
    Department,
    Holiday,
    LeaveApplication,
    LeaveBalance,
    LeaveType,
    ODRequest,
    PayrollCorrection,
    PayrollEntry,
    PayrollEntryLine,
    PayrollPeriod,
    SalaryComponent,
)
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine, Supplier
from ..models.users import Employee
from . import ledger


# Catalog tuple:
# (title, description, kind, required_permission, primary_table, category)
CATALOG = {
    "stock": (
        "Stock on Hand", "Current stock by product and batch.",
        "snapshot", "stock:read", "stock", "Inventory Reports",
    ),
    "sales": (
        "Sales Orders", "Sales order activity for the selected period.",
        "period", "sales:read", "sales_orders", "Sales Reports",
    ),
    "invoices": (
        "Sales Invoice Register", "Issued and cancelled sales invoices.",
        "period", "sales:read", "invoices", "Sales Reports",
    ),
    "leads": (
        "Lead Register", "Lead records created during the selected period.",
        "period", "sales:read", "leads", "Lead & Follow-up Reports",
    ),
    "purchases": (
        "Purchase Orders", "Purchase order activity for the selected period.",
        "period", "stock:read", "purchase_orders", "Purchase Reports",
    ),
    "goods_receipts": (
        "Goods Receipt Register", "Goods receipts recorded during the selected period.",
        "period", "stock:read", "goods_receipts", "Purchase Reports",
    ),
    "suppliers": (
        "Supplier Register", "Supplier master records.",
        "snapshot", "supplier:read", "suppliers", "Supplier & Distributor Reports",
    ),
    "distributors": (
        "Distributor Register", "Distributor master records.",
        "snapshot", "sales:read", "distributors", "Supplier & Distributor Reports",
    ),
    "receivables": (
        "Receivables", "Outstanding issued sales invoices.",
        "snapshot", "accounts:read", "receivables", "Receivables",
    ),
    "receivables_ageing": (
        "Receivables Ageing", "Outstanding invoice ageing as of the report date.",
        "snapshot", "accounts:read", "receivables_ageing", "Receivables",
    ),
    "payables": (
        "Payables", "Received purchase value less recorded payments.",
        "snapshot", "accounts:read", "payables", "Payables",
    ),
    "gst_register": (
        "GST Outward Register", "Outward sales tax register; not a statutory filing export.",
        "period", "tax:read", "gst_register", "GST & Tax Reports",
    ),
    "trial_balance": (
        "Trial Balance", "Accounting balances and reconciliation checks.",
        "snapshot", "accounts:read", "trial_balance", "Accounting & Finance",
    ),
    "hr_employee_master": (
        "Employee Master", "Employee directory without confidential bank and identity fields.",
        "snapshot", "hr:reports", "employees", "Employee Reports",
    ),
    "hr_attendance": (
        "Attendance Register", "Employee attendance for the selected period.",
        "period", "hr:reports", "attendance", "Attendance Reports",
    ),
    "hr_leave": (
        "Leave Register", "Leave applications and their approval status.",
        "period", "hr:reports", "leave", "Leave and OD Reports",
    ),
    "hr_od": (
        "On Duty Register", "On-duty requests and their approval status.",
        "period", "hr:reports", "od_requests", "Leave and OD Reports",
    ),
    "hr_payroll": (
        "Payroll Register", "Payroll entries for the selected period.",
        "period", "hr:reports", "payroll", "Payroll Reports",
    ),
    "hr_approvals": (
        "Approval Register", "Approval requests and their status.",
        "period", "hr:reports", "approvals", "Approval & Audit Reports",
    ),
    "hr_joining_exit": (
        "Joining and Exit Register", "Employees joining or exiting during the selected period.",
        "period", "hr:reports", "employees", "Employee Reports",
    ),
    "hr_late_arrival": (
        "Late Arrival Register", "Attendance records with late arrival minutes.",
        "period", "hr:reports", "late_arrivals", "Attendance Reports",
    ),
    "hr_missing_punch": (
        "Missing Punch Register", "Attendance records missing check-in or check-out.",
        "period", "hr:reports", "missing_punches", "Attendance Reports",
    ),
    "hr_leave_balance": (
        "Leave Balances", "Employee leave entitlement, usage, pending requests, and carry-forward.",
        "period", "hr:reports", "leave_balances", "Leave and OD Reports",
    ),
    "hr_payroll_deductions": (
        "Payroll Deductions", "Payroll deduction components and totals.",
        "period", "hr:reports", "payroll_deductions", "Payroll Reports",
    ),
    "hr_approval_turnaround": (
        "Approval Turnaround", "Approval requests with request and decision timestamps.",
        "period", "hr:reports", "approval_turnaround", "Approval & Audit Reports",
    ),
}

FILTER_KEYS = {
    "hr_employee_master": ["employee_id", "department", "branch_id"],
    "hr_joining_exit": ["employee_id", "department", "branch_id"],
    "hr_attendance": ["employee_id", "department", "branch_id"],
    "hr_late_arrival": ["employee_id", "department", "branch_id"],
    "hr_missing_punch": ["employee_id", "department", "branch_id"],
    "hr_leave": ["employee_id", "department", "branch_id"],
    "hr_od": ["employee_id", "department", "branch_id"],
    "hr_payroll": ["employee_id", "department", "branch_id"],
    "hr_leave_balance": ["employee_id", "department", "branch_id"],
    "hr_payroll_deductions": ["employee_id", "department", "branch_id"],
    "hr_approval_turnaround": [],
    "hr_approvals": [],
    "stock": [],
    "sales": [],
    "invoices": [],
    "leads": [],
    "purchases": [],
    "goods_receipts": [],
    "suppliers": [],
    "distributors": [],
    "receivables": [],
    "receivables_ageing": [],
    "payables": [],
    "gst_register": [],
    "trial_balance": [],
}


def _iso(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _decimal(value):
    try:
        return Decimal(str(value or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except Exception:
        return Decimal("0.00")


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _columns(rows, preferred=None):
    keys = list(preferred or [])
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return [
        {
            "key": key,
            "label": key.replace("_", " ").strip().title(),
            "type": "number" if key in {
                "amount", "gross", "deductions", "net", "qty", "quantity",
                "on_hand", "late_minutes", "worked_minutes", "days",
                "entitled", "used", "pending", "carried", "outstanding",
                "received", "paid", "taxable_value", "tax_total", "grand_total",
                "cgst_total", "sgst_total", "igst_total", "cess_total",
                "gross_total", "discount_total", "received_value",
            } else "text",
        }
        for key in keys
    ]


def _table(key, title, rows, preferred=None, totals=None):
    clean_rows = [
        {k: _iso(v) for k, v in row.items()}
        for row in rows
    ]
    return {
        "key": key,
        "title": title,
        "columns": _columns(clean_rows, preferred),
        "rows": clean_rows,
        "totals": totals,
    }


def _check(name, label, report_value, record_label, record_value, unit="records"):
    ok = report_value == record_value
    return {
        "name": name,
        "report_label": label,
        "report_value": _num(report_value),
        "record_label": record_label,
        "record_value": _num(record_value),
        "unit": unit,
        "ok": bool(ok),
    }


def _envelope(key, date_from, date_to, tables, checks=None, limitations=None):
    meta = CATALOG[key]
    check_list = list(checks or [])
    return {
        "key": key,
        "title": meta[0],
        "category": meta[5],
        "kind": meta[2],
        "primary_table": tables[0]["key"] if tables else meta[4],
        "period_from": date_from,
        "period_to": date_to,
        "as_at": date.today(),
        "tables": tables,
        "checks": check_list,
        "limitations": list(limitations or []),
        "reconciled": all(c["ok"] for c in check_list),
    }


def _in_period(value, date_from, date_to):
    if value is None:
        return False
    day = value.date() if isinstance(value, datetime) else value
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def _employees(db, filters):
    query = db.query(Employee)
    employee_id = filters.get("employee_id")
    department = filters.get("department")
    branch_id = filters.get("branch_id")

    if employee_id is not None:
        query = query.filter(Employee.id == employee_id)
    if department:
        query = query.filter(func.lower(Employee.department) == department.lower())
    if branch_id is not None:
        query = query.filter(Employee.branch_id == branch_id)

    return query.order_by(Employee.code, Employee.id).all()


def _employee_rows(db, filters):
    rows = []
    for e in _employees(db, filters):
        branch = db.get(Branch, e.branch_id) if e.branch_id else None
        rows.append({
            "employee_id": e.id,
            "code": e.code,
            "full_name": e.full_name,
            "department": e.department,
            "designation": e.designation,
            "phone": e.phone,
            "email": e.email,
            "joining_date": e.joining_date,
            "date_of_exit": getattr(e, "date_of_exit", None),
            "status": e.status,
            "branch_id": e.branch_id,
            "branch": branch.name if branch else None,
        })
    return rows


def _hr_attendance_rows(db, filters, date_from, date_to):
    employee_rows = _employees(db, filters)
    ids = [e.id for e in employee_rows]
    if not ids:
        return []
    query = db.query(Attendance).filter(Attendance.employee_id.in_(ids))
    if date_from:
        query = query.filter(Attendance.date >= date_from)
    if date_to:
        query = query.filter(Attendance.date <= date_to)
    query = query.order_by(Attendance.date, Attendance.employee_id)

    employees = {e.id: e for e in employee_rows}
    rows = []
    for a in query.all():
        e = employees.get(a.employee_id)
        rows.append({
            "attendance_id": a.id,
            "employee_id": a.employee_id,
            "code": e.code if e else None,
            "full_name": e.full_name if e else None,
            "department": e.department if e else None,
            "branch_id": e.branch_id if e else None,
            "date": a.date,
            "status": a.status,
            "check_in": a.check_in,
            "check_out": a.check_out,
            "late_minutes": a.late_minutes,
            "early_minutes": a.early_minutes,
            "worked_minutes": a.worked_minutes,
            "source": a.source,
            "remarks": a.remarks,
        })
    return rows


def _payroll_rows(db, filters, date_from, date_to):
    employees = _employees(db, filters)
    ids = [e.id for e in employees]
    if not ids:
        return []
    employee_map = {e.id: e for e in employees}
    query = db.query(PayrollEntry).filter(PayrollEntry.employee_id.in_(ids))
    rows = []
    for entry in query.all():
        period = db.get(PayrollPeriod, entry.period_id)
        if not period:
            continue
        period_date = date(int(period.year), int(period.month), 1)
        if not _in_period(period_date, date_from, date_to):
            continue
        employee = employee_map.get(entry.employee_id)
        rows.append({
            "payroll_entry_id": entry.id,
            "period_id": entry.period_id,
            "year": period.year,
            "month": period.month,
            "employee_id": entry.employee_id,
            "code": employee.code if employee else None,
            "full_name": employee.full_name if employee else None,
            "department": employee.department if employee else None,
            "branch_id": employee.branch_id if employee else None,
            "working_days": entry.working_days,
            "payable_days": entry.payable_days,
            "present_days": entry.present_days,
            "paid_leave_days": entry.paid_leave_days,
            "lop_days": entry.lop_days,
            "gross": _num(_decimal(entry.gross)),
            "deductions": _num(_decimal(entry.deductions)),
            "net": _num(_decimal(entry.net)),
            "status": entry.status,
        })
    return sorted(rows, key=lambda r: (r["year"], r["month"], r["code"] or ""))


def _empty_reconciled(key, date_from, date_to, table):
    return _envelope(
        key, date_from, date_to, [table],
        [_check("row_count", "Report row count", len(table["rows"]),
                "Table row count", len(table["rows"]))],
    )


def build(
    db: Session,
    key: str,
    date_from: date | None = None,
    date_to: date | None = None,
    filters: dict | None = None,
):
    """Build a report using the shared API response contract."""
    if key not in CATALOG:
        raise KeyError(f"Unknown report: {key}")

    filters = filters or {}

    if date_from and date_to and date_from > date_to:
        raise ValueError("'from' must not be after 'to'")

    if key == "hr_employee_master":
        rows = _employee_rows(db, filters)
        table = _table(
            "employees", "Employee Master", rows,
            ["employee_id", "code", "full_name", "department", "designation",
             "phone", "email", "joining_date", "date_of_exit", "status",
             "branch_id", "branch"],
        )
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "hr_joining_exit":
        rows = _employee_rows(db, filters)
        rows = [
            row for row in rows
            if _in_period(row["joining_date"], date_from, date_to)
            or _in_period(row["date_of_exit"], date_from, date_to)
        ]
        table = _table(
            "employees", "Joining and Exit", rows,
            ["employee_id", "code", "full_name", "department", "designation",
             "joining_date", "date_of_exit", "status", "branch_id", "branch"],
        )
        return _empty_reconciled(key, date_from, date_to, table)

    if key in ("hr_attendance", "hr_late_arrival", "hr_missing_punch"):
        rows = _hr_attendance_rows(db, filters, date_from, date_to)
        if key == "hr_late_arrival":
            rows = [r for r in rows if (r.get("late_minutes") or 0) > 0]
            table_key, title = "late_arrivals", "Late Arrivals"
        elif key == "hr_missing_punch":
            rows = [
                r for r in rows
                if r.get("check_in") is None or r.get("check_out") is None
            ]
            table_key, title = "missing_punches", "Missing Punches"
        else:
            table_key, title = "attendance", "Attendance Register"

        attendance_columns = [
            "attendance_id", "employee_id", "code", "full_name",
            "department", "branch_id", "date", "status", "check_in",
            "check_out", "late_minutes", "early_minutes",
            "worked_minutes", "source",
        ]
        table = _table(table_key, title, rows, preferred=attendance_columns)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "hr_leave":
        employees = _employees(db, filters)
        ids = [e.id for e in employees]
        employee_map = {e.id: e for e in employees}
        query = db.query(LeaveApplication)
        if filters.get("employee_id") is not None:
            query = query.filter(LeaveApplication.employee_id == filters["employee_id"])
        rows = []
        for item in query.order_by(LeaveApplication.date_from).all():
            employee = employee_map.get(item.employee_id)
            if filters.get("department") and not employee:
                continue
            if filters.get("branch_id") is not None and not employee:
                continue
            if not employee and filters.get("employee_id") is None:
                employee = db.get(Employee, item.employee_id)
                if filters.get("department") and (
                    not employee or (employee.department or "").lower() !=
                    filters["department"].lower()
                ):
                    continue
                if filters.get("branch_id") is not None and (
                    not employee or employee.branch_id != filters["branch_id"]
                ):
                    continue
            if not _in_period(item.date_from, date_from, date_to):
                continue
            leave_type = db.get(LeaveType, item.leave_type_id)
            rows.append({
                "leave_id": item.id,
                "employee_id": item.employee_id,
                "code": employee.code if employee else None,
                "full_name": employee.full_name if employee else None,
                "department": employee.department if employee else None,
                "branch_id": employee.branch_id if employee else None,
                "leave_type": leave_type.name if leave_type else None,
                "date_from": item.date_from,
                "date_to": item.date_to,
                "days": item.days,
                "status": item.status,
                "reason": item.reason,
                "created_at": item.created_at,
            })
        table = _table("leave", "Leave Register", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "hr_od":
        employees = _employees(db, filters)
        employee_map = {e.id: e for e in employees}
        query = db.query(ODRequest)
        if filters.get("employee_id") is not None:
            query = query.filter(ODRequest.employee_id == filters["employee_id"])
        rows = []
        for item in query.order_by(ODRequest.date).all():
            employee = employee_map.get(item.employee_id)
            if employee is None:
                employee = db.get(Employee, item.employee_id)
            if filters.get("department") and (
                not employee or (employee.department or "").lower() !=
                filters["department"].lower()
            ):
                continue
            if filters.get("branch_id") is not None and (
                not employee or employee.branch_id != filters["branch_id"]
            ):
                continue
            if not _in_period(item.date, date_from, date_to):
                continue
            rows.append({
                "od_id": item.id,
                "employee_id": item.employee_id,
                "code": employee.code if employee else None,
                "full_name": employee.full_name if employee else None,
                "department": employee.department if employee else None,
                "branch_id": employee.branch_id if employee else None,
                "date": item.date,
                "end_date": item.end_date,
                "duration": item.duration,
                "visit_type": item.visit_type,
                "purpose": item.purpose,
                "destination": item.destination,
                "status": item.status,
            })
        table = _table("od_requests", "On Duty Register", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key in ("hr_payroll", "hr_payroll_deductions"):
        rows = _payroll_rows(db, filters, date_from, date_to)
        if key == "hr_payroll":
            table = _table("payroll", "Payroll Register", rows)
        else:
            details = []
            entry_ids = [r["payroll_entry_id"] for r in rows]
            if entry_ids:
                lines = (
                    db.query(PayrollEntryLine)
                    .filter(PayrollEntryLine.entry_id.in_(entry_ids))
                    .order_by(PayrollEntryLine.entry_id, PayrollEntryLine.id)
                    .all()
                )
                entry_map = {r["payroll_entry_id"]: r for r in rows}
                for line in lines:
                    if (line.kind or "").lower() != "deduction":
                        continue
                    parent = entry_map.get(line.entry_id, {})
                    details.append({
                        "payroll_entry_id": line.entry_id,
                        "employee_id": parent.get("employee_id"),
                        "code": parent.get("code"),
                        "full_name": parent.get("full_name"),
                        "department": parent.get("department"),
                        "year": parent.get("year"),
                        "month": parent.get("month"),
                        "component": line.name,
                        "amount": _num(_decimal(line.amount)),
                    })
            table = _table(
            "payroll_deductions",
            "Payroll Deductions",
            details,
            preferred=[
                "payroll_entry_id", "employee_id", "code", "full_name",
                "department", "year", "month", "component", "amount",
            ],
        )
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "hr_leave_balance":
        employees = _employees(db, filters)
        ids = [e.id for e in employees]
        employee_map = {e.id: e for e in employees}
        year = (date_to or date_from or date.today()).year
        query = db.query(LeaveBalance).filter(LeaveBalance.year == year)
        if ids:
            query = query.filter(LeaveBalance.employee_id.in_(ids))
        else:
            query = query.filter(LeaveBalance.employee_id == -1)
        rows = []
        for balance in query.all():
            employee = employee_map.get(balance.employee_id)
            leave_type = db.get(LeaveType, balance.leave_type_id)
            rows.append({
                "employee_id": balance.employee_id,
                "code": employee.code if employee else None,
                "full_name": employee.full_name if employee else None,
                "department": employee.department if employee else None,
                "branch_id": employee.branch_id if employee else None,
                "year": balance.year,
                "leave_type": leave_type.name if leave_type else None,
                "entitled": _num(_decimal(balance.entitled)),
                "used": _num(_decimal(balance.used)),
                "pending": _num(_decimal(balance.pending)),
                "carried": _num(_decimal(balance.carried)),
            })
        table = _table(
            "leave_balances",
            "Leave Balances",
            rows,
            preferred=[
                "employee_id", "code", "full_name", "department",
                "branch_id", "year", "leave_type", "entitled", "used",
                "pending", "carried",
            ],
        )
        return _empty_reconciled(key, date_from, date_to, table)

    if key in ("hr_approvals", "hr_approval_turnaround"):
        query = db.query(ApprovalRequest)
        if date_from:
            query = query.filter(ApprovalRequest.requested_at >= datetime.combine(
                date_from, datetime.min.time()
            ))
        if date_to:
            query = query.filter(ApprovalRequest.requested_at < datetime.combine(
                date_to.fromordinal(date_to.toordinal() + 1), datetime.min.time()
            ))
        rows = []
        for item in query.order_by(ApprovalRequest.requested_at).all():
            row = {
                "approval_id": item.id,
                "record_type": item.record_type,
                "record_id": item.record_id,
                "request_no": item.request_no,
                "document_number": item.document_number,
                "subject": item.subject,
                "status": item.status,
                "pending_approver_role": item.pending_approver_role,
                "requested_by": item.requested_by,
                "requested_at": item.requested_at,
                "decided_by": item.decided_by,
                "decided_at": item.decided_at,
                "decision_reason": item.decision_reason,
            }
            if key == "hr_approval_turnaround":
                elapsed = None
                if item.requested_at and item.decided_at:
                    elapsed = round(
                        (item.decided_at - item.requested_at).total_seconds() / 3600, 2
                    )
                row["turnaround_hours"] = elapsed
            rows.append(row)
        table_key = "approval_turnaround" if key == "hr_approval_turnaround" else "approvals"
        title = "Approval Turnaround" if key == "hr_approval_turnaround" else "Approval Register"
        approval_columns = [
            "approval_id", "record_type", "record_id", "request_no",
            "document_number", "subject", "status",
            "pending_approver_role", "requested_by", "requested_at",
            "decided_by", "decided_at", "decision_reason",
        ]
        if key == "hr_approval_turnaround":
            approval_columns.append("turnaround_hours")
        table = _table(
            table_key, title, rows, preferred=approval_columns
        )
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "stock":
        products = db.query(Product).order_by(Product.sku, Product.id).all()
        rows = []
        for product in products:
            batches = db.query(Batch).filter(Batch.product_id == product.id).all()
            qty = sum((_decimal(b.on_hand) for b in batches), Decimal("0.00"))
            rows.append({
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "pack_size": product.pack_size,
                "status": product.status,
                "quantity": _num(qty),
                "batch_count": len(batches),
            })
        total_qty = sum((_decimal(r["quantity"]) for r in rows), Decimal("0.00"))
        table = _table(
            "stock", "Stock on Hand", rows,
            ["product_id", "sku", "name", "pack_size", "status", "quantity", "batch_count"],
            {"quantity": _num(total_qty)},
        )
        return _envelope(
            key, date_from, date_to, [table],
            [_check("product_count", "Products in report", len(rows),
                    "Products queried", len(products))],
        )

    if key == "receivables":
        data = ledger.receivable_rows(db)
        rows = []
        for item in data:
            if date_from and item.get("invoice_date") and item["invoice_date"] < date_from:
                continue
            if date_to and item.get("invoice_date") and item["invoice_date"] > date_to:
                continue
            rows.append({k: _iso(v) for k, v in item.items()})
        table = _table("receivables", "Receivables", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "receivables_ageing":
        data = ledger.ageing_rows(db, date_to or date.today())
        rows = []
        if isinstance(data, dict):
            rows = [{"ageing_bucket": k, "amount": _num(_decimal(v))}
                    for k, v in data.items()]
        elif isinstance(data, list):
            rows = data
        table = _table("receivables_ageing", "Receivables Ageing", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "payables":
        data = ledger.payable_rows(db)
        rows = []
        for item in data:
            rows.append({k: _iso(v) for k, v in item.items()})
        table = _table("payables", "Payables", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "trial_balance":
        result = ledger.trial_balance(db, date_to or date.today())
        if isinstance(result, dict):
            source_rows = result.get("rows", [])
            if not source_rows:
                source_rows = [
                    {"account": k, "balance": _num(_decimal(v))}
                    for k, v in result.items()
                    if not isinstance(v, (dict, list))
                ]
        elif isinstance(result, list):
            source_rows = result
        else:
            source_rows = []
        table = _table("trial_balance", "Trial Balance", source_rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "gst_register":
        result = ledger.gst_register(db, date_from, date_to)
        if isinstance(result, dict):
            rows = result.get("rows", result.get("items", []))
            limitations = result.get("limitations", [])
            if not limitations:
                limitations = [
                    "Outward supply register only; verify tax data before statutory filing.",
                    "Input GST purchase-register reconciliation is not available in this report.",
                ]
        else:
            rows = result or []
            limitations = [
                "Outward supply register only; verify tax data before statutory filing.",
                "Input GST purchase-register reconciliation is not available in this report.",
            ]
        table = _table("gst_register", "GST Outward Register", rows)
        return _envelope(
            key, date_from, date_to, [table],
            [_check("row_count", "Report rows", len(rows), "Table rows", len(table["rows"]))],
            limitations,
        )

    if key == "hr_approvals":
        # Handled above; kept explicit for catalog clarity.
        raise RuntimeError("Approval report dispatch failed.")

    # Remaining general registers use the actual model classes and fields.
    if key == "sales":
        query = db.query(SalesOrder)
        if date_from:
            query = query.filter(SalesOrder.created_at >= datetime.combine(
                date_from, datetime.min.time()
            ))
        if date_to:
            query = query.filter(SalesOrder.created_at < datetime.combine(
                date_to.fromordinal(date_to.toordinal() + 1), datetime.min.time()
            ))
        rows = [{
            "id": r.id, "so_number": r.so_number, "distributor_id": r.distributor_id,
            "status": r.status, "total": _num(_decimal(r.total)),
            "created_at": r.created_at, "dispatched_at": r.dispatched_at,
        } for r in query.order_by(SalesOrder.created_at).all()]
        table = _table("sales_orders", "Sales Orders", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "invoices":
        query = db.query(Invoice)
        if date_from:
            query = query.filter(Invoice.invoice_date >= date_from)
        if date_to:
            query = query.filter(Invoice.invoice_date <= date_to)
        rows = [{
            "id": r.id, "invoice_number": r.invoice_number, "financial_year": r.financial_year,
            "sales_order_id": r.sales_order_id, "distributor_id": r.distributor_id,
            "status": r.status, "invoice_date": r.invoice_date,
            "taxable_value": _num(_decimal(r.taxable_value)),
            "cgst_total": _num(_decimal(r.cgst_total)),
            "sgst_total": _num(_decimal(r.sgst_total)),
            "igst_total": _num(_decimal(r.igst_total)),
            "tax_total": _num(_decimal(r.tax_total)),
            "grand_total": _num(_decimal(r.grand_total)),
        } for r in query.order_by(Invoice.invoice_date).all()]
        table = _table("invoices", "Sales Invoice Register", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "leads":
        query = db.query(Lead)
        if hasattr(Lead, "created_at"):
            if date_from:
                query = query.filter(Lead.created_at >= datetime.combine(
                    date_from, datetime.min.time()
                ))
            if date_to:
                query = query.filter(Lead.created_at < datetime.combine(
                    date_to.fromordinal(date_to.toordinal() + 1), datetime.min.time()
                ))
        rows = []
        for r in query.all():
            rows.append({
                column: getattr(r, column, None)
                for column in ("id", "name", "phone", "email", "source", "status",
                               "created_at", "assigned_to")
                if hasattr(r, column)
            })
        table = _table("leads", "Lead Register", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "purchases":
        query = db.query(PurchaseOrder)
        if date_from:
            query = query.filter(PurchaseOrder.created_at >= datetime.combine(
                date_from, datetime.min.time()
            ))
        if date_to:
            query = query.filter(PurchaseOrder.created_at < datetime.combine(
                date_to.fromordinal(date_to.toordinal() + 1), datetime.min.time()
            ))
        rows = [{
            "id": r.id, "po_number": r.po_number, "supplier_id": r.supplier_id,
            "supplier_name": r.supplier, "status": r.status,
            "created_at": r.created_at,
        } for r in query.order_by(PurchaseOrder.created_at).all()]
        table = _table("purchase_orders", "Purchase Orders", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "goods_receipts":
        query = db.query(GoodsReceipt)
        if date_from:
            query = query.filter(GoodsReceipt.received_at >= datetime.combine(
                date_from, datetime.min.time()
            ))
        if date_to:
            query = query.filter(GoodsReceipt.received_at < datetime.combine(
                date_to.fromordinal(date_to.toordinal() + 1), datetime.min.time()
            ))
        rows = [{
            "id": r.id, "grn_number": r.grn_number, "po_id": r.po_id,
            "warehouse_id": r.warehouse_id, "received_by": r.received_by,
            "owner": r.owner, "delivery_note": r.delivery_note,
            "received_at": r.received_at,
        } for r in query.order_by(GoodsReceipt.received_at).all()]
        table = _table("goods_receipts", "Goods Receipt Register", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "suppliers":
        rows = [{
            "id": r.id, "code": r.code, "name": r.name, "kind": r.kind,
            "registration_type": r.registration_type, "gstin": r.gstin,
            "state_code": r.state_code, "payment_terms_days": r.payment_terms_days,
            "status": r.status, "needs_completion": r.needs_completion,
        } for r in db.query(Supplier).order_by(Supplier.code).all()]
        table = _table("suppliers", "Supplier Register", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    if key == "distributors":
        rows = [{
            "id": r.id, "code": r.code, "name": r.name, "territory": r.territory,
            "status": r.status, "credit_limit": _num(_decimal(r.credit_limit)),
            "gstin": r.gstin, "state_code": r.state_code,
            "payment_terms_days": r.payment_terms_days,
        } for r in db.query(Distributor).order_by(Distributor.code).all()]
        table = _table("distributors", "Distributor Register", rows)
        return _empty_reconciled(key, date_from, date_to, table)

    raise ValueError(f"Report '{key}' is registered but has no implementation.")
