"""Input GST, net payable and statutory dues (GAP-A05, GAP-A06, GAP-A07).

Every figure is compared with the bill, the register or the payroll the test
itself wrote, so a screen can never show tax the documents do not support. The
tests also prove the honest limits: with no supplier bill there is no input
data, blocked credit is never netted, and a draft payroll is not a liability.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import Invoice, InvoiceLine, SalesOrder, User
from app.models.hr import (PayrollEntry, PayrollEntryLine, PayrollPeriod,
                           SalaryComponent)
from app.services import statutory

TODAY = date.today()
MONTH = (2025, 7)
DAY = date(2025, 7, 10)


def _dec(value) -> Decimal:
    return Decimal(str(value))


def _admin(db):
    return db.scalar(select(User).where(User.username == "admin"))


def _issued_invoice(world, day: date, taxable: str, cgst: str, sgst: str) -> int:
    """An issued invoice with GST stored, written straight into the test DB."""
    with SessionLocal() as db:
        actor = _admin(db)
        suffix = uuid4().hex[:6].upper()
        order = SalesOrder(so_number=f"GST-T-{suffix}",
                           distributor_id=world["distributor_id"],
                           status="dispatched", total=Decimal(taxable),
                           created_by=actor.id)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_number=f"GT{suffix}"[:16], financial_year="2025-26",
            sales_order_id=order.id, distributor_id=world["distributor_id"],
            status="issued", invoice_date=day,
            place_of_supply_state_code="27", place_of_supply_kind="intra",
            seller_legal_name="Herbanova Test Co",
            buyer_name="Test distributor",
            gross_total=Decimal(taxable) + Decimal(cgst) + Decimal(sgst),
            taxable_value=Decimal(taxable), cgst_total=Decimal(cgst),
            sgst_total=Decimal(sgst), igst_total=Decimal("0"),
            cess_total=Decimal("0"),
            tax_total=Decimal(cgst) + Decimal(sgst),
            round_off=Decimal("0"),
            grand_total=Decimal(taxable) + Decimal(cgst) + Decimal(sgst),
            issued_by=actor.id)
        db.add(invoice)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=invoice.id, product_id=world["product_id"],
            sku=world["sku"], product_name="Test product", qty=Decimal("1"),
            unit_price=Decimal(taxable), mrp=Decimal("100"),
            discount_percent=Decimal("0"), discount_amount=Decimal("0"),
            taxable_value=Decimal(taxable), cgst_rate=Decimal("9"),
            sgst_rate=Decimal("9"), cgst_amount=Decimal(cgst),
            sgst_amount=Decimal(sgst),
            line_total=Decimal(taxable) + Decimal(cgst) + Decimal(sgst)))
        db.commit()
        return invoice.id


def _bill(client, world, **overrides):
    suffix = uuid4().hex[:6].upper()
    body = {
        "supplier_id": world["supplier_id"],
        "supplier_invoice_number": f"SUP-{suffix}",
        "invoice_date": DAY.isoformat(),
        "taxable_value": "1000.00",
        "cgst_amount": "90.00",
        "sgst_amount": "90.00",
        "igst_amount": "0.00",
        "cess_amount": "0.00",
        "itc_eligible": True,
    }
    body.update(overrides)
    return client.as_user("admin").post("/api/accounts/purchase-invoices", json=body)


# ------------------------------------------------------- the honest empty case

def test_with_no_supplier_bill_input_tax_is_unavailable_not_zero(client, world):
    admin = client.as_user("admin")
    net = admin.get("/api/accounts/gst-net")
    assert net.status_code == 200, net.text
    body = net.json()
    assert body["available"] is False
    assert body["input_total"] == "0.00"
    assert "supplier bill" in body["reason"]

    register = admin.get("/api/accounts/input-gst").json()
    assert register["available"] is False
    assert register["rows"] == []

    report = admin.get("/api/accounts/report", params={
        "from_date": "2025-10-01", "to_date": "2025-10-31"}).json()
    assert report["net_gst"]["available"] is False
    assert report["net_gst"]["input_total"] == "0.00"
    assert report["net_gst"]["expense_itc"]["included_in_net"] is False


# ------------------------------------------------------ capture, tax and reverse

def test_a_supplier_bill_records_its_tax_and_a_wrong_one_is_reversed(client, world):
    admin = client.as_user("admin")
    ref = f"SUP-{uuid4().hex[:6].upper()}"
    created = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": world["supplier_id"],
        "supplier_invoice_number": ref,
        "invoice_date": DAY.isoformat(),
        "taxable_value": "1000.00", "cgst_amount": "90.00",
        "sgst_amount": "90.00", "itc_eligible": True,
    })
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["supplier_invoice_number"] == ref
    assert row["tax_total"] == "180.00"
    assert row["total"] == "1180.00"
    assert row["status"] == "posted"
    bill_id = row["id"]

    duplicate = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": world["supplier_id"],
        "supplier_invoice_number": ref,
        "invoice_date": DAY.isoformat(),
        "taxable_value": "1000.00",
    })
    assert duplicate.status_code == 409

    # A reversal needs a real reason; then the bill is excluded but kept.
    assert admin.post(f"/api/accounts/purchase-invoices/{bill_id}/reverse",
                      json={"reason": "no"}).status_code == 422
    reversed_ = admin.post(f"/api/accounts/purchase-invoices/{bill_id}/reverse",
                           json={"reason": "supplier cancelled the tax invoice"})
    assert reversed_.status_code == 200, reversed_.text
    kept = next(r for r in reversed_.json()["rows"] if r["id"] == bill_id)
    assert kept["status"] == "reversed"
    assert kept["reversal_reason"] == "supplier cancelled the tax invoice"
    assert admin.post(f"/api/accounts/purchase-invoices/{bill_id}/reverse",
                      json={"reason": "reversing twice is refused"}).status_code == 409

    hidden = admin.get("/api/accounts/input-gst").json()
    assert all(r["id"] != bill_id for r in hidden["rows"])


def test_a_bill_number_is_unique_per_supplier_only(client, world):
    admin = client.as_user("admin")
    shared = f"DUP-{uuid4().hex[:6].upper()}"
    first = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": world["supplier_id"], "supplier_invoice_number": shared,
        "invoice_date": DAY.isoformat(), "taxable_value": "10.00"})
    assert first.status_code == 201, first.text
    with SessionLocal() as db:
        from app.models.suppliers import Supplier
        other = Supplier(code=f"OS-{uuid4().hex[:6].upper()}", name="Other supplier",
                         status="active")
        db.add(other)
        db.commit()
        other_id = other.id
    second = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": other_id, "supplier_invoice_number": shared,
        "invoice_date": DAY.isoformat(), "taxable_value": "10.00"})
    assert second.status_code == 201, second.text


# ------------------------------------------------ net payable at one month end

def test_net_payable_is_output_less_eligible_input(client, world):
    admin = client.as_user("admin")
    eligible = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": world["supplier_id"],
        "supplier_invoice_number": f"NET-E-{uuid4().hex[:6].upper()}",
        "invoice_date": DAY.isoformat(), "taxable_value": "500.00",
        "cgst_amount": "40.00", "sgst_amount": "40.00"})
    assert eligible.status_code == 201, eligible.text
    blocked = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": world["supplier_id"],
        "supplier_invoice_number": f"NET-B-{uuid4().hex[:6].upper()}",
        "invoice_date": DAY.isoformat(), "taxable_value": "200.00",
        "cgst_amount": "10.00", "sgst_amount": "10.00",
        "itc_eligible": False})
    assert blocked.status_code == 201, blocked.text
    _issued_invoice(world, date(2025, 7, 12), "1000.00", "90.00", "90.00")

    net = admin.get("/api/accounts/gst-net", params={
        "date_from": "2025-07-01", "date_to": "2025-07-31"}).json()
    assert net["available"] is True
    assert _dec(net["output"]["cgst"]) == Decimal("90.00")
    assert _dec(net["input"]["cgst"]) == Decimal("40.00")
    assert _dec(net["input_total"]) == Decimal("80.00")
    assert _dec(net["blocked_total"]) == Decimal("20.00")
    assert _dec(net["net"]["cgst"]) == Decimal("50.00")
    assert _dec(net["net_total"]) == Decimal("100.00")

    register = admin.get("/api/accounts/input-gst", params={
        "date_from": "2025-07-01", "date_to": "2025-07-31"}).json()
    assert _dec(register["eligible"]["cgst"]) == Decimal("40.00")
    assert _dec(register["blocked"]["cgst"]) == Decimal("10.00")
    assert register["blocked_count"] == 1


# -------------------------------------------------- filed return reconciliation

def test_a_filed_return_is_compared_with_the_registers(client, world):
    admin = client.as_user("admin")
    year, month = 2025, 7
    computed = admin.get("/api/accounts/gst-reconciliation", params={
        "year": year, "month": month}).json()
    assert computed["available"] is False
    assert computed["computed"]["input_available"] is True

    def filed(**overrides):
        body = {
            "form": "GSTR-3B", "year": year, "month": month,
            "filed_on": "2025-08-20", "reference": "ACK-1",
            "outward_taxable": "1000.00", "outward_cgst": "90.00",
            "outward_sgst": "90.00", "itc_cgst": "40.00", "itc_sgst": "40.00",
        }
        body.update(overrides)
        return admin.post("/api/accounts/gst-returns", json=body)

    saved = filed()
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["available"] is True
    three_b = next(f for f in body["forms"] if f["form"] == "GSTR-3B")
    assert three_b["ok"] is True, three_b["differences"]
    check = {c["key"]: c for c in three_b["checks"]}
    assert _dec(check["tax_payable"]["difference"]) == Decimal("0.00")

    # A portal amendment is captured by replacing the figures, not adding a row.
    amended = filed(outward_cgst="95.00", reference="ACK-2")
    assert amended.status_code == 200, amended.text
    three_b = next(f for f in amended.json()["forms"] if f["form"] == "GSTR-3B")
    assert three_b["ok"] is False
    assert "outward_cgst" in three_b["differences"]
    check = {c["key"]: c for c in three_b["checks"]}
    assert _dec(check["outward_cgst"]["difference"]) == Decimal("5.00")
    assert check["outward_cgst"]["ok"] is False

    listed = admin.get("/api/accounts/gst-returns", params={"year": year}).json()
    rows = [r for r in listed["rows"] if r["form"] == "GSTR-3B" and r["month"] == month]
    assert len(rows) == 1
    assert rows[0]["reference"] == "ACK-2"

    # GSTR-1 reports outward supplies only, and a future month is refused.
    assert filed(form="GSTR-1", itc_cgst="10.00").status_code == 422
    assert filed(form="GSTR-4").status_code == 422
    future = (TODAY.year + 1, 1)
    assert filed(year=future[0], month=future[1]).status_code == 422


# ------------------------------------------------------------- statutory dues

def _pf_component(db, amount: Decimal, period: tuple[int, int], status: str):
    """A payroll period with one statutory PF line, inactive so it cannot leak
    into another file's "configured components" list."""
    suffix = uuid4().hex[:6].upper()
    component = SalaryComponent(code=f"PF-{suffix}", name="Provident fund",
                                kind="deduction", statutory=True,
                                statutory_head="pf", active=False)
    db.add(component)
    db.flush()
    pf_period = PayrollPeriod(year=period[0], month=period[1], status=status)
    db.add(pf_period)
    db.flush()
    actor = _admin(db)
    entry = PayrollEntry(period_id=pf_period.id, employee_id=actor.employee_id,
                         gross=Decimal("1000.00"), net=Decimal("500.00"),
                         status=status)
    db.add(entry)
    db.flush()
    line = PayrollEntryLine(entry_id=entry.id, component_id=component.id,
                            name="Provident fund", kind="deduction", amount=amount)
    db.add(line)
    db.commit()
    return {"line": line.id, "entry": entry.id, "period": pf_period.id,
            "component": component.id}


