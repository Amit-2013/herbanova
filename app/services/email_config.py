"""SMTP configuration stored on the settings screen, plus the test composer.

Two layers decide what a send looks like:

* the environment (`SMTP_*`, `EMAIL_*`) is the deployment default;
* the single `email_settings` row is what the Administrator saved.

A saved value wins over the environment; an empty saved value falls through, so
a deployment that never opens the screen behaves exactly as before. The password
is sealed with a key derived from `APP_SECRET`. It is never returned by the API,
never written to the audit trail and never logged.

Test messages are always test messages: the subject gains a `[TEST]` prefix,
and nothing here can address a scheduled recipient list. A dry run renders and
stores the message without opening a socket; only an explicit `deliver` flag
reaches SMTP.
"""
from __future__ import annotations

import base64
import hashlib
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from html import escape

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.email import EmailSettings, EmailTestMessage

ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MESSAGE_TYPES: dict[str, dict] = {
    "test": {
        "label": "SMTP test",
        "subject": "Herbanova SMTP test",
        "body": ("This is a test message from Herbanova. If you can read it, the "
                 "SMTP settings are correct."),
    },
    "hr_notice": {
        "label": "HR announcement",
        "subject": "HR announcement",
        "body": ("Dear team,\n\nThis is a test copy of an HR announcement. "
                 "No action is required.\n\nHuman Resources"),
    },
    "report_notice": {
        "label": "Scheduled report notice",
        "subject": "Scheduled report ready",
        "body": ("Hello,\n\nThe scheduled report is ready. This is a test copy; "
                 "no report is attached.\n\nHerbanova accounts"),
    },
    "custom": {
        "label": "Custom message",
        "subject": "",
        "body": "",
    },
}


class EmailConfigError(RuntimeError):
    pass


def valid_address(address: str | None) -> bool:
    return bool(address and ADDRESS_RE.match(address.strip()))


def address_list(raw: str | None) -> list[str]:
    return [part.strip().lower() for part in re.split(r"[,;]", raw or "")
            if part.strip()]


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"herbanova:email:{settings.app_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(password: str) -> str:
    return _fernet().encrypt(password.encode("utf-8")).decode("ascii")


def unseal(token: str | None) -> tuple[str, bool]:
    """(password, readable). An unreadable token means APP_SECRET changed."""
    if not token:
        return "", True
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8"), True
    except (InvalidToken, ValueError):
        return "", False


@dataclass(frozen=True)
class Effective:
    stored: bool
    enabled: bool
    mode: str
    live_allowed: bool
    host: str
    port: int
    security: str
    username: str
    password: str
    password_saved: bool
    password_unreadable: bool
    from_address: str
    reply_to: str
    test_to: str
    test_cc: str

    @property
    def smtp_ready(self) -> bool:
        return bool(self.host and self.from_address and self.port)


def load_row(db: Session | None) -> EmailSettings | None:
    if db is None:
        return None
    try:
        return db.get(EmailSettings, 1)
    except SQLAlchemyError:
        # A failed read leaves the session unusable until it is rolled back;
        # without this every later statement on the worker's session raised
        # PendingRollbackError and the delivery could not be recorded.
        db.rollback()
        return None


def _transport(port: int, security: str) -> str:
    """The transport the port actually speaks.

    465 is implicit TLS and 587 is STARTTLS. A saved choice that contradicts a
    well-known port is the usual reason a correct password still cannot sign
    in, so the port wins; the settings screen reports the transport in use.
    """
    if port == 465:
        return "ssl"
    if port == 587:
        return "starttls"
    return security


def effective(db: Session | None = None) -> Effective:
    row = load_row(db)
    env_security = ("ssl" if settings.smtp_ssl
                    else "starttls" if settings.smtp_starttls else "none")
    env_mode = settings.email_mode.strip().lower()
    live_allowed = env_mode == "live"

    def pick(name: str, env_value, treat_zero: bool = False):
        saved = getattr(row, name) if row is not None else None
        if saved is None or saved == "" or (treat_zero and saved == 0):
            return env_value
        return saved

    password, readable = unseal(row.password_enc if row is not None else None)
    if row is None or not row.password_enc:
        password = settings.smtp_password
        readable = True

    stored_mode = pick("mode", env_mode)
    port = int(pick("port", settings.smtp_port, treat_zero=True))
    return Effective(
        stored=row is not None,
        enabled=row.enabled if row is not None else settings.email_send_enabled,
        mode="live" if stored_mode == "live" and live_allowed else "test",
        live_allowed=live_allowed,
        host=pick("host", settings.smtp_host),
        port=port,
        security=_transport(port, pick("security", env_security)),
        username=pick("username", settings.smtp_user),
        password=password,
        password_saved=bool(row is not None and row.password_enc),
        password_unreadable=not readable,
        from_address=pick("from_address", settings.smtp_from),
        reply_to=pick("reply_to", settings.smtp_reply_to),
        test_to=pick("test_to", settings.email_test_recipient),
        test_cc=pick("test_cc", ""),
    )


