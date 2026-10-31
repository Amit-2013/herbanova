"""Account lockout (FR-01, AUD-027).

After MAX_FAILED wrong passwords the account locks for LOCK_MINUTES, counted
per user record (not per username spelling), so retrying with different letter
cases cannot bypass it. A successful login clears the counter. Lockouts are
audited (no secrets, no attempted password).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models.core import User

MAX_FAILED = 5
LOCK_MINUTES = 15


def _aware(dt) -> datetime:
    """Tolerate naive timestamps coming back from the database."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def is_locked(user: User, now: datetime | None = None) -> bool:
    if not user.locked_until:
        return False
    return _aware(user.locked_until) > (now or datetime.now(timezone.utc))


def register_failure(db: Session, user: User) -> bool:
    """Count one failed attempt. Returns True if this attempt locked the account."""
    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= MAX_FAILED:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)
        user.failed_attempts = 0                    # a later lock starts a fresh count
        return True
    return False


def clear_failures(db: Session, user: User) -> None:
    user.failed_attempts = 0
    user.locked_until = None
