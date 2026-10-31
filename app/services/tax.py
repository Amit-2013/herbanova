"""GST arithmetic (FR-13). Everything here is Decimal; nothing touches float.

Two rules decide the numbers:

- **The rate is whatever was in force on the document date.** It is looked up
  from `tax_rates` by HSN and date, never assumed in code.
- **The place of supply decides the split.** Seller and buyer in the same state
  gives CGST + SGST (UTGST instead of SGST inside a union territory); different
  states give IGST. Cess, when a rate carries it, is charged on the taxable
  value too. A rate marked reverse charge states the tax but collects none of
  it: the recipient pays it.

Discount is applied to the line value before tax, so it reduces the taxable
value (CGST Act section 15(3), BRD Appendix B). Every step is rounded to the
paise with half-up rounding, and the document total can then be rounded to the
rupee with a visible round-off amount.

None of this is tax advice: the rates themselves come from the data the
business enters and its adviser validates.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.india_states import STATE_CODES, is_union_territory, state_name
from ..models.tax import TaxRate

ZERO = Decimal(0)
PAISE = Decimal("0.01")
RUPEE = Decimal("1")


def money(x) -> Decimal:
    return Decimal(x or 0).quantize(PAISE, ROUND_HALF_UP)


def pct(x) -> Decimal:
    return Decimal(x or 0).quantize(PAISE, ROUND_HALF_UP)


def round_to_rupee(x: Decimal) -> tuple[Decimal, Decimal]:
    """(rounded total, round-off amount) — the round-off line FR-13 asks for."""
    value = money(x)
    rounded = value.quantize(RUPEE, ROUND_HALF_UP)
    return rounded, money(rounded - value)


def resolve_rate(db: Session, hsn: str, on: date) -> TaxRate | None:
    """The rate for this HSN in force on `on` (None when the master has none)."""
    if not hsn:
        return None
    return db.scalars(
        select(TaxRate)
        .where(TaxRate.hsn == str(hsn).strip(),
               TaxRate.effective_from <= on,
               or_(TaxRate.effective_to.is_(None), TaxRate.effective_to >= on))
        .order_by(TaxRate.effective_from.desc())).first()


def overlapping_rate(db: Session, hsn: str, start: date, end: date | None,
                     exclude_id: int | None = None) -> TaxRate | None:
    """An existing window for the same HSN that overlaps [start, end]."""
    q = select(TaxRate).where(
        TaxRate.hsn == str(hsn).strip(),
        TaxRate.effective_from <= (end or date.max),
        or_(TaxRate.effective_to.is_(None), TaxRate.effective_to >= start))
    if exclude_id:
        q = q.where(TaxRate.id != exclude_id)
    return db.scalars(q).first()


def place_of_supply(seller_state: str | None, buyer_state: str | None) -> dict:
    """Classify the supply. A missing state is refused rather than guessed."""
    if not seller_state or not buyer_state:
        raise ValueError("both the seller's and the buyer's state code are needed")
    seller = str(seller_state).zfill(2)
    buyer = str(buyer_state).zfill(2)
    for code in (seller, buyer):
        if code not in STATE_CODES:
            raise ValueError(f"unknown state code {code}")
    intra = seller == buyer
    return {"kind": "intra" if intra else "inter",
            "seller_state": seller, "seller_state_name": state_name(seller),
            "buyer_state": buyer, "buyer_state_name": state_name(buyer),
            "is_union_territory": is_union_territory(buyer),
            # UTGST replaces SGST when the place of supply is a union territory
            "sgst_label": "UTGST" if (intra and is_union_territory(buyer)) else "SGST"}


def level_split(rate: TaxRate, split: dict) -> dict:
    """The rate percentages that apply, per head, for this place of supply."""
    if split["kind"] == "intra":
        return {"cgst": pct(rate.cgst_rate), "sgst": pct(rate.sgst_rate), "igst": ZERO,
                "cess": pct(rate.cess_rate)}
    return {"cgst": ZERO, "sgst": ZERO, "igst": pct(rate.igst_rate), "cess": pct(rate.cess_rate)}


def line_tax(*, qty: Decimal, unit_price: Decimal, discount_percent: Decimal, rate: TaxRate,
             seller_state: str | None, buyer_state: str | None) -> dict:
    """Tax on one line: value, discount, taxable value, tax heads and total."""
    quantity = Decimal(qty)
    price = Decimal(unit_price)
    if quantity <= 0:
        raise ValueError("quantity must be above zero")
    if price < 0:
        raise ValueError("unit price cannot be negative")
    discount = pct(discount_percent)
    if discount < 0 or discount > 100:
        raise ValueError("the discount must be between 0 and 100 percent")

    split = place_of_supply(seller_state, buyer_state)
    levels = level_split(rate, split)
    reverse_charge = bool(getattr(rate, "is_reverse_charge", False))

    gross = money(quantity * price)
    discount_amount = money(gross * discount / Decimal(100))
    taxable = money(gross - discount_amount)
    cgst = money(taxable * levels["cgst"] / Decimal(100))
    sgst = money(taxable * levels["sgst"] / Decimal(100))
    igst = money(taxable * levels["igst"] / Decimal(100))
    cess = money(taxable * levels["cess"] / Decimal(100))
    tax_total = money(cgst + sgst + igst + cess)
    if reverse_charge:
        # the recipient pays the tax: the seller states it but collects nothing
        cgst = sgst = igst = cess = tax_total = ZERO
    unrounded_total = money(taxable + tax_total)
    total, round_off = round_to_rupee(unrounded_total)
    return {
        "hsn": rate.hsn,
        "rate_id": rate.id,
        "effective_from": rate.effective_from,
        "qty": quantity,
        "unit_price": money(price),
        "gross": gross,
        "discount_percent": discount,
        "discount_amount": discount_amount,
        "taxable_value": taxable,
        "split": split["kind"],
        "place_of_supply": split["buyer_state"],
        "place_of_supply_name": split["buyer_state_name"],
        "seller_state": split["seller_state"],
        "is_union_territory": split["is_union_territory"],
        "reverse_charge": reverse_charge,
        "cgst_rate": levels["cgst"],
        "sgst_rate": levels["sgst"],
        "igst_rate": levels["igst"],
        "cess_rate": levels["cess"],
        "sgst_label": split["sgst_label"],
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "igst_amount": igst,
        "cess_amount": cess,
        "tax_total": tax_total,
        "total_before_round_off": unrounded_total,
        "round_off": round_off,
        "total": total,
    }
