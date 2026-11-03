"""Google Authenticator (TOTP) for the Administrator accounts.

RFC 6238 over the standard library: HMAC-SHA1, six digits, a 30-second step
and a one-step window either side so a slightly slow phone still works. No
SMS, email or network is needed once the key is in the app.

The shared secret is sealed with a key derived from ``APP_SECRET`` before it
is stored, so a database copy alone cannot produce codes. A used code cannot
be replayed: the time step is stored and the next code must be later.

Enrollment is required for the Administrator roles. Every other role keeps
the existing password-only login. The challenge between password and code is
a short-lived, HttpOnly cookie that is not a session: it opens only the two
factor endpoints and cannot read data.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
from cryptography.fernet import Fernet, InvalidToken

from ..core.config import settings
from ..core.security import hash_password, verify_password

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1                    # accept the previous and next step
ISSUER = "Herbanova"
RECOVERY_CODES = 10
MAX_OTP_FAILURES = 5
OTP_LOCK_MINUTES = 15
CHALLENGE_COOKIE = "totp_challenge"
CHALLENGE_MINUTES = 10
TOTP_ROLES = {"admin", "super_admin"}
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


# ---------------------------------------------------------------- secret at rest
def _fernet() -> Fernet:
    digest = hashlib.sha256(f"herbanova:totp:{settings.app_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def unseal(token: str | None) -> str | None:
    """The secret, or None when the token is missing or APP_SECRET changed."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError):
        return None


# ---------------------------------------------------------------- TOTP maths
def generate_secret() -> str:
    """A 160-bit base32 secret, the size the authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.strip().upper()
    padded += "=" * (-len(padded) % 8)
    return base64.b32decode(padded, casefold=True)


def code_at(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def counter_at(moment: datetime | None = None) -> int:
    stamp = moment.timestamp() if moment is not None else time.time()
    return int(stamp // STEP_SECONDS)


def verify_code(secret: str, code: str, *, after_counter: int | None = None,
                now: datetime | None = None) -> int | None:
    """The accepted time step, or None. A step at or before `after_counter` is replay."""
    code = (code or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    current = counter_at(now)
    for delta in range(-WINDOW, WINDOW + 1):
        counter = current + delta
        if after_counter is not None and counter <= after_counter:
            continue
        if hmac.compare_digest(code_at(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


# ---------------------------------------------------------------- recovery codes
def generate_recovery_codes(count: int = RECOVERY_CODES) -> list[str]:
    codes = []
    for _ in range(count):
        left = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5))
        right = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5))
        codes.append(f"{left}-{right}")
    return codes


def hash_recovery_codes(codes: list[str]) -> list[str]:
    return [hash_password(code.strip().lower()) for code in codes]


def take_recovery_code(hashes: list[str] | None, code: str) -> tuple[bool, list[str]]:
    """(matched, remaining hashes). A matching hash is removed, so it is single-use."""
    stored = list(hashes or [])
    text = (code or "").strip().lower()
    if not text:
        return False, stored
    for index, hashed in enumerate(stored):
        if verify_password(text, hashed):
            del stored[index]
            return True, stored
    return False, stored


# ---------------------------------------------------------------- role policy
def role_name(user) -> str:
    role = getattr(user, "role_rel", None)
    name = getattr(role, "name", None) or getattr(user, "role", "")
    return (name or "").strip().lower()


def requires_totp(user) -> bool:
    """Administrator and Super Administrator only; every other role is unchanged."""
    return role_name(user) in TOTP_ROLES


# ---------------------------------------------------------------- challenge token
def make_challenge(user_id: int, token_version: int, mode: str) -> str:
    """A short-lived ticket that only proves the password step succeeded."""
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "tv": int(token_version), "purpose": "totp",
                       "mode": mode, "iat": now,
                       "exp": now + timedelta(minutes=CHALLENGE_MINUTES)},
                      settings.app_secret, "HS256")


def read_challenge(token: str, mode: str) -> tuple[int, int] | None:
    """(user_id, token_version) when the ticket is valid for this mode."""
    try:
        claims = jwt.decode(token, settings.app_secret, ["HS256"])
        if claims.get("purpose") != "totp" or claims.get("mode") != mode:
            return None
        return int(claims["sub"]), int(claims.get("tv", 1))
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def lock_remaining(user) -> int:
    """Seconds left on an OTP lockout (0 when not locked)."""
    until = getattr(user, "totp_locked_until", None)
    if until is None:
        return 0
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return max(0, int((until - datetime.now(timezone.utc)).total_seconds()))