def settings_out(db: Session) -> dict:
    """Everything the screen shows. The password is reduced to a yes/no."""
    cfg = effective(db)
    row = load_row(db)
    return {
        "stored": cfg.stored,
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "requested_mode": row.mode if row is not None else settings.email_mode,
        "live_allowed": cfg.live_allowed,
        "host": cfg.host,
        "port": cfg.port,
        "security": cfg.security,
        "username": cfg.username,
        "password_set": bool(cfg.password),
        "password_saved": cfg.password_saved,
        "password_unreadable": cfg.password_unreadable,
        "from_address": cfg.from_address,
        "reply_to": cfg.reply_to,
        "test_to": cfg.test_to,
        "test_cc": cfg.test_cc,
        "smtp_ready": cfg.smtp_ready,
        "message_types": [
            {"key": key, "label": meta["label"], "subject": meta["subject"],
             "body": meta["body"]}
            for key, meta in MESSAGE_TYPES.items()],
    }


def save(db: Session, actor_id: int | None, values: dict) -> EmailSettings:
    row = load_row(db)
    if row is None:
        row = EmailSettings(id=1)
        db.add(row)
    for name in ("enabled", "mode", "host", "port", "security", "username",
                 "from_address", "reply_to", "test_to", "test_cc"):
        if name in values:
            setattr(row, name, values[name])
    if values.get("clear_password"):
        row.password_enc = None
    elif values.get("password"):
        row.password_enc = seal(values["password"])
    row.updated_by = actor_id
    db.flush()
    return row


def build_test_message(cfg: Effective, *, message_type: str, subject: str,
                       body: str, to: str, cc: str) -> tuple[EmailMessage, str]:
    meta = MESSAGE_TYPES[message_type]
    subject = (subject or meta["subject"]).strip()
    if not subject:
        raise EmailConfigError("Add a subject before sending.")
    if not subject.upper().startswith("[TEST]"):
        subject = f"[TEST] {subject}"
    body = (body if body and body.strip() else meta["body"]).strip()
    if not body:
        raise EmailConfigError("Add a message body before sending.")
    if not cfg.from_address:
        raise EmailConfigError("A From address is required.")
    msg = EmailMessage()
    msg["Subject"] = subject[:250]
    msg["From"] = cfg.from_address
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
    msg["To"] = ", ".join(address_list(to))
    if address_list(cc):
        msg["Cc"] = ", ".join(address_list(cc))
    msg["Date"] = formatdate(localtime=False)
    msg.set_content(body)
    msg.add_alternative(escape(body).replace("\n", "<br>"), subtype="html")
    return msg, body


def deliver(cfg: Effective, msg: EmailMessage) -> int:
    """Open one SMTP session and send `msg`. Raises EmailConfigError."""
    if not cfg.enabled:
        raise EmailConfigError("Sending is switched off on the settings screen.")
    if not cfg.smtp_ready:
        raise EmailConfigError("SMTP is not configured (host and From address are required).")
    size = len(msg.as_bytes())
    context = ssl.create_default_context()
    try:
        if cfg.security == "ssl":
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=30)
        with server:
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if cfg.username:
                server.login(cfg.username, cfg.password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailConfigError(f"SMTP delivery failed: {type(exc).__name__}: {exc}") from exc
    return size


def record_test_message(db: Session, actor_id: int | None, *, message_type: str,
                        to: str, cc: str, subject: str, body: str, status: str,
                        mode: str, size: int = 0, error: str | None = None) -> EmailTestMessage:
    row = EmailTestMessage(
        message_type=message_type, to_addresses=", ".join(address_list(to)),
        cc_addresses=", ".join(address_list(cc)), subject=subject[:250], body=body,
        status=status, mode=mode, size_bytes=size, error=error, created_by=actor_id,
        finished_at=datetime.now(timezone.utc))
    db.add(row)
    db.flush()
    return row
