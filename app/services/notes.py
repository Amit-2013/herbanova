"""Credit and debit notes (FR-14, AUD-035).

An issued invoice is never edited. A correction is a credit note (the buyer is
owed money: a return, a rate difference, a post-sale rebate) or a debit note
(the buyer owes more: an undercharge discovered after dispatch). Both:

- are linked to the original invoice and to its lines;
- cannot take more quantity of a line than the invoice itself carried;
- cannot take the documents past the value of the original invoice;
- take their own consecutive number and are immutable once issued.

Credit notes also reverse tax, because the tax that was charged on the credited
value is credited back line by line (CGST Act section 34).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.core import (Batch, CreditNote, CreditNoteLine, DebitNote, DebitNoteLine,
                           Invoice, InvoiceLine, StockMovement, Warehouse)
from ..services.inventory import post_movement
from ..services.numbering import next_document_number
from ..services.tax import money


class NoteError(Exception):
    """A note that cannot be issued. `status` is the HTTP status to report."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _already_credited(db: Session, invoice_id: int) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(CreditNote.grand_total), 0))
        .where(CreditNote.invoice_id == invoice_id, CreditNote.status == "issued"))
    return money(total)


def _already_debited(db: Session, invoice_id: int) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(DebitNote.grand_total), 0))
        .where(DebitNote.invoice_id == invoice_id, DebitNote.status == "issued"))
    return money(total)


def _correction_room(db: Session, invoice: Invoice) -> Decimal:
    """What is left of the invoice value after the notes already issued."""
    used = _already_credited(db, invoice.id) + _already_debited(db, invoice.id)
    return money(invoice.grand_total - used)


def _line_amounts(inv_line: InvoiceLine, qty: Decimal) -> dict:
    """The share of the invoice line this quantity carries, rounded to the paise.

    A full-line note copies the invoice figures exactly, so a credit for the
    whole line can never leave a stray paise behind through rounding.
    """
    if qty == inv_line.qty:
        return {"taxable": money(inv_line.taxable_value),
                "cgst": money(inv_line.cgst_amount), "sgst": money(inv_line.sgst_amount),
                "igst": money(inv_line.igst_amount), "cess": money(inv_line.cess_amount),
                "total": money(inv_line.line_total)}
    ratio = qty / inv_line.qty
    parts = {"taxable": money(inv_line.taxable_value * ratio),
             "cgst": money(inv_line.cgst_amount * ratio),
             "sgst": money(inv_line.sgst_amount * ratio),
             "igst": money(inv_line.igst_amount * ratio),
             "cess": money(inv_line.cess_amount * ratio)}
    parts["total"] = money(parts["taxable"] + parts["cgst"] + parts["sgst"]
                           + parts["igst"] + parts["cess"])
    return parts


def _prepare(db: Session, invoice_id: int, lines, note_date: date) -> tuple[Invoice, list]:
    invoice = db.get(Invoice, invoice_id, with_for_update=True)
    if invoice is None:
        raise NoteError("Invoice not found", 404)
    if invoice.status != "issued":
        raise NoteError(f"Invoice {invoice.invoice_number} is {invoice.status}; a note needs a live invoice", 409)
    if note_date < invoice.invoice_date:
        raise NoteError("A note cannot be dated before the invoice it corrects", 422)
    if not lines:
        raise NoteError("A note needs at least one line", 422)

    ids = [ln.invoice_line_id for ln in lines]
    if len(set(ids)) != len(ids):
        raise NoteError("A line can appear only once on a note", 422)
    rows = {r.id: r for r in db.scalars(
        select(InvoiceLine).where(InvoiceLine.id.in_(ids))).all()}
    missing = [i for i in ids if i not in rows]
    if missing:
        raise NoteError(f"Invoice line(s) not found: {missing}", 422)
    for i in ids:
        if rows[i].invoice_id != invoice.id:
            raise NoteError(f"Invoice line {i} belongs to another invoice", 422)

    prepared = []
    for ln in lines:
        inv_line = rows[ln.invoice_line_id]
        qty = Decimal(ln.qty)
        if qty <= 0:
            raise NoteError("Quantities must be greater than zero", 422)
        already = db.scalar(
            select(func.coalesce(func.sum(CreditNoteLine.qty), 0))
            .join(CreditNote, CreditNote.id == CreditNoteLine.credit_note_id)
            .where(CreditNoteLine.invoice_line_id == inv_line.id,
                   CreditNote.status == "issued")) or Decimal(0)
        already += db.scalar(
            select(func.coalesce(func.sum(DebitNoteLine.qty), 0))
            .join(DebitNote, DebitNote.id == DebitNoteLine.debit_note_id)
            .where(DebitNoteLine.invoice_line_id == inv_line.id,
                   DebitNote.status == "issued")) or Decimal(0)
        if qty + Decimal(already) > inv_line.qty:
            raise NoteError(
                f"{inv_line.sku}: {inv_line.qty:f} invoiced, {Decimal(already):f} already noted, "
                f"{qty:f} asked for", 409)
        prepared.append((inv_line, qty, _line_amounts(inv_line, qty)))
    return invoice, prepared


