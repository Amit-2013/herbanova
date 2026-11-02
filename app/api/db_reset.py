"""Guarded database reset (Administrator only).

The four steps are separate endpoints and each one validates the previous step
on the server: a token signed for that exact stage, a run journal that records
where the run actually is, and — for the final step — a separate reset key.
Skipping a step is not a UI mistake, it is a rejected request.

The old ``POST /api/db/reset`` endpoint wiped business data with a single
secondary password and no backup. It is gone; the path now answers 410 and
points at this flow, so an old caller cannot destroy a database by accident.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.rbac import require_admin
from ..services import db_reset

router = APIRouter(prefix="/api/db-reset", tags=["database reset"])
legacy_router = APIRouter(tags=["database reset"])


class BeginRequest(BaseModel):
    mode: str = "business"
    password: str = Field(min_length=1)
    phrase: str = Field(min_length=1)


class StepRequest(BaseModel):
    run_id: str
    token: str


class ExecuteRequest(StepRequest):
    reset_key: str = Field(min_length=1)


class CancelRequest(BaseModel):
    run_id: str


@router.get("/status", summary="Whether the guarded reset is available")
def status(actor=Depends(require_admin("db:reset"))):
    state = db_reset.lock_state(actor.id)
    return {
        "enabled": db_reset.settings.db_reset_enabled,
        "database": db_reset.database_name(),
        "phrase": f"RESET {db_reset.database_name()}",
        "prerequisites": db_reset.prerequisites(),
        "locked": state["locked"],
        "locked_until": state["locked_until"],
        "failures": state["failures"],
        "max_attempts": db_reset.settings.db_reset_max_attempts,
        "maintenance": db_reset.current_maintenance(),
        "modes": [
            {"key": "business", "label": "Business data only",
             "detail": "Clears documents, stock, payments and HR transactions. Keeps users, "
                       "employees, roles, settings and master data."},
            {"key": "full", "label": "Full reset",
             "detail": "Drops the schema, replays the migrations and recreates the base "
                       "Administrator. Everyone signs in again."},
        ],
        "recent": db_reset.audit_tail(10),
    }


@router.post("/begin", summary="Step 1: login password and confirmation phrase")
def begin(req: BeginRequest, actor=Depends(require_admin("db:reset"))):
    return db_reset.begin(actor, req.mode, req.password, req.phrase)


@router.post("/backup", summary="Step 2: two encrypted backups on separate devices")
def backup(req: StepRequest, actor=Depends(require_admin("db:reset"))):
    return db_reset.create_backups(actor, req.run_id, req.token)


@router.post("/verify", summary="Step 3: checksum, restore test and row counts")
def verify(req: StepRequest, actor=Depends(require_admin("db:reset"))):
    return db_reset.verify_backups(actor, req.run_id, req.token)


@router.post("/execute", summary="Step 4: separate reset key, then reset")
def execute(req: ExecuteRequest, actor=Depends(require_admin("db:reset"))):
    return db_reset.execute(actor, req.run_id, req.token, req.reset_key)


@router.post("/cancel", summary="Abandon a run and resume writes")
def cancel(req: CancelRequest, actor=Depends(require_admin("db:reset"))):
    return db_reset.cancel(actor, req.run_id)


@legacy_router.post("/api/db/reset", include_in_schema=False)
def legacy_reset():
    raise HTTPException(
        410, "The single-step wipe has been removed. Use Reset Database in Settings & "
             "Administration: it takes two encrypted backups, verifies them and asks for a "
             "separate reset key.")
