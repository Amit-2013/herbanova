"""Directory filters, saved views, CSV export and bulk import."""
from datetime import date, timedelta
from uuid import uuid4

from app.core.db import SessionLocal
from app.core.security import make_token
from app.models.core import User


def _new_employee(client, **fields) -> dict:
    admin = client.as_user("admin")
    code = fields.pop("code", f"D{uuid4().hex[:5].upper()}")
    r = admin.post("/api/hr/employees", json={"code": code, "full_name": "Directory Test",
                                              **fields})
    assert r.status_code == 201, r.text
    return r.json()


def test_directory_filters_and_sorting(client, world):
    admin = client.as_user("admin")
    today = date.today()
    a = _new_employee(client, full_name="Zulu Person", department="FilterDept",
                      designation="Analyst", joining_date=(today - timedelta(days=40)).isoformat())
    b = _new_employee(client, full_name="Alpha Person", department="FilterDept",
                      designation="Manager", joining_date=(today - timedelta(days=10)).isoformat())

    rows = admin.get("/api/hr/employees", params={"department": "FilterDept"}).json()
    assert {r["id"] for r in rows} == {a["id"], b["id"]}

    recent = admin.get("/api/hr/employees", params={
        "department": "FilterDept", "joined_from": (today - timedelta(days=20)).isoformat()}).json()
    assert [r["id"] for r in recent] == [b["id"]]

    newest = admin.get("/api/hr/employees", params={
        "department": "FilterDept", "sort": "joining_date", "order": "desc"}).json()
    assert newest[0]["id"] == b["id"]

    incomplete = admin.get("/api/hr/employees", params={"incomplete": "true"}).json()
    assert any(r["id"] == a["id"] for r in incomplete)  # no manager, phone, email, office

    page = admin.get("/api/hr/employees", params={"page": 1, "page_size": 2})
    assert page.headers["X-Total-Count"].isdigit()


def test_saved_views_belong_to_their_owner(client, world):
    admin = client.as_user("admin")
    name = f"My view {uuid4().hex[:4]}"
    created = admin.post("/api/hr/saved-filters", json={
        "name": name, "params": {"department": "Sales", "status": "active"}})
    assert created.status_code == 201, created.text
    filter_id = created.json()["id"]
    listed = admin.get("/api/hr/saved-filters").json()
    assert any(f["id"] == filter_id and f["params"]["department"] == "Sales" for f in listed)
    assert admin.post("/api/hr/saved-filters", json={
        "name": name, "params": {}}).status_code == 409

    # Another person cannot delete it.
    client.as_user("hr_manager")
    assert client.delete(f"/api/hr/saved-filters/{filter_id}").status_code == 404

    admin = client.as_user("admin")
    assert admin.delete(f"/api/hr/saved-filters/{filter_id}").status_code == 200
    assert all(f["id"] != filter_id for f in admin.get("/api/hr/saved-filters").json())


def test_export_keeps_confidential_columns_masked(client, world):
    staff_id = client.employee_ids["staff"]
    client.as_user("admin").patch(f"/api/hr/employees/{staff_id}", json={
        "bank_account_no": "555566667777", "pan": "ABCDE1234F",
        "manager_id": client.employee_ids["manager"]})

    admin_csv = client.get("/api/hr/employees/export.csv")
    assert admin_csv.status_code == 200
    assert "bank_account_no" in admin_csv.text
    assert "555566667777" in admin_csv.text

    client.as_user("manager")
    masked_csv = client.get("/api/hr/employees/export.csv")
    assert masked_csv.status_code == 200
    assert "555566667777" not in masked_csv.text
    assert "7777" in masked_csv.text


def test_import_preview_reports_row_errors_and_commit_is_undoable(client, world):
    admin = client.as_user("admin")
    code = f"IMP{uuid4().hex[:5].upper()}"
    csv_text = (
        "code,full_name,department,designation,phone,email,joining_date\n"
        f"{code},Imported Person,Sales,Associate,9876543210,imported@example.com,2026-01-15\n"
        f"{code},Duplicate In File,Sales,Associate,,,2026-01-15\n"
        "BADCODE,X,Ops,,,not-an-email,15-01-2026\n")

    preview = admin.post("/api/hr/employees/import", json={
        "filename": "people.csv", "csv_text": csv_text, "commit": False})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["valid_rows"] == 1
    assert body["error_rows"] == 2
    assert body["batch_id"] is None
    # Preview wrote nothing.
    assert all(r["code"] != code for r in admin.get("/api/hr/employees").json())

    committed = admin.post("/api/hr/employees/import", json={
        "filename": "people.csv", "csv_text": csv_text, "commit": True})
    assert committed.status_code == 200, committed.text
    batch_id = committed.json()["batch_id"]
    assert batch_id
    created = next(r for r in admin.get("/api/hr/employees").json() if r["code"] == code)
    assert created["department"] == "Sales"

    # Importing the same code again is a row error, not a duplicate record.
    again = admin.post("/api/hr/employees/import", json={
        "filename": "people.csv", "csv_text": csv_text, "commit": False})
    assert again.json()["valid_rows"] == 0

    undone = admin.post(f"/api/hr/employees/import-batches/{batch_id}/undo")
    assert undone.status_code == 200, undone.text
    assert undone.json()["employees_deactivated"] == 1
    row = next(r for r in admin.get("/api/hr/employees").json() if r["id"] == created["id"])
    assert row["status"] == "inactive"
    assert admin.post(f"/api/hr/employees/import-batches/{batch_id}/undo").status_code == 409


def test_import_of_bank_data_needs_the_confidential_right(client, world):
    admin = client.as_user("admin")
    name = f"imp_writer_{uuid4().hex[:6]}"
    admin.post("/api/roles", json={
        "name": name, "permissions": ["hr:read", "hr:write", "hr:attendance_self"]})
    emp = admin.post("/api/employees", json={
        "code": f"IW{uuid4().hex[:5].upper()}", "full_name": "Import writer"}).json()
    created = admin.post("/api/users", json={
        "username": name, "role": name, "password": "TestPass!123",
        "employee_id": emp["id"]}).json()
    with SessionLocal() as db:
        user = db.get(User, created["id"])
        user.must_change_password = False
        token = make_token(user.id, user.token_version or 1)
        db.commit()
    client.cookies.set("session", token)

    text = ("code,full_name,bank_account_no\n"
            f"BANK{uuid4().hex[:5].upper()},Bank Import,123456789012\n")
    denied = client.post("/api/hr/employees/import", json={
        "filename": "bank.csv", "csv_text": text, "commit": False})
    assert denied.status_code == 403