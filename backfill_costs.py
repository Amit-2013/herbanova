"""Stock cost backfill and invoice attribution tool.

Dry run by default: reads the stock ledger, replays each product through the
weighted-average rule and prints every movement's current and proposed cost and
source, every issued invoice's cost of goods before and after with the reason
when it stays partial, and which legacy issue rows can be attributed to their
invoice. Two SHA-256 fingerprints are printed: one for the cost plan and one for
the attribution plan. Nothing is written.

`--apply` links the unambiguous attribution candidates and `--apply-costs`
writes the cost proposals. Each needs the fingerprint printed by the dry run,
writes exactly one audit row, and refuses without writing if any part of its
plan changed since approval. Re-running with the applied fingerprint is a no-op.
No amounts are hidden from the operator at approval time, but nothing leaves
the database except this report.

    python backfill_costs.py [--product 12] [--product 13]
    python backfill_costs.py --apply --plan-fingerprint <sha256> [--operator NAME]
    python backfill_costs.py --apply-costs --plan-fingerprint <sha256> [--product 12]

The operator is recorded in the audit row. Pass `--operator NAME` or set
HERBANOVA_BACKFILL_OPERATOR; the dry run prints which name would be recorded.
"""
import argparse
import json
import os
import sys
from decimal import Decimal

from app.core.db import SessionLocal
from app.services.costing import (LockedPeriodError, StaleAttributionPlanError,
                                  StaleCostPlanError, apply_attribution,
                                  apply_cost_backfill, attribution_fingerprint,
                                  attribution_plan, backfill_plan,
                                  cost_fingerprint)


def _json(value):
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=int, action="append",
                        help="limit the cost plan to one product id (repeatable); "
                             "attribution is always company-wide")
    parser.add_argument("--apply", action="store_true",
                        help="link the approved attribution candidates")
    parser.add_argument("--apply-costs", action="store_true",
                        help="write the approved cost proposals")
    parser.add_argument("--plan-fingerprint", metavar="SHA256",
                        help="fingerprint printed by the dry run; required to apply")
    parser.add_argument("--operator", default=os.environ.get("HERBANOVA_BACKFILL_OPERATOR"),
                        help="name recorded in the audit row (default: "
                             "HERBANOVA_BACKFILL_OPERATOR)")
    args = parser.parse_args()
    operator = (args.operator or "").strip() or None
    if args.apply and args.apply_costs:
        print("Refused: use --apply or --apply-costs, not both.", file=sys.stderr)
        return 2
    if args.apply and args.product:
        print("Refused: --product applies to costs only; the attribution plan is "
              "always company-wide.", file=sys.stderr)
        return 2
    if (args.apply or args.apply_costs) and not args.plan_fingerprint:
        print("Refused: applying needs --plan-fingerprint from an approved dry run.",
              file=sys.stderr)
        return 2

    if args.apply or args.apply_costs:
        with SessionLocal() as db:
            try:
                if args.apply:
                    result = apply_attribution(
                        db, actor_id=None, operator=operator,
                        expected_fingerprint=args.plan_fingerprint)
                else:
                    result = apply_cost_backfill(
                        db, actor_id=None, product_ids=args.product,
                        operator=operator,
                        expected_fingerprint=args.plan_fingerprint)
            except (StaleAttributionPlanError, StaleCostPlanError,
                    LockedPeriodError, ValueError) as exc:
                print(f"Refused: {exc} Nothing was written.", file=sys.stderr)
                return 3
            db.commit()
        mode = "apply" if args.apply else "apply-costs"
        print(json.dumps(_json({"mode": mode, **result}), indent=2))
        return 0

    with SessionLocal() as db:
        plan = backfill_plan(db, args.product)
        attribution = None if args.product else attribution_plan(db)
    if attribution is not None:
        attribution["plan_fingerprint"] = attribution_fingerprint(attribution)
    report = {
        "mode": "dry-run",
        "operator": operator,
        "products": len(plan["products"]),
        "movements": plan["movements"],
        "would_set_cost": plan["would_set_cost"],
        "would_change_source": plan["would_change_source"],
        "affected_invoices": plan["affected_invoices"],
        "cost_plan_fingerprint": cost_fingerprint(plan),
        "detail": plan["products"],
        "invoices": plan["invoices"],
        "attribution": attribution if attribution is not None
        else {"skipped": "the --product filter applies to costs only"},
    }
    print(json.dumps(_json(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
