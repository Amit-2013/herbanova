"""Central feature availability switches, managed from Roles & Permissions.

A feature switch answers a different question from a permission:

* a permission says *who* may use a module;
* a feature switch says *whether the module is available to anyone at all*.

Both are enforced on the server. A switched-off feature

1. is refused by the API gate (`app.main._feature_gate`) with 403, and
2. loses its permissions from `rbac.role_permissions()`, so `/api/auth/me`,
   navigation, the Overview and global search stop offering it to every role.

The registration is explicit. `tests/test_feature_switches.py` checks that every
permission key belongs to exactly one feature and every navigation view belongs
to at most one, so a new module cannot be added without deciding where its
switch lives.

Defaults: a feature without a stored row is ON, so an installation that has not
run the migration yet behaves exactly as before. `users` is locked ON: the
Administrator must always be able to reach the screen that switches the other
modules back on.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    description: str
    views: tuple[str, ...]
    permissions: tuple[str, ...]
    api_prefixes: tuple[str, ...]
    locked: bool = False


FEATURES: tuple[Feature, ...] = (
    Feature(
        "products", "Products",
        "Product master, SKUs, HSN and pricing.",
        views=("products",),
        permissions=("product:read", "product:write"),
        api_prefixes=("/api/products",)),
    Feature(
        "stock", "Inventory and purchasing",
        "Warehouses, batches, stock ledger and purchase orders.",
        views=("inventory", "purchasing"),
        permissions=("stock:read", "stock:write"),
        api_prefixes=("/api/warehouses", "/api/inventory", "/api/purchase-orders",
                      "/api/dashboard/expiry")),
    Feature(
        "foc", "Free samples (FOC)",
        "Free-of-cost receipts and approved sample distributions.",
        views=("foc",),
        permissions=("foc:read", "foc:write", "foc:approve"),
        api_prefixes=("/api/foc",)),
    Feature(
        "suppliers", "Suppliers",
        "Supplier master and bank-detail change requests.",
        views=("suppliers",),
        permissions=("supplier:read", "supplier:write", "supplier:bank"),
        api_prefixes=("/api/suppliers",)),
    Feature(
        "sales", "Sales, billing and distribution",
        "Customers, distributors, sales orders, invoices, notes and printing.",
        views=("sales", "billing", "customers", "distributors", "geo"),
        permissions=("sales:read", "sales:write", "distributor:write", "credit:manage",
                     "dispatch:write", "invoice:write", "invoice:cancel",
                     "invoice:edit_post_billing", "note:write", "print:document"),
        api_prefixes=("/api/distributors", "/api/sales-orders", "/api/invoices",
                      "/api/credit-notes", "/api/debit-notes", "/api/print",
                      "/api/dashboard/geo")),
    Feature(
        "approvals", "Approvals",
        "The central approvals queue and credit-limit decisions.",
        views=("approvals",),
        permissions=("approval:read", "approval:decide", "approval:credit_limit"),
        api_prefixes=("/api/approvals",)),
    Feature(
        "leads", "Leads",
        "Leads, follow-ups and lost leads.",
        views=("leads", "lost", "followups"),
        permissions=("lead:read", "lead:write", "lead:assign"),
        api_prefixes=("/api/leads",)),
    Feature(
        "accounts", "Accounting and finance",
        "Outstanding, party ledgers, GST registers, expenses and the accounts dashboard.",
        views=("accounts",),
        permissions=("accounts:read", "accounts:write", "accounts:reports",
                     "expense:read", "expense:write"),
        api_prefixes=("/api/accounts", "/api/expenses")),
    Feature(
        "tax", "Tax and discounts",
        "Company tax profile, GST rate master and discount slabs.",
        views=("tax",),
        permissions=("tax:read", "tax:write"),
        api_prefixes=("/api/tax", "/api/company", "/api/discount-slabs")),
    Feature(
        "reports", "Reports",
        "Report catalogue, exports and the month-on-month comparison.",
        views=("reports", "compare"),
        permissions=("report:export",),
        api_prefixes=("/api/reports", "/api/dashboard/compare")),
    Feature(
        "hr", "HR management",
        "HR profile, attendance, leave, payroll, letters and HR reports.",
        views=("hr",),
        permissions=("hr:read", "hr:write", "hr:attendance_self", "hr:attendance_manage",
                     "hr:leave_approve", "hr:payroll_prepare", "hr:payroll_approve",
                     "hr:confidential", "hr:reports"),
        api_prefixes=("/api/hr", "/api/employees")),
    Feature(
        "audit", "Audit trail",
        "The audit trail and the Overview activity feed.",
        views=("audit",),
        permissions=("audit:read",),
        api_prefixes=("/api/audit", "/api/dashboard/activity")),
    Feature(
        "scheduled", "Scheduled reports",
        "Scheduled email recipients, schedules and the delivery log.",
        views=("scheduled",),
        permissions=("email:manage",),
        api_prefixes=("/api/email-reports", "/api/email-settings")),
    Feature(
        "users", "Users and rights",
        "Logins, roles, permissions, the employee master and feature availability.",
        views=("users",),
        permissions=("user:manage", "employee:read", "employee:write", "db:reset"),
        api_prefixes=("/api/users",),
        locked=True),
)

FEATURE_BY_KEY: dict[str, Feature] = {f.key: f for f in FEATURES}
FEATURE_KEYS: frozenset[str] = frozenset(FEATURE_BY_KEY)

# Routes that must keep working whatever the switch says: an unsubscribe link in
# an email that has already been sent cannot depend on the module being on.
PUBLIC_EXCEPTIONS: tuple[str, ...] = ("/api/email-reports/unsubscribe/",)


def feature_for_path(path: str) -> str | None:
    """The feature that owns an API path, longest prefix first, or None.

    The boundary check keeps `/api/inventory` from matching `/api/inventoryx`.
    """
    best: str | None = None
    best_len = -1
    for feature in FEATURES:
        for prefix in feature.api_prefixes:
            if (path == prefix or path.startswith(prefix + "/")) and len(prefix) > best_len:
                best, best_len = feature.key, len(prefix)
    return best


def is_public_exception(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PUBLIC_EXCEPTIONS)
