"""The HR Report Pack sent on a schedule to the MD and Administrator.

The pack reuses the HR report definitions, so the email, its attachments and
the screens cannot drift. It deliberately carries no salary amount: pay is
confidential and stays behind the Department cost report in the application.

Email is delivered through the existing scheduled-reports worker, which
already runs in test mode until the Administrator approves a live recipient
list.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.core import ApprovalRequest
from . import hr_notify, hr_reports, pdf_fonts

LABEL = "HR Report Pack"
GREEN = "#1F6B4A"
INK = "#16211B"
MUTED = "#56635B"
LINE = "#E2E8E4"
TILE = "#F7FAF8"
IST = timezone(timedelta(hours=5, minutes=30))
ATTACHMENT_REPORTS = ("headcount", "attendance-summary")
ROW_LIMIT = 15


def _e(value) -> str:
    return escape("" if value is None else str(value))


def _count(value) -> str:
    return str(value if value is not None else "No data yet")


def _pending(db: Session, today: date) -> tuple[int, int]:
    rows = db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.status == "pending",
        ApprovalRequest.record_type.like("hr_%"))).all()
    stale = 0
    for row in rows:
        requested = row.requested_at
        if requested is None:
            continue
        local = requested.astimezone(IST) if requested.tzinfo else requested
        if (today - local.date()).days > 3:
            stale += 1
    return len(rows), stale


def build(db: Session, start: date, end: date, *, base_url: str | None = None,
          generated_at: datetime | None = None) -> dict:
    from . import report_packs

    built = {
        "headcount": hr_reports.build_report(db, "headcount", None, to_date=end),
        "joiners-leavers": hr_reports.build_report(
            db, "joiners-leavers", None, from_date=start, to_date=end),
        "attendance-summary": hr_reports.build_report(
            db, "attendance-summary", None, from_date=start, to_date=end),
        "late-absentee": hr_reports.build_report(
            db, "late-absentee", None, from_date=start, to_date=end),
        "document-expiry": hr_reports.build_report(db, "document-expiry", None, days=30),
    }
    today = hr_svc_today()
    head = built["headcount"]["summary"]
    movements = built["joiners-leavers"]["summary"]
    attendance = built["attendance-summary"]
    pending, stale = _pending(db, today)
    digest = hr_notify.digest_rows(db, today)

    kpis = [
        {"key": "headcount", "label": "Headcount", "display": _count(head["headcount"]),
         "note": f"On the rolls at {end.strftime('%d %b %Y')}."},
        {"key": "joiners", "label": "Joiners", "display": _count(movements["joiners"]),
         "note": built["joiners-leavers"]["filters"]["from_date"] + " to "
                 + built["joiners-leavers"]["filters"]["to_date"] + "."},
        {"key": "leavers", "label": "Leavers", "display": _count(movements["leavers"]),
         "note": "Attrition "
                 + (f"{movements['attrition_pct']}% of the opening headcount."
                    if movements["attrition_pct"] is not None
                    else "is not available: nobody was on the rolls at the start.")},
        {"key": "pending", "label": "HR requests waiting", "display": _count(pending),
         "note": f"{stale} older than three days." if pending else "Nothing is pending."},
        {"key": "documents", "label": "Documents expiring",
         "display": _count(len(digest["documents"])), "note": "Within 30 days."},
        {"key": "probation", "label": "Probation ending",
         "display": _count(len(digest["probation"])), "note": "Within 30 days."},
    ]

    attention = []
    if pending:
        attention.append({
            "title": "HR approvals waiting",
            "detail": f"{pending} request(s) need a decision; {stale} are older than three days.",
            "href": f"{base_url or settings.app_base_url}/ui#approvals"})
    if digest["documents"]:
        attention.append({
            "title": "Documents expiring",
            "detail": f"{len(digest['documents'])} active document(s) expire within 30 days.",
            "href": f"{base_url or settings.app_base_url}/ui#hr"})
    if digest["probation"]:
        attention.append({
            "title": "Probation decisions due",
            "detail": f"{len(digest['probation'])} employee(s) reach the end of probation "
                      "within 30 days.",
            "href": f"{base_url or settings.app_base_url}/ui#hr"})
    if attendance["no_data"]:
        attention.append({
            "title": "Attendance is missing",
            "detail": "No attendance rows exist in this period.",
            "href": f"{base_url or settings.app_base_url}/ui#hr"})

    tables = [
        {"key": "by-department", "title": "Headcount by department",
         "columns": [{"key": "department", "label": "Department"},
                     {"key": "employees", "label": "Employees"}],
         "rows": head["by_department"], "total": len(head["by_department"])},
        {"key": "movements", "title": "Joiners and leavers",
         "columns": built["joiners-leavers"]["columns"],
         "rows": built["joiners-leavers"]["rows"], "total": len(built["joiners-leavers"]["rows"])},
        {"key": "attendance", "title": "Attendance this period",
         "columns": built["attendance-summary"]["columns"],
         "rows": attendance["rows"], "total": len(attendance["rows"])},
        {"key": "late", "title": "Late and absent employees",
         "columns": built["late-absentee"]["columns"],
         "rows": built["late-absentee"]["rows"], "total": len(built["late-absentee"]["rows"])},
        {"key": "documents", "title": "Documents expiring within 30 days",
         "columns": built["document-expiry"]["columns"],
         "rows": built["document-expiry"]["rows"],
         "total": len(built["document-expiry"]["rows"])},
    ]
    gaps = []
    for item in built.values():
        for gap in item["gaps"]:
            if gap not in gaps:
                gaps.append(gap)
    notes = ["Salary amounts are not included in this pack. Open the confidential "
             "Department cost report in the application to see pay.",
             "Every figure comes from the database; \"No data yet\" marks an input the "
             "system does not hold."]

    return {
        "hr_pack": True, "pack_key": "hr", "label": LABEL,
        "company": report_packs.company_name(db),
        "from": start.isoformat(), "to": end.isoformat(),
        "period_label": report_packs._window_label(start, end),
        "generated_at": (generated_at or datetime.now(IST)).isoformat(),
        "base_url": base_url or settings.app_base_url,
        "kpis": kpis, "attention": attention, "tables": tables,
        "gaps": gaps, "notes": notes, "row_limit": ROW_LIMIT,
        "_built": built,
    }


def hr_svc_today() -> date:
    from . import hr as hr_svc
    return hr_svc.business_today()


def _table_html(table: dict) -> str:
    columns = table["columns"]
    head = "".join(
        f'<th align="left" style="padding:6px 8px;border-bottom:1px solid {LINE};'
        f'font-size:12px;color:{MUTED}">{_e(c["label"])}</th>' for c in columns)
    body = []
    for row in table["rows"][:ROW_LIMIT]:
        cells = "".join(
            f'<td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:13px">'
            f'{_e(row.get(c["key"], ""))}</td>' for c in columns)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append(f'<tr><td colspan="{len(columns)}" style="padding:8px;font-size:13px;'
                    f'color:{MUTED}">No data yet.</td></tr>')
    more = ""
    if table["total"] > ROW_LIMIT:
        more = (f'<p style="margin:4px 0 0;font-size:12px;color:{MUTED}">Showing the first '
                f'{ROW_LIMIT} of {table["total"]} rows. The full report is in the application.'
                f'</p>')
    return (f'<h2 style="margin:18px 0 6px;font-size:16px;color:{INK}">{_e(table["title"])}</h2>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0">{head}{"".join(body)}</table>{more}')


def render(data: dict, attachments: list[dict], *, mode: str = "test",
           test_recipient: str | None = None, real_recipients: int = 0,
           owner: str = "", dashboard_url: str | None = None) -> dict:
    url = dashboard_url or f"{data['base_url']}/ui/"
    banner = ""
    if mode == "test":
        banner = (f'<div style="background:#FFF8E8;border-bottom:1px solid #D9A441;'
                  f'padding:10px 16px;font-size:13px;color:#7A4A00;text-align:center">'
                  f'<b>TEST MODE.</b> This message was redirected to '
                  f'{_e(test_recipient or "the Administrator")}. {real_recipients} real '
                  f'recipient(s) were not sent to.</div>')
    elif mode == "preview":
        banner = (f'<div style="background:#EEF5F1;border-bottom:1px solid {GREEN};'
                  f'padding:10px 16px;font-size:13px;color:{GREEN};text-align:center">'
                  f'<b>PREVIEW.</b> Nothing was sent. This is how the email will look.</div>')

    head = data["kpis"][0]
    joiner = data["kpis"][1]
    leaver = data["kpis"][2]
    headline = (f"Headcount was {head['display']} at the end of the period, with "
                f"{joiner['display']} joiner(s) and {leaver['display']} leaver(s).")
    if data["attention"]:
        headline += (f" {len(data['attention'])} item(s) need attention.")
    else:
        headline += " Nothing needs attention in this period."

    tiles = []
    for index in range(0, len(data["kpis"]), 2):
        pair = data["kpis"][index:index + 2]
        cells = []
        for kpi in pair:
            cells.append(
                f'<td width="50%" style="vertical-align:top;padding:6px">'
                f'<div style="background:{TILE};border:1px solid {LINE};border-radius:10px;'
                f'padding:12px 14px">'
                f'<div style="font-size:12px;color:{MUTED};text-transform:uppercase;'
                f'letter-spacing:.04em">{_e(kpi["label"])}</div>'
                f'<div style="font-size:22px;font-weight:700;color:{INK};margin:4px 0">'
                f'{_e(kpi["display"])}</div>'
                f'<div style="font-size:12px;color:{MUTED}">{_e(kpi["note"])}</div>'
                f'</div></td>')
        if len(cells) == 1:
            cells.append('<td width="50%"></td>')
        tiles.append(f"<tr>{''.join(cells)}</tr>")
    tile_html = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                 f'border="0">{"".join(tiles)}</table>')

    if data["attention"]:
        items = "".join(
            f'<li style="margin:0 0 6px"><b>{_e(a["title"])}</b>: {_e(a["detail"])} '
            f'<a href="{_e(a["href"])}" style="color:{GREEN}">Open</a></li>'
            for a in data["attention"])
        attention_html = f'<ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.5">{items}</ul>'
    else:
        attention_html = (f'<p style="margin:0;font-size:13px;color:{MUTED}">'
                          f'Nothing needs attention in this period.</p>')

    tables_html = "".join(_table_html(t) for t in data["tables"])
    gaps_html = ""
    if data["gaps"]:
        gaps_html = ('<h2 style="margin:18px 0 6px;font-size:16px;color:%s">No data yet</h2>'
                     '<ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.5;'
                     'color:%s">%s</ul>' % (INK, MUTED,
                                            "".join(f"<li>{_e(g)}</li>" for g in data["gaps"])))
    notes_html = "".join(
        f'<p style="margin:4px 0;font-size:12px;color:{MUTED}">{_e(n)}</p>'
        for n in data["notes"])

    attachment_html = ""
    if attachments:
        rows = "".join(
            f'<li style="margin:0 0 4px">{_e(a["filename"])} '
            f'({max(1, round(len(a["bytes"]) / 1000))} KB)</li>' for a in attachments)
        attachment_html = (f'<h2 style="margin:18px 0 6px;font-size:16px;color:{INK}">'
                           f'Attachments</h2>'
                           f'<ul style="margin:0;padding-left:18px;font-size:13px;'
                           f'line-height:1.5">{rows}</ul>')

    html_body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_e(data["company"])} | {_e(data["label"])} | {_e(data["period_label"])}</title>
</head>
<body style="margin:0;padding:0;background:#E9EEEA;font-family:Arial,Helvetica,sans-serif;color:{INK}">
{banner}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#E9EEEA">
<tr><td align="center" style="padding:16px 8px">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;background:#fff;border-radius:12px;overflow:hidden">
<tr><td style="background:{GREEN};color:#fff;padding:24px 28px">
<b style="font-size:20px;letter-spacing:.06em">{_e(data["company"]).upper()}</b>
<div style="font-size:13px;opacity:.92;margin-top:4px">{_e(data["label"])} · {_e(data["period_label"])}</div>
<div style="font-size:12px;opacity:.85;margin-top:2px">Generated {_e(data["generated_at"][:16].replace("T", " "))} IST</div>
</td></tr>
<tr><td style="padding:22px 28px 4px">
<p style="margin:0 0 10px;font-size:14px;line-height:1.5">Dear Sir / Madam,</p>
<p style="margin:0;font-size:14px;line-height:1.5"><b>{_e(headline)}</b></p>
</td></tr>
<tr><td style="padding:8px 22px 0">{tile_html}</td></tr>
<tr><td style="padding:14px 28px 0">
<h2 style="margin:0 0 8px;font-size:16px;color:{INK}">Needs attention</h2>
{attention_html}
</td></tr>
<tr><td style="padding:0 28px 0">{tables_html}</td></tr>
<tr><td style="padding:0 28px 0">{gaps_html}</td></tr>
<tr><td style="padding:0 28px 0">{attachment_html}</td></tr>
<tr><td style="padding:20px 28px 26px;text-align:center">
<a href="{_e(url)}" style="display:inline-block;background:{GREEN};color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:14px 24px;border-radius:10px;min-height:44px;line-height:1.4">Open the HR screen</a>
<p style="font-size:12px;color:{MUTED};margin-top:10px">Login required</p>
</td></tr>
<tr><td style="background:#F4F6F3;padding:18px 28px;font-size:12px;color:{MUTED};line-height:1.5">
Scheduled by {_e(owner or "the Administrator")} (Settings, Scheduled reports). Data is as at {_e(data["to"])}.
{notes_html}
This email is confidential and meant only for the named recipients. If you received it by mistake, please delete it and tell the sender.
</td></tr>
</table></td></tr></table>
</body></html>"""

    lines = []
    if mode == "test":
        lines += [f"[TEST MODE] Redirected to {test_recipient or 'the Administrator'}; "
                  f"{real_recipients} real recipient(s) were not sent to.", ""]
    lines += [f"{data['company'].upper()} | {data['label']} | {data['period_label']}",
              f"Generated {data['generated_at'][:16].replace('T', ' ')} IST", "",
              headline, "", "KEY FIGURES"]
    for kpi in data["kpis"]:
        lines.append(f"- {kpi['label']}: {kpi['display']} ({kpi['note']})")
    lines += ["", "NEEDS ATTENTION" if data["attention"] else "NEEDS ATTENTION: nothing"]
    for item in data["attention"]:
        lines.append(f"- {item['title']}: {item['detail']} {item['href']}")
    for table in data["tables"]:
        lines += ["", table["title"].upper()]
        lines.append(" | ".join(c["label"] for c in table["columns"]))
        for row in table["rows"][:ROW_LIMIT]:
            lines.append(" | ".join(str(row.get(c["key"], "")) for c in table["columns"]))
        if not table["rows"]:
            lines.append("No data yet.")
        elif table["total"] > ROW_LIMIT:
            lines.append(f"Showing the first {ROW_LIMIT} of {table['total']} rows.")
    if data["gaps"]:
        lines += ["", "NO DATA YET"]
        lines += [f"- {gap}" for gap in data["gaps"]]
    if attachments:
        lines += ["", "ATTACHMENTS"]
        lines += [f"- {a['filename']}" for a in attachments]
    lines += ["", f"Open the HR screen: {url}", ""]
    lines += data["notes"]
    lines += ["This email is confidential and meant only for the named recipients."]

    line = subject_line(data)
    if mode == "test":
        line = f"[TEST] {line}"
    return {"html": html_body, "text": "\n".join(lines), "images": {},
            "subject": line, "warnings": []}