def _build(db: Session, *, model, line_model, doc_type, prefix, invoice, prepared,
           reason: str, issued_by: int, note_date: date, kind: str):
    number, fy = next_document_number(db, doc_type, prefix, note_date)
    note = model(
        financial_year=fy,
        invoice_id=invoice.id,
        sales_order_id=invoice.sales_order_id,
        distributor_id=invoice.distributor_id,
        status="issued",
        note_date=note_date,
        reason=reason,
        issued_by=issued_by,
    )
    setattr(note, f"{kind}_number", number)
    db.add(note)
    db.flush()

    taxable = cgst = sgst = igst = cess = total = Decimal(0)
    for inv_line, qty, amounts in prepared:
        db.add(line_model(
            **{f"{kind}_id": note.id},
            invoice_line_id=inv_line.id,
            product_id=inv_line.product_id,
            sku=inv_line.sku,
            product_name=inv_line.product_name,
            qty=qty,
            taxable_value=amounts["taxable"],
            cgst_amount=amounts["cgst"],
            sgst_amount=amounts["sgst"],
            igst_amount=amounts["igst"],
            cess_amount=amounts["cess"],
            line_total=amounts["total"],
        ))
        taxable += amounts["taxable"]
        cgst += amounts["cgst"]
        sgst += amounts["sgst"]
        igst += amounts["igst"]
        cess += amounts["cess"]
        total += amounts["total"]

    note.gross_total = money(total)
    note.taxable_value = money(taxable)
    note.cgst_total = money(cgst)
    note.sgst_total = money(sgst)
    note.igst_total = money(igst)
    note.cess_total = money(cess)
    note.tax_total = money(cgst + sgst + igst + cess)
    note.grand_total = money(total)
    if hasattr(note, "discount_total"):
        note.discount_total = Decimal(0)
        note.round_off = Decimal(0)
    db.flush()
    return note


def _check_room(db: Session, invoice: Invoice, prepared, kind: str) -> None:
    room = _correction_room(db, invoice)
    value = money(sum(a["total"] for _, _, a in prepared))
    if value > room:
        raise NoteError(
            f"The {kind} note is {value:f} but only {room:f} of invoice "
            f"{invoice.invoice_number} ({invoice.grand_total:f}) is left to correct", 409)


def _return_batches(db: Session, invoice: Invoice, product_id: int) -> list:
    """The batches this order's goods left from, newest issue first.

    The dispatch wrote an "issue" movement per batch with a negative quantity.
    A sales return puts the quantity back into those same batches, in the
    reverse order of issue (the last batch issued is refilled first), so a
    return can never exceed what actually left and never invents a batch or an
    expiry date. Quantities are returned as positive amounts.

    Also returns the invoice line expiry for each batch, so the return flow
    can restore the original dispatch expiry date.
    """
    rows = db.execute(
        select(Batch, StockMovement.qty_delta)
        .join(StockMovement, StockMovement.batch_id == Batch.id)
        .where(StockMovement.movement_type == "issue",
               StockMovement.ref_type == "so",
               StockMovement.ref_id == str(invoice.sales_order_id),
               Batch.product_id == product_id)
        .order_by(StockMovement.id.desc())).all()
    result = [(batch, abs(Decimal(issued))) for batch, issued in rows]
    # Pair each batch with the invoice line's expiry snapshot from dispatch. Only when the
    # goods left from a single batch: the line holds one date, so with several batches it
    # is wrong for all but one of them, and each batch keeps the expiry it already has.
    for batch, _ in result:
        if len(result) > 1:
            batch._return_expiry = None
            continue
        line = db.scalar(select(InvoiceLine)
                         .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                         .where(InvoiceLine.product_id == product_id,
                                InvoiceLine.invoice_id == invoice.id)
                         .limit(1))
        batch._return_expiry = getattr(line, 'expiry', None) if line else None
    return result


