"""The scheduled-report worker: a separate, DB-backed process.

It does two things in a loop:

1. `enqueue_due` turns a due schedule into a delivery row. The row's `run_key`
   is unique, so if two workers or a restart both try the same slot, only one
   insert succeeds. Nothing is sent twice.
2. `process_due` claims queued rows with `FOR UPDATE SKIP LOCKED`, builds the
   pack from the same services as the screens, renders it and hands it to the
   mailer. A failure is retried three times with increasing delay; the fourth
   failure is final and alerts through Telegram.

Nothing here sends email directly except through `mailer`, which keeps the
test/live double switch and never logs a credential.

Run it with `python -m app.email_worker` (add `--once` to process one cycle and
exit, which is what the tests and a cron entry point use).
"""
from __future__ import annotations

import argparse
import html
import logging
import time as clock
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import SessionLocal
from ..models.email import EmailDelivery, EmailSchedule
from . import audit, email_render, mailer, report_packs, telegram
from . import schedule as schedule_service

log = logging.getLogger("email_worker")

UTC = timezone.utc
MAX_ATTEMPTS = 4                 # the first try plus three retries
RETRY_DELAYS = (5, 15, 45)       # minutes before retry 1, 2 and 3
STALE_SENDING_MINUTES = 30       # a crashed worker's claim is released after this
CLAIM_LIMIT = 5

# Errors that retrying cannot fix. Anything else (a refused connection, a
# timeout, a 4xx from the SMTP server) is treated as transient and retried.
PERMANENT = (
    "not configured", "disabled", "no active recipients", "invalid",
    "no administrator email", "schedule was deleted", "unknown report pack",
)


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _holidays(db: Session, after: datetime):
    zone_after = after
    start = zone_after.date() - timedelta(days=2)
    end = zone_after.date() + timedelta(days=schedule_service.HORIZON_DAYS + 5)
    return schedule_service.holidays_between(db, start, end)


def _run_date(schedule, slot: datetime):
    zone = ZoneInfo(getattr(schedule, "timezone", None) or schedule_service.DEFAULT_TZ)
    return slot.astimezone(zone).date()


def create_delivery(db: Session, schedule, slot: datetime, trigger: str = "scheduled",
                    created_by: int | None = None) -> tuple[EmailDelivery | None, bool]:
    """Insert the delivery for one slot; (row, True) only if this call created it."""
    key = schedule_service.run_key(schedule.id, slot)
    existing = db.scalar(select(EmailDelivery).where(EmailDelivery.run_key == key))
    if existing is not None:
        return existing, False
    row = EmailDelivery(
        run_key=key, schedule_id=schedule.id, pack_key=schedule.pack_key,
        trigger=trigger, status="queued",
        mode="live" if mailer.live_mode(db) else "test",
        created_by=created_by)
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:          # another worker won the same slot
        return None, False
    return row, True


def enqueue_due(db: Session, now: datetime | None = None) -> int:
    """Create a delivery for every enabled schedule whose slot has arrived."""
    now = _now(now)
    created = 0
    fresh = db.scalars(select(EmailSchedule).where(
        EmailSchedule.enabled.is_(True), EmailSchedule.next_run_at.is_(None),
        or_(EmailSchedule.last_status.is_(None), EmailSchedule.last_status != "skipped"))
    ).all()
    for found in fresh:             # backfill after an import or an upgrade
        found.next_run_at = schedule_service.next_run(found, now)
    if fresh:
        # Commit the backfill even when no slot is due yet, otherwise the next
        # cycle repeats it and a schedule can stay unscheduled for ever.
        db.commit()

    due = db.scalars(select(EmailSchedule).where(
        EmailSchedule.enabled.is_(True), EmailSchedule.next_run_at.is_not(None),
        EmailSchedule.next_run_at <= now)).all()
    for schedule in due:
        slot = schedule.next_run_at.astimezone(UTC)
        try:
            schedule_service.validate(schedule)
        except schedule_service.ScheduleError as exc:
            schedule.last_status = "skipped"
            schedule.last_error = str(exc)[:500]
            schedule.next_run_at = None
            db.commit()
            continue

        holidays = _holidays(db, slot)
        _, made = create_delivery(db, schedule, slot, "scheduled")
        if made:
            created += 1
        schedule.last_run_at = slot
        schedule.last_status = "queued"
        schedule.last_error = None
        # A worker that was down for a while sends the slot it owes, not a
        # backlog of stale ones; the next run is the first slot after now.
        nxt = schedule_service.next_run(schedule, slot, holidays)
        while nxt is not None and nxt <= now:
            nxt = schedule_service.next_run(schedule, nxt, holidays)
        schedule.next_run_at = nxt
        db.commit()
    return created


