"""Free-of-cost stock: the receiving flag, the approved giveaway and the fix.

Rules under test:

* a receipt marked FOC is stored at zero cost with its own source, and it never
  enters the weighted average of purchased stock;
* a giveaway is a note with one named recipient, approved by a second
  Administrator, and it posts a zero-cost issue without an invoice or revenue;
* approval cannot exceed the free stock on hand, and the draft's creator cannot
  approve it;
* a reversal puts the free stock back and keeps the original rows;
* the historical correction refuses a stale fingerprint, rewrites only the
  named legacy receipts and PO line, writes the notes once, and is idempotent.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import (Batch, Product, PurchaseOrder, PurchaseOrderLine,
                             StockMovement, User, Warehouse)
from app.models.foc import FocNote
from app.models.users import Role
from app.services import costing

FOC = "foc"


def _new_product():
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        product = Product(sku=f"FOC-{suffix}", name="FOC product", pack_size="10 tabs",
                          mrp=Decimal("100"), hsn="30049099", uqc="TAB",
                          status="active")
        warehouse = Warehouse(name=f"FOC wh {suffix}")
        db.add_all([product, warehouse])
        db.flush()
        batch = Batch(product_id=product.id, warehouse_id=warehouse.id,
                      batch_no=f"F-{suffix}", on_hand=Decimal("0"))
        db.add(batch)
        db.commit()
        return {"product_id": product.id, "sku": product.sku,
                "warehouse_id": warehouse.id, "batch_id": batch.id}


def _po(client, world, sku, qty, unit_cost=None, remark=None):
    line = {"sku": sku, "qty": str(qty)}
    if unit_cost is not None:
        line["unit_cost"] = str(unit_cost)
    if remark:
        line["rate_remark"] = remark
    response = client.as_user("admin").post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"], "lines": [line]})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["lines"][0]["id"]


def _receive(client, product, po_id, qty):
    response = client.as_user("inventory").post(
        f"/api/purchase-orders/{po_id}/receive", json={
            "warehouse_id": product["warehouse_id"],
            "lines": [{"sku": product["sku"], "qty": str(qty),
                       "batch_no": f"R-{uuid4().hex[:8].upper()}"}]})
    assert response.status_code == 201, response.text
    return response.json()


def _receipts(product_id):
    with SessionLocal() as db:
        return list(db.scalars(
            select(StockMovement)
            .join(Batch, Batch.id == StockMovement.batch_id)
            .where(Batch.product_id == product_id,
                   StockMovement.movement_type == "receipt")).all())


def _note(client, product, qty, actor="inventory", name="Sample recipient"):
    return client.as_user(actor).post("/api/foc/notes", json={
        "note_date": date.today().isoformat(),
        "warehouse_id": product["warehouse_id"],
        "recipient_name": name, "reason": "sample",
        "lines": [{"product_id": product["product_id"],
                   "batch_id": product["batch_id"], "qty": str(qty)}]})


def _seed_paid_and_free(client, world):
    product = _new_product()
    paid_po, _ = _po(client, world, product["sku"], 100, "10.00")
    _receive(client, product, paid_po, 100)
    free_po, _ = _po(client, world, product["sku"], 50, remark="foc")
    _receive(client, product, free_po, 50)
    free = [m for m in _receipts(product["product_id"]) if m.cost_source == FOC]
    product["batch_id"] = free[0].batch_id
    return product


def test_foc_receipt_keeps_the_purchased_average(client, world):
    product = _seed_paid_and_free(client, world)
    receipts = _receipts(product["product_id"])
    free = [m for m in receipts if m.cost_source == FOC]
    assert len(free) == 1
    assert free[0].unit_cost == Decimal("0.00")

    with SessionLocal() as db:
        plan = costing.replay(db, product["product_id"])
        assert plan.foc_qty == Decimal("50")
        assert plan.costed_qty == Decimal("100")
        assert plan.average == Decimal("10.00")
        assert plan.uncosted_on_hand == Decimal("0")


def test_giveaway_is_approved_by_a_second_administrator_and_posts_zero_cost(
        client, world):
    product = _seed_paid_and_free(client, world)

    draft = _note(client, product, 40)
    assert draft.status_code == 201, draft.text
    note_id = draft.json()["id"]
    assert draft.json()["status"] == "draft"

    refused = client.as_user("inventory").post(f"/api/foc/notes/{note_id}/approve")
    assert refused.status_code == 403

    approved = client.as_user("admin").post(f"/api/foc/notes/{note_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    with SessionLocal() as db:
        note = db.get(FocNote, note_id)
        issued = db.scalars(
            select(StockMovement)
            .where(StockMovement.ref_type == "foc", StockMovement.ref_id == str(note_id))
        ).all()
        assert len(issued) == 1
        assert issued[0].qty_delta == Decimal("-40")
        assert issued[0].unit_cost == Decimal("0.00")
        assert issued[0].cost_source == FOC
        assert issued[0].invoice_id is None
        assert note.approved_by == client.ids["admin"]
        plan = costing.replay(db, product["product_id"])
        assert plan.qty_on_hand == Decimal("110")
        assert plan.foc_qty == Decimal("10")
        assert plan.average == Decimal("10.00")


def test_creator_cannot_approve_own_note(client, world):
    product = _seed_paid_and_free(client, world)
    draft = _note(client, product, 10, actor="admin", name="Own note")
    assert draft.status_code == 201, draft.text
    refused = client.as_user("admin").post(f"/api/foc/notes/{draft.json()['id']}/approve")
    assert refused.status_code == 409


def test_approval_cannot_exceed_free_stock(client, world):
    product = _seed_paid_and_free(client, world)
    draft = _note(client, product, 80)
    assert draft.status_code == 201, draft.text
    note_id = draft.json()["id"]
    refused = client.as_user("admin").post(f"/api/foc/notes/{note_id}/approve")
    assert refused.status_code == 409
    with SessionLocal() as db:
        assert db.get(FocNote, note_id).status == "draft"
        assert costing.replay(db, product["product_id"]).foc_qty == Decimal("50")


def test_reversal_returns_the_free_stock(client, world):
    product = _seed_paid_and_free(client, world)
    draft = _note(client, product, 20, name="Reversed recipient")
    note_id = draft.json()["id"]
    assert client.as_user("admin").post(
        f"/api/foc/notes/{note_id}/approve").status_code == 200
    reversed_ = client.as_user("admin").post(
        f"/api/foc/notes/{note_id}/reverse", json={"reason": "goods came back"})
    assert reversed_.status_code == 200, reversed_.text
    with SessionLocal() as db:
        plan = costing.replay(db, product["product_id"])
        assert plan.foc_qty == Decimal("50")
        assert plan.qty_on_hand == Decimal("150")
        returned = db.scalars(
            select(StockMovement)
            .where(StockMovement.movement_type == "foc_return",
                   StockMovement.ref_id == str(note_id))).all()
        assert len(returned) == 1
        assert returned[0].qty_delta == Decimal("20")


def _legacy_receipt(client, world):
    """A zero-rate receipt written before the FOC flag, plus a paid receipt."""
    product = _new_product()
    # The API now refuses a zero rate without a remark; legacy rows predate that,
    # so the zero-rate line is inserted directly with unit_cost 0.00 and no remark.
    with SessionLocal() as db:
        po = PurchaseOrder(po_number=f"LEG-{uuid4().hex[:8].upper()}",
                           supplier="Legacy supplier", supplier_id=world["supplier_id"],
                           created_by=client.ids["admin"])
        db.add(po)
        db.flush()
        line = PurchaseOrderLine(po_id=po.id, product_id=product["product_id"],
                                 qty=Decimal("100"), unit_cost=Decimal("0.00"))
        db.add(line)
        db.commit()
        line_id = line.id
    paid_po, _ = _po(client, world, product["sku"], 100, "20.00")
    _receive(client, product, paid_po, 100)

    with SessionLocal() as db:
        actor = client.ids["admin"]
        batch = db.get(Batch, product["batch_id"])
        movement = StockMovement(batch_id=batch.id, movement_type="receipt",
                                 qty_delta=Decimal("100"), ref_type="grn",
                                 ref_id="999999", actor_id=actor)
        db.add(movement)
        batch.on_hand += Decimal("100")
        db.commit()
        product["movement_id"] = movement.id
        product["line_id"] = line_id
    return product


def _second_admin():
    """A second Administrator to be the creator; the token holder approves."""
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == "admin"))
        user = db.scalar(select(User).where(User.username == "t_admin2"))
        if user is None:
            user = User(username="t_admin2", username_key="t_admin2",
                        password_hash="x", role="admin", role_id=role.id)
            db.add(user)
            db.commit()
        return user.id


def _correction_body(product, fingerprint=None, qty="100", creator_id=None):
    body = {
        "note_date": date.today().isoformat(),
        "warehouse_id": product["warehouse_id"],
        "reason": "sample",
        "recipients": [
            {"name": "Recipient One", "qty": str(Decimal(qty) / 2)},
            {"name": "Recipient Two", "qty": str(Decimal(qty) / 2)},
        ],
        "flag_po7": False,
        "base_movement_id": product["movement_id"],
        "po_line_id": product["line_id"],
    }
    if creator_id is not None:
        body["creator_id"] = creator_id
    if fingerprint:
        body["expected_fingerprint"] = fingerprint
    return body


def test_correction_requires_the_approved_fingerprint_and_is_idempotent(
        client, world):
    product = _legacy_receipt(client, world)
    admin = client.as_user("admin")
    creator_id = _second_admin()

    plan = admin.post("/api/foc/correction/plan", json=_correction_body(product))
    assert plan.status_code == 200, plan.text
    fingerprint = plan.json()["fingerprint"]
    assert plan.json()["already_applied"] is False
    assert [n["recipient"] for n in plan.json()["notes"]] == ["Recipient One",
                                                             "Recipient Two"]

    stale = admin.post("/api/foc/correction/apply",
                       json=_correction_body(product, "0" * 64, creator_id=creator_id))
    assert stale.status_code == 409

    applied = admin.post("/api/foc/correction/apply",
                         json=_correction_body(product, fingerprint,
                                               creator_id=creator_id))
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    assert len(applied.json()["notes_created"]) == 2

    with SessionLocal() as db:
        line = db.get(PurchaseOrderLine, product["line_id"])
        movement = db.get(StockMovement, product["movement_id"])
        assert line.rate_remark == "foc"
        assert movement.cost_source == FOC
        assert movement.unit_cost == Decimal("0.00")
        plan = costing.replay(db, product["product_id"])
        assert plan.foc_qty == Decimal("0")
        assert plan.costed_qty == Decimal("100")
        assert plan.average == Decimal("20.00")
        assert plan.uncosted_on_hand == Decimal("0")
        notes = db.scalars(select(FocNote).where(
            FocNote.correction.is_(True))).all()
        assert len(notes) == 2
        assert {n.created_by for n in notes} == {creator_id}
        assert {n.approved_by for n in notes} == {client.ids["admin"]}

    repeat = admin.post("/api/foc/correction/apply",
                        json=_correction_body(product, fingerprint,
                                              creator_id=creator_id))
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["applied"] is False
    with SessionLocal() as db:
        assert len(db.scalars(select(FocNote).where(
            FocNote.correction.is_(True))).all()) == 2


def test_correction_creator_and_approver_must_differ(client, world):
    product = _legacy_receipt(client, world)
    admin = client.as_user("admin")
    plan = admin.post("/api/foc/correction/plan", json=_correction_body(product))
    assert plan.status_code == 200, plan.text
    same = admin.post("/api/foc/correction/apply", json=_correction_body(
        product, plan.json()["fingerprint"], creator_id=client.ids["admin"]))
    assert same.status_code == 409
    assert "different Administrators" in same.json()["detail"]


def test_correction_is_administrator_only(client, world):
    product = _legacy_receipt(client, world)
    refused = client.as_user("inventory").post(
        "/api/foc/correction/plan", json=_correction_body(product))
    assert refused.status_code == 403


def test_viewer_reads_but_does_not_write(client, world):
    product = _seed_paid_and_free(client, world)
    assert client.as_user("viewer").get("/api/foc/stock").status_code == 200
    refused = _note(client, product, 1, actor="viewer")
    assert refused.status_code == 403
    denied = client.as_user("sales").get("/api/foc/notes")
    assert denied.status_code == 403
