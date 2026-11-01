"""Attendance operations: bulk marking, monthly calendar and period locks.

Months used here are far in the future so the rows this file writes cannot
change the counts other HR tests assert for the current month.
"""
from calendar import monthrange
from uuid import uuid4


def _employee(client, name="Attendance subject"):
    resp = client.post("/api/hr/employees", json={
        "code": f"ATT{uuid4().hex[:5].upper()}", "full_name": f"{name} {uuid4().hex[:4]}"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_bulk_marking_skips_weekends_and_holidays(client):
    emp_id = _employee(client)

    # 1 March 2032 is a Monday; the default shift treats Sat/Sun as off.
    body = {"employee_ids": [emp_id], "date_from": "2032-03-01", "date_to": "2032-03-07",
            "status": "present", "remarks": "Bulk opening attendance"}
    first = client.as_user("hr_manager").post("/api/hr/attendance/bulk", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["employees"] == 1
    assert first.json()["created"] == 5
    assert first.json()["updated"] == 0
    assert first.json()["skipped"] == 2

    holiday = client.as_user("admin").post("/api/hr/holidays", json={
        "date": "2032-03-03", "name": f"Holiday {uuid4().hex[:4]}"})
    assert holiday.status_code == 201, holiday.text

    body.update({"status": "late", "remarks": "Bulk correction after holiday was declared"})
    second = client.as_user("admin").post("/api/hr/attendance/bulk", json=body)
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0
    assert second.json()["updated"] == 4
    assert second.json()["skipped"] == 3

    listed = client.as_user("admin").get("/api/hr/attendance", params={
        "employee_id": emp_id, "from_date": "2032-03-01", "to_date": "2032-03-07"})
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert {r["date"] for r in rows} == {"2032-03-01", "2032-03-02", "2032-03-03",
                                         "2032-03-04", "2032-03-05"}
    by_date = {r["date"]: r["status"] for r in rows}
    # The second run skipped the new holiday: that day keeps the first mark
    # rather than being silently rewritten or deleted.
    assert by_date["2032-03-03"] == "present"
    assert {d: s for d, s in by_date.items() if d != "2032-03-03"} == {
        "2032-03-01": "late", "2032-03-02": "late", "2032-03-04": "late",
        "2032-03-05": "late"}
    assert all(r["source"] == "manual" for r in rows)


def test_bulk_inputs_are_validated(client):
    emp_id = _employee(client)
    base = {"employee_ids": [emp_id], "date_from": "2032-05-01", "date_to": "2032-05-02",
            "status": "present", "remarks": "Validation check"}
    admin = client.as_user("admin")
    assert admin.post("/api/hr/attendance/bulk", json={**base, "date_to": "2032-04-30"}
                      ).status_code == 422
    assert admin.post("/api/hr/attendance/bulk", json={**base, "date_to": "2032-09-30"}
                      ).status_code == 422
    assert admin.post("/api/hr/attendance/bulk", json={**base, "employee_ids": [emp_id] * 2}
                      ).status_code == 422
    assert admin.post("/api/hr/attendance/bulk", json={**base, "status": "nonsense"}
                      ).status_code == 422


def test_bulk_marking_stays_inside_the_reporting_chain(client):
    inside = _employee(client, "Inside chain")
    outside = _employee(client, "Outside chain")
    linked = client.as_user("admin").patch(
        f"/api/hr/employees/{inside}", json={"manager_id": client.employee_ids["manager"]})
    assert linked.status_code == 200, linked.text

    body = {"employee_ids": [inside], "date_from": "2032-06-01", "date_to": "2032-06-02",
            "status": "present", "remarks": "Team attendance"}
    try:
        assert client.as_user("manager").post("/api/hr/attendance/bulk",
                                              json=body).status_code == 200
        refused = client.as_user("manager").post(
            "/api/hr/attendance/bulk", json={**body, "employee_ids": [outside]})
        assert refused.status_code == 403
        assert client.as_user("staff").post(
            "/api/hr/attendance/bulk", json=body).status_code == 403
    finally:
        # Other tests assert the manager's chain is exactly their own team.
        client.as_user("admin").patch(f"/api/hr/employees/{inside}",
                                      json={"manager_id": None})


def test_monthly_view_counts_days_and_leaves_gaps_empty(client):
    emp_id = _employee(client)
    manual = client.as_user("admin").post("/api/hr/attendance/manual", json={
        "employee_id": emp_id, "date": "2032-04-01", "status": "present",
        "check_in": "2032-04-01T09:15:00+05:30", "check_out": "2032-04-01T18:30:00+05:30",
        "overtime_minutes": 45, "remarks": "Monthly summary fixture"})
    assert manual.status_code == 201, manual.text
    bulk = client.as_user("admin").post("/api/hr/attendance/bulk", json={
        "employee_ids": [emp_id], "date_from": "2032-04-02", "date_to": "2032-04-05",
        "status": "late", "remarks": "Monthly summary fixture"})
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["updated"] + bulk.json()["created"] == 2

    out = client.as_user("admin").get("/api/hr/attendance/monthly", params={
        "year": 2032, "month": 4, "employee_id": emp_id}).json()
    assert len(out["days"]) == monthrange(2032, 4)[1]
    row = next(e for e in out["employees"] if e["employee_id"] == emp_id)
    assert row["summary"]["present_days"] == 3
    assert row["summary"]["missing_days"] == monthrange(2032, 4)[1] - 3
    assert row["summary"]["worked_minutes"] == 555
    assert row["summary"]["overtime_minutes"] == 45
    gap = next(d for d in row["calendar"] if d["date"] == "2032-04-10")
    assert gap["status"] is None and "check_in" not in gap

    self_view = client.as_user("staff").get("/api/hr/attendance/monthly",
                                            params={"year": 2032, "month": 4})
    assert self_view.status_code == 200
    assert [e["employee_id"] for e in self_view.json()["employees"]] == \
        [client.employee_ids["staff"]]
    assert self_view.json()["weekdays"][0] == 3  # 1 April 2032 is a Thursday
    assert client.as_user("staff").get(
        "/api/hr/attendance/monthly",
        params={"year": 2032, "month": 4, "employee_id": emp_id}).status_code == 403
    assert client.as_user("admin").get("/api/hr/attendance/monthly",
                                       params={"year": 2032, "month": 13}).status_code == 422


def test_lock_blocks_edits_until_the_administrator_reopens_with_a_reason(client):
    emp_id = _employee(client)
    entry = {"employee_id": emp_id, "date": "2033-01-05", "status": "present",
             "remarks": "Locked period check"}

    locked = client.as_user("hr_manager").post("/api/hr/period-locks", json={
        "scope": "attendance", "year": 2033, "month": 1,
        "reason": "January payroll settled"})
    assert locked.status_code == 201, locked.text
    lock_id = locked.json()["id"]
    assert locked.json()["active"] is True
    assert "password" not in locked.text.lower()

    again = client.as_user("hr_manager").post("/api/hr/period-locks", json={
        "scope": "attendance", "year": 2033, "month": 1, "reason": "Second attempt"})
    assert again.status_code == 409

    blocked = client.as_user("hr_manager").post("/api/hr/attendance/manual", json=entry)
    assert blocked.status_code == 423
    assert "locked" in blocked.json()["detail"].lower()

    manager_override = client.as_user("hr_manager").post(
        "/api/hr/attendance/manual",
        json={**entry, "override_reason": "Manager trying to reopen the month"})
    assert manager_override.status_code == 403

    assert client.as_user("admin").post(
        "/api/hr/attendance/manual", json=entry).status_code == 423
    override = client.as_user("admin").post("/api/hr/attendance/manual", json={
        **entry, "override_reason": "Employee produced a corrected gate record"})
    assert override.status_code == 201, override.text

    from app.core.db import SessionLocal
    from app.models.core import AuditLog
    from sqlalchemy import select
    with SessionLocal() as db:
        row = db.scalars(select(AuditLog).where(
            AuditLog.action == "hr.attendance.lock_override").order_by(
            AuditLog.id.desc())).first()
        assert row is not None
        assert row.actor_id == client.ids["admin"]
        assert row.changes["reason"] == "Employee produced a corrected gate record"

    # Payroll lock metadata follows payroll rights; attendance locks do not.
    payroll_lock = client.as_user("payroll").post("/api/hr/period-locks", json={
        "scope": "payroll", "year": 2033, "month": 1, "reason": "Payroll closed"})
    assert payroll_lock.status_code == 201, payroll_lock.text
    staff_locks = client.as_user("staff").get("/api/hr/period-locks").json()
    assert {l["scope"] for l in staff_locks} == {"attendance"}
    hr_locks = client.as_user("hr_manager").get("/api/hr/period-locks").json()
    assert {"attendance", "payroll"} <= {l["scope"] for l in hr_locks}

    assert client.as_user("staff").post("/api/hr/period-locks", json={
        "scope": "attendance", "year": 2033, "month": 2, "reason": "No right"}).status_code == 403
    assert client.as_user("hr_manager").post(f"/api/hr/period-locks/{lock_id}/unlock",
                                             json={"reason": "Let me in"}).status_code == 403
    assert client.as_user("admin").post(f"/api/hr/period-locks/{lock_id}/unlock",
                                        json={"reason": "x"}).status_code == 422
    reopened = client.as_user("admin").post(
        f"/api/hr/period-locks/{lock_id}/unlock",
        json={"reason": "Correction requested by the auditor"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["active"] is False
    assert reopened.json()["unlock_reason"] == "Correction requested by the auditor"
    assert client.as_user("admin").post(f"/api/hr/period-locks/{lock_id}/unlock",
                                        json={"reason": "Already open"}).status_code == 409

    after = client.as_user("admin").post("/api/hr/attendance/manual",
                                         json={**entry, "status": "absent"})
    assert after.status_code == 201, after.text

    relocked = client.as_user("hr_manager").post("/api/hr/period-locks", json={
        "scope": "attendance", "year": 2033, "month": 1, "reason": "Re-closed after audit"})
    assert relocked.status_code == 201
    assert relocked.json()["id"] == lock_id
    assert relocked.json()["unlocked_by"] is None


def test_corrections_and_payroll_preparation_respect_locks(client):
    emp_id = _employee(client)
    created = client.as_user("admin").post("/api/hr/attendance/manual", json={
        "employee_id": emp_id, "date": "2033-03-04", "status": "present",
        "remarks": "Correction source row"})
    assert created.status_code == 201, created.text
    attendance_id = created.json()["id"]

    assert client.as_user("hr_manager").post("/api/hr/period-locks", json={
        "scope": "attendance", "year": 2033, "month": 3,
        "reason": "March closed"}).status_code == 201
    correction = {"new_status": "half_day", "reason": "Half day was granted"}
    locked = client.as_user("hr_manager").post(
        f"/api/hr/attendance/{attendance_id}/correction", json=correction)
    assert locked.status_code == 423

    locks = client.as_user("admin").get("/api/hr/period-locks",
                                        params={"scope": "attendance"}).json()
    march = next(l for l in locks if l["year"] == 2033 and l["month"] == 3)
    assert client.as_user("admin").post(
        f"/api/hr/period-locks/{march['id']}/unlock",
        json={"reason": "Half-day record must be corrected"}).status_code == 200
    requested = client.as_user("hr_manager").post(
        f"/api/hr/attendance/{attendance_id}/correction", json=correction)
    assert requested.status_code == 201, requested.text
    listed = client.as_user("admin").get("/api/hr/attendance", params={
        "employee_id": emp_id, "from_date": "2033-03-04",
        "to_date": "2033-03-04"})
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["status"] == "correction_pending"

    period = client.as_user("admin").post("/api/hr/payroll/periods",
                                          json={"year": 2033, "month": 3})
    assert period.status_code == 201, period.text
    period_id = period.json()["id"]
    assert client.as_user("payroll").post("/api/hr/period-locks", json={
        "scope": "payroll", "year": 2033, "month": 3,
        "reason": "March payroll closed"}).status_code == 201
    blocked = client.as_user("payroll").post(f"/api/hr/payroll/periods/{period_id}/prepare")
    assert blocked.status_code == 423

    payroll_locks = client.as_user("admin").get("/api/hr/period-locks",
                                                params={"scope": "payroll"}).json()
    march_payroll = next(l for l in payroll_locks
                         if l["year"] == 2033 and l["month"] == 3)
    assert client.as_user("admin").post(
        f"/api/hr/period-locks/{march_payroll['id']}/unlock",
        json={"reason": "Recalculate after the correction"}).status_code == 200
    prepared = client.as_user("payroll").post(
        f"/api/hr/payroll/periods/{period_id}/prepare")
    assert prepared.status_code == 200, prepared.text
