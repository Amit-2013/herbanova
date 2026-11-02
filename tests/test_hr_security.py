"""HR confidentiality and team scope, enforced on the server.

The brief restricts salary, bank and ID data to the Administrator, the
confidential HR right and the roles the Administrator allows. These tests use
ordinary staff and reporting-manager logins, not the Administrator, so a UI
that hides a field cannot be mistaken for the server allowing the read.
"""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import make_token
from app.models.core import ApprovalRequest, User

BANK_FULL = "999988887777"
PAN_FULL = "PQRSX9876Z"


@pytest.fixture()
def linked_team(client, world):
    admin = client.as_user("admin")
    staff_id = client.employee_ids["staff"]
    manager_id = client.employee_ids["manager"]
    sales_id = client.employee_ids["sales"]
    r = admin.patch(f"/api/hr/employees/{staff_id}",
                    json={"manager_id": manager_id, "bank_account_no": BANK_FULL,
                          "pan": PAN_FULL, "bank_ifsc": "HDFC0001234"})
    assert r.status_code == 200, r.text
    r = admin.patch(f"/api/hr/employees/{manager_id}",
                    json={"bank_account_no": "123456789012", "pan": "ABCDE1234F"})
    assert r.status_code == 200, r.text
    return {"staff": staff_id, "manager": manager_id, "sales": sales_id}


def _login_as(client, user_id: int) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        token = make_token(user.id, user.token_version or 1)
    client.cookies.set("session", token)


def _custom_writer(client) -> int:
    """A user who may edit employees but does not hold hr:confidential."""
    admin = client.as_user("admin")
    name = f"hr_writer_{uuid4().hex[:6]}"
    role = admin.post("/api/roles", json={
        "name": name, "display_name": "HR writer (no confidential)",
        "permissions": ["hr:read", "hr:write", "hr:attendance_self"]})
    assert role.status_code == 201, role.text
    emp = admin.post("/api/employees", json={
        "code": f"W{uuid4().hex[:5].upper()}", "full_name": "HR writer"})
    assert emp.status_code == 201, emp.text
    created = admin.post("/api/users", json={
        "username": name, "role": name, "password": "TestPass!123",
        "employee_id": emp.json()["id"]})
    assert created.status_code == 201, created.text
    # The first-login password change is not what this test is about.
    with SessionLocal() as db:
        user = db.get(User, created.json()["id"])
        user.must_change_password = False
        db.commit()
    return created.json()["id"]


def test_reporting_manager_sees_only_their_chain(client, linked_team):
    _login_as(client, client.ids["manager"])
    rows = client.get("/api/hr/employees").json()
    ids = {r["id"] for r in rows}
    assert ids == {linked_team["manager"], linked_team["staff"]}
    assert linked_team["sales"] not in ids

    assert client.get(f"/api/hr/employees/{linked_team['staff']}").status_code == 200
    assert client.get(f"/api/hr/employees/{linked_team['sales']}").status_code == 403

    # An ordinary employee sees only themselves, not the manager above them.
    _login_as(client, client.ids["staff"])
    own = client.get("/api/hr/employees").json()
    assert [r["id"] for r in own] == [linked_team["staff"]]
    assert client.get(f"/api/hr/employees/{linked_team['manager']}").status_code == 403


def test_bank_and_id_are_masked_without_the_confidential_right(client, linked_team):
    _login_as(client, client.ids["manager"])
    row = client.get(f"/api/hr/employees/{linked_team['staff']}").json()
    assert row["confidential_visible"] is False
    assert row["bank_account_no"].endswith(BANK_FULL[-4:])
    assert BANK_FULL not in row["bank_account_no"]
    assert row["pan"].endswith(PAN_FULL[-4:])
    assert PAN_FULL not in row["pan"]

    # The person may read their own full values.
    _login_as(client, client.ids["staff"])
    own = client.get(f"/api/hr/employees/{linked_team['staff']}").json()
    assert own["confidential_visible"] is True
    assert own["bank_account_no"] == BANK_FULL

    # HR and payroll hold the confidential right through their seeded roles.
    for actor in ("hr_manager", "payroll"):
        _login_as(client, client.ids[actor])
        seen = client.get(f"/api/hr/employees/{linked_team['staff']}").json()
        assert seen["confidential_visible"] is True, actor
        assert seen["bank_account_no"] == BANK_FULL, actor


