"""Expenses: heads, entries, approval, reversal and receipts.

The tests exercise the server rules, not the screen: every refusal is asserted
against the API, every accepted entry is read back, and the audit rows and
stored receipt bytes are checked.
"""
import io
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.api import expenses as expenses_api
from app.core.db import SessionLocal
from app.core.security import make_token
from app.models.core import AuditLog, User
from app.models.expenses import Expense
from app.models.users import Employee, Role


@pytest.fixture(autouse=True)
def _receipts_in_tmp(tmp_path, monkeypatch):
    """Never write a test receipt into the real var/expense_receipts."""
    monkeypatch.setattr(expenses_api, "ATTACHMENT_DIR", tmp_path / "receipts")


def _suffix() -> str:
    return uuid4().hex[:6].upper()


def _head(client, name: str | None = None) -> dict:
    name = name or f"Office {_suffix()}"
    res = client.post("/api/expenses/heads", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()


def _set_settings(client, enabled: bool, threshold: str = "0",
                  tracked_from: str = "2020-01-01"):
    res = client.put("/api/expenses/settings", json={
        "approval_enabled": enabled, "approval_threshold": threshold,
        "tracked_from": tracked_from})
    assert res.status_code == 200, res.text
    return res.json()


def _entry(client, head_id: int, amount: str = "100.00", **fields) -> dict:
    payload = {"head_id": head_id, "entry_date": date.today().isoformat(),
               "amount": amount, "mode": "bank", **fields}
    res = client.post("/api/expenses", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def _user_with_role(name: str, role_name: str = "admin",
                    permissions: list[str] | None = None) -> tuple[int, str]:
    """A fresh login, bypassing the password-change flow used by the UI users."""
    with SessionLocal() as db:
        if permissions is not None:
            role = Role(name=f"{name}_role", display_name=name, is_system=False,
                        permissions=permissions)
            db.add(role)
            db.flush()
        else:
            role = db.scalar(select(Role).where(Role.name == role_name))
            assert role is not None
        employee = Employee(code=f"EX_{_suffix()}", full_name=name, status="active")
        db.add(employee)
        db.flush()
        user = User(username=name, username_key=name, password_hash="x",
                    role=role.name, role_id=role.id, employee_id=employee.id)
        db.add(user)
        db.commit()
        return user.id, make_token(user.id, user.token_version or 1)


def _audit(action: str, record: str) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(
            AuditLog.action == action, AuditLog.record == record)
            .order_by(AuditLog.id)).all()
        return [r.changes or {} for r in rows]


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------- heads
def test_head_crud_and_settings_are_administrator_owned(client):
    admin = client.as_user("admin")
    heads = admin.get("/api/expenses/heads").json()
    payroll = next(h for h in heads if h["is_system"])
    assert payroll["name"] == "Payroll (from HR)"
    assert admin.patch(f"/api/expenses/heads/{payroll['id']}",
                       json={"is_active": False}).status_code == 409

    head = _head(admin)
    duplicate = admin.post("/api/expenses/heads", json={"name": head["name"].lower()})
    assert duplicate.status_code == 409, duplicate.text
    assert _audit("expense.head", f"expense_head:{head['id']}")

    renamed = admin.patch(f"/api/expenses/heads/{head['id']}",
                          json={"name": head["name"] + " revised", "is_active": False})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["is_active"] is False
    visible = {h["id"] for h in admin.get("/api/expenses/heads").json()}
    assert head["id"] not in visible
    every = {h["id"] for h in admin.get(
        "/api/expenses/heads", params={"include_inactive": True}).json()}
    assert head["id"] in every

    manual = admin.post("/api/expenses", json={
        "head_id": payroll["id"], "entry_date": date.today().isoformat(),
        "amount": "100.00"})
    assert manual.status_code == 422
    assert "payroll" in manual.json()["detail"].lower()

    _set_settings(admin, True, "25000.00", "2019-04-01")
    current = admin.get("/api/expenses/settings").json()
    assert current == {"approval_enabled": True, "approval_threshold": "25000.00",
                       "tracked_from": "2019-04-01"}
    assert _audit("expense.settings", "expense_settings:1")

    future = admin.put("/api/expenses/settings", json={
        "approval_enabled": False, "approval_threshold": "0",
        "tracked_from": (date.today() + timedelta(days=1)).isoformat()})
    assert future.status_code == 422


def test_server_refuses_expense_access_without_the_permission(client):
    assert client.as_user("sales").get("/api/expenses").status_code == 403
    assert client.as_user("sales").post("/api/expenses", json={
        "head_id": 1, "entry_date": date.today().isoformat(),
        "amount": "10.00"}).status_code == 403
    assert client.as_user("sales").get("/api/expenses/settings").status_code == 403

    # A custom role can hold both expense keys but still cannot change the
    # Administrator-owned threshold.
    name = f"clerk_{_suffix().lower()}"
    _uid, token = _user_with_role(name, permissions=["expense:read", "expense:write"])
    client.cookies.set("session", token)
    try:
        assert client.get("/api/expenses").status_code == 200
        denied = client.put("/api/expenses/settings", json={
            "approval_enabled": True, "approval_threshold": "1",
            "tracked_from": "2020-01-01"})
        assert denied.status_code == 403, denied.text
        assert "Administrator" in denied.json()["detail"]
    finally:
        client.as_user("admin")


# ----------------------------------------------------------------- entries
def test_entry_amounts_gst_and_validation(client):
    admin = client.as_user("admin")
    _set_settings(admin, False)
    head = _head(admin)
    creditable = _entry(admin, head["id"], "1000.00", gst_amount="180.00",
                        gst_creditable=True, reference="INV-1", note=" rent ")
    assert creditable["status"] == "approved"
    assert creditable["number"].startswith("EXP-")
    assert creditable["gst_creditable"] is True
    assert Decimal(creditable["total"]) == Decimal("1180.00")
    assert Decimal(creditable["deductible_amount"]) == Decimal("1000.00")
    assert creditable["note"] == "rent"

    not_creditable = _entry(admin, head["id"], "500.00", gst_amount="90.00",
                            gst_creditable=False)
    assert not_creditable["gst_creditable"] is False
    assert Decimal(not_creditable["deductible_amount"]) == Decimal("590.00")

    assert admin.post("/api/expenses", json={
        "head_id": head["id"],
        "entry_date": (date.today() + timedelta(days=1)).isoformat(),
        "amount": "10.00"}).status_code == 422
    assert admin.post("/api/expenses", json={
        "head_id": head["id"], "entry_date": date.today().isoformat(),
        "amount": "0"}).status_code == 422
    assert admin.post("/api/expenses", json={
        "head_id": head["id"], "entry_date": date.today().isoformat(),
        "amount": "10.00", "gst_amount": "-1"}).status_code == 422
    assert admin.post("/api/expenses", json={
        "head_id": head["id"], "entry_date": date.today().isoformat(),
        "amount": "10.00", "mode": "crypto"}).status_code == 422
    assert admin.post("/api/expenses", json={
        "head_id": 999999, "entry_date": date.today().isoformat(),
        "amount": "10.00"}).status_code == 404

    rows = admin.get("/api/expenses", params={"head_id": head["id"]}).json()
    assert {r["id"] for r in rows} == {creditable["id"], not_creditable["id"]}
    assert _audit("expense.create", f"expense:{creditable['id']}")[0]["amount"] == "1000.00"


def test_reversal_keeps_the_amount_and_excludes_the_entry(client):
    admin = client.as_user("admin")
    _set_settings(admin, False)
    head = _head(admin)
    entry = _entry(admin, head["id"], "750.00")
    reversed_ = admin.post(f"/api/expenses/{entry['id']}/reverse",
                           json={"reason": "Duplicate booking"})
    assert reversed_.status_code == 200, reversed_.text
    body = reversed_.json()
    assert body["status"] == "reversed"
    assert body["reversal_reason"] == "Duplicate booking"
    assert body["reversed_by"] is not None and body["reversed_at"]
    assert Decimal(body["amount"]) == Decimal("750.00")

    again = admin.post(f"/api/expenses/{entry['id']}/reverse",
                       json={"reason": "Again"})
    assert again.status_code == 409
    assert _audit("expense.reverse", f"expense:{entry['id']}")[0]["reason"] == "Duplicate booking"

    _set_settings(admin, True, "100.00")
    pending = _entry(admin, head["id"], "150.00")
    assert pending["status"] == "pending_approval"
    refused = admin.post(f"/api/expenses/{pending['id']}/reverse",
                         json={"reason": "Not approved yet"})
    assert refused.status_code == 409


# ---------------------------------------------------------------- approval
def test_threshold_segregation_and_decision(client):
    admin = client.as_user("admin")
    # The switch is explicit: off means no entry is ever held, even at threshold 0.
    _set_settings(admin, False, "0.00")
    head = _head(admin)
    assert _entry(admin, head["id"], "0.01")["status"] == "approved"

    _set_settings(admin, True, "1000.00")
    below = _entry(admin, head["id"], "900.00")
    assert below["status"] == "approved"
    # The threshold compares the cash value: 900 + 200 GST is above 1000.
    above = _entry(admin, head["id"], "900.00", gst_amount="200.00")
    assert above["status"] == "pending_approval"
    assert above["approval_request_id"]

    queue = admin.get("/api/approvals", params={"request_type": "expense"}).json()
    row = next(a for a in queue if a["record_id"] == above["id"])
    assert row["request_type"] == "expense"
    assert row["document_number"] == above["number"]
    assert row["order_total"] == "1100.00"
    assert row["can_decide"] is False, "the creator cannot decide it"

    own = admin.post(f"/api/approvals/{row['id']}/decide",
                     json={"decision": "approve", "reason": "mine"})
    assert own.status_code == 403
    assert "Segregation" in own.json()["detail"]

    _approver_id, approver_token = _user_with_role(
        f"approver_{_suffix().lower()}", role_name="admin")
    client.cookies.set("session", approver_token)
    try:
        listed = client.get("/api/approvals", params={"request_type": "expense"}).json()
        approver_row = next(a for a in listed if a["record_id"] == above["id"])
        assert approver_row["can_decide"] is True
        decided = client.post(f"/api/approvals/{approver_row['id']}/decide",
                              json={"decision": "approve", "reason": "receipt checked"})
        assert decided.status_code == 200, decided.text
    finally:
        client.as_user("admin")

    approved = admin.get(f"/api/expenses/{above['id']}").json()
    assert approved["status"] == "approved"
    assert approved["approved_by"] is not None
    assert approved["approved_at"]
    changes = _audit("expense.approval", f"expense:{above['id']}")[0]
    assert changes["decision"] == "approve"

    rejected = _entry(admin, head["id"], "2000.00")
    assert rejected["status"] == "pending_approval"
    _approver_id, approver_token = _user_with_role(
        f"rejecter_{_suffix().lower()}", role_name="admin")
    client.cookies.set("session", approver_token)
    try:
        reason = client.post(
            f"/api/approvals/{rejected['approval_request_id']}/decide",
            json={"decision": "reject", "reason": "No invoice attached"})
        assert reason.status_code == 200, reason.text
    finally:
        client.as_user("admin")
    refused = admin.get(f"/api/expenses/{rejected['id']}").json()
    assert refused["status"] == "rejected"
    assert refused["approved_at"] is None


def test_creator_cannot_approve_and_reversal_needs_the_permission(client):
    admin = client.as_user("admin")
    _set_settings(admin, True, "100.00")
    head = _head(admin)

    maker = f"maker_{_suffix().lower()}"
    _maker_id, maker_token = _user_with_role(
        maker, permissions=["expense:read", "expense:write",
                            "approval:read", "approval:decide"])
    client.cookies.set("session", maker_token)
    created = _entry(client, head["id"], "500.00")
    assert created["status"] == "pending_approval"
    row = next(a for a in client.get(
        "/api/approvals", params={"request_type": "expense"}).json()
        if a["record_id"] == created["id"])
    assert row["can_decide"] is False
    own = client.post(f"/api/approvals/{row['id']}/decide",
                      json={"decision": "approve", "reason": "my own entry"})
    assert own.status_code == 403
    assert "Segregation" in own.json()["detail"]

    # With the approval switch off and expense:write, the same creator may
    # reverse their own entry: reversal is a correction, not a decision.
    client.as_user("admin")
    _set_settings(admin, False)
    client.cookies.set("session", maker_token)
    approved = _entry(client, head["id"], "500.00")
    own_reversal = client.post(f"/api/expenses/{approved['id']}/reverse",
                               json={"reason": "Wrong head"})
    assert own_reversal.status_code == 200, own_reversal.text

    reader = f"reader_{_suffix().lower()}"
    _reader_id, reader_token = _user_with_role(reader, permissions=["expense:read"])
    client.cookies.set("session", reader_token)
    try:
        denied = client.post(f"/api/expenses/{approved['id']}/reverse",
                             json={"reason": "Not mine, not allowed"})
        assert denied.status_code == 403
        assert client.get(f"/api/expenses/{approved['id']}").status_code == 200
    finally:
        client.as_user("admin")


# -------------------------------------------------------------- attachments
def test_receipt_upload_validation_download_and_permissions(client):
    admin = client.as_user("admin")
    _set_settings(admin, False)
    head = _head(admin)
    entry = _entry(admin, head["id"], "120.00")

    uploaded = admin.post(f"/api/expenses/{entry['id']}/attachment",
                          files={"file": ("../../evil.png", _png(), "image/png")})
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["attachment"] is True
    assert body["attachment_url"] == f"/api/expenses/{entry['id']}/attachment"

    downloaded = admin.get(f"/api/expenses/{entry['id']}/attachment")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert downloaded.content == _png()

    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    replaced = admin.post(f"/api/expenses/{entry['id']}/attachment",
                          files={"file": ("receipt.pdf", pdf, "application/pdf")})
    assert replaced.status_code == 200, replaced.text
    assert admin.get(f"/api/expenses/{entry['id']}/attachment").content == pdf

    bad = admin.post(f"/api/expenses/{entry['id']}/attachment",
                     files={"file": ("receipt.png", b"not an image", "image/png")})
    assert bad.status_code == 422
    empty = admin.post(f"/api/expenses/{entry['id']}/attachment",
                       files={"file": ("receipt.png", b"", "image/png")})
    assert empty.status_code == 422
    huge = admin.post(f"/api/expenses/{entry['id']}/attachment",
                      files={"file": ("big.png", b"x" * 5_000_001, "image/png")})
    assert huge.status_code == 413

    assert client.as_user("sales").get(
        f"/api/expenses/{entry['id']}/attachment").status_code == 403
    client.as_user("admin")

    reversed_ = admin.post(f"/api/expenses/{entry['id']}/reverse",
                           json={"reason": "Wrong receipt"})
    assert reversed_.status_code == 200
    closed = admin.post(f"/api/expenses/{entry['id']}/attachment",
                        files={"file": ("receipt.png", _png(), "image/png")})
    assert closed.status_code == 409
    assert _audit("expense.attachment", f"expense:{entry['id']}")


def test_create_and_reverse_are_refused_while_the_accounting_month_is_locked(client):
    admin = client.as_user("admin")
    _set_settings(admin, False)
    head = _head(admin)
    january, february = date(2020, 1, 15), date(2020, 2, 10)

    def lock(day):
        res = admin.post("/api/accounts/period-locks", json={
            "year": day.year, "month": day.month, "reason": "month closed for audit"})
        assert res.status_code == 201, res.text
        return res.json()

    january_lock = lock(january)

    refused = admin.post("/api/expenses", json={
        "head_id": head["id"], "entry_date": january.isoformat(),
        "amount": "100.00", "mode": "bank"})
    assert refused.status_code == 423, refused.text
    assert "2020-01" in refused.json()["detail"]
    assert "locked" in refused.json()["detail"]

    february_entry = _entry(admin, head["id"], "100.00",
                            entry_date=february.isoformat())
    assert february_entry["status"] == "approved"
    february_lock = lock(february)
    reverse = admin.post(f"/api/expenses/{february_entry['id']}/reverse",
                         json={"reason": "wrong head"})
    assert reverse.status_code == 423, reverse.text
    assert "2020-02" in reverse.json()["detail"]

    with SessionLocal() as db:
        stored = db.get(Expense, february_entry["id"])
        assert stored.status == "approved" and stored.reversed_at is None
        assert db.scalar(select(Expense).where(Expense.entry_date == january)) is None
    assert _audit("expense.reverse", f"expense:{february_entry['id']}") == []

    unlocked = admin.post(f"/api/accounts/period-locks/{january_lock['id']}/unlock",
                          json={"reason": "reopened for a correction"})
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["active"] is False
    allowed = _entry(admin, head["id"], "120.00", entry_date=january.isoformat())
    assert allowed["status"] == "approved"

    unlocked = admin.post(f"/api/accounts/period-locks/{february_lock['id']}/unlock",
                          json={"reason": "reopened for a correction"})
    assert unlocked.status_code == 200, unlocked.text
    reversed_ok = admin.post(f"/api/expenses/{february_entry['id']}/reverse",
                             json={"reason": "wrong head"})
    assert reversed_ok.status_code == 200, reversed_ok.text
    assert reversed_ok.json()["status"] == "reversed"


def test_expense_api_is_owned_by_the_accounting_feature_switch():
    from app.core.features import feature_for_path
    assert feature_for_path("/api/expenses") == "accounts"
    assert feature_for_path("/api/expenses/12/attachment") == "accounts"
