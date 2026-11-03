"""HR masters: department and holiday edits, and salary structure guards.

Every test creates its own department, holiday, component and employee with a
unique code, so the shared suite database stays independent of other HR tests.
Dates sit in 2035-2036 so these rows never change what the current-month
dashboard and payroll tests count.
"""
from uuid import uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import AuditLog


def _suffix() -> str:
    return uuid4().hex[:6].upper()


def _department(client, name=None):
    payload = {"code": f"D{_suffix()}", "name": name or f"Dept {uuid4().hex[:4]}"}
    r = client.as_user("admin").post("/api/hr/departments", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _branch(client):
    payload = {"code": f"BR{_suffix()}", "name": f"Branch {uuid4().hex[:4]}"}
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


def _component(client, **overrides):
    payload = {"code": f"C{_suffix()}", "name": f"Component {uuid4().hex[:4]}",
               "kind": "earning", "calc_type": "fixed", "default_rate": "0"}
    payload.update(overrides)
    r = client.as_user("admin").post("/api/hr/salary/components", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _structure(client, employee_id, effective_from, lines):
    return client.as_user("admin").post("/api/hr/salary/structures", json={
        "employee_id": employee_id, "effective_from": effective_from,
        "payment_mode": "bank", "lines": lines})


def test_department_rename_follows_linked_employees(client):
    admin = client.as_user("admin")
    name = f"Quality {_suffix()}"
    dept = _department(client, name)
    linked = _employee(client, department=name, department_id=dept["id"])
    free_text = _employee(client, department=name)

    r = admin.patch(f"/api/hr/departments/{dept['id']}", json={"name": name + " Assurance"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == name + " Assurance"

    assert admin.get(f"/api/hr/employees/{linked['id']}").json()["department"] == name + " Assurance"
    assert admin.get(f"/api/hr/employees/{free_text['id']}").json()["department"] == name

    # A second department cannot take the same name.
    duplicate = _department(client)
    r = admin.patch(f"/api/hr/departments/{duplicate['id']}", json={"name": name + " Assurance"})
    assert r.status_code == 409, r.text

    r = admin.patch(f"/api/hr/departments/{dept['id']}", json={"status": "inactive"})
    assert r.status_code == 200 and r.json()["status"] == "inactive"

    with SessionLocal() as db:
        actions = db.scalars(select(AuditLog.action).where(
            AuditLog.record == f"department:{dept['id']}")).all()
    assert "hr.department.update" in actions
    assert "hr.department.create" in actions


def test_department_edit_requires_hr_write(client):
    dept = _department(client)
    r = client.as_user("hr_manager").patch(f"/api/hr/departments/{dept['id']}",
                                           json={"name": "Renamed by HR"})
    assert r.status_code == 200, r.text
    r = client.as_user("staff").patch(f"/api/hr/departments/{dept['id']}",
                                      json={"name": "Renamed by staff"})
    assert r.status_code == 403, r.text


def test_holiday_edit_scope_and_conflicts(client):
    admin = client.as_user("admin")
    branch = _branch(client)
    office = _office(client, branch["id"])
    other_branch = _branch(client)
    other_office = _office(client, other_branch["id"])
    name = f"Foundation {_suffix()}"

    r = admin.post("/api/hr/holidays", json={"date": "2035-02-14", "name": name})
    assert r.status_code == 201, r.text
    holiday = r.json()
    assert holiday["branch_id"] is None and holiday["location_id"] is None

    r = admin.patch(f"/api/hr/holidays/{holiday['id']}",
                    json={"branch_id": branch["id"], "location_id": office["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["branch_id"] == branch["id"]
    assert r.json()["location_id"] == office["id"]

    # An office from another branch cannot be attached to this holiday.
    r = admin.patch(f"/api/hr/holidays/{holiday['id']}",
                    json={"location_id": other_office["id"]})
    assert r.status_code == 422, r.text
    r = admin.patch(f"/api/hr/holidays/{holiday['id']}", json={"branch_id": 999999})
    assert r.status_code == 404, r.text

    # Nulls clear the scope back to the whole company.
    r = admin.patch(f"/api/hr/holidays/{holiday['id']}",
                    json={"branch_id": None, "location_id": None})
    assert r.status_code == 200, r.text
    assert r.json()["branch_id"] is None and r.json()["location_id"] is None

    r = admin.post("/api/hr/holidays", json={"date": "2035-02-14", "name": name})
    assert r.status_code == 409, r.text

    r = client.as_user("staff").patch(f"/api/hr/holidays/{holiday['id']}",
                                      json={"name": "Staff rename"})
    assert r.status_code == 403, r.text

    with SessionLocal() as db:
        actions = db.scalars(select(AuditLog.action).where(
            AuditLog.record == f"holiday:{holiday['id']}")).all()
    assert "hr.holiday.update" in actions


def test_salary_structure_rejects_duplicate_components_and_overlap(client):
    admin = client.as_user("admin")
    component = _component(client, default_rate="1000")
    employee = _employee(client)
    line = {"component_id": component["id"], "amount": "1000", "percent": None}

    duplicate = _structure(client, employee["id"], "2035-01-01", [line, line])
    assert duplicate.status_code == 422, duplicate.text

    first = _structure(client, employee["id"], "2035-01-01", [line])
    assert first.status_code == 201, first.text

    same_start = _structure(client, employee["id"], "2035-01-01", [line])
    assert same_start.status_code == 409, same_start.text

    second = _structure(client, employee["id"], "2035-02-01", [line])
    assert second.status_code == 201, second.text

    rows = {s["id"]: s for s in admin.get(
        f"/api/hr/salary/structures?employee_id={employee['id']}").json()}
    assert rows[first.json()["id"]]["effective_to"] == "2035-01-31"
    assert rows[second.json()["id"]]["effective_to"] is None
    assert rows[second.json()["id"]]["status"] == "active"


def test_salary_masters_respect_role_boundaries(client):
    component = _component(client)
    employee = _employee(client)

    # Payroll may read salary but cannot change masters without hr:write.
    assert client.as_user("payroll").get("/api/hr/salary/components").status_code == 200
    r = client.as_user("payroll").post("/api/hr/salary/components", json={
        "code": f"P{_suffix()}", "name": "Payroll attempt", "kind": "earning"})
    assert r.status_code == 403, r.text
    assert client.as_user("hr_manager").get("/api/hr/salary/components").status_code == 403

    # A statutory head belongs to a deduction, never an earning.
    r = client.as_user("admin").post("/api/hr/salary/components", json={
        "code": f"E{_suffix()}", "name": "Bad statutory earning", "kind": "earning",
        "statutory": True, "statutory_head": "pf"})
    assert r.status_code == 422, r.text

    # The structure route needs hr:write as well as payroll access, so the
    # payroll role is refused even though it can read salary data.
    r = client.as_user("payroll").post("/api/hr/salary/structures", json={
        "employee_id": employee["id"], "effective_from": "2036-01-01",
        "payment_mode": "bank",
        "lines": [{"component_id": component["id"], "amount": "1", "percent": None}]})
    assert r.status_code == 403, r.text
