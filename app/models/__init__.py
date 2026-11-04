"""Import every model module so all tables are registered with the metadata
(Alembic autogenerate, mapper configuration and reset_demo's safety net all
depend on this)."""
from . import (accounts, core, costs, email, expenses, foc, hr, navigation, settings,
               signin, suppliers, tax, users)  # noqa: F401
