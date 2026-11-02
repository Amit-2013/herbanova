"""Printable PDFs for tax documents (Module Phase 5).

Two jobs, both honest about what protection a PDF really gives:

- render() draws an invoice or a note the way GST expects it — seller and
  buyer, place of supply, HSN lines, the tax split, the amount in words and a
  copy set — with a watermark, an IST timestamp and a scannable verification
  code over the whole page;
- reserve_print() takes the print-log row before rendering, finalise_print()
  stores the SHA-256 of the exact bytes served, and verify_reference() answers
  for the code printed on the page or for either form of the hash.

The security is the locked database record plus that hash, not the PDF file
itself. A watermark alone does not stop an edit; the verification does.
"""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.india_states import is_union_territory, state_name
from ..models.core import CreditNote, DebitNote, Invoice, PrintLog
from ..services import pdf_fonts
from ..services.qr import SHORT_HASH_LEN, matrix, parse_print_code
from ..services.words import amount_in_words

IST = ZoneInfo("Asia/Kolkata")
COPIES = ("ORIGINAL", "DUPLICATE", "TRIPLICATE")
DOC_LABEL = {"invoice": "TAX INVOICE", "credit_note": "CREDIT NOTE", "debit_note": "DEBIT NOTE"}

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm

ROW_H = 12           # one table row
TABLE_HEAD_H = 14    # a table's header band, including its gap
CONTENT_BOTTOM = 118  # nothing may be drawn below this: the footer's QR block
                      # with its quiet zone tops out near y=112


class Doc:
    """The drawing surface with page numbering, so a block can ask for a new page.

    Content is written top-down. When a table, the totals or the closing block
    has no room left, it asks the document for another page and keeps drawing at
    that page's cursor. Each page is stamped, numbered and closed as it finishes,
    because ReportLab emits pages in order and a later page cannot be revisited —
    which is also why the renderer lays the document out twice: once to learn how
    many pages there are, then again so every footer can print "Page n of N".
    """

    def __init__(self, canvas_obj, label: str, stamp: datetime, printed_by: str,
                 verify_code: str, watermark: str, doc_id: str = "",
                 page_total: int | None = None):
        self._canvas = canvas_obj
        self.label = label
        self.stamp = stamp
        self.printed_by = printed_by
        self.verify_code = verify_code
        self.watermark = watermark
        self.doc_id = doc_id
        self.page_total = page_total
        self.page_count = 1
        self.y = PAGE_H - MARGIN

    @property
    def canvas(self):
        return self._canvas

    @property
    def total_pages(self) -> int:
        return self.page_count

    @property
    def page_text(self) -> str:
        """The right-hand footer text; the total is unknown while measuring."""
        if self.page_total:
            return f"Page {self.page_count} of {self.page_total}"
        return f"Page {self.page_count}"

    def finish_page(self) -> None:
        """Stamp, number and close the page being drawn, then end it."""
        _draw_watermark(self._canvas, self.watermark)
        if self.page_total is not None:
            _footer(self._canvas, self.doc_id, self.printed_by, self.stamp,
                    self.page_text, self.verify_code)
        self._canvas.showPage()

    def continue_page(self) -> float:
        """Close the current page, start the next one and label it. Returns the new y."""
        self.finish_page()
        self.page_count += 1
        c = self._canvas
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(colors.HexColor("#666666"))
        c.drawString(MARGIN, PAGE_H - MARGIN, f"{self.label} continued")
        c.setFillColor(colors.black)
        self.y = PAGE_H - MARGIN - 14
        return self.y

    def needs(self, height: float, y: float | None = None) -> bool:
        """True when ``y`` (or the page cursor) cannot hold ``height`` more."""
        at = self.y if y is None else y
        return at - height < CONTENT_BOTTOM

    def need_page(self, height: float, y: float | None = None) -> float:
        """Move to a fresh page when the next block will not fit. Returns the cursor."""
        at = self.y if y is None else y
        if self.needs(height, at):
            return self.continue_page()
        return at


