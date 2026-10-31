NEW_HR_REPORTS = ["hr_joining_exit", "hr_late_arrival", "hr_missing_punch",
                  "hr_leave_balance", "hr_payroll_deductions", "hr_approval_turnaround"]


def test_catalog_is_categorised_and_permission_filtered(client, world):
    admin = client.as_user("admin")
    catalog = admin.get("/api/reports")
    assert catalog.status_code == 200
    keys = {r["key"] for r in catalog.json()}
    assert {"hr_employee_master", "hr_attendance", "hr_leave", "hr_od",
            "hr_payroll", "hr_approvals"} <= keys
    assert set(NEW_HR_REPORTS) <= keys
    categories = {r["category"] for r in catalog.json()}
    assert {"Sales Reports", "Purchase Reports", "Inventory Reports",
            "GST & Tax Reports", "Receivables", "Payables", "Accounting & Finance",
            "Lead & Follow-up Reports", "Supplier & Distributor Reports",
            "Approval & Audit Reports", "Employee Reports", "Attendance Reports",
            "Leave and OD Reports", "Payroll Reports"} <= categories

    sales = client.as_user("sales")
    sales_keys = {r["key"] for r in sales.get("/api/reports").json()}
    assert "hr_employee_master" not in sales_keys
    assert sales.get("/api/reports/hr_employee_master").status_code == 403
    assert sales.get("/api/reports/hr_payroll").status_code == 403


def test_report_supports_paging_sorting_and_reconciliation(client, world):
    admin = client.as_user("admin")
    r = admin.get("/api/reports/hr_employee_master", params={
        "page": 1, "page_size": 1, "sort": "code", "direction": "asc"})
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["category"] == "Employee Reports"
    assert report["primary_table"] == "employees"
    table = report["tables"][0]
    assert table["total_rows"] >= 1
    assert len(table["rows"]) == 1
    assert table["page"] == 1
    assert table["page_size"] == 1
    assert isinstance(report["reconciled"], bool)


def test_each_hr_report_builds_and_reconciles(client, world):
    admin = client.as_user("admin")
    catalog = {r["key"]: r for r in admin.get("/api/reports").json()}
    for key in NEW_HR_REPORTS:
        assert catalog[key]["kind"] == "period"
        for params in ({}, {"from": "2026-01-01", "to": "2026-12-31"},
                       {"from": "2020-01-01", "to": "2020-12-31"}):
            r = admin.get(f"/api/reports/{key}", params=params)
            assert r.status_code == 200, (key, params, r.text)
            body = r.json()
            assert body["tables"] and body["tables"][0]["columns"]
            assert body["checks"], key
            assert body["reconciled"] is True, (key, params,
                                                [c for c in body["checks"] if not c["ok"]])
            assert body["primary_table"] == body["tables"][0]["key"]
        for fmt in ("csv", "xlsx", "pdf"):
            exp = admin.get(f"/api/reports/{key}/export", params={"format": fmt})
            assert exp.status_code == 200, (key, fmt, exp.text)
            assert exp.content



def test_hr_reports_narrow_by_employee_department_and_branch(client, world):
    from uuid import uuid4

    admin = client.as_user("admin")
    branch = admin.post("/api/hr/branches",
                        json={"code": f"FB{uuid4().hex[:4].upper()}", "name": "Filter branch"})
    assert branch.status_code == 201, branch.text
    branch_id = branch.json()["id"]
    code = f"FLT{uuid4().hex[:4].upper()}"
    created = admin.post("/api/hr/employees", json={
        "code": code, "full_name": "Filtered Employee", "department": "Filter Dept",
        "branch_id": branch_id, "joining_date": "2026-01-05"})
    assert created.status_code == 201, created.text
    employee_id = created.json()["id"]

    for key in ("hr_employee_master", "hr_joining_exit"):
        for params in ({"department": "filter dept"}, {"employee_id": employee_id},
                       {"branch_id": branch_id}):
            r = admin.get(f"/api/reports/{key}", params=params)
            assert r.status_code == 200, (key, params, r.text)
            body = r.json()
            assert {row["code"] for row in body["tables"][0]["rows"]} == {code}, (key, params)
            assert body["reconciled"] is True, (key, params)

    payroll = admin.get("/api/reports/hr_payroll",
                        params={"employee_id": client.employee_ids["payroll"]})
    assert payroll.status_code == 200, payroll.text
    assert payroll.json()["reconciled"] is True

    # The export is filtered by exactly the same conditions.
    csv = admin.get("/api/reports/hr_employee_master/export",
                    params={"format": "csv", "department": "filter dept"})
    assert csv.status_code == 200, csv.text
    text = csv.content.decode("utf-8-sig")
    assert code in text
    assert "T_SALES" not in text

    # The catalog advertises the filters, and a report that cannot use one refuses it.
    catalog = {r["key"]: r for r in admin.get("/api/reports").json()}
    assert catalog["hr_employee_master"]["filters"] == ["employee_id", "department", "branch_id"]
    assert catalog["stock"]["filters"] == []
    assert admin.get("/api/reports/stock",
                     params={"department": "filter dept"}).status_code == 422
    assert admin.get("/api/reports/hr_employee_master/export",
                     params={"format": "csv", "branch_id": "x"}).status_code == 422