def recover_stale(db: Session, now: datetime | None = None) -> int:
    """Release claims held by a worker that stopped mid-send."""
    now = _now(now)
    cutoff = now - timedelta(minutes=STALE_SENDING_MINUTES)
    rows = db.scalars(select(EmailDelivery).where(
        EmailDelivery.status == "sending",
        EmailDelivery.started_at.is_not(None), EmailDelivery.started_at < cutoff)).all()
    for row in rows:
        row.status = "retry" if (row.attempts or 0) < MAX_ATTEMPTS else "failed"
        row.error = "The worker stopped before recording the result."
        row.next_attempt_at = now if row.status == "retry" else None
    if rows:
        db.commit()
    return len(rows)


def claim(db: Session, now: datetime | None = None, limit: int = CLAIM_LIMIT) -> list[int]:
    """Take ownership of queued rows. SKIP LOCKED keeps two workers apart."""
    now = _now(now)
    rows = db.scalars(select(EmailDelivery).where(
        EmailDelivery.status.in_(("queued", "retry")),
        or_(EmailDelivery.next_attempt_at.is_(None), EmailDelivery.next_attempt_at <= now))
        .order_by(EmailDelivery.id).limit(limit).with_for_update(skip_locked=True)).all()
    ids = []
    for row in rows:
        row.status = "sending"
        row.started_at = now
        row.attempts = (row.attempts or 0) + 1
        ids.append(row.id)
    if ids:
        db.commit()
    return ids


def _permanent(error: Exception) -> bool:
    text = str(error).lower()
    return any(hint in text for hint in PERMANENT)


def _alert(delivery: EmailDelivery, error: Exception) -> None:
    e = html.escape
    text = (f"\U0001F4E7 <b>Scheduled report failed</b>\n"
            f"Pack: {e(delivery.pack_key)}\n"
            f"Delivery: {e(delivery.run_key)}\n"
            f"Attempts: {delivery.attempts}\n"
            f"Error: {e(str(error))[:300]}")
    telegram.notify_text(text)


def _record_success(db: Session, delivery: EmailDelivery, schedule, data: dict,
                    attachments: list[dict], rendered: dict, people: dict,
                    result: dict, mode: str, now: datetime) -> None:
    delivery.status = "sent"
    delivery.mode = mode
    delivery.subject = rendered["subject"][:250]
    delivery.recipients = people["to"] + people.get("cc", []) + people.get("bcc", [])
    delivery.recipient_count = result["to"] + result["cc"] + result["bcc"]
    delivery.attachments = [{"filename": a["filename"], "content_type": a["content_type"],
                             "kind": a["kind"], "bytes": len(a["bytes"])}
                            for a in attachments]
    delivery.attachment_bytes = sum(len(a["bytes"]) for a in attachments)
    delivery.period_from = date.fromisoformat(data["from"])
    delivery.period_to = date.fromisoformat(data["to"])
    delivery.error = None
    delivery.next_attempt_at = None
    delivery.finished_at = now
    delivery.sent_at = now
    schedule.last_status = "sent"
    schedule.last_error = None
    audit.audit(db, delivery.created_by, "email.send", f"delivery:{delivery.id}", {
        "pack": delivery.pack_key, "subject": delivery.subject, "mode": mode,
        "recipients": delivery.recipient_count, "attachments": len(attachments),
        "period": f"{data['from']} to {data['to']}",
    }, notify=False)


def _record_failure(db: Session, delivery: EmailDelivery, schedule, error: Exception,
                    now: datetime) -> None:
    delivery.error = f"{type(error).__name__}: {error}"[:2000]
    delivery.finished_at = now
    if _permanent(error) or (delivery.attempts or 0) >= MAX_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_attempt_at = None
        schedule.last_status = "failed"
        schedule.last_error = delivery.error[:500]
        _alert(delivery, error)
        audit.audit(db, delivery.created_by, "email.failed", f"delivery:{delivery.id}", {
            "pack": delivery.pack_key, "attempts": delivery.attempts,
            "error": delivery.error[:300],
        }, notify=False)
    else:
        delay = RETRY_DELAYS[min((delivery.attempts or 1) - 1, len(RETRY_DELAYS) - 1)]
        delivery.status = "retry"
        delivery.next_attempt_at = now + timedelta(minutes=delay)
        schedule.last_status = "retry"
        schedule.last_error = delivery.error[:500]


