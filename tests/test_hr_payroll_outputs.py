"""Payroll outputs: statutory summaries, bank file, reconciliation and self-service
payslips.

Each test uses its own far-future month so the shared suite database never
collides with the payroll period exercised in test_hr.py. The two employees are
the sales and inventory test logins: earlier HR tests never touch their exit
dates, so they are still on the payroll when these periods are prepared.
Statutory amounts are the ones configured on the structure lines; the test
asserts those, not any statutory rate the application might appear to know.
"""
from decimal import Decimal

from sqlalchemy import select

STATUTORY_MONTH = (2035, 6)
BANK_MONTH = (2035, 7)
RECON_MONTH = (2035, 8)
SELF_MONTH = (2035, 9)
EFFECTIVE_FROM = "2035-01-01"

# BASIC 20000, PF 12% of basic, ESI 0.75% of gross, TDS 5% of gross, other 50.
SALES_NET = Decimal("16400.00")
INVENTORY_NET = Decimal("10000.00")


def _components(client):
    return {c["code"]: c for c in client.as_user("admin").get("/api/hr/salary/components").json()}


def _structure(client, employee_id, lines):
    r = client.as_user("admin").post("/api/hr/salary/structures", json={
        "employee_id": employee_id, "effective_from": EFFECTIVE_FROM, "lines": lines})
    assert r.status_code == 201, r.text


def _period(client, year, month):
    admin = client.as_user("admin")
    created = admin.post("/api/hr/payroll/periods", json={"year": year, "month": month})
    if created.status_code == 201:
        period_id = created.json()["id"]
    else:
        assert created.status_code == 409, created.text
        period_id = next(p["id"] for p in admin.get("/api/hr/payroll/periods").json()
                         if p["year"] == year and p["month"] == month)
    prepared = admin.post(f"/api/hr/payroll/periods/{period_id}/prepare")
    assert prepared.status_code == 200, prepared.text
    return period_id


def _second_admin_token(client):
    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Employee, Role

    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == "admin"))
        user = db.scalar(select(User).where(User.username == "t_admin_pay"))
        if not user:
            emp = Employee(code="T_ADMIN_PAY", full_name="Payroll approver", status="active")
            db.add(emp)
            db.flush()
            user = User(username="t_admin_pay", username_key="t_admin_pay",
                        password_hash="x", role="admin", role_id=role.id,
                        employee_id=emp.id)
            db.add(user)
            db.commit()
        return make_token(user.id, user.token_version or 1)


def _approve(client, period_id):
    admin = client.as_user("admin")
    submitted = admin.post(f"/api/hr/payroll/periods/{period_id}/submit")
    assert submitted.status_code == 200, submitted.text
    client.cookies.set("session", _second_admin_token(client))
    decided = client.post(f"/api/approvals/{submitted.json()['approval_id']}/decide",
                          json={"decision": "approve", "reason": "Checked the register"})
    assert decided.status_code == 200, decided.text
    client.as_user("admin")


def _setup_structures(client):
    comps = _components(client)
    paid_id = client.employee_ids["sales"]
    unbanked_id = client.employee_ids["inventory"]
    _structure(client, paid_id, [
        {"component_id": comps["BASIC"]["id"], "amount": "20000"},
        {"component_id": comps["PF"]["id"], "percent": "12"},
        {"component_id": comps["ESI"]["id"], "percent": "0.75"},
        {"component_id": comps["TDS"]["id"], "percent": "5"},
        {"component_id": comps["OTHER_DED"]["id"], "amount": "50"},
    ])
    _structure(client, unbanked_id, [
        {"component_id": comps["BASIC"]["id"], "amount": "10000"},
    ])
    patched = client.as_user("admin").patch(
        f"/api/hr/employees/{paid_id}",
        json={"bank_name": "HDFC Bank", "bank_account_no": "50100123456789",
              "bank_ifsc": "HDFC0001234"})
    assert patched.status_code == 200, patched.text


_SET_UP = False


def _setup_once(client):
    global _SET_UP
    if not _SET_UP:
        _setup_structures(client)
        _SET_UP = True


def test_statutory_summary_is_built_from_configured_components(client, world):
    _setup_once(client)
    period_id = _period(client, *STATUTORY_MONTH)

    officer = client.as_user("payroll")
    summary = officer.get(f"/api/hr/payroll/periods/{period_id}/statutory")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    heads = {h["head"]: h for h in body["heads"]}
    assert {"pf", "esi", "pt", "tds"} == set(heads)
    assert Decimal(heads["pf"]["amount"]) == Decimal("2400.00")      # 12% of basic
    assert Decimal(heads["esi"]["amount"]) == Decimal("150.00")      # 0.75% of gross
    assert Decimal(heads["tds"]["amount"]) == Decimal("1000.00")     # 5% of gross
    assert Decimal(heads["pt"]["amount"]) == Decimal("0.00")
    assert heads["pf"]["configured"] is True and heads["pf"]["components"] == ["PF"]
    assert heads["pf"]["employees"] == 1
    assert body["gaps"] == []
    assert Decimal(body["other_deductions"]["amount"]) == Decimal("50.00")
    assert Decimal(body["deductions"]) == Decimal("3600.00")
    # Totals come from the register, whatever employees it contains.
    assert Decimal(body["net"]) == Decimal(body["gross"]) - Decimal(body["deductions"])

    assert client.as_user("staff").get(
        f"/api/hr/payroll/periods/{period_id}/statutory").status_code == 403


