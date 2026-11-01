"""HR reports: ranges, gaps, confidentiality and the CSV/PDF exports.

The fixtures build their own month (2034-03 attendance, 2036-02 payroll) so a
standalone run of this file does not depend on another test module's data.
"""
from datetime import date, timedelta

from sqlalchemy import select

ATT_FROM, ATT_TO = "2034-03-01", "2034-03-31"
COST_MONTH = (2036, 2)
EFFECTIVE_FROM = "2035-10-01"

_SET_UP = False


def _leave_type(client) -> int:
    created = client.as_user("admin").post("/api/hr/leave/types", json={
        "code": "RPT", "name": "Report leave", "kind": "paid", "default_days": "12"})
    if created.status_code == 201:
        return created.json()["id"]
    assert created.status_code == 409, created.text
    return next(t["id"] for t in client.as_user("admin").get(
        "/api/hr/leave/types").json() if t["code"] == "RPT")


def _reporter_token(client):
    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Employee, Role

    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == "hr_reporter"))
        if not role:
            role = Role(name="hr_reporter", display_name="HR report reader",
                        permissions=["hr:reports"])
            db.add(role)
            db.flush()
        user = db.scalar(select(User).where(User.username == "t_reporter"))
        if not user:
            emp = Employee(code="T_REPORTER", full_name="Report reader", status="active")
            db.add(emp)
            db.flush()
            user = User(username="t_reporter", username_key="t_reporter",
                        password_hash="x", role="hr_reporter", role_id=role.id,
                        employee_id=emp.id)
            db.add(user)
            db.commit()
        return make_token(user.id, user.token_version or 1)


def _setup(client):
    global _SET_UP
    if _SET_UP:
        return
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    patched = admin.patch(f"/api/hr/employees/{staff_id}", json={
        "joining_date": "2034-03-06", "department": "Reports test dept",
        "designation": "Analyst", "date_of_exit": None})
    assert patched.status_code == 200, patched.text
    # A leaver in the same range, so attrition has an opening headcount to divide by.
    left = admin.patch(f"/api/hr/employees/{client.employee_ids['viewer']}", json={
        "joining_date": "2033-01-01", "date_of_exit": "2034-03-20",
        "exit_reason": "Reports fixture"})
    assert left.status_code == 200, left.text

    for day, status in (("2034-03-06", "present"), ("2034-03-07", "absent"),
                        ("2034-03-08", "late")):
        marked = client.as_user("hr_manager").post("/api/hr/attendance/manual", json={
            "employee_id": staff_id, "date": day, "status": status,
            "remarks": "Reports fixture"})
        assert marked.status_code in (200, 201), marked.text

    expires = date.today() + timedelta(days=10)
    document = admin.post(f"/api/hr/employees/{staff_id}/documents", json={
        "doc_type": "licence", "title": "Report driving licence",
        "expires_on": expires.isoformat()})
    assert document.status_code == 201, document.text

    leave_type_id = _leave_type(client)
    adjusted = admin.post("/api/hr/leave/balances/adjust", json={
        "employee_id": staff_id, "leave_type_id": leave_type_id, "year": 2034,
        "entitled": "10", "carried": "1", "used": "2", "reason": "Reports fixture"})
    assert adjusted.status_code == 200, adjusted.text

    comps = {c["code"]: c for c in admin.get("/api/hr/salary/components").json()}
    structure = admin.post("/api/hr/salary/structures", json={
        "employee_id": staff_id, "effective_from": EFFECTIVE_FROM, "lines": [
            {"component_id": comps["BASIC"]["id"], "amount": "30000"},
            {"component_id": comps["PF"]["id"], "percent": "12"}]})
    assert structure.status_code == 201, structure.text
    period = client.as_user("payroll").post("/api/hr/payroll/periods", json={
        "year": COST_MONTH[0], "month": COST_MONTH[1]})
    assert period.status_code == 201, period.text
    prepared = client.as_user("payroll").post(
        f"/api/hr/payroll/periods/{period.json()['id']}/prepare")
    assert prepared.status_code == 200, prepared.text
    _SET_UP = True


def test_reports_need_the_hr_reports_right_and_validate_their_range(client, world):
    assert client.as_user("sales").get("/api/hr/reports").status_code == 403
    assert client.as_user("sales").get("/api/hr/reports/headcount").status_code == 403

    catalog = client.as_user("payroll").get("/api/hr/reports")
    assert catalog.status_code == 200
    keys = {r["key"] for r in catalog.json()}
    assert {"headcount", "attendance-summary", "leave-balance",
            "department-cost", "document-expiry"} <= keys

    assert client.as_user("payroll").get(
        "/api/hr/reports/no-such-report").status_code == 404
    assert client.as_user("payroll").get("/api/hr/reports/attendance-summary", params={
        "from_date": "2034-03-31", "to_date": "2034-03-01"}).status_code == 422
    assert client.as_user("payroll").get("/api/hr/reports/attendance-summary", params={
        "from_date": "2030-01-01", "to_date": "2032-01-02"}).status_code == 422