def _drop_pf(db, rows: list[dict]):
    for row in rows:
        db.delete(db.get(PayrollEntryLine, row["line"]))
        db.delete(db.get(PayrollEntry, row["entry"]))
        db.delete(db.get(PayrollPeriod, row["period"]))
        db.delete(db.get(SalaryComponent, row["component"]))
    db.commit()


def test_statutory_dues_read_vendor_tds_and_approved_payroll_only(client, world):
    admin = client.as_user("admin")
    with SessionLocal() as db:
        created = [_pf_component(db, Decimal("500.00"), (2025, 9), "approved"),
                   _pf_component(db, Decimal("999.00"), (2022, 3), "draft")]
    try:
        bill = admin.post("/api/accounts/purchase-invoices", json={
            "supplier_id": world["supplier_id"],
            "supplier_invoice_number": f"TDS-{uuid4().hex[:6].upper()}",
            "invoice_date": "2025-09-10", "taxable_value": "1000.00",
            "cgst_amount": "90.00", "sgst_amount": "90.00",
            "tds_section": "194C", "tds_rate": "2", "tds_amount": "20.00"})
        assert bill.status_code == 201, bill.text

        # A section without an amount, or an amount without a section, is incomplete.
        assert admin.post("/api/accounts/purchase-invoices", json={
            "supplier_id": world["supplier_id"],
            "supplier_invoice_number": f"BAD-{uuid4().hex[:6].upper()}",
            "invoice_date": "2025-09-10", "taxable_value": "10.00",
            "tds_section": "194C"}).status_code == 422

        dues = admin.get("/api/accounts/statutory-dues", params={
            "date_from": "2025-09-01", "date_to": "2025-09-30"}).json()
        assert dues["available"] is True
        summary = {row["kind"]: row for row in dues["summary"]}
        assert _dec(summary["tds"]["withheld_to_date"]) == Decimal("20.00")
        assert _dec(summary["pf"]["withheld_to_date"]) == Decimal("500.00")
        assert _dec(summary["pf"]["outstanding"]) == Decimal("500.00")
        assert dues["vendor_tds"]["sections"][0]["section"] == "194C"

        challan = admin.post("/api/accounts/statutory-challans", json={
            "kind": "pf", "challan_number": f"CH-{uuid4().hex[:6].upper()}",
            "paid_on": "2025-09-20", "amount": "300.00",
            "period_year": 2025, "period_month": 8})
        assert challan.status_code == 201, challan.text
        dues = admin.get("/api/accounts/statutory-dues", params={
            "date_from": "2025-09-01", "date_to": "2025-09-30"}).json()
        summary = {row["kind"]: row for row in dues["summary"]}
        assert _dec(summary["pf"]["outstanding"]) == Decimal("200.00")
        assert _dec(summary["pf"]["deposited_in_window"]) == Decimal("300.00")

        listed = admin.get("/api/accounts/statutory-challans",
                           params={"kind": "pf"}).json()
        assert _dec(listed["total"]) >= Decimal("300.00")
        assert admin.get("/api/accounts/statutory-challans",
                         params={"kind": "gst"}).status_code == 422
        assert admin.post("/api/accounts/statutory-challans", json={
            "kind": "pf", "challan_number": "CH-FUTURE", "paid_on": "2025-09-20",
            "amount": "10.00", "period_year": TODAY.year + 1,
            "period_month": 1}).status_code == 422
    finally:
        with SessionLocal() as db:
            _drop_pf(db, created)