def test_new_hr_reports_are_permission_checked(client, world):
    sales = client.as_user("sales")
    keys = {r["key"] for r in sales.get("/api/reports").json()}
    assert not set(NEW_HR_REPORTS) & keys
    for key in NEW_HR_REPORTS:
        assert sales.get(f"/api/reports/{key}").status_code == 403


def test_every_report_builds_and_exports_in_every_format(client, world):
    """No report may 500 because of an empty table, a partial totals row or a
    field that is not on its model."""
    admin = client.as_user("admin")
    created = admin.post("/api/purchase-orders", json={
        "supplier_id": world["supplier_id"],
        "lines": [{"sku": world["sku"], "qty": "2", "unit_cost": "45.50"}]})
    assert created.status_code == 201, created.text

    for entry in admin.get("/api/reports").json():
        key = entry["key"]
        report = admin.get(f"/api/reports/{key}")
        assert report.status_code == 200, (key, report.text)
        assert report.json()["tables"], key
        for fmt in ("csv", "xlsx", "pdf"):
            export = admin.get(f"/api/reports/{key}/export", params={"format": fmt})
            assert export.status_code == 200, (key, fmt, export.text)
            assert export.content


def test_empty_register_exports_an_explicit_empty_state(client, world):
    """A register with no rows says so, whether or not its columns are known."""
    from io import BytesIO

    from openpyxl import load_workbook

    admin = client.as_user("admin")
    # hr_od has no rows and no fixed columns; hr_attendance has fixed columns but
    # no rows in 1990. Both must carry the note in CSV and XLSX.
    for key, params in (("hr_od", {}),
                        ("hr_attendance", {"from": "1990-01-01", "to": "1990-01-02"})):
        csv = admin.get(f"/api/reports/{key}/export", params={**params, "format": "csv"})
        assert csv.status_code == 200, (key, csv.text)
        assert "No records for this period." in csv.content.decode("utf-8-sig"), key

        xlsx = admin.get(f"/api/reports/{key}/export", params={**params, "format": "xlsx"})
        assert xlsx.status_code == 200, (key, xlsx.text)
        wb = load_workbook(BytesIO(xlsx.content))
        values = [cell.value for ws in wb.worksheets
                  for row in ws.iter_rows() for cell in row]
        assert "No records for this period." in values, key


def test_export_is_permission_checked_and_audited(client, world):
    admin = client.as_user("admin")
    csv = admin.get("/api/reports/hr_leave/export", params={"format": "csv"})
    assert csv.status_code == 200, csv.text
    assert csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv.headers["content-disposition"]
    assert csv.content.startswith(b"\xef\xbb\xbf")

    xlsx = admin.get("/api/reports/hr_employee_master/export", params={"format": "xlsx"})
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"

    viewer = client.as_user("viewer")
    assert viewer.get("/api/reports/stock/export").status_code == 403

    # The export itself is in the audit trail.
    logs = admin.get("/api/audit", params={"action": "report.export"})
    if logs.status_code == 200:
        assert any(row.get("action") == "report.export" for row in logs.json())
