from datetime import date, timedelta
from uuid import uuid4


def test_employee_master_requires_hr_permission(client, world):
    sales = client.as_user("sales")
    r = sales.post("/api/hr/employees", json={"code": f"X{uuid4().hex[:4]}", "full_name": "No HR"})
    assert r.status_code == 403


def test_leave_approval_updates_attendance_and_blocks_self_approval(client, world):
    admin = client.as_user("admin")
    created = admin.post("/api/hr/leave/types", json={
        "code": f"CL{uuid4().hex[:3].upper()}", "name": "Casual leave", "kind": "paid",
        "default_days": "12"})
    assert created.status_code == 201, created.text
    leave_type_id = created.json()["id"]

    hr = client.as_user("hr_manager")
    start = date.today() + timedelta(days=10)
    end = start + timedelta(days=1)
    applied = hr.post("/api/hr/leave/applications", json={
        "leave_type_id": leave_type_id, "date_from": start.isoformat(),
        "date_to": end.isoformat(), "reason": "Family function"})
    assert applied.status_code == 201, applied.text
    application_id = applied.json()["id"]

    queue = hr.get("/api/approvals", params={"status": "pending"})
    assert queue.status_code == 200
    request = next(a for a in queue.json()
                   if a["request_type"] == "hr_leave" and a["record_id"] == application_id)
    # Segregation of duties: the requester cannot decide their own leave.
    assert hr.post(f"/api/approvals/{request['id']}/decide",
                   json={"decision": "approve", "reason": "self"}).status_code == 403

    admin = client.as_user("admin")
    decided = admin.post(f"/api/approvals/{request['id']}/decide",
                         json={"decision": "approve", "reason": "Approved"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"

    attendance = admin.get("/api/hr/attendance", params={
        "employee_id": client.employee_ids["hr_manager"],
        "from_date": start.isoformat(), "to_date": end.isoformat()}).json()
    assert {a["status"] for a in attendance} == {"paid_leave"}
    assert len(attendance) == 2


def test_payroll_prepare_submit_approve_process(client, world):
    admin = client.as_user("admin")
    component = admin.post("/api/hr/salary/components", json={
        "code": "BASIC", "name": "Basic salary", "kind": "earning",
        "calc_type": "fixed", "default_rate": "0"})
    assert component.status_code in (201, 409), component.text
    if component.status_code == 409:
        component_id = next(c["id"] for c in admin.get("/api/hr/salary/components").json()
                            if c["code"] == "BASIC")
    else:
        component_id = component.json()["id"]

    structure = admin.post("/api/hr/salary/structures", json={
        "employee_id": client.employee_ids["payroll"], "effective_from": date.today().isoformat(),
        "lines": [{"component_id": component_id, "amount": "30000"}]})
    assert structure.status_code == 201, structure.text

    today = date.today()
    period = admin.post("/api/hr/payroll/periods",
                        json={"year": today.year, "month": today.month})
    assert period.status_code == 201, period.text
    period_id = period.json()["id"]

    # One payroll per employee and period: a second period for the month is refused.
    assert admin.post("/api/hr/payroll/periods",
                      json={"year": today.year, "month": today.month}).status_code == 409

    prepared = admin.post(f"/api/hr/payroll/periods/{period_id}/prepare")
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["status"] == "under_review"

    submitted = admin.post(f"/api/hr/payroll/periods/{period_id}/submit")
    assert submitted.status_code == 200, submitted.text
    approval_id = submitted.json()["approval_id"]

    # The payroll officer may prepare but not approve.
    officer = client.as_user("payroll")
    assert officer.post(f"/api/approvals/{approval_id}/decide",
                        json={"decision": "approve", "reason": "denied"}).status_code == 403

    # The person who prepared it cannot approve it, even as Administrator.
    admin = client.as_user("admin")
    assert admin.post(f"/api/approvals/{approval_id}/decide",
                      json={"decision": "approve", "reason": "self"}).status_code == 403

    approver_token, approver_id = _second_admin(client)
    admin.cookies.set("session", approver_token)
    decided = admin.post(f"/api/approvals/{approval_id}/decide",
                         json={"decision": "approve", "reason": "Checked the register"})
    assert decided.status_code == 200, decided.text

    register = admin.get(f"/api/hr/payroll/periods/{period_id}")
    assert register.status_code == 200
    entry = next(e for e in register.json()["entries"]
                 if e["employee_id"] == client.employee_ids["payroll"])
    assert entry["gross"] == "30000.00"
    assert entry["net"] == "30000.00"

    assert admin.post(f"/api/hr/payroll/periods/{period_id}/process").json()["status"] == "processed"
    assert admin.post(f"/api/hr/payroll/periods/{period_id}/pay").json()["status"] == "paid"
    assert admin.post(f"/api/hr/payroll/periods/{period_id}/process").status_code == 409


def _second_admin(client):
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Employee, Role

    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == "admin"))
        user = db.scalar(select(User).where(User.username == "t_admin2"))
        if not user:
            emp = Employee(code="T_ADMIN2", full_name="Second admin", status="active")
            db.add(emp)
            db.flush()
            user = User(username="t_admin2", username_key="t_admin2",
                        password_hash="x", role="admin", role_id=role.id,
                        employee_id=emp.id)
            db.add(user)
            db.commit()
        return make_token(user.id, user.token_version or 1), user.id