def test_a_draft_payroll_is_not_a_statutory_liability(client, world):
    with SessionLocal() as db:
        created = [_pf_component(db, Decimal("999.00"), (2022, 3), "draft")]
    try:
        with SessionLocal() as db:
            dues = statutory.dues(db, date(2022, 3, 1), date(2022, 3, 31))
        assert dues["available"] is False
        summary = {row["kind"]: row for row in dues["summary"]}
        assert summary["pf"]["withheld_to_date"] is None
        assert "No approved payroll" in dues["payroll"]["reason"] or \
            dues["payroll"]["available"] is False
    finally:
        with SessionLocal() as db:
            _drop_pf(db, created)


# ----------------------------------------------------- permissions and gates

def test_reads_follow_accounts_read_and_writes_stay_with_the_administrator(client):
    sales = client.as_user("sales")
    for path in ("/api/accounts/purchase-invoices", "/api/accounts/input-gst",
                 "/api/accounts/gst-net", "/api/accounts/gst-reconciliation",
                 "/api/accounts/statutory-dues", "/api/accounts/statutory-challans"):
        assert sales.get(path).status_code == 200, path
    denied = sales.post("/api/accounts/purchase-invoices", json={
        "supplier_id": 1, "supplier_invoice_number": "NOPE",
        "invoice_date": DAY.isoformat(), "taxable_value": "10.00"})
    assert denied.status_code == 403
    assert sales.post("/api/accounts/statutory-challans", json={
        "kind": "pf", "challan_number": "NOPE", "paid_on": DAY.isoformat(),
        "amount": "10.00", "period_year": 2025, "period_month": 7}).status_code == 403


