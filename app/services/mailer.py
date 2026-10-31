"""SMTP delivery and recipient resolution.

Two switches guard a real send: `EMAIL_MODE=live` and `EMAIL_SEND_ENABLED=true`.
The default is test mode, which sends the whole message to one Administrator
address and prefixes the subject with [TEST]. If that address is unknown the
send fails closed; it never falls back to the real recipients.

SMTP credentials are read from the environment (`SMTP_*`) and are never logged,
returned by the API or written to the delivery log. TLS is used when configured.
"""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.core import User
from ..models.email import EmailRecipient
from ..models.users import Employee, Role

ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailError(RuntimeError):
    pass


def valid_address(address: str | None) -> bool:
    return bool(address and ADDRESS_RE.match(address.strip()))


def live_mode() -> bool:
    return settings.email_mode.strip().lower() == "live"


def smtp_ready() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def administrator_emails(db: Session) -> list[str]:
    rows = db.execute(
        select(Employee.email)
        .join(User, User.employee_id == Employee.id)
        .join(Role, Role.id == User.role_id)
        .where(User.is_active.is_(True), Role.name == "admin",
               Employee.email.is_not(None))).scalars().all()
    return sorted({e.strip().lower() for e in rows if valid_address(e)})


def test_recipient(db: Session) -> str | None:
    if valid_address(settings.email_test_recipient):
        return settings.email_test_recipient.strip().lower()
    admins = administrator_emails(db)
    return admins[0] if admins else None


def _schedule_people(db: Session, schedule) -> dict[str, list[str]]:
    people = {"to": [], "cc": [], "bcc": []}
    seen: set[str] = set()
    for link in schedule.recipients:
        person = link.recipient
        if not person or not person.active:
            continue
        address = person.email.strip().lower()
        if not valid_address(address) or address in seen:
            continue
        seen.add(address)
        people.setdefault(link.field, []).append(address)
    groups = set(schedule.groups or [])
    if groups:
        for person in db.scalars(select(EmailRecipient)
                                 .where(EmailRecipient.group_key.in_(groups),
                                        EmailRecipient.active.is_(True))).all():
            address = person.email.strip().lower()
            if valid_address(address) and address not in seen:
                seen.add(address)
                people["to"].append(address)
    return people


def resolve(db: Session, schedule) -> dict:
    """The real recipients, and (in test mode) the single address used instead."""
    people = _schedule_people(db, schedule)
    real_count = sum(len(v) for v in people.values())
    if not live_mode() or not settings.email_send_enabled:
        address = test_recipient(db)
        if not address:
            raise MailError(
                "Test mode: no Administrator email is configured. Add EMAIL_TEST_RECIPIENT "
                "or give an active Administrator an employee email; nothing was sent.")
        return {"to": [address], "cc": [], "bcc": [], "real_count": real_count,
                "redirected": True, "test_address": address}
    if real_count == 0:
        raise MailError("This schedule has no active recipients; nothing was sent.")
    for field, addresses in people.items():
        bad = [a for a in addresses if not valid_address(a)]
        if bad:
            raise MailError(f"Invalid {field.upper()} address: {bad[0]}")
    return {**people, "real_count": real_count, "redirected": False, "test_address": None}


def _message(rendered: dict, people: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = rendered["subject"]
    msg["From"] = settings.smtp_from
    if settings.smtp_reply_to:
        msg["Reply-To"] = settings.smtp_reply_to
    msg["To"] = ", ".join(people["to"])
    if people.get("cc"):
        msg["Cc"] = ", ".join(people["cc"])
    if people.get("bcc"):
        msg["Bcc"] = ", ".join(people["bcc"])
    msg["Date"] = formatdate(localtime=False)
    msg.set_content(rendered["text"])
    msg.add_alternative(rendered["html"], subtype="html")
    html_part = msg.get_payload()[1]
    for cid, payload in rendered.get("images", {}).items():
        html_part.add_related(payload, maintype="image", subtype="png", cid=f"<{cid}>")
    for attachment in rendered.get("attachments", []):
        maintype, _, subtype = attachment["content_type"].partition("/")
        msg.add_attachment(attachment["bytes"], maintype=maintype, subtype=subtype,
                           filename=attachment["filename"])
    return msg


def send(db: Session, schedule, rendered: dict, people: dict) -> dict:
    """Send one message. Raises MailError; never prints or logs a secret."""
    if not settings.email_send_enabled:
        raise MailError("Sending is disabled (EMAIL_SEND_ENABLED is false).")
    if not smtp_ready():
        raise MailError("SMTP is not configured (SMTP_HOST and SMTP_FROM are required).")
    msg = _message(rendered, people)
    size = len(msg.as_bytes())
    context = ssl.create_default_context()
    try:
        if settings.smtp_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                      timeout=30, context=context)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        with server:
            server.ehlo()
            if settings.smtp_starttls and not settings.smtp_ssl:
                server.starttls(context=context)
                server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        # The exception text can echo the server banner, which may contain the
        # host but never the password; keep the message short and factual.
        raise MailError(f"SMTP delivery failed: {type(exc).__name__}: {exc}") from exc
    return {"size": size, "to": len(people["to"]), "cc": len(people.get("cc") or []),
            "bcc": len(people.get("bcc") or [])}
