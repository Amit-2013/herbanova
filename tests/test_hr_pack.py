"""The scheduled HR pack: figures from the HR reports, never a salary amount.

Three promises are pinned here:
  * the pack is a registered schedule type and only the Administrator can open
    the scheduled-reports screen that sends it;
  * the email and its attachments carry the same tables as the report layer and
    say "No data yet" where an input is missing;
  * pay stays out of the pack and its files, even though the report layer can
    produce the confidential Department cost report.
"""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.core import User
from app.models.email import EmailDelivery, EmailSchedule
from app.models.hr import Attendance, EmployeeDocument
from app.models.users import Employee
from app.services import email_render, email_worker, mailer, report_packs

UTC = timezone.utc
BASE = "/api/email-reports"
START, END = date(2034, 3, 1), date(2034, 3, 31)
FIXTURE_NAME = "Pack Fixture"


def _payload(**overrides):
    body = {"name": "HR pack to the MD", "pack_key": "hr", "enabled": True,
            "frequency": "monthly", "timezone": "Asia/Kolkata", "weekdays": [],
            "times": ["09:00"], "month_day": 1, "month_rule": "day",
            "custom_cron": None, "holiday_rule": "shift",
            "include_attachments": True, "include_accounts": False,
            "custom_reports": [], "groups": [], "recipients": []}
    body.update(overrides)
    return body


def _seed(db) -> Employee:
    """One joiner with attendance and a document expiring soon, inside a flush
    that the caller rolls back so no other test sees these rows."""
    suffix = uuid4().hex[:6]
    employee = Employee(code=f"PK-{suffix}"[:30], full_name=FIXTURE_NAME,
                        department="Pack dept", designation="Analyst",
                        status="active", joining_date=START + timedelta(days=4),
                        date_of_exit=None, employment_type="permanent")
    db.add(employee)
    db.flush()
    db.add_all([
        Attendance(employee_id=employee.id, date=START, status="present",
                   source="manual", late_minutes=0),
        Attendance(employee_id=employee.id, date=START + timedelta(days=1),
                   status="absent", source="manual", late_minutes=0),
    ])
    db.add(EmployeeDocument(employee_id=employee.id, doc_type="licence",
                            title="Fixture licence",
                            expires_on=date.today() + timedelta(days=10),
                            status="active"))
    db.flush()
    return employee


# --- registration ----------------------------------------------------------

def test_the_hr_pack_is_a_registered_pack_with_a_monthly_window(client):
    meta = report_packs.pack_meta("hr")
    assert meta["label"] == "HR Report Pack"
    assert meta["period"] == "month"
    assert meta["accounts"] is False

    window = report_packs.period_for("hr", date(2026, 11, 5))
    assert (window["from"], window["to"]) == (date(2026, 10, 1), date(2026, 10, 31))

    admin = client.as_user("admin").get(BASE + "/status")
    assert admin.status_code == 200, admin.text
    packs = {p["key"]: p["label"] for p in admin.json()["packs"]}
    assert packs.get("hr") == "HR Report Pack"

    denied = client.as_user("sales").get(BASE + "/status")
    assert denied.status_code == 403


# --- build -----------------------------------------------------------------

def test_pack_figures_come_from_the_report_layer_and_say_no_data_yet(world):
    with SessionLocal() as db:
        _seed(db)
        data = report_packs.build(db, "hr", START, END)

        assert data["hr_pack"] is True and data["pack_key"] == "hr"
        assert data["label"] == "HR Report Pack"
        assert (data["from"], data["to"]) == (START.isoformat(), END.isoformat())

        # The five non-confidential reports are the only ones asked for.
        assert set(data["_built"]) == {"headcount", "joiners-leavers",
                                       "attendance-summary", "late-absentee",
                                       "document-expiry"}

        kpis = {k["key"]: k["display"] for k in data["kpis"]}
        assert set(kpis) == {"headcount", "joiners", "leavers", "pending",
                             "documents", "probation"}
        movements = next(t for t in data["tables"] if t["key"] == "movements")
        assert any(r["full_name"] == FIXTURE_NAME for r in movements["rows"])
        attendance = next(t for t in data["tables"] if t["key"] == "attendance")
        assert any(r["full_name"] == FIXTURE_NAME for r in attendance["rows"])

        # No attendance exists in 2039, so the pack says so instead of zeroes.
        empty = report_packs.build(db, "hr", date(2039, 1, 1), date(2039, 1, 31))
        assert empty["gaps"]
        assert any("No joiners or leavers" in gap for gap in empty["gaps"])
        assert any("attendance" in gap.lower() for gap in empty["gaps"])
        db.rollback()


