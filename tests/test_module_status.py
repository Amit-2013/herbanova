"""The module register tells the truth (COR-007): it adds up, and what it claims exists."""
from pathlib import Path

from app.core import module_register as reg

ROOT = Path(__file__).resolve().parent.parent

# A module marked working must have the code that does the work.
EVIDENCE = {
    "MOD-07": "app/api/leads.py",
    "MOD-08": "app/services/reports.py",
    "MOD-09": "backup_restore_test.py",
    "MOD-10": "app/api/users.py",
    "MOD-11": "app/api/suppliers.py",
    "MOD-12": "app/api/tax.py",
    "MOD-13": "app/api/printing.py",
    "MOD-14": "app/api/accounts.py",
    "MOD-16": "app/api/hr.py",
    "MOD-17": "app/api/accounts.py",
    "MOD-18": "app/api/email_reports.py",
}


def test_identifiers_are_unique():
    ids = [m.id for m in reg.MODULES]
    assert len(ids) == len(set(ids))


def test_headline_and_group_subtotals_agree():
    t, groups = reg.totals(), reg.groups()
    assert t["counted"] == sum(g["counted"] for g in groups)
    assert t["working"] == sum(g["working"] for g in groups)
    assert t["entries"] == t["counted"] + t["conditional"]


def test_modules_claimed_working_have_their_code():
    working = {m.id for m in reg.working()}
    for module_id, path in EVIDENCE.items():
        if module_id in working:
            assert (ROOT / path).is_file(), f"{module_id} is marked working but {path} is missing"


def test_served_register_matches_the_module(client):
    body = client.as_user("viewer").get("/api/modules").json()
    assert body["totals"] == reg.totals()
    assert len(body["modules"]) == len(reg.MODULES)
