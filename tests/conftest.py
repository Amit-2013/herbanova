"""Test harness: a separate PostgreSQL database, migrated with Alembic.

The production/dev database is never touched. The test database is created if
missing; migrations and seed rows are idempotent.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.core.config import settings

URL = make_url(settings.database_url)
TEST_URL = URL.set(database="herbanova_bcs_test")
settings.database_url = TEST_URL.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = settings.database_url
os.environ["APP_ENV"] = "local"

ROOT = Path(__file__).resolve().parent.parent


def _create_database() -> None:
    """Recreate the dedicated test database so every run starts from migrations.

    The name is checked to end in `_test`: this function drops a database and must
    never be pointed at the application's own data.
    """
    name = TEST_URL.database
    if not name or not name.endswith("_test"):
        raise RuntimeError(f"refusing to reset non-test database {name!r}")
    engine = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :name AND pid <> pg_backend_pid()"), {"name": name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _create_database()
    env = {**os.environ, "DATABASE_URL": settings.database_url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                   env=env, check=True, capture_output=True, text=True)
    from app.core.db import engine, SessionLocal
    from app.models.core import User
    from app.models.users import Employee, Role
    from app.core.security import hash_password
    with SessionLocal() as db:
        roles = {r.name: r for r in db.scalars(select(Role)).all()}
        for name in ("admin", "sales", "inventory", "viewer"):
            if name not in roles:
                raise RuntimeError(f"seeded role {name} missing")
        if not db.scalar(select(User).where(User.username == "admin")):
            e = Employee(code="ADMIN", full_name="Admin", designation="Administrator",
                         status="active")
            db.add(e)
            db.flush()
            db.add(User(username="admin", username_key="admin",
                        password_hash=hash_password("TestPass!123"), role="admin",
                        role_id=roles["admin"].id, employee_id=e.id))
        db.commit()
    yield
    engine.dispose()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.core.db import SessionLocal
    from app.core.security import make_token
    from app.models.core import User
    from app.models.users import Role, Employee
    from app.services.audit import audit

    with SessionLocal() as db:
        roles = {r.name: r for r in db.scalars(select(Role)).all()}
        tokens = {}
        for name, role in (("admin", "admin"), ("sales", "sales"),
                           ("inventory", "inventory"), ("viewer", "viewer"),
                           ("hr_manager", "hr_manager"), ("payroll", "payroll_officer")):
            user = db.scalar(select(User).where(User.username == f"t_{name}"))
            if not user:
                emp = Employee(code=f"T_{name}"[:30].upper(), full_name=f"Test {name}",
                               status="active")
                db.add(emp)
                db.flush()
                user = User(username=f"t_{name}", username_key=f"t_{name}",
                            password_hash="x", role=role, role_id=roles[role].id,
                            employee_id=emp.id)
                db.add(user)
                db.flush()
            tokens[name] = (make_token(user.id, user.token_version or 1), user)
        db.commit()
        ids = {name: u.id for name, (_, u) in tokens.items()}
        emp_ids = {name: u.employee_id for name, (_, u) in tokens.items()}
    from app.main import app
    c = TestClient(app)

    def as_user(name: str):
        c.cookies.set("session", tokens[name][0])
        return c

    c.as_user = as_user
    c.ids = ids
    c.employee_ids = emp_ids
    c.as_user("admin")
    return c


@pytest.fixture(scope="session")
def world(database):
    """A product with an HSN, a tax rate, a distributor, stock and a company profile."""
    from datetime import date, timedelta
    from decimal import Decimal
    from uuid import uuid4

    from app.core.db import SessionLocal
    from app.models.core import Batch, Distributor, Product, Warehouse
    from app.models.suppliers import Supplier
    from app.models.tax import CompanyProfile, TaxRate

    suffix = uuid4().hex[:6].upper()
    hsn = "30049099"
    with SessionLocal() as db:
        company = db.scalar(select(CompanyProfile))
        if company is None:
            company = CompanyProfile(legal_name="Herbanova Test Co", gstin="27AAAAA0000A1Z5",
                                     state_code="27", registration_type="regular")
            db.add(company)
            db.flush()
        if not db.scalar(select(TaxRate).where(TaxRate.hsn == hsn)):
            db.add(TaxRate(hsn=hsn, cgst_rate=Decimal("9"), sgst_rate=Decimal("9"),
                           igst_rate=Decimal("18"), cess_rate=Decimal("0"),
                           effective_from=date.today() - timedelta(days=365),
                           created_by=1))
        product = Product(sku=f"TST-{suffix}", name="Test product", pack_size="10 tabs",
                          mrp=Decimal("100"), hsn=hsn, uqc="TAB", status="active")
        distributor = Distributor(code=f"TD-{suffix}", name="Test distributor",
                                  territory="Test", status="active",
                                  credit_limit=Decimal("5000"), state_code="27",
                                  gstin=f"27{suffix[:5]}000A1Z5"[:15],
                                  registration_type="regular")
        warehouse = Warehouse(name=f"Test warehouse {suffix}")
        supplier = Supplier(code=f"TS-{suffix}", name="Test supplier", status="active")
        db.add_all([product, distributor, warehouse, supplier])
        db.flush()
        batch = Batch(product_id=product.id, warehouse_id=warehouse.id,
                      batch_no=f"B-{suffix}", on_hand=Decimal("1000"))
        db.add(batch)
        db.commit()
        return {"product_id": product.id, "sku": product.sku, "hsn": hsn,
                "distributor_id": distributor.id, "warehouse_id": warehouse.id,
                "supplier_id": supplier.id, "batch_id": batch.id,
                "company_id": company.id}
