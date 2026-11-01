"""HR dashboard: range handling, scoping and the drill-through counts."""
from datetime import date, timedelta
from uuid import uuid4

from app.core.db import SessionLocal
from app.models.core import ApprovalRequest
from app.services.hr import IST
from datetime import datetime


def test_dashboard_rejects_impossible_ranges(client, world):
    admin = client.as_user("admin")
    today = date.today()
    r = admin.get("/api/hr/dashboard", params={
        "from_date": today.isoformat(), "to_date": (today - timedelta(days=1)).isoformat()})
    assert r.status_code == 422
    r = admin.get("/api/hr/dashboard", params={
        "from_date": (today - timedelta(days=400)).isoformat(), "to_date": today.isoformat()})
    assert r.status_code == 422


def test_dashboard_defaults_to_this_month_and_reports_no_data_as_null(client, world):
    admin = client.as_user("admin")
    body = admin.get("/api/hr/dashboard").json()
    today = date.today()
    assert body["from_date"] == today.replace(day=1).isoformat()
    assert body["to_date"] == today.isoformat()
    assert body["attendance_trend"][0]["date"] == today.replace(day=1).isoformat()
    assert len(body["attendance_trend"]) == today.day
    # No employee has a birth date in a fresh test database: an empty card, not zeroes.
    assert body["birthdays"] == []
    assert body["leave_by_type"] == []
    for key in ("total_employees", "active_employees", "present_today", "absent_today",
                "on_leave_today", "pending_leave", "pending_other", "new_joiners_month",
                "exits_month", "probation_ending_soon", "documents_expiring"):
        assert key in body


def test_dashboard_is_scoped_to_the_reporting_chain(client, world):
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    manager_id = client.employee_ids["manager"]
    admin.patch(f"/api/hr/employees/{staff_id}", json={"manager_id": manager_id})

    everyone = admin.get("/api/hr/dashboard").json()
    assert everyone["total_employees"] == len(admin.get("/api/hr/employees").json())

    client.as_user("manager")
    team = client.get("/api/hr/dashboard").json()
    assert team["total_employees"] == 2  # the manager and the one direct report
    assert {r["employee_id"] for r in team["needs_attention"]["incomplete_records"]["rows"]} \
        <= {staff_id, manager_id}

    client.as_user("staff")
    own = client.get("/api/hr/dashboard").json()
    assert own["total_employees"] == 1
    assert own["salary_payable"] is None


def test_dashboard_cards_read_real_rows(client, world):
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    today = date.today()
    dob = today.replace(year=today.year - 30)
    joined = today.replace(year=today.year - 2)
    r = admin.patch(f"/api/hr/employees/{staff_id}",
                    json={"date_of_birth": dob.isoformat(),
                          "joining_date": joined.isoformat(),
                          "department": "Sales", "designation": "Associate"})
    assert r.status_code == 200, r.text

    body = admin.get("/api/hr/dashboard").json()
    birthday = next(b for b in body["birthdays"] if b["employee_id"] == staff_id)
    assert birthday["turning"] == 30
    anniversary = next(a for a in body["anniversaries"] if a["employee_id"] == staff_id)
    assert anniversary["years"] == 2
    assert any(d["department"] == "Sales" for d in body["by_department"])

    # A present day with no punch-out is listed for follow-up.
    yesterday = today - timedelta(days=1)
    punched = admin.post("/api/hr/attendance/manual", json={
        "employee_id": staff_id, "date": yesterday.isoformat(), "status": "present",
        "check_in": f"{yesterday.isoformat()}T09:30:00+05:30",
        "remarks": "Forgot to punch out"})
    assert punched.status_code == 201, punched.text
    body = admin.get("/api/hr/dashboard", params={
        "from_date": yesterday.isoformat(), "to_date": today.isoformat()}).json()
    missing = body["needs_attention"]["missing_punches"]
    assert missing["count"] >= 1
    assert any(row["employee_id"] == staff_id for row in missing["rows"])


def test_dashboard_counts_exits_and_stale_approvals(client, world):
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    today = date.today()
    admin.patch(f"/api/hr/employees/{staff_id}", json={
        "joining_date": (today - timedelta(days=800)).isoformat(),
        "date_of_exit": today.isoformat()})
    with SessionLocal() as db:
        db.add(ApprovalRequest(
            record_type="hr_leave", record_id=999998, requested_by=client.ids["staff"],
            reasons=["leave"], request_no=f"AP-OLD-{uuid4().hex[:6]}",
            subject="Old pending request", pending_approver_role="hr_manager",
            detail={"employee_id": staff_id},
            requested_at=datetime.now(IST) - timedelta(days=6)))
        db.commit()

    body = admin.get("/api/hr/dashboard").json()
    assert body["exits_month"] >= 1
    assert body["exits_in_range"] >= 1
    assert body["attrition_pct"] is not None
    stale = body["needs_attention"]["stale_approvals"]
    assert stale["count"] >= 1
    assert any(row["subject"] == "Old pending request" for row in stale["rows"])