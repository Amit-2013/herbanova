"""Leave rules: working days, half days, calendar, balances and carry-forward.

The dates are in 2034-2035 so the counts cannot overlap other HR tests.
"""
from uuid import uuid4


def _employee(client, department=None):
    payload = {"code": f"LV{uuid4().hex[:5].upper()}",
               "full_name": f"Leave subject {uuid4().hex[:4]}"}
    if department:
        payload["department"] = department
    resp = client.as_user("admin").post("/api/hr/employees", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _leave_type(client, *, default="20", carry=False, cap="0", half=True):
    resp = client.as_user("admin").post("/api/hr/leave/types", json={
        "code": f"LT{uuid4().hex[:4].upper()}", "name": f"Leave {uuid4().hex[:4]}",
        "kind": "paid", "default_days": default, "carry_forward": carry,
        "max_carry_forward": cap, "half_day_allowed": half})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _pending_leave(client, application_id):
    rows = client.as_user("hr_manager").get(
        "/api/approvals", params={"status": "pending", "request_type": "hr_leave"}).json()
    return next(a for a in rows if a["record_id"] == application_id)


def test_leave_counts_working_days_only(client):
    emp_id = _employee(client)
    type_id = _leave_type(client)

    # Friday 3 March 2034 to Monday 6 March: two working days, one weekend.
    applied = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2034-03-03", "date_to": "2034-03-06",
        "reason": "Long weekend"})
    assert applied.status_code == 201, applied.text
    body = applied.json()
    assert body["days"] == 2
    assert float(body["balance_before"]) == 20
    assert float(body["balance_after"]) == 18

    request = _pending_leave(client, body["id"])
    decided = client.as_user("hr_manager").post(
        f"/api/approvals/{request['id']}/decide",
        json={"decision": "approve", "reason": "Approved with a recorded reason"})
    assert decided.status_code == 200, decided.text

    rows = client.as_user("admin").get("/api/hr/attendance", params={
        "employee_id": emp_id, "from_date": "2034-03-03",
        "to_date": "2034-03-06"}).json()
    assert {r["date"] for r in rows} == {"2034-03-03", "2034-03-06"}
    assert {r["status"] for r in rows} == {"paid_leave"}
    assert all(r["leave_portion"] is None for r in rows)

    balance = client.as_user("admin").get("/api/hr/leave/balances", params={
        "employee_id": emp_id, "year": 2034}).json()
    row = next(b for b in balance["balances"] if b["leave_type_id"] == type_id)
    assert float(row["used"]) == 2
    assert float(row["pending"]) == 0

    weekend = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2034-03-11", "date_to": "2034-03-12",
        "reason": "Weekend only"})
    assert weekend.status_code == 422
    assert "no working days" in weekend.json()["detail"]


def test_half_day_leave_deducts_half_and_marks_the_day(client):
    emp_id = _employee(client)
    type_id = _leave_type(client)
    applied = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2034-03-08", "date_to": "2034-03-08", "portion": "first_half",
        "reason": "Medical appointment"})
    assert applied.status_code == 201, applied.text
    assert float(applied.json()["days"]) == 0.5
    assert float(applied.json()["balance_after"]) == 19.5

    request = _pending_leave(client, applied.json()["id"])
    assert client.as_user("hr_manager").post(
        f"/api/approvals/{request['id']}/decide",
        json={"decision": "approve", "reason": "Half day approved"}).status_code == 200

    rows = client.as_user("admin").get("/api/hr/attendance", params={
        "employee_id": emp_id, "from_date": "2034-03-08",
        "to_date": "2034-03-08"}).json()
    assert rows[0]["status"] == "paid_leave"
    assert rows[0]["leave_portion"] == "first_half"

    month = client.as_user("admin").get("/api/hr/attendance/monthly", params={
        "year": 2034, "month": 3, "employee_id": emp_id}).json()
    summary = month["employees"][0]["summary"]
    assert float(summary["leave_days"]) == 0.5
    assert float(summary["present_days"]) == 0.5

    two_days = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2034-03-14", "date_to": "2034-03-15", "portion": "second_half",
        "reason": "Two dates cannot be one half day"})
    assert two_days.status_code == 422

    weekend = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2034-03-18", "date_to": "2034-03-18", "portion": "first_half",
        "reason": "Saturday half day"})
    assert weekend.status_code == 422


