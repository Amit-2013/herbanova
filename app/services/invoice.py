"""Tax invoice generation at dispatch (Module Phase 4).

Invoices are created in the same transaction as stock issue and are immutable
once issued. Numbers are consecutive and unique per financial year (April to
March); cancelled numbers are never reused. Every financial field is a frozen
snapshot, so a later change to a product, a distributor or the company profile
cannot alter a document that has already been issued (FR-14).
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core import Distributor, Invoice, InvoiceLine, Product, SalesOrder
from ..models.tax import CompanyProfile
from . import advances
from .numbering import next_document_number
from .order_tax import discount_pct
from .tax import line_tax, money, place_of_supply, resolve_rate
from .words import amount_in_words


def _seller(db: Session, dist: Distributor) -> tuple[CompanyProfile | SimpleNamespace, list[str]]:
    """The company profile as it stands at issue, or a clearly flagged stand-in.

    A tax invoice without the supplier's GSTIN is not a valid document, so when
    the company profile has not been configured the invoice is still produced
    (the goods have moved and the stock ledger must stay truthful) but carries a
    note saying it cannot be issued to the recipient.
    """
    company = db.scalars(select(CompanyProfile).order_by(CompanyProfile.id)).first()
    if company is not None:
        return company, []
    return SimpleNamespace(legal_name="HERBANOVA (company profile not configured)",
                           gstin=None, pan=None, state_code=dist.state_code or "27",
                           address_line1=None, address_line2=None, city=None,
                           pincode=None), ["company tax profile is not configured"]


def create_invoice_for_order(db: Session, order: SalesOrder, issued_by: int) -> Invoice:
    dist = db.get(Distributor, order.distributor_id)
    if dist is None:
        raise ValueError("Distributor missing")
    company, notes = _seller(db, dist)

    buyer_state = dist.state_code or company.state_code or "27"
    split = place_of_supply(company.state_code or buyer_state, buyer_state)

    invoice_date = date.today()
    inv_num, fy = next_document_number(db, "invoice", "INV", invoice_date)
    # The distributor's terms are snapshotted onto the invoice, never read back
    # from the master, so changing the master later cannot move a due date the
    # buyer has already seen. No terms means no due date, and the ageing report
    # lists the invoice as having none rather than assuming one.
    terms = dist.payment_terms_days
    due_date = invoice_date + timedelta(days=terms) if terms is not None else None

    pids = {ln.product_id for ln in order.lines}
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(pids))).all()} if pids else {}

    invoice = Invoice(
        invoice_number=inv_num,
        financial_year=fy,
        sales_order_id=order.id,
        distributor_id=dist.id,
        status="issued",
        invoice_date=invoice_date,
        payment_terms_days=terms,
        due_date=due_date,
        place_of_supply_state_code=buyer_state,
        place_of_supply_kind=split["kind"],
        reverse_charge=False,
        seller_legal_name=company.legal_name,
        seller_gstin=company.gstin,
        seller_pan=company.pan,
        seller_state_code=company.state_code,
        seller_address_line1=company.address_line1,
        seller_address_line2=company.address_line2,
        seller_city=company.city,
        seller_pincode=company.pincode,
        buyer_name=dist.name,
        buyer_gstin=dist.gstin,
        buyer_pan=dist.pan,
        buyer_state_code=buyer_state,
        buyer_address_line1=dist.billing_address,
        buyer_address_line2=dist.shipping_address,
        issued_by=issued_by,
    )
    db.add(invoice)
    db.flush()

    gross_total = Decimal(0)
    discount_total = Decimal(0)
    taxable_value_total = Decimal(0)
    cgst_total = Decimal(0)
    sgst_total = Decimal(0)
    igst_total = Decimal(0)
    cess_total = Decimal(0)
    tax_total = Decimal(0)
    round_off_total = Decimal(0)
    grand_total = Decimal(0)
    has_reverse_charge = False

    for ln in sorted(order.lines, key=lambda x: x.product_id):
        p = products.get(ln.product_id)
        if not p:
            notes.append(f"product {ln.product_id} is missing from the master")
            continue
        hsn = (p.hsn or "").strip()
        applied_disc = discount_pct(p.mrp, ln.unit_price)
        gross = money(ln.qty * ln.unit_price)
        discount_amt = money(gross * applied_disc / 100)
        taxable = money(gross - discount_amt)

        line = InvoiceLine(
            invoice_id=invoice.id,
            product_id=p.id,
            sku=p.sku,
            product_name=p.name,
            hsn=hsn or None,
            uqc=p.uqc,
            qty=ln.qty,
            unit_price=money(ln.unit_price),
            mrp=p.mrp,
            discount_percent=applied_disc,
            discount_amount=discount_amt,
        )

        rate = resolve_rate(db, hsn, invoice_date) if hsn else None
        if not hsn:
            notes.append(f"{p.sku} has no HSN code")
        elif rate is None:
            notes.append(f"HSN {hsn} ({p.sku}) has no rate in force on {invoice_date}")

        if rate is None:
            # An invoice line without a rate is stated at zero tax and flagged,
            # never given an assumed rate.
            line.taxable_value = taxable
            line.cgst_rate = line.sgst_rate = line.igst_rate = line.cess_rate = Decimal(0)
            line.cgst_amount = line.sgst_amount = line.igst_amount = line.cess_amount = Decimal(0)
            line.line_total = taxable
        else:
            computed = line_tax(qty=ln.qty, unit_price=ln.unit_price,
                                discount_percent=applied_disc, rate=rate,
                                seller_state=company.state_code or buyer_state,
                                buyer_state=buyer_state)
            has_reverse_charge = has_reverse_charge or computed["reverse_charge"]
            line.taxable_value = computed["taxable_value"]
            line.cgst_rate = computed["cgst_rate"]
            line.sgst_rate = computed["sgst_rate"]
            line.igst_rate = computed["igst_rate"]
            line.cess_rate = computed["cess_rate"]
            line.cgst_amount = computed["cgst_amount"]
            line.sgst_amount = computed["sgst_amount"]
            line.igst_amount = computed["igst_amount"]
            line.cess_amount = computed["cess_amount"]
            line.line_total = computed["total"]
            cgst_total += computed["cgst_amount"]
            sgst_total += computed["sgst_amount"]
            igst_total += computed["igst_amount"]
            cess_total += computed["cess_amount"]
            tax_total += computed["tax_total"]
            round_off_total += computed["round_off"]

        db.add(line)
        taxable_value_total += line.taxable_value
        gross_total += gross
        discount_total += discount_amt
        grand_total += line.line_total

    invoice.reverse_charge = has_reverse_charge
    invoice.gross_total = money(gross_total)
    invoice.discount_total = money(discount_total)
    invoice.taxable_value = money(taxable_value_total)
    invoice.cgst_total = money(cgst_total)
    invoice.sgst_total = money(sgst_total)
    invoice.igst_total = money(igst_total)
    invoice.cess_total = money(cess_total)
    invoice.tax_total = money(tax_total)
    invoice.round_off = money(round_off_total)
    invoice.grand_total = money(grand_total)
    invoice.amount_in_words = amount_in_words(grand_total)
    invoice.notes = notes or None
    invoice.copy_designation = "ORIGINAL"
    db.flush()
    # Money the distributor already holds as an advance settles this bill now;
    # it is dated on the invoice and never posted to Sales a second time. The
    # applied rows are carried for the dispatch audit, not stored on the column.
    invoice.advance_applied = advances.apply_to_invoice(db, invoice, actor_id=issued_by)
    return invoice