def subject_line(data: dict) -> str:
    headcount = data["kpis"][0]["display"]
    return f"HERBANOVA | {LABEL} | {data['period_label']} | Headcount {headcount}"


def _pdf(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"{data['label']} {data['period_label']}")
    small = pdf_fonts.cell_style(7.5)
    small_head = pdf_fonts.cell_style(7.5, bold=True)
    story = [Paragraph(escape(f"{data['label']} · {data['period_label']}"),
                       pdf_fonts.style("Title")),
             Paragraph(escape(data["company"]), pdf_fonts.style("Normal"))]
    for kpi in data["kpis"]:
        story.append(Paragraph(escape(f"{kpi['label']}: {kpi['display']} — {kpi['note']}"),
                               small))
    for table in data["tables"]:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(escape(table["title"]), pdf_fonts.style("Heading2")))
        rows = [[Paragraph(escape(c["label"]), small_head) for c in table["columns"]]]
        for row in table["rows"]:
            rows.append([Paragraph(escape(str(row.get(c["key"], ""))), small)
                         for c in table["columns"]])
        if len(rows) == 1:
            story.append(Paragraph("No data yet.", small))
            continue
        width = doc.width / len(table["columns"])
        grid = Table(rows, colWidths=[width] * len(table["columns"]), repeatRows=1)
        grid.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f0")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c4be")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(grid)
    if data["gaps"]:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("No data yet", pdf_fonts.style("Heading2")))
        for gap in data["gaps"]:
            story.append(Paragraph("• " + escape(gap), small))
    doc.build(story)
    return buffer.getvalue()


