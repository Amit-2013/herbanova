"""Decision handlers for HR approval requests.

Each handler applies the underlying change and the request decision in one
transaction. The central Approvals API only routes to this module; the
permissions and segregation-of-duties rules are enforced here.
"""
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rbac import is_admin, role_permissions
from ..models.core import ApprovalRequest, User
from ..models.hr import (Attendance, AttendanceCorrection, LeaveApplication, LeaveBalance,
                         LeaveType, ODRequest, PayrollPeriod)
from ..models.users import Employee
from . import hr as hr_svc
from .audit import audit


def _perm(db: Session, user, *keys: str) -> bool:
    perms = role_permissions(db, user)
    return is_admin(db, user) or any(k in perms for k in keys)


def _request(db: Session, approval_id: int) -> ApprovalRequest:
    ar = db.scalars(select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
                    .with_for_update()).first()
    if not ar:
        raise HTTPException(404, "Approval request not found")
    if ar.status != "pending":
        raise HTTPException(409, f"Request is already {ar.status}")
    return ar


def _request_employee_id(db: Session, ar: ApprovalRequest) -> int | None:
    kind = ar.record_type
    if kind == "hr_leave":
        app = db.get(LeaveApplication, ar.record_id)
        return app.employee_id if app else None
    if kind == "hr_od":
        od = db.get(ODRequest, ar.record_id)
        return od.employee_id if od else None
    if kind == "hr_attendance_correction":
        corr = db.get(AttendanceCorrection, ar.record_id)
        return corr.employee_id if corr else None
    if kind == "hr_geofence_exception":
        att_id = (ar.detail or {}).get("attendance_id")
        att = db.get(Attendance, int(att_id)) if att_id else None
        return att.employee_id if att else None
    return (ar.detail or {}).get("employee_id")


def _assert_team_scope(db: Session, ar: ApprovalRequest, user) -> None:
    """A reporting manager may only decide requests for their own team."""
    scope = hr_svc.scoped_employee_ids(db, user)
    if scope is None:
        return
    emp_id = _request_employee_id(db, ar)
    if emp_id is None or int(emp_id) not in scope:
        raise HTTPException(403, "That request is outside your team")


def _assert_open(db: Session, scope: str, first: date, last: date | None = None) -> None:
    """A decision may not rewrite a closed month."""
    lock = (hr_svc.active_period_lock(db, scope, first) if last is None
            else hr_svc.active_lock_for_range(db, scope, first, last))
    if lock:
        raise HTTPException(423, f"The {scope} period {lock.year}-{lock.month:02d} is "
                                 f"locked: {lock.reason}")


def decide_hr_request(db: Session, approval_id: int, body, user):
    ar = _request(db, approval_id)
    if ar.requested_by == user.id:
        raise HTTPException(403, "Segregation of duties: you cannot decide a request you raised")
    kind = ar.record_type
    if kind in ("hr_leave", "hr_od"):
        if not _perm(db, user, "hr:leave_approve"):
            raise HTTPException(403, "Your role cannot decide leave or on-duty requests")
        _assert_team_scope(db, ar, user)
        handler = _leave if kind == "hr_leave" else _od
    elif kind in ("hr_attendance_correction", "hr_geofence_exception"):
        if not _perm(db, user, "hr:attendance_manage"):
            raise HTTPException(403, "Your role cannot decide attendance corrections")
        _assert_team_scope(db, ar, user)
        handler = _correction if kind == "hr_attendance_correction" else _geofence
    elif kind == "hr_payroll":
        if not _perm(db, user, "hr:payroll_approve"):
            raise HTTPException(403, "Your role cannot approve payroll")
        handler = _payroll
    else:
        raise HTTPException(409, "This HR request type has no decision handler")
    handler(db, ar, body, user)
    ar.status = "approved" if body.decision == "approve" else "rejected"
    ar.decided_by, ar.decided_at = user.id, datetime.now(timezone.utc)
    ar.decision_reason = body.reason.strip()
    ar.pending_approver_role = None
    audit(db, user.id, "approval.decide", f"approval:{ar.id}",
          {"type": ar.record_type, "decision": body.decision, "reason": ar.decision_reason})
    db.commit()
    from ..api.approvals import _build
    return _build(db, [ar], user)[0]