def process_one(db: Session, delivery_id: int, now: datetime | None = None) -> str:
    now = _now(now)
    delivery = db.get(EmailDelivery, delivery_id)
    if delivery is None:
        return "missing"
    schedule = delivery.schedule
    if schedule is None:
        delivery.status = "skipped"
        delivery.error = "The schedule was deleted; nothing was sent."
        delivery.finished_at = now
        db.commit()
        return "skipped"
    if delivery.trigger == "scheduled" and not schedule.enabled:
        delivery.status = "skipped"
        delivery.error = "The schedule was paused before this run."
        delivery.finished_at = now
        db.commit()
        return "skipped"

    try:
        slot = delivery.started_at or now
        window = report_packs.period_for(delivery.pack_key, _run_date(schedule, slot),
                                         delivery.trigger)
        data = report_packs.build(
            db, delivery.pack_key, window["from"], window["to"],
            include_accounts=schedule.include_accounts,
            custom_reports=list(schedule.custom_reports or []),
            base_url=settings.app_base_url, generated_at=now)
        data["include_attachments"] = bool(schedule.include_attachments)
        attachments = report_packs.build_attachments(db, data, delivery.pack_key)
        force_test = delivery.trigger == "test"
        people = mailer.resolve(
            db, schedule, force_test=force_test,
            test_address=_actor_email(db, delivery.created_by) if force_test else None)
        mode = "test" if people["redirected"] else "live"
        rendered = email_render.render(
            data, attachments, mode=mode, test_recipient=people.get("test_address"),
            real_recipients=people["real_count"],
            owner=_owner_name(db, schedule), dashboard_url=f"{settings.app_base_url}/ui/")
        rendered["attachments"] = attachments
        result = mailer.send(db, schedule, rendered, people)
        _record_success(db, delivery, schedule, data, attachments, rendered, people,
                        result, mode, now)
        db.commit()
        return "sent"
    except Exception as exc:        # report generation, rendering or SMTP
        log.warning("Delivery %s failed: %s", delivery.run_key, type(exc).__name__)
        # A database error leaves the session in a failed transaction. Roll it
        # back and re-read the row before recording the failure; otherwise the
        # failure itself raises PendingRollbackError and the delivery stays
        # "sending" until the stale-claim sweep, or is never recorded at all.
        db.rollback()
        delivery = db.get(EmailDelivery, delivery_id)
        if delivery is None:
            return "missing"
        schedule = delivery.schedule
        if schedule is None:
            delivery.status = "skipped"
            delivery.error = "The schedule was deleted; nothing was sent."
            delivery.finished_at = now
            db.commit()
            return "skipped"
        _record_failure(db, delivery, schedule, exc, now)
        try:
            db.commit()
        except Exception:
            db.rollback()
            log.exception("Could not record the failure of delivery %s", delivery.run_key)
        return "failed" if delivery.status == "failed" else "retry"


def _owner_name(db: Session, schedule) -> str:
    if not schedule.created_by:
        return "the Administrator"
    from ..models.core import User
    user = db.get(User, schedule.created_by)
    return user.username if user else "the Administrator"


def _actor_email(db: Session, actor_id) -> str | None:
    """The requesting Administrator's own address, used by "Send test to me"."""
    if not actor_id:
        return None
    from ..models.core import User
    from ..models.users import Employee
    user = db.get(User, actor_id)
    if user is None or not user.employee_id:
        return None
    employee = db.get(Employee, user.employee_id)
    return employee.email if employee and mailer.valid_address(employee.email) else None


def process_due(db: Session, now: datetime | None = None, limit: int = CLAIM_LIMIT) -> list[str]:
    return [process_one(db, delivery_id, now) for delivery_id in claim(db, now, limit)]


def run_once(db: Session, now: datetime | None = None) -> dict:
    # A database reset pauses every writer, this process included. Checking at
    # the top of the cycle covers both the queueing and the sending half, and a
    # cycle that started just before the pause finishes on its own.
    from .db_reset import current_maintenance
    paused = current_maintenance()
    if paused:
        return {"paused": True, "maintenance_run": paused.get("run_id"),
                "enqueued": 0, "released": 0, "processed": []}
    now = _now(now)
    return {"paused": False, "enqueued": enqueue_due(db, now),
            "released": recover_stale(db, now), "processed": process_due(db, now)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scheduled email report worker")
    parser.add_argument("--once", action="store_true", help="one cycle, then exit")
    parser.add_argument("--interval", type=int, default=settings.email_worker_interval,
                        help="seconds between cycles")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("Email worker started (mode=%s, send_enabled=%s)",
             settings.email_mode, settings.email_send_enabled)
    while True:
        with SessionLocal() as db:
            try:
                result = run_once(db)
                if result["enqueued"] or result["processed"] or result["released"]:
                    log.info("cycle: %s", result)
            except Exception:
                db.rollback()
                log.exception("Worker cycle failed")
        if args.once:
            return 0
        clock.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
