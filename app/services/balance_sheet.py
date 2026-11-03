"""Opening position, the balance sheet and a single head's balance (GAP-A10).

Three layers meet here, once each:

1. the opening balances captured for a financial year, which documents starting
   after the books began cannot prove;
2. the posted voucher ledger in `app/services/journal.py`, which no document
   produces; and
3. the document-derived trial balance in `app/services/ledger.py`, mapped from
   its buckets to the seeded heads by `role`.

The opening year is the latest captured year at or before the date asked for.
Movements are summed from that year's first day, so a carried-forward opening
is never added to the same year's documents twice. An opening trial balance
that does not balance is reported as a difference, not plugged.

What the sheet does not claim is named in `warnings`: the document layer covers
sales, receipts, payments and goods received only, so earnings are partial; a
receipt or payment moves through Cash or Bank by its mode; and a document is
never posted as a voucher by itself.
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.accounts import LedgerAccount, OpeningBalance
from ..models.core import PurchaseOrderLine
from ..models.suppliers import GoodsReceipt, GoodsReceiptLine
from . import journal, ledger, periods

ZERO = Decimal("0.00")
money = journal.money

SECTIONS = ("asset", "liability", "equity", "income", "expense")

# The bucket names `ledger.trial_balance` already produces, and the head role
# each one belongs to. Output GST is one head fed by three tax buckets.
DERIVED_ROLES = {
    "Cash": "cash",
    "Bank": "bank",
    "Receivables": "receivables",
    "Payables": "payables",
    "Output CGST": "output_gst",
    "Output SGST": "output_gst",
    "Output IGST": "output_gst",
    "Sales": "sales",
    "Purchases": "purchases",
    "Round off": "round_off",
    "Advances from distributors": "distributor_advance",
    "Advances to suppliers": "supplier_advance",
}
ROLE_LABEL = {
    "cash": "Cash", "bank": "Bank", "receivables": "Receivables",
    "payables": "Payables", "output_gst": "Output GST", "capital": "Capital",
    "sales": "Sales", "purchases": "Purchases", "round_off": "Round off",
    "distributor_advance": "Advances from distributors",
    "supplier_advance": "Advances to suppliers",
}
ROLE_TYPE = {
    "cash": "asset", "bank": "asset", "receivables": "asset",
    "payables": "liability", "output_gst": "liability", "capital": "equity",
    "sales": "income", "purchases": "expense", "round_off": "expense",
    "distributor_advance": "liability", "supplier_advance": "asset",
}


# ------------------------------------------------------------------ sources
def _tb_net(db: Session, as_of: date) -> dict[str, Decimal]:
    """Net debit-positive balance per bucket, as the documents state it."""
    return {row["account"]: money(Decimal(row["debit"]) - Decimal(row["credit"]))
            for row in ledger.trial_balance(db, as_of)["rows"]}


def _received_between(db: Session, start: date | None, as_of: date) -> Decimal:
    """Goods-received cost inside the window, valued like the trial balance."""
    stmt = (select(GoodsReceipt.po_id, GoodsReceiptLine.product_id,
                   func.coalesce(func.sum(GoodsReceiptLine.qty), 0))
            .join(GoodsReceiptLine, GoodsReceiptLine.grn_id == GoodsReceipt.id)
            .where(func.date(GoodsReceipt.received_at) <= as_of)
            .group_by(GoodsReceipt.po_id, GoodsReceiptLine.product_id))
    if start is not None:
        stmt = stmt.where(func.date(GoodsReceipt.received_at) >= start)
    costs = {(line.po_id, line.product_id): money(line.unit_cost)
             for line in db.scalars(select(PurchaseOrderLine)).all()}
    total = ZERO
    for po_id, product_id, qty in db.execute(stmt).all():
        unit = costs.get((po_id, product_id))
        if unit is None:
            continue
        total += money(qty * unit)
    return money(total)


def _document_movements(db: Session, start: date | None, as_of: date) -> dict[str, Decimal]:
    """Buckets moved inside the window, from the document-derived trial balance.

    `ledger.trial_balance` values goods received without a date, so subtracting
    two dates cancels Purchases and the credit it posts to Payables. Both are
    recomputed from dated receipts and the difference is applied, leaving the
    date-filtered sales, tax and money movements untouched.
    """
    now = _tb_net(db, as_of)
    if start is None:
        moved = dict(now)
        included = money(sum(ledger.received_value_by_po(db).values(), ZERO))
    else:
        before = _tb_net(db, start - timedelta(days=1))
        moved = {name: money(now.get(name, ZERO) - before.get(name, ZERO))
                 for name in set(now) | set(before)}
        included = ZERO
    adjustment = money(_received_between(db, start, as_of) - included)
    moved["Purchases"] = money(moved.get("Purchases", ZERO) + adjustment)
    moved["Payables"] = money(moved.get("Payables", ZERO) - adjustment)
    return moved


def _movement(db: Session, as_of: date) -> dict:
    """Every head's opening, voucher movement, document movement and net."""
    target = periods.fy_label(as_of)
    labels = set(db.scalars(
        select(OpeningBalance.financial_year).distinct()).all())
    carried = sorted(label for label in labels if label <= target)
    opening_fy = carried[-1] if carried else None
    start = periods.label_bounds(opening_fy)[0] if opening_fy else None

    openings: dict[int, Decimal] = {}
    opening_debit = opening_credit = ZERO
    if opening_fy is not None:
        for row in db.scalars(select(OpeningBalance).where(
                OpeningBalance.financial_year == opening_fy)).all():
            openings[row.ledger_account_id] = money(
                money(row.debit) - money(row.credit))
            opening_debit += money(row.debit)
            opening_credit += money(row.credit)

    vouchers = journal.posted_movements(db, as_of, start)
    documents = _document_movements(db, start, as_of)

    role_documents: dict[str, Decimal] = {}
    unknown = []
    for bucket, value in documents.items():
        role = DERIVED_ROLES.get(bucket)
        if role is None:
            if value != ZERO:
                unknown.append(bucket)
            continue
        role_documents[role] = money(role_documents.get(role, ZERO) + value)

    accounts = db.scalars(select(LedgerAccount).order_by(LedgerAccount.code)).all()
    rows: dict[int, dict] = {}
    used_roles: set[str] = set()
    for account in accounts:
        movement = vouchers.get(account.id, {"debit": ZERO, "credit": ZERO})
        voucher_net = money(movement["debit"] - movement["credit"])
        document_net = role_documents.get(account.role, ZERO) if account.role else ZERO
        opening = openings.get(account.id, ZERO)
        rows[account.id] = {"opening": opening, "voucher": voucher_net,
                            "document": document_net,
                            "net": money(opening + voucher_net + document_net)}
        if account.role:
            used_roles.add(account.role)

    return {
        "as_of": as_of, "financial_year": target, "opening_fy": opening_fy,
        "window_start": start,
        "opening_debit": money(opening_debit),
        "opening_credit": money(opening_credit),
        "rows": rows, "accounts": accounts,
        "unmapped": [role for role in role_documents
                     if role not in used_roles and role_documents[role] != ZERO],
        "role_documents": role_documents,
        "unknown_buckets": sorted(unknown),
    }


