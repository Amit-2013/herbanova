"""Overview dashboard (Phase 3): pipeline, customer/credit, PO ageing,
post-billing corrections and HR-today cards.

Expectations are recomputed from the database or from a sibling section, never
from a hard-coded production value.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select


def _dash(client, who="admin", **params):
    r = client.as_user(who).get("/api/dashboard", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _dec(value):
    return Decimal(str(value))


def test_insights_are_present_and_scoped_by_permission(client, world):
    admin = _dash(client, "admin")["insights"]
    assert admin["pipeline"]["sales"] and admin["pipeline"]["leads"]
    assert admin["customers"]["top"] is not None
    assert admin["customers"]["outstanding"] is not None
    assert admin["purchasing"] is not None
    assert admin["corrections"] is not None
    assert admin["hr"] is not None

    viewer = _dash(client, "viewer")["insights"]
    assert viewer["pipeline"]["sales"] is not None      # sales:read
    assert viewer["pipeline"]["leads"] is None          # no lead:read
    assert viewer["customers"]["top"] is not None       # sales:read
    assert viewer["customers"]["outstanding"] is None   # no accounts:read
    assert viewer["purchasing"] is not None             # stock:read
    assert viewer["corrections"] is not None            # sales:read
    assert viewer["hr"] is None                         # no hr:read

    inventory = _dash(client, "inventory")["insights"]
    assert inventory["pipeline"]["leads"] is None
    assert inventory["customers"]["outstanding"] is None
    assert inventory["hr"] is None

    # An HR manager sees the HR card but not the accounting side.
    hr = _dash(client, "hr_manager")["insights"]
    assert hr["hr"] is not None
    assert hr["customers"] is None or hr["customers"]["outstanding"] is None
    assert hr["pipeline"]["leads"] is None


def test_pipeline_counts_match_the_database(client, world):
    from app.core.db import SessionLocal
    from app.models.core import Lead, SalesOrder

    body = _dash(client)
    pipe = body["insights"]["pipeline"]
    with SessionLocal() as db:
        sales = dict(db.execute(select(SalesOrder.status, func.count())
                                .group_by(SalesOrder.status)).all())
        sales_value = db.scalar(select(func.coalesce(func.sum(SalesOrder.total), 0)))
        leads = dict(db.execute(select(Lead.status, func.count())
                                .group_by(Lead.status)).all())
        dispatched = db.execute(select(SalesOrder.created_at, SalesOrder.dispatched_at)
                                .where(SalesOrder.status == "dispatched",
                                       SalesOrder.dispatched_at.is_not(None))).all()
    days = [(done - raised).total_seconds() / 86400
            for raised, done in dispatched if raised and done and done >= raised]

    assert {r["status"]: r["count"] for r in pipe["sales"]["rows"]} == {
        key: int(sales.get(key, 0)) for key in
        ("draft", "pending_approval", "approved", "dispatched", "cancelled", "rejected")}
    assert pipe["sales"]["total"] == sum(r["count"] for r in pipe["sales"]["rows"])
    assert sum(_dec(r["value"]) for r in pipe["sales"]["rows"]) == _dec(sales_value)
    assert pipe["sales"]["dispatch"]["measured"] == len(days)
    expected_avg = round(sum(days) / len(days), 1) if days else None
    assert pipe["sales"]["dispatch"]["average_days"] == expected_avg
    assert {r["status"]: r["count"] for r in pipe["leads"]["rows"]} == {
        key: int(leads.get(key, 0)) for key in
        ("new", "contacted", "qualified", "won", "lost")}
    assert pipe["leads"]["total"] == sum(r["count"] for r in pipe["leads"]["rows"])


def test_customer_cards_reconcile_with_receivables_and_credit(client, world):
    from app.core.db import SessionLocal
    from app.models.core import Distributor, SalesOrder
    from app.services.sales import EXPOSURE_STATUSES

    body = _dash(client)
    customers = body["insights"]["customers"]

    # Outstanding uses the same receivable function as the ageing report.
    assert customers["outstanding_total"] == body["receivables_ageing"]["total"]
    for row in customers["outstanding"]:
        assert _dec(row["outstanding"]) > 0
        assert row["invoices"] >= 1

    # Credit in use matches the sales-order exposure for the named distributor.
    with SessionLocal() as db:
        for row in customers["credit"]:
            expected = _dec(db.scalar(
                select(func.coalesce(func.sum(SalesOrder.total), 0))
                .where(SalesOrder.distributor_id == row["distributor_id"],
                       SalesOrder.status.in_(EXPOSURE_STATUSES))))
            assert _dec(row["exposure"]) == expected, row
            limit = _dec(db.scalar(select(Distributor.credit_limit)
                                   .where(Distributor.id == row["distributor_id"])))
            assert _dec(row["credit_limit"]) == limit
            assert _dec(row["available"]) == max(limit - expected, Decimal(0))

    # Top customers come from issued invoices in the stated period and are ordered.
    revenues = [_dec(r["revenue"]) for r in customers["top"]]
    assert revenues == sorted(revenues, reverse=True)
    assert all(v > 0 for v in revenues)


def test_po_ageing_adds_up_to_the_open_orders(client, world):
    from app.core.db import SessionLocal
    from app.models.core import PurchaseOrder, PurchaseOrderLine

    body = _dash(client)
    purchasing = body["insights"]["purchasing"]
    assert purchasing["open_count"] == body["open_pos"]["count"]
    assert sum(r["count"] for r in purchasing["rows"]) == purchasing["open_count"]
    assert purchasing["no_receipt"] + purchasing["partial"] <= purchasing["open_count"]
    with SessionLocal() as db:
        open_ids = select(PurchaseOrder.id).where(
            PurchaseOrder.status.in_(("open", "partially_received")))
        ordered_value = db.scalar(
            select(func.coalesce(func.sum(PurchaseOrderLine.qty
                                          * func.coalesce(PurchaseOrderLine.unit_cost, 0)), 0))
            .where(PurchaseOrderLine.po_id.in_(open_ids)))
    assert sum(_dec(r["value"]) for r in purchasing["rows"]) == _dec(ordered_value)
    assert "GAP-D05" in purchasing["note"]


def test_corrections_reconcile_with_issued_notes(client, world):
    from app.core.db import SessionLocal
    from app.models.core import ApprovalRequest, CreditNote, DebitNote

    body = _dash(client)
    corrections = body["insights"]["corrections"]
    start = date.fromisoformat(body["from"])
    end = date.fromisoformat(body["to"])
    with SessionLocal() as db:
        for model, key in ((CreditNote, "credit_notes"), (DebitNote, "debit_notes")):
            count, value = db.execute(
                select(func.count(), func.coalesce(func.sum(model.grand_total), 0))
                .where(model.status == "issued", model.note_date >= start,
                       model.note_date <= end)).one()
            assert corrections[key]["count"] == count
            assert _dec(corrections[key]["value"]) == _dec(value)
            assert corrections[key]["shown"] == min(count, 6)
        post = db.scalar(
            select(func.count()).where(ApprovalRequest.record_type == "invoice_post_billing"))
    assert corrections["post_billing"]["count"] <= post
    assert corrections["post_billing"]["pending"] <= corrections["post_billing"]["count"]


def test_hr_today_reconciles_with_attendance_and_requests(client, world):
    from app.core.db import SessionLocal
    from app.models.hr import Attendance, LeaveApplication, ODRequest
    from app.models.users import Employee

    body = _dash(client)
    hr = body["insights"]["hr"]
    today = date.fromisoformat(hr["date"])
    with SessionLocal() as db:
        headcount = db.scalar(select(func.count()).where(Employee.status == "active"))
        marked = db.scalar(select(func.count()).where(Attendance.date == today))
        pending_leave = db.scalar(select(func.count())
                                  .where(LeaveApplication.status == "pending"))
        pending_od = db.scalar(select(func.count()).where(ODRequest.status == "pending"))
    assert hr["headcount"] == headcount
    assert hr["marked"] == marked
    assert sum(r["count"] for r in hr["attendance"]) == marked
    assert hr["leave_pending"] == pending_leave
    assert hr["od_pending"] == pending_od


def test_insight_card_shapes_are_stable(client, world):
    insights = _dash(client)["insights"]
    assert set(insights) == {"pipeline", "customers", "purchasing", "corrections", "hr"}
    pipeline = insights["pipeline"]
    assert set(pipeline) == {"sales", "leads"}
    for row in pipeline["sales"]["rows"]:
        assert set(row) == {"status", "label", "count", "value"}
    assert set(pipeline["sales"]["dispatch"]) == {
        "measured", "average_days", "approval_measured", "approval_average_days",
        "after_approval_measured", "after_approval_average_days", "delivery",
        "overdue_open", "note"}
    assert set(pipeline["sales"]["dispatch"]["delivery"]) == {
        "measured", "on_time", "late", "average_days_late"}
    for row in insights["purchasing"]["rows"]:
        assert set(row) == {"key", "label", "count", "value"}
    for key in ("credit_notes", "debit_notes"):
        assert set(insights["corrections"][key]) == {"label", "count", "value", "shown", "rows"}
    assert 0 <= insights["hr"]["not_marked"] <= insights["hr"]["headcount"]
