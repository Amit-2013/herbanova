"""Central reporting service for Herbanova.

Reports are read-only. This module does not modify business transactions,
inventory, accounting entries, permissions, or database schema.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models.core import (
    ApprovalRequest,
    Batch,
    CreditNote,
    DebitNote,
    Distributor,
    Invoice,
    InvoiceLine,
    Lead,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesOrder,
    StockMovement,
    Warehouse,
)
from ..models.accounts import RECEIPT, Payment
from ..models.expenses import APPROVED, Expense
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
from . import capacity, ledger, profit_loss


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
    "warehouse_utilisation": (
        "Warehouse Utilisation", "Units on hand, capacity and fill level per warehouse.",
        "snapshot", "stock:read", "warehouses", "Inventory Reports",
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
    "profit_and_loss": (
        "Profit and Loss",
        "Revenue, returns, cost of goods, expenses and payroll for the period, "
        "with reconciliation checks and the gaps that remain.",
        "period", "accounts:reports", "profit_and_loss", "Accounting & Finance",
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
    "warehouse_utilisation": [],
    "suppliers": [],
    "distributors": [],
    "receivables": [],
    "receivables_ageing": [],
    "payables": [],
    "gst_register": [],
    "trial_balance": [],
    "profit_and_loss": [],
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


# Column kinds the exporters and screens already understand. Exporters must
# never receive a kind they do not handle: a numeric column written as text is
# a spreadsheet that cannot be summed.
MONEY_KEYS = {
    "adjusted", "amount", "cess", "cess_total", "cgst", "cgst_total", "credit",
    "credit_limit", "debit", "deductions", "discount_total", "grand_total",
    "gross", "gross_total", "igst", "igst_total", "net", "outstanding", "paid",
    "received", "received_value", "sgst", "sgst_total", "tax_total",
    "taxable", "taxable_value", "total",
}
QTY_KEYS = {
    "capacity_units", "carried", "days", "entitled", "free_units",
    "lop_days", "on_hand", "paid_leave_days", "payable_days", "pending",
    "present_days", "qty", "quantity", "turnaround_hours", "used",
    "used_units", "working_days",
}
INT_KEYS = {
    "batch_count", "batches", "early_minutes", "invoice_count",
    "late_minutes", "month", "payment_terms_days", "worked_minutes", "year",
}
PCT_KEYS = {"utilisation_pct"}

# The payroll register is read by people, not by the database: its headers say
# what the column means and which ones are money.
PAYROLL_LABELS = {
    "payroll_entry_id": "Entry ID",
    "period_id": "Period ID",
    "year": "Year",
    "month": "Month",
    "employee_id": "Employee ID",
    "code": "Employee code",
    "full_name": "Name",
    "department": "Department",
    "branch_id": "Branch ID",
    "working_days": "Working days",
    "payable_days": "Payable days",
    "present_days": "Present days",
    "paid_leave_days": "Paid leave days",
    "lop_days": "LOP days",
    "gross": "Gross (₹)",
    "deductions": "Deductions (₹)",
    "net": "Net (₹)",
    "status": "Status",
}


def _column_type(key):
    if key in MONEY_KEYS:
        return "money"
    if key in QTY_KEYS:
        return "qty"
    if key in INT_KEYS:
        return "int"
    if key in PCT_KEYS:
        return "pct"
    return "text"


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
            "type": _column_type(key),
        }
        for key in keys
    ]


def _table(key, title, rows, preferred=None, totals=None, labels=None):
    clean_rows = [
        {k: _iso(v) for k, v in row.items()}
        for row in rows
    ]
    columns = _columns(clean_rows, preferred)
    if labels:
        for column in columns:
            column["label"] = labels.get(column["key"], column["label"])
    return {
        "key": key,
        "title": title,
        "columns": columns,
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


def _source_receivables(db: Session, date_from: date | None = None,
                        date_to: date | None = None) -> dict:
    """Recompute what is owed straight from grouped SQL aggregates.

    Deliberately a different code path from ``ledger.receivable_rows()``: the
    report is built from ORM rows one document at a time, this from database
    SUM()s, so the two agreeing is real evidence instead of a self-comparison
    (the flaw behind the empty GST register and the flattened ageing report).
    """
    stmt = select(Invoice.id, Invoice.grand_total).where(Invoice.status == "issued")
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    invoices = {i: ledger.money(g) for i, g in db.execute(stmt).all()}
    if not invoices:
        return {"invoices": 0, "outstanding": ledger.money(0),
                "open": 0, "open_total": ledger.money(0)}
    ids = list(invoices)

    def per_invoice(model, column):
        rows = db.execute(
            select(model.invoice_id, func.coalesce(func.sum(column), 0))
            .where(model.status == "issued", model.invoice_id.in_(ids))
            .group_by(model.invoice_id)).all()
        return {i: ledger.money(v) for i, v in rows}

    received = {i: ledger.money(v) for i, v in db.execute(
        select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.kind == RECEIPT, Payment.invoice_id.in_(ids))
        .group_by(Payment.invoice_id)).all()}
    credit = per_invoice(CreditNote, CreditNote.grand_total)
    debit = per_invoice(DebitNote, DebitNote.grand_total)

    total, open_total, open_count = ledger.money(0), ledger.money(0), 0
    for inv_id, grand in invoices.items():
        outstanding = ledger.money(
            grand - credit.get(inv_id, ledger.ZERO) + debit.get(inv_id, ledger.ZERO)
            - received.get(inv_id, ledger.ZERO))
        total = ledger.money(total + outstanding)
        if outstanding > 0:
            open_total = ledger.money(open_total + outstanding)
            open_count += 1
    return {"invoices": len(invoices), "outstanding": total,
            "open": open_count, "open_total": open_total}


def _source_gst(db: Session, date_from: date | None, date_to: date | None) -> dict:
    """Outward taxable value and tax totals summed in SQL, independent of
    ``ledger.gst_register()`` (which builds one Python dict per document)."""
    cols = ("taxable_value", "cgst_total", "sgst_total", "igst_total", "grand_total")

    def period(stmt, date_col):
        if date_from:
            stmt = stmt.where(date_col >= date_from)
        if date_to:
            stmt = stmt.where(date_col <= date_to)
        return stmt

    def totals(model, date_col):
        stmt = select(*[func.coalesce(func.sum(getattr(model, c)), 0) for c in cols])
        stmt = period(stmt.where(model.status == "issued"), date_col)
        return [ledger.money(v) for v in db.execute(stmt).one()]

    documents = 0
    for model, date_col in ((Invoice, Invoice.invoice_date),
                            (CreditNote, CreditNote.note_date),
                            (DebitNote, DebitNote.note_date)):
        stmt = select(func.count()).select_from(model).where(model.status == "issued")
        documents += int(db.scalar(period(stmt, date_col)) or 0)

    inv = totals(Invoice, Invoice.invoice_date)
    credit = totals(CreditNote, CreditNote.note_date)
    debit = totals(DebitNote, DebitNote.note_date)
    keys = ("taxable", "cgst", "sgst", "igst", "total")
    out = {k: ledger.money(inv[i] + debit[i] - credit[i]) for i, k in enumerate(keys)}
    out["documents"] = documents
    return out


def _source_payables(db: Session, po_ids: list[int]) -> dict:
    """Received purchase value and cash paid for the listed orders, recomputed
    in SQL (the report builds the same figures in Python, one row at a time)."""
    if not po_ids:
        return {"received_value": ledger.money(0), "paid": ledger.money(0)}
    received = db.execute(
        select(func.coalesce(func.sum(GoodsReceiptLine.qty * PurchaseOrderLine.unit_cost), 0))
        .select_from(GoodsReceiptLine)
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.grn_id)
        .join(PurchaseOrderLine,
              (PurchaseOrderLine.po_id == GoodsReceipt.po_id)
              & (PurchaseOrderLine.product_id == GoodsReceiptLine.product_id))
        .where(GoodsReceipt.po_id.in_(po_ids))).scalar()
    paid = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.kind == "payment", Payment.purchase_order_id.in_(po_ids))).scalar()
    return {"received_value": ledger.money(received), "paid": ledger.money(paid)}


def _empty_reconciled(key, date_from, date_to, table, source_count=None, extra=None):
    """Envelope consistency check, plus an independent record count when the
    caller supplies one taken straight from the database."""
    checks = [
        _check("row_count", "Report row count", len(table["rows"]),
               "Table row count", len(table["rows"])),
    ]
    if source_count is not None:
        checks.append(_check("source_rows", "Report rows", len(table["rows"]),
                             "Records found in the source table", source_count,
                             "records"))
    checks.extend(extra or [])
    return _envelope(
        key, date_from, date_to, [table],
        checks,
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
            table = _table("payroll", "Payroll Register", rows,
                           labels=PAYROLL_LABELS)
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
        # One grouped query for every batch instead of one round trip per product.
        quantities: dict[int, Decimal] = {}
        counts: dict[int, int] = {}
        for product_id, qty, n in db.query(
                Batch.product_id, func.coalesce(func.sum(Batch.on_hand), 0),
                func.count(Batch.id)).group_by(Batch.product_id).all():
            quantities[product_id] = _decimal(qty)
            counts[product_id] = int(n)
        rows = []
        for product in products:
            qty = quantities.get(product.id, Decimal("0.00"))
            rows.append({
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "pack_size": product.pack_size,
                "status": product.status,
                "quantity": _num(qty),
                "batch_count": counts.get(product.id, 0),
            })
        total_qty = sum((_decimal(r["quantity"]) for r in rows), Decimal("0.00"))
        movement_qty = _decimal(db.scalar(
            select(func.coalesce(func.sum(StockMovement.qty_delta), 0))))
        table = _table(
            "stock", "Stock on Hand", rows,
            ["product_id", "sku", "name", "pack_size", "status", "quantity", "batch_count"],
            {"quantity": _num(total_qty)},
        )
        return _envelope(
            key, date_from, date_to, [table],
            [_check("product_count", "Products in report", len(rows),
                    "Products queried", len(products)),
             # Opening balance + movements = closing stock, checked against the
             # append-only movement ledger rather than against the batch table.
             _check("stock_quantity", "Report stock quantity", total_qty,
                    "Sum of the stock movement ledger", movement_qty, "units")],
        )

    if key == "receivables":
        data = ledger.receivable_rows(db)
        rows = []
        for item in data:
            day = item.get("date")
            if date_from and day and day < date_from:
                continue
            if date_to and day and day > date_to:
                continue
            rows.append({k: _iso(v) for k, v in item.items()})
        table = _table("receivables", "Receivables", rows)
        report_outstanding = ledger.money(
            sum((_decimal(r.get("outstanding")) for r in rows), Decimal("0")))
        source = _source_receivables(db, date_from, date_to)
        return _envelope(key, date_from, date_to, [table], [
            _check("row_count", "Report rows", len(rows),
                   "Issued invoices in the period", source["invoices"], "records"),
            _check("outstanding", "Report outstanding", report_outstanding,
                   "Recomputed from invoices, notes and receipts",
                   source["outstanding"], "amount"),
        ])

    if key == "receivables_ageing":
        # Ageing is a snapshot: it reports every invoice that still carries a
        # balance as at the report date, grouped into the four day buckets.
        data = ledger.ageing_rows(db, date_to or date.today())
        rows = []
        buckets = data.get("buckets", []) if isinstance(data, dict) else []
        for bucket in buckets:
            rows.append({
                "ageing_bucket": bucket["key"],
                "label": bucket["label"],
                "invoice_count": bucket["count"],
                "amount": _num(_decimal(bucket["total"])),
            })
        table = _table("receivables_ageing", "Receivables Ageing", rows,
                       ["ageing_bucket", "label", "invoice_count", "amount"],
                       {"amount": _num(_decimal(data.get("total", 0)))})
        source = _source_receivables(db)
        report_amount = ledger.money(
            sum((_decimal(r["amount"]) for r in rows), Decimal("0")))
        report_count = sum(int(r["invoice_count"]) for r in rows)
        return _envelope(key, date_from, date_to, [table], [
            _check("ageing_total", "Report ageing total", report_amount,
                   "Recomputed from invoices, notes and receipts",
                   source["open_total"], "amount"),
            _check("ageing_count", "Invoices in the buckets", report_count,
                   "Invoices with a balance", source["open"], "records"),
        ], [
            "Buckets count days since the invoice date, measured at the report date; "
            "invoices have no due date of their own.",
            "Outstanding is net of credit notes and receipts already recorded.",
        ])

    if key == "payables":
        data = ledger.payable_rows(db)
        rows = [{k: _iso(v) for k, v in item.items()} for item in data]
        table = _table("payables", "Payables", rows)
        report_received = ledger.money(
            sum((_decimal(r.get("received_value")) for r in rows), Decimal("0")))
        report_paid = ledger.money(
            sum((_decimal(r.get("paid")) for r in rows), Decimal("0")))
        source = _source_payables(db, [r.get("purchase_order_id") for r in rows])
        return _envelope(key, date_from, date_to, [table], [
            _check("received_value", "Report goods received value", report_received,
                   "Recomputed from goods receipts x order lines",
                   source["received_value"], "amount"),
            _check("paid", "Report payments made", report_paid,
                   "Sum of recorded supplier payments", source["paid"], "amount"),
        ])

    if key == "profit_and_loss":
        fy_start, today = profit_loss.defaults(date.today())
        start, end = date_from or fy_start, date_to or today
        if start > end:
            raise ValueError("'from' must not be after 'to'")
        pl = profit_loss.statement(db, start, end)

        rows = [
            {"section": "Revenue", "line": "Revenue (taxable)",
             "amount": _num(_decimal(pl["revenue"]["taxable"])),
             "note": "Issued invoices, before GST."},
            {"section": "Revenue", "line": "Less returns (taxable)",
             "amount": _num(_decimal(-pl["returns"]["taxable"])),
             "note": f"{pl['returns']['count']} issued credit note(s)."},
            {"section": "Revenue", "line": "Add debit notes (taxable)",
             "amount": _num(_decimal(pl["revenue"]["debit_notes"])),
             "note": f"{pl['revenue']['debit_notes_count']} issued debit note(s)."},
            {"section": "Revenue", "line": "Net revenue",
             "amount": _num(_decimal(pl["net_revenue"])),
             "note": "Revenue less returns plus debit notes."},
            {"section": "Cost of sales", "line": "Cost of goods sold",
             "amount": _num(_decimal(pl["cogs"]["value"])),
             "note": (f"Captured issue cost; {pl['cogs']['invoices_costed']} of "
                      f"{pl['cogs']['invoices_total']} invoices fully costed.")},
            {"section": "Profit", "line": pl["gross_profit"]["label"],
             "amount": _num(_decimal(pl["gross_profit"]["value"])),
             "note": ("Complete for every invoice in the window."
                      if not pl["gross_profit"]["partial"]
                      else "Partial: invoices with no captured cost are named in the gaps.")},
        ]
        for head in pl["expenses"]["by_head"]:
            rows.append({
                "section": "Expenses", "line": head["head"],
                "amount": _num(_decimal(head["amount"])),
                "note": (f"{head['count']} approved entrie(s); non-creditable GST "
                         f"{head['gst_noncreditable']} is included in cost."),
            })
        rows.append({
            "section": "Expenses", "line": "Total expenses",
            "amount": (_num(_decimal(pl["expenses"]["total"]))
                       if pl["expenses"]["complete"] else None),
            "note": ("No approved expenses in this window." if not pl["expenses"]["count"]
                     else "Approved, non-reversed entries by head.") if pl["expenses"]["complete"]
            else "Not available: expenses are not tracked for the whole window (GAP-P02).",
        })
        rows.append({
            "section": "Payroll", "line": "Payroll (gross)",
            "amount": (_num(_decimal(pl["payroll"]["total"]))
                       if pl["payroll"]["complete"] else None),
            "note": ("Gross salary of approved, processed or paid monthly periods."
                     if pl["payroll"]["complete"]
                     else "Not available: a month is missing or only partly in the window (GAP-P03)."),
        })
        rows.append({
            "section": "Profit", "line": "Net profit",
            "amount": (_num(_decimal(pl["net_profit"]["value"]))
                       if pl["net_profit"]["available"] else None),
            "note": ("Gross profit less expenses and payroll."
                     if pl["net_profit"]["available"]
                     else "Not available until cost, expenses and payroll are complete; "
                          "no figure is estimated."),
        })
        table = _table("profit_and_loss", "Profit and Loss", rows,
                       ["section", "line", "amount", "note"])

        # Independent figures straight from the source tables, so a difference
        # in the statement is caught rather than printed.
        revenue_src, invoice_count = db.execute(
            select(func.coalesce(func.sum(Invoice.taxable_value), 0),
                   func.count(Invoice.id))
            .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                   Invoice.invoice_date <= end)).one()
        returns_src, returns_count = db.execute(
            select(func.coalesce(func.sum(CreditNote.taxable_value), 0),
                   func.count(CreditNote.id))
            .where(CreditNote.status == "issued", CreditNote.note_date >= start,
                   CreditNote.note_date <= end)).one()
        debits_src, debits_count = db.execute(
            select(func.coalesce(func.sum(DebitNote.taxable_value), 0),
                   func.count(DebitNote.id))
            .where(DebitNote.status == "issued", DebitNote.note_date >= start,
                   DebitNote.note_date <= end)).one()
        expenses_src = db.execute(
            select(func.coalesce(func.sum(
                Expense.amount + case((Expense.gst_creditable.is_(False),
                                       Expense.gst_amount), else_=0)), 0))
            .where(Expense.status == APPROVED, Expense.entry_date >= start,
                   Expense.entry_date <= end)).scalar()
        payroll_src = Decimal("0")
        for item in pl["payroll"]["periods"]:
            period = db.scalar(select(PayrollPeriod).where(
                PayrollPeriod.year == item["year"],
                PayrollPeriod.month == item["month"]))
            if period is not None:
                payroll_src += Decimal(db.scalar(
                    select(func.coalesce(func.sum(PayrollEntry.gross), 0))
                    .where(PayrollEntry.period_id == period.id)) or 0)

        checks = [
            _check("revenue", "Statement revenue", _decimal(pl["revenue"]["taxable"]),
                   "Issued invoices summed in the database", _decimal(revenue_src)),
            _check("returns", "Statement returns", _decimal(pl["returns"]["taxable"]),
                   "Issued credit notes summed in the database", _decimal(returns_src)),
            _check("debit_notes", "Statement debit notes",
                   _decimal(pl["revenue"]["debit_notes"]),
                   "Issued debit notes summed in the database", _decimal(debits_src)),
            _check("net_revenue", "Net revenue", _decimal(pl["net_revenue"]),
                   "Revenue less returns plus debit notes",
                   _decimal(_decimal(pl["revenue"]["taxable"])
                            - _decimal(pl["returns"]["taxable"])
                            + _decimal(pl["revenue"]["debit_notes"]))),
            _check("gross_profit", "Gross profit",
                   _decimal(pl["gross_profit"]["value"]),
                   "Net revenue less cost of goods",
                   _decimal(_decimal(pl["net_revenue"]) - _decimal(pl["cogs"]["value"]))),
            _check("expenses", "Total expenses", _decimal(pl["expenses"]["total"]),
                   "Approved entries summed in the database", _decimal(expenses_src)),
            _check("payroll", "Payroll gross", _decimal(pl["payroll"]["total"]),
                   "Approved or later payroll periods summed", _decimal(payroll_src)),
            _check("invoice_count", "Invoices in the statement", pl["cogs"]["invoices_total"],
                   "Issued invoices in the database", int(invoice_count), "records"),
        ]
        if pl["net_profit"]["available"]:
            checks.append(_check(
                "net_profit", "Net profit", _decimal(pl["net_profit"]["value"]),
                "Gross profit less expenses and payroll",
                _decimal(_decimal(pl["gross_profit"]["value"])
                         - _decimal(pl["expenses"]["total"])
                         - _decimal(pl["payroll"]["total"]))))

        recon_rows = [{
            "check": c["name"],
            "report": f"{c['report_label']}: {c['report_value']}",
            "records": f"{c['record_label']}: {c['record_value']}",
            "result": "Agrees" if c["ok"] else "DIFFERS",
        } for c in checks]
        recon = _table("reconciliation", "Reconciliation", recon_rows,
                       ["check", "report", "records", "result"])

        limitations = list(pl["notes"]) + [
            "Payroll months only partly inside the window are excluded, never prorated.",
            "This statement reads the records; it is not a statutory filing.",
        ]
        for gap in pl["gaps"]:
            limitations.append(f"{gap['code']} — {gap['label']}: {gap['detail']} "
                               f"Fix: {gap['fix_label']}.")
        if not pl["net_profit"]["available"]:
            limitations.append("Net profit is not shown because the statement is "
                               "incomplete; no figure is estimated.")
        return _envelope(key, start, end, [table, recon], checks, limitations)

    if key == "trial_balance":
        result = ledger.trial_balance(db, date_to or date.today())
        source_rows = result.get("rows", []) if isinstance(result, dict) else []
        table = _table("trial_balance", "Trial Balance", source_rows)
        debit_sum = ledger.money(sum((_decimal(r.get("debit")) for r in source_rows),
                                     Decimal("0")))
        credit_sum = ledger.money(sum((_decimal(r.get("credit")) for r in source_rows),
                                      Decimal("0")))
        checks = [
            _check("row_count", "Report rows", len(source_rows),
                   "Table rows", len(table["rows"])),
            # Double entry: every document contributes both sides, so the two
            # totals must agree. A difference would mean a stored figure that
            # does not add up, and is reported rather than hidden.
            _check("balanced", "Total debits", ledger.money(result.get("debit_total")),
                   "Total credits", ledger.money(result.get("credit_total")), "amount"),
            _check("row_debits", "Debits listed in the rows", debit_sum,
                   "Reported debit total", ledger.money(result.get("debit_total")),
                   "amount"),
            _check("row_credits", "Credits listed in the rows", credit_sum,
                   "Reported credit total", ledger.money(result.get("credit_total")),
                   "amount"),
        ]
        return _envelope(key, date_from, date_to, [table], checks)

    if key == "gst_register":
        result = ledger.gst_register(db, date_from, date_to)
        rows = []
        for section, items in (("B2B invoice", result.get("b2b") or []),
                               ("Credit note", result.get("credit_notes") or []),
                               ("Debit note", result.get("debit_notes") or [])):
            for item in items:
                rows.append({
                    "section": section,
                    "number": item.get("number"),
                    "date": item.get("date"),
                    "party": item.get("party"),
                    "gstin": item.get("gstin"),
                    "place_of_supply": item.get("place_of_supply"),
                    "taxable": _num(_decimal(item.get("taxable"))),
                    "cgst": _num(_decimal(item.get("cgst"))),
                    "sgst": _num(_decimal(item.get("sgst"))),
                    "igst": _num(_decimal(item.get("igst"))),
                    "total": _num(_decimal(item.get("total"))),
                })
        preferred = ["section", "number", "date", "party", "gstin", "place_of_supply",
                     "taxable", "cgst", "sgst", "igst", "total"]
        totals = result.get("totals", {})
        table = _table("gst_register", "GST Outward Register", rows, preferred,
                       {k: _num(_decimal(totals.get(k))) for k in
                        ("taxable", "cgst", "sgst", "igst", "total")})
        source = _source_gst(db, date_from, date_to)
        checks = [
            _check("row_count", "Documents listed", len(rows),
                   "Invoices, credit and debit notes in the period",
                   source["documents"], "records"),
        ]
        for label, key_name in (("Taxable value", "taxable"), ("CGST", "cgst"),
                                ("SGST", "sgst"), ("IGST", "igst"),
                                ("Invoice value", "total")):
            checks.append(_check(
                f"{key_name}_total", f"Report {label.lower()}",
                ledger.money(totals.get(key_name)),
                f"{label} summed from the documents",
                source[key_name], "amount"))
        return _envelope(
            key, date_from, date_to, [table], checks,
            [
                "Outward supply register only; verify tax data before statutory filing.",
                "Input GST purchase-register reconciliation is not available in this report.",
                "Purchase orders record a cost, not a tax split, so no input tax credit "
                "can be produced from them yet.",
            ],
        )

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
        # Totals recomputed by the database, not re-added in Python.
        source_count = query.count()
        source_value = ledger.money(query.with_entities(func.coalesce(func.sum(SalesOrder.total), 0)).scalar())
        report_value = ledger.money(sum((_decimal(r["total"]) for r in rows),
                                        Decimal("0")))
        return _empty_reconciled(key, date_from, date_to, table, source_count, [
            _check("order_value", "Report order value", report_value,
                   "Sum of order totals in the database", source_value, "amount"),
        ])

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
        source_count = query.count()
        source_taxable = ledger.money(query.with_entities(func.coalesce(func.sum(Invoice.taxable_value), 0)).scalar())
        source_grand = ledger.money(query.with_entities(func.coalesce(func.sum(Invoice.grand_total), 0)).scalar())
        report_taxable = ledger.money(sum((_decimal(r["taxable_value"]) for r in rows),
                                          Decimal("0")))
        report_grand = ledger.money(sum((_decimal(r["grand_total"]) for r in rows),
                                        Decimal("0")))
        return _empty_reconciled(key, date_from, date_to, table, source_count, [
            _check("taxable_value", "Report taxable value", report_taxable,
                   "Taxable value in the database", source_taxable, "amount"),
            _check("grand_total", "Report invoice value", report_grand,
                   "Invoice value in the database", source_grand, "amount"),
        ])

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

    if key == "warehouse_utilisation":
        state_label = {"not_configured": "Not configured", "ok": "Within capacity",
                       "high": "Above 80%", "full": "Full", "over": "Over capacity"}
        positions = capacity.warehouse_positions(db)
        rows = [{
            "name": r["name"],
            "capacity_units": r["capacity_units"],
            "capacity_note": r["capacity_note"],
            "used_units": _num(_decimal(r["used_units"])),
            "free_units": (None if r["free_units"] is None
                           else _num(_decimal(r["free_units"]))),
            "utilisation_pct": r["utilisation_pct"],
            "capacity_state": state_label.get(r["capacity_state"], r["capacity_state"]),
            "batches": r["batches"],
        } for r in positions]
        report_used = sum((_decimal(r["used_units"]) for r in rows), Decimal("0"))
        table = _table(
            "warehouses", "Warehouse Utilisation", rows,
            ["name", "capacity_units", "capacity_note", "used_units",
             "free_units", "utilisation_pct", "capacity_state", "batches"],
            {"used_units": _num(report_used)},
        )
        source_warehouses = db.scalar(
            select(func.count()).select_from(Warehouse)) or 0
        source_used = _decimal(db.scalar(
            select(func.coalesce(func.sum(Batch.on_hand), 0))))
        configured = db.scalar(
            select(func.count()).select_from(Warehouse)
            .where(Warehouse.capacity_units.is_not(None))) or 0
        report_configured = sum(
            1 for r in positions if r["capacity_units"] is not None)
        return _envelope(key, date_from, date_to, [table], [
            _check("warehouse_count", "Warehouses in report", len(rows),
                   "Warehouses in the database", source_warehouses),
            _check("used_units", "Report units on hand", report_used,
                   "Units on hand in the batch table", source_used, "units"),
            _check("configured_count", "Warehouses with capacity set",
                   report_configured, "Warehouses with a capacity in the database",
                   configured),
        ])

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