# ------------------------------------------------------------- presentation
def _present(account_type: str, values: dict) -> dict:
    net = values["net"]
    natural = net if account_type in ("asset", "expense") else money(-net)
    return {"opening": values["opening"], "vouchers": values["voucher"],
            "documents": values["document"], "net": net, "balance": natural,
            "debit_balance": natural if natural > 0 else ZERO,
            "credit_balance": -natural if natural < 0 else ZERO}


def _account_row(account: LedgerAccount, values: dict) -> dict:
    return {"account_id": account.id, "code": account.code, "name": account.name,
            "type": account.type, "role": account.role, "active": account.active,
            "unmapped": False, **_present(account.type, values)}


def _synthetic_row(role: str, net: Decimal) -> dict:
    kind = ROLE_TYPE[role]
    return {"account_id": None, "code": None, "name": ROLE_LABEL[role],
            "type": kind, "role": role, "active": False, "unmapped": True,
            **_present(kind, {"opening": ZERO, "voucher": ZERO,
                              "document": net, "net": net})}


def balance_sheet(db: Session, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    source = _movement(db, as_of)
    sections = {kind: [] for kind in SECTIONS}

    for account in source["accounts"]:
        values = source["rows"][account.id]
        if values["net"] == ZERO and values["opening"] == ZERO:
            continue
        sections[account.type].append(_account_row(account, values))
    for role in source["unmapped"]:
        row = _synthetic_row(role, source["role_documents"][role])
        sections[row["type"]].append(row)

    for kind in SECTIONS:
        sections[kind].sort(key=lambda r: (r["code"] or "~", r["name"]))
    totals = {kind: money(sum((row["balance"] for row in sections[kind]), ZERO))
              for kind in SECTIONS}
    retained = money(totals["income"] - totals["expense"])
    difference = money(totals["asset"]
                       - (totals["liability"] + totals["equity"] + retained))

    cash_rows = [row for account in source["accounts"]
                 if account.role in ("cash", "bank")
                 for row in [_account_row(account, source["rows"][account.id])]]
    cash_bank = {
        "rows": cash_rows,
        "cash": money(sum((r["balance"] for r in cash_rows if r["role"] == "cash"),
                          ZERO)),
        "bank": money(sum((r["balance"] for r in cash_rows if r["role"] == "bank"),
                          ZERO)),
        "total": money(sum((r["balance"] for r in cash_rows), ZERO)),
    }

    opening_difference = money(source["opening_debit"] - source["opening_credit"])
    warnings = []
    if source["opening_fy"] is None:
        warnings.append(
            "No opening balance is captured, so the sheet starts from the first "
            "document rather than from an opening position.")
    elif source["opening_fy"] != source["financial_year"]:
        warnings.append(
            f"Opening balances are captured for {source['opening_fy']}; movements "
            f"from {source['window_start']} are added. No opening balance is "
            f"captured for {source['financial_year']}.")
    if opening_difference != ZERO:
        warnings.append(
            f"The opening trial balance does not balance: debit "
            f"{source['opening_debit']:.2f}, credit {source['opening_credit']:.2f}, "
            f"difference {opening_difference:.2f}.")
    if source["unmapped"]:
        warnings.append(
            "These document buckets have no head with the matching role, so they "
            "are shown as unlinked rows: "
            + ", ".join(ROLE_LABEL.get(role, role) for role in source["unmapped"])
            + ".")
    if source["unknown_buckets"]:
        warnings.append(
            "These document buckets are not mapped to a head and are excluded: "
            + ", ".join(source["unknown_buckets"]) + ".")
    warnings.append(
        "The document layer covers sales, receipts, payments and goods received "
        "only; expenses, payroll and stock cost are not in it, so earnings and "
        "the difference are partial. Post vouchers or enter openings to complete "
        "the position.")
    warnings.append(
        "A receipt or payment moves through Cash or Bank by its mode; with more "
        "than one bank head, document money cannot be split between them.")
    warnings.append(
        "A document is never posted as a voucher by itself; posted vouchers are "
        "a separate ledger merged here by head.")

    return {
        "as_of": as_of, "financial_year": source["financial_year"],
        "opening_fy": source["opening_fy"], "window_start": source["window_start"],
        "opening": {"financial_year": source["opening_fy"],
                    "debit_total": source["opening_debit"],
                    "credit_total": source["opening_credit"],
                    "difference": opening_difference,
                    "balanced": opening_difference == ZERO},
        "sections": sections,
        "totals": {**totals, "retained_earnings": retained,
                   "difference": difference, "balanced": difference == ZERO},
        "cash_bank": cash_bank,
        "warnings": warnings,
    }


def account_balance(db: Session, account_id: int,
                    as_of: date | None = None) -> dict:
    """One head's balance at a date, with the three layers kept apart."""
    as_of = as_of or date.today()
    account = db.get(LedgerAccount, account_id)
    if account is None:
        raise journal.LedgerError("Ledger account not found")
    source = _movement(db, as_of)
    values = source["rows"].get(account.id, {"opening": ZERO, "voucher": ZERO,
                                             "document": ZERO, "net": ZERO})
    return {"as_of": as_of, "financial_year": source["financial_year"],
            "opening_fy": source["opening_fy"],
            "window_start": source["window_start"], **_account_row(account, values)}