def test_a_locked_month_and_a_closed_year_refuse_a_supplier_bill(client, world):
    admin = client.as_user("admin")
    lock = admin.post("/api/accounts/period-locks",
                      json={"year": 2025, "month": 8,
                            "reason": "August reconciled"})
    assert lock.status_code == 201, lock.text
    blocked = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": world["supplier_id"],
        "supplier_invoice_number": f"LOCK-{uuid4().hex[:6].upper()}",
        "invoice_date": "2025-08-05", "taxable_value": "10.00"})
    assert blocked.status_code == 423
    assert "locked" in blocked.json()["detail"]
    assert admin.post(f"/api/accounts/period-locks/{lock.json()['id']}/unlock",
                      json={"reason": "test finished"}).status_code == 200

    label = "2024-25"
    closed = admin.post(f"/api/accounts/financial-years/{label}/close",
                        json={"reason": "year closed by the test"})
    assert closed.status_code == 201, closed.text
    year_blocked = admin.post("/api/accounts/purchase-invoices", json={
        "supplier_id": world["supplier_id"],
        "supplier_invoice_number": f"FY-{uuid4().hex[:6].upper()}",
        "invoice_date": "2024-06-10", "taxable_value": "10.00"})
    assert year_blocked.status_code == 423
    assert label in year_blocked.json()["detail"]
    assert admin.post(f"/api/accounts/financial-years/{label}/reopen",
                      json={"reason": "test finished"}).status_code == 200
