"""HR notifications, announcements and the daily digest.

The bell is the source of truth: every message is a row addressed to one user.
Email is a second channel and must always be a test-mode message, so the tests
patch the SMTP sender out and inspect the envelope instead of posting anything.
"""
from datetime import date, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.models.core import User
from app.models.hr import HRNotification
from app.services import hr as hr_svc
from app.services import hr_notify, mailer


def _next_monday(offset_days: int) -> date:
    day = date.today() + timedelta(days=offset_days)
    return day + timedelta(days=(7 - day.weekday()) % 7)


def _leave_type(client) -> int:
    created = client.as_user("admin").post("/api/hr/leave/types", json={
        "code": "NTL", "name": "Notification leave", "kind": "paid",
        "default_days": "12"})
    if created.status_code == 201:
        return created.json()["id"]
    assert created.status_code == 409, created.text
    listed = client.as_user("admin").get("/api/hr/leave/types").json()
    return next(t["id"] for t in listed if t["code"] == "NTL")


def test_request_notification_goes_to_the_employees_own_manager(client, world):
    """A linked manager is the only manager told about that employee's request."""
    from app.core.db import SessionLocal
    from app.models.users import Employee

    with SessionLocal() as db:
        staff = db.get(Employee, client.employee_ids["staff"])
        manager = db.get(Employee, client.employee_ids["manager"])
        staff.manager_id = manager.id
        db.flush()
        hr_svc.request_approval(
            db, record_type="hr_leave", record_id=999999,
            requested_by=client.ids["staff"], reasons=["leave"],
            detail={"employee_id": staff.id}, subject="Routing probe",
            approver_role="reporting_manager")
        notes = db.scalars(select(HRNotification).where(
            HRNotification.title == "Approval needed: Routing probe")).all()
        manager_user = db.scalar(select(User).where(User.employee_id == manager.id))
        assert {n.user_id for n in notes} == {manager_user.id}
        db.rollback()


def test_leave_request_notifies_the_queue_and_the_decision_reaches_the_requester(client, world):
    leave_type_id = _leave_type(client)
    start = _next_monday(200)
    applied = client.as_user("staff").post("/api/hr/leave/applications", json={
        "leave_type_id": leave_type_id, "date_from": start.isoformat(),
        "date_to": start.isoformat(), "reason": "Notification check"})
    assert applied.status_code == 201, applied.text
    application_id = applied.json()["id"]

    queue = client.as_user("manager").get("/api/hr/notifications").json()
    approver_note = next(n for n in queue["items"]
                         if n["kind"] == "approval_request"
                         and n["title"] == "Approval needed: Test staff: Notification leave")
    assert approver_note["link"] == "/ui#approvals"
    assert queue["unread"] >= 1

    pending = client.as_user("hr_manager").get("/api/approvals",
                                               params={"status": "pending"}).json()
    request = next(a for a in pending
                   if a["request_type"] == "hr_leave" and a["record_id"] == application_id)
    decided = client.as_user("hr_manager").post(
        f"/api/approvals/{request['id']}/decide",
        json={"decision": "approve", "reason": "Approved in test"})
    assert decided.status_code == 200, decided.text

    mine = client.as_user("staff").get("/api/hr/notifications").json()
    decision = next(n for n in mine["items"]
                    if n["kind"] == "approval_decision"
                    and "Notification leave" in n["body"])
    assert decision["title"] == "Your request was approved"
    assert "Approved in test" in decision["body"]

    # Another user's bell is not readable by id.
    assert client.as_user("manager").post(
        f"/api/hr/notifications/{decision['id']}/read").status_code == 404

    read = client.as_user("staff").post(f"/api/hr/notifications/{decision['id']}/read")
    assert read.status_code == 200 and read.json()["read_at"] is not None
    assert client.as_user("staff").get("/api/hr/notifications",
                                       params={"unread_only": True}).json()["unread"] == 0
    assert client.as_user("staff").post("/api/hr/notifications/read-all").status_code == 200


def test_announcement_fans_out_to_linked_users_and_can_be_retired(client, world):
    assert client.as_user("sales").post("/api/hr/announcements", json={
        "title": "Not allowed", "body": "Sales cannot publish notices"}).status_code == 403

    created = client.as_user("admin").post("/api/hr/announcements", json={
        "title": "Office closed on Friday",
        "body": "The office is closed this Friday for maintenance."})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["notified"] >= 1
    assert body["active"] is True

    staff_view = client.as_user("staff").get("/api/hr/announcements").json()
    assert any(a["id"] == body["id"] for a in staff_view)
    bell = client.as_user("staff").get("/api/hr/notifications").json()
    note = next(n for n in bell["items"] if n["kind"] == "announcement"
                and "Office closed on Friday" in n["title"])
    assert note["body"] == "The office is closed this Friday for maintenance."

    retired = client.as_user("admin").patch(f"/api/hr/announcements/{body['id']}",
                                            json={"active": False})
    assert retired.status_code == 200 and retired.json()["active"] is False
    assert not any(a["id"] == body["id"]
                   for a in client.as_user("staff").get("/api/hr/announcements").json())
    admin_view = client.as_user("admin").get("/api/hr/announcements",
                                             params={"include_inactive": True}).json()
    assert any(a["id"] == body["id"] for a in admin_view)


def test_digest_runs_once_a_day_and_only_mails_the_test_address(client, world, monkeypatch):
    assert client.as_user("payroll").post("/api/hr/notifications/digest").status_code == 403

    sent = []
    monkeypatch.setattr(mailer, "send", lambda db, schedule, rendered, people: (
        sent.append((rendered, people)) or {"size": 1, "to": 1, "cc": 0, "bcc": 0}))
    monkeypatch.setattr(settings, "email_send_enabled", True)
    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_from", "hr@example.test")
    monkeypatch.setattr(settings, "email_test_recipient", "ops@example.test")
    monkeypatch.setattr(hr_notify, "digest_rows", lambda db, today: {
        "birthdays": [{"employee_id": 1, "code": "T", "full_name": "Test person",
                       "turning": 30}],
        "anniversaries": [], "documents": [], "probation": []})

    first = client.as_user("admin").post("/api/hr/notifications/digest")
    assert first.status_code == 200, first.text
    assert first.json()["queued"] >= 1
    assert first.json()["email"]["sent"] is True
    assert sent and sent[0][1]["to"] == ["ops@example.test"]
    assert sent[0][0]["subject"].startswith("[TEST] ")

    again = client.as_user("admin").post("/api/hr/notifications/digest")
    assert again.status_code == 200
    assert again.json()["skipped"] is True and again.json()["queued"] == 0
    assert len(sent) == 1                       # no second email, no duplicate rows

    hr_bell = client.as_user("hr_manager").get("/api/hr/notifications").json()
    assert any(n["kind"] == "hr_digest" for n in hr_bell["items"])
