"""Geography: state comes from the issued invoice snapshot, the total reconciles,
and district/city/pincode are reported as gaps rather than guessed."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.models.core import (CreditNote, Distributor, Invoice, InvoiceLine,
                             SalesOrder, User)

TODAY = date.today()
FIRST = TODAY.replace(day=1)


@pytest.fixture(autouse=True)
def _drop_geo_credit_notes():
    """Keep this module's notes out of the GST register row count other tests check."""
    yield
    with SessionLocal() as db:
        db.execute(delete(CreditNote).where(CreditNote.credit_note_number.like("GT%")))
        db.commit()


def _dec(value):
    return Decimal(str(value))


def _month_end(first: date) -> date:
    nxt = date(first.year + (first.month // 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _invoice(world, day: date, grand: Decimal, state: str | None = "07",
             distributor_id: int | None = None) -> int:
    """A synthetic issued invoice, optionally without a state snapshot."""
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        suffix = uuid4().hex[:6].upper()
        order = SalesOrder(so_number=f"T-GEO-{suffix}",
                           distributor_id=distributor_id or world["distributor_id"],
                           status="dispatched", total=grand, created_by=actor.id)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_number=f"G{suffix}"[:16],
            financial_year=f"{day.year}-{(day.year + 1) % 100:02d}",
            sales_order_id=order.id,
            distributor_id=distributor_id or world["distributor_id"],
            status="issued", invoice_date=day,
            place_of_supply_state_code=state or "27",
            place_of_supply_kind="intra",
            seller_legal_name="Herbanova Test Co", buyer_name="Test distributor",
            buyer_state_code=state, taxable_value=grand, grand_total=grand,
            issued_by=actor.id)
        db.add(invoice)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=invoice.id, product_id=world["product_id"],
            sku=world["sku"], product_name="Test product", qty=Decimal("1"),
            unit_price=grand, mrp=grand, discount_percent=Decimal("0"),
            discount_amount=Decimal("0"), taxable_value=grand, line_total=grand))
        db.commit()
        return invoice.id


def _credit_note(world, invoice_id: int, day: date, grand: Decimal,
                 reason: str) -> int:
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        invoice = db.get(Invoice, invoice_id)
        suffix = uuid4().hex[:6].upper()
        note = CreditNote(
            credit_note_number=f"GT{suffix}"[:16],
            financial_year=f"{day.year}-{(day.year + 1) % 100:02d}",
            invoice_id=invoice.id, sales_order_id=invoice.sales_order_id,
            distributor_id=invoice.distributor_id, status="issued",
            note_date=day, reason=reason, taxable_value=grand,
            grand_total=grand, issued_by=actor.id)
        db.add(note)
        db.commit()
        return note.id


def _geo(client, user="admin", **params):
    r = client.as_user(user).get("/api/dashboard/geo", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _state_total(code: str | None, start: date, end: date) -> Decimal:
    with SessionLocal() as db:
        effective = func.coalesce(Invoice.buyer_state_code, Distributor.state_code)
        condition = effective.is_(None) if code is None else effective == code
        return db.scalar(
            select(func.coalesce(func.sum(Invoice.grand_total), 0))
            .select_from(Invoice)
            .join(Distributor, Distributor.id == Invoice.distributor_id)
            .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                   Invoice.invoice_date <= end, condition)) or Decimal(0)


def _all_total(start: date, end: date) -> Decimal:
    with SessionLocal() as db:
        return db.scalar(
            select(func.coalesce(func.sum(Invoice.grand_total), 0)).where(
                Invoice.status == "issued", Invoice.invoice_date >= start,
                Invoice.invoice_date <= end)) or Decimal(0)


def _row(body, code):
    return next(r for r in body["states"] if r["code"] == code)


def test_states_reconcile_with_issued_invoices(client, world):
    _invoice(world, TODAY, Decimal("1000.00"), state="07")
    _invoice(world, TODAY, Decimal("500.00"), state="07")
    _invoice(world, TODAY, Decimal("250.00"), state="06")

    body = _geo(client)
    start = date.fromisoformat(body["from"])
    end = date.fromisoformat(body["to"])

    assert _dec(body["totals"]["sales"]) == _all_total(start, end)
    assert _dec(_row(body, "07")["sales"]) == _state_total("07", start, end)
    assert _dec(_row(body, "06")["sales"]) == _state_total("06", start, end)
    assert _row(body, "07")["name"] == "Delhi"
    assert _row(body, "06")["name"] == "Haryana"
    assert _row(body, "07")["share"] is not None

    ranked = [r["code"] for r in body["top"]]
    values = [_dec(r["sales"]) for r in body["top"]]
    assert values == sorted(values, reverse=True)
    assert "07" in ranked

    # The map lists every known state, including those with no invoice.
    assert len(body["map"]) == 37
    assert next(m for m in body["map"] if m["code"] == "07")["recorded"] is True
    assert next(m for m in body["map"] if m["code"] == "09")["recorded"] is False

    levels = {x["level"]: x for x in body["levels"]}
    assert levels["state"]["available"] is True
    for name in ("district", "city", "pincode"):
        assert levels[name]["available"] is False
        assert levels[name]["gap"] == "GAP-V11"


