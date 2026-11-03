"""Passwords and session tokens.

Module Phase 1 additions (FR-01):
- JWTs carry the user's `token_version`; bumping it (password change, admin
  reset, deactivation) invalidates every earlier token, so "old sessions end"
  is enforced on the backend, not by hoping the browser clears the cookie.
- A documented password policy, validated on every password set or change.
- Temporary passwords are generated from the crypto random source, shown once
  and never stored anywhere except as an argon2 hash.
"""
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import settings

_ph = PasswordHasher()

# ---------------------------------------------------------------- passwords
MIN_LENGTH = 12
MAX_LENGTH = 128


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, Exception):   # a malformed hash must never crash login
        return False


def hash_secondary_password(pw: str) -> str:
    """Hash the admin secondary password with the same argon2 hasher as logins.

    The encoded string carries its own salt and parameters, so it can be
    verified later without keeping any plaintext or separate salt.
    """
    return _ph.hash(pw)


def verify_secondary_password(hashed: str | None, pw: str) -> bool:
    """Verify the admin secondary password; malformed or missing values fail closed."""
    if not hashed:
        return False
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, Exception):
        return False


def password_problems(pw: str, username: str = "") -> list[str]:
    """The password policy as a list of human-readable problems (empty = acceptable)."""
    problems = []
    if len(pw or "") < MIN_LENGTH:
        problems.append(f"Password must be at least {MIN_LENGTH} characters long")
    if len(pw or "") > MAX_LENGTH:
        problems.append(f"Password must be at most {MAX_LENGTH} characters long")
    classes = sum(1 for ok in (
        any(c.islower() for c in pw), any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw), any(not c.isalnum() for c in pw)) if ok)
    if classes < 3:
        problems.append("Password must combine at least three of: lowercase, "
                        "uppercase, digits, symbols")
    if username and pw.strip().lower() == username.strip().lower():
        problems.append("Password must not be the username")
    return problems


def validate_password(pw: str, username: str = "") -> None:
    problems = password_problems(pw, username)
    if problems:
        raise ValueError("; ".join(problems))


def generate_temp_password() -> str:
    """A random temporary password, shown once. Meets the policy by construction."""
    lower = string.ascii_lowercase.replace("0o", "").replace("1l", "")
    upper = string.ascii_uppercase.replace("O0", "").replace("I1", "")
    digits = string.digits.replace("0", "").replace("1", "")
    symbols = "!@#$%^&*?-_=+"
    pw = [secrets.choice(lower), secrets.choice(upper), secrets.choice(digits),
          secrets.choice(symbols)]
    pool = lower + upper + digits + symbols
    pw += [secrets.choice(pool) for _ in range(MIN_LENGTH + 2 - len(pw))]
    secrets.SystemRandom().shuffle(pw)
    return "".join(pw)


# ---------------------------------------------------------------- session tokens
def make_token(user_id: int, token_version: int = 1, minutes: int = 60,
               otp: bool = False) -> str:
    """A session JWT. `otp` marks a session that passed the second factor.

    A user with two-factor enabled is rejected by `current_user` unless the
    token carries this claim, so a first-factor-only token can never be used
    even if one were issued by a bug.
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=minutes)
    claims = {"sub": str(user_id), "tv": int(token_version), "iat": now, "exp": exp}
    if otp:
        claims["otp"] = True
    return jwt.encode(claims, settings.app_secret, "HS256")


def read_session_token(token: str) -> dict | None:
    """The full session claim set (sub, tv, otp) or None if the token is invalid."""
    try:
        claims = jwt.decode(token, settings.app_secret, ["HS256"])
        return {"user_id": int(claims["sub"]), "token_version": int(claims.get("tv", 1)),
                "otp": claims.get("otp") is True}
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def read_token(token: str) -> int | None:
    pair = read_token_full(token)
    return pair[0] if pair else None


def read_token_full(token: str) -> tuple[int, int] | None:
    """(user_id, token_version) from a session JWT, or None if it is invalid."""
    parsed = read_session_token(token)
    return (parsed["user_id"], parsed["token_version"]) if parsed else None