def test_employee_writes_without_confidential_right_cannot_touch_bank_data(client, linked_team):
    _login_as(client, _custom_writer(client))
    denied = client.patch(f"/api/hr/employees/{linked_team['staff']}",
                          json={"bank_account_no": "111122223333"})
    assert denied.status_code == 403, denied.text
    allowed = client.patch(f"/api/hr/employees/{linked_team['staff']}",
                           json={"designation": "Senior Associate"})
    assert allowed.status_code == 200, allowed.text


def test_bank_change_is_written_to_the_audit_trail_masked(client, linked_team):
    admin = client.as_user("admin")
    new_value = "444433332222"
    r = admin.patch(f"/api/hr/employees/{linked_team['staff']}",
                    json={"bank_account_no": new_value})
    assert r.status_code == 200, r.text
    logs = admin.get("/api/audit", params={
        "action": "employee.update", "record": f"employee:{linked_team['staff']}"}).json()
    assert logs["total"] >= 1
    changes = logs["rows"][0]["changes"]
    assert new_value not in str(changes)
    assert changes["bank_account_no"]["new"].endswith(new_value[-4:])


def _payroll_approval(client) -> int:
    with SessionLocal() as db:
        ar = ApprovalRequest(record_type="hr_payroll", record_id=999999,
                             requested_by=client.ids["payroll"], reasons=["payroll"],
                             request_no=f"AP-TEST-{uuid4().hex[:6]}",
                             subject="Payroll 2026-10", pending_approver_role="admin",
                             detail={"year": 2026, "month": 10, "entries": 7,
                                     "net": "1234567.00"})
        db.add(ar)
        db.commit()
        return ar.id


def test_payroll_approval_is_hidden_from_non_payroll_roles(client, world):
    approval_id = _payroll_approval(client)

    def visible(actor: str) -> bool:
        _login_as(client, client.ids[actor])
        rows = client.get("/api/approvals").json()
        return any(r["id"] == approval_id for r in rows)

    assert visible("staff") is False
    assert visible("manager") is False
    assert visible("hr_manager") is False  # preparer, not approver
    assert visible("payroll") is True      # submitted it
    assert visible("admin") is True


def test_manager_decides_only_inside_the_chain(client, linked_team):
    admin = client.as_user("admin")
    lt = admin.post("/api/hr/leave/types", json={
        "code": f"T{uuid4().hex[:4].upper()}", "name": "Scope test leave",
        "kind": "paid", "default_days": "10"}).json()
    start = date.today() + timedelta(days=30)
    args = {"leave_type_id": lt["id"], "date_from": start.isoformat(),
            "date_to": start.isoformat(), "reason": "Team scope test"}
    inside = admin.post("/api/hr/leave/applications",
                        json={**args, "employee_id": linked_team["staff"]})
    outside = admin.post("/api/hr/leave/applications",
                         json={**args, "employee_id": linked_team["sales"]})
    assert inside.status_code == 201, inside.text
    assert outside.status_code == 201, outside.text

    outside_row = next(r for r in admin.get("/api/approvals", params={
        "status": "pending", "request_type": "hr_leave"}).json()
        if r["record_id"] == outside.json()["id"])

    _login_as(client, client.ids["manager"])
    rows = client.get("/api/approvals",
                      params={"status": "pending", "request_type": "hr_leave"}).json()
    record_ids = {r["record_id"] for r in rows}
    assert inside.json()["id"] in record_ids
    assert outside.json()["id"] not in record_ids

    blocked = client.post(f"/api/approvals/{outside_row['id']}/decide",
                          json={"decision": "approve", "reason": "not my team"})
    assert blocked.status_code == 403

    inside_row = next(r for r in rows if r["record_id"] == inside.json()["id"])
    assert inside_row["can_decide"] is True
    done = client.post(f"/api/approvals/{inside_row['id']}/decide",
                       json={"decision": "approve", "reason": "approved"})
    assert done.status_code == 200, done.text


def test_salary_payable_is_hidden_from_staff(client, world):
    _login_as(client, client.ids["staff"])
    body = client.get("/api/hr/dashboard").json()
    assert body["payroll_visible"] is False
    assert body["salary_payable"] is None
    assert body["payroll_status"] is None

    _login_as(client, client.ids["payroll"])
    body = client.get("/api/hr/dashboard").json()
    assert body["payroll_visible"] is True