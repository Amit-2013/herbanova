"""Printable HR output: letter templates, letters, ID cards, attendance sheets
and leave statements.

Every PDF is opened with pypdf so the assertions are about what a reader would
see, not only about the response status. No real data is used: employees and
leave rows are created inside the isolated test database.
"""
from io import BytesIO
from uuid import uuid4

from pypdf import PdfReader
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import AuditLog


def _pdf_text(response) -> str:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")
    reader = PdfReader(BytesIO(response.content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _employee(client, **fields):
    payload = {"code": f"DOC{uuid4().hex[:5].upper()}",
               "full_name": f"Document subject {uuid4().hex[:4]}"}
    payload.update(fields)
    resp = client.as_user("admin").post("/api/hr/employees", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _audit(action, record):
    with SessionLocal() as db:
        return db.scalar(select(AuditLog).where(AuditLog.action == action,
                                                 AuditLog.record == record)
                         .order_by(AuditLog.id.desc()))


def test_letter_templates_are_listed_editable_and_validated(client):
    listing = client.as_user("hr_manager").get("/api/hr/letters/templates")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    codes = {t["code"] for t in body["templates"]}
    assert {"OFFER", "APPOINTMENT", "EXPERIENCE", "RELIEVING"} <= codes
    assert "employee_name" in body["placeholders"]
    offer = next(t for t in body["templates"] if t["code"] == "OFFER")

    assert client.as_user("staff").patch(
        f"/api/hr/letters/templates/{offer['id']}",
        json={"name": "Not allowed"}).status_code == 403

    unknown = client.as_user("hr_manager").patch(
        f"/api/hr/letters/templates/{offer['id']}",
        json={"body": "Dear {employee_name}, your salary is {salary_amount}."})
    assert unknown.status_code == 422
    assert "salary_amount" in unknown.json()["detail"]

    marker = f"Offer letter {uuid4().hex[:4]}"
    try:
        edited = client.as_user("hr_manager").patch(
            f"/api/hr/letters/templates/{offer['id']}", json={"name": marker})
        assert edited.status_code == 200, edited.text
        assert edited.json()["name"] == marker
        entry = _audit("hr.letter_template.update", f"letter_template:{offer['id']}")
        assert entry is not None and entry.actor_id
    finally:
        client.as_user("admin").patch(f"/api/hr/letters/templates/{offer['id']}",
                                      json={"name": offer["name"]})
    assert client.as_user("hr_manager").get(
        "/api/hr/letters/templates").json()["templates"][0]["name"] == offer["name"]


def test_letters_fill_placeholders_and_report_missing_dates(client):
    emp_id = _employee(client, joining_date="2035-01-07", department="Quality",
                       designation="Analyst", date_of_exit="2035-08-31")
    offer = client.as_user("admin").get(
        "/api/hr/outputs/letter/OFFER", params={"employee_id": emp_id})
    text = _pdf_text(offer)
    assert "Offer letter" in text
    assert "Document subject" in text
    assert "Quality" in text
    assert "07 January 2035" in text
    assert offer.headers["content-disposition"].endswith('.pdf"')

    experience = client.as_user("admin").get(
        "/api/hr/outputs/letter/EXPERIENCE",
        params={"employee_id": emp_id, "exit_date": "2035-10-01"})
    assert "01 October 2035" in _pdf_text(experience)

    no_exit = _employee(client, joining_date="2035-02-03")
    missing = client.as_user("admin").get(
        "/api/hr/outputs/letter/RELIEVING", params={"employee_id": no_exit})
    assert missing.status_code == 422
    assert "exit date" in missing.json()["detail"]

    entry = _audit("hr.output.letter", f"employee:{emp_id}")
    assert entry is not None and entry.changes["template"] == "EXPERIENCE"


def test_letters_and_cards_follow_the_server_side_scope(client):
    other = _employee(client, joining_date="2035-03-04",
                      bank_account_no="555544443333", pan="ABCDE1234F")
    linked = client.employee_ids["staff"]
    profile = client.as_user("admin").get(f"/api/hr/employees/{linked}/profile").json()
    original = profile["employee"]["joining_date"]
    try:
        client.as_user("admin").patch(f"/api/hr/employees/{linked}",
                                      json={"joining_date": None})
        own_offer = client.as_user("staff").get("/api/hr/outputs/letter/OFFER")
        # The staff login has no joining date on its linked employee record.
        assert own_offer.status_code == 422
        assert "joining date" in own_offer.json()["detail"]

        updated = client.as_user("admin").patch(f"/api/hr/employees/{linked}",
                                                json={"joining_date": "2034-09-01"})
        assert updated.status_code == 200, updated.text
        assert client.as_user("staff").get(
            "/api/hr/outputs/letter/OFFER").status_code == 200
        refused = client.as_user("staff").get(
            "/api/hr/outputs/letter/OFFER", params={"employee_id": other})
        assert refused.status_code == 403
    finally:
        client.as_user("admin").patch(f"/api/hr/employees/{linked}",
                                      json={"joining_date": original})

    card = client.as_user("admin").get("/api/hr/outputs/id-card",
                                       params={"employee_id": other})
    text = _pdf_text(card)
    assert "EMPLOYEE ID" in text and "IF FOUND" in text
    assert "555544443333" not in text and "ABCDE1234F" not in text
    assert client.as_user("staff").get(
        "/api/hr/outputs/id-card", params={"employee_id": other}).status_code == 403
    assert _pdf_text(client.as_user("staff").get("/api/hr/outputs/id-card"))


def test_attendance_sheet_matches_the_screen_and_scope(client):
    emp_id = _employee(client, joining_date="2035-03-01")
    marked = client.as_user("hr_manager").post("/api/hr/attendance/bulk", json={
        "employee_ids": [emp_id], "date_from": "2035-03-01", "date_to": "2035-03-02",
        "status": "present", "remarks": "Attendance sheet test"})
    assert marked.status_code == 200, marked.text
    screen = client.as_user("admin").get("/api/hr/attendance/monthly",
                                         params={"year": 2035, "month": 3})
    assert screen.status_code == 200, screen.text
    row = next(e for e in screen.json()["employees"] if e["employee_id"] == emp_id)
    assert row["summary"]["present_days"] == 2

    sheet = client.as_user("admin").get("/api/hr/outputs/attendance-sheet",
                                        params={"year": 2035, "month": 3,
                                                "employee_id": emp_id})
    text = _pdf_text(sheet)
    assert "attendance sheet March 2035" in text
    assert "Document subject" in text
    assert "not recorded" in text
    assert _pdf_text(client.as_user("staff").get(
        "/api/hr/outputs/attendance-sheet", params={"year": 2035, "month": 3}))
    assert client.as_user("staff").get(
        "/api/hr/outputs/attendance-sheet",
        params={"year": 2035, "month": 3, "employee_id": emp_id}).status_code == 403


def test_leave_statement_prints_stored_balances(client):
    emp_id = _employee(client, joining_date="2035-04-01")
    leave_type = client.as_user("admin").post("/api/hr/leave/types", json={
        "code": f"DS{uuid4().hex[:4].upper()}", "name": f"Statement leave {uuid4().hex[:4]}",
        "kind": "paid", "default_days": "12"})
    assert leave_type.status_code == 201, leave_type.text
    type_id = leave_type.json()["id"]
    applied = client.as_user("admin").post("/api/hr/leave/applications", json={
        "leave_type_id": type_id, "employee_id": emp_id,
        "date_from": "2035-04-02", "date_to": "2035-04-03",
        "reason": "Statement test"})
    assert applied.status_code == 201, applied.text
    pending = client.as_user("hr_manager").get(
        "/api/approvals", params={"status": "pending", "request_type": "hr_leave"}).json()
    request = next(a for a in pending if a["record_id"] == applied.json()["id"])
    decided = client.as_user("hr_manager").post(
        f"/api/approvals/{request['id']}/decide",
        json={"decision": "approve", "reason": "Approved for the statement test"})
    assert decided.status_code == 200, decided.text

    statement = client.as_user("admin").get(
        "/api/hr/outputs/leave-statement",
        params={"employee_id": emp_id, "year": 2035})
    text = _pdf_text(statement)
    assert "Leave statement — 2035" in text
    assert "Statement leave" in text
    assert "Approved days in 2035: 2" in text
    assert _pdf_text(client.as_user("staff").get(
        "/api/hr/outputs/leave-statement", params={"year": 2035}))
    assert client.as_user("staff").get(
        "/api/hr/outputs/leave-statement",
        params={"employee_id": emp_id, "year": 2035}).status_code == 403
    entry = _audit("hr.output.leave_statement", f"employee:{emp_id}")
    assert entry is not None and entry.changes["applications"] == 1


def test_leave_statement_reads_without_creating_balances(client):
    from app.models.hr import LeaveBalance

    emp_id = _employee(client)
    statement = client.as_user("admin").get(
        "/api/hr/outputs/leave-statement",
        params={"employee_id": emp_id, "year": 2036})
    text = _pdf_text(statement)
    assert "Leave statement — 2036" in text
    assert "No data yet: no leave balances have been set for this year." in text
    with SessionLocal() as db:
        rows = db.scalars(select(LeaveBalance).where(
            LeaveBalance.employee_id == emp_id)).all()
    assert rows == []
