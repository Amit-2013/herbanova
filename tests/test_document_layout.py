"""Layout guarantees for printed documents.

The company line and the designation are one signature block; a reader signs
between them. If they are drawn on different axes the page looks wrong even
though the text is correct, so this checks the geometry, not the wording.
"""
from datetime import datetime
from io import BytesIO

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.services.document_pdf import (MARGIN, PAGE_W, Doc, _close_page)


def _text_centres(pdf: bytes, wanted: set[str]) -> dict[str, float]:
    centres: dict[str, float] = {}

    def visitor(text, cm, tm, font, size):
        value = text.strip()
        if value in wanted:
            centres[value] = tm[4] + stringWidth(value, "Helvetica", 7) / 2

    reader = PdfReader(BytesIO(pdf))
    reader.pages[0].extract_text(visitor_text=visitor)
    return centres


def _render(terms: bool) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    doc = Doc(c, "Invoice", datetime(2026, 11, 1, 10, 0), "check", "", "ORIGINAL")
    _close_page(doc, "Herbanova LLP", 400, terms=terms)
    doc.finish_page()
    c.save()
    return buffer.getvalue()


def test_signature_block_is_centred_on_one_axis():
    expected = PAGE_W - MARGIN - 75
    for terms in (True, False):
        centres = _text_centres(_render(terms),
                                {"For Herbanova LLP", "Authorised signatory"})
        assert set(centres) == {"For Herbanova LLP", "Authorised signatory"}
        for centre in centres.values():
            assert abs(centre - expected) < 1, (terms, centres, expected)