def _post_returns(db: Session, *, note: CreditNote, invoice: Invoice, prepared,
                  warehouse_id: int, issued_by: int) -> None:
    """Put a returned quantity back into stock, one movement per batch.

    Runs inside the note's own transaction: if any batch cannot be refilled the
    whole note is refused, so a note and its stock can never disagree.

    Restores the original dispatch expiry date from the invoice line onto the
    batch, so returned stock carries the same expiry the goods had when they
    were originally despatched.
    """
    for inv_line, qty, _amounts in prepared:
        batches = _return_batches(db, invoice, inv_line.product_id)
        left = qty
        for batch, issued in batches:
            if left <= 0:
                break
            if batch.warehouse_id != warehouse_id:
                continue
            # Restore the dispatch expiry from the invoice line, if available
            if getattr(batch, '_return_expiry', None) is not None:
                batch.expiry = batch._return_expiry
            take = min(Decimal(issued), left)
            if take <= 0:
                continue
            try:
                post_movement(db, batch_id=batch.id, qty_delta=take, movement_type="return",
                              ref_type="credit_note", ref_id=str(note.id), actor_id=issued_by)
            except Exception as exc:                  # HTTPException from the ledger guard
                raise NoteError(
                    f"{inv_line.sku}: the goods could not be returned to batch "
                    f"{batch.batch_no}: {getattr(exc, 'detail', exc)}", 409)
            left -= take
        if left > 0:
            elsewhere = any(b.warehouse_id != warehouse_id for b, _ in batches)
            if elsewhere:
                raise NoteError(
                    f"{inv_line.sku}: {qty - left:f} of {qty:f} units were issued to "
                    f"another warehouse, so they cannot be returned to this one", 409)
            raise NoteError(
                f"{inv_line.sku}: only {qty - left:f} of {qty:f} units were issued on "
                f"this order, so the rest cannot be returned to stock", 409)


def create_credit_note(db: Session, *, invoice_id: int, lines, reason: str,
                       issued_by: int, note_date: date | None = None,
                       return_warehouse_id: int | None = None) -> CreditNote:
    """Issue a credit note against an invoice, refusing more than it carried.

    `return_warehouse_id` marks the note as a sales return: the credited
    quantities go back into the batches they were issued from, in the same
    warehouse, in the same transaction as the note.
    """
    reason = (reason or "").strip()
    if not reason:
        raise NoteError("A credit note needs a reason", 422)
    note_date = note_date or date.today()
    invoice, prepared = _prepare(db, invoice_id, lines, note_date)
    _check_room(db, invoice, prepared, "credit")
    if return_warehouse_id is not None:
        if db.get(Warehouse, return_warehouse_id) is None:
            raise NoteError("Warehouse not found", 404)
    note = _build(db, model=CreditNote, line_model=CreditNoteLine, doc_type="credit_note",
                  prefix="CN", invoice=invoice, prepared=prepared, reason=reason,
                  issued_by=issued_by, note_date=note_date, kind="credit_note")
    note.return_warehouse_id = return_warehouse_id
    if return_warehouse_id is not None:
        _post_returns(db, note=note, invoice=invoice, prepared=prepared,
                      warehouse_id=return_warehouse_id, issued_by=issued_by)
    db.flush()
    return note


def create_debit_note(db: Session, *, invoice_id: int, lines, reason: str,
                      issued_by: int, note_date: date | None = None) -> DebitNote:
    """Issue a debit note (an undercharge) against an invoice."""
    reason = (reason or "").strip()
    if not reason:
        raise NoteError("A debit note needs a reason", 422)
    note_date = note_date or date.today()
    invoice, prepared = _prepare(db, invoice_id, lines, note_date)
    _check_room(db, invoice, prepared, "debit")
    return _build(db, model=DebitNote, line_model=DebitNoteLine, doc_type="debit_note",
                  prefix="DN", invoice=invoice, prepared=prepared, reason=reason,
                  issued_by=issued_by, note_date=note_date, kind="debit_note")