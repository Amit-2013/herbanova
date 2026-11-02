"""Content and reconciliation tests for the reporting service.

Stage 1 of the audit found two reports that *built* successfully but returned
wrong data: the GST outward register was always empty (the builder looked for a
``rows`` key that ``ledger.gst_register()`` never returns) and the receivables
ageing table printed the wrapper's own keys (``as_of``, ``buckets``, ``total``)
instead of the four buckets. The old suite passed because it only asserted
HTTP 200.

These tests assert report *content*, compare every financial report with an
independent computation over the same documents, and refuse a "reconciled"
flag that is only a self-comparison.
"""
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.core import InvoiceLine
from test_approvals import _invoice_for

ROOT = Path(__file__).resolve().parent.parent
WIDE = {"from": "2000-01-01", "to": "2099-12-31"}


def _report(client, key, **params):
    r = client.as_user("admin").get(f"/api/reports/{key}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _dec(value):
    return Decimal(str(value or 0))


def test_gst_register_lists_the_issued_invoice(client, world):
    """The register must show the document, not an empty table."""
    invoice = _invoice_for(client, world)
    report = _report(client, "gst_register", **WIDE)
    rows = report["tables"][0]["rows"]
    assert rows, "the GST register is empty although an invoice has been issued"

    row = next(r for r in rows if r["number"] == invoice["invoice_number"])
    assert row["section"] == "B2B invoice"
    assert _dec(row["taxable"]) == _dec(invoice["taxable_value"])
    assert _dec(row["cgst"]) == _dec(invoice["cgst_total"])
    assert _dec(row["sgst"]) == _dec(invoice["sgst_total"])
    assert _dec(row["total"]) == _dec(invoice["grand_total"])

    totals = report["tables"][0]["totals"]
    # Other tests also issue invoices in this wide period, so the totals are held
    # against the listed rows (invoices add, credit notes subtract), not one invoice.
    sign = {"B2B invoice": 1, "Debit note": 1, "Credit note": -1}
    for field in ("taxable", "cgst", "sgst", "total"):
        assert _dec(totals[field]) == sum(
            (sign[r["section"]] * _dec(r[field]) for r in rows), Decimal("0")), field
    assert report["reconciled"] is True
    assert all(c["ok"] for c in report["checks"]), report["checks"]


def test_gst_register_and_accounts_endpoint_agree(client, world):
    """The same data through two screens must produce the same numbers."""
    _invoice_for(client, world)
    report = _report(client, "gst_register", **WIDE)
    accounts = client.as_user("admin").get("/api/accounts/gst-register")
    assert accounts.status_code == 200, accounts.text

    totals = report["tables"][0]["totals"]
    for key in ("taxable", "cgst", "sgst", "igst", "total"):
        assert _dec(totals[key]) == _dec(accounts.json()["totals"][key]), key
    # The report table also lists credit and debit notes; the accounts endpoint's
    # `b2b` list is invoices only, so compare the invoice section with it.
    invoice_rows = [r for r in report["tables"][0]["rows"] if r["section"] == "B2B invoice"]
    assert len(invoice_rows) == len(accounts.json()["b2b"])


def test_credit_notes_are_a_separate_gst_section_not_b2b(client, world):
    """GSTR-1 reports a credit note as a credit note, never as a B2B invoice.

    Both the report and the accounts endpoint return one register. The `b2b`
    list holds invoices only; the note sits in `credit_notes` and reduces the
    totals. Putting it in both would double-count the reduction.
    """
    invoice = _invoice_for(client, world)
    with SessionLocal() as db:
        line_id = db.scalar(select(InvoiceLine.id).where(
            InvoiceLine.invoice_id == invoice["id"]))
    note = client.as_user("admin").post("/api/credit-notes", json={
        "invoice_id": invoice["id"], "reason": "GSTR-1 section check",
        "lines": [{"invoice_line_id": line_id, "qty": "1"}]})
    assert note.status_code == 201, note.text
    note_number = note.json()["credit_note_number"]

    report = _report(client, "gst_register", **WIDE)
    accounts = client.as_user("admin").get("/api/accounts/gst-register").json()
    rows = report["tables"][0]["rows"]

    credit_rows = [r for r in rows if r["section"] == "Credit note"
                   and r["number"] == note_number]
    assert len(credit_rows) == 1
    assert _dec(credit_rows[0]["taxable"]) == _dec(note.json()["taxable_value"])
    assert _dec(credit_rows[0]["total"]) == _dec(note.json()["grand_total"])
    # The same note is absent from both B2B lists: an invoice section holds
    # invoices only, exactly as GSTR-1 section 4 does.
    assert not any(r["number"] == note_number for r in rows
                   if r["section"] == "B2B invoice")
    assert not any(r["number"] == note_number for r in accounts["b2b"])
    assert any(r["number"] == note_number for r in accounts["credit_notes"])
    assert len([r for r in rows if r["section"] == "B2B invoice"]) == len(accounts["b2b"])

    # The totals still agree because both paths net the note out.
    totals = report["tables"][0]["totals"]
    for key in ("taxable", "cgst", "sgst", "igst", "total"):
        assert _dec(totals[key]) == _dec(accounts["totals"][key]), key
    sign = {"B2B invoice": 1, "Debit note": 1, "Credit note": -1}
    assert _dec(totals["taxable"]) == sum(
        (sign[r["section"]] * _dec(r["taxable"]) for r in rows), Decimal("0"))


def test_receivables_ageing_shows_the_four_buckets(client, world):
    report = _report(client, "receivables_ageing")
    rows = report["tables"][0]["rows"]
    assert {r["ageing_bucket"] for r in rows} == {"0-30", "31-60", "61-90", "90+"}
    # The wrapper's own keys must never reach the screen.
    assert not {"as_of", "buckets", "total", "count"} & {r["ageing_bucket"] for r in rows}
    for row in rows:
        assert set(row) == {"ageing_bucket", "label", "invoice_count", "amount"}
    assert report["reconciled"] is True


def test_receivables_ageing_puts_the_invoice_in_a_bucket(client, world):
    invoice = _invoice_for(client, world)
    report = _report(client, "receivables_ageing")
    rows = report["tables"][0]["rows"]
    total = sum(_dec(r["amount"]) for r in rows)
    count = sum(int(r["invoice_count"]) for r in rows)
    assert count >= 1
    assert total >= _dec(invoice["grand_total"])
    check = next(c for c in report["checks"] if c["name"] == "ageing_total")
    assert check["ok"], check


def test_receivables_report_honours_the_date_range(client, world):
    invoice = _invoice_for(client, world)
    inside = _report(client, "receivables", **WIDE)
    assert any(r["number"] == invoice["invoice_number"] for r in inside["tables"][0]["rows"])

    outside = _report(client, "receivables", **{"from": "1990-01-01", "to": "1990-12-31"})
    assert not any(r["number"] == invoice["invoice_number"]
                   for r in outside["tables"][0]["rows"])


def test_trial_balance_debits_equal_credits(client, world):
    _invoice_for(client, world)
    report = _report(client, "trial_balance")
    rows = report["tables"][0]["rows"]
    debits = sum(_dec(r["debit"]) for r in rows)
    credits = sum(_dec(r["credit"]) for r in rows)
    assert debits == credits
    assert debits > 0
    assert report["reconciled"] is True


def test_stock_report_agrees_with_the_movement_ledger(client, world):
    """Closing stock must equal opening balance plus movements."""
    report = _report(client, "stock")
    check = next(c for c in report["checks"] if c["name"] == "stock_quantity")
    assert check["ok"], check
    assert all(c["ok"] for c in report["checks"]), report["checks"]


def test_invoice_register_totals_match_the_database(client, world):
    invoice = _invoice_for(client, world)
    report = _report(client, "invoices", **WIDE)
    rows = report["tables"][0]["rows"]
    assert any(r["invoice_number"] == invoice["invoice_number"] for r in rows)
    assert all(c["ok"] for c in report["checks"]), report["checks"]
    check = next(c for c in report["checks"] if c["name"] == "grand_total")
    assert _dec(check["report_value"]) == _dec(check["record_value"])


def test_financial_reports_carry_a_real_cross_check(client, world):
    """A report may not claim to be reconciled by comparing itself with itself."""
    for key in ("gst_register", "receivables_ageing", "receivables", "payables",
                "trial_balance", "stock", "invoices", "sales"):
        report = _report(client, key, **WIDE)
        real = [c for c in report["checks"] if c["name"] != "row_count"]
        assert real, f"{key} has no independent check"
        failed = [c for c in report["checks"] if not c["ok"]]
        assert not failed, (key, failed)


def test_empty_period_still_reports_honest_checks(client, world):
    """A date range with no documents must return an empty register that still
    reconciles, rather than an error or a stale figure."""
    report = _report(client, "gst_register", **{"from": "1990-01-01", "to": "1990-12-31"})
    assert report["tables"][0]["rows"] == []
    assert report["reconciled"] is True


def test_report_filters_are_refused_when_unsupported(client, world):
    admin = client.as_user("admin")
    assert admin.get("/api/reports/gst_register", params={"department": "Sales"}).status_code == 422
    assert admin.get("/api/reports/receivables_ageing",
                     params={"branch_id": "not-a-number"}).status_code == 422


def test_migrations_match_the_models():
    """`alembic check` must stay clean: an autogenerated migration would
    otherwise drop tables or indexes that only exist in the database."""
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()})}
    result = subprocess.run([sys.executable, "-m", "alembic", "check"],
                            cwd=ROOT, capture_output=True, text=True, env=env)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "No new upgrade operations detected" in output, output
