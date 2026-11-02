"""Stage 2: cost is captured when stock moves and COGS is proved per invoice.

Covers the rules agreed with the business: the receipt carries the PO rate, the
issue carries a company-wide weighted average, a credit note that puts goods back
reduces COGS at the issue cost, a price-only credit note does not, an issue that
touches uncosted stock is partial (never a silent zero), and a late PO rate is
corrected by an audited replay that reports every changed invoice.
"""
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.db import SessionLocal
from app.models.core import (AuditLog, Batch, Distributor, Invoice, InvoiceLine,
                             Product, PurchaseOrder, PurchaseOrderLine, StockMovement,
                             Warehouse)
from app.models.costs import CostCorrection
from app.models.hr import PeriodLock
from app.models.suppliers import GoodsReceipt, GoodsReceiptLine
from app.services import costing
from app.services.inventory import post_movement

ROOT = Path(__file__).resolve().parent.parent


def _dec(value):
    return Decimal(str(value))


def _new_product(world, opening=0):
    """A product, warehouse and distributor of its own so tests cannot interfere."""
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        product = Product(sku=f"COST-{suffix}", name="Cost product", pack_size="10 tabs",
                          mrp=Decimal("100"), hsn=world["hsn"], uqc="TAB", status="active")
        warehouse = Warehouse(name=f"Cost wh {suffix}")
        distributor = Distributor(code=f"CD-{suffix}", name=f"Cost dist {suffix}",
                                  territory="Test", status="active",
                                  credit_limit=Decimal("1000000"), state_code="27",
                                  gstin=f"27{suffix[:5]}000A1Z5",
                                  registration_type="regular")
        db.add_all([product, warehouse, distributor])
        db.flush()
        batch = None
        if opening:
            batch = Batch(product_id=product.id, warehouse_id=warehouse.id,
                          batch_no=f"C-{suffix}", on_hand=Decimal(opening))
            db.add(batch)
            db.flush()
            # Opening stock recorded before costs existed: no unit_cost on purpose.
            db.add(StockMovement(batch_id=batch.id, movement_type="receipt",
                                 qty_delta=Decimal(opening), ref_type="opening",
                                 ref_id=f"OPEN-{suffix}", actor_id=1))
        db.commit()
        return {"product_id": product.id, "sku": product.sku,
                "warehouse_id": warehouse.id, "distributor_id": distributor.id,
                "batch_no": batch.batch_no if batch else None}


def _po(client, world, sku, qty, unit_cost=None, remark=None):
    line = {"sku": sku, "qty": str(qty)}
    if unit_cost is not None:
        line["unit_cost"] = str(unit_cost)
    if remark:
        line["rate_remark"] = remark
    r = client.as_user("admin").post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"], "lines": [line]})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["id"], body["lines"][0]["id"]


def _receive(client, po_id, warehouse_id, sku, qty, batch_no=None):
    r = client.as_user("inventory").post(f"/api/purchase-orders/{po_id}/receive", json={
        "warehouse_id": warehouse_id,
        "lines": [{"sku": sku, "batch_no": batch_no or f"R-{uuid4().hex[:6].upper()}",
                   "qty": str(qty)}]})
    assert r.status_code == 201, r.text
    return r.json()


def _dispatch(client, product, qty, price="100.00"):
    sales = client.as_user("sales")
    order = sales.post("/api/sales-orders", json={
        "distributor_id": product["distributor_id"],
        "lines": [{"sku": product["sku"], "qty": str(qty), "unit_price": price}]})
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    submitted = sales.post(f"/api/sales-orders/{order_id}/submit")
    assert submitted.status_code == 200, submitted.text
    if submitted.json()["status"] == "pending_approval":
        approval_id = submitted.json()["approval"]["id"]
        assert client.as_user("admin").post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "approve", "reason": "cost test setup"}).status_code == 200
    dispatched = client.as_user("admin").post(
        f"/api/sales-orders/{order_id}/dispatch",
        json={"warehouse_id": product["warehouse_id"]})
    assert dispatched.status_code == 201, dispatched.text
    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.sales_order_id == order_id))
        assert invoice is not None
        return order_id, invoice.id


def _issue_movements(product_id):
    with SessionLocal() as db:
        return list(db.scalars(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product_id,
                   StockMovement.movement_type == "issue")).all())


def _unlink_issues(product):
    with SessionLocal() as db:
        for m in db.scalars(
                select(StockMovement)
                .join(Batch, Batch.id == StockMovement.batch_id)
                .where(Batch.product_id == product["product_id"],
                       StockMovement.movement_type == "issue")).all():
            m.invoice_id = None
        db.commit()


def _second_invoice(invoice_id, product, world, qty):
    """A second issued invoice for the same sales order, to make it ambiguous."""
    with SessionLocal() as db:
        first = db.get(Invoice, invoice_id)
        data = {c.name: getattr(first, c.name)
                for c in Invoice.__table__.columns if c.name != "id"}
        data["invoice_number"] = f"T{uuid4().hex[:10].upper()}"
        second = Invoice(**data)
        db.add(second)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=second.id, product_id=product["product_id"],
            sku=product["sku"], product_name="Cost product", hsn=world["hsn"],
            uqc="TAB", qty=Decimal(qty), unit_price=Decimal(100), mrp=Decimal(100),
            discount_percent=Decimal(0), discount_amount=Decimal(0),
            taxable_value=Decimal(qty) * 100, line_total=Decimal(qty) * 100))
        db.commit()
        return second.id


