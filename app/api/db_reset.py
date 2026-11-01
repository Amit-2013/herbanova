"""Database wipe endpoint (admin only, gated by the admin secondary password).

This is not a substitute for a verified backup. The documented recovery tool is
the backup/restore test: ``python backup_restore_test.py``. Before any wipe, the
administration owner should have a verified restore captured in audit evidence.

The wipe is deliberately limited to a local/test installation with
``DEMO_MODE=true``. It clears business data but preserves users, roles and
employees so the administrator can still sign in afterwards.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rbac import require_admin
from app.core.security import verify_secondary_password
from app.models.core import User
from app.services.audit import audit

router = APIRouter()


class ResetRequest(BaseModel):
    secondary_password: str


class ResetResponse(BaseModel):
    cleared_at: str
    db_reset_count: int


# Tables whose rows are wiped by the reset. Users, roles and employees are
# deliberately absent so the application still has accounts to sign in with.
# This must track the business tables in the current schema; the endpoint
# intersects it with the tables that actually exist, so an older database does
# not fail because a newer table is missing.
_RESET_TABLES = frozenset({
    "approval_requests",
    "audit_log",
    "batches",
    "company_profile",
    "credit_note_lines",
    "credit_notes",
    "debit_note_lines",
    "debit_notes",
    "discount_slabs",
    "distributors",
    "document_sequences",
    "goods_receipt_lines",
    "goods_receipts",
    "invoice_lines",
    "invoices",
    "lead_activities",
    "leads",
    "print_logs",
    "products",
    "purchase_order_lines",
    "purchase_orders",
    "sales_order_lines",
    "sales_orders",
    "stock_movements",
    "suppliers",
    "tax_rates",
    "warehouses",
})


def _is_demo(db: Session) -> bool:
    """Only allow the wipe on the local/test demo installation."""
    if not settings.demo_mode:
        return False
    if settings.app_env not in {"local", "test"}:
        return False
    existing = {t for t in inspect(db.bind).get_table_names(schema="public")
                if t in _RESET_TABLES}
    if not existing:
        raise HTTPException(
            status_code=409,
            detail="No business data tables found; run the demo seed before reset.",
        )
    return True


def _clear_business_data(db: Session) -> list[tuple[str, int]]:
    """Truncate every business table, returning the row counts from before."""
    existing = set(inspect(db.bind).get_table_names(schema="public"))
    tables = sorted(_RESET_TABLES & existing)
    if not tables:
        raise HTTPException(
            status_code=409,
            detail="No business data tables found; run the demo seed before reset.",
        )

    counted = [
        (table, int(db.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0))
        for table in tables
    ]
    # One statement keeps the wipe transactional. CASCADE covers any table that
    # references a listed table but is not itself listed; users, roles and
    # employees are not referenced by any of these tables, so they survive.
    db.execute(text("TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tables)
                    + " RESTART IDENTITY CASCADE"))
    return counted


@router.post("/api/db/reset", response_model=ResetResponse, summary="Wipe all business data")
def reset_db(req: ResetRequest, db: Session = Depends(get_db),
             actor=Depends(require_admin("db:reset"))):
    admin = db.get(User, actor.id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=403, detail="The acting administrator account is not active.")

    if not _is_demo(db):
        raise HTTPException(
            status_code=403,
            detail="Database reset is only available when DEMO_MODE=true and "
                   "APP_ENV is local or test.",
        )

    # Ask for the admin's secondary password, not the daily login password. This
    # is a separate secret the owner sets with /api/admin/secondary-password and
    # rotates independently.
    if not admin.reset_password_secondary_hash:
        raise HTTPException(
            status_code=403,
            detail="This administrator has no secondary password set. "
            "Set one with POST /api/admin/secondary-password before reset.",
        )

    if not verify_secondary_password(admin.reset_password_secondary_hash,
                                     req.secondary_password):
        audit(db, actor.id, "db.reset_failed", f"admin {admin.username}",
              {"attempted": True})
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="Secondary password is incorrect for this administrator.",
        )

    cleared = _clear_business_data(db)
    now = datetime.now(timezone.utc)
    admin.db_reset_count = (admin.db_reset_count or 0) + 1
    admin.db_reset_at = now
    audit(db, actor.id, "db.reset", f"admin {admin.username}", {
        "tables_cleared": len(cleared),
        "rows_cleared": sum(count for _, count in cleared),
        "reset_count": admin.db_reset_count,
    })
    db.commit()
    return ResetResponse(cleared_at=now.isoformat(), db_reset_count=admin.db_reset_count)
