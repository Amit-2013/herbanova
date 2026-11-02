"""Stage 3: the profit and loss proves its figures from the documents.

The hand-calculated case is deliberately built in a past calendar month so the
whole month lies inside the window: revenue 1,000, returns 100, cost 400,
expenses 150 and payroll 200 give a net profit of 150. GST is on the documents
and must not change that. The remaining tests cover the three gaps, the
non-creditable GST rule, the exports (opened and parsed) and the roles.
"""
import csv
import io
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import (Batch, CreditNote, CreditNoteLine, Invoice, InvoiceLine,
                             Product, SalesOrder, SalesOrderLine, User, Warehouse)
from app.models.expenses import APPROVED, Expense, ExpenseHead, ExpenseSettings
from app.models.hr import PayrollEntry, PayrollPeriod
from app.services import costing, profit_loss
from app.services.inventory import post_movement

ROOT = Path(__file__).resolve().parent.parent
MONTH = (2041, 6)
GST_MONTH = (2041, 7)
GAP_MONTH = (2041, 8)
PAYROLL_MONTH = (2041, 9)


def _dec(value) -> Decimal:
    return Decimal(str(value))


def _first_last(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


@pytest.fixture(scope="module", autouse=True)
def _restore_expense_tracking():
    """This module needs tracking to start before a 2041 window. Put the row back
    afterwards so later test files keep the settings they expect."""
    with SessionLocal() as db:
        row = db.get(ExpenseSettings, 1)
        before = None if row is None else (
            row.approval_enabled, row.approval_threshold, row.tracked_from)
    yield
    with SessionLocal() as db:
        row = db.get(ExpenseSettings, 1)
        if before is None:
            if row is not None:
                db.delete(row)
        else:
            row.approval_enabled, row.approval_threshold, row.tracked_from = before
        db.commit()


@contextmanager
def _tracking_from(when: date):
    with SessionLocal() as db:
        row = db.get(ExpenseSettings, 1)
        previous = row.tracked_from
        row.tracked_from = when
        db.commit()
    try:
        yield
    finally:
        with SessionLocal() as db:
            db.get(ExpenseSettings, 1).tracked_from = previous
            db.commit()


def _set_tracking(when: date) -> None:
    with SessionLocal() as db:
        row = db.get(ExpenseSettings, 1)
        row.approval_enabled = False
        row.approval_threshold = Decimal("0")
        row.tracked_from = when
        db.commit()


def _admin(db) -> User:
    return db.scalar(select(User).where(User.username == "admin"))


def _invoice(db, *, world, admin, order, number, when, taxable, tax, qty, rate,
             with_issue=True):
    """An issued invoice and its line. GST is stored so the tests can prove the
    profit and loss ignores it; the issue is written only when asked."""
    invoice = Invoice(
        invoice_number=number, financial_year="2041-42", sales_order_id=order.id,
        distributor_id=world["distributor_id"], status="issued", invoice_date=when,
        place_of_supply_state_code="27", place_of_supply_kind="intra",
        reverse_charge=False, seller_legal_name="Herbanova Test Co",
        seller_gstin="27AAAAA0000A1Z5", seller_state_code="27",
        buyer_name="Test distributor", buyer_state_code="27",
        gross_total=Decimal(taxable) + Decimal(tax), discount_total=Decimal("0"),
        taxable_value=Decimal(taxable), cgst_total=Decimal(tax) / 2,
        sgst_total=Decimal(tax) / 2, igst_total=Decimal("0"),
        cess_total=Decimal("0"), tax_total=Decimal(tax), round_off=Decimal("0"),
        grand_total=Decimal(taxable) + Decimal(tax), issued_by=admin.id)
    db.add(invoice)
    db.flush()
    line = InvoiceLine(
        invoice_id=invoice.id, product_id=order.product_id, sku=order.sku,
        product_name=order.product_name, hsn=world["hsn"], uqc="TAB",
        qty=Decimal(qty), unit_price=Decimal(rate), mrp=Decimal("100"),
        discount_percent=Decimal("0"), discount_amount=Decimal("0"),
        taxable_value=Decimal(taxable), cgst_rate=Decimal("9"), sgst_rate=Decimal("9"),
        cgst_amount=Decimal(tax) / 2, sgst_amount=Decimal(tax) / 2,
        line_total=Decimal(taxable) + Decimal(tax))
    db.add(line)
    db.flush()
    if with_issue:
        post_movement(db, batch_id=order["batch_id"], qty_delta=-Decimal(qty),
                      movement_type="issue", ref_type="invoice",
                      ref_id=str(invoice.id), actor_id=admin.id,
                      unit_cost=Decimal("10.00"),
                      cost_source=costing.WEIGHTED_AVERAGE, invoice_id=invoice.id)
    return invoice, line


class _Order(dict):
    """A SalesOrder plus the product details the invoice line needs."""

    def __getattr__(self, name):
        return self[name]


def _seed_full_month(world) -> dict:
    """Revenue 1,000 + 180 GST, a 100 + 18 GST price-only return, goods cost 400,
    one approved expense of 150 and one approved payroll month of 200."""
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        admin = _admin(db)
        product = Product(sku=f"PL-{suffix}", name="Profit test product",
                          pack_size="10 tabs", mrp=Decimal("100"),
                          hsn=world["hsn"], uqc="TAB", status="active")
        warehouse = Warehouse(name=f"Profit wh {suffix}")
        db.add_all([product, warehouse])
        db.flush()
        batch = Batch(product_id=product.id, warehouse_id=warehouse.id,
                      batch_no=f"PL-{suffix}", on_hand=Decimal("0"))
        db.add(batch)
        db.flush()
        # Opening 100 units at cost 10, then 40 issued to the invoice.
        post_movement(db, batch_id=batch.id, qty_delta=Decimal("100"),
                      movement_type="receipt", ref_type="opening",
                      ref_id=f"PL-OPEN-{suffix}", actor_id=admin.id,
                      unit_cost=Decimal("10.00"), cost_source=costing.PO_RECEIPT)

        order = SalesOrder(so_number=f"PLSO-{suffix}",
                           distributor_id=world["distributor_id"],
                           status="dispatched", total=Decimal("1000.00"),
                           created_by=admin.id, submitted_by=admin.id,
                           dispatched_by=admin.id,
                           dispatched_at=datetime(2041, 6, 10, 10, 0,
                                                  tzinfo=timezone.utc))
        db.add(order)
        db.flush()
        db.add(SalesOrderLine(order_id=order.id, product_id=product.id,
                              qty=Decimal("40"), unit_price=Decimal("25.00"),
                              line_total=Decimal("1000.00")))
        handle = _Order(id=order.id, order_id=order.id, batch_id=batch.id,
                        product_id=product.id, sku=product.sku,
                        product_name=product.name)
        invoice, line = _invoice(db, world=world, admin=admin, order=handle,
                                 number=f"PL{suffix}", when=date(2041, 6, 10),
                                 taxable="1000.00", tax="180.00", qty="40",
                                 rate="25.00")

        credit = CreditNote(
            credit_note_number=f"CN{suffix}", financial_year="2041-42",
            invoice_id=invoice.id, sales_order_id=order.id,
            distributor_id=world["distributor_id"], status="issued",
            note_date=date(2041, 6, 15), reason="Rate difference agreed",
            return_warehouse_id=None, gross_total=Decimal("118.00"),
            discount_total=Decimal("0"), taxable_value=Decimal("100.00"),
            cgst_total=Decimal("9.00"), sgst_total=Decimal("9.00"),
            igst_total=Decimal("0"), cess_total=Decimal("0"),
            tax_total=Decimal("18.00"), round_off=Decimal("0"),
            grand_total=Decimal("118.00"), issued_by=admin.id)
        db.add(credit)
        db.flush()
        db.add(CreditNoteLine(credit_note_id=credit.id, invoice_line_id=line.id,
                              product_id=product.id, sku=product.sku,
                              product_name=product.name, qty=Decimal("4"),
                              taxable_value=Decimal("100.00"),
                              cgst_amount=Decimal("9.00"),
                              sgst_amount=Decimal("9.00"),
                              line_total=Decimal("118.00")))

        head = ExpenseHead(name=f"Rent {suffix}")
        db.add(head)
        db.flush()
        db.add(Expense(head_id=head.id, entry_date=date(2041, 6, 12),
                       amount=Decimal("150.00"), gst_amount=Decimal("0"),
                       gst_creditable=True, status=APPROVED,
                       created_by=admin.id))
        period = PayrollPeriod(year=2041, month=6, status="approved")
        db.add(period)
        db.flush()
        db.add(PayrollEntry(period_id=period.id, employee_id=admin.employee_id,
                            gross=Decimal("200.00"), net=Decimal("200.00"),
                            status="approved"))
        db.commit()
        return {"invoice_id": invoice.id, "credit_note_id": credit.id,
                "product_id": product.id, "batch_id": batch.id,
                "head_id": head.id}


@pytest.fixture(scope="module")
def full_month(world):
    _set_tracking(date(2030, 1, 1))
    return _seed_full_month(world)


def _statement(year: int, month: int) -> dict:
    start, end = _first_last(year, month)
    with SessionLocal() as db:
        return profit_loss.statement(db, start, end)


# ------------------------------------------------------- hand-calculated P&L
def test_hand_calculated_profit_with_gst_excluded(client, world, full_month):
    pl = _statement(*MONTH)
    with SessionLocal() as db:
        invoice = db.get(Invoice, full_month["invoice_id"])
        credit = db.get(CreditNote, full_month["credit_note_id"])

    assert pl["revenue"]["taxable"] == _dec("1000.00")
    assert pl["revenue"]["invoices"] == 1
    assert pl["returns"]["taxable"] == _dec("100.00")
    assert pl["returns"]["count"] == 1
    assert pl["net_revenue"] == _dec("900.00")

    assert pl["cogs"]["value"] == _dec("400.00")
    assert pl["cogs"]["invoices_total"] == 1
    assert pl["cogs"]["invoices_costed"] == 1
    assert pl["cogs"]["costed"] is True
    assert pl["gross_profit"]["value"] == _dec("500.00")
    assert pl["gross_profit"]["partial"] is False
    assert pl["gross_profit"]["label"] == "Gross profit"

    assert pl["expenses"]["total"] == _dec("150.00")
    assert pl["expenses"]["complete"] is True
    assert pl["payroll"]["total"] == _dec("200.00")
    assert pl["payroll"]["complete"] is True

    assert pl["net_profit"]["available"] is True
    assert pl["net_profit"]["value"] == _dec("150.00")
    assert pl["gaps"] == []

    # GST is on both documents, and it is not part of any profit figure.
    assert invoice.tax_total == _dec("180.00")
    assert invoice.grand_total == _dec("1180.00")
    assert credit.tax_total == _dec("18.00")
    assert credit.grand_total == _dec("118.00")
    assert pl["net_revenue"] == invoice.taxable_value - credit.taxable_value
    assert pl["net_revenue"] != invoice.grand_total - credit.grand_total
    assert any("before GST" in note for note in pl["notes"])


def test_non_creditable_gst_is_added_to_expense_cost(client, world):
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        admin = _admin(db)
        head = ExpenseHead(name=f"Office {suffix}")
        db.add(head)
        db.flush()
        db.add_all([
            # 100 + 18 GST that cannot be reclaimed: cost 118.
            Expense(head_id=head.id, entry_date=date(2041, 7, 3),
                    amount=Decimal("100.00"), gst_amount=Decimal("18.00"),
                    gst_creditable=False, status=APPROVED, created_by=admin.id),
            # 50 + 9 GST that is reclaimed: cost 50, not 59.
            Expense(head_id=head.id, entry_date=date(2041, 7, 4),
                    amount=Decimal("50.00"), gst_amount=Decimal("9.00"),
                    gst_creditable=True, status=APPROVED, created_by=admin.id),
        ])
        period = PayrollPeriod(year=2041, month=7, status="approved")
        db.add(period)
        db.commit()

    with _tracking_from(date(2030, 1, 1)):
        pl = _statement(*GST_MONTH)
    assert pl["expenses"]["total"] == _dec("168.00")
    assert pl["expenses"]["net"] == _dec("150.00")
    assert pl["expenses"]["gst_noncreditable"] == _dec("18.00")
    head_row = next(row for row in pl["expenses"]["by_head"]
                    if row["head"].startswith("Office"))
    assert head_row["amount"] == _dec("168.00")
    assert head_row["net"] == _dec("150.00")
    # No invoices in this month, so cost is zero and the expense is the loss.
    assert pl["cogs"]["value"] == _dec("0.00")
    assert pl["net_profit"]["value"] == _dec("-168.00")


# ------------------------------------------------------------------- gaps
def test_uncosted_invoice_makes_gross_profit_partial(client, world):
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        admin = _admin(db)
        product = Product(sku=f"GAP-{suffix}", name="Gap product", pack_size="10 tabs",
                          mrp=Decimal("100"), hsn=world["hsn"], uqc="TAB",
                          status="active")
        db.add(product)
        db.flush()
        order = SalesOrder(so_number=f"GSO-{suffix}",
                           distributor_id=world["distributor_id"],
                           status="dispatched", total=Decimal("500.00"),
                           created_by=admin.id)
        db.add(order)
        db.flush()
        handle = _Order(id=order.id, order_id=order.id, batch_id=None,
                        product_id=product.id, sku=product.sku,
                        product_name=product.name)
        _invoice(db, world=world, admin=admin, order=handle,
                 number=f"G{suffix}", when=date(2041, 8, 5), taxable="500.00",
                 tax="90.00", qty="20", rate="25.00", with_issue=False)
        db.commit()

    with _tracking_from(date(2030, 1, 1)):
        pl = _statement(*GAP_MONTH)
    codes = {gap["code"] for gap in pl["gaps"]}
    assert "GAP-P01" in codes
    gap = next(gap for gap in pl["gaps"] if gap["code"] == "GAP-P01")
    assert gap["fix"] == "#/inventory/ledger"
    assert "no stock issue is attributed" in gap["detail"]
    assert pl["cogs"]["costed"] is False
    assert pl["cogs"]["invoices_costed"] == 0
    assert "0 of 1 invoices costed" in pl["gross_profit"]["label"]
    assert pl["gross_profit"]["partial"] is True
    assert pl["net_profit"]["available"] is False
    assert pl["net_profit"]["value"] is None


def test_expenses_before_tracking_start_are_a_gap_not_a_zero(client, world):
    with _tracking_from(date(2041, 8, 20)):
        pl = _statement(*GAP_MONTH)
    codes = {gap["code"] for gap in pl["gaps"]}
    assert "GAP-P02" in codes
    gap = next(gap for gap in pl["gaps"] if gap["code"] == "GAP-P02")
    assert gap["fix"] == "#/expenses"
    assert "2041-08-20" in gap["detail"]
    assert pl["expenses"]["complete"] is False
    assert pl["expenses"]["missing_from"] == "2041-08-20"
    assert pl["expenses"]["tracked_from"] == "2041-08-20"
    assert pl["net_profit"]["available"] is False


def test_payroll_gap_names_absent_and_unapproved_months(client, world):
    with SessionLocal() as db:
        period = PayrollPeriod(year=2041, month=10, status="draft")
        db.add(period)
        db.flush()
        admin = _admin(db)
        db.add(PayrollEntry(period_id=period.id, employee_id=admin.employee_id,
                            gross=Decimal("999.00"), net=Decimal("999.00"),
                            status="draft"))
        db.commit()

    with _tracking_from(date(2030, 1, 1)):
        start, _end = _first_last(*PAYROLL_MONTH)
        _, end = _first_last(2041, 10)
        with SessionLocal() as db:
            pl = profit_loss.statement(db, start, end)
        assert pl["payroll"]["complete"] is False
        gap = next(gap for gap in pl["gaps"] if gap["code"] == "GAP-P03")
        assert gap["fix"] == "#/hr"
        assert "2041-09 (no period)" in gap["detail"]
        assert "2041-10 (draft)" in gap["detail"]
        assert pl["payroll"]["total"] == _dec("0.00")

        # Approving September includes its whole month, never a prorated figure.
        with SessionLocal() as db:
            approved = PayrollPeriod(year=2041, month=9, status="approved")
            db.add(approved)
            db.flush()
            db.add(PayrollEntry(period_id=approved.id,
                                employee_id=_admin(db).employee_id,
                                gross=Decimal("111.00"), net=Decimal("111.00"),
                                status="approved"))
            db.commit()
        with SessionLocal() as db:
            pl = profit_loss.statement(db, start, end)
    assert pl["payroll"]["total"] == _dec("111.00")
    assert pl["payroll"]["complete"] is False          # October is still a draft
    assert pl["net_profit"]["available"] is False


# --------------------------------------------------------------- exports
def _export(client, fmt, **params):
    return client.as_user("admin").get(
        "/api/reports/profit_and_loss/export",
        params={"format": fmt, "from": "2041-06-01", "to": "2041-06-30", **params})


def test_profit_and_loss_csv_is_reconciled_and_carries_the_notes(client, full_month):
    res = _export(client, "csv")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf")

    text = res.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    by_line = {row[1]: row[2] for row in rows if len(row) >= 3}
    assert rows[0] == ["Section", "Line", "Amount", "Note"]
    assert by_line["Revenue (taxable)"] == "1000.00"
    assert by_line["Less returns (taxable)"] == "-100.00"
    assert by_line["Net revenue"] == "900.00"
    assert by_line["Cost of goods sold"] == "400.00"
    assert by_line["Gross profit"] == "500.00"
    assert by_line["Total expenses"] == "150.00"
    assert by_line["Payroll (gross)"] == "200.00"
    assert by_line["Net profit"] == "150.00"
    assert "All 9 checks agree with the records" in text
    assert "DOES NOT RECONCILE" not in text
    assert "weighted average" in text
    assert "before GST" in text


def test_profit_and_loss_reconciliation_table_agrees(client, full_month):
    res = _export(client, "csv", table="reconciliation")
    assert res.status_code == 200, res.text
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0] == ["Check", "Report", "Records", "Result"]
    checks = {row[0]: row for row in rows[1:]
              if len(row) == 4 and row[3] in ("Agrees", "DIFFERS")}
    assert {"revenue", "returns", "net_revenue", "gross_profit", "expenses",
            "payroll", "net_profit"} <= set(checks)
    assert all(row[3] == "Agrees" for row in checks.values()), checks
    assert checks["net_profit"][1].endswith("150.0")
    assert checks["expenses"][1].endswith("150.0")


