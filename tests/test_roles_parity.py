"""Frozen role parity and permission-catalogue coverage (AUD-015 / AUD-024).

These tests are the executable form of the promise in `app/core/permissions.py`:
the catalogue is the single source of truth, the seeded baseline roles match the
frozen sets, and no route or report can guard a permission the catalogue does
not define.
"""
import ast
import re
from pathlib import Path

from sqlalchemy import select

from app.core.permissions import BASELINE_ROLE_PERMS, PERMISSION_KEYS, PERMISSIONS
from app.services import reports

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"


def _guarded_permissions() -> set[str]:
    used: set[str] = set()
    for path in API_DIR.glob("*.py"):
        used.update(re.findall(r'require(?:_admin)?\(\s*"([^"]+)"',
                               path.read_text(encoding="utf-8")))
    return used


def _live_roles() -> dict[str, set[str]]:
    from app.core.db import SessionLocal
    from app.models.users import Role
    with SessionLocal() as db:
        return {r.name: set(r.permissions or [])
                for r in db.scalars(select(Role)).all()}


def _catalogue_literals() -> list[str]:
    """The keys written inside the PERMISSIONS dict literal only.

    Parsing the AST matters because the file also holds the parent map, whose
    keys repeat the catalogue; a plain regex over the file would count them
    twice and hide a real duplicate in the catalogue itself.
    """
    source = (Path(__file__).resolve().parent.parent / "app" / "core" / "permissions.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        target = getattr(node, "target", None)
        if isinstance(node, ast.AnnAssign) and getattr(target, "id", "") == "PERMISSIONS":
            return [key.value for key in node.value.keys
                    if isinstance(key, ast.Constant)]
    raise AssertionError("PERMISSIONS dict literal not found")


def test_catalogue_has_no_duplicate_keys():
    # PERMISSIONS is a dict, so a duplicate literal would be silently lost;
    # comparing the parsed source count catches an accidental redefinition.
    literal_keys = _catalogue_literals()
    assert len(literal_keys) == len(set(literal_keys)) == len(PERMISSIONS)


def test_every_route_guards_a_known_permission():
    unknown = _guarded_permissions() - PERMISSION_KEYS
    assert not unknown, f"routes guard permissions missing from the catalogue: {sorted(unknown)}"


def test_every_report_uses_a_known_permission():
    unknown = {key: value[3] for key, value in reports.CATALOG.items()
               if value[3] not in PERMISSION_KEYS}
    assert not unknown, f"reports guard unknown permissions: {unknown}"


def test_baseline_roles_only_use_catalogue_keys():
    for name, perms in BASELINE_ROLE_PERMS.items():
        extra = perms - PERMISSION_KEYS
        assert not extra, f"baseline role {name!r} carries unknown keys: {sorted(extra)}"


def test_administrator_holds_the_whole_catalogue():
    assert BASELINE_ROLE_PERMS["admin"] == PERMISSION_KEYS


def test_seeded_roles_match_the_frozen_baseline(database):
    live = _live_roles()
    for name, expected in BASELINE_ROLE_PERMS.items():
        assert name in live, f"seeded role {name!r} is missing"
        assert live[name] == expected, (
            f"{name!r} drifted from the frozen set: "
            f"extra={sorted(live[name] - expected)} missing={sorted(expected - live[name])}")


def test_no_role_carries_an_unknown_permission(database):
    live = _live_roles()
    unknown = {name: sorted(perms - PERMISSION_KEYS)
               for name, perms in live.items() if perms - PERMISSION_KEYS}
    assert not unknown, f"roles carry permissions outside the catalogue: {unknown}"
