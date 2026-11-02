"""MoM/YoY comparison: one explicit mode, windows the user can read, and every
figure reconciled against the source tables or the invoice register."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models.core import Invoice, InvoiceLine, SalesOrder, User

TODAY = date.today()
FIRST = TODAY.replace(day=1)


def _month_end(first: date) -> date:
    nxt = date(first.year + (first.month // 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _shift(first: date, months: int) -> date:
    index = first.year * 12 + (first.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _compare(client, user="admin", **params):
    r = client.as_user(user).get("/api/dashboard/compare", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _card(body, key):
    return next(card for card in body["cards"] if card["key"] == key)


def _dec(value):
    return Decimal(str(value))


def _invoice(world, day: date, grand: Decimal, taxable: Decimal | None = None,
             product_id: int | None = None, sku: str | None = None) -> int:
    """A synthetic issued invoice on a chosen date, in the isolated test DB."""
    taxable = taxable if taxable is not None else grand
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        suffix = uuid4().hex[:6].upper()
        order = SalesOrder(so_number=f"T-CMP-{suffix}",
                           distributor_id=world["distributor_id"],
                           status="dispatched", total=grand, created_by=actor.id)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_number=f"C{suffix}"[:16], financial_year=f"{day.year}-{(day.year + 1) % 100:02d}",
            sales_order_id=order.id, distributor_id=world["distributor_id"],
            status="issued", invoice_date=day,
            place_of_supply_state_code="27", place_of_supply_kind="intra",
            seller_legal_name="Herbanova Test Co", buyer_name="Test distributor",
            taxable_value=taxable, grand_total=grand, issued_by=actor.id)
        db.add(invoice)
        db.flush()
        db.add(InvoiceLine(
            invoice_id=invoice.id,
            product_id=product_id if product_id is not None else world["product_id"],
            sku=sku or world["sku"], product_name="Test product",
            qty=Decimal("1"), unit_price=taxable, mrp=taxable,
            discount_percent=Decimal("0"), discount_amount=Decimal("0"),
            taxable_value=taxable, line_total=grand))
        db.commit()
        return invoice.id


def _issued_total(start: date, end: date) -> Decimal:
    with SessionLocal() as db:
        return db.scalar(
            select(func.coalesce(func.sum(Invoice.grand_total), 0)).where(
                Invoice.status == "issued", Invoice.invoice_date >= start,
                Invoice.invoice_date <= end)) or Decimal(0)


def _taxable_for_where(start: date, end: date, condition) -> Decimal:
    with SessionLocal() as db:
        return db.scalar(
            select(func.coalesce(func.sum(InvoiceLine.taxable_value), 0))
            .select_from(InvoiceLine)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(Invoice.status == "issued", Invoice.invoice_date >= start,
                   Invoice.invoice_date <= end, condition)) or Decimal(0)


def test_full_month_windows_default_to_the_current_month(client, world):
    body = _compare(client)
    assert body["mode"] == "full_month"
    assert body["month"] == f"{FIRST:%Y-%m}"
    assert body["month_state"] == "current"
    assert body["month_label"] == f"{FIRST:%B %Y}"

    ranges = body["ranges"]
    assert ranges["current"]["from"] == FIRST.isoformat()
    assert ranges["current"]["to"] == _month_end(FIRST).isoformat()
    assert ranges["previous"]["from"] == _shift(FIRST, -1).isoformat()
    assert ranges["previous"]["to"] == (FIRST - timedelta(days=1)).isoformat()
    assert ranges["last_year"]["from"] == _shift(FIRST, -12).isoformat()
    assert ranges["last_year"]["to"] == _month_end(_shift(FIRST, -12)).isoformat()
    assert ranges["elapsed_days"] == TODAY.day
    assert ranges["days_in_month"] == _month_end(FIRST).day


def test_mode_and_month_are_validated(client, world):
    admin = client.as_user("admin")
    assert admin.get("/api/dashboard/compare",
                     params={"mode": "weekly"}).status_code == 422
    assert admin.get("/api/dashboard/compare",
                     params={"month": "2026-13"}).status_code == 422
    assert admin.get("/api/dashboard/compare",
                     params={"month": "not-a-month"}).status_code == 422
    assert admin.get("/api/dashboard/compare",
                     params={"month": "1999-01"}).status_code == 422


def test_month_to_date_compares_the_same_day_and_caps_at_month_end(client, world):
    body = _compare(client, mode="mtd")
    assert body["mode"] == "mtd"
    ranges = body["ranges"]
    assert ranges["current"]["from"] == FIRST.isoformat()
    assert ranges["current"]["to"] == TODAY.isoformat()
    assert ranges["current"]["days"] == TODAY.day
    prev_first = _shift(FIRST, -1)
    expected = min(prev_first + timedelta(days=TODAY.day - 1), _month_end(prev_first))
    assert ranges["previous"]["to"] == expected.isoformat()

    # A past March compared in mtd mode: February has fewer days than March, so
    # the previous window stops on 29 February instead of spilling into March.
    body = _compare(client, mode="mtd", month="2024-03")
    assert body["month_state"] == "past"
    past = body["ranges"]
    assert past["current"]["days"] == 31
    assert past["previous"]["from"] == "2024-02-01"
    assert past["previous"]["to"] == "2024-02-29"
    assert past["last_year"]["from"] == "2023-03-01"
    assert past["last_year"]["to"] == "2023-03-31"


def test_sales_card_reconciles_with_the_invoice_register(client, world):
    current_day = TODAY
    previous_day = _shift(FIRST, -1) + timedelta(days=2)
    _invoice(world, current_day, Decimal("1000.00"), taxable=Decimal("900.00"))
    _invoice(world, previous_day, Decimal("500.00"), taxable=Decimal("450.00"))

    body = _compare(client)
    sales = _card(body, "sales")
    expected_current = _issued_total(FIRST, _month_end(FIRST))
    expected_previous = _issued_total(_shift(FIRST, -1), FIRST - timedelta(days=1))
    assert _dec(sales["current"]) == expected_current
    assert _dec(sales["previous"]) == expected_previous
    assert sales["current"] and sales["previous_change"] is not None

    # The invoice register over the same window, built by the reports endpoint.
    register = client.as_user("admin").get(
        "/api/reports/invoices",
        params={"from": body["ranges"]["current"]["from"],
                "to": body["ranges"]["current"]["to"]}).json()
    registered = sum((_dec(row["grand_total"]) for row in register["tables"][0]["rows"]
                      if row["status"] == "issued"), Decimal(0))
    assert registered == _dec(sales["current"])


def test_projection_is_labelled_an_estimate_and_uses_elapsed_days(client, world):
    current = _compare(client)["projection"]
    assert current["is_estimate"] is True
    assert current["complete"] is False
    assert current["elapsed_days"] == TODAY.day
    assert current["label"] == "Run-rate estimate (not a forecast)"

    past = _compare(client, month="2024-03")
    assert past["month_state"] == "past"
    assert past["projection"]["complete"] is True
    assert past["projection"]["is_estimate"] is False
    assert past["projection"]["label"] == "Complete month"
    assert _dec(past["projection"]["sales"]) == _dec(_card(past, "sales")["current"])

    future_first = _shift(FIRST, 1)
    future = _compare(client, month=f"{future_first:%Y-%m}")
    assert future["month_state"] == "future"
    assert future["projection"]["label"] == "Not started"
    assert _dec(future["projection"]["sales"]) == Decimal(0)


def test_trend_has_twelve_months_with_prior_year_and_moving_average(client, world):
    body = _compare(client)
    trend = body["trend"]
    rows = trend["months"]
    assert len(rows) == 12
    assert rows[-1]["month"] == f"{FIRST:%Y-%m}"

    for row in rows:
        month = date.fromisoformat(f"{row['month']}-01")
        expected = _issued_total(month, _month_end(month))
        assert _dec(row["sales"]) == expected, row["month"]
        prior = _shift(month, -12)
        assert _dec(row["prior_sales"]) == _issued_total(prior, _month_end(prior))

    last_three = [Decimal(r["sales"]) for r in rows[-3:]]
    expected_average = (sum(last_three, Decimal(0)) / 3).quantize(Decimal("0.01"))
    assert _dec(rows[-1]["moving_average"]) == expected_average

    if any(Decimal(r["sales"]) > 0 for r in rows):
        assert trend["best"] is not None and trend["worst"] is not None
        values = [Decimal(r["sales"]) for r in rows if Decimal(r["sales"]) > 0]
        assert _dec(trend["best"]["sales"]) == max(values)
        assert _dec(trend["worst"]["sales"]) == min(values)


def test_breakdowns_use_invoice_lines_and_reconcile(client, world):
    day = TODAY
    taxable = Decimal("900.00")
    _invoice(world, day, Decimal("1062.00"), taxable=taxable)

    body = _compare(client)
    perms = body["breakdowns"]
    start = date.fromisoformat(body["ranges"]["current"]["from"])
    end = date.fromisoformat(body["ranges"]["current"]["to"])

    products = perms["sales_by_product"]["rows"]
    product_row = next(r for r in products if world["sku"] in r["label"])
    expected_product = _taxable_for_where(
        start, end, InvoiceLine.product_id == world["product_id"])
    assert _dec(product_row["current"]) == expected_product
    assert product_row["share"] is not None and 0 < product_row["share"] <= 100

    distributors = perms["sales_by_distributor"]["rows"]
    distributor_row = next(r for r in distributors
                           if r["label"] == "Test distributor")
    expected_distributor = _taxable_for_where(
        start, end, Invoice.distributor_id == world["distributor_id"])
    assert _dec(distributor_row["current"]) == expected_distributor


def test_gap_cards_and_permission_masking(client, world):
    admin = _compare(client, user="admin")
    keys = {card["key"] for card in admin["cards"]}
    assert {"sales", "purchases", "orders", "gross_margin", "receipts",
            "returns", "new_leads", "new_customers"} <= keys
    assert _card(admin, "gross_margin")["available"] is False
    assert _card(admin, "gross_margin")["gap"] == "GAP-D04"
    assert _card(admin, "new_customers")["gap"] == "GAP-V16"
    assert admin["trend"]["sales_visible"] and admin["trend"]["purchases_visible"]

    # The viewer may read sales and stock but not leads; the leads card is not
    # in the payload at all, rather than sent as zero.
    viewer = _compare(client, user="viewer")
    viewer_keys = {card["key"] for card in viewer["cards"]}
    assert "new_leads" not in viewer_keys
    assert "sales" in viewer_keys and "purchases" in viewer_keys
    assert viewer["breakdowns"] is not None


def test_empty_windows_say_zero_and_never_infinity(client, world):
    body = _compare(client, month="2001-01")
    sales = _card(body, "sales")
    assert _dec(sales["current"]) == Decimal(0)
    assert _dec(sales["previous"]) == Decimal(0)
    assert sales["previous_change"] is None
    assert sales["last_year_change"] is None
    assert body["trend"]["best"] is None
    assert body["trend"]["worst"] is None
