"""Read and write the central feature switches (app/core/features.py).

Every read tolerates a missing table: an installation that has not run
Alembic 0016 yet keeps the previous behaviour (every module available) instead
of failing every request. A row that is absent means ON, so the table only
needs the switches the Administrator has actually changed.
"""
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..core.features import FEATURES, FEATURE_BY_KEY
from ..models.settings import FeatureFlag


def stored_flags(db) -> dict[str, bool]:
    try:
        return {row.key: bool(row.enabled) for row in db.scalars(select(FeatureFlag)).all()}
    except SQLAlchemyError:
        db.rollback()
        return {}


def feature_rows(db) -> list[dict]:
    stored = stored_flags(db)
    return [{
        "key": f.key,
        "label": f.label,
        "description": f.description,
        "enabled": True if f.locked else stored.get(f.key, True),
        "locked": f.locked,
        "permissions": sorted(f.permissions),
        "views": list(f.views),
    } for f in FEATURES]


def enabled_keys(db) -> set[str]:
    return {row["key"] for row in feature_rows(db) if row["enabled"]}


def disabled_permissions(db) -> set[str]:
    """Permissions that belong to a switched-off feature, for the effective set."""
    return {key for row in feature_rows(db) if not row["enabled"]
            for key in row["permissions"]}


def is_enabled(db, key: str) -> bool:
    feature = FEATURE_BY_KEY.get(key)
    if feature is None:
        return True
    if feature.locked:
        return True
    return stored_flags(db).get(key, True)


def set_flag(db, key: str, enabled: bool, actor_id: int | None) -> FeatureFlag:
    row = db.get(FeatureFlag, key)
    if row is None:
        row = FeatureFlag(key=key, enabled=enabled, updated_by=actor_id)
        db.add(row)
    else:
        row.enabled = enabled
        row.updated_by = actor_id
    db.flush()
    return row