def _fingerprint():
    with SessionLocal() as db:
        return costing.attribution_fingerprint(costing.attribution_plan(db))


def _attribution_audits():
    with SessionLocal() as db:
        return list(db.scalars(select(AuditLog).where(
            AuditLog.action == costing.ATTRIBUTION_AUDIT).order_by(AuditLog.id)).all())


def _strip_issue_cost(product):
    with SessionLocal() as db:
        for m in db.scalars(
                select(StockMovement)
                .join(Batch, Batch.id == StockMovement.batch_id)
                .where(Batch.product_id == product["product_id"],
                       StockMovement.movement_type == "issue")).all():
            m.unit_cost = None
            m.cost_source = None
        db.commit()


def _cost_fingerprint(product):
    with SessionLocal() as db:
        return costing.cost_fingerprint(
            costing.backfill_plan(db, [product["product_id"]]))


def _cost_audits():
    with SessionLocal() as db:
        return list(db.scalars(select(AuditLog).where(
            AuditLog.action == costing.COST_BACKFILL_AUDIT).order_by(AuditLog.id)).all())


def test_receipt_carries_the_purchase_order_rate(client, world):
    product = _new_product(world)
    po_id, _line = _po(client, world, product["sku"], 100, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 100)
    with SessionLocal() as db:
        movement = db.scalar(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product["product_id"],
                   StockMovement.movement_type == "receipt"))
        assert movement.unit_cost == _dec("10.00")
        assert movement.cost_source == costing.PO_RECEIPT


def test_issue_uses_the_company_wide_weighted_average(client, world):
    product = _new_product(world)
    po1, _ = _po(client, world, product["sku"], 50, "10.00")
    po2, _ = _po(client, world, product["sku"], 50, "20.00")
    _receive(client, po1, product["warehouse_id"], product["sku"], 50)
    _receive(client, po2, product["warehouse_id"], product["sku"], 50)

    _order_id, invoice_id = _dispatch(client, product, 10)

    issues = _issue_movements(product["product_id"])
    assert len(issues) == 1
    assert issues[0].unit_cost == _dec("15.00")
    assert issues[0].cost_source == costing.WEIGHTED_AVERAGE
    assert issues[0].invoice_id == invoice_id

    with SessionLocal() as db:
        cogs = costing.invoice_cogs(db, [invoice_id])[invoice_id]
    assert cogs["cogs"] == _dec("150.00")
    assert cogs["costed"] is True
    assert cogs["partial_reason"] is None


def test_two_invoices_on_one_order_are_costed_separately(client, world):
    """A split dispatch means two invoices for one order; each keeps its own COGS.

    Partial dispatch is not a screen yet, so the second invoice and its issue are
    written through the same ledger service the dispatch screen uses.
    """
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 100, "12.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 100)

    order_id, invoice_a = _dispatch(client, product, 10)

    with SessionLocal() as db:
        first = db.get(Invoice, invoice_a)
        data = {c.name: getattr(first, c.name)
                for c in Invoice.__table__.columns if c.name != "id"}
        data["invoice_number"] = f"{first.invoice_number}B"[:16]
        second = Invoice(**data)
        db.add(second)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=second.id, product_id=product["product_id"], sku=product["sku"],
            product_name="Cost product", hsn=world["hsn"], uqc="TAB", qty=Decimal(4),
            unit_price=Decimal(100), mrp=Decimal(100), discount_percent=Decimal(0),
            discount_amount=Decimal(0), taxable_value=Decimal(400),
            line_total=Decimal(400)))
        batch = db.scalar(select(Batch).where(Batch.product_id == product["product_id"]))
        post_movement(db, batch_id=batch.id, qty_delta=Decimal(-4),
                      movement_type="issue", ref_type="invoice",
                      ref_id=str(second.id), actor_id=1,
                      unit_cost=Decimal("12.00"),
                      cost_source=costing.WEIGHTED_AVERAGE, invoice_id=second.id)
        db.commit()
        invoice_b = second.id

    with SessionLocal() as db:
        result = costing.invoice_cogs(db, [invoice_a, invoice_b])
    assert result[invoice_a]["cogs"] == _dec("120.00")
    assert result[invoice_b]["cogs"] == _dec("48.00")
    assert result[invoice_a]["costed"] and result[invoice_b]["costed"]

    with SessionLocal() as db:
        order_invoices = db.scalars(
            select(Invoice.id).where(Invoice.sales_order_id == order_id)).all()
    assert set(order_invoices) == {invoice_a, invoice_b}


def test_live_dispatch_links_and_costs_every_issue(client, world):
    """The real flow: order, dispatch, invoice in one transaction, issues linked.

    Invoice creation is inside dispatch, so there is no separate "invoice after
    dispatch" step whose order could matter. This test pins that down: the
    invoice that dispatch creates is the one every issue movement points at, and
    the movement carries the weighted-average cost.
    """
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 50, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 50)

    order_id, invoice_id = _dispatch(client, product, 10)

    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        issues = _issue_movements(product["product_id"])
        cogs = costing.invoice_cogs(db, [invoice_id])[invoice_id]
        plan = costing.attribution_plan(db)
    assert invoice.sales_order_id == order_id
    assert issues
    assert all(m.invoice_id == invoice_id for m in issues)
    assert all(m.unit_cost == _dec("10.00") for m in issues)
    assert all(m.cost_source == costing.WEIGHTED_AVERAGE for m in issues)
    assert cogs["cogs"] == _dec("100.00")
    assert cogs["costed"] is True
    assert any(a["sales_order_id"] == order_id for a in plan["already_attributed"])
    assert not any(c["sales_order_id"] == order_id for c in plan["candidates"])


