"""Database access for the navigation API (WP-4b).

This module only reads: the two registry tables and the feature switches. It is
kept apart from `navigation_registry.py`, which stays pure and importable
without a database (the migration seed generator depends on that).

A missing table is reported as `None`, never as a partial registry: the endpoint
answers 503, because half a menu is worse than an honest error (design §6.1).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..models.navigation import FeatureRegistry, NavNode
from .feature_store import stored_flags

NODE_FIELDS = (
    "id", "parent_id", "depth", "node_key", "label", "kind", "view", "route",
    "component_key", "feature_key", "permission_any", "menu_rule", "menu_any",
    "aliases", "is_home", "sort_order", "active",
)
FEATURE_FIELDS = (
    "feature_key", "label", "description", "status", "locked", "api_prefixes",
    "tables", "permissions", "depends_on",
)


def _node(row: NavNode) -> dict:
    row_dict = {field: getattr(row, field) for field in NODE_FIELDS}
    for field in ("permission_any", "menu_any", "aliases"):
        row_dict[field] = list(row_dict[field] or [])
    return row_dict


def _feature(row: FeatureRegistry) -> dict:
    row_dict = {field: getattr(row, field) for field in FEATURE_FIELDS}
    for field in ("api_prefixes", "tables", "permissions", "depends_on"):
        row_dict[field] = list(row_dict[field] or [])
    return row_dict


def load_registry(db) -> tuple[list[dict], list[dict], dict[str, bool]] | None:
    """Every node, every feature and the stored switch states.

    Order is fixed here rather than left to the database: the fingerprint and
    the rendered response must not change because a query plan changed.
    """
    try:
        nodes = [_node(row) for row in db.scalars(select(NavNode)).all()]
        features = [_feature(row) for row in db.scalars(select(FeatureRegistry)).all()]
    except SQLAlchemyError:
        db.rollback()
        return None
    nodes.sort(key=lambda n: (n["depth"], n["sort_order"], n["id"]))
    features.sort(key=lambda f: f["feature_key"])
    return nodes, features, stored_flags(db)


def load_features(db) -> tuple[list[dict], dict[str, bool]] | None:
    """Just the feature rows and switch states, for the shared closure.

    The route gate and the effective permission set need the dependencies but
    not the menu nodes, so they read the smaller pair. A missing table means an
    installation before Alembic 0031 and is reported as `None`.
    """
    try:
        features = [_feature(row) for row in db.scalars(select(FeatureRegistry)).all()]
    except SQLAlchemyError:
        db.rollback()
        return None
    features.sort(key=lambda f: f["feature_key"])
    return features, stored_flags(db)


def feature_available(features: list[dict], flags: dict[str, bool]) -> set[str]:
    """Feature keys the registry itself makes available.

    A switch row is not enough: a planned or retired feature, or one whose
    dependency is unavailable, is not something the browser may offer. All 14
    shipped rows are active with no dependencies, so this closes a gap rather
    than changing today's menu.
    """
    on = {row["feature_key"] for row in features
          if row["locked"] or flags.get(row["feature_key"], True)}
    status = {row["feature_key"]: row["status"] for row in features}
    deps = {row["feature_key"]: row["depends_on"] for row in features}

    resolved: dict[str, bool] = {}

    def usable(key: str, path: frozenset[str]) -> bool:
        if key in resolved:
            return resolved[key]
        if key in path:                  # validation refuses a cycle; fail closed
            return False
        ok = (status.get(key) == "active" and key in on
              and all(usable(dep, path | {key}) for dep in deps.get(key, ())))
        resolved[key] = ok
        return ok

    return {key for key in deps if usable(key, frozenset())}
