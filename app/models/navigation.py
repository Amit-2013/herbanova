"""Navigation nodes and the feature registry (WP-4).

Two tables, both additive. `nav_nodes` holds the 5 → 14 → 20 → 25 menu tree and
`feature_registry` holds the 14 feature rows. There is deliberately no alias
table: the single shipped alias (`distributors` → `customers`) lives in
`nav_nodes.aliases`.

Both `feature_key` columns are plain strings with **no foreign key** to
`feature_flags.key` (risk R-01). Registration and switch state are independent:
a feature can be registered with no flag row (ON by default), and deleting every
switch row cannot break, cascade or block the registry. The service validates
the key against `app/core/features.py`; the database cannot express "belongs to
the code catalogue" as a constraint.
"""
from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index,
                        Integer, JSON, SmallInteger, String, Text, UniqueConstraint,
                        func, text)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base


class NavNode(Base):
    __tablename__ = "nav_nodes"
    __table_args__ = (
        UniqueConstraint("node_key", name="uq_nav_nodes_key"),
        CheckConstraint("depth BETWEEN 1 AND 4", name="ck_nav_nodes_depth"),
        CheckConstraint(
            "(depth = 1 AND kind = 'module') OR (depth = 2 AND kind = 'category') "
            "OR (depth = 3 AND kind = 'group') OR (depth = 4 AND kind = 'screen')",
            name="ck_nav_nodes_kind_depth"),
        CheckConstraint("(kind = 'screen') = (view IS NOT NULL)",
                        name="ck_nav_nodes_screen_view"),
        CheckConstraint("(kind = 'screen') = (route IS NOT NULL)",
                        name="ck_nav_nodes_screen_route"),
        CheckConstraint("(kind = 'screen') = (component_key IS NOT NULL)",
                        name="ck_nav_nodes_screen_component"),
        CheckConstraint("menu_rule IN ('always', 'never', 'menu_any')",
                        name="ck_nav_nodes_menu_rule"),
        CheckConstraint("sort_order >= 0", name="ck_nav_nodes_sort"),
        CheckConstraint(
            "NOT is_home OR (depth = 4 AND view IS NOT NULL "
            "AND feature_key IS NULL)",
            name="ck_nav_nodes_home"),
        Index("ix_nav_nodes_parent_order", "parent_id", "sort_order"),
        Index("ix_nav_nodes_feature", "feature_key"),
        Index("ix_nav_nodes_active", "active"),
        Index("ux_nav_nodes_home", "is_home", unique=True,
              postgresql_where=text("is_home")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("nav_nodes.id", ondelete="RESTRICT"), nullable=True)
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    view: Mapped[str | None] = mapped_column(String(32), nullable=True)
    route: Mapped[str | None] = mapped_column(String(120), nullable=True)
    component_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # No ForeignKey here: see the module docstring and design §4.1 / R-01.
    feature_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    permission_any: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                                 server_default=text("'[]'::json"))
    menu_rule: Mapped[str] = mapped_column(String(16), nullable=False, default="always",
                                           server_default="always")
    menu_any: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                           server_default=text("'[]'::json"))
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                          server_default=text("'[]'::json"))
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                          server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                            server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                         server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 nullable=False, server_default=func.now(),
                                                 onupdate=func.now())


class FeatureRegistry(Base):
    """Ownership of one feature. Switch state stays in `feature_flags` only."""

    __tablename__ = "feature_registry"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'planned', 'retired')",
                        name="ck_feature_registry_status"),
        CheckConstraint("json_array_length(api_prefixes) >= 0",
                        name="ck_feature_registry_prefixes"),
    )

    # No ForeignKey to feature_flags.key (R-01): registration is not switch state.
    feature_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active",
                                        server_default="active")
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                         server_default=text("false"))
    api_prefixes: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                               server_default=text("'[]'::json"))
    # Empty until a verified feature→table derivation exists (WP-5). Never guess.
    tables: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                         server_default=text("'[]'::json"))
    permissions: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                              server_default=text("'[]'::json"))
    depends_on: Mapped[list] = mapped_column(JSON, nullable=False, default=list,
                                             server_default=text("'[]'::json"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 nullable=False, server_default=func.now(),
                                                 onupdate=func.now())
