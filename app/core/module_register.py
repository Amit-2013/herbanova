"""The module register — one place the Overview screen's figures come from.

The screen used to carry its own hand-typed copy of this list, which is how it
came to show two different totals at once (COR-007). The list now lives here, is
served at `GET /api/modules`, and the browser renders whatever it is given: there
is no second copy to drift.

Rules this module keeps:

- Only a `conditional` module is excluded from the denominator. A `blocked`
  module stays in it and is simply not counted as working, because a capability
  the business expects is not made smaller by an environment problem.
- The group subtotals are derived, never typed, so they always add up to the
  headline.
- `MOD-` identifiers match docs/Feature Structure.md section 4. Module Phase 4
  and Module Phase 5 are one module (MOD-13), as that document requires.

A status changes only against evidence: a passing test suite, an executed code
path, or a live check. `tests/test_module_status.py` compares this register with
the human register in the documentation.
"""
from dataclasses import dataclass, asdict

WORKING = "w"
BLOCKED = "b"
PLANNED = "p"
CONDITIONAL = "c"

# The chip a status renders as, and the word shown in it.
CHIPS: dict[str, tuple[str, str]] = {
    WORKING: ("ok", "Working"),
    BLOCKED: ("warn", "Blocked"),
    PLANNED: ("off", "Planned"),
    CONDITIONAL: ("off", "Conditional"),
}


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    does: str
    status: str
    group: str

    @property
    def counted(self) -> bool:
        return self.status != CONDITIONAL


BUILT = "Built modules"
PHASES = "Module phases"

MODULES: tuple[Module, ...] = (
    # MOD-01 .. MOD-09 — the baseline modules
    Module("MOD-01", "Sign-in and roles",
           "Permissions are checked by the server on every request", WORKING, BUILT),
    Module("MOD-02", "Products and SKUs",
           "Unique SKU, valid prices, audit entry on every change", WORKING, BUILT),
    Module("MOD-03", "Stock ledger",
           "Every movement recorded; negative stock refused", WORKING, BUILT),
    Module("MOD-04", "Purchase orders and receipts",
           "Duplicate receipts refused; stock added by batch", WORKING, BUILT),
    Module("MOD-05", "Sales orders and dispatch",
           "Stock and credit checked at submit and again at dispatch; the warehouse "
           "is chosen at dispatch", WORKING, BUILT),
    Module("MOD-06", "Credit control and approvals",
           "Distributor master with All / Active / Draft / Pending verification / "
           "Blocked / Inactive, editing and needs-completion, credit limits, discount "
           "rule, no self-approval", WORKING, BUILT),
    Module("MOD-07", "Leads and follow-ups",
           "One owner per lead, follow-up dates, overdue flags, full activity history",
           WORKING, BUILT),
    Module("MOD-08", "Reports and exports",
           "Totals reconciled to records", WORKING, BUILT),
    Module("MOD-09", "Backup and restore test",
           "Dump, restore into a scratch database and reconcile: row counts, Alembic "
           "revision and every report check compared with the live database",
           WORKING, BUILT),
    # MOD-10 .. MOD-15 — the module phases; Phases 4 and 5 are one module
    Module("MOD-10", "Users, rights and employees",
           "Roles and permission matrix, employee records, password lifecycle, "
           "lockout, audit-trail viewer", WORKING, PHASES),
    Module("MOD-11", "Supplier management",
           "Supplier master with GSTIN and PAN checks, goods receipt notes, part "
           "receipts, second-approver bank changes", WORKING, PHASES),
    Module("MOD-12", "GST tax and discount slabs",
           "HSN and GST rate master (CGST, SGST or UTGST inside a union territory, "
           "IGST), discount slabs, tax quote", WORKING, PHASES),
    Module("MOD-13", "Billing and document printing",
           "Tax invoices from dispatch, consecutive numbers, credit and debit notes, "
           "no edits after issue; PDFs with SHA-256, print log, copy selector, "
           "verification panel, real scannable code, HSN annexure, terms, signature "
           "and pagination", WORKING, PHASES),
    Module("MOD-14", "Accounts",
           "Distributor and supplier ledgers, receipts and payments, outstanding and "
           "ageing, GST register and trial balance",
           WORKING, PHASES),
    Module("MOD-15", "E-invoice and e-way bill",
           "Only if the business turnover requires it", CONDITIONAL, PHASES),
    Module("MOD-16", "HR management, attendance and payroll",
           "Employee master, office/geofence attendance, leave, OD, central HR approvals, "
           "configurable payroll and HR reports", WORKING, PHASES),
)


def counted() -> list[Module]:
    """The denominator: every module the build is expected to deliver."""
    return [m for m in MODULES if m.counted]


def working() -> list[Module]:
    return [m for m in counted() if m.status == WORKING]


def totals() -> dict:
    """The headline figure, derived once here and never recomputed by hand."""
    denominator = len(counted())
    numerator = len(working())
    return {
        "entries": len(MODULES),
        "counted": denominator,
        "working": numerator,
        "conditional": len(MODULES) - denominator,
        "percent": round(numerator / denominator * 100) if denominator else 0,
    }


def groups() -> list[dict]:
    """One row per group, in the order the groups appear in the register.

    A group subtotal is computed on the same basis as the headline, so the two
    can never tell different stories.
    """
    out = []
    for name in dict.fromkeys(m.group for m in MODULES):
        rows = [m for m in MODULES if m.group == name]
        out.append({
            "name": name,
            "counted": sum(1 for m in rows if m.counted),
            "working": sum(1 for m in rows if m.counted and m.status == WORKING),
        })
    return out


def payload() -> dict:
    """The whole register as the browser needs it, in one response."""
    return {
        "modules": [asdict(m) for m in MODULES],
        "groups": groups(),
        "totals": totals(),
        "chips": {k: list(v) for k, v in CHIPS.items()},
    }
