"""Branch- and office-based attendance: sites, policies, gating and filters.

Each test builds its own branch/office and employees, so the shared suite
database stays independent of what other HR tests create. Months are in the far
future (2033-2036) so these rows never change the counts other tests assert for
the current month.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select


def _suffix() -> str:
    return uuid4().hex[:6].upper()


def _branch(client, **overrides):
    payload = {"code": f"BR{_suffix()}", "name": f"Branch {uuid4().hex[:4]}"}
    payload.update(overrides)
    r = client.as_user("admin").post("/api/hr/branches", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _office(client, branch_id=None, **overrides):
    payload = {"code": f"OF{_suffix()}", "name": f"Office {uuid4().hex[:4]}",
               "branch_id": branch_id, "attendance_mode": "office"}
    payload.update(overrides)
    r = client.as_user("admin").post("/api/hr/offices", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _employee(client, **overrides):
    payload = {"code": f"EMP{_suffix()}", "full_name": f"Employee {uuid4().hex[:4]}"}
    payload.update(overrides)
    r = client.as_user("admin").post("/api/hr/employees", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _rule(client, **payload):
    r = client.as_user("admin").post("/api/hr/attendance-rules", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _drop_rules(client, *rule_ids):
    for rule_id in rule_ids:
        r = client.as_user("admin").delete(f"/api/hr/attendance-rules/{rule_id}")
        assert r.status_code in (204, 404), r.text


def _manual(client, employee_id, day, status="present", **extra):
    payload = {"employee_id": employee_id, "date": str(day), "status": status,
               "remarks": "Branch and office attendance test"}
    payload.update(extra)
    return client.as_user("admin").post("/api/hr/attendance/manual", json=payload)


def test_sites_crud_and_employee_assignment(client):
    admin = client.as_user("admin")
    hr_admin_id = client.employee_ids["hr_manager"]
    branch = _branch(client, hr_admin_id=hr_admin_id)
    other_branch = _branch(client)
    office = _office(client, branch["id"])
    second_office = _office(client, branch["id"], attendance_mode="both")

    branches = {b["id"]: b for b in admin.get("/api/hr/branches").json()}
    assert branches[branch["id"]]["hr_admin_id"] == hr_admin_id
    assert branches[branch["id"]]["hr_admin"] == "Test hr_manager"

    offices = {o["id"]: o for o in admin.get("/api/hr/offices").json()}
    assert offices[office["id"]]["branch"] == branch["name"]
    assert offices[office["id"]]["active_employees"] == 0

    # An office decides its own branch: an employee given only an office is
    # placed in that office's branch automatically.
    emp = _employee(client, office_id=office["id"], designation="Field Executive")
    assert emp["branch_id"] == branch["id"]
    assert emp["office_id"] == office["id"]

    mismatched = admin.post("/api/hr/employees", json={
        "code": f"EMP{_suffix()}", "full_name": "Mismatched placement",
        "branch_id": other_branch["id"], "office_id": office["id"]})
    assert mismatched.status_code == 422, mismatched.text

    unknown = admin.post("/api/hr/employees", json={
        "code": f"EMP{_suffix()}", "full_name": "Unknown office", "office_id": 999999})
    assert unknown.status_code == 404, unknown.text

    # Coordinates are a pair; one without the other is refused.
    half_pair = admin.post("/api/hr/offices", json={
        "code": f"OF{_suffix()}", "name": "Half coordinates", "branch_id": branch["id"],
        "latitude": "19.07"})
    assert half_pair.status_code == 422, half_pair.text

    # Live staff block the moves that would orphan their policy.
    assert admin.patch(f"/api/hr/branches/{branch['id']}",
                       json={"status": "inactive"}).status_code == 409
    assert admin.patch(f"/api/hr/offices/{office['id']}",
                       json={"status": "inactive"}).status_code == 409
    assert admin.patch(f"/api/hr/offices/{office['id']}",
                       json={"branch_id": other_branch["id"]}).status_code == 409
    assert admin.patch(f"/api/hr/offices/{office['id']}",
                       json={"latitude": "19.07"}).status_code == 422

    # Moving the employee to the other office in the same branch clears the
    # guard, and only then can the empty office be switched off.
    moved = admin.patch(f"/api/hr/employees/{emp['id']}",
                        json={"office_id": second_office["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["branch_id"] == branch["id"]
    assert admin.patch(f"/api/hr/offices/{office['id']}",
                       json={"status": "inactive"}).status_code == 200

    # Deactivation of the branch still needs the employee moved out (or made
    # inactive), because an active employee remains assigned to it.
    assert admin.patch(f"/api/hr/branches/{branch['id']}",
                       json={"status": "inactive"}).status_code == 409
    emptied = admin.patch(f"/api/hr/employees/{emp['id']}", json={"status": "inactive"})
    assert emptied.status_code == 200, emptied.text
    assert admin.patch(f"/api/hr/branches/{branch['id']}",
                       json={"status": "inactive"}).status_code == 200

    # An inactive branch cannot be assigned to a new employee.
    refused = admin.post("/api/hr/employees", json={
        "code": f"EMP{_suffix()}", "full_name": "Inactive branch",
        "branch_id": branch["id"]})
    assert refused.status_code == 422, refused.text

    unknown_admin = admin.patch(f"/api/hr/branches/{other_branch['id']}",
                                json={"hr_admin_id": 999999})
    assert unknown_admin.status_code == 404, unknown_admin.text

    # Reading sites needs an HR right; writing needs hr:write.
    viewer = client.as_user("viewer")
    assert viewer.get("/api/hr/branches").status_code == 403
    assert viewer.get("/api/hr/offices").status_code == 403
    assert viewer.post("/api/hr/branches", json={
        "code": f"BR{_suffix()}", "name": "No right"}).status_code == 403
    client.as_user("admin")


def test_rule_validation_precedence_and_effective_dates(client):
    branch = _branch(client)
    other_branch = _branch(client)
    office = _office(client, branch["id"])
    emp = _employee(client, branch_id=branch["id"], office_id=office["id"],
                    designation="Field Executive")
    rule_ids = []
    try:
        admin = client.as_user("admin")
        wrong_office = admin.post("/api/hr/attendance-rules", json={
            "employee_id": emp["id"], "office_id": 999999})
        assert wrong_office.status_code == 404, wrong_office.text
        mismatch = admin.post("/api/hr/attendance-rules", json={
            "employee_id": emp["id"], "branch_id": other_branch["id"]})
        assert mismatch.status_code == 422, mismatch.text
        wrong_dates = admin.post("/api/hr/attendance-rules", json={
            "branch_id": branch["id"], "effective_from": "2032-06-01",
            "effective_to": "2032-05-01"})
        assert wrong_dates.status_code == 422, wrong_dates.text
        no_shift = admin.post("/api/hr/attendance-rules", json={
            "branch_id": branch["id"], "shift_id": 999999})
        assert no_shift.status_code == 404, no_shift.text

        branch_rule = _rule(client, branch_id=branch["id"], required=False,
                            effective_from="2032-01-01", effective_to="2032-12-31",
                            note="Field branch: attendance recorded by the supervisor")
        rule_ids.append(branch_rule["id"])
        duplicate = admin.post("/api/hr/attendance-rules", json={"branch_id": branch["id"]})
        assert duplicate.status_code == 409, duplicate.text

        resolved = admin.get("/api/hr/attendance-rules/resolve",
                             params={"employee_id": emp["id"], "day": "2031-12-31"})
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["required"] is True
        assert resolved.json()["source"] == f"Office default ({office['name']})"
        assert resolved.json()["office"] == office["name"]

        in_window = admin.get("/api/hr/attendance-rules/resolve",
                              params={"employee_id": emp["id"], "day": "2032-06-01"}).json()
        assert in_window["required"] is False
        assert in_window["rule_id"] == branch_rule["id"]
        assert in_window["source"] == f"Branch rule #{branch_rule['id']}"

        office_rule = _rule(client, branch_id=branch["id"], office_id=office["id"],
                            required=True, effective_from="2032-01-01",
                            effective_to="2032-12-31")
        rule_ids.append(office_rule["id"])
        by_office = admin.get("/api/hr/attendance-rules/resolve",
                              params={"employee_id": emp["id"], "day": "2032-06-01"}).json()
        assert by_office["required"] is True
        assert by_office["rule_id"] == office_rule["id"]

        employee_rule = _rule(client, employee_id=emp["id"], self_service=False,
                              attendance_mode="gps", effective_to="2032-06-30")
        rule_ids.append(employee_rule["id"])
        by_employee = admin.get("/api/hr/attendance-rules/resolve",
                                params={"employee_id": emp["id"],
                                        "day": "2032-06-15"}).json()
        assert by_employee["rule_id"] == employee_rule["id"]
        assert by_employee["required"] is True
        assert by_employee["self_service"] is False
        assert by_employee["attendance_mode"] == "gps"
        assert by_employee["source"] == f"Employee rule #{employee_rule['id']}"

        # The employee rule's window ends in June; July falls back to the
        # office rule, and switching the office rule off falls back to the
        # branch rule again.
        after_window = admin.get("/api/hr/attendance-rules/resolve",
                                 params={"employee_id": emp["id"], "day": "2032-07-01"}).json()
        assert after_window["rule_id"] == office_rule["id"]
        assert admin.patch(f"/api/hr/attendance-rules/{office_rule['id']}",
                           json={"active": False}).status_code == 200
        fallback = admin.get("/api/hr/attendance-rules/resolve",
                             params={"employee_id": emp["id"], "day": "2032-07-01"}).json()
        assert fallback["rule_id"] == branch_rule["id"]
        assert fallback["required"] is False

        # A company-wide rule is allowed once, and only once.
        company = _rule(client, required=True)
        rule_ids.append(company["id"])
        assert admin.post("/api/hr/attendance-rules",
                          json={"required": True}).status_code == 409

        listed = admin.get("/api/hr/attendance-rules").json()
        assert set(rule_ids) <= {r["id"] for r in listed}
        assert all(r["source"] for r in listed)
    finally:
        _drop_rules(client, *rule_ids)
    assert not (set(rule_ids) &
                {r["id"] for r in client.as_user("admin").get(
                    "/api/hr/attendance-rules").json()})


def test_exempt_employee_is_blocked_from_manual_bulk_and_correction(client):
    branch = _branch(client)
    office = _office(client, branch["id"])
    emp = _employee(client, branch_id=branch["id"], office_id=office["id"])

    recorded = _manual(client, emp["id"], date(2033, 3, 1))
    assert recorded.status_code == 201, recorded.text
    attendance_id = recorded.json()["id"]

    rule = _rule(client, branch_id=branch["id"], required=False,
                 effective_from="2033-03-01",
                 note="Supervisor marks this branch on paper")
    try:
        blocked = _manual(client, emp["id"], date(2033, 3, 2))
        assert blocked.status_code == 409, blocked.text
        assert "not required" in blocked.json()["detail"]

        bulk = client.as_user("admin").post("/api/hr/attendance/bulk", json={
            "employee_ids": [emp["id"]], "date_from": "2033-03-02",
            "date_to": "2033-03-03", "status": "present",
            "remarks": "Should be refused for an exempt employee"})
        assert bulk.status_code == 409, bulk.text
        assert "not required" in bulk.json()["detail"]

        correction = client.as_user("admin").post(
            f"/api/hr/attendance/{attendance_id}/correction",
            json={"new_status": "late", "reason": "Punch was late"})
        assert correction.status_code == 409, correction.text
        assert "not required" in correction.json()["detail"]

        # The exemption is a policy, not a deletion: the day recorded before the
        # rule still exists and still reads as present.
        listed = client.as_user("admin").get("/api/hr/attendance", params={
            "employee_id": emp["id"], "from_date": "2033-03-01",
            "to_date": "2033-03-05"}).json()
        assert [r["status"] for r in listed] == ["present"]
    finally:
        _drop_rules(client, rule["id"])

    # Once the exemption is gone the same manual entry is allowed again.
    allowed = _manual(client, emp["id"], date(2033, 3, 2))
    assert allowed.status_code == 201, allowed.text


def test_self_service_check_in_obeys_the_rule(client):
    staff_id = client.employee_ids["staff"]
    no_self_service = _rule(client, employee_id=staff_id, self_service=False,
                            effective_from="2020-01-01")
    try:
        refused = client.as_user("staff").post("/api/hr/attendance/check-in",
                                               json={"source": "web"})
        assert refused.status_code == 409, refused.text
        assert "Self check-in is switched off" in refused.json()["detail"]
        # Resolving your own policy needs no employee id.
        mine = client.as_user("staff").get("/api/hr/attendance-rules/resolve")
        assert mine.status_code == 200, mine.text
        assert mine.json()["employee_id"] == staff_id
        assert mine.json()["self_service"] is False
    finally:
        _drop_rules(client, no_self_service["id"])

    exempt = _rule(client, employee_id=staff_id, required=False,
                   effective_from="2020-01-01")
    try:
        refused = client.as_user("staff").post("/api/hr/attendance/check-in",
                                               json={"source": "web"})
        assert refused.status_code == 409, refused.text
        assert "not required" in refused.json()["detail"]
    finally:
        _drop_rules(client, exempt["id"])

    gps = _rule(client, employee_id=staff_id, attendance_mode="gps",
                effective_from="2020-01-01")
    try:
        resolved = client.as_user("staff").get(
            "/api/hr/attendance-rules/resolve").json()
        assert resolved["attendance_mode"] == "gps"
        refused = client.as_user("staff").post("/api/hr/attendance/check-in",
                                               json={"source": "gps"})
        assert refused.status_code == 422, refused.text
        assert "GPS coordinates" in refused.json()["detail"]
    finally:
        _drop_rules(client, gps["id"])

    # A staff login may resolve its own policy but not a colleague's: scope is
    # enforced on the server, not by which employee id the screen sends.
    assert client.as_user("staff").get(
        "/api/hr/attendance-rules/resolve",
        params={"employee_id": client.employee_ids["sales"]}).status_code == 403
    client.as_user("admin")


def test_site_filters_reach_attendance_employees_dashboard_and_reports(client):
    branch_a = _branch(client)
    branch_b = _branch(client)
    office_a = _office(client, branch_a["id"])
    office_b = _office(client, branch_b["id"])
    emp_a = _employee(client, branch_id=branch_a["id"], office_id=office_a["id"])
    emp_b = _employee(client, branch_id=branch_b["id"], office_id=office_b["id"])

    for emp in (emp_a, emp_b):
        marked = _manual(client, emp["id"], date(2033, 4, 3))
        assert marked.status_code == 201, marked.text

    admin = client.as_user("admin")
    rows_a = admin.get("/api/hr/attendance", params={
        "from_date": "2033-04-03", "to_date": "2033-04-03",
        "branch_id": branch_a["id"]}).json()
    assert [r["employee_id"] for r in rows_a] == [emp_a["id"]]
    assert rows_a[0]["branch_id"] == branch_a["id"]
    assert rows_a[0]["employee_office_id"] == office_a["id"]
    rows_office = admin.get("/api/hr/attendance", params={
        "from_date": "2033-04-03", "to_date": "2033-04-03",
        "office_id": office_b["id"]}).json()
    assert [r["employee_id"] for r in rows_office] == [emp_b["id"]]

    monthly = admin.get("/api/hr/attendance/monthly", params={
        "year": 2033, "month": 4, "branch_id": branch_a["id"]}).json()
    assert [e["employee_id"] for e in monthly["employees"]] == [emp_a["id"]]
    payload = monthly["employees"][0]
    assert payload["branch_id"] == branch_a["id"]
    assert payload["office_id"] == office_a["id"]
    assert payload["attendance_required"] is True
    assert payload["attendance_rule"] == f"Office default ({office_a['name']})"
    third = next(d for d in payload["calendar"] if d["date"] == "2033-04-03")
    assert third["status"] == "present"
    fourth = next(d for d in payload["calendar"] if d["date"] == "2033-04-04")
    assert fourth["status"] is None and not fourth.get("not_required")
    assert payload["summary"]["missing_days"] >= 1
    assert payload["summary"]["not_required_days"] == 0
    assert monthly["totals"]["present_days"] == 1.0

    directory = admin.get("/api/hr/employees", params={
        "branch_id": branch_a["id"], "status": "active"}).json()
    assert [e["id"] for e in directory] == [emp_a["id"]]
    assert directory[0]["branch_name"] == branch_a["name"]
    assert directory[0]["office_name"] == office_a["name"]
    assert directory[0]["attendance_required"] is True
    assert directory[0]["attendance_rule"] == f"Office default ({office_a['name']})"

    dashboard = admin.get("/api/hr/dashboard", params={
        "day": "2033-04-03", "from_date": "2033-04-01", "to_date": "2033-04-04",
        "branch_id": branch_a["id"]}).json()
    assert dashboard["filters"] == {"branch_id": branch_a["id"], "office_id": None}
    assert dashboard["active_employees"] == 1
    assert dashboard["attendance_required_today"] == 1
    assert dashboard["attendance_exempt_today"] == 0
    assert dashboard["by_office"] == [{"office": office_a["name"], "employees": 1}]

    report = admin.get("/api/hr/reports/headcount", params={
        "branch_id": branch_a["id"]}).json()
    assert report["filters"]["branch"] == branch_a["name"]
    assert [r["code"] for r in report["rows"]] == [emp_a["code"]]
    report = admin.get("/api/hr/reports/headcount", params={
        "office_id": office_b["id"]}).json()
    assert report["filters"]["office"] == office_b["name"]
    assert [r["code"] for r in report["rows"]] == [emp_b["code"]]
    assert admin.get("/api/hr/reports/headcount",
                     params={"branch_id": 999999}).status_code == 404


def test_monthly_register_marks_exempt_days_as_not_required(client):
    branch = _branch(client)
    office = _office(client, branch["id"])
    emp = _employee(client, branch_id=branch["id"], office_id=office["id"])
    rule = _rule(client, branch_id=branch["id"], required=False,
                 effective_from="2033-05-01", effective_to="2033-05-31")
    try:
        monthly = client.as_user("admin").get("/api/hr/attendance/monthly", params={
            "year": 2033, "month": 5, "employee_id": emp["id"]}).json()
        payload = monthly["employees"][0]
        assert payload["attendance_required"] is False
        assert payload["attendance_rule"] == f"Branch rule #{rule['id']}"
        assert payload["summary"]["missing_days"] == 0
        assert payload["summary"]["not_required_days"] == len(monthly["days"])
        assert all(day.get("not_required") for day in payload["calendar"])
        assert monthly["totals"]["not_required_days"] == len(monthly["days"])
        # Other branches' employees are untouched by this branch's policy.
        other = _employee(client)
        bystander = client.as_user("admin").get("/api/hr/attendance/monthly", params={
            "year": 2033, "month": 5, "employee_id": other["id"]}).json()["employees"][0]
        assert bystander["summary"]["not_required_days"] == 0
        assert bystander["summary"]["missing_days"] == len(monthly["days"])
    finally:
        _drop_rules(client, rule["id"])


def test_payroll_does_not_invent_absence_for_exempt_employees(client):
    from app.core.db import SessionLocal
    from app.models.hr import Attendance, PayrollPeriod
    from app.services.payroll import run_payroll

    branch = _branch(client)
    office = _office(client, branch["id"])
    exempt = _employee(client, branch_id=branch["id"], office_id=office["id"])
    regular = _employee(client, branch_id=branch["id"], office_id=office["id"])
    rule = _rule(client, branch_id=branch["id"], required=False,
                 effective_from="2036-01-01")
    try:
        admin = client.as_user("admin")
        basic = next(c for c in admin.get("/api/hr/salary/components").json()
                     if c["code"] == "BASIC")
        for emp_id in (exempt["id"], regular["id"]):
            created = admin.post("/api/hr/salary/structures", json={
                "employee_id": emp_id, "effective_from": "2035-01-01",
                "lines": [{"component_id": basic["id"], "amount": "20000"}]})
            assert created.status_code == 201, created.text

        with SessionLocal() as db:
            # The exempt employee has one recorded unpaid day; the regular one
            # has no rows at all. Neither should be treated as absent by default.
            db.add(Attendance(employee_id=exempt["id"], date=date(2037, 2, 10),
                              status="unpaid_leave", source="manual"))
            period = PayrollPeriod(year=2037, month=2, status="draft")
            db.add(period)
            db.flush()
            entries = {e.employee_id: e for e in run_payroll(db, period)}
            exempt_entry = entries[exempt["id"]]
            regular_entry = entries[regular["id"]]
            assert exempt_entry.working_days > 0
            assert exempt_entry.lop_days == Decimal("1")
            assert exempt_entry.payable_days == exempt_entry.working_days - 1
            assert "not required" in (exempt_entry.note or "")
            assert regular_entry.lop_days == Decimal("0")
            assert regular_entry.payable_days == regular_entry.working_days
            assert regular_entry.present_days == regular_entry.working_days
            assert regular_entry.note is not None       # "no attendance recorded"
            db.rollback()
    finally:
        _drop_rules(client, rule["id"])

    # Self-check: the rolled-back run left no payroll entry behind.
    from app.core.db import SessionLocal as Session
    from app.models.hr import PayrollEntry
    with Session() as db:
        assert not db.scalar(select(PayrollEntry).where(
            PayrollEntry.employee_id == exempt["id"]))