def test_attribution_plan_proposes_a_legacy_order_and_never_writes(client, world):
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 50, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 50)
    order_id, invoice_id = _dispatch(client, product, 10)

    with SessionLocal() as db:
        issues = list(db.scalars(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product["product_id"],
                   StockMovement.movement_type == "issue")).all())
        movement_ids = sorted(m.id for m in issues)
        for m in issues:                     # simulate a pre-0021 dispatch
            m.invoice_id = None
        db.commit()

    with SessionLocal() as db:
        plan = costing.attribution_plan(db)
    match = next(c for c in plan["candidates"] if c["sales_order_id"] == order_id)
    assert match["invoice_id"] == invoice_id
    assert match["movement_ids"] == movement_ids
    assert match["products"] == {str(product["product_id"]): "10.000"}

    with SessionLocal() as db:
        again = costing.attribution_plan(db)
        unchanged = _issue_movements(product["product_id"])
    assert again["candidates"] == plan["candidates"]
    assert all(m.invoice_id is None for m in unchanged)


def test_attribution_plan_refuses_two_invoices_and_quantity_mismatches(client, world):
    """Two issued invoices, or a quantity that differs, stay unlinked with a reason."""
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 100, "12.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 100)
    order_id, invoice_a = _dispatch(client, product, 10)

    with SessionLocal() as db:
        first = db.get(Invoice, invoice_a)
        data = {c.name: getattr(first, c.name)
                for c in Invoice.__table__.columns if c.name != "id"}
        data["invoice_number"] = f"{first.invoice_number}B"[:16]
        second = Invoice(**data)
        db.add(second)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=second.id, product_id=product["product_id"], sku=product["sku"],
            product_name="Cost product", hsn=world["hsn"], uqc="TAB", qty=Decimal(4),
            unit_price=Decimal(100), mrp=Decimal(100), discount_percent=Decimal(0),
            discount_amount=Decimal(0), taxable_value=Decimal(400),
            line_total=Decimal(400)))
        for m in db.scalars(
                select(StockMovement)
                .join(Batch, Batch.id == StockMovement.batch_id)
                .where(Batch.product_id == product["product_id"],
                       StockMovement.movement_type == "issue")).all():
            m.invoice_id = None
        db.commit()

    with SessionLocal() as db:
        plan = costing.attribution_plan(db)
    two = next(a for a in plan["ambiguous"] if a["sales_order_id"] == order_id)
    assert set(two["invoice_ids"]) == {invoice_a, second.id}
    assert "2 issued invoices" in two["reason"]
    assert not any(c["sales_order_id"] == order_id for c in plan["candidates"])

    mismatch_product = _new_product(world)
    po_id, _ = _po(client, world, mismatch_product["sku"], 50, "10.00")
    _receive(client, po_id, mismatch_product["warehouse_id"], mismatch_product["sku"], 50)
    mismatch_order, original_invoice = _dispatch(client, mismatch_product, 10)
    assert client.as_user("admin").post(
        f"/api/invoices/{original_invoice}/cancel",
        json={"reason": "reissuing for the test"}).status_code == 200
    with SessionLocal() as db:
        original = db.get(Invoice, original_invoice)
        data = {c.name: getattr(original, c.name)
                for c in Invoice.__table__.columns if c.name != "id"}
        data.update(invoice_number=f"{original.invoice_number}B"[:16], status="issued",
                    cancel_reason=None, cancelled_by=None, cancelled_at=None,
                    copy_designation="ORIGINAL")
        replacement = Invoice(**data)
        db.add(replacement)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=replacement.id, product_id=mismatch_product["product_id"],
            sku=mismatch_product["sku"], product_name="Cost product", hsn=world["hsn"],
            uqc="TAB", qty=Decimal(9), unit_price=Decimal(100), mrp=Decimal(100),
            discount_percent=Decimal(0), discount_amount=Decimal(0),
            taxable_value=Decimal(900), line_total=Decimal(900)))
        movement = db.scalars(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == mismatch_product["product_id"],
                   StockMovement.movement_type == "issue")).one()
        movement.invoice_id = None
        db.commit()
        movement_id = movement.id
    with SessionLocal() as db:
        plan = costing.attribution_plan(db)
    mismatched = next(a for a in plan["ambiguous"]
                      if a["sales_order_id"] == mismatch_order)
    assert mismatched["movement_ids"] == [movement_id]
    assert "quantities differ" in mismatched["reason"]
    assert "issued 10" in mismatched["reason"] and "invoiced 9" in mismatched["reason"]