def test_leave_type_rules_are_set_by_hr(client):
    type_id = _leave_type(client, half=True)
    patched = client.as_user("hr_manager").patch(f"/api/hr/leave/types/{type_id}", json={
        "half_day_allowed": False, "carry_forward": True, "max_carry_forward": "5",
        "encashable": True})
    assert patched.status_code == 200, patched.text
    assert patched.json()["half_day_allowed"] is False
    assert patched.json()["carry_forward"] is True
    assert float(patched.json()["max_carry_forward"]) == 5
    assert patched.json()["encashable"] is True

    listed = client.as_user("staff").get("/api/hr/leave/types").json()
    row = next(t for t in listed if t["id"] == type_id)
    assert row["max_carry_forward"] is not None

    # A cap without carry-forward enabled is a contradiction.
    other = _leave_type(client)
    assert client.as_user("hr_manager").patch(
        f"/api/hr/leave/types/{other}",
        json={"max_carry_forward": "5"}).status_code == 422
    assert client.as_user("staff").patch(
        f"/api/hr/leave/types/{other}", json={"half_day_allowed": False}).status_code == 403
    assert client.as_user("hr_manager").patch(
        f"/api/hr/leave/types/{other}", json={}).status_code == 422


def test_team_leave_calendar_is_scoped(client):
    department = f"Ops{uuid4().hex[:4]}"
    emp_id = _employee(client, department=department)
    type_id = _leave_type(client)
    applied = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2034-04-10", "date_to": "2034-04-11",
        "reason": "Team calendar fixture"})
    assert applied.status_code == 201, applied.text

    calendar = client.as_user("admin").get("/api/hr/leave/calendar", params={
        "year": 2034, "month": 4, "department": department})
    assert calendar.status_code == 200, calendar.text
    body = calendar.json()
    assert [e["employee_id"] for e in body["employees"]] == [emp_id]
    entry = next(e for e in body["entries"] if e["id"] == applied.json()["id"])
    assert entry["status"] == "pending"
    assert entry["leave_type_code"]
    assert entry["days"] == 2
    assert "holidays" in body

    own = client.as_user("staff").get("/api/hr/leave/calendar",
                                      params={"year": 2034, "month": 4}).json()
    assert {e["employee_id"] for e in own["entries"]} <= {client.employee_ids["staff"]}
    assert client.as_user("admin").get(
        "/api/hr/leave/calendar", params={"year": 2034, "month": 13}).status_code == 422


def test_balance_adjustment_is_audited_and_scoped(client):
    emp_id = _employee(client)
    type_id = _leave_type(client)
    adjusted = client.as_user("hr_manager").post("/api/hr/leave/balances/adjust", json={
        "employee_id": emp_id, "leave_type_id": type_id, "year": 2034,
        "entitled": "24", "used": "3.5",
        "reason": "Background verification correction"})
    assert adjusted.status_code == 200, adjusted.text
    assert float(adjusted.json()["entitled"]) == 24
    assert float(adjusted.json()["available"]) == 20.5

    from app.core.db import SessionLocal
    from app.models.core import AuditLog
    from sqlalchemy import select
    with SessionLocal() as db:
        row = db.scalars(select(AuditLog).where(
            AuditLog.action == "hr.leave_balance.adjust").order_by(
            AuditLog.id.desc())).first()
        assert row is not None
        assert row.changes["reason"] == "Background verification correction"
        assert row.changes["before"]["entitled"] == "20.0"

    assert client.as_user("staff").post("/api/hr/leave/balances/adjust", json={
        "employee_id": emp_id, "leave_type_id": type_id, "year": 2034,
        "entitled": "30", "reason": "Not my call"}).status_code == 403
    assert client.as_user("hr_manager").post("/api/hr/leave/balances/adjust", json={
        "employee_id": emp_id, "leave_type_id": type_id, "year": 2034,
        "reason": "No values"}).status_code == 422
    assert client.as_user("hr_manager").post("/api/hr/leave/balances/adjust", json={
        "employee_id": emp_id, "leave_type_id": type_id, "year": 2034,
        "used": "-1", "reason": "Negative usage"}).status_code == 422


