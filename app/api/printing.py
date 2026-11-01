"""Printing tax documents (Module Phase 5, AUD-036 and AUD-037).

A print serves the document as a PDF built from the locked database record —
never from a stored file — carrying the watermark for its copy set, an IST
timestamp, a document ID and page numbering. The SHA-256 of the exact bytes
served is stored in the print log, so a later verification can prove a printed
page still matches that record.

Honest about the limits: a watermark and a timestamp do not stop an edit. The
security is the locked record plus the hash, and the verification endpoint is
what proves it.
"""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.downloads import safe_filename
from ..core.rbac import require
from ..models.core import CreditNote, DebitNote, Invoice, PrintLog, User
from ..services.audit import audit
from ..services.document_pdf import (COPIES, finalise_print, render, reserve_print,
                                     verify_reference)
from ..services.qr import print_code, svg

router = APIRouter(prefix="/api/print", tags=["printing"])

MODEL_BY_KIND = {"invoice": Invoice, "credit_note": CreditNote, "debit_note": DebitNote}
NUMBER_ATTR = {"invoice": "invoice_number", "credit_note": "credit_note_number",
               "debit_note": "debit_note_number"}


def _load(kind: str, document_id: int, db: Session):
    model = MODEL_BY_KIND.get(kind)
    if model is None:
        raise HTTPException(404, f"Unknown document type {kind}")
    doc = db.get(model, document_id)
    if doc is None:
        raise HTTPException(404, f"{kind} {document_id} not found")
    return doc


class PrintOut(BaseModel):
    document_type: str
    document_number: str
    copy_designation: str
    print_code: str
    sha256: str
    printed_at: datetime
    printed_by: str
    verify_path: str


def _log_out(log: PrintLog, printed_by: str) -> PrintOut:
    return PrintOut(
        document_type=log.document_type,
        document_number=log.document_number,
        copy_designation=log.copy_designation,
        print_code=print_code(log.id),
        sha256=log.sha256,
        printed_at=log.printed_at,
        printed_by=printed_by,
        verify_path=f"/api/print/verify/{print_code(log.id)}",
    )


@router.get("/verify/{reference}")
@router.post("/verify/{reference}")
def verify_document(reference: str, db: Session = Depends(get_db),
                    user=Depends(require("print:document"))):
    """Check a printed reference against the print log.

    Both verbs are served (COR-004): the screen reads the result with GET, and a
    link or a scan opened in a browser asks the same way. Three references are
    accepted — the code printed on the page (``PRT-000123``), the full SHA-256
    of the served file, and the 16-character short hash. Whatever the reference,
    the answer names the print it belongs to.
    """
    log = verify_reference(db, reference)
    if log is None:
        return {"valid": False,
                "reason": "No printed document carries that code. The page or "
                          "file is not one this system served, or it has been "
                          "altered."}
    actor = _username_for(db, log.printed_by)
    return {"valid": True, "document_type": log.document_type,
            "document_number": log.document_number,
            "copy_designation": log.copy_designation,
            "printed_at": log.printed_at, "printed_by": actor,
            "print_code": print_code(log.id),
            "sha256": log.sha256}


@router.get("/qr/{reference}")
def document_qr(reference: str, db: Session = Depends(get_db),
                user=Depends(require("print:document"))):
    """The QR symbol for a print (COR-005, D-15).

    The symbol always encodes the code printed on the page (``PRT-000123``), so
    the image on screen and the image on paper are the same reference. Asking by
    hash resolves to the same print and returns that same symbol; an unknown
    reference is a 404, because there is nothing to vouch for.
    """
    log = verify_reference(db, reference)
    if log is None:
        raise HTTPException(404, "No printed document carries that code")
    return Response(content=svg(print_code(log.id)), media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=300"})


# The specific routes must be declared before the catch-all below them,
# otherwise "verify" or "qr" is read as a document kind.
@router.post("/{kind}/{document_id}")
def print_document(kind: str, document_id: int, copy: str = "ORIGINAL",
                   db: Session = Depends(get_db),
                   user=Depends(require("print:document"))):
    """Serve one copy of a document as a PDF, and record its hash."""
    if copy not in COPIES:
        raise HTTPException(422, f"Copy must be one of {', '.join(COPIES)}")
    doc = _load(kind, document_id, db)
    number = getattr(doc, NUMBER_ATTR[kind])
    # Document numbers carry slashes (INV/2627/000001). A slash inside the
    # quoted name is not a path, but browsers save it inconsistently, so the
    # served name uses dashes instead.
    filename = f"{kind}-{number.replace('/', '-')}-{copy}.pdf"
    # Reserve the row first: the page carries its code, and the code is the row.
    log = reserve_print(db, kind, document_id, number, copy, user.id)
    code = print_code(log.id)
    try:
        payload, digest = render(db, kind, document_id, copy, user.username, code)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc))
    finalise_print(db, log, digest)
    audit(db, user.id, "document.print", f"{kind}:{document_id}",
          {"number": number, "copy": copy, "print_code": code, "sha256": digest})
    db.commit()
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename(filename, "document.pdf")}"',
            "X-Document-SHA256": digest,
            "X-Print-Code": code,
        },
    )


def _username_for(db: Session, user_id: int) -> str:
    u = db.get(User, user_id)
    return u.username if u else str(user_id)


@router.get("/log", response_model=list[PrintOut])
def print_log(db: Session = Depends(get_db), user=Depends(require("print:document"))):
    logs = db.scalars(select(PrintLog).order_by(PrintLog.id.desc()).limit(200)).all()
    names = {log.printed_by: _username_for(db, log.printed_by) for log in logs}
    return [_log_out(log, names.get(log.printed_by, str(log.printed_by))) for log in logs]


@router.get("/log/{kind}/{document_id}", response_model=list[PrintOut])
def document_print_log(kind: str, document_id: int,
                       db: Session = Depends(get_db),
                       user=Depends(require("print:document"))):
    """Every print of one document, newest first."""
    if kind not in MODEL_BY_KIND:
        raise HTTPException(404, f"Unknown document type {kind}")
    logs = db.scalars(select(PrintLog).where(PrintLog.document_type == kind,
                                            PrintLog.document_id == document_id)
                      .order_by(PrintLog.id.desc())).all()
    names = {log.printed_by: _username_for(db, log.printed_by) for log in logs}
    return [_log_out(log, names.get(log.printed_by, str(log.printed_by))) for log in logs]
