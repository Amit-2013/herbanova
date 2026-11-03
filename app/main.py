from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.concurrency import run_in_threadpool
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from .core.config import settings
from .core.features import FEATURE_BY_KEY, feature_for_path, is_public_exception
from .core.limiter import limiter
from .api import (accounts, admin, approvals, audit, auth, costs, credit_notes, dashboard,
                  debit_notes, db_reset, distributors, email_reports, email_settings,
                  employees, expenses, features, foc, gst, hr, inventory, invoices, ledger, leads, modules, periods, printing, products,
                  purchase_orders, reports, roles, sales_orders, suppliers, tax, users)

app = FastAPI(title="HERBANOVA Business Control System")
app.state.limiter = limiter

# Sentry error tracking initialization
sentry_dsn = __import__("os").getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FastApiIntegration()],
        environment=__import__("os").getenv("APP_ENV", "local"),
        traces_sample_rate=1.0,
    )

@app.exception_handler(RateLimitExceeded)
async def _rate_limited(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429,
                        content={"detail": "Too many requests. Please wait a moment and try again."})


def _feature_on(key: str) -> bool:
    from .core.db import SessionLocal
    from .services.feature_store import is_enabled
    with SessionLocal() as db:
        return is_enabled(db, key)


@app.middleware("http")
async def _feature_gate(request: Request, call_next):
    """Refuse a switched-off module's API whatever else the route would allow.

    This sits in front of the routers so an endpoint reached with only
    `require_login` (the dashboard drill-downs, for example) is covered too.
    Permissions are narrowed as well (rbac.role_permissions), so the two checks
    agree. The public unsubscribe link is exempt.
    """
    path = request.url.path
    if path.startswith("/api/") and not is_public_exception(path):
        key = feature_for_path(path)
        if key and not await run_in_threadpool(_feature_on, key):
            return JSONResponse(status_code=403, content={
                "detail": f"{FEATURE_BY_KEY[key].label} is switched off by the Administrator"})
    return await call_next(request)


@app.middleware("http")
async def _maintenance_gate(request: Request, call_next):
    """Pause writes while a guarded database reset is running.

    Reads stay open so the reset screen can show progress; the reset's own
    endpoints and logout must work, otherwise the operator could not finish or
    leave. The window expires on its own, so an abandoned run cannot freeze the
    application for ever.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return await call_next(request)
    path = request.url.path
    if path.startswith("/api/db-reset") or path in ("/api/health", "/api/auth/logout"):
        return await call_next(request)
    if path.startswith("/api/"):
        from .services.db_reset import current_maintenance
        state = await run_in_threadpool(current_maintenance)
        if state:
            return JSONResponse(status_code=503, headers={"Retry-After": "60"}, content={
                "detail": "A database reset is in progress. Writes are paused until it finishes."})
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(features.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(employees.router)
app.include_router(hr.router)
app.include_router(db_reset.router)
app.include_router(db_reset.legacy_router)
app.include_router(admin.router)
app.include_router(audit.router)
app.include_router(modules.router)
app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(gst.router)
app.include_router(ledger.router)
app.include_router(costs.router)
app.include_router(costs.lock_router)
app.include_router(periods.router)
app.include_router(expenses.router)
app.include_router(foc.router)
app.include_router(products.router)
app.include_router(suppliers.router)
app.include_router(purchase_orders.router)
app.include_router(inventory.router)
app.include_router(distributors.router)
app.include_router(tax.router)
app.include_router(sales_orders.router)
app.include_router(invoices.router)
app.include_router(credit_notes.router)
app.include_router(debit_notes.router)
app.include_router(printing.router)
app.include_router(approvals.router)
app.include_router(leads.router)
app.include_router(reports.router)
app.include_router(email_reports.router)
app.include_router(email_reports.public_router)
app.include_router(email_settings.router)

from pathlib import Path
from fastapi.staticfiles import StaticFiles
app.mount("/ui", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static", html=True), name="ui")

@app.middleware("http")
async def _revalidate_ui(request: Request, call_next):
    """The single-page UI changes between releases, so the browser must
    revalidate it instead of reusing a heuristically cached copy; the ETag still
    makes every revalidation a cheap 304."""
    response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-cache"
    return response

@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.app_env}

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")
