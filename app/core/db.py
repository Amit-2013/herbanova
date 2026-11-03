from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

# A bounded pool with recycling keeps one idle worker from exhausting the
# server, and discards a connection the network dropped while it sat idle.
# `pool_pre_ping` checks a borrowed connection before the first statement.
_options = {"pool_pre_ping": True, "pool_recycle": settings.db_pool_recycle}
if not settings.database_url.startswith("sqlite"):
    _options.update(pool_size=settings.db_pool_size,
                    max_overflow=settings.db_max_overflow,
                    pool_timeout=settings.db_pool_timeout)
engine = create_engine(settings.database_url, **_options)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    with SessionLocal() as db:
        yield db