def test_apply_links_only_the_candidates_and_writes_one_audit_row(client, world):
    """Apply the approved plan: candidates linked, ambiguous order untouched."""
    linked = _new_product(world)
    po_id, _ = _po(client, world, linked["sku"], 50, "10.00")
    _receive(client, po_id, linked["warehouse_id"], linked["sku"], 50)
    linked_order, linked_invoice = _dispatch(client, linked, 10)
    _unlink_issues(linked)

    blocked = _new_product(world)
    po_id, _ = _po(client, world, blocked["sku"], 50, "10.00")
    _receive(client, po_id, blocked["warehouse_id"], blocked["sku"], 50)
    blocked_order, blocked_invoice = _dispatch(client, blocked, 10)
    _unlink_issues(blocked)
    _second_invoice(blocked_invoice, blocked, world, 4)

    with SessionLocal() as db:
        plan = costing.attribution_plan(db)
        fingerprint = costing.attribution_fingerprint(plan)
    planned = next(c for c in plan["candidates"] if c["sales_order_id"] == linked_order)
    assert not any(c["sales_order_id"] == blocked_order for c in plan["candidates"])

    with SessionLocal() as db:
        result = costing.apply_attribution(db, expected_fingerprint=fingerprint)
        db.commit()

    assert result["applied"] is True and result["already_applied"] is False
    assert result["audit_rows"] == 1
    assert result["attributed_movements"] >= planned["movements"]
    assert any(link["sales_order_id"] == linked_order for link in result["links"])

    linked_issues = _issue_movements(linked["product_id"])
    blocked_issues = _issue_movements(blocked["product_id"])
    assert linked_issues and all(m.invoice_id == linked_invoice for m in linked_issues)
    assert blocked_issues and all(m.invoice_id is None for m in blocked_issues)

    audited = [row for row in _attribution_audits()
               if (row.changes or {}).get("plan_fingerprint") == fingerprint]
    assert len(audited) == 1
    assert audited[0].actor_id is None
    assert audited[0].record == "stock_movements:attribution"
    assert audited[0].changes["tool"] == "backfill_costs.py"


def test_apply_is_idempotent_and_writes_no_second_audit_row(client, world):
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 50, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 50)
    order_id, invoice_id = _dispatch(client, product, 10)
    _unlink_issues(product)

    fingerprint = _fingerprint()
    with SessionLocal() as db:
        first = costing.apply_attribution(db, expected_fingerprint=fingerprint)
        db.commit()
    audits_after_first = len(_attribution_audits())

    with SessionLocal() as db:
        second = costing.apply_attribution(db, expected_fingerprint=fingerprint)
        db.commit()

    assert first["applied"] is True and first["audit_rows"] == 1
    assert second["applied"] is False and second["already_applied"] is True
    assert second["idempotent"] is True
    assert second["attributed_movements"] == 0 and second["audit_rows"] == 0
    assert len(_attribution_audits()) == audits_after_first
    assert all(m.invoice_id == invoice_id for m in _issue_movements(product["product_id"]))


def test_apply_refuses_a_stale_plan_and_writes_nothing(client, world):
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 50, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 50)
    order_id, invoice_id = _dispatch(client, product, 10)
    _unlink_issues(product)

    fingerprint = _fingerprint()
    _second_invoice(invoice_id, product, world, 4)      # the database moved on
    audits_before = len(_attribution_audits())

    with SessionLocal() as db:
        with pytest.raises(costing.StaleAttributionPlanError):
            costing.apply_attribution(db, expected_fingerprint=fingerprint)
        db.rollback()

    assert all(m.invoice_id is None for m in _issue_movements(product["product_id"]))
    assert len(_attribution_audits()) == audits_before

    with SessionLocal() as db:
        with pytest.raises(ValueError):
            costing.apply_attribution(db, expected_fingerprint="not-a-fingerprint")


def _legacy_partial_order(client, world, qty=4):
    """Opening stock with no cost plus a costed receipt: the issue stays partial."""
    product = _new_product(world, opening=5)
    po_id, _ = _po(client, world, product["sku"], 10, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 10)
    order_id, invoice_id = _dispatch(client, product, qty)
    _strip_issue_cost(product)
    return product, order_id, invoice_id


def test_cost_apply_sets_the_proposal_and_writes_one_audit_row(client, world):
    product, _order_id, invoice_id = _legacy_partial_order(client, world)

    with SessionLocal() as db:
        plan = costing.backfill_plan(db, [product["product_id"]])
    row = plan["products"][0]
    detail = next(m for m in row["movements_detail"] if m["movement_type"] == "issue")
    assert detail["changed"] is True
    assert detail["unit_cost"] == "10.00"
    assert detail["cost_source"] == costing.PARTIAL
    assert row["uncosted_on_hand"] == _dec("5")
    invoice = next(i for i in plan["invoices"] if i["invoice_id"] == invoice_id)
    assert invoice["costed_after"] is False
    assert "partial" in invoice["partial_reason_after"]

    fingerprint = costing.cost_fingerprint(plan)
    with SessionLocal() as db:
        result = costing.apply_cost_backfill(
            db, expected_fingerprint=fingerprint, product_ids=[product["product_id"]])
        db.commit()

    assert result["applied"] is True and result["audit_rows"] == 1
    assert result["movements_changed"] == row["would_set_cost"] + row["would_change_source"]
    issue = _issue_movements(product["product_id"])[0]
    assert issue.unit_cost == _dec("10.00")
    assert issue.cost_source == costing.PARTIAL

    audited = [row for row in _cost_audits()
               if row.changes.get("plan_fingerprint") == fingerprint]
    assert len(audited) == 1
    assert audited[0].actor_id is None
    assert audited[0].record == "stock_movements:cost_backfill"
    recorded = {c["movement_id"]: c for c in audited[0].changes["costs"]}
    assert recorded[issue.id]["unit_cost"] == "10.00"
    assert recorded[issue.id]["cost_source"] == costing.PARTIAL