def test_profit_and_loss_xlsx_has_statement_reconciliation_and_notes(client, full_month):
    res = _export(client, "xlsx")
    assert res.status_code == 200, res.text
    assert res.content[:2] == b"PK"

    wb = load_workbook(io.BytesIO(res.content))
    # The statement's own reconciliation table is kept apart from the exporter's
    # checks sheet, so opening "Reconciliation" always shows the checks.
    assert {"Profit and Loss", "Reconciliation (report)", "Reconciliation",
            "Notes"} <= set(wb.sheetnames)
    statement = wb["Profit and Loss"]
    lines = {row[1].value for row in statement.iter_rows(min_row=2)}
    assert {"Revenue (taxable)", "Cost of goods sold", "Total expenses",
            "Payroll (gross)", "Net profit"} <= lines
    results = [row[5] for row in wb["Reconciliation"].iter_rows(
        min_row=2, values_only=True) if row[0] is not None]
    assert results and set(results) == {"Agrees"}
    notes = " ".join(str(c.value) for row in wb["Notes"].iter_rows()
                     for c in row if c.value)
    assert "weighted average" in notes
    assert "purchase-order rate without freight or discounts" in notes


def test_profit_and_loss_pdf_opens_and_states_the_result(client, full_month):
    res = _export(client, "pdf")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(res.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Profit and Loss" in text
    assert "All checks agree with the records" in text
    assert "Net profit" in text
    assert "150.00" in text


def test_profit_and_loss_needs_accounts_reports_and_export(client, full_month):
    assert client.as_user("sales").get(
        "/api/reports/profit_and_loss", params={"from": "2041-06-01",
                                                "to": "2041-06-30"}).status_code == 403
    assert client.as_user("sales").get(
        "/api/reports/profit_and_loss/export",
        params={"format": "csv"}).status_code == 403
    assert client.as_user("viewer").get(
        "/api/reports/profit_and_loss/export",
        params={"format": "csv"}).status_code == 403
    assert client.as_user("staff").get(
        "/api/reports/profit_and_loss").status_code == 403
    admin = client.as_user("admin")
    assert admin.get("/api/reports/profit_and_loss").status_code == 200


# ------------------------------------------------------- expenses menu/roles
def test_expenses_menu_follows_the_central_permission_map(client):
    js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'expenses: "accounts"' in js                     # feature switch
    assert 'expenses: "expense:read"' in js                 # route permission
    assert 'showView("expenses", can("expense:read"))' in js  # sidebar entry
    assert 'data-v="expenses"' in html
    assert 'id="navExpenses"' in html

    for role in ("admin", "sales", "viewer", "staff"):
        me = client.as_user(role).get("/api/auth/me")
        assert me.status_code == 200, me.text
        allowed = "expense:read" in set(me.json()["permissions"])
        # The menu shows the entry exactly when the server grants its permission.
        listed = client.as_user(role).get("/api/expenses")
        assert listed.status_code == (200 if allowed else 403), role
        assert client.as_user(role).get("/api/expenses/heads").status_code == (
            200 if allowed else 403), role
        assert client.as_user(role).get("/api/expenses/settings").status_code == (
            200 if allowed else 403), role
        assert client.as_user(role).get("/api/reports/profit_and_loss").status_code == (
            200 if allowed else 403), role
