"""Reports and exports.

Opening a report needs the permission for the data it shows (stock, sales or leads).
Downloading needs 'report:export' as well, and every download is written to the audit
log (who, which report, format, row count) without any personal data.
"""
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.rbac import current_user, require, role_permissions
from ..services import exports, reports
from ..services.audit import audit

router = APIRouter(prefix="/api/reports", tags=["reports"])
MEDIA = {"csv": "text/csv; charset=utf-8",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "pdf": "application/pdf"}


class ColumnOut(BaseModel):
    key: str
    label: str
    type: str


class TableOut(BaseModel):
    key: str
    title: str
    columns: list[ColumnOut]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None
    total_rows: int = 0
    page: int = 1
    page_size: int = 0


class CheckOut(BaseModel):
    name: str
    report_label: str
    report_value: Any
    record_label: str
    record_value: Any
    unit: str
    ok: bool


class ReportOut(BaseModel):
    key: str
    title: str
    category: str
    kind: str
    primary_table: str
    period_from: date | None
    period_to: date | None
    as_at: date
    tables: list[TableOut]
    checks: list[CheckOut]
    limitations: list[str]
    reconciled: bool


class CatalogOut(BaseModel):
    key: str
    title: str
    description: str
    category: str
    kind: str                 # snapshot (as at today) | period (takes from/to dates)
    primary_table: str
    can_export: bool
    filters: list[str] = []   # optional narrowing filters this report accepts


def _perms(user, db: Session) -> set[str]:
    return role_permissions(db, user)


def _open(user, key: str, db: Session) -> None:
    if key not in reports.CATALOG:
        raise HTTPException(404, "Report not found")
    if reports.CATALOG[key][3] not in _perms(user, db):
        raise HTTPException(403, "Your role cannot open this report")


def _period(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to")):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "'from' must not be after 'to'")
    return date_from, date_to


def _filters(key: str, employee_id: int | None = None, department: str | None = None,
             branch_id: int | None = None) -> dict:
    """Validated narrowing filters. A report that cannot use one refuses it rather
    than quietly returning unfiltered figures."""
    given = {k: v for k, v in (("employee_id", employee_id), ("department", department),
                               ("branch_id", branch_id))
             if v not in (None, "") and not (isinstance(v, str) and not v.strip())}
    allowed = reports.FILTER_KEYS.get(key, ())
    unsupported = sorted(k for k in given if k not in allowed)
    if unsupported:
        raise HTTPException(422, "This report does not filter by " + ", ".join(unsupported))
    if isinstance(given.get("department"), str):
        given["department"] = given["department"].strip()
    return given


@router.get("", response_model=list[CatalogOut])
def catalog(db: Session = Depends(get_db), user=Depends(current_user)):
    p = _perms(user, db)
    return [CatalogOut(key=k, title=v[0], description=v[1], category=v[5], kind=v[2],
                       primary_table=v[4], can_export="report:export" in p,
                       filters=list(reports.FILTER_KEYS.get(k, ())))
            for k, v in reports.CATALOG.items() if v[3] in p]


@router.get("/{key}", response_model=ReportOut)
def get_report(key: str, period=Depends(_period), page: int = Query(1, ge=1),
               page_size: int = Query(100, ge=1, le=500), sort: str | None = None,
               direction: Literal["asc", "desc"] = "asc",
               employee_id: int | None = None, department: str | None = None,
               branch_id: int | None = None,
               db: Session = Depends(get_db), user=Depends(current_user)):
    _open(user, key, db)
    rep = reports.build(db, key, *period,
                        _filters(key, employee_id, department, branch_id))
    for t in rep["tables"]:
        all_rows = t["rows"]
        keys = {c["key"] for c in t["columns"]}
        if sort in keys:
            all_rows = sorted(all_rows, key=lambda r: (r.get(sort) is None, r.get(sort)),
                              reverse=direction == "desc")
        t["total_rows"] = len(all_rows)
        t["page"] = page
        t["page_size"] = page_size
        start = (page - 1) * page_size
        t["rows"] = all_rows[start:start + page_size]
    return rep


@router.get("/{key}/export")
def export_report(key: str, fmt: Literal["csv", "xlsx", "pdf"] = Query("csv", alias="format"),
                  table: str | None = None, period=Depends(_period),
                  employee_id: int | None = None, department: str | None = None,
                  branch_id: int | None = None,
                  db: Session = Depends(get_db),
                  user=Depends(require("report:export"))):
    _open(user, key, db)
    rep = reports.build(db, key, *period,
                        _filters(key, employee_id, department, branch_id))
    tkey = table or rep["primary_table"]
    t = exports.table_of(rep, tkey)
    if t is None:
        raise HTTPException(422, "Unknown table. Choose one of: " + ", ".join(x["key"] for x in rep["tables"]))
    if fmt == "csv":
        body = exports.to_csv(rep, tkey, user.username)
    elif fmt == "xlsx":
        body = exports.to_xlsx(rep, user.username)
    else:
        from ..services.reports_pdf import to_pdf
        body = to_pdf(rep, tkey, user.username)
    audit(db, user.id, "report.export", f"report:{key}",
          {"format": fmt, "table": tkey if fmt != "xlsx" else "all", "rows": len(t["rows"]),
           "reconciled": rep["reconciled"]})
    db.commit()
    return Response(content=body, media_type=MEDIA[fmt], headers={
        "Content-Disposition": f'attachment; filename="herbanova-{key}-{date.today():%Y%m%d}.{fmt}"',
        "Cache-Control": "no-store"})