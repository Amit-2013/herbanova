"""Telegram notifications for website updates.

audit() queues a message on the DB session; it is only sent after the transaction
commits (rolled-back changes never notify). Sending runs in a background thread
and never raises, so Telegram problems can't break or slow down an API request.
"""
import html
import logging
import threading

import httpx
from sqlalchemy import event
from sqlalchemy.orm import Session

from ..core.config import settings

log = logging.getLogger("telegram")
_PENDING = "telegram_pending"

ICONS = {
    "product.create": "\U0001F4E6", "warehouse.create": "\U0001F3ED",
    "po.create": "\U0001F9FE", "po.receive": "\u2705", "auth.login": "\U0001F511",
    "distributor.create": "\U0001F91D", "distributor.credit_limit": "\U0001F4B3",
    "so.create": "\U0001F4DD", "so.submit": "\U0001F4E4", "so.dispatch": "\U0001F69A",
    "so.cancel": "\u274C", "approval.decide": "\U0001F6E1",
    "lead.create": "\U0001F331", "lead.activity": "\U0001F4DE", "lead.status": "\U0001F3AF",
    "lead.followup": "\U0001F4C5", "lead.owner": "\U0001F464", "lead.update": "\u270F",
    "report.export": "\U0001F4E5",
}


def enabled() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def _send(text: str) -> None:
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10)
        if r.status_code != 200:
            log.warning("Telegram rejected message: %s %s", r.status_code, r.text[:200])
    except Exception as exc:  # never let notifications break the app
        log.warning("Telegram send failed: %s", exc)


def _format(action: str, record: str, actor: str, changes: dict) -> str:
    e = html.escape
    lines = [f"{ICONS.get(action, chr(0x1F514))} <b>{e(action)}</b>",
             f"Record: <code>{e(record)}</code>", f"By: {e(actor)}"]
    for k, v in changes.items():
        lines.append(f"{e(str(k))}: {e(str(v))[:300]}")
    return "\n".join(lines)


def queue(db: Session, action: str, record: str, actor: str, changes: dict) -> None:
    """Called by audit(); message goes out only if/when this session commits."""
    if not enabled():
        return
    if action == "auth.login" and not settings.telegram_notify_login:
        return
    db.info.setdefault(_PENDING, []).append(_format(action, record, actor, changes))


@event.listens_for(Session, "after_commit")
def _flush_after_commit(session: Session) -> None:
    for text in session.info.pop(_PENDING, []):
        threading.Thread(target=_send, args=(text,), daemon=True).start()


@event.listens_for(Session, "after_rollback")
def _drop_on_rollback(session: Session) -> None:
    session.info.pop(_PENDING, None)