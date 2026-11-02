"""Business-rule constants. Change here, not inside endpoints."""
from decimal import Decimal

# A line priced more than this % below MRP needs an approver's decision.
DISCOUNT_APPROVAL_PCT = Decimal("10")

# Reports group orders by calendar day in this time zone (the business runs in India),
# not in the database server's UTC.
REPORT_TZ = "Asia/Kolkata"

# A purchase-order line whose unit cost is still unknown must carry one of these
# reasons. The keys are stored; the labels are shown.
PO_RATE_REMARKS: dict[str, str] = {
    "testing": "Testing",
    "sample": "Sample",
    "foc": "Free of Cost (FOC)",
    "rate_pending": "Rate Pending",
    "quotation_pending": "Quotation Pending",
    "promotional_stock": "Promotional Stock",
    "replacement": "Replacement",
}

# Approval request categories handled by the central Approvals module.
APPROVAL_TYPES: dict[str, str] = {
    "sales_order": "Sales order",
    "invoice_post_billing": "Post-billing edit",
    "expense": "Expense",
    "hr_leave": "Leave application",
    "hr_od": "On-duty request",
    "hr_attendance_correction": "Attendance correction",
    "hr_geofence_exception": "Location exception",
    "hr_overtime": "Overtime adjustment",
    "hr_salary_revision": "Salary revision",
    "hr_payroll": "Payroll approval",
    "hr_reimbursement": "Reimbursement",
}