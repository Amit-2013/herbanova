#!/usr/bin/env python
"""Remove exactly the demo records created by ``seed_demo.py``.

Safety:
- Rows are deleted by the ids recorded in ``demo_seed_manifest.json`` and only
  when their DEMO marker still matches (SKU, code, email, batch number).
- Before deleting anything, the script checks for records that were created
  after seeding against the demo masters (for example a real sales order for a
  demo distributor). If any exist, nothing is deleted and the operator is told
  what blocks the rollback.
- Audit history and document-number counters are append-only and stay.
- Nothing outside the manifest is touched.

Usage:
    python seed_demo_rollback.py          # dry run: list what would be removed
    python seed_demo_rollback.py --yes    # delete the demo rows
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import delete, func, or_, select

from app.core.db import SessionLocal
from app.models.accounts import Payment
from app.models.core import (ApprovalRequest, Batch, CreditNote, CreditNoteLine,
                             DebitNote, Distributor, Invoice, InvoiceLine, Lead,
                             LeadActivity, Product, PurchaseOrder, PurchaseOrderLine,
                             SalesOrder, SalesOrderLine, StockMovement, User)
from app.models.suppliers import GoodsReceipt, GoodsReceiptLine, Supplier
from app.models.users import Employee

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "demo_seed_manifest.json"


def _ids_of(section) -> list[int]:
    """Manifest sections are either a list of ids or {marker: id} mappings."""
    if isinstance(section, list):
        return [int(v) for v in section]
    if isinstance(section, dict):
        return [int(v) for v in section.values()]
    return []


def _one(section) -> int | None:
    """A single-id section is stored as {"id": n} (older runs may have a plain int)."""
    if isinstance(section, dict):
        value = section.get("id")
    elif isinstance(section, int):
        value = section
    else:
        value = None
    return int(value) if value is not None else None


class Rollback:
    def __init__(self, manifest: dict) -> None:
        ids = manifest.get("ids") or {}
        self.product_ids = _ids_of(ids.get("products"))
        self.supplier_id = _one(ids.get("supplier"))
        self.distributor_ids = _ids_of(ids.get("distributors"))
        self.employee_ids = _ids_of(ids.get("employees"))
        self.lead_ids = _ids_of(ids.get("leads"))
        self.po_ids = _ids_of(ids.get("purchase_orders"))
        if not self.po_ids:
            legacy = _one(ids.get("purchase_order"))
            self.po_ids = [legacy] if legacy is not None else []
        self.grn_ids = _ids_of(ids.get("goods_receipts"))
        self.batch_ids = _ids_of(ids.get("batches"))
        self.so_ids = _ids_of(ids.get("sales_orders"))
        self.approval_ids = _ids_of(ids.get("approvals"))
        self.invoice_id = _one(ids.get("invoice"))
        self.payment_ids = _ids_of(ids.get("payments"))
        self.credit_note_id = _one(ids.get("credit_note"))

    # -------------------------------------------------------------- guards
    def blockers(self, db) -> list[str]:
        """Records made after seeding that depend on demo masters: do not delete."""
        out: list[str] = []
        payment_filter = []
        if self.invoice_id:
            payment_filter.append(Payment.invoice_id == self.invoice_id)
        if self.distributor_ids:
            payment_filter.append(Payment.distributor_id.in_(self.distributor_ids))
        if self.supplier_id:
            payment_filter.append(Payment.supplier_id == self.supplier_id)
        if payment_filter:
            extra = db.scalar(select(func.count()).select_from(Payment).where(
                or_(*payment_filter),
                Payment.id.notin_(self.payment_ids) if self.payment_ids else True))
            if extra:
                out.append(f"{extra} payment(s) reference a demo party but are not demo payments")
        if self.invoice_id:
            extra = db.scalar(select(func.count()).select_from(CreditNote).where(
                CreditNote.invoice_id == self.invoice_id,
                CreditNote.id != (self.credit_note_id or -1)))
            if extra:
                out.append(f"{extra} credit note(s) reference the demo invoice")
            extra = db.scalar(select(func.count()).select_from(DebitNote).where(
                DebitNote.invoice_id == self.invoice_id))
            if extra:
                out.append(f"{extra} debit note(s) reference the demo invoice")
        if self.so_ids:
            extra = db.scalar(select(func.count()).select_from(Invoice).where(
                Invoice.sales_order_id.in_(self.so_ids),
                Invoice.id != (self.invoice_id or -1)))
            if extra:
                out.append(f"{extra} invoice(s) reference a demo sales order")
        if self.distributor_ids:
            extra = db.scalar(select(func.count()).select_from(SalesOrder).where(
                SalesOrder.distributor_id.in_(self.distributor_ids),
                SalesOrder.id.notin_(self.so_ids) if self.so_ids else True))
            if extra:
                out.append(f"{extra} sales order(s) reference a demo distributor")
        if self.supplier_id and self.po_ids:
            extra = db.scalar(select(func.count()).select_from(PurchaseOrder).where(
                PurchaseOrder.supplier_id == self.supplier_id,
                PurchaseOrder.id.notin_(self.po_ids)))
            if extra:
                out.append(f"{extra} purchase order(s) reference the demo supplier")
        if self.po_ids and self.grn_ids:
            extra = db.scalar(select(func.count()).select_from(GoodsReceipt).where(
                GoodsReceipt.po_id.in_(self.po_ids), GoodsReceipt.id.notin_(self.grn_ids)))
            if extra:
                out.append(f"{extra} goods receipt(s) reference a demo purchase order")
        if self.batch_ids and self.grn_ids:
            extra = db.scalar(select(func.count()).select_from(GoodsReceiptLine).where(
                GoodsReceiptLine.batch_id.in_(self.batch_ids),
                GoodsReceiptLine.grn_id.notin_(self.grn_ids)))
            if extra:
                out.append(f"{extra} goods receipt line(s) use a demo batch")
        if self.batch_ids:
            allowed = []
            if self.grn_ids:
                allowed.append((StockMovement.ref_type == "grn")
                               & StockMovement.ref_id.in_([str(i) for i in self.grn_ids]))
            if self.so_ids:
                allowed.append((StockMovement.ref_type == "so")
                               & StockMovement.ref_id.in_([str(i) for i in self.so_ids]))
            if self.credit_note_id:
                allowed.append((StockMovement.ref_type == "credit_note")
                               & (StockMovement.ref_id == str(self.credit_note_id)))
            base = select(func.count()).select_from(StockMovement).where(
                StockMovement.batch_id.in_(self.batch_ids))
            if allowed:
                base = base.where(~or_(*allowed))
            extra = db.scalar(base)
            if extra:
                out.append(f"{extra} stock movement(s) on demo batches belong to other documents")
        if self.employee_ids:
            extra = db.scalar(select(func.count()).select_from(User).where(
                User.employee_id.in_(self.employee_ids)))
            if extra:
                out.append(f"{extra} login(s) are linked to a demo employee")
        return out

    # -------------------------------------------------------------- deletes
    def execute(self, db) -> list[tuple[str, int]]:
        done: list[tuple[str, int]] = []

        def run(label: str, stmt) -> None:
            result = db.execute(stmt)
            if result.rowcount:
                done.append((label, result.rowcount))

        if self.batch_ids:
            run("stock movements on demo batches", delete(StockMovement).where(
                StockMovement.batch_id.in_(self.batch_ids)))
        if self.lead_ids:
            run("lead activity", delete(LeadActivity).where(LeadActivity.lead_id.in_(self.lead_ids)))
        if self.payment_ids:
            run("demo payments", delete(Payment).where(Payment.id.in_(self.payment_ids)))
        if self.credit_note_id:
            run("credit note lines", delete(CreditNoteLine).where(
                CreditNoteLine.credit_note_id == self.credit_note_id))
            run("demo credit note", delete(CreditNote).where(
                CreditNote.id == self.credit_note_id))
        if self.invoice_id:
            run("invoice lines", delete(InvoiceLine).where(InvoiceLine.invoice_id == self.invoice_id))
            run("demo invoice", delete(Invoice).where(Invoice.id == self.invoice_id))
        approval_filter = []
        if self.approval_ids:
            approval_filter.append(ApprovalRequest.id.in_(self.approval_ids))
        if self.so_ids:
            approval_filter.append((ApprovalRequest.record_type == "sales_order")
                                   & ApprovalRequest.record_id.in_(self.so_ids))
        if approval_filter:
            run("demo approval requests", delete(ApprovalRequest).where(or_(*approval_filter)))
        if self.so_ids:
            run("sales order lines", delete(SalesOrderLine).where(
                SalesOrderLine.order_id.in_(self.so_ids)))
            run("demo sales orders", delete(SalesOrder).where(SalesOrder.id.in_(self.so_ids)))
        if self.grn_ids:
            run("goods receipt lines", delete(GoodsReceiptLine).where(
                GoodsReceiptLine.grn_id.in_(self.grn_ids)))
            run("demo goods receipts", delete(GoodsReceipt).where(GoodsReceipt.id.in_(self.grn_ids)))
        if self.po_ids:
            run("purchase order lines", delete(PurchaseOrderLine).where(
                PurchaseOrderLine.po_id.in_(self.po_ids)))
            run("demo purchase orders", delete(PurchaseOrder).where(
                PurchaseOrder.id.in_(self.po_ids)))
        if self.batch_ids:
            run("demo batches", delete(Batch).where(Batch.id.in_(self.batch_ids)))
        if self.employee_ids:
            run("demo employees", delete(Employee).where(Employee.id.in_(self.employee_ids)))
        if self.lead_ids:
            run("demo leads", delete(Lead).where(Lead.id.in_(self.lead_ids)))
        if self.distributor_ids:
            run("demo distributors", delete(Distributor).where(Distributor.id.in_(self.distributor_ids)))
        if self.supplier_id:
            run("demo supplier", delete(Supplier).where(Supplier.id == self.supplier_id))
        if self.product_ids:
            run("demo products", delete(Product).where(Product.id.in_(self.product_ids)))
        return done

    # -------------------------------------------------------------- checks
    def marker_problems(self, db) -> list[str]:
        problems = []
        if self.product_ids:
            bad = db.scalar(select(func.count()).select_from(Product).where(
                Product.id.in_(self.product_ids), ~Product.sku.startswith("DEMO-")))
            if bad:
                problems.append(f"{bad} product id(s) no longer carry a DEMO- SKU")
        if self.distributor_ids:
            bad = db.scalar(select(func.count()).select_from(Distributor).where(
                Distributor.id.in_(self.distributor_ids), ~Distributor.code.startswith("DEMO-")))
            if bad:
                problems.append(f"{bad} distributor id(s) no longer carry a DEMO- code")
        if self.employee_ids:
            bad = db.scalar(select(func.count()).select_from(Employee).where(
                Employee.id.in_(self.employee_ids), ~Employee.code.startswith("DEMO-")))
            if bad:
                problems.append(f"{bad} employee id(s) no longer carry a DEMO- code")
        if self.batch_ids:
            bad = db.scalar(select(func.count()).select_from(Batch).where(
                Batch.id.in_(self.batch_ids), ~Batch.batch_no.startswith("DEMO-")))
            if bad:
                problems.append(f"{bad} batch id(s) no longer carry a DEMO- number")
        if self.supplier_id:
            bad = db.scalar(select(func.count()).select_from(Supplier).where(
                Supplier.id == self.supplier_id, ~Supplier.code.startswith("DEMO-")))
            if bad:
                problems.append("the supplier id no longer carries a DEMO- code")
        return problems


def summarize(db, rb: Rollback) -> list[tuple[str, int]]:
    counts = [
        ("stock movements on demo batches", select(func.count()).select_from(StockMovement).where(
            StockMovement.batch_id.in_(rb.batch_ids)) if rb.batch_ids else None),
        ("demo payments", select(func.count()).select_from(Payment).where(
            Payment.id.in_(rb.payment_ids)) if rb.payment_ids else None),
        ("demo credit notes", select(func.count()).select_from(CreditNote).where(
            CreditNote.id == rb.credit_note_id) if rb.credit_note_id else None),
        ("demo invoices", select(func.count()).select_from(Invoice).where(
            Invoice.id == rb.invoice_id) if rb.invoice_id else None),
        ("demo sales orders", select(func.count()).select_from(SalesOrder).where(
            SalesOrder.id.in_(rb.so_ids)) if rb.so_ids else None),
        ("demo goods receipts", select(func.count()).select_from(GoodsReceipt).where(
            GoodsReceipt.id.in_(rb.grn_ids)) if rb.grn_ids else None),
        ("demo purchase orders", select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.id.in_(rb.po_ids)) if rb.po_ids else None),
        ("demo batches", select(func.count()).select_from(Batch).where(
            Batch.id.in_(rb.batch_ids)) if rb.batch_ids else None),
        ("demo employees", select(func.count()).select_from(Employee).where(
            Employee.id.in_(rb.employee_ids)) if rb.employee_ids else None),
        ("demo leads", select(func.count()).select_from(Lead).where(
            Lead.id.in_(rb.lead_ids)) if rb.lead_ids else None),
        ("demo distributors", select(func.count()).select_from(Distributor).where(
            Distributor.id.in_(rb.distributor_ids)) if rb.distributor_ids else None),
        ("demo suppliers", select(func.count()).select_from(Supplier).where(
            Supplier.id == rb.supplier_id) if rb.supplier_id else None),
        ("demo products", select(func.count()).select_from(Product).where(
            Product.id.in_(rb.product_ids)) if rb.product_ids else None),
    ]
    return [(label, db.scalar(stmt)) for label, stmt in counts if stmt is not None]


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove the records created by seed_demo.py")
    parser.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                        help=f"manifest path (default: {DEFAULT_MANIFEST.name})")
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"STOPPED: {args.manifest} not found; nothing to roll back.", file=sys.stderr)
        return 1
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rb = Rollback(manifest)

    with SessionLocal() as db:
        blockers = rb.blockers(db) + rb.marker_problems(db)
        if blockers:
            print("STOPPED - rollback would not be clean:", file=sys.stderr)
            for problem in blockers:
                print(f"  - {problem}", file=sys.stderr)
            print("Nothing was deleted.", file=sys.stderr)
            return 2

        rows = summarize(db, rb)
        print("Demo rows recorded in the manifest:")
        for label, count in rows:
            print(f"  {label:<34} {count}")
        total = sum(count for _, count in rows)
        if not args.yes:
            print(f"\nDry run: {total} row(s) would be deleted. Re-run with --yes to delete.")
            return 0

        done = rb.execute(db)
        db.commit()
    print("\nDeleted:")
    for label, count in done:
        print(f"  {label:<34} {count}")
    args.manifest.unlink()
    print(f"\nManifest removed. Audit history and document counters were left untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
