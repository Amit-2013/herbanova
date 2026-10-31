from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from .core.config import settings
from .core.limiter import limiter
from .api import (accounts, admin, approvals, audit, auth, credit_notes, dashboard, debit_notes, db_reset, distributors, email_reports, employees,
                  hr, inventory, invoices, leads, modules, printing, products, purchase_orders,
                  reports, roles, sales_orders, suppliers, tax, users)

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

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(employees.router)
app.include_router(hr.router)
app.include_router(db_reset.router)
app.include_router(admin.router)
app.include_router(audit.router)
app.include_router(modules.router)
app.include_router(dashboard.router)
app.include_router(accounts.router)
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