def build_attachments(db: Session, data: dict) -> list[dict]:
    if not data.get("include_attachments", True):
        return []
    period = f"{data['from']}_{data['to']}"
    files = []
    try:
        files.append({"filename": f"HERBANOVA_HR_Report_{period}.pdf",
                      "content_type": "application/pdf", "bytes": _pdf(data),
                      "kind": "summary", "contains": "KPI summary and every table",
                      "rows": sum(len(t["rows"]) for t in data["tables"])})
    except Exception as exc:
        data.setdefault("attachment_errors", []).append(f"PDF not built: {exc}")
    for key in ATTACHMENT_REPORTS:
        report = (data.get("_built") or {}).get(key)
        if not report:
            continue
        try:
            files.append({"filename": f"HERBANOVA_HR_{key}_{period}.csv",
                          "content_type": "text/csv", "bytes": hr_reports.to_csv(report),
                          "kind": "register", "contains": report["title"],
                          "rows": len(report["rows"])})
        except Exception as exc:
            data.setdefault("attachment_errors", []).append(f"{key} CSV not built: {exc}")
    budget = int(settings.email_max_bytes)
    dropped = []
    while files and sum(len(f["bytes"]) for f in files) > budget:
        victim = next((f for f in reversed(files) if f["kind"] == "register"), None)
        if victim is None:
            victim = files.pop()
        else:
            files.remove(victim)
        dropped.append(victim["filename"])
    if dropped:
        data.setdefault("attachment_notes", []).append(
            "These files were too large to attach: " + ", ".join(dropped) + ".")
    return files
