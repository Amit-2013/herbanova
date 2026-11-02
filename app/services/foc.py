"""Free-of-cost stock: approved giveaways and the audited historical fix.

A note is the only way stock leaves the ledger without an invoice. It carries
one named recipient, is approved by an Administrator other than its creator, and
posts a `foc_issue` movement at zero cost. It never touches revenue, GST or the
weighted average. Reversal posts a `foc_return`; the original rows stay.

The historical correction is separate: it is a guarded, fingerprinted operation
that marks the legacy zero-rate receipt and its PO line as FOC and writes the
approved note(s) in one transaction. It refuses if the database changed since
the plan was approved.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import is_admin, role_permissions
from ..models.core import (AuditLog, Batch, DocumentSequence, Product,
                           PurchaseOrderLine, StockMovement, User, Warehouse)
from ..models.foc import (APPROVED, DRAFT, REASONS, REJECTED, REVERSED, FocNote,
                          FocNoteLine)
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine
from .audit import audit
from .costing import FOC, money, replay
from .hr import active_period_lock, business_today
from .inventory import post_movement
from .numbering import financial_year, next_document_number

IST = ZoneInfo("Asia/Calcutta")
ZERO = Decimal("0")
CENT = Decimal("0.01")


class FocError(Exception):
    status = 409

    def __init__(self, detail: str, status: int | None = None):
        super().__init__(detail)
        self.detail = detail
        if status is not None:
            self.status = status


class FocLockedPeriod(FocError):
    status = 423


class StaleFocCorrection(FocError):
    status = 409


def _amount(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _posted_at(day: date) -> datetime:
    """Backdated documents post at the end of their business day, after receipts.

    A note dated today posts now. A historical note posts at 23:59:59 IST of its
    date, so its negative quantity never sorts before the receipt it consumes.
    """
    now = datetime.now(timezone.utc)
    if day >= now.astimezone(IST).date():
        return now
    return datetime.combine(day, time(23, 59, 59), tzinfo=IST)


def _lock_check(db: Session, day: date) -> None:
    lock = active_period_lock(db, "accounting", day)
    if lock is not None:
        raise FocLockedPeriod(
            f"The accounting period {lock.year}-{lock.month:02d} is locked, so a "
            "free-sample note cannot be written in it. Unlock the month first.")


def _clean(value: str | None, limit: int) -> str | None:
    text = (value or "").strip()
    return text[:limit] if text else None


def _validate_lines(db: Session, warehouse_id: int, lines: list[dict]) -> None:
    if not lines:
        raise FocError("Add at least one product line", 422)
    seen = set()
    for line in lines:
        batch = db.get(Batch, line["batch_id"])
        if batch is None:
            raise FocError("Batch not found", 404)
        if batch.warehouse_id != warehouse_id:
            raise FocError("Every batch must belong to the note's warehouse", 422)
        if batch.product_id != line["product_id"]:
            raise FocError("The batch does not hold that product", 422)
        if line["qty"] <= 0:
            raise FocError("Quantity must be positive", 422)
        if batch.id in seen:
            raise FocError("One line per batch; combine the quantity", 422)
        seen.add(batch.id)


def create_note(db: Session, *, actor, note_date: date, warehouse_id: int,
                recipient_name: str, recipient_address: str | None,
                recipient_contact: str | None, distributor_id: int | None,
                reason: str, reason_note: str | None,
                notional_value: Decimal | None, lines: list[dict],
                correction: bool = False) -> FocNote:
    if note_date > business_today():
        raise FocError("A free-sample note cannot be dated in the future", 422)
    if reason not in REASONS:
        raise FocError(f"reason must be one of {', '.join(REASONS)}", 422)
    name = _clean(recipient_name, 150)
    if not name:
        raise FocError("Name the recipient", 422)
    if db.get(Warehouse, warehouse_id) is None:
        raise FocError("Warehouse not found", 404)
    _validate_lines(db, warehouse_id, lines)
    if notional_value is not None and Decimal(notional_value) < 0:
        raise FocError("The notional value cannot be negative", 422)

    number, fy = next_document_number(db, "foc_note", "FOC", note_date)
    note = FocNote(
        note_number=number, financial_year=fy, note_date=note_date,
        warehouse_id=warehouse_id, distributor_id=distributor_id,
        recipient_name=name, recipient_address=_clean(recipient_address, 300),
        recipient_contact=_clean(recipient_contact, 120), reason=reason,
        reason_note=_clean(reason_note, 300),
        notional_value=_amount(notional_value) if notional_value is not None else None,
        status=DRAFT, correction=correction, created_by=actor.id)
    db.add(note)
    db.flush()
    for line in lines:
        unit = line.get("unit_notional_value")
        unit = _amount(unit) if unit is not None else None
        db.add(FocNoteLine(
            note_id=note.id, product_id=line["product_id"],
            batch_id=line["batch_id"], qty=Decimal(line["qty"]),
            unit_notional_value=unit,
            line_notional_value=(unit * Decimal(line["qty"]) if unit is not None else None)))
    db.flush()
    audit(db, actor.id, "foc.create", f"foc:{note.id}", {
        "note_number": note.note_number, "note_date": str(note_date),
        "warehouse_id": warehouse_id, "recipient": name, "reason": reason,
        "lines": [{"batch_id": l["batch_id"], "qty": str(l["qty"])} for l in lines],
        "notional_value": (str(note.notional_value)
                           if note.notional_value is not None else None)})
    return note


def _foc_available(db: Session, note: FocNote) -> None:
    by_product: dict[int, Decimal] = {}
    for line in note.lines:
        by_product[line.product_id] = by_product.get(line.product_id, ZERO) + Decimal(line.qty)
    for product_id, qty in by_product.items():
        plan = replay(db, product_id)
        if plan.foc_qty < qty:
            product = db.get(Product, product_id)
            raise FocError(
                f"Only {plan.foc_qty:f} FOC units of {product.sku if product else product_id} "
                f"are on hand; this note gives away {qty:f}. Mark the receipt as FOC first.",
                409)


def _post_note(db: Session, note: FocNote, actor_id: int) -> None:
    for line in note.lines:
        movement = post_movement(
            db, batch_id=line.batch_id, qty_delta=-Decimal(line.qty),
            movement_type="foc_issue", ref_type="foc", ref_id=str(note.id),
            actor_id=actor_id, unit_cost=Decimal("0.00"), cost_source=FOC,
            created_at=_posted_at(note.note_date))
        line.movement_id = movement.id


def approve_note(db: Session, note_id: int, actor) -> FocNote:
    note = db.get(FocNote, note_id, with_for_update=True)
    if note is None:
        raise FocError("Free-sample note not found", 404)
    if note.status != DRAFT:
        raise FocError(f"Only a draft can be approved; this one is {note.status}")
    if note.created_by == actor.id:
        raise FocError("A free-sample note must be approved by another Administrator",
                       409)
    _lock_check(db, note.note_date)
    _foc_available(db, note)
    _post_note(db, note, actor.id)
    note.status, note.approved_by = APPROVED, actor.id
    note.approved_at = datetime.now(timezone.utc)
    audit(db, actor.id, "foc.approve", f"foc:{note.id}", {
        "note_number": note.note_number, "note_date": str(note.note_date),
        "warehouse_id": note.warehouse_id, "recipient": note.recipient_name,
        "lines": [{"batch_id": l.batch_id, "qty": str(l.qty),
                   "movement_id": l.movement_id} for l in note.lines]})
    db.flush()
    return note


def reject_note(db: Session, note_id: int, actor, reason: str) -> FocNote:
    note = db.get(FocNote, note_id, with_for_update=True)
    if note is None:
        raise FocError("Free-sample note not found", 404)
    if note.status != DRAFT:
        raise FocError(f"Only a draft can be rejected; this one is {note.status}")
    clean = _clean(reason, 300)
    if not clean:
        raise FocError("Give a reason for rejecting the note", 422)
    note.status, note.rejected_by = REJECTED, actor.id
    note.rejected_at = datetime.now(timezone.utc)
    note.rejection_reason = clean
    audit(db, actor.id, "foc.reject", f"foc:{note.id}",
          {"note_number": note.note_number, "reason": clean})
    db.flush()
    return note


def reverse_note(db: Session, note_id: int, actor, reason: str) -> FocNote:
    note = db.get(FocNote, note_id, with_for_update=True)
    if note is None:
        raise FocError("Free-sample note not found", 404)
    if note.status != APPROVED:
        raise FocError(f"Only an approved note can be reversed; this one is {note.status}")
    _lock_check(db, note.note_date)
    clean = _clean(reason, 300)
    if not clean:
        raise FocError("Give a reason for reversing the note", 422)
    for line in note.lines:
        post_movement(
            db, batch_id=line.batch_id, qty_delta=Decimal(line.qty),
            movement_type="foc_return", ref_type="foc_return", ref_id=str(note.id),
            actor_id=actor.id, unit_cost=Decimal("0.00"), cost_source=FOC)
    note.status, note.reversed_by = REVERSED, actor.id
    note.reversed_at = datetime.now(timezone.utc)
    note.reversal_reason = clean
    audit(db, actor.id, "foc.reverse", f"foc:{note.id}",
          {"note_number": note.note_number, "reason": clean,
           "lines": [{"batch_id": l.batch_id, "qty": str(l.qty)} for l in note.lines]})
    db.flush()
    return note


def notes_query(db: Session, *, status: str | None = None, date_from: date | None = None,
                date_to: date | None = None, q: str | None = None, limit: int = 200):
    stmt = select(FocNote)
    if status:
        stmt = stmt.where(FocNote.status == status)
    if date_from:
        stmt = stmt.where(FocNote.note_date >= date_from)
    if date_to:
        stmt = stmt.where(FocNote.note_date <= date_to)
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(FocNote.note_number.ilike(term)
                          | FocNote.recipient_name.ilike(term)
                          | FocNote.reason_note.ilike(term))
    return list(db.scalars(stmt.order_by(FocNote.id.desc()).limit(limit)).all())


def note_out(note: FocNote, warehouses: dict[int, str] | None = None) -> dict:
    return {
        "id": note.id, "note_number": note.note_number, "note_date": note.note_date,
        "financial_year": note.financial_year, "warehouse_id": note.warehouse_id,
        "warehouse": (warehouses or {}).get(note.warehouse_id),
        "distributor_id": note.distributor_id,
        "recipient_name": note.recipient_name,
        "recipient_address": note.recipient_address,
        "recipient_contact": note.recipient_contact,
        "reason": note.reason, "reason_note": note.reason_note,
        "notional_value": (str(note.notional_value)
                           if note.notional_value is not None else None),
        "status": note.status, "correction": note.correction,
        "created_by": note.created_by, "created_at": note.created_at,
        "approved_by": note.approved_by, "approved_at": note.approved_at,
        "rejected_by": note.rejected_by, "rejected_at": note.rejected_at,
        "rejection_reason": note.rejection_reason,
        "reversed_by": note.reversed_by, "reversed_at": note.reversed_at,
        "reversal_reason": note.reversal_reason,
        "lines": [{
            "id": line.id, "product_id": line.product_id,
            "batch_id": line.batch_id, "qty": str(line.qty),
            "unit_notional_value": (str(line.unit_notional_value)
                                    if line.unit_notional_value is not None else None),
            "line_notional_value": (str(line.line_notional_value)
                                    if line.line_notional_value is not None else None),
            "movement_id": line.movement_id,
        } for line in note.lines],
    }


def foc_stock(db: Session) -> list[dict]:
    """Every product holding free stock, with the pools kept separate."""
    product_ids = sorted(db.scalars(
        select(Batch.product_id).join(StockMovement, StockMovement.batch_id == Batch.id)
        .distinct()).all())
    out = []
    for product_id in product_ids:
        plan = replay(db, product_id)
        if plan.foc_qty == 0 and plan.costed_qty == 0:
            continue
        product = db.get(Product, product_id)
        out.append({
            "product_id": product_id, "sku": product.sku if product else None,
            "name": product.name if product else None,
            "on_hand": str(plan.qty_on_hand), "foc_qty": str(plan.foc_qty),
            "costed_qty": str(plan.costed_qty),
            "average": str(plan.average) if plan.average is not None else None,
        })
    return out


# --------------------------------------------------------------- correction
def _preview_numbers(db: Session, count: int, day: date) -> list[str]:
    fy = financial_year(day)
    label = fy.replace("-", "")
    seq = db.scalar(select(DocumentSequence).where(
        DocumentSequence.doc_type == "foc_note",
        DocumentSequence.financial_year == fy))
    last = seq.last_number if seq is not None else 0
    for number in db.scalars(select(FocNote.note_number)
                             .where(FocNote.financial_year == fy)).all():
        tail = number.rsplit("/", 1)[-1]
        if tail.isdigit():
            last = max(last, int(tail))
    return [f"FOC/{label}/{last + i:06d}" for i in range(1, count + 1)]


def _po7_rows(db: Session, product_id: int, base_id: int) -> list[StockMovement]:
    rows = list(db.scalars(
        select(StockMovement).join(Batch, Batch.id == StockMovement.batch_id)
        .where(Batch.product_id == product_id,
               StockMovement.movement_type == "receipt",
               StockMovement.id != base_id,
               StockMovement.unit_cost.is_(None),
               StockMovement.cost_source.is_(None))
        .order_by(StockMovement.created_at, StockMovement.id)).all())
    out = []
    for movement in rows:
        if movement.ref_type != "grn" or not movement.ref_id.isdigit():
            continue
        grn = db.get(GoodsReceipt, int(movement.ref_id))
        if grn is None:
            continue
        line = db.scalar(select(PurchaseOrderLine).where(
            PurchaseOrderLine.po_id == grn.po_id,
            PurchaseOrderLine.product_id == product_id))
        if line is not None and (line.rate_remark or "").strip().lower() == "foc":
            out.append(movement)
    return out


def _digest(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint(state: dict, target: dict) -> str:
    return _digest({"state": state, "target": target})


def correction_plan(db: Session, *, note_date: date, warehouse_id: int,
                    reason: str, reason_note: str | None,
                    notional_value: Decimal | None,
                    recipients: list[dict], flag_po7: bool,
                    base_movement_id: int = 1, po_line_id: int = 1) -> dict:
    """The exact rows an apply would write, and a fingerprint of the input state."""
    if note_date > business_today():
        raise FocError("The distribution date cannot be in the future", 422)
    if reason not in REASONS:
        raise FocError(f"reason must be one of {', '.join(REASONS)}", 422)
    if not recipients:
        raise FocError("Name at least one recipient", 422)

    base = db.get(StockMovement, base_movement_id)
    if base is None:
        raise FocError("The base receipt movement was not found", 404)
    batch = db.get(Batch, base.batch_id)
    product = db.get(Product, batch.product_id) if batch else None
    if batch is None or product is None:
        raise FocError("The base receipt has no batch", 409)
    if base.movement_type != "receipt" or Decimal(base.qty_delta) <= 0:
        raise FocError("The base movement is not a receipt", 409)
    if base.cost_source not in (None, FOC) or base.unit_cost not in (None, ZERO):
        raise FocError("The base receipt already carries a real cost; refusing to relabel it")
    if batch.warehouse_id != warehouse_id:
        raise FocError("The base receipt is in another warehouse", 409)
    received_on = base.created_at.astimezone(IST).date() if base.created_at else note_date
    if note_date < received_on:
        raise FocError("The distribution cannot predate the receipt", 422)

    po_line = db.get(PurchaseOrderLine, po_line_id)
    if po_line is None or po_line.product_id != product.id:
        raise FocError("The PO line does not match the receipt's product", 409)
    remark = (po_line.rate_remark or "").strip().lower() or None
    if remark not in (None, FOC):
        raise FocError(f"PO line {po_line.id} already has remark '{po_line.rate_remark}'")

    total = sum((Decimal(r["qty"]) for r in recipients), ZERO)
    if total != Decimal(base.qty_delta):
        raise FocError(
            f"Recipient quantities total {total:f}, but the receipt is "
            f"{Decimal(base.qty_delta):f}", 422)
    for recipient in recipients:
        if not _clean(recipient.get("name"), 150):
            raise FocError("Every recipient needs a name", 422)
        if Decimal(recipient["qty"]) <= 0:
            raise FocError("Every recipient quantity must be positive", 422)

    po7 = _po7_rows(db, product.id, base.id) if flag_po7 else []
    numbers = _preview_numbers(db, len(recipients), note_date)
    state = {
        "po_line": {"id": po_line.id, "unit_cost": str(po_line.unit_cost),
                    "rate_remark": po_line.rate_remark},
        "base_movement": {"id": base.id, "unit_cost": str(base.unit_cost),
                          "cost_source": base.cost_source,
                          "qty": str(base.qty_delta)},
        "po7_movements": [{"id": m.id, "unit_cost": str(m.unit_cost),
                           "cost_source": m.cost_source, "qty": str(m.qty_delta)}
                          for m in po7],
        "batch": {"id": batch.id, "on_hand": str(batch.on_hand),
                  "warehouse_id": batch.warehouse_id},
        "foc_on_hand": str(replay(db, product.id).foc_qty),
        "note_numbers": numbers,
        "locked": active_period_lock(db, "accounting", note_date) is not None,
    }
    target = {
        "note_date": str(note_date), "warehouse_id": warehouse_id,
        "reason": reason, "reason_note": reason_note,
        "notional_value": str(notional_value) if notional_value is not None else None,
        "recipients": [{"name": r["name"], "address": r.get("address"),
                        "contact": r.get("contact"),
                        "distributor_id": r.get("distributor_id"),
                        "qty": str(r["qty"])} for r in recipients],
        "flag_po7": bool(flag_po7), "base_movement_id": base.id,
        "po_line_id": po_line.id, "product_id": product.id, "batch_id": batch.id,
        "corrections": {
            "po_line_remark": "foc",
            "movement_ids": [base.id] + [m.id for m in po7],
        },
    }
    return {"fingerprint": _fingerprint(state, target),
            "target_signature": _digest(target), "state": state,
            "target": target, "product": {"id": product.id, "sku": product.sku,
                                          "name": product.name},
            "notes": [{"note_number": n, "recipient": r["name"],
                       "qty": str(r["qty"])} for n, r in zip(numbers, recipients)],
            "already_applied": _already_applied(db, _digest(target))}


def _already_applied(db: Session, target_signature: str) -> bool:
    """The distribution already exists, whatever the ledger looks like now.

    The full fingerprint includes the before-state, which necessarily changes
    once the correction is applied. The target alone is stable, so a repeated
    apply is recognised instead of writing the notes twice.
    """
    for row in db.scalars(select(AuditLog).where(AuditLog.action == "foc.correction")):
        changes = row.changes or {}
        if changes.get("target_signature") == target_signature:
            return True
    return False


def _allocate_notional(recipients: list[dict], total_value: Decimal | None) -> list[Decimal | None]:
    if total_value is None:
        return [None] * len(recipients)
    total_qty = sum((Decimal(r["qty"]) for r in recipients), ZERO)
    if total_qty <= 0:
        return [None] * len(recipients)
    unit = _amount(total_value / total_qty)
    values = [_amount(unit * Decimal(r["qty"])) for r in recipients]
    # Put the rounding difference on the last note so the memo adds up exactly.
    values[-1] = _amount(total_value - sum(values[:-1], ZERO))
    return values


def _correction_creator(db: Session, creator_id: int, approver) -> User:
    """The Administrator whose name goes on the notes, distinct from the approver."""
    creator = db.get(User, creator_id)
    if creator is None:
        raise FocError("The named creator was not found", 404)
    if not creator.is_active:
        raise FocError("The named creator is not an active user", 409)
    if creator.id == approver.id:
        raise FocError("The creator and approver must be different Administrators", 409)
    if not is_admin(db, creator):
        raise FocError("The creator must be an Administrator", 409)
    if "foc:write" not in role_permissions(db, creator):
        raise FocError("The creator needs free-sample write access", 409)
    return creator


def apply_correction(db: Session, *, expected_fingerprint: str, creator_id: int,
                     approver, **kwargs) -> dict:
    """Apply the approved historical plan atomically, or refuse as stale."""
    creator = _correction_creator(db, creator_id, approver)
    plan = correction_plan(db, **kwargs)
    if plan["already_applied"]:
        return {**plan, "applied": False, "detail": "This correction was already applied."}
    if plan["fingerprint"] != expected_fingerprint:
        raise StaleFocCorrection(
            "The database changed since this correction was approved. "
            "Generate a new plan and approve its fingerprint.")
    if plan["state"]["locked"]:
        raise FocLockedPeriod(
            "The distribution date falls in a locked accounting period. "
            "Unlock the month first.")
    _lock_check(db, kwargs["note_date"])

    target = plan["target"]
    po_line = db.get(PurchaseOrderLine, target["po_line_id"])
    before_remark = po_line.rate_remark
    if before_remark != "foc":
        po_line.rate_remark = "foc"
        audit(db, approver.id, "po_line.rate_remark", f"po_line:{po_line.id}", {
            "before": before_remark, "after": "foc",
            "reason": "FOC sample stock (audited correction)",
        })

    corrected = []
    for movement_id in target["corrections"]["movement_ids"]:
        movement = db.get(StockMovement, movement_id)
        before = {"unit_cost": str(movement.unit_cost) if movement.unit_cost is not None
                  else None,
                  "cost_source": movement.cost_source}
        movement.unit_cost, movement.cost_source = ZERO, FOC
        corrected.append({"movement_id": movement.id, "before": before,
                          "after": {"unit_cost": "0.00", "cost_source": FOC}})
        audit(db, approver.id, "stock.foc_correction", f"movement:{movement.id}", {
            "before": before, "after": {"unit_cost": "0.00", "cost_source": FOC},
            "reason": "FOC sample stock (audited correction)",
        })
    db.flush()

    product = db.get(Product, target["product_id"])
    batch_id = target["batch_id"]
    distribution = sum((Decimal(r["qty"]) for r in kwargs["recipients"]), ZERO)
    available = replay(db, product.id).foc_qty
    if available < distribution:
        raise FocError(
            f"After the correction only {available:f} FOC units of {product.sku} are "
            f"on hand; the distribution gives away {distribution:f}.", 409)
    notes = []
    allocations = _allocate_notional(kwargs["recipients"], kwargs.get("notional_value"))
    for index, (recipient, value) in enumerate(zip(kwargs["recipients"], allocations)):
        note = create_note(
            db, actor=creator, note_date=kwargs["note_date"],
            warehouse_id=kwargs["warehouse_id"], recipient_name=recipient["name"],
            recipient_address=recipient.get("address"),
            recipient_contact=recipient.get("contact"),
            distributor_id=recipient.get("distributor_id"),
            reason=kwargs["reason"], reason_note=kwargs.get("reason_note"),
            notional_value=value,
            lines=[{"product_id": product.id, "batch_id": batch_id,
                    "qty": Decimal(recipient["qty"])}],
            correction=True)
        if note.note_number != plan["notes"][index]["note_number"]:
            raise StaleFocCorrection(
                "Another free-sample note took the next number during apply; "
                "the plan is stale. Generate and approve a new fingerprint.")
        _post_note(db, note, approver.id)
        note.status, note.approved_by = APPROVED, approver.id
        note.approved_at = datetime.now(timezone.utc)
        audit(db, approver.id, "foc.approve", f"foc:{note.id}", {
            "note_number": note.note_number, "note_date": str(note.note_date),
            "recipient": note.recipient_name, "correction": True,
            "creator_id": creator.id,
            "lines": [{"batch_id": l.batch_id, "qty": str(l.qty),
                       "movement_id": l.movement_id} for l in note.lines]})
        notes.append(note.note_number)

    audit(db, approver.id, "foc.correction", "foc:correction", {
        "fingerprint": plan["fingerprint"],
        "target_signature": plan["target_signature"],
        "creator_id": creator.id,
        "approver_id": approver.id,
        "po_line_id": po_line.id,
        "movements": corrected,
        "notes": notes,
        "recipient_total": str(sum((Decimal(r["qty"]) for r in kwargs["recipients"]), ZERO)),
        "flag_po7": target["flag_po7"],
        "note_date": str(kwargs["note_date"]),
        "warehouse_id": kwargs["warehouse_id"],
    })
    db.flush()
    return {**plan, "applied": True, "notes_created": notes,
            "movements_corrected": corrected}
