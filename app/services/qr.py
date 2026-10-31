"""QR codes and verification references for printed documents (Phase 5, COR-005, D-15).

A printed page must carry a code that a reader can actually scan and that the
system can resolve back to the print it came from. The screen used to paint a
21x21 checkerboard and label it a QR code, which encodes nothing; this module
produces real symbols.

The symbol printed on a page carries the **print code** — ``PRT-000123``,
derived from the print-log row. It is known before the PDF is drawn, which is
what lets the symbol appear *on* the page: a QR cannot contain the hash of the
file that contains it, so the paper carries a reference that resolves to the log
entry, and the log entry holds the SHA-256 of the exact bytes served. A typed
check also accepts that hash in full or as its first 16 characters.

Encoding uses ReportLab's QR encoder, which the project already depends on for
the PDFs. The matrix is rendered here as a plain grid instead of through
ReportLab's SVG backend so the output is simple to size, cache, draw into a PDF
and read back in a test.
"""
import re

from reportlab.graphics.barcode.qr import QrCodeWidget

# The length of the short hash a scan or a typed code may also be checked against.
SHORT_HASH_LEN = 16

# The reference printed on the page: PRT- followed by the print-log row number.
PRINT_CODE_PREFIX = "PRT-"
_PRINT_CODE = re.compile(r"^PRT-(\d{1,9})$")

QR_SCALE = 6      # pixels per module in the served SVG
QR_QUIET = 4      # quiet-zone modules the standard requires on every side


def print_code(print_id: int) -> str:
    """The reference printed on a page, resolvable to its print-log row."""
    return f"{PRINT_CODE_PREFIX}{int(print_id):06d}"


def parse_print_code(value: str) -> int | None:
    """The print-log row a printed reference names, or None if it is not one."""
    match = _PRINT_CODE.match((value or "").strip().upper())
    return int(match.group(1)) if match else None


def matrix(payload: str) -> list[list[bool]]:
    """The modules of the symbol: True is dark. Row-major, square.

    ReportLab builds the module map lazily — the widget only encodes when it is
    drawn — so the code is built here before anything is read from it. Without
    this the grid would be all light and the symbol would be blank.
    """
    code = QrCodeWidget(payload, barWidth=1, barHeight=1).qr
    if code.modules is None:
        code.make()
    size = code.moduleCount
    return [[bool(code.isDark(row, col)) for col in range(size)] for row in range(size)]


def svg(payload: str, scale: int = QR_SCALE, quiet: int = QR_QUIET) -> str:
    """The symbol as an SVG document: white ground, black modules, integer grid.

    One rectangle per dark module at whole-number coordinates, so the output is
    crisp at any size and can be read back from the response in a test.
    """
    grid = matrix(payload)
    side = len(grid) + 2 * quiet
    rects = "".join(
        f'<rect x="{col + quiet}" y="{row + quiet}" width="1" height="1"/>'
        for row, line in enumerate(grid) for col, dark in enumerate(line) if dark
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{side * scale}" height="{side * scale}" '
        f'viewBox="0 0 {side} {side}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR code carrying the print verification code">'
        f'<rect width="{side}" height="{side}" fill="#ffffff"/>'
        f'<g fill="#000000">{rects}</g></svg>'
    )
