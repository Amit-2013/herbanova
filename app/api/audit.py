"""Audit-trail viewer (FR-12, AUD-044).

Reading needs `audit:read` (administrator); exporting additionally needs
`report:export`. Rows never contain secrets - audit() strips those keys
before the row is written - and this endpoint shows exactly what was stored.
The export is itself audited, without personal data.
"""
import csv
import io
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import require
from ..models.core import AuditLog, User
from ..services.audit import audit
from ..services.exports import IST, safe_text

router = APIRouter(prefix="/api/audit", tags=["audit"])

LIMIT_MAX = 500


def _rows(db: Session, q, limit: int, offset: int):
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.limit(limit).offset(offset)).all()
    out = []
    for log, actor in rows:
        out.append({
            "id": log.id,
            "at": log.at.isoformat() if log.at else None,
            "actor": actor.username if actor else "system",
            "action": log.action,
            "record": log.record,
            "changes": log.changes or {},
        })
    return total, out


def _filtered(actor_id: int | None, action: str | None, record: str | None,
              date_from: date | None, date_to: date | None):
    q = (select(AuditLog, User)
         .join(User, User.id == AuditLog.actor_id, isouter=True))
    if actor_id is not None:
        q = q.where(AuditLog.actor_id == actor_id)
    if action:
        q = q.where(AuditLog.action == action)
    if record:
        q = q.where(AuditLog.record == record)
    if date_from:
        start = datetime_utc(date_from)
        q = q.where(AuditLog.at >= start)
    if date_to:
        q = q.where(AuditLog.at < datetime_utc(date_to + timedelta(days=1)))
    return q.order_by(AuditLog.id.desc())


def datetime_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


@router.get("")
def list_audit(actor_id: int | None = None, action: str | None = None,
               record: str | None = None,
               date_from: date | None = Query(default=None, alias="from"),
               date_to: date | None = Query(default=None, alias="to"),
               limit: int = Query(100, ge=1, le=LIMIT_MAX), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), _=Depends(require("audit:read"))):
    total, rows = _rows(db, _filtered(actor_id, action, record, date_from, date_to),
                        limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "rows": rows}


@router.get("/actions")
def list_actions(db: Session = Depends(get_db), _=Depends(require("audit:read"))):
    """Distinct actions and actors, for the filter drop-downs."""
    actions = db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()
    users = db.scalars(select(User).order_by(User.username)).all()
    return {"actions": list(actions),
            "actors": [{"id": u.id, "username": u.username} for u in users]}


@router.get("/export")
def export_audit(actor_id: int | None = None, action: str | None = None,
                 record: str | None = None,
                 date_from: date | None = Query(default=None, alias="from"),
                 date_to: date | None = Query(default=None, alias="to"),
                 db: Session = Depends(get_db), user=Depends(require("audit:read"))):
    if "report:export" not in _perms(db, user):
        raise HTTPException(403, "Permission denied")
    q = _filtered(actor_id, action, record, date_from, date_to)
    rows = db.execute(q.limit(5000)).all()

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["When (UTC)", "Actor", "Action", "Record", "Changes"])
    for log, actor in rows:
        changes = json.dumps(log.changes or {}, ensure_ascii=False, sort_keys=True)
        w.writerow([log.at.strftime("%Y-%m-%d %H:%M:%S") if log.at else "",
                    safe_text(actor.username if actor else "system"),
                    safe_text(log.action), safe_text(log.record), safe_text(changes)])
    w.writerow([])
    w.writerow(["Report", "Audit trail"])
    w.writerow(["Filters", json.dumps({"actor_id": actor_id, "action": action,
                                      "record": record, "from": str(date_from or ""),
                                      "to": str(date_to or "")})])
    w.writerow(["Rows", str(len(rows))])
    w.writerow(["Generated", datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")])
    w.writerow(["Prepared by", user.username])

    audit(db, user.id, "audit.export", "audit:trail",
          {"rows": len(rows), "action": action or "all"})
    db.commit()
    return Response(content=("\ufeff" + buf.getvalue()).encode("utf-8"),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="audit-trail.csv"'})


def _perms(db: Session, user) -> set[str]:
    from ..core.rbac import role_permissions
    return role_permissions(db, user)
