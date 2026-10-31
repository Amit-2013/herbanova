"""What a sales order will look like as a tax document (FR-13).

A sales order is not an invoice: the invoice is issued when the goods are
dispatched. This is the preview the sales desk and the warehouse see BEFORE
that happens — the discount slab the order falls under, and the GST the
invoice will charge, line by line and in total.

Two rules decide every number, and both come from the tax module rather than
being repeated here:

- the rate is whatever the GST rate master had in force on the document date
  (`services.tax.resolve_rate`), and an HSN with no rate in force is reported
  as missing — never assumed;
- the place of supply decides the split, CGST + SGST (UTGST inside a union
  territory) or IGST (`services.tax.line_tax`).

The discount shown is the one the prices already carry (MRP versus the unit
price on the line); the slab shown is the policy that justifies it, taken from
`services.discounts`, the same source the approval check at submit uses. So
the preview cannot drift from the decision that was made.

Nothing here is tax advice: the rates come from the data the business enters
and its adviser validates.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core import Distributor, Product, SalesOrder
from ..models.tax import CompanyProfile
from ..services import discounts
from ..services.tax import ZERO, line_tax, money, place_of_supply, resolve_rate


class CannotQuote(Exception):
    """The order cannot be quoted as a tax document (a missing company profile,
    for instance). The message is meant for the person reading the screen."""


def _discount_pct(mrp: Decimal, price: Decimal) -> Decimal:
    """The discount the price carries, in percent (the same rule the order API uses)."""
    return (Decimal(0) if mrp <= 0
            else ((mrp - price) / mrp * 100).quantize(Decimal("0.1"), ROUND_HALF_UP))


def _slab_brief(slab) -> dict | None:
    if slab is None:
        return None
    return {"id": slab.id, "name": slab.name, "scope": slab.scope,
            "group_name": slab.group_name,
            "discount_percent": slab.discount_percent,
            "approval_above": slab.approval_above,
            "effective_from": slab.effective_from, "effective_to": slab.effective_to,
            "active": bool(slab.is_active)}


def order_preview(db: Session, order: SalesOrder, *, on: date | None = None) -> dict:
    """The discount slab and the calculated GST for one sales order.

    Raises `CannotQuote` when the order cannot be priced as a tax document at
    all; a missing rate for one line is not that — it is reported on the line.
    """
    when = on or date.today()
    company = db.scalars(select(CompanyProfile).order_by(CompanyProfile.id)).first()
    if company is None or not company.state_code:
        raise CannotQuote("Save the company tax profile (with its state) before quoting tax")
    dist = db.get(Distributor, order.distributor_id)
    if dist is None:
        raise CannotQuote("The distributor on this order is missing")
    pids = {ln.product_id for ln in order.lines}
    products = ({p.id: p for p in db.scalars(select(Product).where(Product.id.in_(pids))).all()}
                if pids else {})

    try:
        split = place_of_supply(company.state_code, dist.state_code)
    except ValueError as exc:
        raise CannotQuote(f"The place of supply cannot be worked out: {exc}. "
                          f"Give the distributor its state code in the distributor master.")
    notes: list[str] = []
    missing_rates: list[str] = []

    lines = []
    for ln in sorted(order.lines, key=lambda x: x.product_id):
        p = products.get(ln.product_id)
        hsn = (p.hsn or "").strip() if p else ""
        applied = _discount_pct(p.mrp, ln.unit_price) if p else Decimal(0)
        gross = money(ln.qty * ln.unit_price)
        slab = discounts.best_slab(db, on=when, product_id=ln.product_id,
                                   group_name=dist.group_name, qty=ln.qty,
                                   value=ln.line_total)
        entry = {"sku": p.sku if p else "?", "product_name": p.name if p else "?",
                 "hsn": hsn or None, "uqc": p.uqc if p else None,
                 "qty": ln.qty, "unit_price": money(ln.unit_price),
                 "gross": gross,
                 "mrp": p.mrp if p else ZERO, "discount_percent": applied,
                 "discount_amount": money(gross * applied / 100),
                 "slab": _slab_brief(slab),
                 "slab_discount_percent": slab.discount_percent if slab else ZERO,
                 "approval_needed": discounts.approval_needed(applied, slab),
                 "rate_found": False, "reverse_charge": False, "sgst_label": split["sgst_label"]}
        # a line with no rate in force is reported, not priced: its tax fields are null
        entry.update({k: None for k in (
            "taxable_value", "cgst_rate", "sgst_rate", "igst_rate", "cess_rate",
            "cgst_amount", "sgst_amount", "igst_amount", "cess_amount",
            "tax_total", "round_off", "total")})
        if not hsn:
            notes.append(f"{entry['sku']} has no HSN code, so no GST rate can be looked up "
                         f"for it; add the HSN in the product master.")
            missing_rates.append(entry["sku"])
        else:
            rate = resolve_rate(db, hsn, when)
            if rate is None:
                notes.append(f"HSN {hsn} ({entry['sku']}) has no rate in force on {when}. "
                             f"Add one in the GST rate master; no rate is assumed.")
                missing_rates.append(hsn)
            else:
                computed = line_tax(qty=ln.qty, unit_price=ln.unit_price,
                                    discount_percent=applied, rate=rate,
                                    seller_state=company.state_code, buyer_state=dist.state_code)
                entry.update({
                    "rate_found": True, "reverse_charge": computed["reverse_charge"],
                    "taxable_value": computed["taxable_value"],
                    "cgst_rate": computed["cgst_rate"], "sgst_rate": computed["sgst_rate"],
                    "igst_rate": computed["igst_rate"], "cess_rate": computed["cess_rate"],
                    "cgst_amount": computed["cgst_amount"], "sgst_amount": computed["sgst_amount"],
                    "igst_amount": computed["igst_amount"], "cess_amount": computed["cess_amount"],
                    "sgst_label": computed["sgst_label"],
                    "tax_total": computed["tax_total"], "round_off": computed["round_off"],
                    "total": computed["total"]})
                if computed["reverse_charge"]:
                    notes.append(f"HSN {hsn} is on reverse charge: the tax is stated but "
                                 f"not collected; the recipient pays it.")
        lines.append(entry)

    # the document-level slab: the policy for the order as a whole (a quantity or
    # value band for every product, or one for this distributor's group). A slab
    # for a single product is shown on its own line instead.
    order_slab = discounts.best_slab(db, on=when, group_name=dist.group_name,
                                     qty=sum((ln.qty for ln in order.lines), ZERO),
                                     value=order.total)

    quoted = [l for l in lines if l["rate_found"]]
    totals = {
        "gross": money(sum((l["gross"] for l in lines), ZERO)),
        "discount_amount": money(sum((l["discount_amount"] for l in lines), ZERO)),
        "taxable_value": money(sum((l["taxable_value"] for l in quoted), ZERO)),
        "cgst_amount": money(sum((l["cgst_amount"] for l in quoted), ZERO)),
        "sgst_amount": money(sum((l["sgst_amount"] for l in quoted), ZERO)),
        "igst_amount": money(sum((l["igst_amount"] for l in quoted), ZERO)),
        "cess_amount": money(sum((l["cess_amount"] for l in quoted), ZERO)),
        "tax_total": money(sum((l["tax_total"] for l in quoted), ZERO)),
        "round_off": money(sum((l["round_off"] for l in quoted), ZERO)),
        "grand_total": money(sum((l["total"] for l in quoted), ZERO)),
    }
    return {
        "so_number": order.so_number, "status": order.status, "on": when,
        "seller": {"legal_name": company.legal_name, "gstin": company.gstin,
                   "pan": company.pan, "state_code": company.state_code,
                   "registration_type": company.registration_type},
        "place_of_supply": split,
        "slab": _slab_brief(order_slab),
        "lines": lines,
        "missing_rates": sorted(set(missing_rates)),
        "notes": notes,
        "totals": totals,
    }