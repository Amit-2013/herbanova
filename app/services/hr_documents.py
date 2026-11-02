"""Printable HR output: letters from editable templates, ID cards, attendance
sheets and leave statements.

Nothing is recalculated here. Day counts, balances and dates come from the rows
the API already read; this module only lays them out. A value that is not on
record is printed as a dash or reported as a gap, never invented.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Image, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.tax import CompanyProfile
from . import pdf_fonts

IST = timezone(timedelta(hours=5, minutes=30))
DARK = colors.HexColor("#1f3d2f")
ACCENT = colors.HexColor("#2f6b4f")
LIGHT = colors.HexColor("#eef3ec")
GREY = colors.HexColor("#6b7280")
LINE = colors.HexColor("#b8c4be")

PLACEHOLDERS = ("employee_name", "code", "designation", "department", "joining_date",
                "exit_date", "company_name", "company_address", "today")

PLACEHOLDER_LABELS = {
    "employee_name": "employee name", "code": "employee code",
    "designation": "designation", "department": "department",
    "joining_date": "joining date", "exit_date": "exit date",
    "company_name": "company name", "company_address": "company address",
    "today": "today's date",
}

WEEKDAY_INITIALS = ("M", "T", "W", "T", "F", "S", "S")

SHEET_CODES = {
    "present": ("P", "Present"),
    "late": ("L", "Late"),
    "early_departure": ("E", "Early departure"),
    "half_day": ("H", "Half day"),
    "paid_leave": ("LV", "Paid leave"),
    "unpaid_leave": ("LU", "Unpaid leave"),
    "od": ("OD", "On duty"),
    "absent": ("A", "Absent"),
    "weekly_off": ("W", "Weekly off"),
    "holiday": ("HO", "Holiday"),
    "correction_pending": ("C", "Correction pending"),
    None: ("·", "Not recorded"),
}
SHEET_TINTS = {
    "present": DARK, "late": colors.HexColor("#8a5a00"), "early_departure": colors.HexColor("#8a5a00"),
    "half_day": colors.HexColor("#8a5a00"), "paid_leave": colors.HexColor("#1f4f82"),
    "unpaid_leave": colors.HexColor("#1f4f82"), "od": colors.HexColor("#6b4f00"),
    "absent": colors.HexColor("#a4262c"), "weekly_off": GREY, "holiday": GREY,
    "correction_pending": colors.HexColor("#8a5a00"), None: colors.HexColor("#aab2ac"),
}


def company_details(db: Session) -> dict:
    """The letterhead taken from the company profile; blanks stay blank."""
    row = db.scalar(select(CompanyProfile))
    if row is None:
        return {"name": "HERBANOVA", "address": "", "phone": "", "email": ""}
    parts = [row.address_line1, row.address_line2, row.city, row.pincode]
    return {"name": (row.trade_name or row.legal_name or "HERBANOVA").strip(),
            "address": ", ".join(p for p in parts if p),
            "phone": row.phone or "", "email": row.email or ""}


def long_date(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d %B %Y")


def _stamp(value: datetime | None = None) -> str:
    moment = (value or datetime.now(IST)).astimezone(IST) if (value and value.tzinfo) else \
        (value or datetime.now(IST))
    return moment.strftime("%Y-%m-%d %H:%M IST")


def _styles():
    pdf_fonts.register()
    base = getSampleStyleSheet()
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=8, leading=10,
                                textColor=GREY, fontName=pdf_fonts.FONT, shaping=1),
        "tiny": ParagraphStyle("tiny", parent=base["Normal"], fontSize=6.5, leading=8,
                               textColor=GREY, fontName=pdf_fonts.FONT, shaping=1),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=10.5, leading=16,
                               spaceAfter=6, fontName=pdf_fonts.FONT, shaping=1),
        "subject": ParagraphStyle("subject", parent=base["Normal"], fontSize=11, leading=15,
                                  fontName=pdf_fonts.FONT_BOLD, shaping=1,
                                  spaceBefore=4, spaceAfter=8),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8, leading=10,
                               fontName=pdf_fonts.FONT, shaping=1),
        "cellhead": ParagraphStyle("cellhead", parent=base["Normal"], fontSize=8, leading=10,
                                   fontName=pdf_fonts.FONT_BOLD, shaping=1),
        "sheet": ParagraphStyle("sheet", parent=base["Normal"], fontSize=5.5, leading=6.5,
                                fontName=pdf_fonts.FONT, shaping=1),
        "sheethead": ParagraphStyle("sheethead", parent=base["Normal"], fontSize=5.5,
                                    leading=6.5, fontName=pdf_fonts.FONT_BOLD, shaping=1),
    }


def _footer(note: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.3)
        canvas.line(16 * mm, 12 * mm, doc.pagesize[0] - 16 * mm, 12 * mm)
        canvas.setFont(pdf_fonts.FONT, 6.5)
        canvas.setFillColor(GREY)
        canvas.drawString(16 * mm, 8 * mm, note)
        canvas.drawRightString(doc.pagesize[0] - 16 * mm, 8 * mm,
                               f"Page {canvas.getPageNumber()}")
        canvas.restoreState()
    return draw


def _letterhead(company: dict, styles, width: float) -> list:
    lines = [Paragraph(escape(company["name"]), ParagraphStyle(
        "co", parent=styles["base"]["Title"], fontSize=16, leading=20, textColor=DARK,
        fontName=pdf_fonts.FONT_BOLD, shaping=1, spaceAfter=2))]
    contact = " · ".join(p for p in (company["address"], company["phone"],
                                     company["email"]) if p)
    if contact:
        lines.append(Paragraph(escape(contact), styles["small"]))
    lines.append(HRFlowable(width=width, thickness=0.8, color=ACCENT, spaceBefore=4,
                            spaceAfter=10))
    return lines


def _set(values: dict) -> dict:
    out = dict(values)
    for key, value in out.items():
        if isinstance(value, (date, datetime)):
            out[key] = long_date(value)
    return out


def _missing_placeholders(body: str, values: dict) -> list[str]:
    """Placeholders that need a date the employee record does not hold."""
    return [token for token in ("joining_date", "exit_date")
            if "{" + token + "}" in body and values.get(token) is None]


def render_letter(template, employee, company: dict, *, exit_date=None,
                  today: date | None = None) -> bytes:
    """Fill an editable template for one employee.

    Raises ValueError when the body needs a date the employee record does not
    hold, so the caller can answer with a gap instead of a blank line.
    """
    today = today or date.today()
    values = {
        "employee_name": employee.full_name,
        "code": employee.code,
        "designation": employee.designation or "—",
        "department": employee.department or "—",
        "joining_date": employee.joining_date,
        "exit_date": exit_date if exit_date is not None else employee.date_of_exit,
        "company_name": company["name"],
        "company_address": company["address"] or "—",
        "today": today,
    }
    missing = _missing_placeholders(template.body, values)
    if missing:
        names = " and ".join(PLACEHOLDER_LABELS.get(m, m) for m in missing)
        raise ValueError(f"Record the employee's {names} before generating this letter")
    filled = _set(values)
    text = re.sub(r"\{([a-z_]+)\}",
                  lambda m: str(filled[m.group(1)]) if m.group(1) in filled else m.group(0),
                  template.body)
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=16 * mm, bottomMargin=20 * mm,
                            title=f"{template.name} — {employee.full_name}")
    width = doc.width
    story = _letterhead(company, styles, width)
    meta = Table([[Paragraph(escape(f"Ref: {template.code}/{employee.code}/{today.year}"),
                             styles["small"]),
                   Paragraph(escape(f"Date: {long_date(today)}"),
                             ParagraphStyle("right", parent=styles["small"], alignment=2))]],
                 colWidths=[width / 2, width / 2])
    story += [meta, Spacer(1, 4 * mm),
              Paragraph(escape(template.name), styles["subject"])]
    for block in re.split(r"\n\s*\n", text):
        if block.strip():
            story.append(Paragraph(escape(block.strip()).replace("\n", "<br/>"),
                                   styles["body"]))
    story += [Spacer(1, 8 * mm),
              Paragraph("For <b>" + escape(company["name"]) + "</b>",
                        ParagraphStyle("sig", parent=styles["body"], alignment=2)),
              Spacer(1, 14 * mm),
              Paragraph("Authorised signatory",
                        ParagraphStyle("sigline", parent=styles["body"], alignment=2)),
              Spacer(1, 8 * mm),
              Paragraph(escape(f"Generated from the HR system on {_stamp()}. This letter "
                               "is a draft until signed and sealed."), styles["tiny"])]
    doc.build(story, onFirstPage=_footer("Herbanova HR — employee letter"),
              onLaterPages=_footer("Herbanova HR — employee letter"))
    return buffer.getvalue()


def _photo_cell(photo_file, styles):
    if photo_file is not None:
        try:
            from reportlab.lib.utils import ImageReader
            ImageReader(str(photo_file))
            image = Image(str(photo_file), width=24 * mm, height=30 * mm)
            image.hAlign = "CENTER"
            inner = [image]
        except Exception:
            inner = [Paragraph("PHOTO", styles["tiny"])]
    else:
        inner = [Paragraph("NO PHOTO", styles["tiny"])]
    box = Table([[inner]], colWidths=[26 * mm], rowHeights=[32 * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return box


def _card_front(employee, company, branch: str, office: str, photo_file, styles) -> Table:
    white = ParagraphStyle("white", parent=styles["small"], textColor=colors.white,
                           fontName=pdf_fonts.FONT_BOLD, fontSize=7, leading=9, shaping=1)
    name = ParagraphStyle("cardname", parent=styles["base"]["Normal"], fontSize=15,
                          leading=18, fontName=pdf_fonts.FONT_BOLD, textColor=DARK,
                          shaping=1)
    line = ParagraphStyle("cardline", parent=styles["base"]["Normal"], fontSize=8.5,
                          leading=11, textColor=colors.HexColor("#25332c"),
                          fontName=pdf_fonts.FONT, shaping=1)
    left = [Paragraph(escape(employee.full_name), name),
            Paragraph(escape(" · ".join(p for p in (employee.code,
                                                    employee.designation) if p)), line),
            Paragraph(escape(employee.department or "Department not recorded"), line),
            Paragraph(escape(" · ".join(p for p in (branch, office) if p) or
                            "Branch not recorded"), styles["tiny"]),
            Paragraph(escape("Joined " + long_date(employee.joining_date)), styles["tiny"])]
    tag = ParagraphStyle("idtag", parent=white, alignment=2)
    head = Table([[Paragraph(escape(company["name"]), white), Paragraph("EMPLOYEE ID", tag)]],
                 colWidths=[94 * mm, 32 * mm])
    head.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    front = Table([
        [head, ""],
        [left, _photo_cell(photo_file, styles)],
        [Paragraph("This card is company property and is not transferable.",
                   ParagraphStyle("foot", parent=white, fontSize=6.5)), ""],
    ], colWidths=[104 * mm, 32 * mm], rowHeights=[9 * mm, 46 * mm, 7 * mm])
    front.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)), ("SPAN", (0, 2), (1, 2)),
        ("BACKGROUND", (0, 0), (1, 0), DARK),
        ("BACKGROUND", (0, 2), (1, 2), ACCENT),
        ("BACKGROUND", (0, 1), (-1, 1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (1, 1), "CENTER"),
        ("LEFTPADDING", (0, 1), (0, 1), 8),
    ]))
    return front


def _card_back(employee, company, styles) -> Table:
    label = ParagraphStyle("bl", parent=styles["small"], fontSize=7)
    value = ParagraphStyle("bv", parent=styles["base"]["Normal"], fontSize=8.5, leading=11,
                           fontName=pdf_fonts.FONT, shaping=1)
    emergency = " · ".join(p for p in (employee.emergency_name, employee.emergency_phone) if p)
    back = Table([
        [Paragraph("IF FOUND, PLEASE RETURN TO", ParagraphStyle(
            "bh", parent=styles["cellhead"], textColor=colors.white, fontSize=7))],
        [Paragraph(escape(company["name"]) + "<br/>" +
                   escape(" · ".join(p for p in (company["address"], company["phone"]) if p)
                          or "Address not recorded"), value)],
        [Paragraph(escape(f"Emergency contact: {emergency or 'not recorded'}"), label)],
        [Paragraph(escape(f"Date of birth: {long_date(employee.date_of_birth)} · "
                          f"Phone: {employee.phone or '—'}"), label)],
        [Paragraph("Not valid without the company seal. Report a lost card to Human Resources.",
                   styles["tiny"])],
    ], colWidths=[136 * mm], rowHeights=[8 * mm, 18 * mm, 11 * mm, 9 * mm, 8 * mm])
    back.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), DARK),
        ("BACKGROUND", (0, 4), (0, 4), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 1), (-1, -1), 8),
    ]))
    return back


def build_id_card(employee, company: dict, *, branch: str = "", office: str = "",
                  photo_file=None, generated_on: date | None = None) -> bytes:
    """Two credit-card size faces on one A4 sheet, cut marks kept outside the cards."""
    styles = _styles()
    day = generated_on or date.today()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=16 * mm, bottomMargin=20 * mm,
                            title=f"ID card — {employee.full_name}")
    story = [Paragraph(escape(company["name"]), ParagraphStyle(
                 "co", parent=styles["base"]["Title"], fontSize=14, textColor=DARK,
                 fontName=pdf_fonts.FONT_BOLD, shaping=1)),
             Paragraph(escape(f"Employee identity card · {employee.full_name} "
                              f"({employee.code}) · generated {long_date(day)}"),
                       styles["small"]),
             Spacer(1, 6 * mm),
             Paragraph("Front", styles["small"]), Spacer(1, 2 * mm),
             _card_front(employee, company, branch, office, photo_file, styles),
             Spacer(1, 8 * mm),
             HRFlowable(width=doc.width, thickness=0.4, color=LINE, dash=(2, 2)),
             Spacer(1, 8 * mm),
             Paragraph("Back", styles["small"]), Spacer(1, 2 * mm),
             _card_back(employee, company, styles),
             Spacer(1, 6 * mm),
             Paragraph("Cut along the dashed line. Bank, PAN and salary details are "
                       "deliberately not printed on this card.", styles["tiny"])]
    doc.build(story, onFirstPage=_footer("Herbanova HR — identity card"),
              onLaterPages=_footer("Herbanova HR — identity card"))
    return buffer.getvalue()


def _day_number(value) -> int:
    if isinstance(value, str):
        return int(value[8:10])
    return value.day


def build_attendance_sheet(data: dict, company: dict, *, department: str | None = None,
                           generated_on: date | None = None) -> bytes:
    """A month grid laid out for printing; codes match the on-screen legend."""
    styles = _styles()
    day = generated_on or date.today()
    days = data["days"]
    month_name = days[0].strftime("%B %Y") if days else f"{data['year']}-{data['month']:02d}"
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=9 * mm,
                            rightMargin=9 * mm, topMargin=10 * mm, bottomMargin=14 * mm,
                            title=f"Attendance sheet {month_name}")
    scope = f" · department: {department}" if department else " · all departments"
    story = [Paragraph(escape(f"{company['name']} — attendance sheet {month_name}"),
                       ParagraphStyle("t", parent=styles["base"]["Title"], fontSize=13,
                                      leading=16, textColor=DARK,
                                      fontName=pdf_fonts.FONT_BOLD, shaping=1)),
             Paragraph(escape(f"Generated {long_date(day)}{scope} · "
                              f"{len(data['employees'])} employee(s)"), styles["small"]),
             Spacer(1, 3 * mm)]
    head = [Paragraph(escape(x), styles["sheethead"])
            for x in ("Code", "Employee")] + \
           [Paragraph(str(_day_number(d)), styles["sheethead"]) for d in days] + \
           [Paragraph(escape(x), styles["sheethead"])
            for x in ("P", "Lv", "A", "—")]
    initials = [Paragraph("", styles["sheet"]) for _ in range(2)] + \
               [Paragraph(WEEKDAY_INITIALS[d.weekday()], styles["sheet"]) for d in days] + \
               [Paragraph("", styles["sheet"]) for _ in range(4)]
    rows = [head, initials]
    styles_cmds = [
        ("BACKGROUND", (0, 0), (-1, 1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.2, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 2), (-1, -1), "CENTER"),
    ]
    for index, weekday in enumerate(data.get("weekdays", [])):
        if weekday >= 5:
            styles_cmds.append(("BACKGROUND", (2 + index, 2), (2 + index, -1),
                                colors.HexColor("#f3f5f4")))
    for row_index, emp in enumerate(data["employees"], start=2):
        by_day = {_day_number(c["date"]): c for c in emp["calendar"]}
        cells = [Paragraph(escape(emp["code"]), styles["sheet"]),
                 Paragraph(escape(emp["name"]), styles["sheet"])]
        for number, value in enumerate(days, start=1):
            item = by_day.get(_day_number(value), {"status": None})
            code, _label = SHEET_CODES.get(item.get("status"), ("?", "Unknown"))
            cells.append(Paragraph(escape(code), styles["sheet"]))
            styles_cmds.append(("TEXTCOLOR", (2 + number - 1, row_index),
                                (2 + number - 1, row_index),
                                SHEET_TINTS.get(item.get("status"), GREY)))
        summary = emp["summary"]
        cells += [Paragraph(str(summary["present_days"]), styles["sheet"]),
                  Paragraph(str(summary["leave_days"]), styles["sheet"]),
                  Paragraph(str(summary["absent_days"]), styles["sheet"]),
                  Paragraph(str(summary["missing_days"]), styles["sheet"])]
        rows.append(cells)
    totals = data["totals"]
    rows.append([Paragraph("", styles["sheet"]),
                 Paragraph(f"All {len(data['employees'])} employee(s)", styles["sheethead"])] +
                [Paragraph("", styles["sheet"]) for _ in days] +
                [Paragraph(str(totals["present_days"]), styles["sheethead"]),
                 Paragraph(str(totals["leave_days"]), styles["sheethead"]),
                 Paragraph(str(totals["absent_days"]), styles["sheethead"]),
                 Paragraph(str(totals["missing_days"]), styles["sheethead"])])
    widths = [18 * mm, 42 * mm] + [5.55 * mm] * len(days) + [11 * mm] * 4
    table = Table(rows, colWidths=widths, repeatRows=2)
    table.setStyle(TableStyle(styles_cmds))
    story += [table, Spacer(1, 3 * mm),
              Paragraph(escape("P present · L late · E early departure · H half day · "
                               "LV paid leave · LU unpaid leave · OD on duty · A absent · "
                               "W weekly off · HO holiday · C correction pending · "
                               "· not recorded. Sat/Sun shading is a visual guide only; "
                               "the employee's shift decides the weekly off."),
                        styles["tiny"]),
              Paragraph(escape(f"{totals['missing_days']} employee-day(s) have no "
                               "attendance row and are shown as gaps, not absences."),
                        styles["tiny"])]
    doc.build(story, onFirstPage=_footer("Herbanova HR — attendance sheet"),
              onLaterPages=_footer("Herbanova HR — attendance sheet"))
    return buffer.getvalue()


def build_leave_statement(employee, year: int, balances: list[dict], applications: list[dict],
                          company: dict, *, gaps: list[str] | None = None,
                          generated_on: date | None = None) -> bytes:
    """A per-employee annual statement built from the stored balances and applications."""
    styles = _styles()
    day = generated_on or date.today()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title=f"Leave statement {employee.code} {year}")
    width = doc.width
    story = _letterhead(company, styles, width)
    story += [Paragraph(f"Leave statement — {year}",
                        ParagraphStyle("t", parent=styles["base"]["Title"], fontSize=14,
                                       leading=18, textColor=DARK,
                                       fontName=pdf_fonts.FONT_BOLD, shaping=1)),
              Paragraph(escape(f"{employee.full_name} ({employee.code}) · "
                               f"{employee.designation or 'Designation not recorded'} · "
                               f"{employee.department or 'Department not recorded'} · "
                               f"generated {long_date(day)}"), styles["small"]),
              Spacer(1, 5 * mm)]
    info = [["Joined on", long_date(employee.joining_date), "Employment type",
             employee.employment_type or "—"]]
    info_table = Table([[Paragraph(escape(str(c)), styles["cellhead"]) if i % 2 == 0
                         else Paragraph(escape(str(c)), styles["cell"]) for i, c in enumerate(row)]
                        for row in info], colWidths=[28 * mm, 55 * mm, 32 * mm, 55 * mm])
    info_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.2, LINE),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT), ("BACKGROUND", (2, 0), (2, -1), LIGHT)]))
    story += [info_table, Spacer(1, 5 * mm),
              Paragraph("Balances", ParagraphStyle("h", parent=styles["subject"],
                                                    fontSize=10, spaceBefore=0))]
    if balances:
        data = [[Paragraph(escape(x), styles["cellhead"])
                 for x in ("Leave type", "Entitled", "Carried", "Used", "Pending",
                           "Available")]]
        for row in balances:
            data.append([Paragraph(escape(str(row["name"])), styles["cell"])] +
                        [Paragraph(escape(str(row[key])), styles["cell"])
                         for key in ("entitled", "carried", "used", "pending", "available")])
        table = Table(data, colWidths=[60 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm],
                      repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, LINE),
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story.append(table)
    else:
        story.append(Paragraph("No data yet: no leave balances have been set for this year.",
                               styles["body"]))
    story += [Spacer(1, 6 * mm),
              Paragraph("Applications", ParagraphStyle("h2", parent=styles["subject"],
                                                        fontSize=10, spaceBefore=0))]
    if applications:
        data = [[Paragraph(escape(x), styles["cellhead"])
                 for x in ("From", "To", "Type", "Days", "Portion", "Status")]]
        for row in applications:
            data.append([Paragraph(escape(str(row["date_from"])), styles["cell"]),
                         Paragraph(escape(str(row["date_to"])), styles["cell"]),
                         Paragraph(escape(str(row["leave_type"])), styles["cell"]),
                         Paragraph(escape(str(row["days"])), styles["cell"]),
                         Paragraph(escape(str(row["portion"]).replace("_", " ")), styles["cell"]),
                         Paragraph(escape(str(row["status"])), styles["cell"])])
        table = Table(data, colWidths=[26 * mm, 26 * mm, 46 * mm, 16 * mm, 34 * mm, 22 * mm],
                      repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, LINE),
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT)]))
        story.append(table)
    else:
        story.append(Paragraph(f"No leave applications have been recorded in {year}.",
                               styles["body"]))
    approved = sum((Decimal(str(a["days"])) for a in applications
                    if a["status"] == "approved"), Decimal("0"))
    pending = sum((Decimal(str(a["days"])) for a in applications
                   if a["status"] == "pending"), Decimal("0"))
    story += [Spacer(1, 5 * mm),
              Paragraph(escape(f"Approved days in {year}: {approved} · pending days: "
                               f"{pending}. Pending applications are held in Pending and are "
                               "not deducted until approved. The figures above are the "
                               "stored balances, not a recalculation."), styles["small"])]
    for gap in gaps or []:
        story.append(Paragraph(escape("Gap: " + gap), styles["small"]))
    doc.build(story, onFirstPage=_footer("Herbanova HR — leave statement"),
              onLaterPages=_footer("Herbanova HR — leave statement"))
    return buffer.getvalue()