def test_unconfigured_statutory_head_is_reported_as_a_gap(client, world):
    _setup_once(client)
    comps = _components(client)
    tds_id = comps["TDS"]["id"]
    admin = client.as_user("admin")

    cleared = admin.patch(f"/api/hr/salary/components/{tds_id}",
                          json={"statutory_head": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["statutory_head"] is None

    period_id = _period(client, *STATUTORY_MONTH)
    body = client.as_user("payroll").get(
        f"/api/hr/payroll/periods/{period_id}/statutory").json()
    heads = {h["head"]: h for h in body["heads"]}
    assert heads["tds"]["configured"] is False
    assert Decimal(body["unmapped_statutory"]["amount"]) == Decimal("1000.00")
    assert any("Tax deducted at source" in g for g in body["gaps"])

    # The rules endpoint refuses configurations that cannot be summarised.
    admin = client.as_user("admin")
    assert admin.patch(f"/api/hr/salary/components/{comps['BASIC']['id']}",
                       json={"statutory_head": "pf"}).status_code == 422
    assert admin.patch(f"/api/hr/salary/components/{tds_id}",
                       json={"statutory_head": "tds", "statutory": False}).status_code == 422
    assert admin.patch(f"/api/hr/salary/components/{tds_id}", json={}).status_code == 422
    # The payroll officer may prepare payroll but cannot redefine a rule.
    assert client.as_user("payroll").patch(
        f"/api/hr/salary/components/{tds_id}", json={"name": "Tax"}).status_code == 403

    restored = client.as_user("admin").patch(f"/api/hr/salary/components/{tds_id}",
                                             json={"statutory_head": "tds"})
    assert restored.status_code == 200 and restored.json()["statutory_head"] == "tds"


def test_bank_file_needs_approval_confidential_rights_and_masks_the_preview(client, world):
    _setup_once(client)
    period_id = _period(client, *BANK_MONTH)

    # Not approved yet: no bank file can be generated.
    assert client.as_user("payroll").get(
        f"/api/hr/payroll/periods/{period_id}/bank-file").status_code == 409
    _approve(client, period_id)

    officer = client.as_user("payroll")
    csv_response = officer.get(f"/api/hr/payroll/periods/{period_id}/bank-file")
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "bank-file-2035-07.csv" in csv_response.headers["content-disposition"]
    lines = csv_response.text.strip().splitlines()
    assert lines[0].split(",") == ["employee_code", "beneficiary_name", "bank_name", "ifsc",
                                   "account_number", "amount", "narration", "reference"]
    assert len(lines) == 2                      # one payable row; the rest are held back
    assert "50100123456789" in lines[1]
    assert "16400.00" in lines[1]

    preview = officer.get(f"/api/hr/payroll/periods/{period_id}/bank-file",
                          params={"format": "json"}).json()
    assert preview["count"] == 1
    assert preview["rows"][0]["account_masked"].endswith("6789")
    assert preview["rows"][0]["account_masked"] != "50100123456789"
    assert preview["skipped"][0]["reason"] == "Bank account or IFSC is not recorded"
    assert "account" not in preview["skipped"][0]
    assert Decimal(preview["total"]) == SALES_NET

    # Confidential data follows the confidential right, not general HR access.
    assert client.as_user("staff").get(
        f"/api/hr/payroll/periods/{period_id}/bank-file").status_code == 403


def test_reconciliation_ties_register_lines_and_bank_file(client, world):
    _setup_once(client)
    period_id = _period(client, *RECON_MONTH)
    _approve(client, period_id)

    body = client.as_user("payroll").get(
        f"/api/hr/payroll/periods/{period_id}/reconciliation").json()
    assert body["reconciled"] is True, body["checks"]
    assert all(c["ok"] for c in body["checks"])
    keys = {c["key"] for c in body["checks"]}
    assert keys == {"entries", "gross", "deductions", "net", "bank_file", "statutory"}
    assert Decimal(body["bank_file"]["total"]) == SALES_NET
    assert Decimal(body["bank_file"]["total"]) + Decimal(body["bank_file"]["held_back"]) \
        == Decimal(body["net"])
    assert Decimal(body["bank_file"]["held_back"]) >= INVENTORY_NET
    assert body["bank_file"]["skipped"] >= 1
    assert any("not recorded" in g for g in body["gaps"])
    assert "GAP-A01" in body["accounts_note"]
    assert client.as_user("staff").get(
        f"/api/hr/payroll/periods/{period_id}/reconciliation").status_code == 403


def test_self_service_payslips_are_own_and_only_after_release(client, world):
    _setup_once(client)
    period_id = _period(client, *SELF_MONTH)
    _approve(client, period_id)

    # Approved is not released: the employee sees nothing yet.
    assert client.as_user("sales").get("/api/hr/me/payslips").json() == []

    register = client.as_user("admin").get(
        f"/api/hr/payroll/periods/{period_id}").json()["entries"]
    own = next(e for e in register if e["employee_id"] == client.employee_ids["sales"])
    other = next(e for e in register if e["employee_id"] == client.employee_ids["inventory"])
    assert client.as_user("sales").get(
        f"/api/hr/me/payslips/{own['id']}").status_code == 409

    assert client.as_user("admin").post(
        f"/api/hr/payroll/periods/{period_id}/process").json()["status"] == "processed"

    sales = client.as_user("sales")
    slips = sales.get("/api/hr/me/payslips").json()
    assert len(slips) == 1
    assert slips[0]["entry_id"] == own["id"]
    assert slips[0]["year"] == SELF_MONTH[0] and slips[0]["month"] == SELF_MONTH[1]
    assert Decimal(slips[0]["net"]) == SALES_NET

    pdf = sales.get(f"/api/hr/me/payslips/{own['id']}")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    # Another employee's payslip is not reachable, and an unknown id is not either.
    assert sales.get(f"/api/hr/me/payslips/{other['id']}").status_code == 404
    assert sales.get("/api/hr/me/payslips/999999").status_code == 404
