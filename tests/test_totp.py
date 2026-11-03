"""Administrator two-factor authentication: RFC vectors and the login gate.

The code screen is only a view. These tests prove the server refuses to issue
a session for an Administrator account until the authenticator step (or the
one-time enrollment) is complete, and that every other role is unchanged.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.limiter import limiter
from app.core.security import hash_password, make_token
from app.main import app
from app.models.core import User
from app.models.users import Employee, Role
from app.services import totp

PASSWORD = "AdminPass!1234"
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"   # RFC 6238 test key, base32


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    limiter.reset()
    yield
    limiter.reset()


def _user(role_name: str) -> tuple[int, str]:
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == role_name))
        employee = Employee(code=f"TOTP_{suffix}"[:30].upper(),
                            full_name="TOTP test", status="active")
        db.add(employee)
        db.flush()
        user = User(username=f"totp_{suffix}", username_key=f"totp_{suffix}",
                    password_hash=hash_password(PASSWORD), role=role.name,
                    role_id=role.id, employee_id=employee.id)
        db.add(user)
        db.commit()
        return user.id, user.username


def _enrolled_admin() -> tuple[int, str, str, list[str]]:
    user_id, username = _user("admin")
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/auth/login", json={
        "username": username, "password": PASSWORD}).json()["status"] == "setup_required"
    secret = client.get("/api/auth/2fa/setup").json()["secret"]
    done = client.post("/api/auth/2fa/confirm", json={
        "code": totp.code_at(secret, totp.counter_at())})
    assert done.status_code == 200, done.text
    client.cookies.clear()
    return user_id, username, secret, done.json()["recovery_codes"]


# --- the maths --------------------------------------------------------------

def test_codes_match_the_rfc_6238_vectors():
    at_59 = datetime.fromtimestamp(59, tz=timezone.utc)
    at_1111111109 = datetime.fromtimestamp(1111111109, tz=timezone.utc)
    assert totp.code_at(SECRET, totp.counter_at(at_59)) == "287082"
    assert totp.code_at(SECRET, totp.counter_at(at_1111111109)) == "081804"


def test_a_used_step_cannot_be_replayed():
    step = totp.counter_at()
    code = totp.code_at(SECRET, step)
    assert totp.verify_code(SECRET, code, after_counter=step - 1) == step
    assert totp.verify_code(SECRET, code, after_counter=step) is None
    assert totp.verify_code(SECRET, "12ab34") is None


# --- the login gate ---------------------------------------------------------

def test_a_non_administrator_still_signs_in_with_the_password_alone():
    _user_id, username = _user("viewer")
    client = TestClient(app, base_url="https://testserver")
    res = client.post("/api/auth/login", json={"username": username,
                                               "password": PASSWORD})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"
    assert res.json()["totp"] == {"required": False, "enabled": False}
    assert client.cookies.get("session")
    assert client.get("/api/auth/me").status_code == 200


def test_an_administrator_cannot_get_a_session_before_enrolling():
    _user_id, username = _user("admin")
    client = TestClient(app, base_url="https://testserver")
    res = client.post("/api/auth/login", json={"username": username,
                                               "password": PASSWORD})
    assert res.status_code == 200
    assert res.json()["status"] == "setup_required"
    assert client.cookies.get("session") is None
    assert client.get("/api/auth/me").status_code == 401


def test_enrollment_confirm_then_the_next_sign_in_needs_the_code():
    _user_id, username, secret, codes = _enrolled_admin()
    assert len(codes) == 10 and all("-" in code for code in codes)

    client = TestClient(app, base_url="https://testserver")
    first = client.post("/api/auth/login", json={"username": username,
                                                 "password": PASSWORD})
    assert first.json()["status"] == "otp_required"
    assert client.cookies.get("session") is None

    wrong = "000000" if totp.code_at(secret, totp.counter_at() + 1) != "000000" else "000001"
    assert client.post("/api/auth/2fa/verify",
                       json={"code": wrong}).status_code == 401
    code = totp.code_at(secret, totp.counter_at() + 1)
    good = client.post("/api/auth/2fa/verify", json={"code": code})
    assert good.status_code == 200, good.text
    assert good.json()["status"] == "ok"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["totp"] == {"required": True, "enabled": True}


def test_a_recovery_code_works_once_only():
    _user_id, username, _secret, codes = _enrolled_admin()
    client = TestClient(app, base_url="https://testserver")
    client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    first = client.post("/api/auth/2fa/verify",
                        json={"recovery_code": codes[0]})
    assert first.status_code == 200, first.text
    assert first.json()["method"] == "recovery"

    again = TestClient(app, base_url="https://testserver")
    again.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    reused = again.post("/api/auth/2fa/verify", json={"recovery_code": codes[0]})
    assert reused.status_code == 401


def test_a_session_without_the_second_factor_claim_is_rejected():
    user_id, _username, _secret, _codes = _enrolled_admin()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        token = make_token(user.id, user.token_version, otp=False)
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set("session", token)
    refused = client.get("/api/auth/me")
    assert refused.status_code == 401
    assert "two-factor" in refused.json()["detail"].lower()


def test_five_wrong_codes_lock_the_second_step():
    _user_id, username, _secret, _codes = _enrolled_admin()
    client = TestClient(app, base_url="https://testserver")
    client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    for _ in range(totp.MAX_OTP_FAILURES):
        assert client.post("/api/auth/2fa/verify",
                           json={"code": "000000"}).status_code == 401
    # The challenge is cleared when the lock is set, so a fresh password step
    # is needed before the lock itself answers.
    client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    locked = client.post("/api/auth/2fa/verify", json={"code": "000000"})
    assert locked.status_code == 423
