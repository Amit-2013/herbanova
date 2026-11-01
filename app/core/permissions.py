"""Permission catalog and the frozen baseline role sets.

`PERMISSIONS` is the single source of truth for every permission key the
application understands (module:action). `docs/permissions-matrix.md` is
generated from it and must be updated alongside it.

`BASELINE_ROLE_PERMS` is the frozen copy of the four original fixed roles.
Module Phase 1 seeds these exact sets into the `roles` table so existing
accounts keep working (parity is enforced by tests/test_roles_parity.py);
new permissions are additive and never silently removed from a seeded role
by this module.
"""

# key -> (description, module)  -- the permission matrix is grouped by module
PERMISSIONS: dict[str, tuple[str, str]] = {
    "user:manage":       ("Create and disable users, assign roles", "Users and rights"),
    "employee:read":     ("View the employee master", "Users and rights"),
    "employee:write":    ("Create and edit employees", "Users and rights"),
    "audit:read":        ("View and export the audit trail", "Users and rights"),
    "supplier:read":     ("View supplier records", "Purchasing"),
    "supplier:write":    ("Create and edit supplier records", "Purchasing"),
    "supplier:bank":     ("Request a supplier bank-detail change (needs second-person approval)", "Purchasing"),
    "product:read":      ("View products", "Products"),
    "product:write":     ("Create and edit products", "Products"),
    "tax:read":          ("View the company tax profile, GST rate master and discount slabs", "Tax and discounts"),
    "tax:write":         ("Maintain the company tax profile, GST rates and discount slabs", "Tax and discounts"),
    "stock:read":        ("View warehouses, batches, ledger and purchasing", "Inventory"),
    "stock:write":       ("Create warehouses, purchase orders and goods receipts", "Inventory"),
    "sales:read":        ("View distributors, sales orders and approvals", "Sales"),
    "sales:write":       ("Create, submit and cancel sales orders", "Sales"),
    "approval:read":     ("View the central approvals queue", "Approvals"),
    "approval:decide":   ("Approve or reject approval requests", "Sales"),
    "approval:credit_limit": ("Decide requests that exceed a distributor credit limit (Administrator only)", "Approvals"),
    "invoice:edit_post_billing": ("Amend an issued invoice after billing (Administrator only)", "Billing"),
    "distributor:write": ("Create and edit distributors", "Sales"),
    "credit:manage":     ("Change distributor credit limits", "Sales"),
    "dispatch:write":    ("Dispatch approved sales orders", "Sales"),
    "invoice:write":     ("Ask an Administrator to change the challan or e-way bill after billing", "Billing"),
    "invoice:cancel":    ("Cancel an issued invoice, with a reason", "Billing"),
    "note:write":        ("Issue credit and debit notes against an issued invoice", "Billing"),
    "print:document":    ("Print an invoice, credit note or debit note as a secure PDF", "Billing"),
    "accounts:read":     ("View outstanding, party ledgers, GST registers and the trial balance", "Accounts"),
    "accounts:write":    ("Record receipts from distributors and payments to suppliers", "Accounts"),
    "accounts:reports":  ("View the Accounts dashboard, Accounts report pack and Accounts email block", "Accounts"),
    "lead:read":         ("View leads", "Leads"),
    "lead:write":        ("Create and work leads", "Leads"),
    "lead:assign":       ("Reassign lead ownership", "Leads"),
    "report:export":     ("Download reports as CSV or Excel", "Reports"),
    "email:manage":      ("Manage scheduled report recipients, schedules and the delivery log (Administrator only)", "Reports"),
    "db:reset":          ("Wipe all business data after confirming with the admin secondary password", "Users and rights"),
    # ---- HR management (module phase 7)
    "hr:read":            ("View the HR dashboard and employee records", "HR"),
    "hr:write":           ("Maintain employees, offices, shifts, holidays and HR policies", "HR"),
    "hr:attendance_self": ("Record own attendance and submit own leave, OD and correction requests", "HR"),
    "hr:attendance_manage": ("Record, correct and approve attendance for the team", "HR"),
    "hr:leave_approve":   ("Approve or reject leave and OD requests within authority", "HR"),
    "hr:payroll_prepare": ("Prepare, review and export payroll", "HR"),
    "hr:payroll_approve": ("Approve and finalise payroll", "HR"),
    "hr:confidential":    ("View salary structures and confidential HR reports", "HR"),
    "hr:reports":         ("Open HR reports", "HR"),
}

PERMISSION_KEYS = set(PERMISSIONS)

# ---------------------------------------------------------------- parent / child
# A module's read permission is its parent. A child is never usable without its
# parent, and a role edit that clears a parent drops the children with it. The
# map is deliberately explicit: a permission added to PERMISSIONS without an
# entry here fails `tests/test_permission_tree.py`, so the tree cannot drift.
#
# A `None` parent is a top-level module gate. `accounts:reports` and
# `hr:attendance_self` are top-level on purpose: the Accounts reports and the
# self-service HR screens are reachable without the wider read permission.
PERMISSION_PARENT: dict[str, str | None] = {
    "user:manage": None,
    "employee:read": None,
    "employee:write": "employee:read",
    "audit:read": None,
    "db:reset": "user:manage",
    "product:read": None,
    "product:write": "product:read",
    "stock:read": None,
    "stock:write": "stock:read",
    "supplier:read": None,
    "supplier:write": "supplier:read",
    "supplier:bank": "supplier:read",
    "tax:read": None,
    "tax:write": "tax:read",
    "sales:read": None,
    "sales:write": "sales:read",
    "distributor:write": "sales:read",
    "credit:manage": "sales:read",
    "dispatch:write": "sales:read",
    "invoice:write": "sales:read",
    "invoice:cancel": "sales:read",
    "invoice:edit_post_billing": "sales:read",
    "note:write": "sales:read",
    "print:document": "sales:read",
    "approval:read": None,
    "approval:decide": "approval:read",
    "approval:credit_limit": "approval:read",
    "accounts:read": None,
    "accounts:write": "accounts:read",
    "accounts:reports": None,
    "lead:read": None,
    "lead:write": "lead:read",
    "lead:assign": "lead:read",
    "report:export": None,
    "email:manage": None,
    "hr:read": None,
    "hr:write": "hr:read",
    "hr:attendance_self": None,
    "hr:attendance_manage": "hr:read",
    "hr:leave_approve": "hr:read",
    "hr:payroll_prepare": "hr:read",
    "hr:payroll_approve": "hr:read",
    "hr:confidential": "hr:read",
    "hr:reports": "hr:read",
}

