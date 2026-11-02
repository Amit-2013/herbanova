"""SMTP delivery and recipient resolution.

Two switches guard a real send: `EMAIL_MODE=live` and `EMAIL_SEND_ENABLED=true`.
The default is test mode, which sends the whole message to one Administrator
address and prefixes the subject with [TEST]. If that address is unknown the
send fails closed; it never falls back to the real recipients.

SMTP credentials are read from the environment (`SMTP_*`) and are never logged,
returned by the API or written to the delivery log. TLS is used when configured.
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core import User
from ..models.email import EmailRecipient
from ..models.users import Employee, Role
from . import email_config


class MailError(RuntimeError):
    pass


valid_address = email_config.valid_address


def live_mode(db: Session | None = None) -> bool:
    """Live delivery needs both the deployment gate and the saved setting."""
    return email_config.effective(db).mode == "live"


def smtp_ready(db: Session | None = None) -> bool:
    return email_config.effective(db).smtp_ready


def administrator_emails(db: Session) -> list[str]:
    rows = db.execute(
        select(Employee.email)
        .join(User, User.employee_id == Employee.id)
        .join(Role, Role.id == User.role_id)
        .where(User.is_active.is_(True), Role.name == "admin",
               Employee.email.is_not(None))).scalars().all()
    return sorted({e.strip().lower() for e in rows if valid_address(e)})


def test_recipient(db: Session) -> str | None:
    configured = email_config.effective(db).test_to
    if valid_address(configured):
        return configured.strip().lower()
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


def resolve(db: Session, schedule, *, force_test: bool = False,
            test_address: str | None = None) -> dict:
    """The real recipients, and (in test mode) the single address used instead.

    `force_test` is used by the "Send test to me" action: even a live session
    must not mail the real list for a test.
    """
    people = _schedule_people(db, schedule)
    real_count = sum(len(v) for v in people.values())
    cfg = email_config.effective(db)
    if force_test or not live_mode(db) or not cfg.enabled:
        address = test_address if valid_address(test_address) else test_recipient(db)
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


def _message(rendered: dict, people: dict, cfg) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = rendered["subject"]
    msg["From"] = cfg.from_address
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
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
    cfg = email_config.effective(db)
    if not cfg.enabled:
        raise MailError("Sending is disabled (EMAIL_SEND_ENABLED is false).")
    if not cfg.smtp_ready:
        raise MailError("SMTP is not configured (SMTP_HOST and SMTP_FROM are required).")
    msg = _message(rendered, people, cfg)
    try:
        size = email_config.deliver(cfg, msg)
    except email_config.EmailConfigError as exc:
        # The exception text can echo the server banner, which may contain the
        # host but never the password; keep the message short and factual.
        raise MailError(str(exc)) from exc
    return {"size": size, "to": len(people["to"]), "cc": len(people.get("cc") or []),
            "bcc": len(people.get("bcc") or [])}


def send_note(db: Session, addresses: list[str], subject: str, text: str,
              html: str | None = None, *, force_test: bool = True) -> dict:
    """One short plain message, through the same switches as a scheduled pack.

    `force_test` defaults to True: HR notifications have no approved live
    recipient list, so they always land at the single test address with a
    [TEST] subject. Callers pass False only for a pack whose recipients the
    Administrator has configured.
    """
    cfg = email_config.effective(db)
    if not cfg.enabled:
        raise MailError("Sending is disabled (EMAIL_SEND_ENABLED is false).")
    if not cfg.smtp_ready:
        raise MailError("SMTP is not configured (SMTP_HOST and SMTP_FROM are required).")
    if force_test or not live_mode(db):
        address = test_recipient(db)
        if not address:
            raise MailError("Test mode: no Administrator email is configured. "
                            "Nothing was sent.")
        people = {"to": [address], "cc": [], "bcc": []}
        subject = f"[TEST] {subject}"
        redirected = True
    else:
        people = {"to": [a.strip().lower() for a in addresses if valid_address(a)],
                  "cc": [], "bcc": []}
        if not people["to"]:
            raise MailError("No valid recipient address; nothing was sent.")
        redirected = False
    safe = escape(text)
    rendered = {"subject": subject, "text": text,
                "html": html or f"<p>{safe.replace(chr(10), '<br>')}</p>"}
    result = send(db, None, rendered, people)
    return {**result, "redirected": redirected}
