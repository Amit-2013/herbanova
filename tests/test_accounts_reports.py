"""Accounts reports: the dashboard, the comparisons and the email block.

Every figure in these tests is compared with the statement it is built from,
so a screen can never show a number the documents do not support.
"""
from datetime import date, timedelta
from decimal import Decimal

from app.core.db import SessionLocal
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
    report = _report(client)
    rows = {r["key"]: r for r in report["profit_and_loss"]["rows"]}
    assert rows["expenses"]["available"] is False
    assert rows["expenses"]["value"] is None
    assert rows["expenses"]["gap"] == "GAP-P02"
    assert rows["net_profit"]["available"] is False
    assert rows["net_profit"]["value"] is None
    pl_gaps = report["profit_and_loss"]["gaps"]
    assert rows["net_profit"]["gap"] == pl_gaps[0]["code"]
    assert report["net_profit"]["available"] is False
    codes = {g["code"] for g in pl_gaps}
    # Expenses and payroll are incomplete; an earlier invoice without a stock
    # issue also leaves cost incomplete, and that gap comes first.
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