def _money(v) -> str:
    return f"{Decimal(v or 0):,.2f}"


def _state_label(code: str | None) -> str:
    """A state code with its name, as the rules ask for the place of supply."""
    if not code:
        return "—"
    name = state_name(code)
    return f"{code} · {name}" if name else str(code)


def _split_label(place_of_supply_code: str, kind: str) -> str:
    """What the tax on this supply is actually called.

    A supply inside a union territory is CGST + UTGST; calling that "SGST" on
    the paper would misname a statutory tax head (part of COR-009; the stored
    column is still named sgst, which the print does not change).
    """
    if kind == "inter":
        return "IGST"
    return "CGST + UTGST" if is_union_territory(place_of_supply_code) else "CGST + SGST"


def _plain(value) -> str:
    """A stored number without scale or exponent: 9.00 -> 9, 50.000 -> 50, 1E+2 -> 100."""
    return format(Decimal(value or 0).normalize(), "f")


def _rate_text(value) -> str:
    """A GST rate without trailing scale: Decimal('9.00') prints as 9."""
    return _plain(value)


def _wrap(text: str, max_width: float, size: float = 8) -> list[str]:
    """Split a value into lines that fit a column, so free text cannot run off the page."""
    pdf_fonts.register()  # stringWidth needs the face even when build() has not run
    words = str(text or "—").split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or stringWidth(trial, pdf_fonts.FONT, size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return [line for line in lines if line] or ["—"]


def _uniform_rate(lines, attr: str):
    """The one rate every line carries for this head, or None when they differ."""
    rates = {Decimal(getattr(line, attr, 0) or 0) for line in lines}
    return rates.pop() if len(rates) == 1 else None


def _tax_heads(doc, lines, inter: bool, sgst_label: str) -> list[tuple[str, object]]:
    """The tax heads that apply to this document, with a rate when it is uniform.

    Only applicable heads are printed: an inter-state supply does not show a
    zero CGST line, and cess appears only when it was charged.
    """
    heads = ([("IGST", "igst_total", "igst_rate")] if inter else
             [("CGST", "cgst_total", "cgst_rate"),
              (sgst_label, "sgst_total", "sgst_rate")])
    rows: list[tuple[str, object]] = []
    for label, total_attr, rate_attr in heads:
        rate = _uniform_rate(lines, rate_attr)
        rows.append((f"{label} @ {_rate_text(rate)}%" if rate else label,
                     getattr(doc, total_attr, 0)))
    if Decimal(getattr(doc, "cess_total", 0) or 0):
        rate = _uniform_rate(lines, "cess_rate")
        rows.append((f"Cess @ {_rate_text(rate)}%" if rate else "Cess", doc.cess_total))
    return rows


def _totals(c: canvas.Canvas, doc, lines, inter: bool, sgst_label: str, y: float,
            total_label: str = "Grand total") -> float:
    """Taxable value, each applicable tax head, round off and the total."""
    right = PAGE_W - MARGIN
    c.setFont("Helvetica", 8)
    rows = [("Taxable value", doc.taxable_value)] + _tax_heads(doc, lines, inter, sgst_label)
    if Decimal(getattr(doc, "round_off", 0) or 0):
        rows.append(("Round off", doc.round_off))
    for label, value in rows:
        c.drawRightString(right - 100, y, label)
        c.drawRightString(right, y, _money(value))
        y -= 12
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(right - 100, y, total_label)
    c.drawRightString(right, y, f"Rs {_money(doc.grand_total)}")
    return y - 16


def _in_words(c: canvas.Canvas, words: str | None, y: float) -> float:
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(MARGIN, y, f"In words: {words or '—'}")
    return y - 12


# Statements this application can actually stand behind. Terms that would bind
# the business (interest, jurisdiction, return windows) are business decisions
# and are deliberately not printed.
TERMS = (
    "Goods once sold are taken back only through a credit note issued against this document.",
    "The prices, discounts and tax rates shown are the ones recorded when this document was "
    "issued; a later change to the master data does not alter it.",
    "This is a computer-generated document. The printed verification code can be checked "
    "against the system's own record.",
)

SIGNATURE_ANCHOR = 200   # points from the bottom edge; the terms block ends
                          # near y=120 and must clear the QR caption that tops
                          # out near y=112, so nothing may sit between them


def _annexure_rows(lines, inter: bool, sgst_label: str):
    """(headers, rows, widths) of the HSN-wise tax summary.

    Lines that share an HSN but carry different rates stay separate rows — a
    single classification can be taxed at more than one rate.
    """
    groups: dict[tuple, dict[str, Decimal]] = {}
    for ln in lines:
        key = (getattr(ln, "hsn", None) or "—", _rate_text(getattr(ln, "cgst_rate", 0)),
               _rate_text(getattr(ln, "sgst_rate", 0)), _rate_text(getattr(ln, "igst_rate", 0)),
               _rate_text(getattr(ln, "cess_rate", 0)))
        totals = groups.setdefault(key, {name: Decimal(0) for name in
                                        ("taxable", "cgst", "sgst", "igst", "cess")})
        for field, attr in (("taxable", "taxable_value"), ("cgst", "cgst_amount"),
                            ("sgst", "sgst_amount"), ("igst", "igst_amount"),
                            ("cess", "cess_amount")):
            totals[field] += Decimal(getattr(ln, attr, 0) or 0)
    widths = [58, 44, 66, 62, 62, 62, 58]
    headers = ["HSN / SAC", "GST %", "Taxable", "CGST", sgst_label, "IGST", "Cess"]
    rows = []
    for (hsn, cgst_rate, sgst_rate, igst_rate, cess_rate), totals in sorted(groups.items()):
        rate = igst_rate if inter else f"{cgst_rate}+{sgst_rate}"
        rows.append([hsn, rate, _money(totals["taxable"]),
                     _money(totals["cgst"]) if not inter else "—",
                     _money(totals["sgst"]) if not inter else "—",
                     _money(totals["igst"]) if inter else "—",
                     _money(totals["cess"])])
    return headers, rows, widths


def _annexure_height(lines) -> float:
    """How much vertical room the annexure takes, title band included."""
    _, rows, _ = _annexure_rows(lines, True, "SGST")
    return 6 + 14 + TABLE_HEAD_H + ROW_H * len(rows)


def _hsn_annexure(c: canvas.Canvas, doc: Doc, lines, inter: bool, sgst_label: str,
                  y: float) -> float:
    """The HSN-wise tax summary: one row per classification and rate."""
    y -= 6
    c.setFont("Helvetica-Bold", 8)
    c.drawString(MARGIN, y, "HSN / SAC tax summary")
    y -= 14
    headers, rows, widths = _annexure_rows(lines, inter, sgst_label)
    return _table(doc, headers, rows, widths, y)


def _close_page(doc: Doc, seller: str, y: float, annexure: bool = False,
                inter: bool = False, sgst_label: str = "SGST", lines=(),
                terms: bool = True) -> float:
    """Close the document: the annexure, then the terms and the signature.

    Neither block is ever squeezed: when the page has no room for it, the
    document continues onto a fresh page instead. That is the whole promise of
    pagination — the totals, the terms and the signature are printed in full or
    not at all, never overprinted by a footer and never dropped. Terms belong to
    the invoice; a note repeats no business terms of its own.
    """
    c = doc.canvas
    if annexure:
        # The annexure must finish with room left for the terms and signature.
        if y - _annexure_height(lines) - 40 < SIGNATURE_ANCHOR:
            y = doc.continue_page()
            c = doc.canvas
        y = _hsn_annexure(c, doc, lines, inter, sgst_label, y)
    # The closing block is anchored, so it is never squeezed into the footer.
    if y - 40 < SIGNATURE_ANCHOR:
        y = doc.continue_page()
        c = doc.canvas
    anchor = SIGNATURE_ANCHOR
    # The company line and the designation are one block: both sit on the
    # centre of the same signature line, so they align on paper.
    signature_x = PAGE_W - MARGIN - 75
    if terms:
        c.setFont("Helvetica-Bold", 7)
        c.drawString(MARGIN, anchor, "Terms and conditions")
        c.setFont("Helvetica", 7)
        c.drawCentredString(signature_x, anchor, f"For {seller or 'the supplier'}")
    else:
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#444444"))
        c.drawCentredString(signature_x, anchor, f"For {seller or 'the supplier'}")
        c.setFillColor(colors.black)
    y = anchor - 10
    c.setStrokeColor(colors.HexColor("#666666"))
    c.line(PAGE_W - MARGIN - 150, y, PAGE_W - MARGIN, y)
    c.setFont("Helvetica", 7)
    c.drawCentredString(signature_x, y - 10, "Authorised signatory")
    y = anchor - 28
    if terms:
        width = (PAGE_W - 2 * MARGIN) / 2 - 10
        c.setFont("Helvetica", 6.5)
        for number, term in enumerate(TERMS, start=1):
            for line in _wrap(f"{number}. {term}", width, size=6.5):
                c.drawString(MARGIN, y, line)
                y -= 8
    return y


def _draw_watermark(c: canvas.Canvas, text: str) -> None:
    """A faint diagonal stamp across the page. It marks the copy; it is not security."""
    c.saveState()
    c.setFillColor(colors.Color(0.55, 0.55, 0.55, alpha=0.16))
    c.setFont("Helvetica-Bold", 64)
    c.translate(PAGE_W / 2, PAGE_H / 2)
    c.rotate(45)
    c.drawCentredString(0, 0, text)
    c.restoreState()


def _lines(c: canvas.Canvas, rows: list[tuple[str, str]], x: float, y: float, width: float) -> float:
    """Draw label/value pairs down from y; returns the next free y."""
    c.setFont("Helvetica", 8)
    for label, value in rows:
        c.setFillColor(colors.HexColor("#444444"))
        c.drawString(x, y, label)
        c.setFillColor(colors.black)
        c.drawRightString(x + width, y, value or "—")
        y -= 11
    return y


def _kv(c: canvas.Canvas, left: tuple[str, str], right: tuple[str, str], y: float,
        wrap: float | None = None) -> float:
    """A label/value pair on each half of the page, one line or wrapped."""
    half = (PAGE_W - 2 * MARGIN) / 2
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#444444"))
    c.drawString(MARGIN, y, left[0])
    c.drawString(MARGIN + half, y, right[0])
    c.setFillColor(colors.black)
    left_lines = _wrap(left[1] or "—", wrap) if wrap else [left[1] or "—"]
    right_lines = _wrap(right[1] or "—", wrap) if wrap else [right[1] or "—"]
    for index in range(max(len(left_lines), len(right_lines))):
        line_y = y - 10 - index * 10
        if index < len(left_lines):
            c.drawString(MARGIN, line_y, left_lines[index])
        if index < len(right_lines):
            c.drawString(MARGIN + half, line_y, right_lines[index])
    return y - 26 - (max(len(left_lines), len(right_lines)) - 1) * 10


def _table(doc: Doc, headers: list[str], rows: list[list[str]], widths: list[float],
           y: float) -> float:
    """Draw a table, starting a new page and repeating its header when it runs out.

    A new page is chosen so that no row lands below the footer's QR block.
    """
    c = doc.canvas
    x = MARGIN
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(colors.HexColor("#eeeeee"))
    c.rect(x, y - 4, sum(widths), 13, stroke=0, fill=1)
    c.setFillColor(colors.black)
    for head, w in zip(headers, widths):
        c.drawString(x + 2, y, head)
        x += w
    y -= 14
    for row in rows:
        if doc.needs(ROW_H, y):
            y = doc.continue_page()
            c = doc.canvas
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(colors.HexColor("#eeeeee"))
            c.rect(MARGIN, y - 4, sum(widths), 13, stroke=0, fill=1)
            c.setFillColor(colors.black)
            x = MARGIN
            for head, w in zip(headers, widths):
                c.drawString(x + 2, y, head)
                x += w
            y -= 14
        x = MARGIN
        for cell, w in zip(row, widths):
            c.drawString(x + 2, y, cell)
            x += w
        y -= 12
    return y


VERIFY_QR = 18 * mm   # side of the symbol printed on the page


def _draw_verify_block(c: canvas.Canvas, code: str) -> None:
    """Draw the scannable verification code in the lower-left footer band.

    The symbol encodes the print reference (``PRT-000123``), not a hash of this
    file: a QR cannot contain the hash of the document that contains it. The
    reference resolves at /api/print/verify to the print-log row, and that row
    holds the SHA-256 of the exact bytes served.
    """
    grid = matrix(code)
    side = len(grid)
    module = VERIFY_QR / side
    quiet = 4 * module          # the standard's quiet zone, kept clear of text
    x0, y0 = MARGIN, 18 * mm    # above the footer line, below the last of the totals
    c.saveState()
    c.setFillColor(colors.white)
    c.rect(x0 - quiet, y0 - quiet, VERIFY_QR + 2 * quiet, VERIFY_QR + 2 * quiet,
           stroke=0, fill=1)
    c.setFillColor(colors.black)
    for row, line in enumerate(grid):
        for col, dark in enumerate(line):
            if dark:
                c.rect(x0 + col * module, y0 + (side - 1 - row) * module,
                       module, module, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#444444"))
    c.setFont("Helvetica-Bold", 7)
    c.drawString(x0 + VERIFY_QR + quiet + 2, y0 + VERIFY_QR - 8,
                 f"Verification code {code}")
    c.setFont("Helvetica", 6)
    c.drawString(x0 + VERIFY_QR + quiet + 2, y0 + VERIFY_QR - 18,
                 "Scan the symbol, or enter the code in Print and verification")
    c.drawString(x0 + VERIFY_QR + quiet + 2, y0 + VERIFY_QR - 27,
                 "to confirm this page still matches the record it was printed from.")
    c.restoreState()


def _footer(c: canvas.Canvas, doc_id: str, printed_by: str, stamp: datetime,
            page_text: str, verify_code: str = "") -> None:
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(MARGIN, 10 * mm, f"Document ID {doc_id}  ·  printed by {printed_by}")
    c.drawRightString(PAGE_W - MARGIN, 10 * mm,
                      f"Generated {stamp.strftime('%d %b %Y %H:%M:%S')} IST  ·  "
                      f"{page_text}")
    if verify_code:
        _draw_verify_block(c, verify_code)


def _render_invoice(doc: Doc, inv: Invoice, copy: str) -> float:
    """Draw the invoice; returns the free y left after the content block."""
    c = doc.canvas
    y = PAGE_H - MARGIN
    y = PAGE_H - MARGIN
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, y, DOC_LABEL["invoice"])
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(PAGE_W - MARGIN, y, copy)
    y -= 16
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#444444"))
    c.drawString(MARGIN, y, f"Invoice {inv.invoice_number}   ·   Financial year {inv.financial_year}")
    c.drawRightString(PAGE_W - MARGIN, y, f"Date {inv.invoice_date:%d %b %Y}")
    y -= 16

    c.setLineWidth(0.6)
    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 14

    y = _kv(c, ("Seller", inv.seller_legal_name or "—"),
               ("Buyer", inv.buyer_name or "—"), y)
    y = _kv(c, ("GSTIN", inv.seller_gstin or "—"), ("GSTIN", inv.buyer_gstin or "—"), y)
    y = _kv(c, ("PAN", inv.seller_pan or "—"), ("PAN", inv.buyer_pan or "—"), y)
    y = _kv(c, ("Address", ", ".join(filter(None, [inv.seller_address_line1,
                                                    inv.seller_address_line2,
                                                    inv.seller_city, inv.seller_pincode])) or "—"),
               ("Address", ", ".join(filter(None, [inv.buyer_address_line1,
                                                    inv.buyer_address_line2])) or "—"), y,
               wrap=(PAGE_W - 2 * MARGIN) / 2 - 6)
    y = _kv(c, ("State", _state_label(inv.seller_state_code)),
               ("State", _state_label(inv.buyer_state_code)), y)
    y = _kv(c, ("Place of supply",
                f"{_state_label(inv.place_of_supply_state_code)} · "
                f"{_split_label(inv.place_of_supply_state_code, inv.place_of_supply_kind)}"),
               ("Reverse charge", "Yes" if inv.reverse_charge else "No"), y)

    if inv.delivery_challan_number or inv.vehicle_number or inv.transporter_name:
        y -= 4
        y = _kv(c, ("Delivery challan", inv.delivery_challan_number or "—"),
                   ("Vehicle", inv.vehicle_number or "—"), y)
        y = _kv(c, ("Transporter", inv.transporter_name or "—"),
                   ("E-way bill", inv.eway_bill_number or "—"), y)

    y -= 6
    c.line(MARGIN, y + 6, PAGE_W - MARGIN, y + 6)
    inter = inv.place_of_supply_kind == "inter"
    widths = [86, 34, 22, 30, 40, 32, 46, 46, 30, 46]
    headers = ["Product", "HSN", "UQC", "Qty", "Rate", "GST %", "Taxable", "Tax",
               "Cess", "Total"]
    rows = []
    for ln in inv.lines:
        tax = ln.igst_amount if inter else (ln.cgst_amount + ln.sgst_amount)
        # The rate of tax is a mandatory particular, so it is printed per line;
        # a union-territory split reads 9+9 the same way a state split does.
        rate = (_rate_text(ln.igst_rate) if inter else
                f"{_rate_text(ln.cgst_rate)}+{_rate_text(ln.sgst_rate)}")
        rows.append([ln.product_name, ln.hsn or "—", ln.uqc or "—", _plain(ln.qty),
                     _money(ln.unit_price), rate, _money(ln.taxable_value), _money(tax),
                     _money(ln.cess_amount), _money(ln.line_total)])
    y = _table(doc, headers, rows, widths, y)

    y -= 8
    sgst_label = "UTGST" if (not inter and is_union_territory(inv.place_of_supply_state_code)) \
        else "SGST"
    # The totals, the words and the closing block are one unit: if they will not
    # fit here they all move together, so the total is never orphaned from it.
    y = doc.need_page(120, y)
    c = doc.canvas
    y = _totals(c, inv, inv.lines, inter, sgst_label, y)
    return _in_words(c, inv.amount_in_words, y)


def _render_note(doc: Doc, note, kind: str, copy: str, invoice: Invoice | None) -> float:
    """Draw a credit or debit note; returns the free y left after the content."""
    c = doc.canvas
    y = PAGE_H - MARGIN
    y = PAGE_H - MARGIN
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, y, DOC_LABEL[kind])
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(PAGE_W - MARGIN, y, copy)
    y -= 16
    number = note.credit_note_number if kind == "credit_note" else note.debit_note_number
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#444444"))
    c.drawString(MARGIN, y, f"{number}   ·   Financial year {note.financial_year}")
    c.drawRightString(PAGE_W - MARGIN, y, f"Date {note.note_date:%d %b %Y}")
    y -= 16
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 14
    # A note must name the document it corrects, with that document's date.
    against = (f"{invoice.invoice_number} dated {invoice.invoice_date:%d %b %Y}"
               if invoice else "—")
    y = _kv(c, ("Against invoice", against), ("Reason", note.reason), y)
    y = _kv(c, ("Buyer", invoice.buyer_name if invoice else "—"),
               ("GSTIN", (invoice.buyer_gstin if invoice else None) or "—"), y)
    inter = invoice.place_of_supply_kind == "inter" if invoice else False
    pos_code = invoice.place_of_supply_state_code if invoice else ""
    split = _split_label(pos_code, "inter" if inter else "intra")
    if invoice:
        y = _kv(c, ("Place of supply", f"{_state_label(pos_code)} · {split}"),
                   ("Reverse charge", "Yes" if invoice.reverse_charge else "No"), y)
    sgst_label = "UTGST" if (not inter and is_union_territory(pos_code)) else "SGST"
    y -= 6
    c.line(MARGIN, y + 6, PAGE_W - MARGIN, y + 6)
    widths = [110, 40, 60, 60, 60, 60]
    headers = ["Product", "Qty", "Taxable", split, "Cess", "Total"]
    rows = []
    for ln in note.lines:
        tax = ln.igst_amount if inter else (ln.cgst_amount + ln.sgst_amount)
        rows.append([ln.product_name, _plain(ln.qty), _money(ln.taxable_value),
                     _money(tax), _money(ln.cess_amount), _money(ln.line_total)])
    y = _table(doc, headers, rows, widths, y)
    y -= 8
    # As on the invoice, the totals and the words move as one block.
    y = doc.need_page(120, y)
    c = doc.canvas
    y = _totals(c, note, note.lines, inter, sgst_label, y, total_label="Total")
    y = _in_words(c, amount_in_words(note.grand_total), y)
    # No HSN annexure on a note: the note's line snapshot carries no HSN and no
    # rate, so a summary table could only repeat what the model does not store.
    return _close_page(doc, invoice.seller_legal_name if invoice else "", y, terms=False)


