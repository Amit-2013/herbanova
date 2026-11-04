"""Read and write the central feature switches (app/core/features.py).

Every read tolerates a missing table: an installation that has not run
Alembic 0016 yet keeps the previous behaviour (every module available) instead
of failing every request. A row that is absent means ON, so the table only
needs the switches the Administrator has actually changed.

Since WP-4c one answer decides availability everywhere: the route gate, the
effective permissions, the identity payload and the navigation API all use
`available_keys`, so a feature dependency cannot hide a screen from the menu
while its API stays reachable. Before 0031 the registry table is absent and the
stored switches alone decide, exactly as they did before.
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


def _own_switches(db) -> set[str]:
    stored = stored_flags(db)
    return {f.key for f in FEATURES if f.locked or stored.get(f.key, True)}


def available_keys(db) -> set[str]:
    """Feature keys usable after the registry's dependency closure.

    A key absent from the registry (an older seed) keeps its own switch, so the
    closure can only narrow the shipped catalogue, never silently switch off a
    module the registry does not know about.
    """
    from .navigation_store import feature_available, load_features

    own = _own_switches(db)
    loaded = load_features(db)
    if loaded is None:
        return own
    features, flags = loaded
    known = feature_available(features, flags)
    return known | (own - {row["feature_key"] for row in features})


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
    return available_keys(db)


def disabled_permissions(db) -> set[str]:
    """Permissions that belong to an unavailable feature, for the effective set."""
    on = available_keys(db)
    return {key for feature in FEATURES if feature.key not in on
            for key in feature.permissions}


def is_enabled(db, key: str) -> bool:
    if key not in FEATURE_BY_KEY:
        return True
    return key in available_keys(db)


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