def test_cost_apply_is_idempotent_and_writes_no_second_audit_row(client, world):
    product, _order_id, _invoice_id = _legacy_partial_order(client, world)
    fingerprint = _cost_fingerprint(product)

    with SessionLocal() as db:
        first = costing.apply_cost_backfill(
            db, expected_fingerprint=fingerprint, product_ids=[product["product_id"]])
        db.commit()
    audits_after_first = len(_cost_audits())

    with SessionLocal() as db:
        second = costing.apply_cost_backfill(
            db, expected_fingerprint=fingerprint, product_ids=[product["product_id"]])
        db.commit()

    assert first["applied"] is True and first["audit_rows"] == 1
    assert second["applied"] is False and second["already_applied"] is True
    assert second["idempotent"] is True and second["audit_rows"] == 0
    assert len(_cost_audits()) == audits_after_first


def test_cost_apply_refuses_a_stale_plan_and_writes_nothing(client, world):
    product, _order_id, _invoice_id = _legacy_partial_order(client, world)
    fingerprint = _cost_fingerprint(product)

    with SessionLocal() as db:
        receipt = db.scalar(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product["product_id"],
                   StockMovement.movement_type == "receipt",
                   StockMovement.ref_type == "grn"))
        receipt.unit_cost = Decimal("20.00")
        db.commit()
    audits_before = len(_cost_audits())

    with SessionLocal() as db:
        with pytest.raises(costing.StaleCostPlanError):
            costing.apply_cost_backfill(
                db, expected_fingerprint=fingerprint,
                product_ids=[product["product_id"]])
        db.rollback()

    issue = _issue_movements(product["product_id"])[0]
    assert issue.unit_cost is None and issue.cost_source is None
    assert len(_cost_audits()) == audits_before


def test_cost_apply_refuses_a_locked_invoice_month(client, world):
    product, _order_id, invoice_id = _legacy_partial_order(client, world)
    with SessionLocal() as db:
        db.get(Invoice, invoice_id).invoice_date = date(2019, 3, 10)
        db.add(PeriodLock(scope="accounting", year=2019, month=3, active=True,
                          locked_by=1, reason="test close"))
        db.commit()
    fingerprint = _cost_fingerprint(product)
    audits_before = len(_cost_audits())
    try:
        with SessionLocal() as db:
            with pytest.raises(costing.LockedPeriodError):
                costing.apply_cost_backfill(
                    db, expected_fingerprint=fingerprint,
                    product_ids=[product["product_id"]])
            db.rollback()
        issue = _issue_movements(product["product_id"])[0]
        assert issue.unit_cost is None and len(_cost_audits()) == audits_before
    finally:
        with SessionLocal() as db:
            lock = db.scalar(select(PeriodLock).where(
                PeriodLock.scope == "accounting", PeriodLock.year == 2019,
                PeriodLock.month == 3))
            if lock is not None:
                lock.active = False
                db.commit()


def test_issue_is_partial_when_any_on_hand_stock_has_no_cost(client, world):
    product = _new_product(world, opening=100)          # 100 units, no cost
    po_id, _ = _po(client, world, product["sku"], 50, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 50)

    _order_id, invoice_id = _dispatch(client, product, 10)

    issues = _issue_movements(product["product_id"])
    assert len(issues) == 1
    assert issues[0].unit_cost == _dec("10.00")          # best available average
    assert issues[0].cost_source == costing.PARTIAL

    with SessionLocal() as db:
        cogs = costing.invoice_cogs(db, [invoice_id])[invoice_id]
    assert cogs["costed"] is False
    assert cogs["cogs"] == _dec("100.00")
    assert "partial" in cogs["partial_reason"]


def test_price_only_credit_note_leaves_cogs_unchanged(client, world):
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 100, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 100)
    _order_id, invoice_id = _dispatch(client, product, 10)

    with SessionLocal() as db:
        line = db.scalar(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id))
        on_hand_before = db.scalar(select(Batch.on_hand).where(
            Batch.product_id == product["product_id"]))

    note = client.as_user("admin").post("/api/credit-notes", json={
        "invoice_id": invoice_id, "reason": "Rate difference agreed with the buyer",
        "lines": [{"invoice_line_id": line.id, "qty": "2"}]})
    assert note.status_code == 201, note.text
    assert note.json()["returned_to_stock"] is False

    with SessionLocal() as db:
        on_hand_after = db.scalar(select(Batch.on_hand).where(
            Batch.product_id == product["product_id"]))
        returns = db.scalars(select(StockMovement).where(
            StockMovement.movement_type == "return")).all()
        cogs = costing.invoice_cogs(db, [invoice_id])[invoice_id]
    assert on_hand_after == on_hand_before              # same < 0 is not stock movement
    assert on_hand_before == _dec("90")
    assert returns == []
    assert cogs["cogs"] == _dec("100.00")
    assert cogs["costed"] is True