def test_missing_snapshot_falls_back_and_unrecorded_row_keeps_the_total(client, world):
    fallback_id = _invoice(world, TODAY, Decimal("300.00"), state=None)
    with SessionLocal() as db:
        distributor = Distributor(
            code=f"TG-{uuid4().hex[:6].upper()}", name="No-state distributor",
            territory="Test", status="active", credit_limit=Decimal("0"),
            state_code=None, registration_type="unregistered")
        db.add(distributor)
        db.flush()
        distributor_id = distributor.id
        db.commit()
    unrecorded_id = _invoice(world, TODAY, Decimal("200.00"), state=None,
                             distributor_id=distributor_id)

    body = _geo(client)
    start = date.fromisoformat(body["from"])
    end = date.fromisoformat(body["to"])
    assert _dec(body["totals"]["sales"]) == _all_total(start, end)
    assert body["basis"]["snapshot"] >= 0
    assert body["basis"]["fallback"] >= 1
    assert body["basis"]["unrecorded"] >= 1

    unrecorded = body["unrecorded"]
    assert unrecorded["name"] == "Location not recorded"
    assert unrecorded["recorded"] is False
    assert _dec(unrecorded["sales"]) >= Decimal("200.00")
    assert unrecorded["key"] == "unrecorded"

    # The fallback invoice landed in Maharashtra (the world distributor's state).
    assert _dec(_row(body, "27")["sales"]) == _state_total("27", start, end)
    assert fallback_id and unrecorded_id


def test_date_window_and_validation(client, world):
    old_day = FIRST - timedelta(days=40)
    _invoice(world, old_day, Decimal("999.00"), state="07")
    _invoice(world, TODAY, Decimal("10.00"), state="09")

    body = _geo(client, from_date=TODAY.isoformat(), to_date=TODAY.isoformat())
    assert body["from"] == TODAY.isoformat() and body["to"] == TODAY.isoformat()
    assert _dec(body["totals"]["sales"]) == _all_total(TODAY, TODAY)
    assert all(r["code"] != "07" or _dec(r["sales"]) == _state_total("07", TODAY, TODAY)
               for r in body["states"])

    admin = client.as_user("admin")
    assert admin.get("/api/dashboard/geo", params={
        "from_date": TODAY.isoformat(),
        "to_date": (TODAY - timedelta(days=1)).isoformat()}).status_code == 422
    assert admin.get("/api/dashboard/geo", params={
        "to_date": (TODAY + timedelta(days=1)).isoformat()}).status_code == 422


def test_returns_gst_and_role_scoping(client, world):
    invoice_id = _invoice(world, TODAY, Decimal("1180.00"), state="07")
    _credit_note(world, invoice_id, TODAY, Decimal("118.00"),
                 "Damaged cartons on arrival")

    admin = _geo(client)
    assert admin["gst"]["available"] is True
    gst_row = next(r for r in admin["gst"]["rows"] if r["code"] == "07")
    assert _dec(gst_row["taxable"]) >= Decimal("1180.00")
    assert admin["returns"]["available"] is True
    assert admin["returns"]["count"] >= 1
    assert any("Damaged cartons" in reason
               for row in admin["returns"]["rows"] for reason in row["reasons"])

    viewer = _geo(client, user="viewer")
    assert viewer["gst"]["available"] is False
    assert viewer["gst"]["gap"] == "tax:read"
    assert viewer["returns"]["available"] is False
    assert viewer["returns"]["gap"] == "accounts:read"
    assert all("taxable" not in r and "return_value" not in r
               for r in viewer["states"])
    assert _dec(viewer["totals"]["sales"]) == _dec(admin["totals"]["sales"])

    assert client.as_user("payroll").get("/api/dashboard/geo").status_code == 403