def test_general_shift_is_assigned_and_late_and_early_are_calculated(client, world):
    """Office timings come from the shift, and the comparison uses India time."""
    from datetime import datetime, time
    from types import SimpleNamespace

    from app.services.hr import IST, shift_early_minutes, shift_late_minutes

    admin = client.as_user("admin")
    shifts = admin.get("/api/hr/shifts").json()
    general = next(s for s in shifts if s["name"] == "General")
    assert general["start_time"].startswith("09:30")
    assert general["grace_minutes"] == 10

    # A new employee with no explicit shift goes on the general shift.
    created = admin.post("/api/hr/employees", json={
        "code": f"SH{uuid4().hex[:4].upper()}", "full_name": "Shift test"})
    assert created.status_code == 201, created.text
    assert created.json()["shift_id"] == general["id"]

    shift = SimpleNamespace(start_time=time(9, 30), end_time=time(18, 30), grace_minutes=10)
    assert shift_late_minutes(shift, datetime(2026, 1, 5, 9, 40, tzinfo=IST)) == 0
    assert shift_late_minutes(shift, datetime(2026, 1, 5, 10, 0, tzinfo=IST)) == 20
    assert shift_early_minutes(shift, datetime(2026, 1, 5, 18, 0, tzinfo=IST)) == 30
    assert shift_early_minutes(shift, datetime(2026, 1, 5, 18, 30, tzinfo=IST)) == 0

    # A check-in after the shift start records the lateness on the row.
    # "An hour ago" can fall on the previous calendar day just after midnight,
    # and a shift starting yesterday is not today's shift. Stay inside today.
    now = datetime.now(IST)
    start_at = now - timedelta(hours=1)
    if start_at.date() != now.date():
        start_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_at.strftime("%H:%M")
    expected_late = int((now - start_at).total_seconds() // 60)
    custom = admin.post("/api/hr/shifts", json={
        "name": f"Late {uuid4().hex[:4].upper()}", "start_time": start,
        "end_time": "23:59", "grace_minutes": 0})
    assert custom.status_code == 201, custom.text
    moved = admin.patch(f"/api/hr/employees/{client.employee_ids['viewer']}",
                        json={"shift_id": custom.json()["id"]})
    assert moved.status_code == 200, moved.text

    viewer = client.as_user("viewer")
    checked = viewer.post("/api/hr/attendance/check-in", json={"source": "web"})
    assert checked.status_code == 201, checked.text
    assert checked.json()["late_minutes"] >= max(expected_late - 5, 0)


def test_shift_timings_can_be_edited_by_hr_only(client, world):
    admin = client.as_user("admin")
    created = admin.post("/api/hr/shifts", json={
        "name": f"Edit {uuid4().hex[:4].upper()}", "start_time": "09:15",
        "end_time": "18:15"})
    assert created.status_code == 201, created.text
    shift_id = created.json()["id"]

    patched = admin.patch(f"/api/hr/shifts/{shift_id}", json={
        "start_time": "10:00", "end_time": "19:00", "grace_minutes": 15,
        "full_day_hours": "8.5", "half_day_hours": "4.5", "weekly_offs": [6]})
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["start_time"] == "10:00"
    assert body["end_time"] == "19:00"
    assert body["grace_minutes"] == 15
    assert float(body["full_day_hours"]) == 8.5
    assert body["weekly_offs"] == [6]

    listed = next(s for s in admin.get("/api/hr/shifts").json() if s["id"] == shift_id)
    assert listed["start_time"] == "10:00"
    assert listed["grace_minutes"] == 15

    # Bad weekday numbers and a zero-length shift are refused on create and edit.
    assert admin.patch(f"/api/hr/shifts/{shift_id}",
                       json={"weekly_offs": [7]}).status_code == 422
    assert admin.patch(f"/api/hr/shifts/{shift_id}",
                       json={"start_time": "10:00", "end_time": "10:00"}).status_code == 422
    assert admin.post("/api/hr/shifts", json={
        "name": f"Bad {uuid4().hex[:4].upper()}", "start_time": "09:00",
        "end_time": "09:00"}).status_code == 422
    assert admin.post("/api/hr/shifts", json={
        "name": f"Bad {uuid4().hex[:4].upper()}", "weekly_offs": [9]}).status_code == 422

    sales = client.as_user("sales")
    assert sales.patch(f"/api/hr/shifts/{shift_id}",
                       json={"grace_minutes": 5}).status_code == 403

    admin = client.as_user("admin")
    logs = admin.get("/api/audit", params={"action": "hr.shift.update",
                                           "record": f"shift:{shift_id}"}).json()
    assert logs["total"] >= 1
    assert logs["rows"][0]["changes"]["grace_minutes"]["new"] == "15"


def test_staff_can_check_in_at_their_office(client, world):
    """A staff login records its own attendance; the geofence is enforced on the server."""
    admin = client.as_user("admin")
    office = admin.post("/api/hr/offices", json={
        "code": f"TST{uuid4().hex[:4].upper()}", "name": "Test office",
        "latitude": "12.971600", "longitude": "77.603500",
        "geofence_radius_m": 200, "attendance_mode": "both"})
    assert office.status_code == 201, office.text
    office_id = office.json()["id"]
    moved = admin.patch(f"/api/hr/employees/{client.employee_ids['sales']}",
                        json={"office_id": office_id})
    assert moved.status_code == 200, moved.text

    sales = client.as_user("sales")
    outside = sales.post("/api/hr/attendance/check-in", json={
        "source": "gps", "latitude": "12.900000", "longitude": "77.500000"})
    assert outside.status_code == 409
    assert "geofence" in outside.text.lower()

    inside = sales.post("/api/hr/attendance/check-in", json={
        "source": "gps", "latitude": "12.971700", "longitude": "77.603900"})
    assert inside.status_code == 201, inside.text
    assert inside.json()["geofence_result"] == "inside"

    rows = sales.get("/api/hr/attendance").json()
    assert {r["employee_id"] for r in rows} == {client.employee_ids["sales"]}
    assert rows[0]["office_id"] == office_id

    # A second check-in on the same day is refused.
    assert sales.post("/api/hr/attendance/check-in",
                      json={"source": "web"}).status_code == 409
    # Self-service does not open the employee directory.
    assert sales.get("/api/hr/employees").status_code == 403


def test_hr_decision_flag_follows_the_permission(client, world):
    admin = client.as_user("admin")
    created = admin.post("/api/hr/leave/types", json={
        "code": f"SL{uuid4().hex[:3].upper()}", "name": "Sick leave (flag test)",
        "kind": "paid", "default_days": "10"})
    assert created.status_code == 201, created.text
    start = date.today() + timedelta(days=20)

    hr = client.as_user("hr_manager")
    applied = hr.post("/api/hr/leave/applications", json={
        "leave_type_id": created.json()["id"], "date_from": start.isoformat(),
        "date_to": start.isoformat(), "reason": "Decision flag test"})
    assert applied.status_code == 201, applied.text
    application_id = applied.json()["id"]

    def pending(actor):
        rows = client.as_user(actor).get("/api/approvals", params={"status": "pending"}).json()
        return next(a for a in rows if a["request_type"] == "hr_leave"
                    and a["record_id"] == application_id)

    # A payroll officer can open the queue but does not hold hr:leave_approve.
    row = pending("payroll")
    assert row["can_decide"] is False
    assert client.post(f"/api/approvals/{row['id']}/decide",
                       json={"decision": "approve", "reason": "not my call"}).status_code == 403

    # The HR manager holds it, but raised this request.
    assert pending("hr_manager")["can_decide"] is False
    # The Administrator can decide it, and the form is offered.
    assert pending("admin")["can_decide"] is True


def test_employee_login_link_is_visible_to_both_screens(client, world):
    admin = client.as_user("admin")
    code = f"LNK{uuid4().hex[:4].upper()}"
    emp = admin.post("/api/employees", json={"code": code, "full_name": "Link Test"})
    assert emp.status_code == 201, emp.text
    emp_id = emp.json()["id"]

    created = admin.post("/api/users", json={
        "username": f"lnk_{uuid4().hex[:6]}", "role": "viewer", "employee_id": emp_id})
    assert created.status_code == 201, created.text

    # The employee master and the HR list read the same link, so the New user
    # dropdown (which lists employees without a login) skips this one.
    row = next(e for e in admin.get("/api/employees").json() if e["id"] == emp_id)
    assert row["user_id"] == created.json()["id"]
    assert row["username"] == created.json()["username"]
    hr_row = next(e for e in admin.get("/api/hr/employees").json() if e["id"] == emp_id)
    assert hr_row["user_id"] == created.json()["id"]

    # A second login for the same employee is refused.
    again = admin.post("/api/users", json={
        "username": f"lnk_{uuid4().hex[:6]}", "role": "viewer", "employee_id": emp_id})
    assert again.status_code == 409