def test_stock_return_credit_note_reduces_cogs_at_the_issue_cost(client, world):
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 100, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 100)
    _order_id, invoice_id = _dispatch(client, product, 10)

    with SessionLocal() as db:
        line = db.scalar(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id))

    note = client.as_user("admin").post("/api/credit-notes", json={
        "invoice_id": invoice_id, "reason": "Damaged in transit", "warehouse_id":
        product["warehouse_id"], "lines": [{"invoice_line_id": line.id, "qty": "4"}]})
    assert note.status_code == 201, note.text
    assert note.json()["returned_to_stock"] is True

    with SessionLocal() as db:
        returned = db.scalars(select(StockMovement).where(
            StockMovement.movement_type == "return")).all()
        cogs = costing.invoice_cogs(db, [invoice_id])[invoice_id]
        on_hand = db.scalar(select(Batch.on_hand).where(
            Batch.product_id == product["product_id"]))
    assert len(returned) == 1
    assert returned[0].unit_cost == _dec("10.00")
    assert returned[0].cost_source == costing.RETURN
    assert returned[0].invoice_id == invoice_id
    assert on_hand == _dec("94")
    assert cogs["cogs"] == _dec("60.00")
    assert cogs["return_qty"] == _dec("4")
    assert cogs["costed"] is True


def test_audited_cost_correction_replays_and_reports_changed_invoices(client, world):
    product = _new_product(world)
    po_id, po_line_id = _po(client, world, product["sku"], 100, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 100)
    _order_id, invoice_id = _dispatch(client, product, 10)

    refused = client.as_user("viewer").post("/api/accounts/costs/correction", json={
        "po_line_id": po_line_id, "new_unit_cost": "12.00",
        "reason": "late supplier invoice"})
    assert refused.status_code == 403, refused.text

    fixed = client.as_user("admin").post("/api/accounts/costs/correction", json={
        "po_line_id": po_line_id, "new_unit_cost": "12.00",
        "reason": "late supplier invoice"})
    assert fixed.status_code == 200, fixed.text
    body = fixed.json()
    assert _dec(body["old_po_rate"]) == _dec("10.00")
    assert _dec(body["new_po_rate"]) == _dec("12.00")
    assert _dec(body["before_total"]) == _dec("100.00")
    assert _dec(body["after_total"]) == _dec("120.00")
    assert body["movements_changed"] >= 2
    changed = {row["invoice_number"]: row for row in body["invoices"]}
    assert changed, body
    row = next(iter(changed.values()))
    assert _dec(row["before_cogs"]) == _dec("100.00")
    assert _dec(row["after_cogs"]) == _dec("120.00")
    assert _dec(row["delta"]) == _dec("20.00")

    with SessionLocal() as db:
        receipt = db.scalar(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product["product_id"],
                   StockMovement.movement_type == "receipt",
                   StockMovement.ref_type == "grn"))
        issue = db.scalar(select(StockMovement).where(
            StockMovement.movement_type == "issue",
            StockMovement.invoice_id == invoice_id))
        correction = db.scalar(select(CostCorrection).where(
            CostCorrection.product_id == product["product_id"]))
        audit_row = db.scalar(select(AuditLog).where(
            AuditLog.action == "accounts.cost_correction"))
        line = db.get(PurchaseOrderLine, po_line_id)
        cogs = costing.invoice_cogs(db, [invoice_id])[invoice_id]
    assert receipt.unit_cost == _dec("12.00")
    assert issue.unit_cost == _dec("12.00")
    assert issue.qty_delta == _dec("-10")              # quantities never change
    assert line.unit_cost == _dec("12.00")
    assert correction is not None
    assert correction.reason == "late supplier invoice"
    assert correction.result["new_po_rate"] == "12.00"
    assert audit_row is not None
    assert cogs["cogs"] == _dec("120.00")


def test_legacy_receipt_without_cost_is_derived_from_the_purchase_order(client, world):
    """Movements written before Stage 2 have no cost; a replay takes the PO rate."""
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 20, "8.00")
    with SessionLocal() as db:
        purchase_order = db.get(PurchaseOrder, po_id)
        batch = Batch(product_id=product["product_id"],
                      warehouse_id=product["warehouse_id"],
                      batch_no=f"LEG-{uuid4().hex[:6].upper()}", on_hand=Decimal(20))
        db.add(batch)
        db.flush()
        grn = GoodsReceipt(grn_number=f"GRN-LEG-{uuid4().hex[:8].upper()}",
                           po_id=purchase_order.id,
                           warehouse_id=product["warehouse_id"], received_by=1)
        db.add(grn)
        db.flush()
        db.add(GoodsReceiptLine(grn_id=grn.id, product_id=product["product_id"],
                                batch_id=batch.id, qty=Decimal(20)))
        db.add(StockMovement(batch_id=batch.id, movement_type="receipt",
                             qty_delta=Decimal(20), ref_type="grn",
                             ref_id=str(grn.id), actor_id=1))   # no stored cost
        db.commit()
        cost, source = costing.issue_cost(db, product["product_id"])
    assert cost == _dec("8.00")
    assert source == costing.WEIGHTED_AVERAGE


def test_backfill_is_dry_run_and_changes_nothing(client, world):
    product = _new_product(world, opening=50)
    po_id, _ = _po(client, world, product["sku"], 10, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 10)

    with SessionLocal() as db:
        before = {(m.id, m.unit_cost, m.cost_source) for m in db.scalars(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product["product_id"])).all()}
        plan = costing.backfill_plan(db, [product["product_id"]])
        after = {(m.id, m.unit_cost, m.cost_source) for m in db.scalars(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product["product_id"])).all()}
        db.rollback()

    assert before == after
    assert plan["movements"] >= 2
    row = plan["products"][0]
    assert row["uncosted_on_hand"] == _dec("50")


