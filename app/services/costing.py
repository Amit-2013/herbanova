"""Stock cost capture: weighted average per product, company-wide.

Cost is captured when the ledger row is written, not reconstructed at report
time except by the explicit backfill and correction tools:

* a receipt carries the purchase-order rate (freight and discounts are not in it,
  because they are not recorded);
* an issue carries the product's moving weighted average across every warehouse;
* a return carries the cost at which the invoice issued the goods.

The ledger stays append-only for quantities. Cost corrections are the one
deliberate exception: an audited tool may replace the captured cost on a
product's movements after a late purchase rate, then replays that product and
reports exactly which invoices changed.

A product whose on-hand stock includes any quantity with no cost cannot produce
a clean issue cost. That issue is stored with `cost_source = 'partial'` (plus
the best available average when there is one) and its invoice is reported as
partially costed, never with a silent zero.

Concurrent issues of the same product serialise on the product row
(`lock_products`): the reader that computes the average holds the row until its
issue rows are committed, so a second issue cannot compute from a stale ledger.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core import (AuditLog, Batch, Invoice, InvoiceLine, Product,
                           PurchaseOrder, PurchaseOrderLine, StockMovement)
from ..models.costs import CostCorrection
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine
from .audit import audit

CENT = Decimal("0.01")
ZERO = Decimal("0")
PO_RECEIPT = "po_receipt"
WEIGHTED_AVERAGE = "weighted_average"
PARTIAL = "partial"
RETURN = "return"
UNCOSTED = "uncosted"
COST_SOURCES = (PO_RECEIPT, WEIGHTED_AVERAGE, PARTIAL, RETURN, UNCOSTED)
ATTRIBUTION_AUDIT = "accounts.cost_attribution"
COST_BACKFILL_AUDIT = "accounts.cost_backfill"


class LockedPeriodError(Exception):
    """An accounting month is locked, so the correction must not run."""


class StaleAttributionPlanError(Exception):
    """The database no longer matches the attribution plan that was approved."""


class StaleCostPlanError(Exception):
    """The database no longer matches the cost plan that was approved."""


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def lock_products(db: Session, product_ids) -> None:
    """Serialise issue costing on the product rows, in a fixed order.

    The caller reads the average and writes the issue cost in one transaction.
    Holding `FOR UPDATE` on each product until commit means a second issue of the
    same product replays a ledger that already includes the first one. Sorting the
    ids keeps a multi-product dispatch from deadlocking with another.
    """
    for product_id in sorted(set(product_ids)):
        db.execute(select(Product.id).where(Product.id == product_id)
                   .with_for_update()).all()


@dataclass
class MovementCost:
    movement_id: int
    unit_cost: Decimal | None
    cost_source: str
    invoice_id: int | None
    movement_type: str
    qty: Decimal


@dataclass
class ReplayPlan:
    product_id: int
    costs: dict[int, MovementCost] = field(default_factory=dict)
    qty_on_hand: Decimal = ZERO
    costed_qty: Decimal = ZERO
    costed_value: Decimal = ZERO
    warnings: list[str] = field(default_factory=list)

    @property
    def average(self) -> Decimal | None:
        if self.costed_qty <= 0:
            return None
        return money(self.costed_value / self.costed_qty)

    @property
    def uncosted_on_hand(self) -> Decimal:
        return max(self.qty_on_hand - self.costed_qty, ZERO)


def _product_movements(db: Session, product_id: int) -> list[StockMovement]:
    return list(db.scalars(
        select(StockMovement)
        .join(Batch, Batch.id == StockMovement.batch_id)
        .where(Batch.product_id == product_id)
        .order_by(StockMovement.created_at, StockMovement.id)).all())


def _po_unit_cost(db: Session, product_id: int, ref_id: str, batch_id: int,
                  cache: dict) -> Decimal | None:
    """The purchase-order rate behind a goods-receipt movement, if recorded."""
    key = (ref_id, batch_id)
    if key in cache:
        return cache[key]
    cost = None
    try:
        grn_id = int(ref_id)
    except (TypeError, ValueError):
        cache[key] = None
        return None
    line = db.scalar(select(GoodsReceiptLine).where(
        GoodsReceiptLine.grn_id == grn_id,
        GoodsReceiptLine.batch_id == batch_id,
        GoodsReceiptLine.product_id == product_id))
    if line is not None:
        grn = db.get(GoodsReceipt, grn_id)
        if grn is not None:
            po_line = db.scalar(select(PurchaseOrderLine).where(
                PurchaseOrderLine.po_id == grn.po_id,
                PurchaseOrderLine.product_id == product_id))
            if po_line is not None and po_line.unit_cost is not None:
                cost = money(po_line.unit_cost)
    cache[key] = cost
    return cost


def _add_stock(plan: ReplayPlan, qty: Decimal, cost: Decimal | None) -> None:
    plan.qty_on_hand += qty
    if cost is not None:
        plan.costed_qty += qty
        plan.costed_value += qty * cost


def _take_stock(plan: ReplayPlan, qty: Decimal) -> None:
    average = plan.average
    plan.qty_on_hand -= qty
    if average is not None:
        costed_take = min(qty, plan.costed_qty)
        plan.costed_qty -= costed_take
        plan.costed_value -= costed_take * average
    if plan.costed_qty <= 0:
        plan.costed_qty = ZERO
        plan.costed_value = ZERO
    if plan.qty_on_hand < 0:
        plan.warnings.append("movement ledger goes negative")


def replay(db: Session, product_id: int, *,
           receipt_overrides: dict[int, Decimal] | None = None) -> ReplayPlan:
    """Replay one product's movements through the weighted-average rule.

    Stored costs are used when present. A legacy receipt row with no stored cost
    is derived from its purchase order; a correction passes `receipt_overrides`
    keyed by movement id.
    """
    overrides = receipt_overrides or {}
    plan = ReplayPlan(product_id=product_id)
    grn_cache: dict = {}
    invoice_issues: dict[tuple[int, int], list[tuple[Decimal, Decimal, bool]]] = {}

    for m in _product_movements(db, product_id):
        qty = Decimal(m.qty_delta)
        source = m.cost_source
        cost = money(m.unit_cost) if m.unit_cost is not None else None

        if m.movement_type == "receipt" and m.id in overrides:
            cost, source = money(overrides[m.id]), PO_RECEIPT
        elif qty < 0 and m.movement_type == "issue":
            average = plan.average
            cost = average
            source = PARTIAL if (plan.uncosted_on_hand > 0 or average is None) \
                else WEIGHTED_AVERAGE
            if m.invoice_id:
                invoice_issues.setdefault((m.invoice_id, product_id), []).append(
                    (-qty, cost, source == PARTIAL))
        elif qty > 0 and m.movement_type == "return":
            if cost is None:
                issued = invoice_issues.get((m.invoice_id, product_id)) if m.invoice_id else None
                if issued and all(u is not None for _q, u, _p in issued):
                    total_qty = sum(q for q, _u, _p in issued)
                    cost = money(sum(q * (u or ZERO) for q, u, _p in issued) / total_qty) \
                        if total_qty > 0 else None
                    source = PARTIAL if any(p for _q, _u, p in issued) else RETURN
                elif plan.average is not None:
                    cost, source = plan.average, RETURN
                else:
                    source = PARTIAL
            else:
                source = source or RETURN
        elif qty > 0:
            if cost is None and m.ref_type == "grn":
                cost = _po_unit_cost(db, product_id, m.ref_id, m.batch_id, grn_cache)
            if cost is not None:
                source = source or (PO_RECEIPT if m.ref_type == "grn" else WEIGHTED_AVERAGE)
            else:
                source = UNCOSTED
        else:
            cost = plan.average
            source = source or (WEIGHTED_AVERAGE if cost is not None else UNCOSTED)

        if qty > 0:
            _add_stock(plan, qty, cost)
        elif qty < 0:
            _take_stock(plan, -qty)
        else:
            plan.warnings.append(f"movement {m.id} has zero quantity")

        plan.costs[m.id] = MovementCost(
            movement_id=m.id, unit_cost=money(cost) if cost is not None else None,
            cost_source=source or UNCOSTED, invoice_id=m.invoice_id,
            movement_type=m.movement_type, qty=qty)
    return plan


def issue_cost(db: Session, product_id: int) -> tuple[Decimal | None, str]:
    """The cost and source an issue should carry, measured over all warehouses."""
    plan = replay(db, product_id)
    if plan.uncosted_on_hand > 0 or plan.average is None:
        return plan.average, PARTIAL
    return plan.average, WEIGHTED_AVERAGE


def invoice_product_cost(db: Session, invoice_id: int,
                         product_id: int) -> tuple[Decimal | None, str]:
    """The cost at which an invoice issued a product, for crediting a return.

    Uses the issue movements attributed to that invoice. When the invoice has no
    attributed issue (a legacy invoice from before attribution), the product's
    current average is offered but flagged partial, because the original cost is
    not provable from the ledger.
    """
    rows = list(db.scalars(
        select(StockMovement)
        .join(Batch, Batch.id == StockMovement.batch_id)
        .where(StockMovement.invoice_id == invoice_id,
               StockMovement.movement_type == "issue",
               StockMovement.qty_delta < 0,
               Batch.product_id == product_id)).all())
    if rows:
        qty = sum(-Decimal(m.qty_delta) for m in rows)
        if qty > 0 and all(m.unit_cost is not None for m in rows):
            value = sum(-Decimal(m.qty_delta) * money(m.unit_cost) for m in rows)
            clean = all(m.cost_source == WEIGHTED_AVERAGE for m in rows)
            return money(value / qty), RETURN if clean else PARTIAL
        return None, PARTIAL
    average, _source = issue_cost(db, product_id)
    return average, PARTIAL


def apply_plan(db: Session, plan: ReplayPlan) -> list[StockMovement]:
    """Write proposed costs onto movements that differ. The caller commits."""
    changed = []
    for m in _product_movements(db, plan.product_id):
        proposed = plan.costs.get(m.id)
        if proposed is None:
            continue
        stored = money(m.unit_cost) if m.unit_cost is not None else None
        if stored != proposed.unit_cost or (m.cost_source or UNCOSTED) != proposed.cost_source:
            m.unit_cost = proposed.unit_cost
            m.cost_source = proposed.cost_source
            changed.append(m)
    db.flush()
    return changed


def _invoice_cogs(movements: list[StockMovement],
                  costs: dict[int, MovementCost]) -> dict[int, dict]:
    """COGS from a cost map. Issues add, stock returns subtract."""
    out: dict[int, dict] = {}
    for m in movements:
        if not m.invoice_id:
            continue
        item = out.setdefault(m.invoice_id, {
            "cogs": ZERO, "issue_qty": ZERO, "return_qty": ZERO,
            "uncosted_issue_qty": ZERO, "clean": True})
        proposed = costs.get(m.id)
        cost = proposed.unit_cost if proposed else (
            money(m.unit_cost) if m.unit_cost is not None else None)
        source = proposed.cost_source if proposed else (m.cost_source or UNCOSTED)
        qty = Decimal(m.qty_delta)
        if m.movement_type == "issue" and qty < 0:
            item["issue_qty"] += -qty
            if cost is None:
                item["uncosted_issue_qty"] += -qty
                item["clean"] = False
            else:
                item["cogs"] += (-qty) * cost
                if source == PARTIAL:
                    item["clean"] = False
        elif m.movement_type == "return" and qty > 0:
            item["return_qty"] += qty
            if cost is None:
                item["clean"] = False
            else:
                item["cogs"] -= qty * cost
                if source == PARTIAL:
                    item["clean"] = False
    for item in out.values():
        item["cogs"] = money(item["cogs"])
        if item["issue_qty"] <= 0:
            item["clean"] = False
    return out


def invoice_cogs(db: Session, invoice_ids: list[int] | None = None) -> dict[int, dict]:
    """Cost of goods for each invoice, with an explicit partial flag.

    A clean invoice has at least one issue and every issue carried a cost.
    Anything else is `costed = False` with a reason, so a gross profit can be
    labelled "partial, X of Y invoices costed" rather than presented as complete.
    """
    stmt = select(Invoice.id, Invoice.invoice_number)
    if invoice_ids:
        stmt = stmt.where(Invoice.id.in_(invoice_ids))
    invoices = {iid: number for iid, number in db.execute(stmt).all()}
    if not invoices:
        return {}
    movements = list(db.scalars(select(StockMovement).where(
        StockMovement.invoice_id.in_(list(invoices)))).all())
    costs = {m.id: MovementCost(
        m.id, money(m.unit_cost) if m.unit_cost is not None else None,
        m.cost_source or UNCOSTED, m.invoice_id, m.movement_type,
        Decimal(m.qty_delta)) for m in movements}
    raw = _invoice_cogs(movements, costs)
    result = {}
    for iid, number in invoices.items():
        item = raw.get(iid, {"cogs": ZERO, "issue_qty": ZERO, "return_qty": ZERO,
                             "uncosted_issue_qty": ZERO, "clean": False})
        reason = None
        if item["issue_qty"] <= 0:
            reason = "no stock issue is attributed to this invoice"
        elif item["uncosted_issue_qty"] > 0:
            reason = (f"{item['uncosted_issue_qty']:f} of {item['issue_qty']:f} "
                      "issued units have no cost")
        elif not item["clean"]:
            reason = ("the captured cost is partial: some on-hand stock had no cost "
                      "when the goods were issued")
        result[iid] = {"invoice_id": iid, "invoice_number": number,
                       "cogs": item["cogs"], "issue_qty": item["issue_qty"],
                       "return_qty": item["return_qty"], "costed": item["clean"],
                       "partial_reason": reason}
    return result


def _stored_costs(movements: list[StockMovement]) -> dict[int, MovementCost]:
    return {m.id: MovementCost(
        m.id, money(m.unit_cost) if m.unit_cost is not None else None,
        m.cost_source or UNCOSTED, m.invoice_id, m.movement_type,
        Decimal(m.qty_delta)) for m in movements}


def _invoice_issue_reason(item: dict) -> str | None:
    if item["issue_qty"] <= 0:
        return "no stock issue is attributed to this invoice"
    if item["uncosted_issue_qty"] > 0:
        return (f"{item['uncosted_issue_qty']:f} of {item['issue_qty']:f} issued "
                "units have no cost")
    if not item["clean"]:
        return ("the captured cost is partial: some on-hand stock had no cost "
                "when the goods were issued")
    return None


def backfill_plan(db: Session, product_ids: list[int] | None = None) -> dict:
    """What a cost backfill would change, without changing anything.

    Each movement carries its current and proposed cost and source, and every
    issued invoice reports its cost of goods before and after, with the reason
    when it would stay partial. Money is printed as a string only; this is a
    reviewed proposal, never a write.
    """
    stmt = (select(Batch.product_id)
            .join(StockMovement, StockMovement.batch_id == Batch.id).distinct())
    if product_ids:
        stmt = stmt.where(Batch.product_id.in_(product_ids))
    products = sorted(db.scalars(stmt).all())
    rows = []
    proposed_costs: dict[int, MovementCost] = {}
    for pid in products:
        movements = _product_movements(db, pid)
        plan = replay(db, pid)
        proposed_costs.update(plan.costs)
        would_set = would_change = same = 0
        detail = []
        for m in movements:
            proposed = plan.costs.get(m.id)
            if proposed is None:
                continue
            stored = money(m.unit_cost) if m.unit_cost is not None else None
            matches = (stored == proposed.unit_cost
                       and (m.cost_source or UNCOSTED) == proposed.cost_source)
            if matches:
                same += 1
            elif stored is None and proposed.unit_cost is not None:
                would_set += 1
            else:
                would_change += 1
            detail.append({
                "movement_id": m.id, "movement_type": m.movement_type,
                "qty_delta": f"{Decimal(m.qty_delta):f}",
                "current_unit_cost": str(stored) if stored is not None else None,
                "current_cost_source": m.cost_source,
                "unit_cost": (str(proposed.unit_cost)
                              if proposed.unit_cost is not None else None),
                "cost_source": proposed.cost_source,
                "changed": not matches,
            })
        before = _invoice_cogs(movements, _stored_costs(movements))
        after = _invoice_cogs(movements, plan.costs)
        affected = []
        for invoice_id in sorted(set(before) | set(after)):
            b = before.get(invoice_id, {"cogs": ZERO, "clean": False})
            a = after.get(invoice_id, {"cogs": ZERO, "clean": False})
            if b["cogs"] != a["cogs"] or b["clean"] != a["clean"]:
                affected.append({"invoice_id": invoice_id,
                                 "before_cogs": b["cogs"], "after_cogs": a["cogs"],
                                 "before_costed": b["clean"], "after_costed": a["clean"]})
        rows.append({"product_id": pid, "movements": len(movements),
                     "would_set_cost": would_set,
                     "would_change_source": would_change,
                     "already_matching": same,
                     "uncosted_on_hand": plan.uncosted_on_hand,
                     "average_after": plan.average,
                     "movements_detail": detail,
                     "affected_invoices": affected})

    linked = list(db.scalars(select(StockMovement)
                             .where(StockMovement.invoice_id.is_not(None))).all())
    before_all = _invoice_cogs(linked, _stored_costs(linked))
    after_all = _invoice_cogs(linked, {**_stored_costs(linked), **proposed_costs})
    empty = {"cogs": ZERO, "issue_qty": ZERO, "return_qty": ZERO,
             "uncosted_issue_qty": ZERO, "clean": False}
    invoices = []
    for invoice_id, number in db.execute(
            select(Invoice.id, Invoice.invoice_number)
            .where(Invoice.status == "issued").order_by(Invoice.id)).all():
        b = before_all.get(invoice_id, empty)
        a = after_all.get(invoice_id, empty)
        invoices.append({
            "invoice_id": invoice_id, "invoice_number": number,
            "cogs_before": str(b["cogs"]), "cogs_after": str(a["cogs"]),
            "costed_before": b["clean"], "costed_after": a["clean"],
            "partial_reason_after": None if a["clean"] else _invoice_issue_reason(a),
        })

    return {"products": rows,
            "movements": sum(r["movements"] for r in rows),
            "would_set_cost": sum(r["would_set_cost"] for r in rows),
            "would_change_source": sum(r["would_change_source"] for r in rows),
            "affected_invoices": sum(len(r["affected_invoices"]) for r in rows),
            "invoices": invoices}


def cost_plan_payload(plan: dict) -> dict:
    """The material part of a cost plan: proposals per movement and per invoice."""
    return {
        "products": [
            {"product_id": row["product_id"],
             "movements": row["movements_detail"],
             "uncosted_on_hand": f"{row['uncosted_on_hand']:f}",
             "average_after": (None if row["average_after"] is None
                               else str(row["average_after"]))}
            for row in plan["products"]],
        "invoices": plan["invoices"],
    }


def cost_fingerprint(plan: dict) -> str:
    """Stable SHA-256 of the cost plan, for approval and apply."""
    return _sha256(cost_plan_payload(plan))


def _cost_audit(db: Session, fingerprint: str) -> dict | None:
    for changes in db.scalars(select(AuditLog.changes).where(
            AuditLog.action == COST_BACKFILL_AUDIT)
            .order_by(AuditLog.id.desc())).all():
        if (changes or {}).get("plan_fingerprint") == fingerprint:
            return changes
    return None


def _costs_intact(db: Session, costs: list[dict]) -> bool:
    if not costs:
        return False
    ids = [entry["movement_id"] for entry in costs]
    actual = {m.id: (money(m.unit_cost) if m.unit_cost is not None else None,
                     m.cost_source or UNCOSTED)
              for m in db.scalars(select(StockMovement)
                                  .where(StockMovement.id.in_(ids))).all()}
    if len(actual) != len(ids):
        return False
    for entry in costs:
        expected = (money(entry["unit_cost"]) if entry["unit_cost"] is not None
                    else None, entry["cost_source"] or UNCOSTED)
        if actual.get(entry["movement_id"]) != expected:
            return False
    return True


def apply_cost_backfill(db: Session, *, expected_fingerprint: str,
                        actor_id: int | None = None,
                        product_ids: list[int] | None = None,
                        operator: str | None = None) -> dict:
    """Write the approved cost proposals, guarded like the attribution apply.

    Nothing is written unless the live plan still hashes to the approved
    fingerprint. The product rows and the planned movements are locked, the plan
    is recomputed under those locks, and any change refuses the batch before a
    cost is set. An invoice whose cost of goods would move in a locked
    accounting month refuses the batch as a whole.

    Idempotent: re-running with the applied fingerprint is a no-op when every
    recorded cost is still in place, and writes no second audit row. The caller
    commits.
    """
    expected = (expected_fingerprint or "").strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("The plan fingerprint must be the 64-character SHA-256 "
                         "printed by the dry run")

    plan = backfill_plan(db, product_ids)
    current = cost_fingerprint(plan)
    if current != expected:
        prior = _cost_audit(db, expected)
        if prior is not None and _costs_intact(db, prior.get("costs", [])):
            return {"applied": False, "already_applied": True, "idempotent": True,
                    "movements_changed": 0, "products": 0, "audit_rows": 0,
                    "plan_fingerprint": current}
        raise StaleCostPlanError(
            "The database changed after this plan was made, so nothing was "
            "written. Run the dry run again and approve the new plan.")
    pending = [m for row in plan["products"]
               for m in row["movements_detail"] if m["changed"]]
    if not pending:
        return {"applied": False, "already_applied": False, "idempotent": False,
                "movements_changed": 0, "products": 0, "audit_rows": 0,
                "plan_fingerprint": current}

    pids = [row["product_id"] for row in plan["products"]]
    lock_products(db, pids)
    movement_ids = sorted(m["movement_id"] for m in pending)
    db.scalars(select(StockMovement).where(StockMovement.id.in_(movement_ids))
               .order_by(StockMovement.id).with_for_update()).all()

    plan = backfill_plan(db, product_ids)
    if cost_fingerprint(plan) != expected:
        raise StaleCostPlanError(
            "The database changed while this plan was being locked, so nothing "
            "was written. Run the dry run again and approve the new plan.")

    affected = [i["invoice_id"] for i in plan["invoices"]
                if i["cogs_before"] != i["cogs_after"]
                or i["costed_before"] != i["costed_after"]]
    if affected:
        from .hr import active_period_lock
        locked: dict[tuple[int, int], list[str]] = {}
        for invoice_id, number, day in db.execute(
                select(Invoice.id, Invoice.invoice_number, Invoice.invoice_date)
                .where(Invoice.id.in_(affected))).all():
            lock = active_period_lock(db, "accounting", day)
            if lock is not None:
                locked.setdefault((lock.year, lock.month), []).append(number)
        if locked:
            periods = "; ".join(
                f"{year}-{month:02d} ({', '.join(sorted(numbers))})"
                for (year, month), numbers in sorted(locked.items()))
            raise LockedPeriodError(
                "The accounting period is locked, so this backfill cannot move "
                f"cost of goods in: {periods}. Unlock the month first.")

    costs = []
    changed_total = 0
    for row in plan["products"]:
        changed = apply_plan(db, replay(db, row["product_id"]))
        changed_total += len(changed)
        for movement in changed:
            costs.append({
                "movement_id": movement.id, "product_id": row["product_id"],
                "unit_cost": (str(money(movement.unit_cost))
                              if movement.unit_cost is not None else None),
                "cost_source": movement.cost_source,
            })
    audit(db, actor_id, COST_BACKFILL_AUDIT, "stock_movements:cost_backfill",
          {"plan_fingerprint": current, "products": pids,
           "movements": changed_total, "costs": costs,
           "operator": (operator or "").strip() or None,
           "tool": "backfill_costs.py"}, notify=False)
    return {"applied": True, "already_applied": False, "idempotent": False,
            "movements_changed": changed_total, "products": len(pids),
            "audit_rows": 1, "plan_fingerprint": current}


def _issue_quantities(movements: list[StockMovement],
                      batches: dict[int, Batch]) -> dict[int, Decimal]:
    quantities: dict[int, Decimal] = {}
    for m in movements:
        batch = batches.get(m.batch_id)
        if batch is None:
            continue
        quantities[batch.product_id] = quantities.get(batch.product_id, ZERO) \
            + (-Decimal(m.qty_delta))
    return quantities


def attribution_plan(db: Session) -> dict:
    """Which legacy issue rows can be linked to their invoice, without writing.

    A candidate is a sales order that has exactly one issued invoice and issue
    rows with no `invoice_id`. It is proposed only when no issue row of that
    order is attributed at all, the products on both sides are the same set, and
    the issued quantity equals the invoiced quantity for every product. Every
    other order is reported with the reason, or as already attributed.

    Dry-run only: this function never writes.
    """
    invoices = db.execute(
        select(Invoice.id, Invoice.invoice_number, Invoice.sales_order_id)
        .where(Invoice.status == "issued").order_by(Invoice.id)).all()
    by_order: dict[int, list[tuple[int, str]]] = {}
    for invoice_id, number, so_id in invoices:
        by_order.setdefault(so_id, []).append((invoice_id, number))

    candidates, ambiguous = [], []
    attributed, without_issues = [], []
    for so_id in sorted(by_order):
        issued = by_order[so_id]
        invoice_ids = [i for i, _ in issued]
        invoice_numbers = [n for _, n in issued]
        issues = list(db.scalars(select(StockMovement).where(
            StockMovement.movement_type == "issue",
            StockMovement.qty_delta < 0,
            StockMovement.ref_type == "so",
            StockMovement.ref_id == str(so_id))).all())
        if not issues:
            without_issues.append({
                "sales_order_id": so_id, "invoice_ids": invoice_ids,
                "invoice_numbers": invoice_numbers,
                "reason": "no issue movement references this sales order",
            })
            continue
        unlinked = [m for m in issues if m.invoice_id is None]
        linked = [m for m in issues if m.invoice_id is not None]
        if not unlinked:
            attributed.append({
                "sales_order_id": so_id, "invoice_ids": invoice_ids,
                "invoice_numbers": invoice_numbers, "movements": len(linked),
            })
            continue
        if len(issued) != 1:
            ambiguous.append({
                "sales_order_id": so_id, "invoice_ids": invoice_ids,
                "invoice_numbers": invoice_numbers,
                "movement_ids": sorted(m.id for m in unlinked),
                "reason": f"sales order has {len(issued)} issued invoices, so its "
                          "issue rows cannot be assigned to one of them",
            })
            continue
        invoice_id, number = issued[0]
        if linked:
            ambiguous.append({
                "sales_order_id": so_id, "invoice_ids": invoice_ids,
                "invoice_numbers": invoice_numbers,
                "movement_ids": sorted(m.id for m in unlinked),
                "reason": f"{len(linked)} issue movements are already attributed "
                          f"and {len(unlinked)} are not",
            })
            continue

        batch_ids = sorted({m.batch_id for m in unlinked})
        batches = {b.id: b for b in db.scalars(
            select(Batch).where(Batch.id.in_(batch_ids))).all()}
        issued_qty = _issue_quantities(unlinked, batches)
        invoiced_qty: dict[int, Decimal] = {}
        for line in db.scalars(select(InvoiceLine).where(
                InvoiceLine.invoice_id == invoice_id)).all():
            invoiced_qty[line.product_id] = invoiced_qty.get(line.product_id, ZERO) \
                + Decimal(line.qty)

        entry = {
            "sales_order_id": so_id, "invoice_id": invoice_id,
            "invoice_number": number,
            "movement_ids": sorted(m.id for m in unlinked),
            "movements": len(unlinked),
        }
        missing = sorted(set(invoiced_qty) - set(issued_qty))
        extra = sorted(set(issued_qty) - set(invoiced_qty))
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"no issue for product ids {missing}")
            if extra:
                parts.append(f"issue for product ids {extra} not on the invoice")
            ambiguous.append({**entry, "reason": "; ".join(parts)})
            continue
        mismatched = [pid for pid in sorted(invoiced_qty)
                      if issued_qty[pid] != invoiced_qty[pid]]
        if mismatched:
            detail = ", ".join(
                f"product {pid}: issued {issued_qty[pid]:f} but invoiced "
                f"{invoiced_qty[pid]:f}" for pid in mismatched)
            ambiguous.append({**entry, "reason": f"quantities differ ({detail})"})
            continue
        entry["products"] = {str(pid): f"{issued_qty[pid]:f}"
                             for pid in sorted(issued_qty)}
        candidates.append(entry)

    return {
        "invoices_checked": len(invoices),
        "candidates": candidates,
        "candidates_movements": sum(c["movements"] for c in candidates),
        "ambiguous": ambiguous,
        "already_attributed": attributed,
        "without_issue_movements": without_issues,
    }


def _sha256(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def attribution_fingerprint(plan: dict) -> str:
    """Stable SHA-256 of the whole attribution plan, for approval and apply."""
    return _sha256(plan)


def _attribution_audit(db: Session, fingerprint: str) -> dict | None:
    """The changes of the audit row that recorded this exact plan, if any."""
    for changes in db.scalars(select(AuditLog.changes).where(
            AuditLog.action == ATTRIBUTION_AUDIT).order_by(AuditLog.id.desc())).all():
        if (changes or {}).get("plan_fingerprint") == fingerprint:
            return changes
    return None


def _links_intact(db: Session, links: list[dict]) -> bool:
    expected = {mid: link.get("invoice_id")
                for link in links or [] for mid in link.get("movement_ids", [])}
    if not expected:
        return False
    actual = {mid: iid for mid, iid in db.execute(
        select(StockMovement.id, StockMovement.invoice_id)
        .where(StockMovement.id.in_(sorted(expected)))).all()}
    return actual == expected


def apply_attribution(db: Session, *, expected_fingerprint: str,
                      actor_id: int | None = None,
                      operator: str | None = None) -> dict:
    """Link legacy issue rows to their invoice, guarded by the approved plan.

    The caller passes the SHA-256 fingerprint printed by the dry run. Nothing is
    written unless the live plan still hashes to exactly that value. The planned
    rows are then locked and the plan recomputed inside the same transaction, so
    a concurrent invoice or ledger change refuses the batch before any link is
    set. One audit row records the links; Telegram is not notified.

    Idempotent: re-running with the fingerprint already applied is a no-op when
    every recorded link is still in place, and writes no second audit row. If a
    recorded link was removed, the plan is stale and the call refuses.

    The caller commits.
    """
    expected = (expected_fingerprint or "").strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("The plan fingerprint must be the 64-character SHA-256 "
                         "printed by the dry run")

    plan = attribution_plan(db)
    current = attribution_fingerprint(plan)
    if current != expected:
        prior = _attribution_audit(db, expected)
        if prior is not None and _links_intact(db, prior.get("links", [])):
            return {"applied": False, "already_applied": True, "idempotent": True,
                    "attributed_movements": 0, "invoices": 0, "audit_rows": 0,
                    "plan_fingerprint": current}
        raise StaleAttributionPlanError(
            "The database changed after this plan was made, so nothing was "
            "written. Run the dry run again and approve the new plan.")
    if not plan["candidates"]:
        return {"applied": False, "already_applied": False, "idempotent": False,
                "attributed_movements": 0, "invoices": 0, "audit_rows": 0,
                "plan_fingerprint": current}

    movement_ids = sorted(mid for c in plan["candidates"]
                          for mid in c["movement_ids"])
    invoice_ids = sorted({c["invoice_id"] for c in plan["candidates"]})
    locked = {m.id: m for m in db.scalars(
        select(StockMovement).where(StockMovement.id.in_(movement_ids))
        .order_by(StockMovement.id).with_for_update()).all()}
    db.scalars(select(Invoice).where(Invoice.id.in_(invoice_ids))
               .order_by(Invoice.id).with_for_update()).all()

    if attribution_fingerprint(attribution_plan(db)) != expected:
        raise StaleAttributionPlanError(
            "The database changed while this plan was being locked, so nothing "
            "was written. Run the dry run again and approve the new plan.")

    links = []
    for candidate in plan["candidates"]:
        for mid in candidate["movement_ids"]:
            locked[mid].invoice_id = candidate["invoice_id"]
        links.append({"sales_order_id": candidate["sales_order_id"],
                      "invoice_id": candidate["invoice_id"],
                      "invoice_number": candidate["invoice_number"],
                      "movement_ids": candidate["movement_ids"]})
    movements = sum(len(link["movement_ids"]) for link in links)
    audit(db, actor_id, ATTRIBUTION_AUDIT, "stock_movements:attribution",
          {"plan_fingerprint": current, "links": links, "movements": movements,
           "invoices": len(links), "operator": (operator or "").strip() or None,
           "tool": "backfill_costs.py"}, notify=False)
    return {"applied": True, "already_applied": False, "idempotent": False,
            "attributed_movements": movements, "invoices": len(links),
            "audit_rows": 1, "plan_fingerprint": current, "links": links}


def correct_po_cost(db: Session, *, po_line_id: int, new_unit_cost: Decimal,
                    reason: str, actor_id: int) -> dict:
    """Apply a late purchase rate, replay the product and report what changed.

    The caller commits. Quantities never change; only captured costs do.
    """
    line = db.get(PurchaseOrderLine, po_line_id, with_for_update=True)
    if line is None:
        raise ValueError("Purchase order line not found")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("Give a reason for the cost correction")
    new_cost = money(new_unit_cost)
    if new_cost < 0:
        raise ValueError("The cost cannot be negative")
    po = db.get(PurchaseOrder, line.po_id)
    lock_products(db, [line.product_id])

    grn_ids = [gid for (gid,) in db.execute(
        select(GoodsReceipt.id).where(GoodsReceipt.po_id == line.po_id)).all()]
    movement_ids = set(db.scalars(
        select(StockMovement.id)
        .join(Batch, Batch.id == StockMovement.batch_id)
        .where(StockMovement.movement_type == "receipt",
               StockMovement.ref_type == "grn",
               StockMovement.ref_id.in_([str(g) for g in grn_ids]),
               Batch.product_id == line.product_id)).all())

    movements = _product_movements(db, line.product_id)
    before = _invoice_cogs(movements, {
        m.id: MovementCost(m.id, money(m.unit_cost) if m.unit_cost is not None else None,
                           m.cost_source or UNCOSTED, m.invoice_id, m.movement_type,
                           Decimal(m.qty_delta)) for m in movements})
    plan = replay(db, line.product_id,
                  receipt_overrides={mid: new_cost for mid in movement_ids})
    after = _invoice_cogs(movements, plan.costs)

    # A correction rewrites the cost of goods of every invoice whose issue cost
    # changes. If any of those invoices sits in a locked accounting month, refuse
    # before a single row is written, so a closed month cannot move.
    changed_ids = [iid for iid in sorted(set(before) | set(after))
                   if (before.get(iid, {"cogs": ZERO, "clean": False})["cogs"]
                       != after.get(iid, {"cogs": ZERO, "clean": False})["cogs"]
                       or before.get(iid, {"cogs": ZERO, "clean": False})["clean"]
                       != after.get(iid, {"cogs": ZERO, "clean": False})["clean"])]
    if changed_ids:
        from .hr import active_period_lock
        locked: dict[tuple[int, int], list[str]] = {}
        for invoice_id, number, day in db.execute(
                select(Invoice.id, Invoice.invoice_number, Invoice.invoice_date)
                .where(Invoice.id.in_(changed_ids))).all():
            lock = active_period_lock(db, "accounting", day)
            if lock is not None:
                locked.setdefault((lock.year, lock.month), []).append(number)
        if locked:
            periods = "; ".join(
                f"{year}-{month:02d} ({', '.join(sorted(numbers))})"
                for (year, month), numbers in sorted(locked.items()))
            raise LockedPeriodError(
                "The accounting period is locked, so this correction cannot move "
                f"cost of goods in: {periods}. Unlock the month first.")

    old_cost = money(line.unit_cost) if line.unit_cost is not None else None
    old_remark = line.rate_remark
    line.unit_cost = new_cost
    line.rate_remark = None
    changed = apply_plan(db, plan)

    invoices = []
    for invoice_id in sorted(set(before) | set(after)):
        b = before.get(invoice_id, {"cogs": ZERO, "clean": False})
        a = after.get(invoice_id, {"cogs": ZERO, "clean": False})
        number = db.scalar(select(Invoice.invoice_number).where(Invoice.id == invoice_id))
        invoices.append({"invoice_id": invoice_id, "invoice_number": number,
                         "before_cogs": b["cogs"], "after_cogs": a["cogs"],
                         "delta": money(a["cogs"] - b["cogs"]),
                         "costed_before": b["clean"], "costed_after": a["clean"]})
    sku = db.scalar(select(Product.sku).where(Product.id == line.product_id))
    result = {
        "product_id": line.product_id, "sku": sku,
        "po_id": line.po_id, "po_number": po.po_number if po else None,
        "po_line_id": line.id, "old_po_rate": old_cost, "new_po_rate": new_cost,
        "old_rate_remark": old_remark,
        "receipt_movements": len(movement_ids),
        "movements_changed": len(changed),
        "uncosted_on_hand": plan.uncosted_on_hand,
        "average_after": plan.average,
        "invoices": invoices,
        "before_total": money(sum(i["before_cogs"] for i in invoices)),
        "after_total": money(sum(i["after_cogs"] for i in invoices)),
    }
    db.add(CostCorrection(
        product_id=line.product_id, po_id=line.po_id, po_line_id=line.id,
        old_unit_cost=old_cost, new_unit_cost=new_cost, reason=reason,
        actor_id=actor_id,
        result={k: (str(v) if isinstance(v, Decimal) else v)
                for k, v in result.items() if k != "invoices"}))
    db.flush()
    return result
