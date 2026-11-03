"""SMTP settings and the test-email composer.

No test reaches a real mail server. Delivery is proved against a throwaway SMTP
sink bound to 127.0.0.1 on an ephemeral port; everything else is a dry run.
"""
import socket
import threading
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.core import AuditLog
from app.models.email import EmailSettings, EmailTestMessage
from app.services import email_config

BASE = "/api/email-settings"


@pytest.fixture(autouse=True)
def clean_email_rows():
    def wipe():
        with SessionLocal() as db:
            db.execute(delete(EmailTestMessage))
            db.execute(delete(EmailSettings))
            db.commit()
    wipe()
    yield
    wipe()


class SmtpSink:
    """A one-connection SMTP server that only records what it was handed."""

    def __init__(self):
        self.messages: list[bytes] = []
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self._sock.accept()
        try:
            stream = conn.makefile("rb")

            def say(text: str):
                conn.sendall(text.encode("ascii"))

            say("220 test-sink ready\r\n")
            buffering = False
            body: list[bytes] = []
            while True:
                line = stream.readline()
                if not line:
                    break
                if buffering:
                    if line in (b".\r\n", b".\n"):
                        self.messages.append(b"".join(body))
                        body = []
                        buffering = False
                        say("250 queued\r\n")
                    else:
                        body.append(line[1:] if line.startswith(b"..") else line)
                    continue
                command = line.strip().upper()
                if command.startswith((b"EHLO", b"HELO")):
                    say("250-test-sink\r\n250 OK\r\n")
                elif command.startswith((b"MAIL", b"RCPT")):
                    say("250 OK\r\n")
                elif command.startswith(b"DATA"):
                    say("354 end with .\r\n")
                    buffering = True
                elif command.startswith(b"QUIT"):
                    say("221 bye\r\n")
                    break
                elif command.startswith(b"RSET"):
                    say("250 OK\r\n")
                else:
                    say("250 OK\r\n")
        finally:
            conn.close()

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


def _payload(**overrides):
    body = {
        "enabled": True, "mode": "test", "host": "127.0.0.1", "port": 2525,
        "security": "none", "username": "", "password": None,
        "clear_password": False, "from_address": "reports@example.test",
        "reply_to": "", "test_to": "admin@example.test", "test_cc": "",
    }
    body.update(overrides)
    return body


def _test_body(**overrides):
    body = {"message_type": "test", "to": "admin@example.test", "cc": "",
            "subject": "", "body": "", "deliver": False}
    body.update(overrides)
    return body


def test_only_administrators_reach_the_settings(client):
    for path in ("", "/test-messages"):
        assert client.as_user("sales").get(BASE + path).status_code == 403
        assert client.as_user("viewer").get(BASE + path).status_code == 403
    assert client.as_user("sales").put(BASE, json=_payload()).status_code == 403
    assert client.as_user("sales").post(BASE + "/test",
                                        json=_test_body()).status_code == 403


def test_settings_never_return_the_password(client):
    admin = client.as_user("admin")
    secret = f"TopSecret-{uuid4().hex[:8]}"
    saved = admin.put(BASE, json=_payload(password=secret))
    assert saved.status_code == 200, saved.text
    assert saved.json()["password_set"] is True
    assert secret not in saved.text

    read = admin.get(BASE)
    assert read.status_code == 200
    assert read.json()["password_set"] is True
    assert secret not in read.text
    assert "password_enc" not in read.text

    with SessionLocal() as db:
        row = db.get(EmailSettings, 1)
        assert row is not None and row.password_enc
        assert secret not in row.password_enc
        plain, readable = email_config.unseal(row.password_enc)
        assert readable and plain == secret
        log = db.scalar(select(AuditLog)
                        .where(AuditLog.action == "email.settings.update")
                        .order_by(AuditLog.id.desc()))
        assert log is not None
        assert secret not in str(log.changes)


def test_empty_password_keeps_the_stored_one_and_clear_removes_it(client):
    admin = client.as_user("admin")
    admin.put(BASE, json=_payload(password="FirstSecret!9")).raise_for_status()
    admin.put(BASE, json=_payload(host="smtp.example.test", password="")).raise_for_status()
    with SessionLocal() as db:
        row = db.get(EmailSettings, 1)
        assert email_config.unseal(row.password_enc)[0] == "FirstSecret!9"
        assert row.host == "smtp.example.test"
    cleared = admin.put(BASE, json=_payload(clear_password=True))
    assert cleared.json()["password_set"] is False
    with SessionLocal() as db:
        assert db.get(EmailSettings, 1).password_enc is None


def test_validation_and_live_mode_gate(client, monkeypatch):
    monkeypatch.setattr(settings, "email_mode", "test")
    admin = client.as_user("admin")
    assert admin.put(BASE, json=_payload(from_address="not-an-address")).status_code == 422
    assert admin.put(BASE, json=_payload(test_to="bad address")).status_code == 422
    assert admin.put(BASE, json=_payload(port=70000)).status_code == 422
    assert admin.put(BASE, json=_payload(security="tls-ish")).status_code == 422
    live = admin.put(BASE, json=_payload(mode="live"))
    assert live.status_code == 409 and "EMAIL_MODE=live" in live.json()["detail"]