# These rights decide on money or on the security of the system itself. The
# server already checks the Administrator role at the route; this set makes the
# same rule apply when a role is created or edited, so a custom role can never
# carry one.
ADMIN_ONLY_PERMISSIONS: frozenset[str] = frozenset({
    "approval:credit_limit",
    "invoice:edit_post_billing",
    "email:manage",
    "db:reset",
})


def parent_of(key: str) -> str | None:
    return PERMISSION_PARENT.get(key)


def is_admin_only(key: str) -> bool:
    return key in ADMIN_ONLY_PERMISSIONS


def permission_allowed(key: str, granted: set[str] | frozenset[str]) -> bool:
    """A key is usable only when it and its parent are both granted."""
    if key not in granted:
        return False
    parent = parent_of(key)
    return parent is None or parent in granted


def effective_permissions(granted) -> set[str]:
    """The subset of stored keys a request may actually use.

    Stored data can be older than the rule: a role that carries a child but not
    its parent keeps the record but loses the child's authority until the
    parent is granted. This is the fail-closed behaviour the rule requires.
    """
    keys = set(granted or ())
    return {key for key in keys if permission_allowed(key, keys)}


def sanitized_permissions(requested) -> tuple[list[str], list[str]]:
    """Drop children whose parent is absent; return (kept, dropped).

    Only explicit selections survive. Nothing is implied by a parent, so this
    removes exactly the orphans and never adds a key the caller did not send.
    """
    keys = {key for key in (requested or ()) if key in PERMISSION_KEYS}
    dropped = {key for key in keys if not permission_allowed(key, keys)}
    kept = keys - dropped
    return sorted(kept), sorted(dropped)


# Frozen baseline sets (the original ROLE_PERMS). DO NOT EDIT to "fix" a role:
# changes belong in a documented role-permission update with tests, because
# these values also define seeded-role parity (AUD-015 / AUD-024).
BASELINE_ROLE_PERMS: dict[str, set[str]] = {
    "admin":     {"user:manage", "product:read", "product:write", "stock:read", "stock:write",
                  "sales:read", "sales:write", "approval:decide", "report:export", "audit:read",
                  "distributor:write", "credit:manage", "dispatch:write",
                  # Module Phase 4 adds billing: the issue, correction and cancellation of tax documents
                  "invoice:write", "invoice:cancel", "note:write", "print:document",
                  "lead:read", "lead:write", "lead:assign",
                  # Module Phase 1 adds employee management to the administrator role
                  "employee:read", "employee:write",
                  # Module Phase 2 adds the supplier master and its bank-change flow
                  "supplier:read", "supplier:write", "supplier:bank",
                  # Module Phase 3 adds the GST rate master and discount slabs
                  "tax:read", "tax:write",
                  # Database reset (admin only, gated by a secondary password)
                  "db:reset",
                  # Module Phase 6 adds accounts: statements, plus recording money
                  "accounts:read", "accounts:write",
                  # Full accounts reporting is a narrower right than the statements
                  # above; the Administrator may grant it to an Accounts head.
                  "accounts:reports",
                  # Scheduled reports: recipients, schedules and the delivery log
                  "email:manage",
                  # Approvals and post-billing amendments are administrator decisions
                  "approval:read", "approval:credit_limit", "invoice:edit_post_billing",
                  # HR management
                  "hr:read", "hr:write", "hr:attendance_self", "hr:attendance_manage",
                  "hr:leave_approve", "hr:payroll_prepare", "hr:payroll_approve",
                  "hr:confidential", "hr:reports"},
    "sales":     {"product:read", "stock:read", "sales:read", "sales:write", "report:export",
                  "distributor:write", "lead:read", "lead:write", "approval:read",
                  # Module Phase 3: the sales desk needs the rates that apply to an order
                  "tax:read",
                  # Module Phase 4: the desk records the challan/e-way details and issues notes
                  "invoice:write", "note:write", "print:document",
                  # Module Phase 6: the desk can see what is still owed to it
                  "accounts:read",
                  # Staff record their own office/GPS attendance; nothing team-wide
                  "hr:attendance_self"},
    "inventory": {"product:read", "product:write", "stock:read", "stock:write",
                  "sales:read", "dispatch:write", "approval:read",
                  # Module Phase 4: the dispatch desk records the vehicle and e-way bill
                  "invoice:write", "print:document",
                  # Module Phase 2: buying needs to read supplier records; writes stay with admin
                  "supplier:read",
                  # Module Phase 3: product tax fields are maintained where products are
                  "tax:read",
                  # Staff record their own office/GPS attendance; nothing team-wide
                  "hr:attendance_self"},
    "viewer":    {"product:read", "stock:read", "sales:read", "hr:attendance_self"},
}
