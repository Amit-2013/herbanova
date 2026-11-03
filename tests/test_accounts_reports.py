"""Accounts reports: the dashboard, the comparisons and the email block.

Every figure in these tests is compared with the statement it is built from,
so a screen can never show a number the documents do not support.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.accounts import Payment
from app.models.core import CreditNote, Invoice, User
from app.services import report_packs

from test_dashboard_v2 import _invoice

TODAY = date.today()
DAY = TODAY - timedelta(days=1)


def _report(client, **params):
    params.setdefault("from_date", DAY.isoformat())
    params.setdefault("to_date", DAY.isoformat())
    res = client.as_user("admin").get("/api/accounts/report", params=params)
    assert res.status_code == 200, res.text
    return res.json()


# --- permission, the server-side gate --------------------------------------

def test_accounts_report_needs_accounts_reports_not_just_read(client, world):
    # The sales desk can read outstanding, but not the Accounts dashboard.
    assert client.as_user("sales").get("/api/accounts/outstanding").status_code == 200
    forbidden = client.get("/api/accounts/report")
    assert forbidden.status_code == 403
    assert client.get("/api/accounts/report/compare").status_code == 403
    assert client.as_user("viewer").get("/api/accounts/report").status_code == 403
    assert client.as_user("admin").get("/api/accounts/report").status_code == 200


def test_dates_and_state_codes_are_validated(client, world):
    admin = client.as_user("admin")
    assert admin.get("/api/accounts/report", params={
        "from_date": "2026-01-10", "to_date": "2026-01-01"}).status_code == 422
    assert admin.get("/api/accounts/report", params={
        "to_date": (TODAY + timedelta(days=1)).isoformat()}).status_code == 422
    assert admin.get("/api/accounts/report", params={
        "from_date": DAY.isoformat(), "to_date": DAY.isoformat(),
        "state": "abc"}).status_code == 422
    assert admin.get("/api/accounts/report/compare", params={
        "mode": "weekly"}).status_code == 422


# --- figures reconcile with the statements ---------------------------------

def test_report_figures_match_the_ageing_and_trial_balance(client, world):
    grand = Decimal("2500.00")
    _invoice(world, DAY, grand)
    report = _report(client)

    ageing = client.get("/api/accounts/ageing", params={"as_of": DAY.isoformat()}).json()
    assert Decimal(report["outstanding"]["total"]) == Decimal(str(ageing["total"]))
    assert Decimal(report["outstanding"]["total"]) >= grand

    tb = report["trial_balance"]
    assert tb["balanced"] is True
    assert Decimal(tb["debit_total"]) == Decimal(tb["credit_total"])
    assert Decimal(report["revenue"]["taxable"]) >= grand


def test_overview_accounts_tiles_match_the_accounts_report(client, world):
    _invoice(world, DAY, Decimal("1800.00"))
    report = _report(client)
    dash = client.as_user("admin").get(
        "/api/dashboard", params={"from_date": DAY.isoformat(),
                                  "to_date": DAY.isoformat()}).json()
    assert dash["accounts"] is not None
    assert Decimal(dash["accounts"]["receivable_total"]) == Decimal(report["outstanding"]["total"])
    assert Decimal(dash["accounts"]["payable_total"]) == Decimal(report["payables"]["total"])
    assert Decimal(dash["accounts"]["cash_bank_net"]) == Decimal(report["cash_bank_net"])
    assert dash["accounts"]["net_profit"] is None
    # The tile names the same first gap as the statement it was built from.
    assert dash["accounts"]["net_profit_gap"] \
        == report["profit_and_loss"]["gaps"][0]["code"]


def test_region_filter_narrows_flows_and_leaves_balances(client, world):
    _invoice(world, DAY, Decimal("1200.00"))
    everything = _report(client)
    same_state = _report(client, state="27")
    other_state = _report(client, state="29")

    assert Decimal(same_state["revenue"]["taxable"]) == Decimal(everything["revenue"]["taxable"])
    assert Decimal(other_state["revenue"]["taxable"]) == 0
    assert Decimal(other_state["output_gst"]["total"]) == 0
    # Balances are company-wide and say so instead of pretending to be filtered.
    assert Decimal(same_state["outstanding"]["total"]) == Decimal(everything["outstanding"]["total"])
    assert same_state["region"]["state"] == "27"
    assert "company-wide" in same_state["region"]["not_applied_to"]


def test_states_and_trend_carry_the_same_money(client, world):
    _invoice(world, DAY, Decimal("900.00"))
    report = _report(client)
    state_total = sum(Decimal(s["revenue"]) for s in report["states"])
    assert state_total == Decimal(report["revenue"]["taxable"])

    month = f"{DAY.year}-{DAY.month:02d}"
    trend = next(r for r in report["trend"]
                 if f"{r['year']}-{r['month']:02d}" == month)
    assert Decimal(trend["revenue"]) >= Decimal("900.00")
    assert Decimal(trend["net_cash"]) == Decimal(trend["collections"]) - Decimal(trend["payments"])


def test_missing_expenses_and_profit_are_gaps_not_zeroes(client, world):
    # A window with no expense tracking and no payroll period at all: both are
    # named as gaps, never printed as zero.
    report = _report(client, from_date="2001-02-01", to_date="2001-02-28")
    rows = {r["key"]: r for r in report["profit_and_loss"]["rows"]}
    assert rows["expenses"]["available"] is False
    assert rows["expenses"]["value"] is None
    assert rows["expenses"]["gap"] == "GAP-P02"
    assert rows["payroll"]["available"] is False
    assert rows["payroll"]["value"] is None
    assert rows["payroll"]["gap"] == "GAP-P03"
    assert rows["net_profit"]["available"] is False
    assert rows["net_profit"]["value"] is None
    pl_gaps = report["profit_and_loss"]["gaps"]
    assert rows["net_profit"]["gap"] == pl_gaps[0]["code"]
    assert report["net_profit"]["available"] is False
    codes = {g["code"] for g in pl_gaps}
    assert {"GAP-P02", "GAP-P03"} <= codes
    assert not {"GAP-A01", "GAP-A02"} & codes


# --- month on month and year on year ---------------------------------------

def test_compare_reports_both_modes_and_no_percentage_against_zero(client, world):
    admin = client.as_user("admin")
    for mode in ("full_month", "mtd"):
        res = admin.get("/api/accounts/report/compare", params={
            "mode": mode, "month": "2001-02"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["mode"] == mode
        assert body["month_state"] == "past"
        revenue = next(m for m in body["metrics"] if m["key"] == "revenue")
        assert Decimal(revenue["current"]) == 0
        assert revenue["previous_change"] is None
        assert revenue["last_year_change"] is None
        gaps = {m["key"]: m.get("gap") for m in body["metrics"]}
        assert gaps["expenses"] == "GAP-P02"
        assert gaps["net_profit"] == "GAP-P02"
        assert body["current"]["trial_balance"]["balanced"] is True


# --- the email block uses the same figures ---------------------------------

def test_email_accounts_block_matches_the_report(client, world):
    _invoice(world, DAY, Decimal("1600.00"))
    with SessionLocal() as db:
        data = report_packs.build(db, "daily", DAY, DAY)
    report = _report(client)
    assert Decimal(data["accounts"]["revenue"]["taxable"]) \
        == Decimal(report["revenue"]["taxable"])
    assert Decimal(data["accounts"]["outstanding"]["total"]) \
        == Decimal(report["outstanding"]["total"])
    assert Decimal(data["accounts"]["output_gst"]["total"]) \
        == Decimal(report["output_gst"]["total"])
    assert data["accounts"]["trial_balance"]["balanced"] is True


# --- receivables by distributor: the statement in its own section ----------

def _rbd(client, **params):
    res = client.as_user("admin").get("/api/accounts/receivables-by-distributor",
                                      params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _row(body, distributor_id):
    return next(r for r in body["rows"] if r["distributor_id"] == distributor_id)


def test_receivables_by_distributor_permissions_and_dates(client, world):
    # The statements are on accounts:read, so the sales desk may read this report;
    # a viewer has no accounts right at all.
    assert client.as_user("sales").get(
        "/api/accounts/receivables-by-distributor").status_code == 200
    assert client.as_user("viewer").get(
        "/api/accounts/receivables-by-distributor").status_code == 403
    admin = client.as_user("admin")
    assert admin.get("/api/accounts/receivables-by-distributor", params={
        "from_date": "2026-01-10", "to_date": "2026-01-01"}).status_code == 422
    assert admin.get("/api/accounts/receivables-by-distributor", params={
        "to_date": (TODAY + timedelta(days=1)).isoformat()}).status_code == 422


def test_receivables_by_distributor_opening_plus_movements_is_closing(client, world):
    _invoice(world, date(2019, 4, 10), Decimal("700.00"))
    _invoice(world, date(2019, 5, 10), Decimal("300.00"))
    body = _rbd(client, from_date="2019-05-01", to_date="2019-05-31")
    row = _row(body, world["distributor_id"])
    assert Decimal(row["opening"]) >= Decimal("700.00")
    assert Decimal(row["invoiced"]) >= Decimal("300.00")
    assert row["invoices"] >= 1
    for r in body["rows"]:
        assert Decimal(r["closing"]) == (
            Decimal(r["opening"]) + Decimal(r["invoiced"]) + Decimal(r["debited"])
            - Decimal(r["credited"]) - Decimal(r["received"]))
    assert Decimal(body["totals"]["closing"]) == sum(
        (Decimal(r["closing"]) for r in body["rows"]), Decimal("0"))
    assert body["count"] == len(body["rows"])


def test_receivables_by_distributor_closing_reconciles_with_outstanding(client, world):
    _invoice(world, DAY, Decimal("4321.00"))
    body = _rbd(client, from_date=DAY.isoformat(), to_date=DAY.isoformat())
    out = client.as_user("admin").get("/api/accounts/outstanding").json()
    assert Decimal(body["totals"]["closing"]) == Decimal(str(out["receivable_total"]))


def test_receivables_by_distributor_is_as_at_the_closing_date(client, world):
    # A receipt and a credit note dated after the closing date must not change
    # the earlier statement, and both must appear once the window reaches them.
    invoice_id, _ = _invoice(world, date(2019, 8, 10), Decimal("2200.00"))
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        invoice = db.get(Invoice, invoice_id)
        db.add(Payment(kind="receipt", distributor_id=world["distributor_id"],
                       invoice_id=invoice_id, amount=Decimal("500.00"),
                       paid_on=date(2019, 9, 5), mode="bank",
                       reference="RBD-ASAT", created_by=actor.id))
        db.add(CreditNote(
            credit_note_number=f"RBD{uuid4().hex[:6].upper()}"[:16],
            financial_year="2019-20", invoice_id=invoice_id,
            sales_order_id=invoice.sales_order_id,
            distributor_id=world["distributor_id"], status="issued",
            note_date=date(2019, 9, 5), reason="as-at test",
            taxable_value=Decimal("200.00"), grand_total=Decimal("200.00"),
            issued_by=actor.id))
        db.commit()
    at_august = _row(_rbd(client, from_date="2019-08-01", to_date="2019-08-31"),
                     world["distributor_id"])
    at_september = _row(_rbd(client, from_date="2019-08-01", to_date="2019-09-30"),
                        world["distributor_id"])
    assert Decimal(at_september["received"]) == Decimal(at_august["received"]) + Decimal("500.00")
    assert Decimal(at_september["credited"]) == Decimal(at_august["credited"]) + Decimal("200.00")
    assert Decimal(at_september["closing"]) == Decimal(at_august["closing"]) - Decimal("700.00")


def test_receivables_by_distributor_overdue_needs_a_due_date_before_the_close(client, world):
    invoice_id, _ = _invoice(world, date(2019, 7, 1), Decimal("640.00"))
    with SessionLocal() as db:
        db.get(Invoice, invoice_id).due_date = date(2019, 7, 15)
        db.commit()
    before_due = _row(_rbd(client, from_date="2019-07-01", to_date="2019-07-10"),
                      world["distributor_id"])
    after_due = _row(_rbd(client, from_date="2019-07-01", to_date="2019-07-31"),
                     world["distributor_id"])
    assert Decimal(before_due["overdue"]) == 0
    assert Decimal(after_due["overdue"]) >= Decimal("640.00")
    assert after_due["overdue_invoices"] >= 1


def test_receivables_by_distributor_empty_window_says_so(client, world):
    body = _rbd(client, from_date="2001-01-01", to_date="2001-12-31")
    assert body["rows"] == []
    assert body["count"] == 0
    assert Decimal(body["totals"]["closing"]) == 0
    assert "closing" in body["note"].lower()


# --- KPI cards: each one opens its own report ------------------------------

def test_each_kpi_card_opens_its_own_report_with_the_same_window(client, world):
    """A card carries the window to the report that proves it.

    The destinations are distinct: two cards that share a figure share a
    screen, but no card funnels every figure into one page.
    """
    start, end = date(2019, 8, 1), date(2019, 8, 31)
    res = client.as_user("admin").get("/api/accounts/report", params={
        "from_date": start.isoformat(), "to_date": end.isoformat()})
    assert res.status_code == 200, res.text
    cards = {c["key"]: c for c in res.json()["cards"]}
    window = f"?from={start.isoformat()}&to={end.isoformat()}"
    expected = {
        "revenue": f"#/accounts/gst-out{window}",
        "gst": f"#/accounts/gst-out{window}",
        "collections": f"#/accounts/cash{window}",
        "cash_bank": f"#/accounts/cash{window}",
        "outstanding": "#/accounts/receivables",
        "overdue_60": f"#/accounts/ageing?as_of={end.isoformat()}",
        "payables": "#/accounts/payables",
        "payable_week": "#/accounts/payables?due=week",
        "expenses": f"#/expenses{window}",
        "net_profit": "#/accounts/reports?focus=pnl",
    }
    for key, href in expected.items():
        assert cards[key]["href"] == href, key
    screens = {c["href"].split("?")[0] for c in cards.values()}
    assert len(screens) >= 5
