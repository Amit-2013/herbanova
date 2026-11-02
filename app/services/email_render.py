"""The email itself: table-based HTML, a plain-text alternative and chart images.

The HTML uses tables and inline styles because that is what Outlook renders.
The stylesheet is only an enhancement. No JavaScript, no external font, no
remote image: the logo and the charts travel as CID attachments. Every chart is
followed by its data table, so the figures survive blocked images and the
plain-text part carries the same numbers.

Colour is never the only signal: every change is written with an arrow and the
words "up" or "down". A figure the system cannot compute is printed as
"No data yet" with its gap code.
"""
from __future__ import annotations

import html
from datetime import datetime

from . import email_charts
from .report_packs import _inr as inr

GREEN = "#1F6B4A"
AMBER = "#9A5B00"
RED = "#B3261E"
INK = "#16211B"
MUTED = "#56635B"
LINE = "#E2E8E4"
TILE = "#F7FAF8"

TONE = {"good": GREEN, "watch": AMBER, "flat": MUTED, "bad": RED}


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _size(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f} MB"
    return f"{max(1, round(count / 1000))} KB"


def _dt(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%d %b %Y, %I:%M %p").lstrip("0")


def _delta(kpi: dict) -> str:
    if kpi.get("static"):
        return ""
    if not kpi["available"]:
        return f"No data yet · {kpi['gap']}"
    direction = kpi["direction"]
    if kpi.get("change") is None:
        return "No prior period to compare"
    return f"{direction['arrow']} {direction['word']} {abs(kpi['change']):.1f}% vs previous"


def _delta_colour(kpi: dict) -> str:
    return TONE.get(kpi["direction"]["tone"], MUTED)


def _tile(kpi: dict) -> str:
    value = kpi["display"] if kpi["available"] else "No data yet"
    colour = _delta_colour(kpi) if kpi["available"] else AMBER
    note = kpi.get("note") or ""
    return (
        f'<div style="border:1px solid {LINE};border-radius:10px;padding:12px 14px;'
        f'background:{TILE};height:100%">'
        f'<span style="display:block;font-size:12px;color:{MUTED}">{_e(kpi["label"])}</span>'
        f'<b style="display:block;font-size:22px;line-height:1.2;margin:2px 0;color:{INK}">{_e(value)}</b>'
        + (f'<i style="font-style:normal;font-size:12px;font-weight:700;color:{colour}">{_e(_delta(kpi))}</i>'
           if _delta(kpi) else "")
        + (f'<div style="font-size:11px;color:{MUTED};margin-top:3px">{_e(note)}</div>' if note else "")
        + "</div>")


def _tiles(kpis: list[dict]) -> str:
    cells = []
    for index in range(0, len(kpis), 2):
        pair = kpis[index:index + 2]
        left = f'<td width="50%" style="padding:0 6px 12px 0;vertical-align:top">{_tile(pair[0])}</td>'
        right = (f'<td width="50%" style="padding:0 0 12px 6px;vertical-align:top">{_tile(pair[1])}</td>'
                 if len(pair) > 1 else '<td width="50%"></td>')
        cells.append(f"<tr>{left}{right}</tr>")
    return ('<table role="presentation" width="100%" style="border-collapse:separate;'
            'border-spacing:0">' + "".join(cells) + "</table>")


def _attention(items: list[dict]) -> str:
    if not items:
        return (f'<p style="margin:0;font-size:14px;color:{MUTED}">'
                "Nothing needs attention in this period.</p>")
    out = []
    for item in items:
        red = item["severity"] == "red"
        colour = RED if red else AMBER
        background = "#FDECEA" if red else "#FFF8E8"
        out.append(
            f'<div style="border-left:4px solid {colour};background:{background};'
            f'padding:10px 14px;margin:0 0 8px;font-size:14px;color:{INK}">'
            f'<b>{_e(item["title"])}</b> {_e(item["detail"])} '
            f'<a href="{_e(item["href"])}" style="color:{colour};font-weight:600">{_e(item["link"])}</a></div>')
    return "".join(out)


def _change_text(value, good_when_up: bool = True) -> str:
    if value is None:
        return "No prior figure"
    if value == 0:
        return "No change"
    up = value > 0
    good = up if good_when_up else not up
    colour = GREEN if good else AMBER
    return (f'<span style="color:{colour};font-weight:700">'
            f'{"▲" if up else "▼"} {abs(value):.1f}%</span>')


def _comparison(data: dict) -> str:
    rows = []
    for row in data["comparison"]:
        if row.get("gap"):
            rows.append(
                f'<tr><td style="padding:9px 8px;border-bottom:1px solid {LINE};font-size:13px">'
                f'{_e(row["label"])}</td><td colspan="4" style="padding:9px 8px;'
                f'border-bottom:1px solid {LINE};font-size:13px;color:{AMBER}">'
                f'No data yet · {_e(row["gap"])}</td></tr>')
            continue
        rows.append(
            f'<tr><td style="padding:9px 8px;border-bottom:1px solid {LINE};font-size:13px">'
            f'{_e(row["label"])}</td>'
            f'<td style="padding:9px 8px;border-bottom:1px solid {LINE};font-size:13px;text-align:right">'
            f'{_e(inr(row["current"]))}</td>'
            f'<td style="padding:9px 8px;border-bottom:1px solid {LINE};font-size:13px;text-align:right">'
            f'{_e(inr(row["previous"]) if row.get("previous") is not None else "—")}</td>'
            f'<td style="padding:9px 8px;border-bottom:1px solid {LINE};font-size:13px;text-align:right">'
            f'{_e(inr(row["last_year"]) if row.get("last_year") is not None else "—")}</td>'
            f'<td style="padding:9px 8px;border-bottom:1px solid {LINE};font-size:13px;text-align:right">'
            f'{_change_text(row.get("previous_change"))}</td></tr>')
    return (
        f'<div style="overflow-x:auto"><table role="table" width="100%" '
        f'style="border-collapse:collapse;min-width:520px">'
        f'<tr><th style="background:{GREEN};color:#fff;font-size:12px;text-align:left;padding:8px">Metric</th>'
        f'<th style="background:{GREEN};color:#fff;font-size:12px;text-align:right;padding:8px">This period</th>'
        f'<th style="background:{GREEN};color:#fff;font-size:12px;text-align:right;padding:8px">Previous</th>'
        f'<th style="background:{GREEN};color:#fff;font-size:12px;text-align:right;padding:8px">Last year</th>'
        f'<th style="background:{GREEN};color:#fff;font-size:12px;text-align:right;padding:8px">Change</th></tr>'
        + "".join(rows) + "</table></div>")


def _series_table(series: list[dict]) -> str:
    rows = "".join(
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:12px">{_e(r["label"])}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:12px;text-align:right">{_e(inr(r["sales"]))}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:12px;text-align:right">{_e(inr(r["purchases"]))}</td></tr>'
        for r in series)
    return (f'<table role="table" width="100%" style="border-collapse:collapse;margin-top:8px">'
            f'<tr><th style="font-size:12px;text-align:left;padding:6px 8px;color:{MUTED}">Period</th>'
            f'<th style="font-size:12px;text-align:right;padding:6px 8px;color:{MUTED}">Sales</th>'
            f'<th style="font-size:12px;text-align:right;padding:6px 8px;color:{MUTED}">Purchases</th></tr>'
            + rows + "</table>")


def _ageing_table(buckets: list[dict]) -> str:
    rows = "".join(
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:13px">{_e(b["label"])}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:13px;text-align:right">{_e(inr(b["total"]))}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:13px;text-align:right">{_e(b["count"])}</td></tr>'
        for b in buckets)
    return (f'<table role="table" width="100%" style="border-collapse:collapse;margin-top:8px">'
            f'<tr><th style="font-size:12px;text-align:left;padding:6px 8px;color:{MUTED}">Bucket</th>'
            f'<th style="font-size:12px;text-align:right;padding:6px 8px;color:{MUTED}">Outstanding</th>'
            f'<th style="font-size:12px;text-align:right;padding:6px 8px;color:{MUTED}">Invoices</th></tr>'
            + rows + "</table>")


def _top_table(rows: list[dict], label: str) -> str:
    if not rows:
        return f'<p style="margin:0;font-size:13px;color:{AMBER}">No data yet for this period.</p>'
    body = "".join(
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:13px">{_e(r.get("name") or r.get("sku"))}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid {LINE};font-size:13px;text-align:right">{_e(inr(r.get("value")))}</td></tr>'
        for r in rows)
    return (f'<table role="table" width="100%" style="border-collapse:collapse">'
            f'<tr><th style="font-size:12px;text-align:left;padding:6px 8px;color:{MUTED}">{_e(label)}</th>'
            f'<th style="font-size:12px;text-align:right;padding:6px 8px;color:{MUTED}">Value</th></tr>'
            + body + "</table>")


def _accounts(data: dict) -> str:
    acc = data.get("accounts")
    if not acc:
        return ""
    profit = data.get("profit") or {}
    gaps = profit.get("gaps") or []
    first_gap = gaps[0]["code"] if gaps else "GAP-P01"
    gross_ok = profit.get("gross_profit") is not None
    expenses_ok = profit.get("expenses") is not None
    net_ok = profit.get("net_profit") is not None
    tiles = [
        {"key": "revenue", "static": True, "label": "Revenue (taxable)", "display": inr(acc["revenue"]["taxable"]),
         "available": True, "change": None, "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None, "note": "Issued invoices, before GST."},
        {"key": "collections", "static": True, "label": "Collections", "display": inr(acc["collections"]["total"]),
         "available": True, "change": None, "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None, "note": "Receipts dated in the window."},
        {"key": "outstanding", "static": True, "label": "Receivables outstanding", "display": inr(acc["outstanding"]["total"]),
         "available": True, "change": None, "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None, "note": f"As at {acc['as_of']}."},
        {"key": "payables", "static": True, "label": "Payables outstanding", "display": inr(acc["payables"]["total"]),
         "available": True, "change": None, "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None, "note": "As at the window end; due dates estimated."},
        {"key": "gst", "static": True, "label": "Output GST", "display": inr(acc["output_gst"]["total"]),
         "available": True, "change": None, "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None, "note": "Input tax is not captured (GAP-A05)."},
        {"key": "cash", "static": True, "label": "Cash and bank (net movement)", "display": inr(acc["cash_bank_net"]),
         "available": True, "change": None, "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None, "note": "No opening balance is captured (GAP-A10)."},
        {"key": "gross_profit", "static": True, "label": "Gross profit",
         "display": inr(profit.get("gross_profit")) if gross_ok else "No data yet",
         "available": gross_ok, "change": None,
         "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None if gross_ok else "GAP-P01",
         "note": profit.get("gross_profit_label") or "Cost of goods is not captured."},
        {"key": "expenses", "static": True, "label": "Expenses",
         "display": inr(profit.get("expenses")) if expenses_ok else "No data yet",
         "available": expenses_ok, "change": None,
         "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None if expenses_ok else "GAP-P02",
         "note": ("Approved entries; non-creditable GST is cost." if expenses_ok
                  else "Expenses are not tracked for the whole window.")},
        {"key": "net_profit", "static": True, "label": "Net profit",
         "display": inr(profit.get("net_profit")) if net_ok else "No data yet",
         "available": net_ok, "change": None,
         "direction": {"arrow": "", "word": "", "tone": "flat"},
         "gap": None if net_ok else first_gap,
         "note": ("Gross profit less expenses and payroll." if net_ok
                  else "Not shown until cost, expenses and payroll are complete.")},
    ]
    tb = acc["trial_balance"]
    check = ("Debits equal credits" if tb["balanced"] else
             f"DOES NOT BALANCE: debits {inr(tb['debit_total'])} vs credits {inr(tb['credit_total'])}")
    # Accounts attention items are raised in the single "Needs attention" list
    # above, so this block carries figures only and never repeats a warning.
    return (
        f'<hr style="border:0;border-top:1px solid {LINE};margin:0">'
        f'<div style="padding:22px 28px">'
        f'<h2 style="margin:0 0 6px;font-size:16px;color:{INK}">Accounts summary</h2>'
        f'<p style="margin:0 0 12px;font-size:13px;color:{MUTED}">Period {_e(data["period_label"])}. '
        f'Outstanding and payables are as at {_e(acc["as_of"])}. A locked accounting month '
        f'refuses cost corrections and expense creation or reversal; invoice changes, '
        f'credit notes, receipts, payments and year-end close are not covered (GAP-A03).</p>'
        + _tiles(tiles)
        + f'<p style="font-size:12px;color:{"#1F6B4A" if tb["balanced"] else RED};margin:8px 0 0">'
          f'Trial balance: {_e(check)}.</p>'
        + "</div>")


def _attachments(attachments: list[dict], notes: list[str], as_of: str) -> str:
    if not attachments and not notes:
        return ""
    rows = "".join(
        f'<tr><td style="padding:8px;border-bottom:1px solid {LINE};font-size:12px;word-break:break-all">'
        f'{_e(a["filename"])}</td>'
        f'<td style="padding:8px;border-bottom:1px solid {LINE};font-size:12px">{_e(a.get("contains"))}</td>'
        f'<td style="padding:8px;border-bottom:1px solid {LINE};font-size:12px;text-align:right">{_e(a.get("rows"))}</td>'
        f'<td style="padding:8px;border-bottom:1px solid {LINE};font-size:12px;text-align:right">{_size(len(a["bytes"]))}</td>'
        f'<td style="padding:8px;border-bottom:1px solid {LINE};font-size:12px">'
        f'{"PDF" if a["filename"].endswith(".pdf") else "Excel"}</td></tr>'
        for a in attachments)
    note_html = "".join(f'<p style="font-size:12px;color:{AMBER};margin:6px 0">{_e(n)}</p>' for n in notes)
    return (
        f'<hr style="border:0;border-top:1px solid {LINE};margin:0">'
        f'<div style="padding:22px 28px">'
        f'<h2 style="margin:0 0 6px;font-size:16px;color:{INK}">Attached reports</h2>'
        f'<p style="margin:0 0 10px;font-size:13px;color:{MUTED}">Data is as at {_e(as_of)}'
        f'</p>'
        f'<div style="overflow-x:auto"><table role="table" width="100%" style="border-collapse:collapse">'
        f'<tr><th style="font-size:11px;text-align:left;padding:8px;color:{MUTED}">File</th>'
        f'<th style="font-size:11px;text-align:left;padding:8px;color:{MUTED}">Contains</th>'
        f'<th style="font-size:11px;text-align:right;padding:8px;color:{MUTED}">Rows</th>'
        f'<th style="font-size:11px;text-align:right;padding:8px;color:{MUTED}">Size</th>'
        f'<th style="font-size:11px;text-align:left;padding:8px;color:{MUTED}">Format</th></tr>'
        + rows + "</table></div>" + note_html + "</div>")


def render(data: dict, attachments: list[dict], *, mode: str = "test",
           test_recipient: str | None = None, real_recipients: int = 0,
           owner: str = "", dashboard_url: str | None = None) -> dict:
    if data.get("hr_pack"):
        from . import hr_pack
        return hr_pack.render(data, attachments, mode=mode, test_recipient=test_recipient,
                              real_recipients=real_recipients, owner=owner,
                              dashboard_url=dashboard_url)
    url = dashboard_url or f"{data['base_url']}/ui/"
    images: dict[str, bytes] = {}
    chart_blocks = []
    try:
        images["sales_chart"] = email_charts.sales_purchases(data["series"])
        chart_blocks.append(
            f'<h2 style="margin:14px 0 6px;font-size:16px;color:{INK}">Sales vs purchases</h2>'
            f'<img src="cid:sales_chart" width="560" alt="Bar chart of sales and purchases for '
            f'{_e(data["period_label"])}. The same figures are in the table below." '
            f'style="width:100%;max-width:560px;height:auto;border:0">'
            + _series_table(data["series"]))
    except Exception:
        chart_blocks.append(_series_table(data["series"]))
    try:
        images["ageing_chart"] = email_charts.ageing(data["ageing"]["buckets"])
        chart_blocks.append(
            f'<h2 style="margin:14px 0 6px;font-size:16px;color:{INK}">Receivables ageing</h2>'
            f'<img src="cid:ageing_chart" width="560" alt="Bar chart of receivables by age bucket. '
            f'The same figures are in the table below." style="width:100%;max-width:560px;height:auto;border:0">'
            + _ageing_table(data["ageing"]["buckets"]))
    except Exception:
        chart_blocks.append(_ageing_table(data["ageing"]["buckets"]))
    if data.get("trend"):
        try:
            images["trend_chart"] = email_charts.trend(data["trend"])
            chart_blocks.append(
                f'<h2 style="margin:14px 0 6px;font-size:16px;color:{INK}">Monthly trend</h2>'
                f'<img src="cid:trend_chart" width="560" alt="Line chart of monthly revenue and '
                f'collections. The figures are in the accounts table." '
                f'style="width:100%;max-width:560px;height:auto;border:0">')
        except Exception:
            pass
    try:
        images["logo"] = email_charts.logo()
    except Exception:
        pass

    sales = next((k for k in data["kpis"] if k["key"] == "sales"), None)
    headline = ""
    if sales and sales["available"]:
        if sales.get("change") is not None:
            direction = sales["direction"]
            headline = (f"Sales were {_e(inr(sales['value']))}, {direction['arrow']} "
                        f"{direction['word']} {abs(sales['change']):.1f}% on the previous period.")
        else:
            headline = f"Sales were {_e(inr(sales['value']))}. There is no prior period to compare."
    else:
        headline = "No sales figure is available for this period."
    attention_count = len(data["attention"])
    headline += (f" {attention_count} item{'s' if attention_count != 1 else ''} "
                 f"{'need' if attention_count != 1 else 'needs'} attention."
                 if attention_count else " Nothing needs attention in this period.")

    test_banner = ""
    if mode == "test":
        test_banner = (
            f'<div style="background:#FFF8E8;border-bottom:1px solid #D9A441;padding:10px 16px;'
            f'font-size:13px;color:#7A4A00;text-align:center">'
            f'<b>TEST MODE.</b> This message was redirected to {_e(test_recipient or "the Administrator")}. '
            f'{real_recipients} real recipient(s) were not sent to.</div>')
    elif mode == "preview":
        test_banner = (
            f'<div style="background:#EEF5F1;border-bottom:1px solid {GREEN};padding:10px 16px;'
            f'font-size:13px;color:{GREEN};text-align:center">'
            f'<b>PREVIEW.</b> Nothing was sent. This is how the email will look.</div>')

    logo_img = ('<img src="cid:logo" width="48" height="48" alt="Herbanova" '
                'style="display:block;border:0">' if "logo" in images else "")

    attachments_note = []
    if not attachments:
        attachments_note.append("No attachment was added to this email.")
    attachments_note += data.get("attachment_notes", [])

    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_e(data["company"])} | {_e(data["label"])} | {_e(data["period_label"])}</title>
<style>
body{{margin:0;padding:0;background:#E9EEEA;font-family:Arial,Helvetica,sans-serif;color:{INK}}}
@media (prefers-color-scheme:dark){{body{{background:#0F1713!important}}}}
.wrap{{width:100%;max-width:640px;background:#fff;border-radius:12px;overflow:hidden}}
a{{color:{GREEN}}}
</style>
</head>
<body style="margin:0;padding:0;background:#E9EEEA">
{test_banner}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#E9EEEA">
<tr><td align="center" style="padding:16px 8px">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" class="wrap" style="width:100%;max-width:640px;background:#fff;border-radius:12px;overflow:hidden">
<tr><td style="background:{GREEN};color:#fff;padding:24px 28px">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="padding-right:12px">{logo_img}</td>
<td><b style="font-size:20px;letter-spacing:.06em">{_e(data["company"]).upper()}</b>
<div style="font-size:13px;opacity:.92;margin-top:4px">{_e(data["label"])} · {_e(data["period_label"])}</div>
<div style="font-size:12px;opacity:.85;margin-top:2px">Generated {_e(_dt(data["generated_at"]))} IST</div></td>
</tr></table></td></tr>
<tr><td style="padding:22px 28px 0">
<p style="margin:0 0 10px;font-size:14px;line-height:1.5">Dear Sir / Madam,</p>
<p style="margin:0 0 10px;font-size:14px;line-height:1.5"><b>{headline}</b></p>
</td></tr>
<tr><td style="padding:12px 22px 0 28px">{_tiles(data["kpis"])}</td></tr>
<tr><td style="padding:10px 28px 0">
<h2 style="margin:8px 0 10px;font-size:16px;color:{INK}">Needs attention</h2>
{_attention(data["attention"])}
</td></tr>
<tr><td style="padding:18px 28px 0">
<h2 style="margin:0 0 6px;font-size:16px;color:{INK}">Comparison</h2>
<p style="margin:0 0 10px;font-size:13px;color:{MUTED}">{_e(data["period_label"])} against the equally long previous period and the same period last year. A change against zero is shown as "No prior figure".</p>
{_comparison(data)}
</td></tr>
<tr><td style="padding:18px 28px 0">{''.join(chart_blocks)}</td></tr>
<tr><td style="padding:18px 28px 0">
<table role="presentation" width="100%"><tr><td width="50%" style="vertical-align:top;padding-right:8px">
<h2 style="margin:0 0 6px;font-size:16px;color:{INK}">Top products</h2>
{_top_table(data["top_products"], "Product")}
</td><td width="50%" style="vertical-align:top;padding-left:8px">
<h2 style="margin:0 0 6px;font-size:16px;color:{INK}">Top customers</h2>
{_top_table(data["top_customers"], "Customer")}
</td></tr></table>
<h2 style="margin:14px 0 6px;font-size:16px;color:{INK}">Top states by sales</h2>
{_top_table(data["states"]["top"], "State")}
<p style="font-size:12px;color:{MUTED};margin:6px 0 0">{_e(data["states"]["note"])}</p>
</td></tr>
{('<tr><td>' + _accounts(data) + '</td></tr>') if data.get("accounts") else ""}
{('<tr><td>' + _attachments(attachments, attachments_note, data['to']) + '</td></tr>') if attachments or attachments_note else ""}
<tr><td style="padding:8px 28px 26px;text-align:center">
<a href="{_e(url)}" style="display:inline-block;background:{GREEN};color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:14px 24px;border-radius:10px;min-height:44px;line-height:1.4">View full dashboard</a>
<p style="font-size:12px;color:{MUTED};margin-top:10px">Login required</p>
</td></tr>
<tr><td style="background:#F4F6F3;padding:18px 28px;font-size:12px;color:{MUTED};line-height:1.5">
Scheduled by {_e(owner or "the Administrator")} (Settings, Scheduled reports). Data is as at {_e(data["to"])}.
Every figure comes from the database; "No data yet" marks an input the system does not capture.
This email and its attachments are confidential and meant only for the named recipients. If you received it by mistake, please delete it and tell the sender.
</td></tr>
</table></td></tr></table>
</body></html>"""

    text = _plain(data, attachments, mode, test_recipient, real_recipients, owner, url)
    return {"html": body, "text": text, "images": images,
            "subject": _subject(data, mode), "warnings": attachments_note}


def _subject(data: dict, mode: str) -> str:
    from .report_packs import subject
    base = subject(data)
    return f"[TEST] {base}" if mode == "test" else base


def _plain(data: dict, attachments: list[dict], mode: str, test_recipient: str | None,
           real_recipients: int, owner: str, url: str) -> str:
    lines = []
    if mode == "test":
        lines += [f"[TEST MODE] Redirected to {test_recipient or 'the Administrator'}; "
                  f"{real_recipients} real recipient(s) were not sent to.", ""]
    lines += [f"{data['company'].upper()} | {data['label']} | {data['period_label']}",
              f"Generated {_dt(data['generated_at'])} IST", ""]
    lines.append("KEY FIGURES")
    for kpi in data["kpis"]:
        if kpi["available"]:
            lines.append(f"- {kpi['label']}: {kpi['display']} ({_delta(kpi)})")
        else:
            lines.append(f"- {kpi['label']}: No data yet ({kpi['gap']})")
    lines += ["", "NEEDS ATTENTION" if data["attention"] else "NEEDS ATTENTION: nothing in this period"]
    for item in data["attention"]:
        lines.append(f"- {item['title']}: {item['detail']} {item['href']}")
    lines += ["", "COMPARISON (this period, previous, last year, change)"]
    for row in data["comparison"]:
        if row.get("gap"):
            lines.append(f"- {row['label']}: No data yet ({row['gap']})")
            continue
        change = ("no prior figure" if row.get("previous_change") is None
                  else f"{row['previous_change']:+.1f}%")
        previous = (inr(row["previous"]) if row.get("previous") is not None else "—")
        last_year = (inr(row["last_year"]) if row.get("last_year") is not None else "—")
        lines.append(f"- {row['label']}: {inr(row['current'])}, {previous}, "
                     f"{last_year}, {change}")
    lines += ["", "SALES VS PURCHASES", "Period | Sales | Purchases"]
    for row in data["series"]:
        lines.append(f"- {row['label']} | {inr(row['sales'])} | {inr(row['purchases'])}")
    lines += ["", "RECEIVABLES AGEING", "Bucket | Outstanding | Invoices"]
    for bucket in data["ageing"]["buckets"]:
        lines.append(f"- {bucket['label']} | {inr(bucket['total'])} | {bucket['count']}")
    lines += ["", "TOP PRODUCTS"]
    lines += [f"- {r['name']}: {inr(r['value'])}" for r in data["top_products"]] or ["- No data yet"]
    lines += ["", "TOP CUSTOMERS"]
    lines += [f"- {r['name']}: {inr(r['value'])}" for r in data["top_customers"]] or ["- No data yet"]
    lines += ["", "TOP STATES"]
    lines += [f"- {r['name']}: {inr(r['value'])}" for r in data["states"]["top"]] or ["- No data yet"]
    if data.get("accounts"):
        acc = data["accounts"]
        profit = data.get("profit") or {}
        gaps = profit.get("gaps") or []
        first_gap = gaps[0]["code"] if gaps else "GAP-P01"
        lines += ["", "ACCOUNTS SUMMARY",
                  f"- Revenue (taxable): {inr(acc['revenue']['taxable'])}",
                  f"- Collections: {inr(acc['collections']['total'])}",
                  f"- Returns: {inr(acc['returns']['value'])}",
                  f"- Output GST: {inr(acc['output_gst']['total'])} (input tax not captured, GAP-A05)",
                  f"- Receivables outstanding: {inr(acc['outstanding']['total'])} as at {acc['as_of']}",
                  f"- Receivables over 60 days: {inr(acc['outstanding']['overdue_60'])}",
                  f"- Payables outstanding: {inr(acc['payables']['total'])} (due dates estimated)",
                  f"- Cash and bank net movement: {inr(acc['cash_bank_net'])} (no opening balance, GAP-A10)",
                  f"- {profit.get('gross_profit_label', 'Gross profit')}: "
                  + (inr(profit["gross_profit"]) if profit.get("gross_profit") is not None
                     else "No data yet (GAP-P01)"),
                  f"- Expenses: " + (inr(profit["expenses"])
                                     if profit.get("expenses") is not None
                                     else "No data yet (GAP-P02)"),
                  f"- Payroll (gross): " + (inr(profit["payroll"])
                                            if profit.get("payroll") is not None
                                            else "No data yet (GAP-P03)"),
                  f"- Net profit: " + (inr(profit["net_profit"])
                                       if profit.get("net_profit") is not None
                                       else f"No data yet ({first_gap})"),
                  f"- Trial balance: {'debits equal credits' if acc['trial_balance']['balanced'] else 'DOES NOT BALANCE'}",
                  "- A locked accounting month refuses cost corrections and expense creation or reversal; "
                  "invoice changes, credit notes, receipts, payments and year-end close are not covered (GAP-A03)"]
    lines += ["", "ATTACHED REPORTS"]
    lines += ([f"- {a['filename']} ({a.get('contains')}, {a.get('rows')} rows, {_size(len(a['bytes']))})"
               for a in attachments] or ["- None"])
    lines += data.get("attachment_notes", [])
    lines += ["", f"View the full dashboard (login required): {url}", "",
              f"Scheduled by {owner or 'the Administrator'}. Data is as at {data['to']}.",
              "Every figure comes from the database; 'No data yet' marks an input the system does not capture.",
              "This email and its attachments are confidential and meant only for the named recipients."]
    return "\n".join(lines)