def test_headcount_movements_and_document_expiry(client, world):
    _setup(client)
    headcount = client.as_user("payroll").get("/api/hr/reports/headcount", params={
        "to_date": "2034-03-31"}).json()
    staff = next(r for r in headcount["rows"] if r["full_name"] == "Test staff")
    assert staff["department"] == "Reports test dept"
    assert staff["joining_date"] == "2034-03-06"
    assert headcount["gaps"] == []
    assert headcount["summary"]["as_of"] == "2034-03-31"

    movements = client.as_user("payroll").get("/api/hr/reports/joiners-leavers", params={
        "from_date": ATT_FROM, "to_date": ATT_TO}).json()
    joiner = next(r for r in movements["rows"] if r["event"] == "Joiner"
                  and r["full_name"] == "Test staff")
    assert joiner["event_date"] == "2034-03-06"
    leaver = next(r for r in movements["rows"] if r["event"] == "Leaver"
                  and r["full_name"] == "Test viewer")
    assert leaver["event_date"] == "2034-03-20"
    assert leaver["reason"] == "Reports fixture"
    assert movements["summary"]["joiners"] >= 1
    assert movements["summary"]["leavers"] == 1
    opening = movements["summary"]["opening_headcount"]
    assert opening >= 1
    assert movements["summary"]["attrition_pct"] == round(100 / opening, 1)

    documents = client.as_user("payroll").get("/api/hr/reports/document-expiry", params={
        "days": 30}).json()
    licence = next(r for r in documents["rows"]
                   if r["title"] == "Report driving licence")
    assert licence["days_left"] == 10

    empty = client.as_user("payroll").get("/api/hr/reports/document-expiry", params={
        "days": 1}).json()
    assert empty["no_data"] is True
    assert empty["gaps"] == ["No active documents expire within 1 days."]


def test_attendance_late_and_leave_reports(client, world):
    _setup(client)
    summary = client.as_user("payroll").get("/api/hr/reports/attendance-summary", params={
        "from_date": ATT_FROM, "to_date": ATT_TO}).json()
    row = next(r for r in summary["rows"] if r["full_name"] == "Test staff")
    assert (row["present"], row["absent"], row["late"]) == (1, 1, 1)
    assert row["leave"] == 0 and row["od"] == 0
    assert summary["no_data"] is False
    assert any("no attendance rows" in gap for gap in summary["gaps"])

    late = client.as_user("payroll").get("/api/hr/reports/late-absentee", params={
        "from_date": ATT_FROM, "to_date": ATT_TO}).json()
    flagged = next(r for r in late["rows"] if r["full_name"] == "Test staff")
    assert flagged["late_days"] == 1 and flagged["absent_days"] == 1
    assert flagged["early_days"] == 0
    assert late["summary"]["absent_days"] >= 1

    balances = client.as_user("payroll").get("/api/hr/reports/leave-balance", params={
        "year": 2034}).json()
    balance = next(r for r in balances["rows"] if r["full_name"] == "Test staff"
                   and r["leave_type"] == "Report leave")
    assert (balance["entitled"], balance["carried"], balance["used"],
            balance["pending"], balance["available"]) == \
        ("10.0", "1.0", "2.0", "0.0", "9.0")


def test_department_cost_needs_confidential_rights_and_exports_csv_and_pdf(client, world):
    _setup(client)
    officer = client.as_user("payroll")
    report = officer.get("/api/hr/reports/department-cost", params={
        "year": COST_MONTH[0], "month": COST_MONTH[1]}).json()
    department = next(r for r in report["rows"]
                      if r["department"] == "Reports test dept")
    assert department["employees"] == 1
    assert department["gross"] == "30000.00"
    assert department["deductions"] == "3600.00"
    assert department["net"] == "26400.00"
    assert report["summary"]["period_status"] == "under_review"

    csv_response = officer.get("/api/hr/reports/department-cost", params={
        "year": COST_MONTH[0], "month": COST_MONTH[1], "format": "csv"})
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "hr-department-cost-" in csv_response.headers["content-disposition"]
    lines = csv_response.text.strip().splitlines()
    assert lines[0] == "Department,Employees,Gross,Deductions,Net"
    assert any(line.startswith("Reports test dept,1,30000.00,3600.00,26400.00")
               for line in lines[1:])

    pdf = officer.get("/api/hr/reports/headcount", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # A role may be allowed to read HR reports without being allowed salary cost.
    client.cookies.set("session", _reporter_token(client))
    assert client.get("/api/hr/reports/headcount").status_code == 200
    denied = client.get("/api/hr/reports/department-cost", params={
        "year": COST_MONTH[0], "month": COST_MONTH[1]})
    assert denied.status_code == 403
    assert "confidential" in denied.json()["detail"].lower()


def test_reports_say_no_data_yet_instead_of_zeroes(client, world):
    # A payroll month nobody prepared is a gap, not a zero-cost department list.
    body = client.as_user("payroll").get("/api/hr/reports/department-cost", params={
        "year": 2039, "month": 4}).json()
    assert body["rows"] == [] and body["no_data"] is True
    assert body["gaps"] == ["No payroll period exists for 2039-04."]
    assert body["summary"]["net"] == "0.00"