def test_carry_forward_previews_then_caps_at_the_configured_limit(client):
    type_id = _leave_type(client, default="10", carry=True, cap="5")
    first = _employee(client)
    second = _employee(client)
    for emp_id, used in ((first, "7"), (second, "2")):
        resp = client.as_user("hr_manager").post("/api/hr/leave/balances/adjust", json={
            "employee_id": emp_id, "leave_type_id": type_id, "year": 2034,
            "entitled": "10", "used": used, "reason": "Carry-forward fixture"})
        assert resp.status_code == 200, resp.text

    preview = client.as_user("admin").post("/api/hr/leave/carry-forward",
                                           json={"from_year": 2034, "dry_run": True})
    assert preview.status_code == 200, preview.text
    rows = {r["employee_id"]: r for r in preview.json()["rows"]
            if r["leave_type_code"] and r["leave_type_code"].startswith("LT")}
    assert float(rows[first]["unused_days"]) == 3
    assert float(rows[first]["carried"]) == 3
    assert float(rows[second]["unused_days"]) == 8
    assert float(rows[second]["carried"]) == 5  # capped by max_carry_forward

    still_zero = client.as_user("admin").get("/api/hr/leave/balances", params={
        "employee_id": first, "year": 2035}).json()
    assert float(next(b for b in still_zero["balances"]
                      if b["leave_type_id"] == type_id)["carried"]) == 0

    applied = client.as_user("admin").post("/api/hr/leave/carry-forward",
                                           json={"from_year": 2034, "dry_run": False})
    assert applied.status_code == 200, applied.text
    following = client.as_user("admin").get("/api/hr/leave/balances", params={
        "employee_id": first, "year": 2035}).json()
    assert float(next(b for b in following["balances"]
                      if b["leave_type_id"] == type_id)["carried"]) == 3
    again = client.as_user("admin").post("/api/hr/leave/carry-forward",
                                         json={"from_year": 2034, "dry_run": False})
    assert again.status_code == 200
    after = client.as_user("admin").get("/api/hr/leave/balances", params={
        "employee_id": first, "year": 2035}).json()
    assert float(next(b for b in after["balances"]
                      if b["leave_type_id"] == type_id)["carried"]) == 3


def test_locked_attendance_month_blocks_leave_approval(client):
    emp_id = _employee(client)
    type_id = _leave_type(client)
    applied = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2035-01-08", "date_to": "2035-01-09",
        "reason": "Locked approval check"})
    assert applied.status_code == 201, applied.text
    request = _pending_leave(client, applied.json()["id"])

    assert client.as_user("hr_manager").post("/api/hr/period-locks", json={
        "scope": "attendance", "year": 2035, "month": 1,
        "reason": "January closed"}).status_code == 201
    refused = client.as_user("hr_manager").post(
        f"/api/approvals/{request['id']}/decide",
        json={"decision": "approve", "reason": "Should be refused"})
    assert refused.status_code == 423

    locks = client.as_user("admin").get("/api/hr/period-locks",
                                        params={"scope": "attendance"}).json()
    january = next(l for l in locks if l["year"] == 2035 and l["month"] == 1)
    client.as_user("admin").post(f"/api/hr/period-locks/{january['id']}/unlock",
                                 json={"reason": "Leave must be approved"})
    allowed = client.as_user("hr_manager").post(
        f"/api/approvals/{request['id']}/decide",
        json={"decision": "approve", "reason": "Approved after reopening"})
    assert allowed.status_code == 200, allowed.text


def test_staff_self_service_reads_are_scoped_to_their_own_record(client):
    """A staff login may read leave policy and its own records, nothing wider."""
    other = _employee(client)
    type_id = _leave_type(client)
    created = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": other,
        "date_from": "2035-02-05", "date_to": "2035-02-05",
        "reason": "Colleague's application"})
    assert created.status_code == 201, created.text
    me = client.employee_ids["staff"]

    staff = client.as_user("staff")
    types = staff.get("/api/hr/leave/types")
    assert types.status_code == 200 and types.json()

    balances = staff.get("/api/hr/leave/balances")
    assert balances.status_code == 200
    assert balances.json()["employee_id"] == me

    applications = staff.get("/api/hr/leave/applications")
    assert applications.status_code == 200
    assert all(a["employee_id"] == me for a in applications.json())

    assert staff.get(f"/api/hr/leave/balances?employee_id={other}").status_code == 403
    assert staff.get(f"/api/hr/leave/applications?employee_id={other}").status_code == 403

    od = staff.get("/api/hr/od")
    assert od.status_code == 200
    assert all(row["employee_id"] == me for row in od.json())
