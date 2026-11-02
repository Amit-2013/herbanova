#!/usr/bin/env python
"""Seed clearly-marked demo data into the current database.

Why: verify every screen and report against a database that is populated with
real flows (purchase receipt -> stock batches -> sales order -> dispatch ->
invoice -> receipt -> credit note), not hand-written rows.

Safety:
- Every master record carries a DEMO marker in its natural key (SKU, code or
  email address), so it is identifiable without the manifest.
- Nothing that already exists is modified or deleted. Every step first looks
  for the demo record and reuses it, so the script is safe to re-run.
- The ids of every created row are written to ``demo_seed_manifest.json``.
  ``seed_demo_rollback.py`` removes exactly those rows.
- The script refuses to run against a database without the core tables or
  without the ``admin`` / ``sales`` accounts created by ``seed.py``.
- No password, token or credential is printed. Tokens are minted in-process
  and held only in the HTTP client's cookie jar.

Usage:
    python seed_demo.py --dry-run      # report what exists / would be created
    python seed_demo.py                # create the demo records
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, or_, select

from app.core.db import SessionLocal, engine
from app.core.security import make_token
from app.models.core import (Batch, Distributor, Invoice, Lead, Product,
                             PurchaseOrder, SalesOrder, User, Warehouse)
from app.models.suppliers import GoodsReceipt, Supplier
from app.models.tax import TaxRate
from app.models.users import Employee
from app.services.tax_ids import make_gstin, make_pan

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "demo_seed_manifest.json"

AS_OF = date.today()

PRODUCTS = [
    # (sku, name, pack_size, mrp)
    ("DEMO-ASH-01", "Ashwagandha Capsules (demo)", "60 capsules", "450.00"),
    ("DEMO-TUL-01", "Tulsi Drops (demo)", "30 ml", "220.00"),
]
SUPPLIER = ("DEMO-SUP-01", "Demo Botanicals Supplier")
DISTRIBUTORS = [
    # (code, name, territory, state_code, pan_letters, pan_digits, credit_limit)
    ("DEMO-DIST-01", "Demo Delhi Distributor", "North", "07", "DEMBA", "0001", "100000.00"),
    ("DEMO-DIST-02", "Demo Mumbai Distributor", "West", "27", "DEMCA", "0002", "2000.00"),
]
EMPLOYEES = [
    # (code, full_name, department, designation)
    ("DEMO-EMP-01", "Riya Demo", "Sales", "Sales executive"),
    ("DEMO-EMP-02", "Arjun Demo", "Warehouse", "Warehouse supervisor"),
]
LEADS = [
    # (name, company, source, days_ahead, email)
    ("Demo Prospect A", "Demo Wellness Store", "website", 0, "demo.lead1@example.invalid"),
    ("Demo Prospect B", "Demo Pharmacy Chain", "referral", 5, "demo.lead2@example.invalid"),
    ("Demo Prospect C", "Demo Online Seller", "event", 30, "demo.lead3@example.invalid"),
]
PO_NUMBER = "DEMO-PO-01"
PO_PARTIAL_NUMBER = "DEMO-PO-02"
BATCH_NUMBERS = ["DEMO-ASH-EARLY", "DEMO-ASH-LATE", "DEMO-TUL-MID", "DEMO-TUL-PARTIAL"]


class DemoError(RuntimeError):
    pass


# ---------------------------------------------------------------- manifest
def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"created_at": None, "purpose": "Marked demo data - remove with seed_demo_rollback.py",
            "markers": {}, "ids": {}}


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["created_at"] = manifest["created_at"] or datetime.now().isoformat(timespec="seconds")
    manifest["markers"] = {
        "product_skus": [p[0] for p in PRODUCTS],
        "supplier_codes": [SUPPLIER[0]],
        "distributor_codes": [d[0] for d in DISTRIBUTORS],
        "employee_codes": [e[0] for e in EMPLOYEES],
        "lead_emails": [l[4] for l in LEADS],
        "purchase_order": PO_NUMBER,
        "batch_prefix": "DEMO-",
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def remember(manifest: dict, path: Path, section: str, key, value) -> None:
    manifest["ids"].setdefault(section, {})[key] = value
    save_manifest(path, manifest)


# ---------------------------------------------------------------- read helpers
def find_id(model, **where):
    with SessionLocal() as db:
        row = db.scalar(select(model).filter_by(**where))
        return row.id if row else None


def active_hsn() -> str:
    today = date.today()
    with SessionLocal() as db:
        row = db.scalars(
            select(TaxRate).where(TaxRate.effective_from <= today)
            .where(or_(TaxRate.effective_to.is_(None), TaxRate.effective_to >= today))
            .order_by(TaxRate.hsn)).first()
    if row is None:
        raise DemoError("no GST rate is in force; add one in Tax and discounts before seeding")
    return row.hsn


def main_warehouse() -> int:
    with SessionLocal() as db:
        row = (db.scalar(select(Warehouse).where(Warehouse.name == "Main Warehouse"))
               or db.scalars(select(Warehouse).order_by(Warehouse.id)).first())
    if row is None:
        raise DemoError("no warehouse exists; create one before seeding")
    return row.id


def existing_markers() -> list[str]:
    out = []
    with SessionLocal() as db:
        for sku, *_ in PRODUCTS:
            if db.scalar(select(Product).where(Product.sku == sku)):
                out.append(f"product {sku}")
        if db.scalar(select(Supplier).where(Supplier.code == SUPPLIER[0])):
            out.append(f"supplier {SUPPLIER[0]}")
        for code, *_ in DISTRIBUTORS:
            if db.scalar(select(Distributor).where(Distributor.code == code)):
                out.append(f"distributor {code}")
        for code, *_ in EMPLOYEES:
            if db.scalar(select(Employee).where(Employee.code == code)):
                out.append(f"employee {code}")
        for _, _, _, _, email in LEADS:
            if db.scalar(select(Lead).where(Lead.email == email)):
                out.append(f"lead {email}")
        if db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == PO_NUMBER)):
            out.append(f"purchase order {PO_NUMBER}")
        if db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == PO_PARTIAL_NUMBER)):
            out.append(f"purchase order {PO_PARTIAL_NUMBER}")
    return out


# ---------------------------------------------------------------- API client
class Api:
    """TestClient with a minted session per actor. Tokens are never printed."""

    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        self._client = TestClient(app)
        self._tokens: dict[str, str] = {}

    def _token(self, actor: str) -> str:
        if actor not in self._tokens:
            with SessionLocal() as db:
                user = db.scalar(select(User).where(User.username == actor))
                if user is None:
                    raise DemoError(f"account {actor!r} is missing - run: python seed.py")
                if user.must_change_password:
                    raise DemoError(f"account {actor!r} must change its password before seeding")
                self._tokens[actor] = make_token(user.id, user.token_version or 1, minutes=240)
        return self._tokens[actor]

    def call(self, actor: str, method: str, url: str, body=None, expect=(200, 201)):
        self._client.cookies.set("session", self._token(actor))
        response = self._client.request(method, url, json=body)
        if response.status_code not in expect:
            raise DemoError(f"{method} {url} -> {response.status_code}: {response.text[:500]}")
        return response.json() if response.content else None


# ---------------------------------------------------------------- master records
def ensure_product(api, manifest, path, sku, name, pack_size, mrp, hsn) -> int:
    existing = find_id(Product, sku=sku)
    if existing:
        manifest["ids"].setdefault("products", {})[sku] = existing
        save_manifest(path, manifest)
        return existing
    row = api.call("admin", "POST", "/api/products", {
        "sku": sku, "name": name, "pack_size": pack_size, "mrp": mrp, "hsn": hsn, "uqc": "NOS"})
    remember(manifest, path, "products", sku, row["id"])
    print(f"  product       {sku:<14} id={row['id']}")
    return row["id"]


def ensure_supplier(api, manifest, path) -> int:
    code, name = SUPPLIER
    existing = find_id(Supplier, code=code)
    if existing:
        manifest["ids"]["supplier"] = {"id": existing}
        save_manifest(path, manifest)
        return existing
    pan = make_pan("DEMAA", "0003")
    row = api.call("admin", "POST", "/api/suppliers", {
        "code": code, "name": name, "kind": "supplier", "registration_type": "regular",
        "gstin": make_gstin("07", pan), "pan": pan, "state_code": "07", "payment_terms_days": 30})
    remember(manifest, path, "supplier", "id", row["id"])
    print(f"  supplier      {code:<14} id={row['id']}")
    return row["id"]


def ensure_distributor(api, manifest, path, code, name, territory, state_code,
                       pan_letters, pan_digits, credit_limit) -> int:
    existing = find_id(Distributor, code=code)
    if existing:
        manifest["ids"].setdefault("distributors", {})[code] = existing
        save_manifest(path, manifest)
        return existing
    row = api.call("admin", "POST", "/api/distributors", {
        "code": code, "name": name, "territory": territory, "credit_limit": credit_limit,
        "registration_type": "regular", "gstin": make_gstin(state_code, make_pan(pan_letters, pan_digits)),
        "state_code": state_code, "contact_person": "Demo contact", "phone": "9810000000",
        "email": f"{code.lower()}@example.invalid", "payment_terms_days": 30, "status": "active"})
    remember(manifest, path, "distributors", code, row["id"])
    print(f"  distributor   {code:<14} id={row['id']}")
    return row["id"]


def ensure_employee(api, manifest, path, code, full_name, department, designation) -> int:
    existing = find_id(Employee, code=code)
    if existing:
        manifest["ids"].setdefault("employees", {})[code] = existing
        save_manifest(path, manifest)
        return existing
    row = api.call("admin", "POST", "/api/hr/employees", {
        "code": code, "full_name": full_name, "department": department,
        "designation": designation, "email": f"{code.lower().replace('-', '.')}@example.invalid",
        "joining_date": (AS_OF - timedelta(days=90)).isoformat(),
        "employment_type": "Full time"})
    remember(manifest, path, "employees", code, row["id"])
    print(f"  employee      {code:<14} id={row['id']}")
    return row["id"]


def ensure_lead(api, manifest, path, name, company, source, days_ahead, email) -> int:
    existing = find_id(Lead, email=email)
    if existing:
        manifest["ids"].setdefault("leads", {})[email] = existing
        save_manifest(path, manifest)
        return existing
    row = api.call("sales", "POST", "/api/leads", {
        "name": name, "company": company, "source": source, "email": email,
        "next_follow_up": (AS_OF + timedelta(days=days_ahead)).isoformat(),
        "note": f"Demo lead for feature verification ({source})."})
    remember(manifest, path, "leads", email, row["id"])
    print(f"  lead          {email:<14} id={row['id']}")
    return row["id"]


# ---------------------------------------------------------------- transactions
def ensure_purchase_order(api, manifest, path, number, supplier_id, warehouse_id,
                          lines, receipt) -> int:
    existing = find_id(PurchaseOrder, po_number=number)
    if existing is None:
        row = api.call("admin", "POST", "/api/purchase-orders",
                       {"supplier_id": supplier_id, "po_number": number, "lines": lines})
        existing = row["id"]
        print(f"  purchase order {number} id={existing}")
    po_ids = manifest["ids"].setdefault("purchase_orders", [])
    if existing not in po_ids:
        po_ids.append(existing)
        save_manifest(path, manifest)

    with SessionLocal() as db:
        status = db.get(PurchaseOrder, existing).status
        already_received = db.scalar(
            select(GoodsReceipt).where(GoodsReceipt.po_id == existing,
                                       GoodsReceipt.delivery_note == receipt.get("delivery_note")))
    if status in ("open", "partially_received") and already_received is None:
        received = api.call("admin", "POST", f"/api/purchase-orders/{existing}/receive",
                            {"warehouse_id": warehouse_id, "owner": "HERBANOVA", **receipt})
        print(f"  goods receipt {received['grn_number']} against {number} "
              f"({received['status']})")

    with SessionLocal() as db:
        grns = [r.id for r in db.scalars(
            select(GoodsReceipt).where(GoodsReceipt.po_id == existing)).all()]
        batches = [b.id for b in db.scalars(
            select(Batch).where(Batch.batch_no.in_(BATCH_NUMBERS))).all()]
    manifest["ids"]["goods_receipts"] = sorted(set(manifest["ids"].get("goods_receipts", []) + grns))
    manifest["ids"]["batches"] = sorted(set(manifest["ids"].get("batches", []) + batches))
    save_manifest(path, manifest)
    return existing


def ensure_sales_order(api, manifest, path, key, distributor_id, lines, leave_pending=False) -> dict:
    so_ids = manifest["ids"].setdefault("sales_orders", {})
    so_id = so_ids.get(key)
    if so_id is None:
        row = api.call("sales", "POST", "/api/sales-orders",
                       {"distributor_id": distributor_id, "lines": lines})
        so_id = row["id"]
        remember(manifest, path, "sales_orders", key, so_id)
        print(f"  sales order   {row['so_number']} (draft) id={so_id}")

    order = api.call("admin", "GET", f"/api/sales-orders/{so_id}")
    if order["status"] == "draft":
        order = api.call("sales", "POST", f"/api/sales-orders/{so_id}/submit")
        print(f"  sales order   {order['so_number']} submitted -> {order['status']}")
    if order["status"] == "pending_approval":
        if leave_pending:
            approval = order.get("approval") or {}
            if approval.get("id"):
                ids = manifest["ids"].setdefault("approvals", [])
                if approval["id"] not in ids:
                    ids.append(approval["id"])
                    save_manifest(path, manifest)
            print(f"  sales order   {order['so_number']} left pending approval (demo queue)")
            return order
        approval_id = (order.get("approval") or {}).get("id")
        if approval_id is None:
            raise DemoError(f"{order['so_number']} needs approval but has no request")
        api.call("admin", "POST", f"/api/approvals/{approval_id}/decide",
                 {"decision": "approve", "reason": "Demo approval for verification"})
        ids = manifest["ids"].setdefault("approvals", [])
        if approval_id not in ids:
            ids.append(approval_id)
            save_manifest(path, manifest)
        order = api.call("admin", "GET", f"/api/sales-orders/{so_id}")
        print(f"  sales order   {order['so_number']} approved")

    if order["status"] == "approved":
        api.call("admin", "POST", f"/api/sales-orders/{so_id}/dispatch",
                 {"warehouse_id": main_warehouse()})
        order = api.call("admin", "GET", f"/api/sales-orders/{so_id}")
        print(f"  sales order   {order['so_number']} dispatched -> {order['status']}")
    return order


def find_invoice(api, distributor_id, sales_order_id) -> dict | None:
    invoices = api.call("admin", "GET", f"/api/invoices?distributor_id={distributor_id}")
    return next((i for i in invoices if i["sales_order_id"] == sales_order_id), None)


def ensure_invoice_receipts(api, manifest, path, invoice, distributor_id) -> None:
    first_time = (manifest["ids"].get("invoice") or {}).get("id") != invoice["id"]
    remember(manifest, path, "invoice", "id", invoice["id"])
    if first_time:
        print(f"  invoice       {invoice['invoice_number']} id={invoice['id']}")

    payments = manifest["ids"].setdefault("payments", [])
    if not payments:
        row = api.call("admin", "POST", "/api/accounts/payments", {
            "kind": "receipt", "distributor_id": distributor_id, "invoice_id": invoice["id"],
            "amount": "5000.00", "paid_on": AS_OF.isoformat(), "mode": "bank",
            "reference": "DEMO-RCPT-01", "notes": "Demo partial receipt for verification"})
        payments.append(row["id"])
        save_manifest(path, manifest)
        print(f"  receipt       {row['number']} id={row['id']}")

    if "credit_note" not in manifest["ids"]:
        line = next((ln for ln in invoice["lines"] if ln["sku"] == "DEMO-TUL-01"), None)
        if line is None:
            raise DemoError("demo invoice has no Tulsi line to credit")
        row = api.call("admin", "POST", "/api/credit-notes", {
            "invoice_id": invoice["id"], "reason": "Demo: 2 packs returned damaged",
            "lines": [{"invoice_line_id": line["invoice_line_id"], "qty": "2"}],
            "note_date": AS_OF.isoformat(), "warehouse_id": main_warehouse()})
        remember(manifest, path, "credit_note", "id", row["id"])
        print(f"  credit note   {row['credit_note_number']} id={row['id']}")


def ensure_supplier_payment(api, manifest, path, purchase_order_id) -> None:
    payments = manifest["ids"].setdefault("payments", [])
    if len(payments) >= 2:
        return
    row = api.call("admin", "POST", "/api/accounts/payments", {
        "kind": "payment", "purchase_order_id": purchase_order_id,
        "amount": "3000.00", "paid_on": AS_OF.isoformat(), "mode": "bank",
        "reference": "DEMO-PAY-01", "notes": "Demo payment to supplier against PO"})
    payments.append(row["id"])
    save_manifest(path, manifest)
    print(f"  payment       {row['number']} id={row['id']}")


# ---------------------------------------------------------------- main
def dry_run(manifest_path: Path) -> int:
    print("Dry run - nothing is written.\n")
    print("Markers already present:")
    found = existing_markers()
    print("  " + ("\n  ".join(found) if found else "(none)"))
    print("\nWould ensure:")
    for sku, *_ in PRODUCTS:
        print(f"  product       {sku}")
    print(f"  supplier      {SUPPLIER[0]}")
    for code, *_ in DISTRIBUTORS:
        print(f"  distributor   {code}")
    for code, *_ in EMPLOYEES:
        print(f"  employee      {code}")
    for _, _, _, _, email in LEADS:
        print(f"  lead          {email}")
    print(f"  purchase order {PO_NUMBER} + one full goods receipt (3 batches)")
    print(f"  purchase order {PO_PARTIAL_NUMBER} + one part receipt (open on the dashboard)")
    print("  2 sales orders (one dispatched to an invoice, one pending approval)")
    print("  1 receipt, 1 supplier payment, 1 credit note")
    print(f"\nManifest: {manifest_path}")
    return 0


def seed(manifest_path: Path) -> int:
    if not inspect(engine).has_table("users"):
        raise DemoError("'users' table missing - run: alembic upgrade head first")

    manifest_existed = manifest_path.exists()
    manifest = load_manifest(manifest_path)
    if not manifest_existed and existing_markers():
        raise DemoError(
            "demo master records already exist but demo_seed_manifest.json is missing; "
            "restore the manifest or remove the DEMO- records before re-seeding")

    hsn = active_hsn()
    warehouse_id = main_warehouse()
    api = Api()
    print("Creating demo data (existing DEMO records are reused):\n")

    product_ids = {sku: ensure_product(api, manifest, manifest_path, sku, name, pack, mrp, hsn)
                   for sku, name, pack, mrp in PRODUCTS}
    supplier_id = ensure_supplier(api, manifest, manifest_path)
    distributor_ids = {}
    for code, name, territory, state_code, letters, digits, limit in DISTRIBUTORS:
        distributor_ids[code] = ensure_distributor(api, manifest, manifest_path, code, name,
                                                   territory, state_code, letters, digits, limit)
    for code, full_name, department, designation in EMPLOYEES:
        ensure_employee(api, manifest, manifest_path, code, full_name, department, designation)
    for name, company, source, days_ahead, email in LEADS:
        ensure_lead(api, manifest, manifest_path, name, company, source, days_ahead, email)

    ids = manifest["ids"]
    legacy = ids.pop("purchase_order", None)
    if isinstance(legacy, dict):
        legacy = legacy.get("id")
    if legacy is not None and legacy not in ids.setdefault("purchase_orders", []):
        ids["purchase_orders"].append(legacy)

    po_id = ensure_purchase_order(
        api, manifest, manifest_path, PO_NUMBER, supplier_id, warehouse_id,
        [{"sku": "DEMO-ASH-01", "qty": "500", "unit_cost": "120.00"},
         {"sku": "DEMO-TUL-01", "qty": "400", "unit_cost": "60.00"}],
        {"delivery_note": "DEMO-DN-01", "note": "Demo goods receipt",
         "lines": [
             {"sku": "DEMO-ASH-01", "batch_no": "DEMO-ASH-EARLY", "qty": "200",
              "expiry": (AS_OF + timedelta(days=12)).isoformat()},
             {"sku": "DEMO-ASH-01", "batch_no": "DEMO-ASH-LATE", "qty": "300",
              "expiry": (AS_OF + timedelta(days=730)).isoformat()},
             {"sku": "DEMO-TUL-01", "batch_no": "DEMO-TUL-MID", "qty": "400",
              "expiry": (AS_OF + timedelta(days=60)).isoformat()}]})
    ensure_purchase_order(
        api, manifest, manifest_path, PO_PARTIAL_NUMBER, supplier_id, warehouse_id,
        [{"sku": "DEMO-TUL-01", "qty": "200", "unit_cost": "60.00"}],
        {"delivery_note": "DEMO-DN-02", "note": "Demo part delivery (80 still to come)",
         "lines": [{"sku": "DEMO-TUL-01", "batch_no": "DEMO-TUL-PARTIAL", "qty": "120",
                    "expiry": (AS_OF + timedelta(days=400)).isoformat()}]})

    dispatched = ensure_sales_order(
        api, manifest, manifest_path, "dispatched", distributor_ids["DEMO-DIST-01"],
        [{"sku": "DEMO-ASH-01", "qty": "20", "unit_price": "420.00"},
         {"sku": "DEMO-TUL-01", "qty": "10", "unit_price": "210.00"}])
    invoice = find_invoice(api, distributor_ids["DEMO-DIST-01"], dispatched["id"])
    if invoice is None:
        raise DemoError("dispatch did not produce an invoice for the demo order")
    ensure_invoice_receipts(api, manifest, manifest_path, invoice,
                            distributor_ids["DEMO-DIST-01"])
    ensure_supplier_payment(api, manifest, manifest_path, po_id)

    ensure_sales_order(
        api, manifest, manifest_path, "pending", distributor_ids["DEMO-DIST-02"],
        [{"sku": "DEMO-ASH-01", "qty": "10", "unit_price": "420.00"}], leave_pending=True)

    save_manifest(manifest_path, manifest)
    print(f"\nDemo manifest written to {manifest_path.name}.")
    print("Remove these rows later with: python seed_demo_rollback.py --yes")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed marked demo data into the current database")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                        help=f"manifest path (default: {DEFAULT_MANIFEST.name})")
    args = parser.parse_args()
    try:
        return dry_run(args.manifest) if args.dry_run else seed(args.manifest)
    except DemoError as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
