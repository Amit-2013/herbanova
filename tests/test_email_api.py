"""Scheduled reports API: Administrator only, validated schedules, safe queueing.

The API never sends; it queues a delivery and the worker sends. Test mode and
the kill switch are checked before a row is queued, so the screen cannot claim a
send is on its way when it cannot be.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.email import EmailDelivery, EmailRecipient, EmailSchedule
from app.services import email_worker, mailer

UTC = timezone.utc
BASE = "/api/email-reports"


def _payload(**overrides):
    body = {"name": "Daily to management", "pack_key": "daily", "enabled": True,
            "frequency": "weekdays", "timezone": "Asia/Kolkata", "weekdays": [],
            "times": ["09:00"], "month_day": None, "month_rule": None,
            "custom_cron": None, "holiday_rule": "shift",
            "include_attachments": False, "include_accounts": True,
            "custom_reports": [], "groups": [], "recipients": []}
    body.update(overrides)
    return body


def _allow_sending(monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "test")
    monkeypatch.setattr(settings, "email_send_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_from", "reports@example.test")


def test_only_an_administrator_can_open_the_screens(client):
    for path in ("/status", "/recipients", "/schedules", "/deliveries"):
        assert client.as_user("sales").get(BASE + path).status_code == 403, path
        assert client.as_user("viewer").get(BASE + path).status_code == 403, path
    assert client.as_user("sales").post(BASE + "/recipients",
                                        json={"email": "x@example.test"}).status_code == 403


def test_status_reports_the_guardrails_without_secrets(client):
    body = client.as_user("admin").get(BASE + "/status").json()
    assert body["mode"] in ("test", "live")
    assert "send_enabled" in body and "smtp_ready" in body
    assert {p["key"] for p in body["packs"]} >= {"daily", "weekly", "monthly_md",
                                                 "alerts", "accounts", "custom"}
    assert "smtp_password" not in str(body).lower()
    assert "smtp_user" not in str(body).lower()


def test_recipients_are_validated_and_unique(client):
    email = f"md-{uuid4().hex[:8]}@example.test"
    admin = client.as_user("admin")
    created = admin.post(BASE + "/recipients",
                         json={"email": email.upper(), "name": "MD", "group_key": "md"})
    assert created.status_code == 201, created.text
    assert admin.post(BASE + "/recipients",
                      json={"email": email, "group_key": "md"}).status_code == 409
    assert admin.post(BASE + "/recipients",
                      json={"email": "not-an-address"}).status_code == 422
    rows = admin.get(BASE + "/recipients").json()
    mine = next(r for r in rows if r["email"] == email)
    assert mine["group"] == "md"
    assert "unsubscribe_token" not in mine


def test_schedule_is_validated_before_it_is_saved(client):
    admin = client.as_user("admin")
    assert admin.post(BASE + "/schedules",
                      json=_payload(times=["09:99"])).status_code == 422
    assert admin.post(BASE + "/schedules",
                      json=_payload(pack_key="not-a-pack")).status_code == 422
    assert admin.post(BASE + "/schedules",
                      json=_payload(frequency="monthly", month_rule=None)).status_code == 422
    assert admin.post(BASE + "/schedules",
                      json=_payload(custom_reports=["no_such_report"])).status_code == 422


def test_schedule_lifecycle_and_next_run(client):
    admin = client.as_user("admin")
    name = f"Weekly test {datetime.now().timestamp():.0f}"
    created = admin.post(BASE + "/schedules", json=_payload(name=name, pack_key="weekly",
                                                           frequency="weekly",
                                                           weekdays=[0]))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["next_run_at"] is not None
    assert body["description"].startswith("Weekly on Mon")
    schedule_id = body["id"]

    paused = admin.post(f"{BASE}/schedules/{schedule_id}/enable", json={"enabled": False})
    assert paused.status_code == 200 and paused.json()["next_run_at"] is None

    resumed = admin.post(f"{BASE}/schedules/{schedule_id}/enable", json={"enabled": True})
    assert resumed.json()["next_run_at"] is not None

    copy = admin.post(f"{BASE}/schedules/{schedule_id}/duplicate")
    assert copy.status_code == 201
    assert copy.json()["enabled"] is False
    assert copy.json()["name"].endswith("(copy)")

    assert admin.delete(f"{BASE}/schedules/{copy.json()['id']}").status_code == 200
    assert admin.delete(f"{BASE}/schedules/{schedule_id}").status_code == 200
    assert admin.get(f"{BASE}/schedules/{schedule_id}/preview").status_code == 404


def test_queueing_is_refused_while_sending_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "email_send_enabled", False)
    admin = client.as_user("admin")
    created = admin.post(BASE + "/schedules", json=_payload(
        name=f"Queue guard {uuid4().hex[:8]}"))
    schedule_id = created.json()["id"]
    r = admin.post(f"{BASE}/schedules/{schedule_id}/run-now")
    assert r.status_code == 409 and "disabled" in r.json()["detail"].lower()
    admin.delete(f"{BASE}/schedules/{schedule_id}")


def test_run_now_queues_a_delivery_without_sending(client, monkeypatch):
    _allow_sending(monkeypatch)
    monkeypatch.setattr(settings, "email_test_recipient", "admin@example.test")
    admin = client.as_user("admin")
    created = admin.post(BASE + "/schedules", json=_payload(
        name=f"Run now {uuid4().hex[:8]}"))
    schedule_id = created.json()["id"]
    r = admin.post(f"{BASE}/schedules/{schedule_id}/run-now")
    assert r.status_code == 202, r.text
    with SessionLocal() as db:
        delivery = db.get(EmailDelivery, r.json()["delivery_id"])
        assert delivery.status == "queued"
        assert delivery.trigger == "manual"
        assert delivery.mode == "test"
    admin.delete(f"{BASE}/schedules/{schedule_id}")


def test_send_test_always_redirects_even_in_live_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "live")
    monkeypatch.setattr(settings, "email_send_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_from", "reports@example.test")
    monkeypatch.setattr(settings, "email_test_recipient", "boss@example.test")
    sent = {}
    monkeypatch.setattr(mailer, "send", lambda db, s, r, p: sent.update(people=p) or {
        "size": 1, "to": 1, "cc": 0, "bcc": 0})

    admin = client.as_user("admin")
    address = f"md-{uuid4().hex[:8]}@example.test"
    recipient = admin.post(BASE + "/recipients",
                           json={"email": address, "group_key": "md"}).json()
    created = admin.post(BASE + "/schedules", json=_payload(
        name=f"Test redirect {uuid4().hex[:8]}",
        recipients=[{"recipient_id": recipient["id"], "field": "to"}]))
    schedule_id = created.json()["id"]
    r = admin.post(f"{BASE}/schedules/{schedule_id}/test")
    assert r.status_code == 202, r.text

    with SessionLocal() as db:
        email_worker.process_due(db, datetime.now(UTC))
        delivery = db.get(EmailDelivery, r.json()["delivery_id"])
        assert delivery.status == "sent"
        assert delivery.mode == "test"
    assert sent["people"]["to"] == ["boss@example.test"]
    assert address not in sent["people"]["to"]
    admin.delete(f"{BASE}/schedules/{schedule_id}")
    admin.delete(f"{BASE}/recipients/{recipient['id']}")


def test_preview_renders_and_sends_nothing(client, monkeypatch):
    monkeypatch.setattr(settings, "email_send_enabled", False)
    admin = client.as_user("admin")
    created = admin.post(BASE + "/schedules", json=_payload(
        name=f"Preview {uuid4().hex[:8]}", pack_key="daily"))
    schedule_id = created.json()["id"]
    r = admin.get(f"{BASE}/schedules/{schedule_id}/preview")
    assert r.status_code == 200
    assert "PREVIEW" in r.text and "Nothing was sent" in r.text
    assert "No data yet" in r.text
    with SessionLocal() as db:
        assert not db.scalars(select(EmailDelivery)
                              .where(EmailDelivery.schedule_id == schedule_id)).all()
    admin.delete(f"{BASE}/schedules/{schedule_id}")


def test_delivery_log_is_listed_with_filters(client, monkeypatch):
    admin = client.as_user("admin")
    rows = admin.get(BASE + "/deliveries", params={"limit": 5}).json()
    assert isinstance(rows, list)
    assert admin.get(BASE + "/deliveries", params={"status": "sent", "limit": 5}) \
        .status_code == 200
    assert admin.get(BASE + "/deliveries", params={"limit": 0}).status_code == 422


def test_unsubscribe_only_deactivates_extras_and_needs_the_token(client):
    admin = client.as_user("admin")
    suffix = uuid4().hex[:8]
    extra = admin.post(BASE + "/recipients",
                       json={"email": f"extra-{suffix}@example.test",
                             "group_key": "extra"}).json()
    with SessionLocal() as db:
        token = db.get(EmailRecipient, extra["id"]).unsubscribe_token
    page = client.get(f"{BASE}/unsubscribe/{token}")
    assert page.status_code == 200 and "Stop sending" in page.text
    done = client.post(f"{BASE}/unsubscribe/{token}")
    assert done.status_code == 200 and "will not receive" in done.text
    with SessionLocal() as db:
        assert db.get(EmailRecipient, extra["id"]).active is False
    assert client.get(f"{BASE}/unsubscribe/not-a-token").status_code == 404

    md = admin.post(BASE + "/recipients",
                    json={"email": f"md-{suffix}@example.test", "group_key": "md"}).json()
    with SessionLocal() as db:
        md_token = db.get(EmailRecipient, md["id"]).unsubscribe_token
    refused = client.post(f"{BASE}/unsubscribe/{md_token}")
    assert refused.status_code == 403
    with SessionLocal() as db:
        assert db.get(EmailRecipient, md["id"]).active is True
    admin.delete(f"{BASE}/recipients/{extra['id']}")
    admin.delete(f"{BASE}/recipients/{md['id']}")


def test_every_schedule_change_is_audited(client):
    from app.models.core import AuditLog
    admin = client.as_user("admin")
    created = admin.post(BASE + "/schedules", json=_payload(
        name=f"Audit {uuid4().hex[:8]}"))
    schedule_id = created.json()["id"]
    admin.post(f"{BASE}/schedules/{schedule_id}/enable", json={"enabled": False})
    admin.delete(f"{BASE}/schedules/{schedule_id}")
    with SessionLocal() as db:
        actions = {row.action for row in db.scalars(
            select(AuditLog).where(AuditLog.record == f"schedule:{schedule_id}")).all()}
    assert {"email.schedule.create", "email.schedule.pause",
            "email.schedule.delete"} <= actions
