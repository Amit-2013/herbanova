from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.db import Base
# Every model module must be imported here. If one is missing, `alembic revision
# --autogenerate` cannot see its tables and will propose DROPping them (the
# `payments` table was at risk before this list was completed).
import app.models.core      # noqa: F401  users, products, batches, POs, SOs, invoices, notes, leads
import app.models.hr        # noqa: F401  HR tables
import app.models.accounts  # noqa: F401  payments (receipts and payments)
import app.models.users     # noqa: F401  roles, employees
import app.models.tax       # noqa: F401  company_profile, tax_rates, discount_slabs
import app.models.suppliers # noqa: F401  suppliers, goods_receipts

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# single source of truth: same DATABASE_URL as the running app
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()