def test_backfill_tool_refuses_to_write():
    env = {**os.environ}
    refused = subprocess.run([sys.executable, "backfill_costs.py", "--apply"],
                             cwd=ROOT, env=env, capture_output=True, text=True)
    assert refused.returncode == 2
    assert "--plan-fingerprint" in refused.stderr

    filtered = subprocess.run(
        [sys.executable, "backfill_costs.py", "--apply", "--product", "1",
         "--plan-fingerprint", "0" * 64],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert filtered.returncode == 2
    assert "--product" in filtered.stderr

    both = subprocess.run(
        [sys.executable, "backfill_costs.py", "--apply", "--apply-costs",
         "--plan-fingerprint", "0" * 64],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert both.returncode == 2
    assert "not both" in both.stderr

    no_cost_fingerprint = subprocess.run(
        [sys.executable, "backfill_costs.py", "--apply-costs"],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert no_cost_fingerprint.returncode == 2
    assert "--plan-fingerprint" in no_cost_fingerprint.stderr

    stale = subprocess.run(
        [sys.executable, "backfill_costs.py", "--apply",
         "--plan-fingerprint", "0" * 64],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert stale.returncode == 3
    assert "Refused" in stale.stderr

    report = subprocess.run([sys.executable, "backfill_costs.py"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert report.returncode == 0, report.stderr
    data = json.loads(report.stdout)
    assert data["mode"] == "dry-run"
    assert "would_set_cost" in data
    assert len(data["attribution"]["plan_fingerprint"]) == 64
    assert len(data["cost_plan_fingerprint"]) == 64
    assert all("movements_detail" in row for row in data["detail"])


# ------------------------------------------------- issues with no known cost
def test_issue_before_any_receipt_is_partial_with_no_cost(client, world):
    """Opening stock has no cost: the issue stores NULL/partial, never zero."""
    product = _new_product(world, opening=10)
    _order_id, invoice_id = _dispatch(client, product, 2)

    issues = _issue_movements(product["product_id"])
    assert len(issues) == 1
    assert issues[0].unit_cost is None
    assert issues[0].unit_cost != Decimal("0")
    assert issues[0].cost_source == costing.PARTIAL

    with SessionLocal() as db:
        cogs = costing.invoice_cogs(db, [invoice_id])[invoice_id]
    assert cogs["costed"] is False
    assert cogs["partial_reason"] == "2.000 of 2.000 issued units have no cost"


def test_issue_after_stock_is_exhausted_has_no_average_not_zero(client, world):
    """With every costed unit issued, the average is gone, so a later issue is NULL."""
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 10, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 10)
    _order_id, _invoice_id = _dispatch(client, product, 10)

    with SessionLocal() as db:
        cost, source = costing.issue_cost(db, product["product_id"])
        plan = costing.replay(db, product["product_id"])
    assert plan.qty_on_hand == _dec("0")
    assert plan.average is None
    assert cost is None
    assert source == costing.PARTIAL


def test_negative_legacy_ledger_never_yields_a_zero_cost(client, world):
    """A ledger that runs negative (legacy data) must not present a zero cost."""
    product = _new_product(world)
    with SessionLocal() as db:
        batch = Batch(product_id=product["product_id"],
                      warehouse_id=product["warehouse_id"],
                      batch_no=f"NEG-{uuid4().hex[:6].upper()}", on_hand=Decimal(0))
        db.add(batch)
        db.flush()
        batch_id = batch.id
        db.add(StockMovement(batch_id=batch.id, movement_type="issue",
                             qty_delta=Decimal(-5), ref_type="legacy",
                             ref_id=f"LEG-{uuid4().hex[:6].upper()}", actor_id=1))
        db.commit()
        cost, source = costing.issue_cost(db, product["product_id"])
        plan = costing.replay(db, product["product_id"])
    assert plan.qty_on_hand == _dec("-5")
    assert plan.average is None
    assert cost is None
    assert source == costing.PARTIAL
    assert "negative" in plan.warnings[0]
    # The fixture deliberately breaks the batch/ledger invariant to model legacy
    # data. Remove it so the stock report's cross-check stays meaningful for the
    # rest of the suite.
    with SessionLocal() as db:
        db.query(StockMovement).filter(StockMovement.batch_id == batch_id).delete()
        db.query(Batch).filter(Batch.id == batch_id).delete()
        db.commit()


def test_dispatch_without_stock_writes_no_issue_at_all(client, world):
    product = _new_product(world)                       # no batch, no stock
    sales = client.as_user("sales")
    order = sales.post("/api/sales-orders", json={
        "distributor_id": product["distributor_id"],
        "lines": [{"sku": product["sku"], "qty": "1", "unit_price": "100.00"}]})
    assert order.status_code == 201, order.text
    submitted = sales.post(f"/api/sales-orders/{order.json()['id']}/submit")
    assert submitted.status_code == 409
    assert "Insufficient stock" in submitted.text
    with SessionLocal() as db:
        movements = db.scalars(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product["product_id"])).all()
        invoices = db.scalars(select(Invoice).where(
            Invoice.sales_order_id == order.json()["id"])).all()
    assert movements == []
    assert invoices == []


# ------------------------------------------------------- concurrent issues
def test_product_lock_blocks_a_second_issue_until_commit(client, world):
    """Two sessions: the second cannot take the product row until the first commits."""
    product = _new_product(world)
    with SessionLocal() as first, SessionLocal() as second:
        costing.lock_products(first, [product["product_id"]])
        with pytest.raises(OperationalError):
            second.execute(select(Product.id)
                           .where(Product.id == product["product_id"])
                           .with_for_update(nowait=True)).all()
        second.rollback()

        first.commit()                                  # issue cost is now durable
        second.execute(select(Product.id)
                       .where(Product.id == product["product_id"])
                       .with_for_update(nowait=True)).all()
        second.rollback()


def test_dispatch_locks_the_product_before_reading_the_average(client, world, monkeypatch):
    product = _new_product(world)
    po_id, _ = _po(client, world, product["sku"], 20, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 20)
    seen = []
    real = costing.lock_products

    def spy(db, product_ids):
        seen.append(sorted(set(product_ids)))
        return real(db, product_ids)

    monkeypatch.setattr(costing, "lock_products", spy)
    _dispatch(client, product, 2)
    assert seen and product["product_id"] in seen[0]


# ---------------------------------------------- transfers and adjustments
def test_transfer_and_adjustment_rows_store_no_cost_rather_than_zero(client, world):
    """No screen writes transfers/adjustments; if a row is written, cost stays NULL."""
    product = _new_product(world)
    with SessionLocal() as db:
        batch = Batch(product_id=product["product_id"],
                      warehouse_id=product["warehouse_id"],
                      batch_no=f"ADJ-{uuid4().hex[:6].upper()}", on_hand=Decimal(0))
        db.add(batch)
        db.flush()
        for kind, ref in (("adjust", "ADJ-1"), ("transfer", "TRF-1")):
            post_movement(db, batch_id=batch.id, qty_delta=Decimal(5),
                          movement_type=kind, ref_type="manual", ref_id=ref,
                          actor_id=1)
        db.commit()
        rows = db.scalars(select(StockMovement).where(
            StockMovement.batch_id == batch.id)).all()
        plan = costing.replay(db, product["product_id"])
        cost, source = costing.issue_cost(db, product["product_id"])
    assert len(rows) == 2
    assert all(row.unit_cost is None for row in rows)
    assert all(row.unit_cost != Decimal("0") for row in rows)
    assert all(row.cost_source is None for row in rows)
    assert plan.uncosted_on_hand == _dec("10")
    assert cost is None and source == costing.PARTIAL


# ------------------------------------------------- accounting period locks
def _lock_month(client, when, reason="month closed for audit"):
    return client.as_user("admin").post("/api/accounts/period-locks", json={
        "year": when.year, "month": when.month, "reason": reason})


def test_cost_correction_is_refused_while_the_accounting_month_is_locked(client, world):
    product = _new_product(world)
    po_id, po_line_id = _po(client, world, product["sku"], 100, "10.00")
    _receive(client, po_id, product["warehouse_id"], product["sku"], 100)
    _order_id, invoice_id = _dispatch(client, product, 10)

    assert client.as_user("viewer").get("/api/accounts/period-locks").status_code == 403
    assert client.as_user("sales").post("/api/accounts/period-locks", json={
        "year": date.today().year, "month": date.today().month,
        "reason": "not my job"}).status_code == 403

    locked = _lock_month(client, date.today())
    assert locked.status_code == 201, locked.text
    lock_id = locked.json()["id"]
    assert locked.json()["scope"] == "accounting"
    assert _lock_month(client, date.today()).status_code == 409

    refused = client.as_user("admin").post("/api/accounts/costs/correction", json={
        "po_line_id": po_line_id, "new_unit_cost": "12.00",
        "reason": "late supplier invoice"})
    assert refused.status_code == 423, refused.text
    assert "locked" in refused.json()["detail"]
    assert str(date.today().year) in refused.json()["detail"]

    with SessionLocal() as db:
        issue = db.scalar(select(StockMovement).where(
            StockMovement.movement_type == "issue",
            StockMovement.invoice_id == invoice_id))
        line = db.get(PurchaseOrderLine, po_line_id)
        correction = db.scalar(select(CostCorrection).where(
            CostCorrection.po_line_id == po_line_id))
    assert issue.unit_cost == _dec("10.00")             # nothing moved
    assert line.unit_cost == _dec("10.00")
    assert correction is None

    assert client.as_user("sales").post(
        f"/api/accounts/period-locks/{lock_id}/unlock",
        json={"reason": "please reopen"}).status_code == 403
    admin = client.as_user("admin")
    unlocked = admin.post(f"/api/accounts/period-locks/{lock_id}/unlock",
                          json={"reason": "invoice reissued after review"})
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["active"] is False

    fixed = admin.post("/api/accounts/costs/correction", json={
        "po_line_id": po_line_id, "new_unit_cost": "12.00",
        "reason": "late supplier invoice"})
    assert fixed.status_code == 200, fixed.text
    assert _dec(fixed.json()["after_total"]) == _dec("120.00")

    with SessionLocal() as db:
        lock = db.get(PeriodLock, lock_id)
    assert lock is not None and lock.active is False