NUMBER_FIELD = {"invoice": "invoice_number", "credit_note": "credit_note_number",
                "debit_note": "debit_note_number"}


def _draw_document(surface: Doc, kind: str, doc, copy: str,
                   invoice: Invoice | None) -> None:
    """Draw one document onto a surface. Called twice: measure, then for real."""
    if kind == "invoice":
        inter = doc.place_of_supply_kind == "inter"
        sgst_label = ("UTGST" if (not inter and is_union_territory(doc.place_of_supply_state_code))
                      else "SGST")
        y = _render_invoice(surface, doc, copy)
        _close_page(surface, doc.seller_legal_name, y, annexure=True, inter=inter,
                    sgst_label=sgst_label, lines=doc.lines)
    else:
        y = _render_note(surface, doc, kind, copy, invoice)
        _close_page(surface, invoice.seller_legal_name if invoice else "", y, terms=False)


def build(kind: str, doc, copy: str, printed_by: str, verify_code: str,
          invoice: Invoice | None = None) -> tuple[bytes, str]:
    """Lay a document out and return (pdf bytes, sha256 of those bytes).

    The footer must print "Page n of N", and N is only known once every page
    has been laid out, so the document is measured first and then drawn for real.
    ``verify_code`` is the print reference drawn on every page of it.
    """
    stamp = datetime.now(IST)
    pdf_fonts.register()
    # One watermark, not two: a cancelled document is stamped CANCELLED instead
    # of its copy name, so the two stamps never sit on top of each other.
    watermark = "CANCELLED" if getattr(doc, "status", "") == "cancelled" else copy
    number = getattr(doc, NUMBER_FIELD[kind], "")
    doc_id = f"{kind.upper()}-{number}-{copy}"

    measure = Doc(pdf_fonts.ShapedCanvas(BytesIO(), pagesize=A4), DOC_LABEL[kind], stamp,
                  printed_by, verify_code, watermark, doc_id=doc_id, page_total=None)
    _draw_document(measure, kind, doc, copy, invoice)
    measure.finish_page()

    buffer = BytesIO()
    c = pdf_fonts.ShapedCanvas(buffer, pagesize=A4)
    c.setTitle(f"{number} {copy}")
    c.setAuthor("HERBANOVA Business Control")
    surface = Doc(c, DOC_LABEL[kind], stamp, printed_by, verify_code, watermark,
                  doc_id=doc_id, page_total=measure.total_pages)
    _draw_document(surface, kind, doc, copy, invoice)
    surface.finish_page()
    c.save()
    payload = buffer.getvalue()
    return payload, sha256(payload).hexdigest()


