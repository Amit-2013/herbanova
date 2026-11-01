"""CSV and Excel output for reports.

  CSV   one table (the report's main one unless ?table= says otherwise), a TOTAL row, then a
        short footer: who/when, whether the checks agreed, and the report's limitations.
        UTF-8 with a BOM so Excel shows rupee signs and names correctly.
  XLSX  every table on its own sheet, plus 'Reconciliation' and 'Notes' sheets.

User-typed text (lead names, companies, distributor names) can start with = + - @, which
spreadsheets run as formulas. CSV text is therefore prefixed with an apostrophe when it
looks like a formula, and Excel text cells are written as strings, never as formulas.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

IST = timezone(timedelta(hours=5, minutes=30))       # India has no daylight saving
# A register with no records must say so in the file itself; a header-only or
# completely blank sheet looks like a failed export.
EMPTY_NOTE = "No records for this period."
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER_LIKE = re.compile(r"^[+-]?[\d\s().,-]+$")    # plain numbers / phone-style text are not a risk
NUM_FMT = {"money": "#,##0.00", "qty": "#,##0.###", "int": "#,##0", "pct": "0.0", "date": "yyyy-mm-dd"}
UNIT_FMT = {"money": "#,##0.00", "units": "#,##0.###", "count": "#,##0"}


def stamp() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


def safe_text(v) -> str:
    s = "" if v is None else str(v)
    if s and s[0] in _FORMULA_START and not _NUMBER_LIKE.match(s):
        return "'" + s
    return s


def fmt(v, typ: str) -> str:
    if v is None:
        return ""
    if typ == "money":
        return f"{Decimal(str(v)):.2f}"
    if typ == "qty":
        d = Decimal(str(v))
        return format(d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize(), "f")
    if typ == "pct":
        return f"{Decimal(str(v)):.1f}"
    if typ == "int":
        return str(int(Decimal(str(v))))
    if typ == "date":
        return v.isoformat() if isinstance(v, date) else str(v)
    return safe_text(v)


def _period_text(rep) -> str:
    if rep["kind"] == "period":
        a, b = rep["period_from"], rep["period_to"]
        return "All dates" if not a and not b else f"{a.isoformat() if a else 'start'} to {b.isoformat() if b else 'today'}"
    return f"As at {rep['as_at'].isoformat()}"


def _status(rep) -> str:
    bad = [c["name"] for c in rep["checks"] if not c["ok"]]
    return (f"All {len(rep['checks'])} checks agree with the records" if not bad
            else "DOES NOT RECONCILE: " + "; ".join(bad))


def table_of(rep, key: str):
    return next((t for t in rep["tables"] if t["key"] == key), None)


def to_csv(rep, table_key: str, who: str) -> bytes:
    t = table_of(rep, table_key)
    cols = t["columns"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    if cols:
        w.writerow([c["label"] for c in cols])
    if t["rows"]:
        for r in t["rows"]:
            w.writerow([fmt(r[c["key"]], c["type"]) for c in cols])
        if t["totals"]:
            # A report may total only some columns (stock totals quantity, not SKU);
            # the other cells are left blank instead of raising KeyError.
            w.writerow([fmt(t["totals"].get(c["key"]), c["type"]) for c in cols])
    else:
        w.writerow([EMPTY_NOTE] + [""] * max(0, len(cols) - 1))
    w.writerow([])
    for k, v in (("Report", rep["title"]), ("Table", t["title"]), ("Period", _period_text(rep)),
                 ("Generated", stamp()), ("Prepared by", who), ("Reconciliation", _status(rep))):
        w.writerow([k, v])
    for lim in rep["limitations"]:
        w.writerow(["Note", lim])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def _put(ws, row, col, v, typ, bold=False):
    if v is None or v == "":
        return
    c = ws.cell(row=row, column=col)
    if typ in ("money", "qty", "int", "pct"):
        try:
            number = Decimal(str(v))
        except (ArithmeticError, ValueError):
            # A column typed numeric should never hold prose; if it does, keep
            # the text rather than losing the cell (and never run it as a formula).
            c.value = str(v)
            c.data_type = "s"
        else:
            c.value = number
            c.number_format = NUM_FMT[typ]
    elif typ == "date" and isinstance(v, date):
        c.value = v
        c.number_format = NUM_FMT["date"]
    else:
        c.value = str(v)
        c.data_type = "s"            # text stays text, even if it starts with "="
    if bold:
        c.font = Font(bold=True)


def _sheet_name(wb, title: str) -> str:
    base = re.sub(r"[\[\]\*\?/\\:]", "", title)[:28] or "Sheet"
    name, n = base, 2
    while name in wb.sheetnames:
        name, n = f"{base} {n}", n + 1
    return name


def to_xlsx(rep, who: str) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for t in rep["tables"]:
        ws = wb.create_sheet(_sheet_name(wb, t["title"]))
        for j, c in enumerate(t["columns"], 1):
            h = ws.cell(row=1, column=j, value=c["label"])
            h.font = Font(bold=True)
            h.alignment = Alignment(wrap_text=True, vertical="top")
            ws.column_dimensions[get_column_letter(j)].width = max(12, min(34, len(c["label"]) + 4))
        cols = t["columns"]
        if t["rows"]:
            for i, r in enumerate(t["rows"], 2):
                for j, c in enumerate(cols, 1):
                    _put(ws, i, j, r[c["key"]], c["type"])
            if t["totals"]:
                i = len(t["rows"]) + 2
                for j, c in enumerate(cols, 1):
                    _put(ws, i, j, t["totals"].get(c["key"]), c["type"], bold=True)
        else:
            row = 2 if cols else 1
            note = ws.cell(row=row, column=1, value=EMPTY_NOTE)
            note.font = Font(italic=True)
            note.data_type = "s"
            if len(cols) > 1:
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(cols))
        if cols:
            ws.freeze_panes = "A2"
    ws = wb.create_sheet("Reconciliation")
    for j, h in enumerate(["Check", "Report figure from", "Report figure", "Records figure from", "Records figure", "Result"], 1):
        ws.cell(row=1, column=j, value=h).font = Font(bold=True)
    for i, c in enumerate(rep["checks"], 2):
        for j, (v, kind) in enumerate([(c["name"], "t"), (c["report_label"], "t"), (c["report_value"], "n"),
                                       (c["record_label"], "t"), (c["record_value"], "n"),
                                       ("Agrees" if c["ok"] else "DIFFERS", "t")], 1):
            cell = ws.cell(row=i, column=j)
            if kind == "n":
                cell.value = Decimal(str(v))
                cell.number_format = UNIT_FMT.get(c["unit"], "#,##0")
            else:
                cell.value = str(v)
                cell.data_type = "s"
        if not c["ok"]:
            ws.cell(row=i, column=6).font = Font(bold=True, color="B3261E")
    for col, wdt in zip("ABCDEF", (52, 30, 16, 40, 16, 12)):
        ws.column_dimensions[col].width = wdt
    ws = wb.create_sheet("Notes")
    rows = [("Report", rep["title"]), ("Period", _period_text(rep)), ("Generated", stamp()), ("Prepared by", who),
            ("Reconciliation", _status(rep)), ("", "")] + [("Limitation", x) for x in rep["limitations"]]
    for i, (k, v) in enumerate(rows, 1):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        c = ws.cell(row=i, column=2)
        c.value = str(v)
        c.data_type = "s"
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 110
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()