def test_dry_run_is_stored_and_opens_no_socket(client):
    admin = client.as_user("admin")
    admin.put(BASE, json=_payload(host="unreachable.invalid", port=1)).raise_for_status()
    sent = admin.post(BASE + "/test", json=_test_body(message_type="hr_notice"))
    assert sent.status_code == 200, sent.text
    made = sent.json()
    assert made["status"] == "captured" and made["mode"] == "dry_run"
    assert made["subject"].startswith("[TEST]")
    assert "HR announcement" in made["subject"]

    listed = admin.get(BASE + "/test-messages")
    assert listed.status_code == 200
    rows = listed.json()
    assert rows and rows[0]["id"] == made["id"]
    with SessionLocal() as db:
        row = db.get(EmailTestMessage, made["id"])
        assert row is not None and row.status == "captured"
        assert "No action is required" in row.body


def test_message_content_and_recipients_are_validated(client):
    admin = client.as_user("admin")
    admin.put(BASE, json=_payload()).raise_for_status()
    assert admin.post(BASE + "/test", json=_test_body(to="")).status_code == 422
    assert admin.post(BASE + "/test", json=_test_body(cc="oops")).status_code == 422
    assert admin.post(BASE + "/test",
                      json=_test_body(message_type="not-a-type")).status_code == 422
    too_many = ", ".join(f"p{i}@example.test" for i in range(11))
    assert admin.post(BASE + "/test",
                      json=_test_body(to=too_many)).status_code == 422


def test_a_test_message_travels_through_smtp_to_a_local_sink(client):
    sink = SmtpSink()
    try:
        admin = client.as_user("admin")
        saved = admin.put(BASE, json=_payload(port=sink.port, test_cc="cc@example.test",
                                              from_address="reports@example.test"))
        assert saved.status_code == 200, saved.text
        sent = admin.post(BASE + "/test", json=_test_body(
            to="first@example.test", cc="cc@example.test", subject="Hello",
            body="Line one\nLine two", deliver=True))
        assert sent.status_code == 200, sent.text
        made = sent.json()
        assert made["status"] == "sent", made
        assert made["mode"] == "smtp" and made["size_bytes"] > 0
        assert made["subject"] == "[TEST] Hello"
    finally:
        sink.close()
    assert len(sink.messages) == 1
    wire = sink.messages[0].decode("utf-8", "replace")
    assert "To: first@example.test" in wire
    assert "Cc: cc@example.test" in wire
    assert "Subject: [TEST] Hello" in wire
    assert "Line two" in wire


def test_a_refused_connection_is_recorded_as_failed(client):
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()
    admin = client.as_user("admin")
    admin.put(BASE, json=_payload(port=port)).raise_for_status()
    sent = admin.post(BASE + "/test", json=_test_body(deliver=True))
    assert sent.status_code == 200, sent.text
    made = sent.json()
    assert made["status"] == "failed" and made["mode"] == "smtp"
    assert made["error"]


def test_saved_settings_drive_the_scheduler_recipient(client):
    admin = client.as_user("admin")
    admin.put(BASE, json=_payload(enabled=True,
                                  test_to="ops@example.test")).raise_for_status()
    with SessionLocal() as db:
        from app.services import mailer
        assert mailer.test_recipient(db) == "ops@example.test"
        assert mailer.smtp_ready(db) is True
        assert email_config.effective(db).enabled is True


def test_well_known_smtp_ports_decide_the_transport(client):
    """465 means implicit TLS and 587 means STARTTLS, whatever was selected.

    A saved account that contradicts the port cannot authenticate; the port
    wins so a correct password is not rejected by the wrong handshake.
    """
    admin = client.as_user("admin")
    for port, saved, used in ((465, "starttls", "ssl"), (587, "ssl", "starttls"),
                              (2525, "none", "none")):
        admin.put(BASE, json=_payload(port=port, security=saved)).raise_for_status()
        with SessionLocal() as db:
            assert email_config.effective(db).security == used, (port, saved)


def test_an_unreadable_settings_row_rolls_the_session_back():
    """A failed read must not poison the worker's session."""
    from sqlalchemy.exc import OperationalError

    class Broken:
        rolled_back = False

        def get(self, *args):
            raise OperationalError("SELECT 1", {}, Exception("database is down"))

        def rollback(self):
            self.rolled_back = True

    db = Broken()
    assert email_config.load_row(db) is None
    assert db.rolled_back is True


def test_switching_scheduled_off_closes_the_settings_api(client):
    admin = client.as_user("admin")
    try:
        assert admin.patch("/api/features/scheduled",
                           json={"enabled": False}).status_code == 200
        assert admin.get(BASE).status_code == 403
    finally:
        assert admin.patch("/api/features/scheduled",
                           json={"enabled": True}).status_code == 200
    assert admin.get(BASE).status_code == 200