def render(db: Session, kind: str, document_id: int, copy: str, printed_by: str,
           verify_code: str) -> tuple[bytes, str]:
    """Render one document as a PDF. Returns (pdf bytes, sha256 of those bytes).

    ``verify_code`` is the print reference drawn on the page. It must exist
    before rendering, which is why the print-log row is reserved first.
    """
    if copy not in COPIES:
        raise ValueError(f"Unknown copy set {copy!r}")
    model = {"invoice": Invoice, "credit_note": CreditNote, "debit_note": DebitNote}.get(kind)
    if model is None:
        raise ValueError(f"Unknown document type {kind!r}")
    doc = db.get(model, document_id)
    if doc is None:
        raise LookupError(f"{kind} {document_id} not found")
    invoice = db.get(Invoice, doc.invoice_id) if kind != "invoice" else None
    return build(kind, doc, copy, printed_by, verify_code, invoice)


def reserve_print(db: Session, kind: str, document_id: int, document_number: str,
                  copy: str, printed_by: int) -> PrintLog:
    """Reserve the print-log row before rendering, so the page can carry its code.

    The hash is not known until the bytes exist, and the bytes cannot contain a
    hash of themselves. The row is therefore inserted first (giving the code its
    number), the page is rendered with that code, and ``finalise_print`` writes
    the digest afterwards. The placeholder is never a valid digest, so a row that
    somehow escaped without its hash cannot verify as anything.
    """
    log = PrintLog(document_type=kind, document_id=document_id,
                   document_number=document_number, copy_designation=copy,
                   sha256="pending", printed_by=printed_by)
    db.add(log)
    db.flush()
    return log