def _leave(db: Session, ar: ApprovalRequest, body, user):
    app = db.scalars(select(LeaveApplication).where(LeaveApplication.id == ar.record_id)
                     .with_for_update()).first()
    if not app or app.status != "pending":
        raise HTTPException(409, "Leave application is not pending")
    lt = db.get(LeaveType, app.leave_type_id)
    bal = hr_svc.leave_balance(db, app.employee_id, app.leave_type_id, app.date_from.year)
    if body.decision == "approve":
        _assert_open(db, "attendance", app.date_from, app.date_to)
        if bal.pending >= app.days:
            bal.pending -= app.days
        bal.used += app.days
        app.status = "approved"
        hr_svc.apply_attendance_for_leave(db, app, lt)
    else:
        bal.pending = max(0, bal.pending - app.days)
        app.status = "rejected"
    app.decided_by, app.decided_at = user.id, datetime.now(timezone.utc)
    app.remarks = body.reason.strip()


def _od(db: Session, ar: ApprovalRequest, body, user):
    od = db.scalars(select(ODRequest).where(ODRequest.id == ar.record_id)
                    .with_for_update()).first()
    if not od or od.status != "pending":
        raise HTTPException(409, "OD request is not pending")
    if body.decision == "approve":
        _assert_open(db, "attendance", od.date, od.end_date or od.date)
        od.status = "approved"
        hr_svc.apply_attendance_for_od(db, od)
    else:
        od.status = "rejected"
    od.decided_by, od.decided_at = user.id, datetime.now(timezone.utc)
    od.decision_remarks = body.reason.strip()


def _correction(db: Session, ar: ApprovalRequest, body, user):
    corr = db.scalars(select(AttendanceCorrection).where(
        AttendanceCorrection.id == ar.record_id).with_for_update()).first()
    if not corr or corr.status != "pending":
        raise HTTPException(409, "Correction request is not pending")
    if body.decision == "approve":
        att = db.scalars(select(Attendance).where(Attendance.id == corr.attendance_id)
                         .with_for_update()).first()
        if not att:
            raise HTTPException(404, "Attendance record not found")
        _assert_open(db, "attendance", att.date)
        if corr.new_status:
            att.status = corr.new_status
        if corr.new_check_in:
            att.check_in = corr.new_check_in
        if corr.new_check_out:
            att.check_out = corr.new_check_out
        att.remarks = f"Correction approved: {corr.reason}"
        att.approved_by = user.id
        corr.status = "approved"
    else:
        corr.status = "rejected"
    corr.decided_by, corr.decided_at = user.id, datetime.now(timezone.utc)
    corr.remarks = body.reason.strip()


def _geofence(db: Session, ar: ApprovalRequest, body, user):
    att_id = int((ar.detail or {}).get("attendance_id") or 0)
    att = db.get(Attendance, att_id)
    if not att:
        raise HTTPException(404, "Attendance record not found")
    if body.decision == "approve":
        _assert_open(db, "attendance", att.date)
        att.geofence_result = "manual"
        att.approved_by = user.id
        att.remarks = f"Location exception approved: {body.reason.strip()}"


def _payroll(db: Session, ar: ApprovalRequest, body, user):
    period = db.scalars(select(PayrollPeriod).where(PayrollPeriod.id == ar.record_id)
                        .with_for_update()).first()
    if not period or period.status != "under_review":
        raise HTTPException(409, "Payroll period is not under review")
    if period.prepared_by == user.id:
        raise HTTPException(403, "The person who prepared payroll cannot approve it")
    if body.decision == "approve":
        _assert_open(db, "payroll", date(period.year, period.month, 1))
        period.status = "approved"
        period.approved_by = user.id
        period.approved_at = datetime.now(timezone.utc)
        for entry in period.entries:
            entry.status = "approved"
