"""Salary slip PDF, built from a stored payroll entry (not recalculated here)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

IST = timezone(timedelta(hours=5, minutes=30))


def _m(v) -> str:
    return f"{Decimal(v or 0):,.2f}"


def build_slip(entry, employee, period) -> bytes:
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Salary slip {employee.code} {period.year}-{period.month:02d}")
    story = [Paragraph("HERBANOVA — Salary slip", styles["Title"]),
             Paragraph(escape(f"{employee.full_name} ({employee.code}) · "
                              f"{period.year}-{period.month:02d} · generated "
                              f"{datetime.now(IST):%Y-%m-%d %H:%M IST}"), styles["Normal"]),
             Spacer(1, 5 * mm)]
    info = [["Department", employee.department or "—", "Designation", employee.designation or "—"],
            ["Working days", str(entry.working_days), "Payable days", str(entry.payable_days)],
            ["Present", str(entry.present_days), "Paid leave", str(entry.paid_leave_days)],
            ["LOP", str(entry.lop_days), "Status", entry.status.replace("_", " ").title()]]
    t = Table(info, colWidths=[35 * mm, 50 * mm, 35 * mm, 50 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3ec")),
                           ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef3ec"))]))
    story += [t, Spacer(1, 5 * mm)]
    rows = [["Component", "Type", "Basis", "Amount (₹)"]]
    for line in entry.lines:
        rows.append([line.name, line.kind.title(), line.basis or "", _m(line.amount)])
    rows.append(["Gross earnings", "", "", _m(entry.gross)])
    rows.append(["Total deductions", "", "", _m(entry.deductions)])
    rows.append(["Net payable", "", "", _m(entry.net)])
    t2 = Table(rows, colWidths=[62 * mm, 25 * mm, 55 * mm, 28 * mm], repeatRows=1)
    t2.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8efe6")),
                            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef3ec")),
                            ("ALIGN", (3, 1), (3, -1), "RIGHT")]))
    story += [t2, Spacer(1, 5 * mm),
              Paragraph("This slip is built from the stored payroll entry. Statutory rates are the "
                        "configured values at the time payroll was prepared; it is not a tax "
                        "return.", styles["BodyText"])]
    if entry.note:
        story.append(Paragraph(escape("Note: " + entry.note), styles["BodyText"]))
    doc.build(story)
    return buf.getvalue()
