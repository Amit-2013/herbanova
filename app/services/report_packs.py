"""Report packs: the figures an email carries, built from the same services as
the screens and Reports.

Nothing here queries a table for a number that another module already computes.
Sales, purchases, orders, returns and leads come from the dashboard's period
helpers; outstanding and ageing from `ledger`; payables, GST and the trial
balance from `accounting`; the attached PDF and Excel files from the report
catalog. A missing input is `available: false` with a gap code.

The pack period is fixed by the pack type and the run date, never by the time
the worker happened to wake up:
  daily      the previous complete day
  weekly     the seven days ending the day before the run
  monthly    the previous month on days 1-7, otherwise the current month to date
  alerts     the seven days ending today, plus the current position
  accounts   same as monthly
  custom     the selected month
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.accounts import Payment
from ..models.core import ApprovalRequest, Batch, Distributor, Invoice, Lead, Product
from ..models.tax import CompanyProfile
from ..api.dashboard import (_period_stats as period_stats,
                             _purchases_by_day as purchases_by_day,
                             _sales_by_day as sales_by_day)
from ..services import (accounting, balance_sheet, capacity, exports, ledger,
                        profit_loss, reports, reports_pdf)

ZERO = Decimal("0.00")
IST_OFFSET = timedelta(hours=5, minutes=30)

PACKS = {
    "daily": {"label": "Daily Business Summary", "period": "day",
              "reports": ["sales", "invoices"], "accounts": True,
              "frequency_hint": "Every working morning"},
    "weekly": {"label": "Weekly Management Report", "period": "week",
               "reports": ["sales", "invoices", "purchases"], "accounts": True,
               "frequency_hint": "Weekly, Monday morning"},
    "monthly_md": {"label": "Monthly MD Report", "period": "month",
                   "reports": ["sales", "invoices", "purchases", "receivables_ageing",
                               "gst_register"], "accounts": True,
                   "frequency_hint": "Monthly, first working day"},
    "alerts": {"label": "Alerts Digest", "period": "alert",
               "reports": [], "accounts": False,
               "frequency_hint": "Daily or as needed"},
    "accounts": {"label": "Accounts Report", "period": "month",
                 "reports": ["receivables", "receivables_ageing", "payables",
                             "gst_register", "trial_balance"], "accounts": True,
                 "frequency_hint": "Monthly for the Accounts head"},
    "custom": {"label": "Custom Report", "period": "month",
               "reports": [], "accounts": True,
               "frequency_hint": "Chosen reports on a chosen schedule"},
    "hr": {"label": "HR Report Pack", "period": "month",
           "reports": [], "accounts": False,
           "frequency_hint": "Monthly to the MD and Administrator"},
}


class PackError(ValueError):
    pass


def pack_meta(pack_key: str) -> dict:
    if pack_key not in PACKS:
        raise PackError(f"Unknown report pack {pack_key!r}")
    return PACKS[pack_key]


def company_name(db: Session) -> str:
    row = db.scalar(select(CompanyProfile))
    if row is None:
        return "HERBANOVA"
    return (row.trade_name or row.legal_name or "HERBANOVA").strip()


def _month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def _last_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:                     # 29 February
        return day.replace(year=day.year - 1, day=28)


def period_for(pack_key: str, run_date: date, trigger: str = "scheduled") -> dict:
    """The window a pack covers for a run on `run_date`."""
    kind = pack_meta(pack_key)["period"]
    if kind == "day":
        start = end = run_date - timedelta(days=1)
    elif kind == "week":
        end = run_date - timedelta(days=1)
        start = end - timedelta(days=6)
    elif kind == "alert":
        end = run_date
        start = end - timedelta(days=6)
    else:                                   # month
        if 1 <= run_date.day <= 7:
            end = run_date.replace(day=1) - timedelta(days=1)
            start = end.replace(day=1)
        else:
            start = run_date.replace(day=1)
            end = run_date
    return {"from": start, "to": end,
            "label": _window_label(start, end),
            "previous": (start - timedelta(days=(end - start).days + 1),
                         start - timedelta(days=1)),
            "last_year": (_last_year(start), _last_year(end))}


def _window_label(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%d %b %Y")
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {start.strftime('%b %Y')}"
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"


def _money(value) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def _profit_data(statement: dict | None) -> dict | None:
    """The profit lines an email or attachment can print, already formatted."""
    if not statement:
        return None

    def s(value):
        return _money(value) if isinstance(value, Decimal) else value

    return {
        "revenue": s(statement["revenue"]["taxable"]),
        "returns": s(statement["returns"]["taxable"]),
        "net_revenue": s(statement["net_revenue"]),
        "cogs": s(statement["cogs"]["value"]),
        "gross_profit": s(statement["gross_profit"]["value"]),
        "gross_profit_label": statement["gross_profit"]["label"],
        "gross_profit_partial": statement["gross_profit"]["partial"],
        "invoices_costed": statement["cogs"]["invoices_costed"],
        "invoices_total": statement["cogs"]["invoices_total"],
        "expenses": (s(statement["expenses"]["total"])
                     if statement["expenses"]["complete"]
                     or statement["expenses"]["total"] > 0 else None),
        "expenses_complete": statement["expenses"]["complete"],
        "expenses_partial": (not statement["expenses"]["complete"]
                             and statement["expenses"]["total"] > 0),
        "expenses_tracked_from": statement["expenses"]["tracked_from"],
        "payroll": (s(statement["payroll"]["total"])
                    if statement["payroll"]["complete"]
                    or statement["payroll"]["periods"] else None),
        "payroll_complete": statement["payroll"]["complete"],
        "payroll_partial": (not statement["payroll"]["complete"]
                            and bool(statement["payroll"]["periods"])),
        "net_profit": (s(statement["net_profit"]["value"])
                       if statement["net_profit"]["available"] else None),
        "net_profit_available": statement["net_profit"]["available"],
        "gaps": statement["gaps"],
        "notes": statement["notes"],
    }


def change(current, previous) -> float | None:
    current, previous = Decimal(current or 0), Decimal(previous or 0)
    if previous == 0:
        return None
    return round(float((current - previous) / previous * 100), 1)


def _direction(value: float | None, good_when_up: bool = True) -> dict:
    if value is None:
        return {"arrow": "", "word": "no comparison", "tone": "flat"}
    if value == 0:
        return {"arrow": "", "word": "no change", "tone": "flat"}
    up = value > 0
    good = up if good_when_up else not up
    return {"arrow": "▲" if up else "▼", "word": "up" if up else "down",
            "tone": "good" if good else "watch"}


def _kpi(key, label, value, display, previous, unit="amount", good_when_up=True,
         note="", gap=None, href=""):
    delta = change(value, previous) if value is not None and previous is not None else None
    return {"key": key, "label": label, "value": value, "display": display,
            "unit": unit, "change": delta, "direction": _direction(delta, good_when_up),
            "available": value is not None, "gap": gap, "note": note, "href": href}


def _sum_payments(db: Session, kind: str, start: date, end: date) -> dict:
    row = db.execute(select(func.count(), func.coalesce(func.sum(Payment.amount), 0))
                     .where(Payment.kind == kind, Payment.paid_on >= start,
                            Payment.paid_on <= end)).one()
    return {"count": int(row[0]), "total": Decimal(row[1])}


def _attendance(db: Session) -> dict:
    today = date.today()
    in_stock = Batch.on_hand > 0
    expired = db.execute(select(func.count(), func.min(Batch.expiry))
                         .where(in_stock, Batch.expiry.is_not(None),
                                Batch.expiry < today)).one()
    names = db.execute(
        select(Product.name).join(Batch, Batch.product_id == Product.id)
        .where(in_stock, Batch.expiry.is_not(None), Batch.expiry < today)
        .group_by(Product.name).limit(5)).scalars().all()
    tight = [r for r in capacity.warehouse_positions(db)
             if r.get("capacity_state") in ("high", "over", "full")]
    pending = db.scalar(select(func.count()).where(ApprovalRequest.status == "pending")) or 0
    admin_pending = db.scalar(
        select(func.count()).where(ApprovalRequest.status == "pending",
                                   ApprovalRequest.record_type.in_(
                                       ("sales_order", "invoice_post_billing")))) or 0
    overdue = db.scalar(
        select(func.count()).where(Lead.status.not_in(("won", "lost")),
                                   Lead.next_follow_up.is_not(None),
                                   Lead.next_follow_up < today)) or 0
    return {"expired": int(expired[0]), "expired_names": list(names),
            "tight_warehouses": tight, "pending_approvals": int(pending),
            "admin_approvals": int(admin_pending), "overdue_followups": int(overdue)}


def _attention(db: Session, data: dict, base_url: str) -> list[dict]:
    out = []
    att = data["position"]
    if att["expired"]:
        names = ", ".join(att["expired_names"][:3])
        if len(att["expired_names"]) > 3:
            names += "…"
        out.append({"severity": "red", "title": f"{att['expired']} batches already expired",
                    "detail": f"{names}. Quarantine and raise a write-off.",
                    "href": f"{base_url}/ui/#/inventory", "link": "Open expiry watch"})
    if att["tight_warehouses"]:
        names = ", ".join(r["name"] for r in att["tight_warehouses"][:3])
        out.append({"severity": "amber", "title": "Warehouse at or above the capacity line",
                    "detail": f"{names}. Move slow stock before the next receipt.",
                    "href": f"{base_url}/ui/#/inventory", "link": "Open stock by warehouse"})
    ageing = data["ageing"]
    if Decimal(ageing["overdue_60"]) > 0:
        share = (Decimal(ageing["overdue_60"]) / Decimal(ageing["total"]) * 100
                 if Decimal(ageing["total"]) > 0 else 0)
        out.append({"severity": "amber",
                    "title": f"{share:.1f}% of receivables are older than 60 days",
                    "detail": f"{_inr(ageing['overdue_60'])} outstanding. Send reminders to the top debtors.",
                    "href": f"{base_url}/ui/#/accounts", "link": "Open receivables"})
    if att["admin_approvals"]:
        out.append({"severity": "amber",
                    "title": f"{att['admin_approvals']} approvals need the Administrator",
                    "detail": f"{att['pending_approvals']} requests are waiting in total.",
                    "href": f"{base_url}/ui/#/approvals", "link": "Open approvals"})
    if att["overdue_followups"]:
        out.append({"severity": "red",
                    "title": f"{att['overdue_followups']} follow-ups are overdue",
                    "detail": "Open the follow-up list and reassign or close them.",
                    "href": f"{base_url}/ui/#/followups", "link": "Open follow-ups"})
    credit = data.get("credit")
    if credit and credit["over_limit_count"]:
        count = credit["over_limit_count"]
        out.append({"severity": "red",
                    "title": (f"{count} customer{'s' if count != 1 else ''} "
                              f"{'are' if count != 1 else 'is'} over their credit limit"),
                    "detail": f"{_inr(credit['over_limit_amount'])} above the approved limits.",
                    "href": f"{base_url}/ui/#/accounts", "link": "Open credit use"})
    accounts = data.get("accounts")
    if accounts and Decimal(accounts["payables"]["due_this_week"] or 0) > 0:
        out.append({"severity": "amber",
                    "title": "Payables falling due within 7 days",
                    "detail": (f"{_inr(accounts['payables']['due_this_week'])} estimated "
                               "from current supplier terms."),
                    "href": f"{base_url}/ui/#/accounts", "link": "Open payables"})
    return out


def _inr(value) -> str:
    """Indian digit grouping with the rupee sign: 12,34,567.00."""
    amount = Decimal(value or 0)
    sign = "-" if amount < 0 else ""
    whole, _, paise = f"{abs(amount):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return f"{sign}₹ {whole}.{paise}"


def _weekly_buckets(start: date, end: date, sales: dict, purchases: dict) -> list[dict]:
    days = (end - start).days + 1
    rows = []
    if days <= 14:
        cursor = start
        while cursor <= end:
            rows.append({"label": cursor.strftime("%d %b"),
                         "sales": _money(sales.get(cursor, 0)),
                         "purchases": _money(purchases.get(cursor, 0))})
            cursor += timedelta(days=1)
        return rows
    cursor = start
    index = 1
    while cursor <= end:
        stop = min(cursor + timedelta(days=6), end)
        rows.append({"label": f"W{index} {cursor.strftime('%d %b')}",
                     "sales": _money(sum((sales.get(d, 0) for d in _days(cursor, stop)), ZERO)),
                     "purchases": _money(sum((purchases.get(d, 0) for d in _days(cursor, stop)), ZERO))})
        cursor = stop + timedelta(days=1)
        index += 1
    return rows


def _days(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def _top_customers(db: Session, start: date, end: date, limit: int = 6) -> list[dict]:
    rows = db.execute(
        select(Distributor.id, Distributor.name, func.count(Invoice.id),
               func.coalesce(func.sum(Invoice.grand_total), 0))
        .join(Invoice, Invoice.distributor_id == Distributor.id)
        .where(Invoice.status == "issued", Invoice.invoice_date >= start,
               Invoice.invoice_date <= end)
        .group_by(Distributor.id, Distributor.name)
        .order_by(func.sum(Invoice.grand_total).desc(), Distributor.id.asc())
        .limit(limit)).all()
    return [{"id": did, "name": name, "invoices": int(count), "value": _money(total)}
            for did, name, count, total in rows]


def _states(db: Session, start: date, end: date) -> dict:
    from ..api.dashboard import _geo_states  # one grouping rule for map and email

    rows = [r for r in _geo_states(db, start, end) if r["_sales"] > 0]
    rows.sort(key=lambda r: (-r["_sales"], r["key"]))
    top = [{"name": r["name"], "value": _money(r["_sales"])} for r in rows[:5]]
    positive = [r for r in rows if r["_sales"] > 0]
    bottom = [{"name": r["name"], "value": _money(r["_sales"])} for r in positive[-5:]]
    return {"top": top, "bottom": bottom,
            "note": "Buyer state from the issued invoice snapshot."}


def build(db: Session, pack_key: str, start: date, end: date, *,
          include_accounts: bool = True, custom_reports: list[str] | None = None,
          base_url: str | None = None, generated_at: datetime | None = None) -> dict:
    meta = pack_meta(pack_key)
    if pack_key == "hr":
        from . import hr_pack
        return hr_pack.build(db, start, end, base_url=base_url, generated_at=generated_at)
    # The comparison windows are measured from the actual window, not recomputed
    # from its end date: a weekly pack must compare with the seven days before it.
    length = (end - start).days + 1
    previous = (start - timedelta(days=length), start - timedelta(days=1))
    last_year = (_last_year(start), _last_year(end))
    perms = {"sales:read", "stock:read", "lead:read", "accounts:reports"}
    stats = period_stats(db, start, end, perms)
    prev_stats = period_stats(db, previous[0], previous[1], perms)
    year_stats = period_stats(db, last_year[0], last_year[1], perms)
    collections = _sum_payments(db, "receipt", start, end)
    prev_collections = _sum_payments(db, "receipt", previous[0], previous[1])
    year_collections = _sum_payments(db, "receipt", last_year[0], last_year[1])

    accounts = (accounting.window(db, start, end)
                if include_accounts and meta["accounts"] else None)
    profit = profit_loss.statement(db, start, end) if accounts else None
    balance = balance_sheet.balance_sheet(db, end) if accounts else None
    prev_profit = profit_loss.statement(db, *previous) if profit else None
    year_profit = profit_loss.statement(db, *last_year) if profit else None
    ageing_window = accounts["outstanding"] if accounts else _ageing(db, end)
    position = _attendance(db)

    sales_days = sales_by_day(db, start, end)
    purchase_days = purchases_by_day(db, start, end)
    series = _weekly_buckets(start, end, sales_days, purchase_days)
    ageing = ageing_window
    overdue_60 = ageing["overdue_60"] if "overdue_60" in ageing else _overdue_60(db, end)

    gross = profit["gross_profit"] if profit else None
    expense = profit["expenses"] if profit else None
    net = profit["net_profit"] if profit else None
    first_gap = (profit["gaps"][0]["code"] if profit and profit["gaps"] else "GAP-P01")

    kpis = [
        _kpi("sales", "Sales", stats["sales"], _inr(stats["sales"]), prev_stats["sales"],
             note="Issued invoices, including GST."),
        _kpi("purchases", "Purchases", stats["purchases"], _inr(stats["purchases"]),
             prev_stats["purchases"], note="Goods received, valued at order cost."),
        _kpi("orders", "Sales orders", stats["orders"], str(stats["orders"]),
             prev_stats["orders"], unit="count", note="Orders created in the window."),
        _kpi("collections", "Collections", collections["total"],
             _inr(collections["total"]), prev_collections["total"],
             note="Receipts dated in the window."),
        _kpi("returns", "Returns", stats["returns"], _inr(stats["returns"]),
             prev_stats["returns"], good_when_up=False, note="Issued credit notes."),
        _kpi("outstanding", "Receivables outstanding", ageing["total"],
             _inr(ageing["total"]), None, note="As at the window end."),
        _kpi("gross_margin", "Gross profit",
             float(gross["value"]) if gross else None,
             _inr(gross["value"]) if gross else "No data yet", None,
             note=(gross["label"] + "; revenue less returns and cost of goods."
                   if gross else "Cost of goods is not captured."),
             gap=None if gross else "GAP-P01"),
        _kpi("expenses", "Expenses",
             float(expense["total"]) if expense and expense["complete"] else None,
             _inr(expense["total"]) if expense and expense["complete"] else "No data yet",
             None, note=("Approved entries; non-creditable GST is cost."
                         if expense and expense["complete"] else
                         "Expenses are not tracked for the whole window."),
             gap=None if expense and expense["complete"] else "GAP-P02"),
        _kpi("net_profit", "Net profit",
             float(net["value"]) if net and net["available"] else None,
             _inr(net["value"]) if net and net["available"] else "No data yet", None,
             note=("Gross profit less expenses and payroll."
                   if net and net["available"] else
                   "Not shown until cost, expenses and payroll are complete."),
             gap=None if net and net["available"] else first_gap),
    ]

    comparison = []
    for key, label, cur, prev, year, good_up in (
            ("sales", "Sales", stats["sales"], prev_stats["sales"], year_stats["sales"], True),
            ("purchases", "Purchases", stats["purchases"], prev_stats["purchases"],
             year_stats["purchases"], False),
            ("orders", "Orders", stats["orders"], prev_stats["orders"], year_stats["orders"], True),
            ("collections", "Collections", collections["total"], prev_collections["total"],
             year_collections["total"], True),
            ("returns", "Returns", stats["returns"], prev_stats["returns"],
             year_stats["returns"], False),
            ("outstanding", "Receivables outstanding", ageing["total"], None, None, False)):
        comparison.append({"key": key, "label": label,
                           "current": _money(cur),
                           "previous": _money(prev) if prev is not None else None,
                           "last_year": _money(year) if year is not None else None,
                           "previous_change": change(cur, prev) if prev is not None else None,
                           "last_year_change": change(cur, year) if year is not None else None,
                           "direction": _direction(change(cur, prev), good_up)
                           if prev is not None else _direction(None)})
    if profit:
        def profit_value(statement, key):
            if statement is None:
                return None
            if key == "expenses":
                return (float(statement["expenses"]["total"])
                        if statement["expenses"]["complete"] else None)
            if key == "net_profit":
                return (float(statement["net_profit"]["value"])
                        if statement["net_profit"]["available"] else None)
            return float(statement["gross_profit"]["value"])

        for key, label in (("gross_profit", "Gross profit"),
                           ("expenses", "Expenses"),
                           ("net_profit", "Net profit")):
            cur = profit_value(profit, key)
            prev = profit_value(prev_profit, key)
            year = profit_value(year_profit, key)
            comparison.append({
                "key": key, "label": label,
                "current": _money(cur) if cur is not None else None,
                "previous": _money(prev) if prev is not None else None,
                "last_year": _money(year) if year is not None else None,
                "previous_change": (change(cur, prev)
                                    if cur is not None and prev is not None else None),
                "last_year_change": (change(cur, year)
                                     if cur is not None and year is not None else None),
                "direction": (_direction(change(cur, prev))
                              if cur is not None and prev is not None
                              else _direction(None)),
                "gap": None if cur is not None else (
                    "GAP-P02" if key == "expenses" else first_gap),
            })

    ageing_rows = [
        {"key": b["key"], "label": b["label"], "total": b["total"], "count": b["count"],
         "share": b.get("share")}
        for b in (ageing.get("buckets") or _buckets(db, end))
    ]
    top_products = [{"name": r["name"], "sku": r["sku"], "qty": r["qty"],
                     "value": r["revenue"]}
                    for r in _top_products(db, start, end)]
    data = {
        "pack_key": pack_key, "label": meta["label"], "company": company_name(db),
        "trend": accounting.monthly_series(db, end.replace(day=1)) if accounts else [],
        "from": start.isoformat(), "to": end.isoformat(),
        "period_label": _window_label(start, end),
        "generated_at": (generated_at or datetime.now()).isoformat(),
        "stats": {k: _money(v) if isinstance(v, Decimal) else v for k, v in stats.items()},
        "kpis": kpis, "comparison": comparison, "series": series,
        "ageing": {**ageing, "buckets": ageing_rows},
        "top_products": top_products, "top_customers": _top_customers(db, start, end),
        "states": _states(db, start, end), "accounts": accounts,
        "profit": _profit_data(profit),
        "credit": accounts["credit"] if accounts else None,
        "position": position,
        "unavailable": accounting.UNAVAILABLE if include_accounts else [],
        "balance_sheet": balance,
        "notes": ((accounts["notes"] + (profit["notes"] if profit else [])
                   + (balance["warnings"] if balance else []))
                  if accounts else [
                      "Sales are tax-inclusive; purchases are valued at order cost, "
                      "exclusive of tax.",
                      "Profit and loss is not included because the Accounts section "
                      "is switched off for this pack.",
                  ]),
        "gaps": ((accounts["gaps"] + (profit["gaps"] if profit else []))
                 if accounts else []),
        "custom_reports": custom_reports or [],
        "attachments": [],
        "base_url": base_url or settings.app_base_url,
    }
    data["attention"] = _attention(db, data, data["base_url"])
    return data


def _ageing(db: Session, as_of: date) -> dict:
    a = ledger.ageing_rows(db, as_of)
    total = a["total"]
    overdue = sum((b["total"] for b in a["buckets"] if b["key"] in ("61-90", "90+")), ZERO)
    return {"total": _money(total), "count": a["count"], "overdue_60": _money(overdue),
            "buckets": [{"key": b["key"], "label": b["label"], "total": _money(b["total"]),
                         "count": b["count"],
                         "share": round(float(b["total"] / total * 100), 1) if total else 0.0}
                        for b in a["buckets"]]}


def _buckets(db: Session, as_of: date) -> list[dict]:
    return _ageing(db, as_of)["buckets"]


def _overdue_60(db: Session, as_of: date) -> str:
    return _ageing(db, as_of)["overdue_60"]


def _top_products(db: Session, start: date, end: date) -> list[dict]:
    from ..api.dashboard import _top_products as top
    return top(db, start, end)["rows"]


# ----------------------------------------------------------------- attachments
def _file_period(start: date, end: date, pack_key: str) -> str:
    if start == end:
        return start.strftime("%Y-%m-%d")
    if PACKS[pack_key]["period"] == "month":
        return start.strftime("%Y-%m")
    return f"{start:%Y-%m-%d}_to_{end:%Y-%m-%d}"


def _slug(label: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in label).strip("_")


def _summary_rep(data: dict) -> dict:
    comparison = [{"metric": r["label"],
                   "current": r["current"] if r.get("current") is not None else "No data yet",
                   "previous": r.get("previous") if r.get("previous") is not None else "No data yet",
                   "last_year": r.get("last_year") if r.get("last_year") is not None else "No data yet",
                   "change": (f"{r['previous_change']:+.1f}%" if r.get("previous_change") is not None
                              else "No prior figure")}
                  for r in data["comparison"]]
    ageing = [{"bucket": r["label"], "amount": r["total"], "count": r["count"]}
              for r in data["ageing"]["buckets"]]
    products = [{"product": r["name"], "sku": r["sku"], "units": r["qty"],
                 "value": r["value"]} for r in data["top_products"]]
    attention = [{"severity": r["severity"], "item": r["title"], "detail": r["detail"]}
                 for r in data["attention"]]
    tables = [
        {"key": "comparison", "title": "Comparison",
         "columns": [{"key": "metric", "label": "Metric", "type": "text"},
                     {"key": "current", "label": "Current", "type": "text"},
                     {"key": "previous", "label": "Previous", "type": "text"},
                     {"key": "last_year", "label": "Same period last year", "type": "text"},
                     {"key": "change", "label": "Change", "type": "text"}],
         "rows": comparison, "totals": None},
        {"key": "ageing", "title": "Receivables ageing",
         "columns": [{"key": "bucket", "label": "Bucket", "type": "text"},
                     {"key": "amount", "label": "Outstanding", "type": "money"},
                     {"key": "count", "label": "Invoices", "type": "int"}],
         "rows": ageing, "totals": None},
    ]
    if products:
        tables.append({"key": "products", "title": "Top products",
                       "columns": [{"key": "product", "label": "Product", "type": "text"},
                                   {"key": "sku", "label": "SKU", "type": "text"},
                                   {"key": "units", "label": "Units", "type": "qty"},
                                   {"key": "value", "label": "Taxable value", "type": "money"}],
                       "rows": products, "totals": None})
    if attention:
        tables.append({"key": "attention", "title": "Needs attention",
                       "columns": [{"key": "severity", "label": "Severity", "type": "text"},
                                   {"key": "item", "label": "Item", "type": "text"},
                                   {"key": "detail", "label": "Detail", "type": "text"}],
                       "rows": attention, "totals": None})
    if data.get("accounts"):
        acc = data["accounts"]
        profit = data.get("profit") or {}
        gaps = profit.get("gaps") or []
        first_gap = gaps[0]["code"] if gaps else "GAP-P01"
        sheet = data.get("balance_sheet") or {}
        totals = sheet.get("totals") or {}
        assets = totals.get("asset")
        owed = (None if assets is None else
                totals["liability"] + totals["equity"]
                + totals["retained_earnings"])

        def shown(key):
            return profit.get(key) if profit.get(key) is not None else "No data yet"

        tables.append({"key": "accounts", "title": "Accounts summary",
                       "columns": [{"key": "metric", "label": "Metric", "type": "text"},
                                   {"key": "value", "label": "Value", "type": "text"},
                                   {"key": "gap", "label": "Gap", "type": "text"}],
                       "rows": [
                           {"metric": "Revenue (taxable)", "value": acc["revenue"]["taxable"], "gap": ""},
                           {"metric": "Collections", "value": acc["collections"]["total"], "gap": ""},
                           {"metric": "Returns", "value": acc["returns"]["value"], "gap": ""},
                           {"metric": "Output GST", "value": acc["output_gst"]["total"], "gap": ""},
                           {"metric": "Net GST payable",
                            "value": (acc["net_gst"]["net_total"]
                                      if acc["net_gst"]["available"] else "No data yet"),
                            "gap": ""},
                           {"metric": "Receivables outstanding", "value": acc["outstanding"]["total"], "gap": ""},
                           {"metric": "Payables outstanding", "value": acc["payables"]["total"], "gap": ""},
                           {"metric": profit.get("gross_profit_label", "Gross profit"),
                            "value": shown("gross_profit"),
                            "gap": "" if profit.get("gross_profit") is not None else "GAP-P01"},
                           {"metric": "Expenses", "value": shown("expenses"),
                            "gap": "" if profit.get("expenses") is not None else "GAP-P02"},
                           {"metric": "Payroll (gross)", "value": shown("payroll"),
                            "gap": "" if profit.get("payroll") is not None else "GAP-P03"},
                           {"metric": "Net profit", "value": shown("net_profit"),
                            "gap": ("" if profit.get("net_profit") is not None
                                    else first_gap)},
                           {"metric": "Balance sheet · total assets",
                            "value": _money(assets) if assets is not None else "No data yet",
                            "gap": "" if assets is not None else "GAP-A10"},
                           {"metric": "Balance sheet · liabilities, equity and earnings",
                            "value": _money(owed) if owed is not None else "No data yet",
                            "gap": "" if owed is not None else "GAP-A10"},
                           {"metric": "Balance sheet · difference",
                            "value": (_money(totals["difference"])
                                      if totals.get("difference") is not None
                                      else "No data yet"),
                            "gap": ("" if totals.get("balanced") is not False
                                    else "Partial")},
                       ], "totals": None})

    checks = []
    if data.get("accounts"):
        checks.append({"name": "Trial balance debits equal credits",
                       "report_label": "Debits",
                       "report_value": data["accounts"]["trial_balance"]["debit_total"],
                       "record_label": "Credits",
                       "record_value": data["accounts"]["trial_balance"]["credit_total"],
                       "unit": "amount",
                       "ok": bool(data["accounts"]["trial_balance"]["balanced"])})
    profit = data.get("profit")
    if profit:
        gross = Decimal(profit["gross_profit"])
        expected_gross = Decimal(profit["net_revenue"]) - Decimal(profit["cogs"])
        checks.append({"name": "Gross profit arithmetic",
                       "report_label": "Gross profit", "report_value": gross,
                       "record_label": "Net revenue less cost of goods",
                       "record_value": expected_gross, "unit": "amount",
                       "ok": gross == expected_gross})
        if profit.get("net_profit_available"):
            net = Decimal(profit["net_profit"])
            expected_net = (gross - Decimal(profit["expenses"] or 0)
                            - Decimal(profit["payroll"] or 0))
            checks.append({"name": "Net profit arithmetic",
                           "report_label": "Net profit", "report_value": net,
                           "record_label": "Gross profit less expenses and payroll",
                           "record_value": expected_net, "unit": "amount",
                           "ok": net == expected_net})
    return {"title": f"{data['company']} — {data['label']}",
            "kind": "period", "period_from": date.fromisoformat(data["from"]),
            "period_to": date.fromisoformat(data["to"]),
            "as_at": date.fromisoformat(data["to"]),
            "checks": checks,
            "tables": tables,
            "limitations": data["notes"] + [
                "A closed financial year refuses dated documents until the "
                "Administrator reopens it; a locked accounting month stays the "
                "narrower gate for corrections."]}


def build_attachments(db: Session, data: dict, pack_key: str) -> list[dict]:
    """PDF for reading and Excel for detail, inside the size budget."""
    if data.get("hr_pack"):
        from . import hr_pack
        return hr_pack.build_attachments(db, data)
    if not data.get("include_attachments", True):
        return []
    period = _file_period(date.fromisoformat(data["from"]),
                          date.fromisoformat(data["to"]), pack_key)
    base = f"HERBANOVA_{_slug(data['label']).replace('_Report', '')}_{period}"
    rep = _summary_rep(data)
    files: list[dict] = []
    try:
        pdf = reports_pdf.to_pdf(rep, "comparison", "Scheduled reports")
        files.append({"filename": f"{base}.pdf", "content_type": "application/pdf",
                      "bytes": pdf, "kind": "summary",
                      "contains": "Summary, comparison, ageing, top products, accounts",
                      "rows": sum(len(t["rows"]) for t in rep["tables"])})
    except Exception as exc:                    # a missing attachment must not stop the email
        data.setdefault("attachment_errors", []).append(f"PDF not built: {exc}")
    try:
        xlsx = exports.to_xlsx(rep, "Scheduled reports")
        files.append({"filename": f"{base}_Detail.xlsx",
                      "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      "bytes": xlsx, "kind": "detail",
                      "contains": "Every table in this email, one sheet each",
                      "rows": sum(len(t["rows"]) for t in rep["tables"])})
    except Exception as exc:
        data.setdefault("attachment_errors", []).append(f"Excel not built: {exc}")

    keys = list(data.get("custom_reports") or []) or list(PACKS[pack_key]["reports"])
    for key in keys[:2]:
        try:
            report = reports.build(db, key, date.fromisoformat(data["from"]),
                                   date.fromisoformat(data["to"]))
            table = report["tables"][0] if report["tables"] else None
            if not table:
                continue
            payload = exports.to_xlsx(report, "Scheduled reports")
            files.append({"filename": f"HERBANOVA_{_slug(report['title'])}_{period}.xlsx",
                          "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          "bytes": payload, "kind": "register",
                          "contains": table["title"],
                          "rows": len(table["rows"])})
        except Exception as exc:
            data.setdefault("attachment_errors", []).append(f"{key} not attached: {exc}")

    budget = int(settings.email_max_bytes)
    dropped = []
    while files and sum(len(f["bytes"]) for f in files) > budget:
        victim = next((f for f in reversed(files) if f["kind"] == "register"), None)
        if victim is None:
            victim = next((f for f in reversed(files) if f["kind"] == "detail"), None)
        if victim is None:
            victim = files.pop()
        else:
            files.remove(victim)
        dropped.append(victim["filename"])
    if dropped:
        data.setdefault("attachment_notes", []).append(
            "These files were too large to attach: " + ", ".join(dropped)
            + ". Open them from Reports.")
    return files


def subject(data: dict) -> str:
    if data.get("hr_pack"):
        from . import hr_pack
        return hr_pack.subject_line(data)
    sales = next((k for k in data["kpis"] if k["key"] == "sales"), None)
    parts = ["HERBANOVA", data["label"], data["period_label"]]
    if sales and sales["available"]:
        amount = _inr(sales["value"])
        change_text = ""
        if sales["change"] is not None:
            change_text = f" ({sales['direction']['arrow']} {abs(sales['change']):.1f}% MoM)"
        parts.append(f"Sales {amount}{change_text}")
    return " | ".join(parts)
