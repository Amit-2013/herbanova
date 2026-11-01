"""Central approvals queue.

Every request type the business needs approval for is stored in
`approval_requests` and shown here: sales orders over a credit limit or with a
large discount, post-billing amendments, and (from the HR module) leave, OD,
attendance corrections, payroll and the rest. The queue never decides anything
itself beyond routing: each type's handler applies the change in one
transaction and writes the audit entry.

Rules enforced here:
- `approval:read` to see the queue; a role only sees the categories it may open.
- credit-limit requests can only be decided by the Administrator;
- nobody decides a request they raised (or the order they created);
- a request can be decided once.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.pagination import page_params, paginate
from ..core.rbac import is_admin, require, role_permissions
from ..core.rules import APPROVAL_TYPES, REPORT_TZ
from ..models.core import ApprovalRequest, Distributor, Invoice, SalesOrder, User
from ..services.audit import audit

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

# The permission each decidable HR request type needs. Request types with no
# handler here (overtime, salary revision, reimbursement) have nothing to
# decide yet and are refused by /decide.
HR_DECIDE_PERMISSION = {
    "hr_leave": "hr:leave_approve",
    "hr_od": "hr:leave_approve",
    "hr_attendance_correction": "hr:attendance_manage",
    "hr_geofence_exception": "hr:attendance_manage",
    "hr_payroll": "hr:payroll_approve",
}


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=300)


class ApprovalOut(BaseModel):
    id: int
    request_type: str
    request_type_label: str
    request_no: str | None
    record_type: str
    record_id: int
    so_number: str | None = None
    document_number: str | None = None
    subject: str | None = None
    requested_dates: str | None = None
    distributor: str | None = None
    order_total: Decimal | None = None
    reasons: list[str]
    status: str
    requested_by: str
    requested_at: datetime | None
    decided_by: str | None
    decided_at: datetime | None
    decision_reason: str | None
    pending_approver_role: str | None = None
    detail: dict | None
    can_decide: bool = False
    age_days: int | None = None
    deciders: list[str] = []


def _category_allowed(db: Session, user, record_type: str) -> bool:
    if record_type == "sales_order":
        return True
    if record_type.startswith("hr_"):
        return bool({"hr:read", "approval:read"} & role_permissions(db, user))
    return True


def _age_days(raised: datetime | None) -> int | None:
    """Whole business days since the request was raised, in the report timezone."""
    if not raised:
        return None
    tz = ZoneInfo(REPORT_TZ)
    local = raised.replace(tzinfo=tz) if raised.tzinfo is None else raised.astimezone(tz)
    # A request cannot be raised in the future; clock skew is reported as today.
    return max(0, (datetime.now(tz).date() - local.date()).days)


def _build(db: Session, rows: list[ApprovalRequest], user) -> list[ApprovalOut]:
    if not rows:
        return []
    order_ids = [a.record_id for a in rows if a.record_type == "sales_order"]
    orders = {o.id: o for o in db.scalars(select(SalesOrder).where(
        SalesOrder.id.in_(order_ids))).all()} if order_ids else {}
    dists = {d.id: d for d in db.scalars(select(Distributor)).all()}
    invoice_ids = [a.record_id for a in rows if a.record_type == "invoice_post_billing"]
    invoices = {i.id: i for i in db.scalars(select(Invoice).where(
        Invoice.id.in_(invoice_ids))).all()} if invoice_ids else {}
    uids = {a.requested_by for a in rows} | {a.decided_by for a in rows if a.decided_by}
    users = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(uids))).all()}
    admin = is_admin(db, user)
    perms = role_permissions(db, user)
    from ..services.hr import scoped_employee_ids
    hr_scope = scoped_employee_ids(db, user)

    def deciders(a: ApprovalRequest) -> list[str]:
        """Who may decide, in words taken from the same rule `can_decide` uses.

        Naming people would go stale and could be wrong; naming the rule is true.
        """
        if a.status != "pending":
            return []
        if a.record_type == "sales_order":
            if "credit_limit" in (a.reasons or []):
                return ["Administrator"]
            return ["Administrator", "Approver with approval:decide"]
        if a.record_type == "invoice_post_billing":
            return ["Administrator"]
        need = HR_DECIDE_PERMISSION.get(a.record_type)
        return [f"Role with {need}"] if need else ["No decision handler yet"]

    def can_decide(a: ApprovalRequest) -> bool:
        """Whether *this* user could decide the request now — the same rules the
        decide handlers enforce, so the UI never offers a decision that will 403."""
        if a.status != "pending" or a.requested_by == user.id:
            return False
        if a.record_type == "sales_order":
            so = orders.get(a.record_id)
            if so and so.created_by == user.id:
                return False
            if "credit_limit" in (a.reasons or []) and not admin:
                return False
            return admin or "approval:decide" in perms
        if a.record_type == "invoice_post_billing":
            return admin
        need = HR_DECIDE_PERMISSION.get(a.record_type)
        if not (need and (admin or need in perms)):
            return False
        # A reporting manager decides only inside their own reporting chain;
        # HR-wide roles have no scope restriction (hr_scope is None).
        if hr_scope is not None and a.record_type != "hr_payroll":
            emp_id = (a.detail or {}).get("employee_id")
            if emp_id is None or int(emp_id) not in hr_scope:
                return False
        return True

    out = []
    for a in rows:
        so = orders.get(a.record_id) if a.record_type == "sales_order" else None
        inv = invoices.get(a.record_id) if a.record_type == "invoice_post_billing" else None
        dist = dists.get(so.distributor_id) if so else None
        detail = a.detail or {}
        document_number = a.document_number or (so.so_number if so else
                                                inv.invoice_number if inv else None)
        subject = a.subject or (str(detail.get("subject") or "") or None)
        if subject is None and so:
            subject = f"{dist.name if dist else 'Distributor'} · ₹ {so.total}"
        if subject is None and inv:
            subject = f"Invoice {inv.invoice_number} · ₹ {inv.grand_total}"
        reasons = a.reasons or []
        out.append(ApprovalOut(
            id=a.id, request_type=a.record_type,
            request_type_label=APPROVAL_TYPES.get(a.record_type,
                                                  a.record_type.replace("_", " ").title()),
            request_no=a.request_no, record_type=a.record_type, record_id=a.record_id,
            so_number=so.so_number if so else None, document_number=document_number,
            subject=subject, requested_dates=a.requested_dates,
            distributor=dist.code if dist else None,
            order_total=so.total if so else (inv.grand_total if inv else None),
            reasons=reasons, status=a.status,
            requested_by=users.get(a.requested_by, "?"), requested_at=a.requested_at,
            decided_by=users.get(a.decided_by) if a.decided_by else None,
            decided_at=a.decided_at, decision_reason=a.decision_reason,
            pending_approver_role=a.pending_approver_role,
            detail=a.detail,
            can_decide=can_decide(a),
            age_days=_age_days(a.requested_at),
            deciders=deciders(a)))
    return out


@router.get("", response_model=list[ApprovalOut])
def list_approvals(response: Response, status: str | None = None,
                   request_type: str | None = None, q: str | None = None,
                   paging=Depends(page_params), db: Session = Depends(get_db),
                   user=Depends(require("approval:read"))):
    page, page_size = paging
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.id.desc())
    if status in ("pending", "approved", "rejected", "withdrawn", "cancelled"):
        stmt = stmt.where(ApprovalRequest.status == status)
    if request_type:
        stmt = stmt.where(ApprovalRequest.record_type == request_type)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(ApprovalRequest.document_number.ilike(like)
                          | ApprovalRequest.request_no.ilike(like)
                          | ApprovalRequest.subject.ilike(like))
    rows = [a for a in paginate(db, stmt, response, page, page_size)
            if _category_allowed(db, user, a.record_type)]
    # An employee sees the HR requests they raised, not the whole company's.
    perms = role_permissions(db, user)
    if not ({"hr:write", "hr:attendance_manage", "hr:leave_approve", "hr:payroll_prepare"}
            & perms) and not is_admin(db, user):
        rows = [a for a in rows if not a.record_type.startswith("hr_")
                or a.requested_by == user.id]
    # Payroll amounts are salary data. Only the payroll approver (and the
    # person who submitted the request) may see a payroll approval at all.
    if not is_admin(db, user) and "hr:payroll_approve" not in perms:
        rows = [a for a in rows if a.record_type != "hr_payroll"
                or a.requested_by == user.id]
    # A reporting manager sees only their own chain's HR requests.
    from ..services.hr import scoped_employee_ids
    scope = scoped_employee_ids(db, user)
    if scope is not None:
        def _in_scope(a) -> bool:
            if not a.record_type.startswith("hr_"):
                return True
            if a.requested_by == user.id:
                return True
            emp_id = (a.detail or {}).get("employee_id")
            return emp_id is not None and int(emp_id) in scope
        rows = [a for a in rows if _in_scope(a)]
    return _build(db, rows, user)


@router.post("/{approval_id}/decide", response_model=ApprovalOut)
def decide(approval_id: int, body: DecisionIn, db: Session = Depends(get_db),
           user=Depends(require("approval:read"))):
    first = db.get(ApprovalRequest, approval_id)
    if not first:
        raise HTTPException(404, "Approval request not found")
    if first.record_type == "sales_order":
        out = _decide_sales_order(db, approval_id, body, user)
    elif first.record_type.startswith("hr_"):
        from ..services.hr_approvals import decide_hr_request
        out = decide_hr_request(db, approval_id, body, user)
    elif first.record_type == "invoice_post_billing":
        out = _decide_post_billing(db, approval_id, body, user)
    else:
        raise HTTPException(409, "This request type cannot be decided here")
    # The dashboard counts pending requests, so a decision retires its cached
    # payload: the badge, the KPI and the card must agree on the next load.
    from .dashboard import invalidate_dashboard_cache
    invalidate_dashboard_cache()
    return out


def _decide_sales_order(db: Session, approval_id: int, body: DecisionIn, user):
    first = db.get(ApprovalRequest, approval_id)
    so = db.scalars(select(SalesOrder).where(SalesOrder.id == first.record_id)
                    .with_for_update()).one()
    ar = db.scalars(select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
                    .with_for_update().execution_options(populate_existing=True)).one()
    if ar.status != "pending":
        raise HTTPException(409, f"Request is already {ar.status}")
    if "credit_limit" in (ar.reasons or []) and not is_admin(db, user):
        raise HTTPException(403, "Only an Administrator can decide a request that exceeds "
                                 "the credit limit")
    if "approval:decide" not in role_permissions(db, user) and not is_admin(db, user):
        raise HTTPException(403, "Your role cannot decide sales-order approvals")
    if user.id in (ar.requested_by, so.created_by):
        raise HTTPException(403, "Segregation of duties: you cannot decide a request you "
                                 "raised or created")
    if so.status != "pending_approval":
        raise HTTPException(409, f"Order is {so.status}; nothing to decide")
    approved = body.decision == "approve"
    ar.status = "approved" if approved else "rejected"
    ar.decided_by, ar.decided_at = user.id, datetime.now(timezone.utc)
    ar.decision_reason = body.reason.strip()
    ar.pending_approver_role = None
    so.status = "approved" if approved else "rejected"
    audit(db, user.id, "approval.decide", f"approval:{ar.id}",
          {"decision": body.decision, "reason": ar.decision_reason, "order": so.so_number,
           "reasons": ar.reasons, "administrator": is_admin(db, user)})
    db.commit()
    return _build(db, [ar], user)[0]


def _decide_post_billing(db: Session, approval_id: int, body: DecisionIn, user):
    ar = db.scalars(select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
                    .with_for_update()).one()
    if ar.status != "pending":
        raise HTTPException(409, f"Request is already {ar.status}")
    if not is_admin(db, user):
        raise HTTPException(403, "Only an Administrator can decide a post-billing edit")
    if ar.requested_by == user.id:
        raise HTTPException(403, "A post-billing edit needs a different Administrator to "
                                 "decide it")
    inv = db.get(Invoice, ar.record_id, with_for_update=True)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    changes = dict((ar.detail or {}).get("changes") or {})
    approved = body.decision == "approve"
    if approved:
        from .invoices import AMENDABLE
        for field, value in changes.items():
            if field in AMENDABLE:
                setattr(inv, field, value)
    ar.status = "approved" if approved else "rejected"
    ar.decided_by, ar.decided_at = user.id, datetime.now(timezone.utc)
    ar.decision_reason = body.reason.strip()
    ar.pending_approver_role = None
    audit(db, user.id, "invoice.amend_decision", f"invoice:{inv.id}",
          {"number": inv.invoice_number, "decision": body.decision,
           "reason": ar.decision_reason, "changes": changes})
    db.commit()
    return _build(db, [ar], user)[0]


class AmendRequestIn(BaseModel):
    """A non-Admin asks for a post-billing change; only the Admin decides."""
    reason: str = Field(min_length=3, max_length=300)
    changes: dict = Field(default_factory=dict)


@router.post("/post-billing/{invoice_id}", response_model=ApprovalOut, status_code=201)
def request_post_billing_change(invoice_id: int, body: AmendRequestIn,
                                db: Session = Depends(get_db),
                                user=Depends(require("invoice:write"))):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status != "issued":
        raise HTTPException(409, "Only an issued invoice can be amended")
    allowed = {"delivery_challan_number", "vehicle_number", "transporter_name",
               "eway_bill_number", "eway_bill_date"}
    changes = {k: v for k, v in body.changes.items() if k in allowed}
    if not changes:
        raise HTTPException(422, "Choose at least one permitted field to change")
    ar = ApprovalRequest(
        record_type="invoice_post_billing", record_id=inv.id,
        reasons=["post_billing"], requested_by=user.id,
        request_no=f"AP-{datetime.now():%Y%m%d}-{inv.id:04d}"[:40],
        document_number=inv.invoice_number, subject=f"Invoice {inv.invoice_number}",
        pending_approver_role="admin",
        detail={"changes": changes, "requested_reason": body.reason.strip()})
    db.add(ar)
    db.flush()
    audit(db, user.id, "invoice.amend_request", f"invoice:{inv.id}",
          {"number": inv.invoice_number, "reason": body.reason.strip(),
           "fields": sorted(changes)})
    db.commit()
    return _build(db, [ar], user)[0]
