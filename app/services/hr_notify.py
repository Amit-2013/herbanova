"""HR notifications and announcements.

A notification is always written as a row: the bell in the application is the
source of truth. Email is a second channel and is always a test-mode email
(mailer.send_note with force_test=True), so nothing reaches an employee's real
address until the Administrator approves a recipient list.

Delivery is best effort. A failure is returned, never raised, because the HR
action that produced the note has already been committed and must not be undone
by an SMTP problem.
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.core import User
from ..models.hr import EmployeeDocument, HRNotification
from ..models.users import Employee, Role
from . import mailer

MAX_TITLE = 160
MAX_BODY = 500
MAX_LINK = 200
IST = timezone(timedelta(hours=5, minutes=30))


def notify(db: Session, user_ids, kind: str, title: str, body: str,
           link: str | None = None) -> list[HRNotification]:
    """Queue one in-app notification per user. The caller commits."""
    rows = []
    seen: set[int] = set()
    for user_id in user_ids:
        if not user_id or user_id in seen:
            continue
        seen.add(int(user_id))
        note = HRNotification(user_id=int(user_id), kind=(kind or "hr")[:30],
                              title=title[:MAX_TITLE], body=body[:MAX_BODY],
                              link=(link[:MAX_LINK] if link else None))
        db.add(note)
        rows.append(note)
    return rows


def _role_users(db: Session, role_name: str) -> list[User]:
    return db.scalars(select(User).join(Role, Role.id == User.role_id).where(
        User.is_active.is_(True), Role.name == role_name)).all()


def notify_request(db: Session, request, employee_id: int | None = None) -> list[HRNotification]:
    """Tell the people who can decide a request.

    A reporting-manager request goes to the employee's own manager, not to
    every manager: a leave reason must not reach an unrelated team. When no
    manager is linked, the role that owns the queue is notified instead.
    """
    role = request.pending_approver_role
    targets: set[int] = set()
    if role == "reporting_manager" and employee_id:
        emp = db.get(Employee, int(employee_id))
        if emp and emp.manager_id:
            manager = db.scalar(select(User).where(User.employee_id == emp.manager_id,
                                                   User.is_active.is_(True)))
            if manager:
                targets.add(manager.id)
    if not targets and role:
        targets = {u.id for u in _role_users(db, role)}
    title = f"Approval needed: {request.subject or request.record_type.replace('_', ' ')}"
    body = (f"{request.subject or 'A request'} is waiting for a decision. "
            f"Request {request.request_no}.")
    return notify(db, targets, "approval_request", title, body, "/ui#approvals")


def notify_decision(db: Session, request, approved: bool, reason: str = "") -> list[HRNotification]:
    title = "Your request was approved" if approved else "Your request was rejected"
    body = (f"{request.subject or request.record_type.replace('_', ' ')}: "
            f"{'approved' if approved else 'rejected'}.")
    if reason:
        body = f"{body} Reason: {reason}"
    return notify(db, [request.requested_by], "approval_decision", title, body, "/ui#hr")


def address_for(db: Session, user_id: int) -> str | None:
    user = db.get(User, user_id)
    if not user or not user.employee_id:
        return None
    emp = db.get(Employee, user.employee_id)
    return emp.email if emp and mailer.valid_address(emp.email) else None


def email_note(db: Session, note: HRNotification, address: str | None = None,
               subject: str | None = None) -> dict:
    """Send one notification by email in test mode. Never raises."""
    try:
        result = mailer.send_note(db, [address] if address else [],
                                  subject or f"Herbanova HR: {note.title}", note.body,
                                  force_test=True)
        return {"sent": True, **result}
    except mailer.MailError as exc:
        return {"sent": False, "reason": str(exc)}


def email_configured() -> bool:
    return bool(settings.email_send_enabled) and mailer.smtp_ready()


def _next_occurrence(day: date, today: date) -> date:
    try:
        candidate = day.replace(year=today.year)
    except ValueError:                       # 29 February in a common year
        candidate = date(today.year, 3, 1)
    return candidate if candidate >= today else candidate.replace(year=today.year + 1)


def digest_rows(db: Session, today: date) -> dict:
    """What the daily digest would say. The dashboard uses the same rules."""
    active = db.scalars(select(Employee).where(Employee.status == "active")).all()
    birthdays, anniversaries = [], []
    for emp in active:
        if emp.date_of_birth:
            nxt = _next_occurrence(emp.date_of_birth, today)
            if (nxt - today).days == 0:
                birthdays.append({"employee_id": emp.id, "code": emp.code,
                                  "full_name": emp.full_name,
                                  "turning": nxt.year - emp.date_of_birth.year})
        if emp.joining_date:
            nxt = _next_occurrence(emp.joining_date, today)
            years = nxt.year - emp.joining_date.year
            if years >= 1 and (nxt - today).days == 0:
                anniversaries.append({"employee_id": emp.id, "code": emp.code,
                                      "full_name": emp.full_name, "years": years})
    expiring = db.scalars(select(EmployeeDocument).where(
        EmployeeDocument.status == "active",
        EmployeeDocument.expires_on.is_not(None),
        EmployeeDocument.expires_on >= today,
        EmployeeDocument.expires_on <= today + timedelta(days=30))).all()
    probation = [{"employee_id": emp.id, "code": emp.code, "full_name": emp.full_name,
                  "date": emp.probation_end_date.isoformat()}
                 for emp in active if emp.probation_end_date
                 and today <= emp.probation_end_date <= today + timedelta(days=30)]
    return {"birthdays": birthdays, "anniversaries": anniversaries,
            "documents": [{"document_id": d.id, "employee_id": d.employee_id,
                           "title": d.title, "expires_on": d.expires_on.isoformat()}
                          for d in expiring],
            "probation": probation}


def _already_notified(db: Session, user_id: int, kind: str, link: str,
                      since: datetime) -> bool:
    return db.scalar(select(HRNotification.id).where(
        HRNotification.user_id == user_id, HRNotification.kind == kind,
        HRNotification.link == link, HRNotification.created_at >= since)) is not None


def _dedupe_since(today: date) -> datetime:
    """Start of the digest day in business time.

    `today` is an IST date. Using UTC midnight here would start the window 5½
    hours in the future between 00:00 and 05:30 IST, so a second run on the same
    day would queue a duplicate.
    """
    return datetime.combine(today, time.min, tzinfo=IST)


def run_digest(db: Session, today: date | None = None) -> dict:
    """Queue the daily HR digest for the Administrator and HR managers.

    Running it twice on the same day does not create a second copy. The caller
    commits; email is sent by the caller after the commit.
    """
    today = today or datetime.now(IST).date()
    rows = digest_rows(db, today)
    counts = {key: len(value) for key, value in rows.items()}
    if not any(counts.values()):
        return {"queued": 0, "counts": counts, "skipped": True, "rows": rows, "notes": []}
    since = _dedupe_since(today)
    people = ({u.id for u in _role_users(db, "hr_manager")}
              | {u.id for u in _role_users(db, "admin")})
    title = "HR digest for " + today.strftime("%d %B %Y")
    parts = []
    if rows["birthdays"]:
        parts.append("Birthdays: " + ", ".join(b["full_name"] for b in rows["birthdays"]))
    if rows["anniversaries"]:
        parts.append("Work anniversaries: "
                     + ", ".join(a["full_name"] for a in rows["anniversaries"]))
    if rows["documents"]:
        parts.append(f"Documents expiring within 30 days: {len(rows['documents'])}")
    if rows["probation"]:
        parts.append(f"Probation ending within 30 days: {len(rows['probation'])}")
    body = ". ".join(parts)
    notes = []
    for user_id in sorted(people):
        if _already_notified(db, user_id, "hr_digest", "/ui#hr", since):
            continue
        notes.extend(notify(db, [user_id], "hr_digest", title, body, "/ui#hr"))
    return {"queued": len(notes), "counts": counts, "skipped": not notes,
            "rows": rows, "notes": notes}
