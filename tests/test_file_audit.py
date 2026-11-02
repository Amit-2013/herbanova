"""End-to-end audit of every file feature: CSV, Excel, PDF, photo upload, print.

These tests open the artefacts they receive rather than trusting a 200: CSV is
parsed, XLSX is loaded with openpyxl, PDFs are opened with pypdf and every page
must carry text. They also pin the refusal behaviour for empty, renamed,
corrupted, oversized and hostile input.
"""
import csv
import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import Distributor, User
from app.models.hr import PayrollEntry, PayrollEntryLine, PayrollPeriod
from app.models.users import Employee

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "var" / "audit"


def _save(name: str, content: bytes) -> Path:
    ART.mkdir(parents=True, exist_ok=True)
    path = ART / name
    path.write_bytes(content)
    return path


def _employee(client, **fields) -> dict:
    code = fields.pop("code", f"FA{uuid4().hex[:5].upper()}")
    r = client.as_user("admin").post("/api/hr/employees", json={
        "code": code, "full_name": "File Audit Person", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def _pdf(res, name: str) -> str:
    assert res.status_code == 200, (name, res.text[:300])
    assert res.headers["content-type"].startswith("application/pdf"), (name, res.headers)
    disposition = res.headers.get("content-disposition", "")
    assert disposition.startswith(("attachment;", "inline;")), (name, res.headers)
    assert res.content.startswith(b"%PDF-"), name
    assert len(res.content) > 800, (name, len(res.content))
    _save(name, res.content)
    reader = PdfReader(io.BytesIO(res.content))
    assert len(reader.pages) >= 1, name
    texts = [(page.extract_text() or "") for page in reader.pages]
    assert all(text.strip() for text in texts), (name, "blank page")
    assert "\ufffd" not in "".join(texts), (name, "missing-glyph marker in the text")
    # ff/fi/... as a single ligature glyph extracts as U+FB00-U+FB06 and breaks
    # search and copy-paste; every generator must emit plain letters instead.
    ligatures = {ch for ch in "".join(texts) if 0xFB00 <= ord(ch) <= 0xFB06}
    assert not ligatures, (name, "ligature glyphs in extracted text", ligatures)
    return "\n".join(texts)


def _fonts(pdf: bytes) -> set[str]:
    """The font names embedded in a PDF, as pypdf reports them."""
    reader = PdfReader(io.BytesIO(pdf))
    names: set[str] = set()
    for page in reader.pages:
        try:
            fonts = page["/Resources"]["/Font"].get_object()
        except KeyError:
            continue
        for ref in fonts.values():
            base = ref.get_object().get("/BaseFont", "")
            names.add(str(base).lstrip("/"))
    return names


def _reads(pdf_text: str, expected: str) -> bool:
    """True when the logical characters survive extraction.

    ReportLab writes shaped Devanagari as harfbuzz glyphs, so a conjunct may
    extract as a ligature code and a vowel sign may gain a space. Comparing
    with whitespace removed checks the letters really are in the file; the
    rendered look is proved separately by the raster probe.
    """
    return re.sub(r"\s+", "", expected) in re.sub(r"\s+", "", pdf_text)


def _invoice(client, world, qty="1", price="100.00") -> dict:
    sales = client.as_user("sales")
    order = sales.post("/api/sales-orders", json={
        "distributor_id": world["distributor_id"],
        "lines": [{"sku": world["sku"], "qty": qty, "unit_price": price}]})
    assert order.status_code == 201, order.text
    order = order.json()
    submitted = sales.post(f"/api/sales-orders/{order['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    if submitted.json()["status"] == "pending_approval":
        approval_id = submitted.json()["approval"]["id"]
        assert client.as_user("admin").post(
            f"/api/approvals/{approval_id}/decide",
            json={"decision": "approve", "reason": "file audit"}).status_code == 200
    dispatched = client.as_user("admin").post(
        f"/api/sales-orders/{order['id']}/dispatch",
        json={"warehouse_id": world["warehouse_id"]})
    assert dispatched.status_code == 201, dispatched.text
    return next(i for i in client.as_user("admin").get("/api/invoices").json()
                if i["sales_order_id"] == order["id"])


# ---------------------------------------------------------------- CSV export
def test_employee_csv_export_contract_and_import_round_trip(client, world):
    """Export, read it back, then import the same file: no loss, no duplicates."""
    emp = _employee(client, full_name="रमेश कुमार", department="Sales & Ops",
                    designation="Territory Manager", email="ramesh@example.invalid",
                    bank_account_no="50100123456789", bank_ifsc="HDFC0001234",
                    pan="ABCDE1234F")
    admin = client.as_user("admin")
    res = admin.get("/api/hr/employees/export.csv")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    assert "employees.csv" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf"), "CSV must carry a UTF-8 BOM for Excel"
    _save("employees.csv", res.content)

    text = res.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    row = next(r for r in rows if r["code"] == emp["code"])
    assert row["full_name"] == "रमेश कुमार"
    assert row["bank_account_no"] == "50100123456789"
    assert row["pan"] == "ABCDE1234F"

    before = len(admin.get("/api/hr/employees").json())
    again = admin.post("/api/hr/employees/import", json={
        "filename": "employees.csv", "csv_text": text, "commit": False})
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["valid_rows"] == 0, body
    assert body["error_rows"] == len(rows)
    assert any("already exists" in e["errors"][0] for e in body["errors"])

    committed = admin.post("/api/hr/employees/import", json={
        "filename": "employees.csv", "csv_text": text, "commit": True})
    assert committed.status_code == 200, committed.text
    assert committed.json()["valid_rows"] == 0
    assert committed.json()["batch_id"] is None
    assert len(admin.get("/api/hr/employees").json()) == before


def test_employee_export_neutralises_spreadsheet_formulas(client, world):
    """A name starting with =, +, - or @ must not run when Excel opens the file."""
    hostile = _employee(client, full_name='=HYPERLINK("http://evil.invalid","click")')
    plus = _employee(client, full_name="+SUM(1,1)")
    at = _employee(client, full_name="@cmd")
    admin = client.as_user("admin")
    res = admin.get("/api/hr/employees/export.csv")
    assert res.status_code == 200
    _save("employees-hostile.csv", res.content)
    rows = {r["code"]: r for r in csv.DictReader(
        io.StringIO(res.content.decode("utf-8-sig")))}
    for code in (hostile["code"], plus["code"], at["code"]):
        assert rows[code]["full_name"].startswith("'"), rows[code]
    # Re-importing the escaped file restores the original name rather than
    # creating a second employee whose name starts with an apostrophe.
    preview = admin.post("/api/hr/employees/import", json={
        "filename": "employees.csv", "csv_text": res.content.decode("utf-8-sig"),
        "commit": False})
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] == 0


def test_import_template_is_importable_and_headers_are_exact(client, world):
    admin = client.as_user("admin")
    res = admin.get("/api/hr/employees/import-template.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "employee-import-template.csv" in res.headers["content-disposition"]
    _save("employee-import-template.csv", res.content)
    text = res.content.decode("utf-8-sig")
    preview = admin.post("/api/hr/employees/import", json={
        "filename": "employee-import-template.csv", "csv_text": text, "commit": False})
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 1
    assert preview.json()["error_rows"] == 0


# ---------------------------------------------------------- import bad cases
def test_import_rejects_empty_wrong_and_hostile_files_clearly(client, world):
    admin = client.as_user("admin")

    empty = admin.post("/api/hr/employees/import", json={
        "filename": "empty.csv", "csv_text": "   \n\n", "commit": False})
    assert empty.status_code == 422, empty.text
    assert "empty" in empty.json()["detail"].lower()

    header_only = admin.post("/api/hr/employees/import", json={
        "filename": "h.csv", "csv_text": "code,full_name\n", "commit": False})
    assert header_only.status_code == 422, header_only.text

    missing_required = admin.post("/api/hr/employees/import", json={
        "filename": "m.csv", "csv_text": "code,department\nAB,Sales\n", "commit": False})
    assert missing_required.status_code == 422, missing_required.text
    assert "full_name" in missing_required.json()["detail"]

    unknown = admin.post("/api/hr/employees/import", json={
        "filename": "u.csv", "csv_text": "code,full_name,salary\nAB,Person,10\n",
        "commit": False})
    assert unknown.status_code == 422
    assert "salary" in unknown.json()["detail"]

    binary = admin.post("/api/hr/employees/import", json={
        "filename": "photo.csv", "csv_text": "\x89PNG\r\n\x1a\n\x00\x00\xff",
        "commit": False})
    assert binary.status_code == 422, binary.text

    oversized = admin.post("/api/hr/employees/import", json={
        "filename": "big.csv", "csv_text": "x" * 2_000_001, "commit": False})
    assert oversized.status_code == 413

    # A browser cannot be trusted to honour accept=".csv"; the server must not
    # care about the extension, only about the content.
    renamed_ok = admin.post("/api/hr/employees/import", json={
        "filename": "people.xlsx",
        "csv_text": "code,full_name\n" + f"RN{uuid4().hex[:5].upper()},Renamed But Valid\n",
        "commit": False})
    assert renamed_ok.status_code == 200
    assert renamed_ok.json()["valid_rows"] == 1

    hostile_name = admin.post("/api/hr/employees/import", json={
        "filename": "../../evil.csv",
        "csv_text": "code,full_name\n" + f"PT{uuid4().hex[:5].upper()},Traversal\n",
        "commit": False})
    assert hostile_name.status_code == 200


def test_import_skips_blank_rows_and_reports_duplicates(client, world):
    admin = client.as_user("admin")
    code = f"DP{uuid4().hex[:5].upper()}"
    text = ("code,full_name,joining_date\n"
            f"{code},First Person,2026-01-15\n"
            ",\n"
            "   ,   ,\n"
            f"{code},Second Person,2026-01-16\n"
            "BAD,X,not-a-date\n")
    preview = admin.post("/api/hr/employees/import", json={
        "filename": "dupes.csv", "csv_text": text, "commit": False})
    assert preview.status_code == 200
    body = preview.json()
    assert body["valid_rows"] == 1
    assert body["error_rows"] == 2
    joined = " ".join(" ".join(e["errors"]) for e in body["errors"])
    assert "appears twice" in joined and "YYYY-MM-DD" in joined

    committed = admin.post("/api/hr/employees/import", json={
        "filename": "dupes.csv", "csv_text": text, "commit": True})
    assert committed.status_code == 200
    assert committed.json()["batch_id"] is not None
    matches = [e for e in admin.get("/api/hr/employees").json() if e["code"] == code]
    assert len(matches) == 1, matches


def test_large_import_commits_every_valid_row_once(client, world):
    admin = client.as_user("admin")
    prefix = f"LG{uuid4().hex[:4].upper()}"
    lines = ["code,full_name,department"] + [
        f"{prefix}{i:04d},Bulk Person {i},Sales" for i in range(300)]
    preview = admin.post("/api/hr/employees/import", json={
        "filename": "bulk.csv", "csv_text": "\n".join(lines), "commit": False})
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 300, preview.json()
    committed = admin.post("/api/hr/employees/import", json={
        "filename": "bulk.csv", "csv_text": "\n".join(lines), "commit": True})
    assert committed.status_code == 200, committed.text
    assert committed.json()["valid_rows"] == 300
    codes = [e["code"] for e in admin.get("/api/hr/employees").json()
             if e["code"].startswith(prefix)]
    assert len(codes) == len(set(codes)) == 300


def test_failed_import_leaves_no_half_written_employee(client, world):
    admin = client.as_user("admin")
    before = len(admin.get("/api/hr/employees").json())
    code = f"RB{uuid4().hex[:5].upper()}"
    res = admin.post("/api/hr/employees/import", json={
        "filename": "broken.csv", "csv_text": f"code,full_name\n{code},\n",
        "commit": True})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["batch_id"] is None, body
    assert body["valid_rows"] == 0 and body["error_rows"] == 1
    after = admin.get("/api/hr/employees").json()
    assert len(after) == before
    assert not any(e["code"] == code for e in after)


# ------------------------------------------------------------------- Excel
def test_report_xlsx_is_a_real_workbook_with_numbers_not_formulas(client, world):
    admin = client.as_user("admin")
    catalog = admin.get("/api/reports").json()
    key = next(c["key"] for c in catalog if c["key"] == "sales")
    res = admin.get(f"/api/reports/{key}/export", params={"format": "xlsx"})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert res.headers["content-disposition"].endswith(f'.xlsx"')
    assert res.content.startswith(b"PK"), "an xlsx is a zip"
    _save(f"report-{key}.xlsx", res.content)

    wb = load_workbook(io.BytesIO(res.content))
    assert {"Reconciliation", "Notes"} <= set(wb.sheetnames)
    data_sheets = [s for s in wb.sheetnames if s not in ("Reconciliation", "Notes")]
    assert data_sheets
    for ws in wb.worksheets:
        assert ws.max_row >= 1
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f", (ws.title, cell.coordinate)
    # Every data sheet with columns has a frozen header row and a bold header.
    # A register with no columns at all carries a "no records" note instead.
    from app.services.exports import EMPTY_NOTE
    for name in data_sheets:
        ws = wb[name]
        if ws.cell(row=1, column=1).value == EMPTY_NOTE:
            continue
        assert ws.freeze_panes == "A2"
        assert ws.cell(row=1, column=1).font.bold


def test_hr_payroll_xlsx_is_the_payroll_register_with_numeric_cells(client, world):
    """The payroll export must be payroll: named headers, the employee's own row,
    and figures a spreadsheet can add up (not numbers stored as text)."""
    emp = _employee(client, full_name="Payroll Export Person", department="Payroll QA")
    with SessionLocal() as db:
        period = PayrollPeriod(year=2047, month=4, status="approved")
        period.entries.append(PayrollEntry(
            employee_id=emp["id"], working_days=Decimal("26.0"),
            payable_days=Decimal("26.0"), present_days=Decimal("25.0"),
            paid_leave_days=Decimal("1.0"), lop_days=Decimal("0.0"),
            gross=Decimal("62000.00"), deductions=Decimal("7000.00"),
            net=Decimal("55000.00"), status="approved"))
        db.add(period)
        db.commit()

    admin = client.as_user("admin")
    params = {"format": "xlsx", "employee_id": emp["id"],
              "from": "2047-04-01", "to": "2047-04-30"}
    res = admin.get("/api/reports/hr_payroll/export", params=params)
    assert res.status_code == 200, res.text
    _save("hr-payroll-export.xlsx", res.content)

    # The JSON the screen uses carries the same kinds, so money is formatted
    # and right-aligned there too.
    data = admin.get("/api/reports/hr_payroll",
                     params={k: v for k, v in params.items() if k != "format"}).json()
    kinds = {c["key"]: c["type"] for c in data["tables"][0]["columns"]}
    assert kinds["gross"] == "money" and kinds["year"] == "int"
    assert kinds["working_days"] == "qty"

    wb = load_workbook(io.BytesIO(res.content))
    assert wb.sheetnames == ["Payroll Register", "Reconciliation", "Notes"]
    ws = wb["Payroll Register"]
    headers = [c.value for c in ws[1]]
    assert headers == [
        "Entry ID", "Period ID", "Year", "Month", "Employee ID",
        "Employee code", "Name", "Department", "Branch ID",
        "Working days", "Payable days", "Present days", "Paid leave days",
        "LOP days", "Gross (₹)", "Deductions (₹)", "Net (₹)", "Status",
    ]
    assert ws.max_row == 2, "the employee filter must leave exactly the seeded row"
    row = dict(zip(headers, ws[2]))
    assert row["Employee code"].value == emp["code"]
    assert row["Name"].value == "Payroll Export Person"
    assert row["Department"].value == "Payroll QA"
    for header, expected in (("Year", 2047), ("Month", 4), ("Working days", 26),
                             ("Gross (₹)", 62000), ("Deductions (₹)", 7000),
                             ("Net (₹)", 55000)):
        cell = row[header]
        assert cell.data_type == "n", (header, cell.data_type, cell.value)
        assert float(cell.value) == float(expected), (header, cell.value)
    assert row["Gross (₹)"].number_format == "#,##0.00"
    assert row["Working days"].number_format == "#,##0.###"
    assert row["Status"].data_type == "s"

    recon = wb["Reconciliation"]
    results = [recon.cell(row=i, column=6).value for i in range(2, recon.max_row + 1)]
    assert results and all(r == "Agrees" for r in results), results
    notes = {wb["Notes"].cell(row=i, column=1).value: wb["Notes"].cell(row=i, column=2).value
             for i in range(1, wb["Notes"].max_row + 1)}
    assert notes["Report"] == "Payroll Register"
    assert notes["Reconciliation"].startswith("All ")


# --------------------------------------------------------------------- PDFs
def _seed_payslip(client, employee_id: int) -> int:
    with SessionLocal() as db:
        period = PayrollPeriod(year=2045, month=3, status="processed")
        entry = PayrollEntry(period=period, employee_id=employee_id, working_days=30,
                             payable_days=30, present_days=30, paid_leave_days=0,
                             lop_days=0, gross=Decimal("50000"), deductions=Decimal("5000"),
                             net=Decimal("45000"), status="paid")
        entry.lines.append(PayrollEntryLine(name="Basic", kind="earning",
                                           amount=Decimal("50000"), basis="Monthly"))
        entry.lines.append(PayrollEntryLine(name="Provident fund", kind="deduction",
                                           amount=Decimal("5000"), basis="12%"))
        db.add(period)
        db.commit()
        return entry.id


def test_every_pdf_opens_has_text_and_shows_hindi_and_the_rupee(client, world):
    emp = _employee(client, full_name="रमेश कुमार", department="बिक्री",
                    designation="प्रबंधक", joining_date="2024-04-01")
    entry_id = _seed_payslip(client, emp["id"])
    admin = client.as_user("admin")

    slip_res = admin.get(f"/api/hr/payroll/entries/{entry_id}/slip")
    slip = _pdf(slip_res, "salary-slip.pdf")
    assert _reads(slip, "रमेश कुमार"), slip[:500]
    assert "₹" in slip, "the rupee sign is missing from the slip"
    assert any("Mukta" in name for name in _fonts(slip_res.content)), \
        "the PDF must embed the Devanagari font, not fall back to Helvetica"

    card_res = admin.get("/api/hr/outputs/id-card", params={"employee_id": emp["id"]})
    card = _pdf(card_res, "id-card.pdf")
    assert _reads(card, "रमेश कुमार")
    assert "₹" not in card  # the card carries no money

    templates = admin.get("/api/hr/letters/templates").json()["templates"]
    active = next(t for t in templates if t["active"])
    letter = _pdf(admin.get(f"/api/hr/outputs/letter/{active['code']}",
                            params={"employee_id": emp["id"]}), "letter.pdf")
    assert _reads(letter, "रमेश कुमार")

    statement = _pdf(admin.get("/api/hr/outputs/leave-statement",
                               params={"employee_id": emp["id"], "year": 2026}),
                     "leave-statement.pdf")
    assert _reads(statement, "रमेश कुमार")

    sheet = _pdf(admin.get("/api/hr/outputs/attendance-sheet",
                           params={"year": 2026, "month": 11, "employee_id": emp["id"]}),
                 "attendance-sheet.pdf")
    assert _reads(sheet, "रमेश कुमार")

    report = _pdf(admin.get("/api/hr/reports/headcount", params={"format": "pdf"}),
                  "hr-headcount.pdf")
    assert report.strip()

    invoice = _invoice(client, world)
    printed = admin.post(f"/api/print/invoice/{invoice['id']}", params={"copy": "ORIGINAL"})
    text = _pdf(printed, "invoice-print.pdf")
    assert printed.headers["content-disposition"].startswith("inline;")
    assert "/" not in printed.headers["content-disposition"].split("filename=")[-1]
    assert "X-Document-SHA256" in printed.headers
    assert "TAX INVOICE" in text and "Rs " in text
    assert any("Mukta" in name for name in _fonts(printed.content))
    assert _reads(text, "Rupees")


# -------------------------------------------------------------------- photo
def _png(size=(40, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 90, 60)).save(buf, format="PNG")
    return buf.getvalue()


def test_photo_upload_validates_content_and_never_uses_the_supplied_name(client, world):
    emp = _employee(client, full_name="Photo Person")
    admin = client.as_user("admin")

    good = admin.post(f"/api/hr/employees/{emp['id']}/photo",
                      files={"file": ("../../outside.png", _png(), "image/png")})
    assert good.status_code == 200, good.text
    read = admin.get(f"/api/hr/employees/{emp['id']}/photo")
    assert read.status_code == 200
    assert read.headers["content-type"] == "image/png"
    assert read.content == _png()
    assert not (ROOT / "outside.png").exists()

    text = admin.post(f"/api/hr/employees/{emp['id']}/photo",
                      files={"file": ("fake.png", b"not an image", "image/png")})
    assert text.status_code == 422, text.text

    truncated = admin.post(f"/api/hr/employees/{emp['id']}/photo",
                           files={"file": ("cut.png", _png()[:20], "image/png")})
    assert truncated.status_code == 422, truncated.text

    oversized = admin.post(f"/api/hr/employees/{emp['id']}/photo",
                           files={"file": ("big.png", b"x" * 2_000_001, "image/png")})
    assert oversized.status_code == 413

    client.cookies.clear()
    assert client.get(f"/api/hr/employees/{emp['id']}/photo").status_code == 401


# ------------------------------------------------------------------ audit
def test_audit_trail_csv_contract_and_permissions(client, world):
    admin = client.as_user("admin")
    res = admin.get("/api/audit/export")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    assert "audit-trail.csv" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf")
    _save("audit-trail.csv", res.content)
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0] == ["When (UTC)", "Actor", "Action", "Record", "Changes"]
    assert len(rows) > 3

    client.as_user("sales")
    assert client.get("/api/audit/export").status_code == 403


# -------------------------------------------------- report CSV/PDF contracts
def test_report_exports_have_matching_headers_and_permissions(client, world):
    admin = client.as_user("admin")
    key = next(c["key"] for c in admin.get("/api/reports").json() if c["key"] == "sales")
    csv_res = admin.get(f"/api/reports/{key}/export", params={"format": "csv"})
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    assert csv_res.headers["content-disposition"].endswith('.csv"')
    assert csv_res.content.startswith(b"\xef\xbb\xbf")
    _save(f"report-{key}.csv", csv_res.content)

    pdf_text = _pdf(admin.get(f"/api/reports/{key}/export", params={"format": "pdf"}),
                    f"report-{key}.pdf")
    assert pdf_text.strip()

    # The sales role may export its own report; a read-only viewer may not.
    client.as_user("viewer")
    assert client.get(f"/api/reports/{key}/export", params={"format": "csv"}).status_code in (403, 404)


def test_hr_report_csv_is_utf8_bom_and_matches_the_json_columns(client, world):
    admin = client.as_user("admin")
    data = admin.get("/api/hr/reports/headcount").json()
    res = admin.get("/api/hr/reports/headcount", params={"format": "csv"})
    assert res.status_code == 200, res.text
    assert res.content.startswith(b"\xef\xbb\xbf"), "HR report CSV must carry a BOM"
    _save("hr-headcount.csv", res.content)
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0] == [c["label"] for c in data["columns"]]
    assert len(rows) == len(data["rows"]) + 1


# ------------------------------------------------------- header injection
def test_employee_code_cannot_inject_or_break_a_file_name(client, world):
    quoted = _employee(client, code=f'AB"CD{uuid4().hex[:3].upper()}')
    admin = client.as_user("admin")
    res = admin.get("/api/hr/outputs/id-card", params={"employee_id": quoted["id"]})
    assert res.status_code == 200, res.text
    assert res.headers["content-disposition"].count('"') == 2

    crlf = _employee(client, code="CRLF\r\nX-Injected: 1")
    res = admin.get("/api/hr/outputs/id-card", params={"employee_id": crlf["id"]})
    assert res.status_code == 200, res.text
    assert "X-Injected" not in res.headers
    assert "\r" not in res.headers["content-disposition"]


def test_hr_report_and_bank_file_keep_formula_text_as_text(client, world):
    """A name that looks like a formula must not run when a spreadsheet opens the CSV."""
    hostile = '=HYPERLINK("http://evil.invalid","click")'
    emp = _employee(client, full_name=hostile, bank_account_no="50100123456789",
                    bank_ifsc="HDFC0001234")
    admin = client.as_user("admin")

    report = admin.get("/api/hr/reports/headcount", params={"format": "csv"})
    assert report.status_code == 200, report.text
    row = next(r for r in csv.reader(io.StringIO(report.content.decode("utf-8-sig")))
               if r and r[0] == emp["code"])
    assert row[1] == "'" + hostile, row

    with SessionLocal() as db:
        period = PayrollPeriod(year=2046, month=1, status="approved")
        period.entries.append(PayrollEntry(
            employee_id=emp["id"], working_days=30, payable_days=30, present_days=30,
            paid_leave_days=0, lop_days=0, gross=Decimal("50000"),
            deductions=Decimal("5000"), net=Decimal("45000"), status="approved"))
        db.add(period)
        db.commit()
        period_id = period.id

    bank = admin.get(f"/api/hr/payroll/periods/{period_id}/bank-file")
    assert bank.status_code == 200, bank.text
    row = next(r for r in csv.reader(io.StringIO(bank.content.decode("utf-8")))
               if r and r[0] == emp["code"])
    assert row[1] == "'" + hostile, row
    assert row[4] == "50100123456789", "an account number must not be altered"


def test_every_file_route_refuses_an_anonymous_caller(client, world):
    client.cookies.clear()
    for url in ("/api/hr/employees/export.csv", "/api/hr/employees/import-template.csv",
                "/api/audit/export", "/api/reports/sales/export?format=csv"):
        assert client.get(url).status_code == 401, url
    assert client.post("/api/hr/employees/import", json={
        "filename": "x.csv", "csv_text": "code,full_name\nAB,X\n"}).status_code == 401
