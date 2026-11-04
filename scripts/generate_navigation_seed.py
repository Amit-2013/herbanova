"""Generate and check the literal seed block in migration 0031.

The migration must not import application code (a migration has to keep working
after the code moves on), so the 64 navigation rows and 14 feature rows are
committed as literal data inside the migration (or its `.py.draft` before
activation). This script is the only producer of that block and `--check`
fails when the literal and the catalogue disagree.

    python scripts/generate_navigation_seed.py --check
    python scripts/generate_navigation_seed.py --write

No database connection is opened. `--check` works against the active migration
or the `.py.draft`. `--write` only edits the `.py.draft` while the migration is
still inactive; once `alembic/versions/0031_navigation_registry.py` exists,
`--write` refuses rather than mutating an already-applied revision. A seed
change after activation belongs in a new migration.
"""
from __future__ import annotations

import argparse
import pprint
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.navigation_catalog import (  # noqa: E402
    build_features, build_nodes, catalog_counts, EXPECTED_COUNTS,
)
from app.services.navigation_registry import validate_catalog  # noqa: E402

ACTIVE = ROOT / "alembic" / "versions" / "0031_navigation_registry.py"
SOURCE = ACTIVE if ACTIVE.exists() else ACTIVE.with_name(ACTIVE.name + ".draft")
BEGIN = "# --- BEGIN GENERATED SEED"
END = "# --- END GENERATED SEED ---"


def is_active(path: Path) -> bool:
    """True when `path` is the migration Alembic may already have applied."""
    return path.resolve() == ACTIVE.resolve()


def _block() -> str:
    nodes = pprint.pformat(build_nodes(), width=110, sort_dicts=False)
    features = pprint.pformat(build_features(), width=110, sort_dicts=False)
    return (f"{BEGIN} (scripts/generate_navigation_seed.py) ---\n"
            f"NAV_NODES = {nodes}\n\n"
            f"FEATURE_ROWS = {features}\n"
            f"{END}")


def _replace(text: str, block: str) -> str:
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise SystemExit(f"marker block not found in {SOURCE}")
    return text[:start] + block + text[end + len(END):]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()

    counts = catalog_counts()
    if counts != EXPECTED_COUNTS:
        raise SystemExit(f"catalogue counts {counts} != {EXPECTED_COUNTS}")
    errors = validate_catalog(build_nodes(), build_features())
    if errors:
        raise SystemExit("catalogue is invalid:\n- " + "\n- ".join(errors))

    if not SOURCE.exists():
        raise SystemExit(f"missing migration source: {SOURCE}")
    current = SOURCE.read_text(encoding="utf-8")
    wanted = _replace(current, _block())

    if args.check:
        if current != wanted:
            if is_active(SOURCE):
                print("seed block is stale; the active migration must not be "
                      "rewritten — add a new migration for the change")
            else:
                print("seed block is stale; run --write")
            return 1
        print(f"seed block is current ({sum(counts.values())} rows)")
        return 0

    if is_active(SOURCE):
        print(
            f"refusing to rewrite the active migration {SOURCE}.\n"
            "The migration may already be applied and Alembic does not checksum "
            "applied revisions. Put a seed change in a new migration.",
            file=sys.stderr)
        return 2

    SOURCE.write_text(wanted, encoding="utf-8")
    print(f"wrote {SOURCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
