"""SMTP configuration and the test-email composer (Administrator only).

The screen is the one place SMTP is configured. It never returns the password:
`password_set` says whether one is stored, and an empty password field on save
means "keep the stored one".

A test message is captured unless `deliver` is explicitly true, in which case
one SMTP session is opened with the saved settings. Every attempt is recorded,
so a failure is visible after the fact instead of disappearing into a log.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..core.rbac import require_admin
from ..models.email import EmailTestMessage
from ..services import email_config, mailer
from ..services.audit import audit

router = APIRouter(prefix="/api/email-settings", tags=["email settings"])
admin_only = require_admin("email:manage")

MAX_RECIPIENTS = 10


def _addresses(raw: str | None, field: str) -> list[str]:
    found = email_config.address_list(raw)
    bad = [a for a in found if not email_config.valid_address(a)]
    if bad:
        raise HTTPException(422, f"{field} contains an invalid address: {bad[0]}")
    return found


class SettingsIn(BaseModel):
    enabled: bool = False
    mode: str = "test"
    host: str = ""
    port: int = Field(587, ge=1, le=65535)
    security: str = "starttls"
    username: str = ""
    password: str | None = None
    clear_password: bool = False
    from_address: str = ""
    reply_to: str = ""
    test_to: str = ""
    test_cc: str = ""

    @field_validator("mode")
    @classmethod
    def mode_is_known(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("test", "live"):
            raise ValueError("mode must be test or live")
        return value

    @field_validator("security")
    @classmethod
    def security_is_known(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("none", "starttls", "ssl"):
            raise ValueError("security must be none, starttls or ssl")
        return value


class TestMessageIn(BaseModel):
    message_type: str = "test"
    to: str = ""
    cc: str = ""
    subject: str = Field("", max_length=250)
    body: str = Field("", max_length=20_000)
    deliver: bool = False

    @field_validator("message_type")
    @classmethod
    def type_is_known(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in email_config.MESSAGE_TYPES:
            raise ValueError("unknown message type")
        return value


def _out(row: EmailTestMessage) -> dict:
    return {
        "id": row.id, "message_type": row.message_type,
        "to": row.to_addresses, "cc": row.cc_addresses,
        "subject": row.subject, "status": row.status, "mode": row.mode,
        "size_bytes": row.size_bytes, "error": row.error,
        "created_at": row.created_at, "finished_at": row.finished_at,
    }


@router.get("")
def read_settings(db: Session = Depends(get_db), _=Depends(admin_only)):
    body = email_config.settings_out(db)
    body["suggested_to"] = mailer.test_recipient(db) or ""
    return body


@router.put("")
def write_settings(body: SettingsIn, db: Session = Depends(get_db),
                   actor=Depends(admin_only)):
    if body.mode == "live" and settings.email_mode.strip().lower() != "live":
        raise HTTPException(
            409, "Live sending needs EMAIL_MODE=live in the deployment. "
                 "The settings can still be saved in test mode.")
    for value, field in ((body.from_address, "From address"),
                         (body.reply_to, "Reply-To")):
        if value.strip() and not email_config.valid_address(value):
            raise HTTPException(422, f"{field} is not a valid email address")
    _addresses(body.test_to, "Test To")
    _addresses(body.test_cc, "Test CC")
    if body.password is not None and body.password and body.clear_password:
        raise HTTPException(422, "Choose a new password or clear it, not both")

    values = {
        "enabled": body.enabled, "mode": body.mode,
        "host": body.host.strip(), "port": body.port,
        "security": body.security, "username": body.username.strip(),
        "from_address": body.from_address.strip().lower(),
        "reply_to": body.reply_to.strip().lower(),
        "test_to": ", ".join(_addresses(body.test_to, "Test To")),
        "test_cc": ", ".join(_addresses(body.test_cc, "Test CC")),
        "password": body.password or None,
        "clear_password": body.clear_password,
    }
    email_config.save(db, actor.id, values)
    changed = {k: v for k, v in values.items()
               if k not in ("password", "clear_password")}
    changed["password"] = ("replaced" if body.password else
                           "cleared" if body.clear_password else "unchanged")
    audit(db, actor.id, "email.settings.update", "email_settings:1", changed)
    db.commit()
    out = email_config.settings_out(db)
    out["suggested_to"] = mailer.test_recipient(db) or ""
    return out


@router.get("/test-messages")
def list_test_messages(limit: int = Query(20, ge=1, le=100),
                       db: Session = Depends(get_db), _=Depends(admin_only)):
    rows = db.scalars(select(EmailTestMessage)
                      .order_by(EmailTestMessage.id.desc()).limit(limit)).all()
    return [_out(row) for row in rows]


@router.post("/test")
def send_test(body: TestMessageIn, db: Session = Depends(get_db),
              actor=Depends(admin_only)):
    to = _addresses(body.to, "To")
    cc = _addresses(body.cc, "CC")
    if not to:
        raise HTTPException(422, "Add at least one To address")
    if len(to) + len(cc) > MAX_RECIPIENTS:
        raise HTTPException(422, f"A test message can address at most {MAX_RECIPIENTS} people")

    cfg = email_config.effective(db)
    try:
        msg, text = email_config.build_test_message(
            cfg, message_type=body.message_type, subject=body.subject,
            body=body.body, to=", ".join(to), cc=", ".join(cc))
    except email_config.EmailConfigError as exc:
        raise HTTPException(422, str(exc))

    if body.deliver:
        try:
            size = email_config.deliver(cfg, msg)
        except email_config.EmailConfigError as exc:
            row = email_config.record_test_message(
                db, actor.id, message_type=body.message_type, to=body.to,
                cc=body.cc, subject=str(msg["Subject"]), body=text,
                status="failed", mode="smtp", error=str(exc))
            audit(db, actor.id, "email.test.send", f"email_test:{row.id}", {
                "type": body.message_type, "recipients": len(to) + len(cc),
                "mode": "smtp", "status": "failed"}, notify=False)
            db.commit()
            return _out(row)
        row = email_config.record_test_message(
            db, actor.id, message_type=body.message_type, to=body.to, cc=body.cc,
            subject=str(msg["Subject"]), body=text, status="sent", mode="smtp",
            size=size)
    else:
        row = email_config.record_test_message(
            db, actor.id, message_type=body.message_type, to=body.to, cc=body.cc,
            subject=str(msg["Subject"]), body=text, status="captured",
            mode="dry_run", size=len(msg.as_bytes()))

    audit(db, actor.id, "email.test.send", f"email_test:{row.id}", {
        "type": body.message_type, "recipients": len(to) + len(cc),
        "mode": row.mode, "status": row.status}, notify=False)
    db.commit()
    return _out(row)
