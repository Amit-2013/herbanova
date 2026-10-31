"""PDF output for a report table.

Uses the same report shape as the CSV/XLSX exporters so any report can be
printed. Long values are wrapped; the reconciliation result is printed on the
first page rather than hidden.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle)

IST = timezone(timedelta(hours=5, minutes=30))


def _text(v, typ):
    if v is None:
        return ""
    if typ == "money":
        return f"{Decimal(v):,.2f}"
    if typ == "qty":
        d = Decimal(v)
        return f"{d.normalize():f}" if d != d.to_integral() else f"{int(d):,}"
    if typ == "pct":
        return f"{Decimal(v):.1f}%"
    if typ == "date":
        return v.isoformat() if isinstance(v, date) else str(v)
    return str(v)


def to_pdf(rep, table_key: str, who: str) -> bytes:
    table = next((t for t in rep["tables"] if t["key"] == table_key), rep["tables"][0])
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm,
                            rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                            title=rep["title"])
    story = [Paragraph(escape(rep["title"]), styles["Title"]),
             Paragraph(escape(f"{table['title']} · generated {datetime.now(IST):%Y-%m-%d %H:%M IST} by {who}"),
                       styles["Normal"]), Spacer(1, 4 * mm)]
    if rep["kind"] == "period":
        span = f"{rep['period_from'] or 'start'} to {rep['period_to'] or 'today'}"
    else:
        span = f"as at {rep['as_at']}"
    story.append(Paragraph(escape(f"Period: {span}"), styles["Normal"]))
    bad = [c["name"] for c in rep["checks"] if not c["ok"]]
    story.append(Paragraph(escape("All checks agree with the records" if not bad
                                  else "DOES NOT RECONCILE: " + "; ".join(bad)),
                           styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    cols = table["columns"]
    if not cols:
        # An empty register has no rows to discover columns from; a table with
        # zero columns is invalid for ReportLab, so print the fact instead.
        story.append(Paragraph("No records for this period.", styles["Normal"]))
    else:
        data = [[Paragraph(escape(c["label"]), styles["BodyText"]) for c in cols]]
        for row in table["rows"]:
            data.append([Paragraph(escape(_text(row.get(c["key"]), c["type"])), styles["BodyText"])
                         for c in cols])
        if table.get("totals"):
            data.append([Paragraph(escape("Total" if i == 0 else
                                          _text(table["totals"].get(c["key"]), c["type"])),
                                   styles["BodyText"]) for i, c in enumerate(cols)])
        width = landscape(A4)[0] - 20 * mm
        col_widths = [width / len(cols)] * len(cols)
        pdf_table = LongTable(data, colWidths=col_widths, repeatRows=1)
        pdf_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8efe6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(pdf_table)
    story.append(Spacer(1, 4 * mm))
    for limitation in rep["limitations"]:
        story.append(Paragraph(escape("• " + limitation), styles["BodyText"]))
    doc.build(story)
    return buf.getvalue()