def test_no_salary_amount_appears_in_the_pack_or_its_files(world):
    with SessionLocal() as db:
        _seed(db)
        data = report_packs.build(db, "hr", START, END)
        data["include_attachments"] = True
        attachments = report_packs.build_attachments(db, data, "hr")
        db.rollback()

    # Pay is confidential; the pack links to the Department cost report instead.
    assert any("Salary amounts are not included" in note for note in data["notes"])
    table_keys = {t["key"] for t in data["tables"]}
    assert "department-cost" not in table_keys
    for table in data["tables"]:
        labels = {c["label"].lower() for c in table["columns"]}
        assert not labels & {"gross", "deductions", "net", "salary", "pay"}

    kinds = {a["kind"] for a in attachments}
    assert {"summary", "register"} <= kinds
    pdf = next(a for a in attachments if a["content_type"] == "application/pdf")
    assert pdf["filename"].startswith("HERBANOVA_HR_Report_")
    assert pdf["bytes"].startswith(b"%PDF")
    csvs = [a for a in attachments if a["content_type"] == "text/csv"]
    assert {a["filename"] for a in csvs} == {
        f"HERBANOVA_HR_headcount_{START}_{END}.csv",
        f"HERBANOVA_HR_attendance-summary_{START}_{END}.csv"}
    for item in attachments:
        lowered = item["bytes"].lower()
        assert b"salary" not in lowered and b"net pay" not in lowered
    assert sum(len(a["bytes"]) for a in attachments) <= settings.email_max_bytes


# --- render ----------------------------------------------------------------

def test_render_marks_test_mode_and_carries_the_same_figures(world):
    with SessionLocal() as db:
        _seed(db)
        data = report_packs.build(db, "hr", START, END)
        data["include_attachments"] = False
        rendered = email_render.render(data, [], mode="test",
                                       test_recipient="admin@example.test",
                                       real_recipients=2, owner="admin")
        db.rollback()

    assert "TEST MODE" in rendered["html"]
    assert "admin@example.test" in rendered["text"]
    assert rendered["subject"].startswith("[TEST] HERBANOVA | HR Report Pack |")
    assert rendered["subject"].endswith(f"Headcount {data['kpis'][0]['display']}")
    for kpi in data["kpis"]:
        assert kpi["display"] in rendered["text"]
    assert FIXTURE_NAME in rendered["html"]
    assert "Salary amounts are not included" in rendered["html"]
    assert "Net pay" not in rendered["html"]

    assert "<script" not in rendered["html"].lower()
    assert 'src="http' not in rendered["html"]

    preview = email_render.render(data, [], mode="preview")
    assert "PREVIEW." in preview["html"]
    assert "TEST MODE" not in preview["html"]


# --- API and worker --------------------------------------------------------

def test_the_administrator_can_preview_an_hr_schedule(client):
    admin = client.as_user("admin")
    created = admin.post(BASE + "/schedules", json=_payload())
    assert created.status_code in (200, 201), created.text
    schedule_id = created.json()["id"]
    try:
        preview = admin.get(f"{BASE}/schedules/{schedule_id}/preview")
        assert preview.status_code == 200, preview.text
        assert "HR Report Pack" in preview.text
        assert "PREVIEW." in preview.text
        assert "Salary amounts are not included" in preview.text
        assert "Net pay" not in preview.text

        denied = client.as_user("hr_manager").get(
            f"{BASE}/schedules/{schedule_id}/preview")
        assert denied.status_code == 403
    finally:
        client.as_user("admin").delete(f"{BASE}/schedules/{schedule_id}")


def test_the_worker_sends_the_hr_pack_in_test_mode(world, monkeypatch):
    sent = {}

    def fake_send(db, schedule_obj, rendered, people):
        sent["rendered"] = rendered
        sent["people"] = people
        return {"size": len(rendered["html"].encode()), "to": 1, "cc": 0, "bcc": 0}

    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "email_send_enabled", False)
    monkeypatch.setattr(settings, "email_test_recipient", "admin@example.test")
    monkeypatch.setattr(mailer, "send", fake_send)

    suffix = uuid4().hex[:6]
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "admin"))
        schedule_obj = EmailSchedule(
            name=f"HR pack {suffix}", pack_key="hr", enabled=True, frequency="monthly",
            timezone="Asia/Kolkata", weekdays=[], month_day=1, month_rule="day",
            times=["09:00"], custom_cron=None, holiday_rule="shift",
            include_attachments=True, include_accounts=False, custom_reports=[],
            groups=[], next_run_at=None, created_by=actor.id)
        db.add(schedule_obj)
        db.commit()
        delivery, _ = email_worker.create_delivery(
            db, schedule_obj, datetime.now(UTC), "manual")
        db.commit()
        delivery_id = delivery.id

        assert email_worker.process_one(db, delivery_id, datetime.now(UTC)) == "sent"
        db.refresh(delivery)
        assert delivery.status == "sent"
        assert delivery.mode == "test"
        assert delivery.subject.startswith("[TEST] HERBANOVA | HR Report Pack |")
        names = [a["filename"] for a in delivery.attachments]
        assert any(n.endswith(".pdf") for n in names)
        assert sent["people"]["to"] == ["admin@example.test"]
        assert "HR Report Pack" in sent["rendered"]["html"]
        # The footer names the confidential report; no cost table is in the mail.
        assert ">Gross<" not in sent["rendered"]["html"]
        assert ">Net<" not in sent["rendered"]["html"]

        db.delete(db.get(EmailDelivery, delivery_id))
        db.delete(schedule_obj)
        db.commit()
