"""Scheduled report screens and the recipient list (Administrator only).

Every route here is guarded by `require_admin("email:manage")`, so a custom role
granted the key still cannot manage schedules: the requirement is that the
scheduler screen belongs to the Administrator. The one exception is the
unsubscribe page, which is addressed by an unguessable token and only ever
deactivates an `extra` recipient.

Nothing on this router sends a real email except by queueing a delivery row; the
worker sends it. Preview builds the message in the browser and sends nothing.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..core.rbac import require_admin
from ..models.email import (GROUPS, EmailDelivery, EmailRecipient, EmailSchedule,
                            EmailScheduleRecipient)
from ..services import email_config, email_worker, mailer, report_packs, reports
from ..services import schedule as schedule_service
from ..services.audit import audit
from ..services.email_render import render

router = APIRouter(prefix="/api/email-reports", tags=["scheduled reports"])
public_router = APIRouter(prefix="/api/email-reports", tags=["scheduled reports"])

admin_only = require_admin("email:manage")


class RecipientIn(BaseModel):
    email: str
    name: str | None = None
    group_key: str = "extra"

    @field_validator("email")
    @classmethod
    def norm_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("group_key")
    @classmethod
    def norm_group(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in GROUPS:
            raise ValueError("group must be md, admin or extra")
        return value


class RecipientUpdate(BaseModel):
    name: str | None = None
    group_key: str | None = None
    active: bool | None = None


class PersonLink(BaseModel):
    recipient_id: int
    field: str = "to"

    @field_validator("field")
    @classmethod
    def norm_field(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("to", "cc", "bcc"):
            raise ValueError("field must be to, cc or bcc")
        return value


class ScheduleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    pack_key: str
    enabled: bool = True
    frequency: str = "weekdays"
    timezone: str = "Asia/Kolkata"
    weekdays: list[int] = []
    times: list[str] = ["09:00"]
    month_day: int | None = None
    month_rule: str | None = None
    custom_cron: str | None = None
    holiday_rule: str = "shift"
    include_attachments: bool = True
    include_accounts: bool = True
    custom_reports: list[str] = []
    groups: list[str] = []
    recipients: list[PersonLink] = []


class ScheduleUpdate(ScheduleIn):
    name: str = Field(min_length=2, max_length=120)


class EnableIn(BaseModel):
    enabled: bool


# --- configuration ---------------------------------------------------------

@router.get("/status")
def status(db: Session = Depends(get_db), _=Depends(admin_only)):
    """What the screen needs to explain the guardrails, with no secrets."""
    return {
        "mode": "live" if mailer.live_mode(db) else "test",
        "send_enabled": email_config.effective(db).enabled,
        "smtp_ready": mailer.smtp_ready(db),
        "test_recipient": settings.email_test_recipient or None,
        "worker_interval": settings.email_worker_interval,
        "max_bytes": settings.email_max_bytes,
        "packs": [{"key": key, "label": meta["label"],
                   "period": meta["period"], "hint": meta["frequency_hint"],
                   "accounts": meta["accounts"]}
                  for key, meta in report_packs.PACKS.items()],
        "report_catalog": [{"key": key, "title": meta[0], "permission": meta[3]}
                           for key, meta in reports.CATALOG.items()],
    }


@router.get("/recipients")
def list_recipients(db: Session = Depends(get_db), _=Depends(admin_only)):
    used = {link.recipient_id for link in
            db.scalars(select(EmailScheduleRecipient)).all()}
    return [{"id": r.id, "email": r.email, "name": r.name, "group": r.group_key,
             "active": r.active, "in_use": r.id in used,
             "created_at": r.created_at}
            for r in db.scalars(select(EmailRecipient)
                                .order_by(EmailRecipient.group_key,
                                          EmailRecipient.email)).all()]


@router.post("/recipients", status_code=201)
def create_recipient(body: RecipientIn, db: Session = Depends(get_db),
                     actor=Depends(admin_only)):
    if not mailer.valid_address(body.email):
        raise HTTPException(422, "That is not a valid email address")
    person = EmailRecipient(email=body.email, name=(body.name or "").strip() or None,
                            group_key=body.group_key, active=True,
                            unsubscribe_token=_token(), created_by=actor.id)
    db.add(person)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That address is already on the list")
    audit(db, actor.id, "email.recipient.create", f"recipient:{person.id}",
          {"email": person.email, "group": person.group_key})
    db.commit()
    return {"id": person.id}


@router.patch("/recipients/{recipient_id}")
def update_recipient(recipient_id: int, body: RecipientUpdate,
                     db: Session = Depends(get_db), actor=Depends(admin_only)):
    person = db.get(EmailRecipient, recipient_id)
    if not person:
        raise HTTPException(404, "Recipient not found")
    changes = {}
    if body.name is not None:
        person.name = body.name.strip() or None
        changes["name"] = person.name
    if body.group_key is not None:
        group = body.group_key.strip().lower()
        if group not in GROUPS:
            raise HTTPException(422, "group must be md, admin or extra")
        if group != person.group_key:
            person.group_key = group
            changes["group"] = group
    if body.active is not None:
        person.active = body.active
        changes["active"] = body.active
    if changes:
        audit(db, actor.id, "email.recipient.update", f"recipient:{person.id}",
              changes)
    db.commit()
    return {"id": person.id}


@router.delete("/recipients/{recipient_id}")
def delete_recipient(recipient_id: int, db: Session = Depends(get_db),
                     actor=Depends(admin_only)):
    person = db.get(EmailRecipient, recipient_id)
    if not person:
        raise HTTPException(404, "Recipient not found")
    audit(db, actor.id, "email.recipient.delete", f"recipient:{person.id}",
          {"email": person.email, "group": person.group_key})
    db.delete(person)
    db.commit()
    return {"ok": True}


# --- schedules -------------------------------------------------------------

def _recipient_rows(db: Session, schedule) -> list[dict]:
    return [{"id": link.recipient.id, "email": link.recipient.email,
             "name": link.recipient.name, "group": link.recipient.group_key,
             "active": link.recipient.active, "field": link.field}
            for link in schedule.recipients if link.recipient]


def _out(db: Session, schedule) -> dict:
    people = _recipient_rows(db, schedule)
    groups = list(schedule.groups or [])
    active_people = [p for p in people if p["active"]]
    warnings = []
    if not active_people and not groups:
        warnings.append("No active recipients: a live send will be refused.")
    if schedule.pack_key == "accounts" and "extra" in groups:
        warnings.append("The Accounts pack is going to the extra group; confirm "
                        "the Administrator allows those people to see accounts data.")
    return {
        "id": schedule.id, "name": schedule.name, "pack_key": schedule.pack_key,
        "pack_label": report_packs.PACKS.get(schedule.pack_key, {}).get("label",
                                                                       schedule.pack_key),
        "enabled": schedule.enabled, "frequency": schedule.frequency,
        "timezone": schedule.timezone, "weekdays": schedule.weekdays or [],
        "times": schedule.times or [], "month_day": schedule.month_day,
        "month_rule": schedule.month_rule, "custom_cron": schedule.custom_cron,
        "holiday_rule": schedule.holiday_rule,
        "include_attachments": schedule.include_attachments,
        "include_accounts": schedule.include_accounts,
        "custom_reports": schedule.custom_reports or [],
        "groups": groups, "recipients": people,
        "description": schedule_service.describe(schedule),
        "next_run_at": schedule.next_run_at, "last_run_at": schedule.last_run_at,
        "last_status": schedule.last_status, "last_error": schedule.last_error,
        "warnings": warnings,
    }


def _apply(schedule, body: ScheduleIn, db: Session) -> None:
    try:
        report_packs.pack_meta(body.pack_key)
    except report_packs.PackError as exc:
        raise HTTPException(422, str(exc))
    fields = ("enabled", "frequency", "timezone", "holiday_rule",
              "include_attachments", "include_accounts")
    for name in fields:
        setattr(schedule, name, getattr(body, name))
    schedule.name = body.name.strip()
    schedule.pack_key = body.pack_key
    schedule.weekdays = sorted({int(d) for d in body.weekdays})
    schedule.times = sorted({t.strip() for t in body.times if t and t.strip()})
    schedule.month_day = body.month_day
    schedule.month_rule = (body.month_rule or None)
    schedule.custom_cron = (body.custom_cron or "").strip() or None
    schedule.custom_reports = [r for r in dict.fromkeys(body.custom_reports) if r]
    unknown = [r for r in schedule.custom_reports if r not in reports.CATALOG]
    if unknown:
        raise HTTPException(422, f"Unknown report: {unknown[0]}")
    schedule.groups = [g for g in dict.fromkeys(body.groups) if g in GROUPS]
    try:
        schedule_service.validate(schedule)
    except schedule_service.ScheduleError as exc:
        raise HTTPException(422, str(exc))

    for person in body.recipients:
        if db.get(EmailRecipient, person.recipient_id) is None:
            raise HTTPException(422, f"Recipient {person.recipient_id} does not exist")
    schedule.recipients = [
        EmailScheduleRecipient(recipient_id=person.recipient_id, field=person.field)
        for person in body.recipients]


def _next_run(db: Session, schedule):
    return (schedule_service.next_run(schedule, datetime.now(timezone.utc),
                                      _holidays(db, schedule))
            if schedule.enabled else None)


def _holidays(db: Session, schedule):
    today = datetime.now(timezone.utc).date()
    return schedule_service.holidays_between(db, today - timedelta(days=2),
                                             today + timedelta(
                                                 days=schedule_service.HORIZON_DAYS + 5))


def _timing(body: ScheduleIn) -> tuple:
    return (body.frequency, body.timezone, tuple(sorted(body.weekdays)),
            tuple(body.times), body.month_day, body.month_rule,
            (body.custom_cron or "").strip(), body.holiday_rule)


@router.get("/schedules")
def list_schedules(db: Session = Depends(get_db), _=Depends(admin_only)):
    return [_out(db, s) for s in db.scalars(
        select(EmailSchedule).order_by(EmailSchedule.name)).all()]


@router.post("/schedules", status_code=201)
def create_schedule(body: ScheduleIn, db: Session = Depends(get_db),
                    actor=Depends(admin_only)):
    schedule = EmailSchedule(created_by=actor.id)
    _apply(schedule, body, db)
    schedule.next_run_at = _next_run(db, schedule)
    db.add(schedule)
    db.flush()
    audit(db, actor.id, "email.schedule.create", f"schedule:{schedule.id}",
          {"name": schedule.name, "pack": schedule.pack_key,
           "frequency": schedule.frequency, "enabled": schedule.enabled})
    db.commit()
    return _out(db, schedule)


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleUpdate,
                    db: Session = Depends(get_db), actor=Depends(admin_only)):
    schedule = db.get(EmailSchedule, schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    before = _timing(body)
    was_enabled = schedule.enabled
    _apply(schedule, body, db)
    same_timing = (before == _timing(body) and was_enabled == schedule.enabled
                   and schedule.next_run_at is not None)
    schedule.next_run_at = schedule.next_run_at if same_timing else _next_run(db, schedule)
    audit(db, actor.id, "email.schedule.update", f"schedule:{schedule.id}",
          {"name": schedule.name, "pack": schedule.pack_key,
           "enabled": schedule.enabled, "frequency": schedule.frequency,
           "recipients": len(body.recipients), "groups": schedule.groups})
    db.commit()
    return _out(db, schedule)


@router.post("/schedules/{schedule_id}/enable")
def enable_schedule(schedule_id: int, body: EnableIn, db: Session = Depends(get_db),
                    actor=Depends(admin_only)):
    schedule = db.get(EmailSchedule, schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    schedule.enabled = body.enabled
    schedule.next_run_at = _next_run(db, schedule)
    audit(db, actor.id, "email.schedule.pause" if not body.enabled
          else "email.schedule.resume", f"schedule:{schedule.id}",
          {"name": schedule.name, "enabled": body.enabled})
    db.commit()
    return _out(db, schedule)


@router.post("/schedules/{schedule_id}/duplicate", status_code=201)
def duplicate_schedule(schedule_id: int, db: Session = Depends(get_db),
                       actor=Depends(admin_only)):
    source = db.get(EmailSchedule, schedule_id)
    if not source:
        raise HTTPException(404, "Schedule not found")
    copy = EmailSchedule(name=f"{source.name} (copy)"[:120],
                         pack_key=source.pack_key, enabled=False,
                         frequency=source.frequency, timezone=source.timezone,
                         weekdays=list(source.weekdays or []),
                         month_day=source.month_day, month_rule=source.month_rule,
                         times=list(source.times or []),
                         custom_cron=source.custom_cron,
                         holiday_rule=source.holiday_rule,
                         include_attachments=source.include_attachments,
                         include_accounts=source.include_accounts,
                         custom_reports=list(source.custom_reports or []),
                         groups=list(source.groups or []), created_by=actor.id,
                         next_run_at=None)
    copy.recipients = [EmailScheduleRecipient(recipient_id=link.recipient_id,
                                              field=link.field)
                       for link in source.recipients]
    db.add(copy)
    db.flush()
    audit(db, actor.id, "email.schedule.duplicate", f"schedule:{copy.id}",
          {"from": source.id, "name": copy.name})
    db.commit()
    return _out(db, copy)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db),
                    actor=Depends(admin_only)):
    schedule = db.get(EmailSchedule, schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    audit(db, actor.id, "email.schedule.delete", f"schedule:{schedule.id}",
          {"name": schedule.name, "pack": schedule.pack_key})
    db.delete(schedule)
    db.commit()
    return {"ok": True}


def _preflight(db: Session, schedule) -> None:
    """Refuse queuing when the send would fail for a reason the admin can fix now."""
    if not email_config.effective(db).enabled:
        raise HTTPException(409, "Sending is disabled (EMAIL_SEND_ENABLED is false)")
    if not mailer.smtp_ready(db):
        raise HTTPException(409, "SMTP is not configured; a send cannot start")
    if mailer.live_mode(db):
        try:
            mailer.resolve(db, schedule)
        except mailer.MailError as exc:
            raise HTTPException(409, str(exc))


def _queue(db: Session, schedule, trigger: str, actor) -> EmailDelivery:
    _preflight(db, schedule)
    delivery, made = email_worker.create_delivery(db, schedule,
                                                  datetime.now(timezone.utc), trigger,
                                                  created_by=actor.id)
    if delivery is None:
        raise HTTPException(409, "This run was already queued this second")
    audit(db, actor.id, "email.queue", f"delivery:{delivery.id}",
          {"schedule": schedule.id, "pack": schedule.pack_key, "trigger": trigger},
          notify=False)
    db.commit()
    return delivery


@router.post("/schedules/{schedule_id}/run-now", status_code=202)
def run_now(schedule_id: int, db: Session = Depends(get_db), actor=Depends(admin_only)):
    schedule = db.get(EmailSchedule, schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    delivery = _queue(db, schedule, "manual", actor)
    return {"delivery_id": delivery.id, "status": delivery.status}


@router.post("/schedules/{schedule_id}/test", status_code=202)
def send_test(schedule_id: int, db: Session = Depends(get_db), actor=Depends(admin_only)):
    schedule = db.get(EmailSchedule, schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    delivery = _queue(db, schedule, "test", actor)
    return {"delivery_id": delivery.id, "status": delivery.status,
            "redirected_to": mailer.test_recipient(db) or "the Administrator"}


@router.get("/schedules/{schedule_id}/preview", response_class=HTMLResponse)
def preview(schedule_id: int, db: Session = Depends(get_db), actor=Depends(admin_only)):
    schedule = db.get(EmailSchedule, schedule_id)
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    today = datetime.now(timezone.utc).astimezone(
        ZoneInfo(schedule.timezone or schedule_service.DEFAULT_TZ)).date()
    window = report_packs.period_for(schedule.pack_key, today, "manual")
    data = report_packs.build(db, schedule.pack_key, window["from"], window["to"],
                              include_accounts=schedule.include_accounts,
                              custom_reports=list(schedule.custom_reports or []),
                              base_url=settings.app_base_url)
    data["include_attachments"] = schedule.include_attachments
    attachments = report_packs.build_attachments(db, data, schedule.pack_key)
    rendered = render(data, attachments, mode="preview",
                      owner=actor.username, dashboard_url=f"{settings.app_base_url}/ui/")
    return HTMLResponse(rendered["html"])


# --- delivery log ----------------------------------------------------------

def _delivery_out(row: EmailDelivery) -> dict:
    return {"id": row.id, "run_key": row.run_key, "schedule_id": row.schedule_id,
            "pack": row.pack_key, "trigger": row.trigger, "status": row.status,
            "mode": row.mode, "period_from": row.period_from,
            "period_to": row.period_to, "subject": row.subject,
            "recipients": row.recipients or [], "recipient_count": row.recipient_count,
            "attachments": row.attachments or [],
            "attachment_bytes": row.attachment_bytes, "error": row.error,
            "attempts": row.attempts, "next_attempt_at": row.next_attempt_at,
            "created_at": row.created_at, "started_at": row.started_at,
            "finished_at": row.finished_at, "sent_at": row.sent_at}


@router.get("/deliveries")
def list_deliveries(status: str | None = None, pack: str | None = None,
                    schedule_id: int | None = None,
                    limit: int = Query(100, ge=1, le=500),
                    db: Session = Depends(get_db), _=Depends(admin_only)):
    query = select(EmailDelivery)
    if status:
        query = query.where(EmailDelivery.status == status)
    if pack:
        query = query.where(EmailDelivery.pack_key == pack)
    if schedule_id is not None:
        query = query.where(EmailDelivery.schedule_id == schedule_id)
    rows = db.scalars(query.order_by(EmailDelivery.id.desc()).limit(limit)).all()
    return [_delivery_out(row) for row in rows]


@router.post("/deliveries/{delivery_id}/resend", status_code=202)
def resend(delivery_id: int, db: Session = Depends(get_db), actor=Depends(admin_only)):
    original = db.get(EmailDelivery, delivery_id)
    if not original:
        raise HTTPException(404, "Delivery not found")
    if original.schedule is None:
        raise HTTPException(409, "The schedule for this delivery no longer exists")
    delivery = _queue(db, original.schedule, "resend", actor)
    return {"delivery_id": delivery.id, "status": delivery.status}


# --- unsubscribe (public, token-addressed) ---------------------------------

def _token() -> str:
    from uuid import uuid4
    return uuid4().hex + uuid4().hex


def _page(title: str, message: str, form: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title></head>'
            f'<body style="margin:0;background:#E9EEEA;font-family:Arial,Helvetica,sans-serif">'
            f'<div style="max-width:520px;margin:40px auto;background:#fff;border-radius:12px;'
            f'padding:28px"><h1 style="font-size:20px;color:#1F6B4A;margin-top:0">{title}</h1>'
            f'<p style="font-size:15px;line-height:1.5;color:#16211B">{message}</p>{form}</div>'
            f'</body></html>')


@public_router.get("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str, db: Session = Depends(get_db)):
    person = db.scalar(select(EmailRecipient)
                       .where(EmailRecipient.unsubscribe_token == token))
    if person is None:
        return HTMLResponse(_page("Link not recognised",
                                  "This unsubscribe link is not valid."), status_code=404)
    if person.group_key != "extra":
        return HTMLResponse(_page(
            "Managed by the Administrator",
            "Management and Administrator report mail is required and can be removed "
            "only by the Administrator."), status_code=403)
    if not person.active:
        return HTMLResponse(_page("Already unsubscribed",
                                  "This address no longer receives scheduled reports."))
    form = (f'<form method="post" action="/api/email-reports/unsubscribe/{token}">'
            f'<button type="submit" style="background:#1F6B4A;color:#fff;border:0;'
            f'border-radius:10px;padding:14px 22px;font-size:15px;min-height:44px">'
            f'Stop sending reports to this address</button></form>')
    return HTMLResponse(_page("Unsubscribe", "Confirm that you no longer wish to receive "
                              "scheduled reports at this address.", form))


@public_router.post("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    person = db.scalar(select(EmailRecipient)
                       .where(EmailRecipient.unsubscribe_token == token))
    if person is None:
        return HTMLResponse(_page("Link not recognised",
                                  "This unsubscribe link is not valid."), status_code=404)
    if person.group_key != "extra":
        return HTMLResponse(_page(
            "Managed by the Administrator",
            "Management and Administrator report mail is required and can be removed "
            "only by the Administrator."), status_code=403)
    person.active = False
    audit(db, None, "email.unsubscribe", f"recipient:{person.id}",
          {"group": person.group_key}, notify=False)
    db.commit()
    return HTMLResponse(_page("Unsubscribed",
                              "This address will not receive scheduled reports again. "
                              "The Administrator can re-enable it."))