def finalise_print(db: Session, log: PrintLog, digest: str) -> PrintLog:
    """Store the hash of the exact bytes served. This is what verification checks."""
    log.sha256 = digest
    db.flush()
    return log


def verify_reference(db: Session, value: str) -> PrintLog | None:
    """The print a reference names: a printed code, or a full/short SHA-256."""
    print_id = parse_print_code(value)
    if print_id is not None:
        return db.get(PrintLog, print_id)
    return verify_digest(db, value)


def verify_digest(db: Session, digest: str) -> PrintLog | None:
    """The print-log row carrying this hash, if the document is still unaltered.

    A full 64-character SHA-256 matches exactly. The short hash printed in the
    QR (COR-005) matches by prefix, and only when exactly one print log carries
    it: an ambiguous code reports nothing rather than guessing which document
    the paper was meant to prove.
    """
    value = (digest or "").strip().lower()
    if (not SHORT_HASH_LEN <= len(value) <= 64
            or any(ch not in "0123456789abcdef" for ch in value)):
        return None
    if len(value) == 64:
        return db.scalars(select(PrintLog).where(PrintLog.sha256 == value)
                          .order_by(PrintLog.id.desc())).first()
    rows = db.scalars(select(PrintLog).where(PrintLog.sha256.startswith(value))
                      .order_by(PrintLog.id.desc()).limit(2)).all()
    return rows[0] if len(rows) == 1 else None
