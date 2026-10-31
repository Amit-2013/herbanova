"""Consecutive document numbers, unique per financial year (FR-14, AUD-034).

Every numbered tax document (invoice, credit note, debit note) takes its number
from one counter row per document type and financial year. The row is read
`FOR UPDATE` before it is incremented, so two dispatches at the same moment
queue for the next number instead of both seeing the same "last" value. A
number is never reused: a cancelled document keeps its number and the counter
only moves forward.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.core import (CreditNote, DebitNote, DocumentSequence, Invoice)

# The document each counter numbers, and the column that holds the number.
DOCUMENTS = {
    "invoice": (Invoice, Invoice.invoice_number),
    "credit_note": (CreditNote, CreditNote.credit_note_number),
    "debit_note": (DebitNote, DebitNote.debit_note_number),
}

# The invoice number is at most 16 characters (FR-14). "INV/2627/000001" is 15,
# leaving room for the largest serial a financial year can reach.
NUMBER_LIMIT = 16


def financial_year(d: date) -> str:
    """The Indian financial year label for a date: April to March, e.g. "26-27"."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def _highest_serial(db: Session, doc_type: str, fy: str) -> int:
    """The highest number already stored for this year.

    A counter table that arrives empty (a restored dump that predates it, or a
    migration re-applied over live documents) must continue after the documents
    that exist rather than start again at one.
    """
    model, column = DOCUMENTS[doc_type]
    stored = db.scalars(select(column).where(model.financial_year == fy)).all()
    serials = [int(n.rsplit("/", 1)[-1]) for n in stored
               if n and n.rsplit("/", 1)[-1].isdigit()]
    return max(serials, default=0)


def _counter(db: Session, doc_type: str, fy: str) -> DocumentSequence:
    """The locked counter row for this document type and year, created on first use."""
    def locked():
        return db.scalars(
            select(DocumentSequence)
            .where(DocumentSequence.doc_type == doc_type,
                   DocumentSequence.financial_year == fy)
            .with_for_update()
        ).first()

    seq = locked()
    if seq is not None:
        return seq
    # Two requests can find the counter missing at the same moment. The unique
    # constraint lets exactly one insert win; the loser then waits for the
    # winner's row (and lock) instead of issuing the same number.
    try:
        with db.begin_nested():
            db.add(DocumentSequence(doc_type=doc_type, financial_year=fy,
                                    last_number=_highest_serial(db, doc_type, fy)))
        seq = locked()
    except IntegrityError:
        seq = locked()
    if seq is None:                     # pragma: no cover - only if the insert vanished
        raise RuntimeError("document counter could not be created")
    return seq


def next_document_number(db: Session, doc_type: str, prefix: str,
                         on_date: date | None = None) -> tuple[str, str]:
    """Take the next number for `doc_type`, returning (number, financial_year).

    Callers must be inside the transaction that stores the document, so a
    failure anywhere after this point gives the number back rather than leaving
    a gap.
    """
    fy = financial_year(on_date or date.today())
    seq = _counter(db, doc_type, fy)
    seq.last_number += 1
    db.flush()
    number = f"{prefix}/{fy.replace('-', '')}/{seq.last_number:06d}"
    if len(number) > NUMBER_LIMIT:       # pragma: no cover - 999,999 documents in a year
        raise ValueError(f"{doc_type} number {number} is longer than {NUMBER_LIMIT} characters")
    return number, fy
