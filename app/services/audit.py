from sqlalchemy.orm import Session
from ..models.core import AuditLog, User
from . import telegram

SECRET_KEYS = {"password", "password_hash", "token", "secret", "temporary_password",
               "new_password", "current_password"}

def audit(db: Session, actor_id, action: str, record: str, changes: dict | None = None):
    clean = {k: v for k, v in (changes or {}).items() if k.lower() not in SECRET_KEYS}
    db.add(AuditLog(actor_id=actor_id, action=action, record=record, changes=clean))
    actor = db.get(User, actor_id) if actor_id else None
    telegram.queue(db, action, record, actor.username if actor else "system", clean)