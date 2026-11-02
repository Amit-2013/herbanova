"""Cost backfill report - dry run only in this phase.

Reads the stock ledger, replays each product through the weighted-average rule
and prints what a backfill would fill. It also lists which legacy issue rows
can be attributed to their invoice. It never writes: the proposal must be
checked against a database copy before an apply mode is enabled. Money amounts
are not printed; the report carries counts, product ids, movement ids and
affected invoice ids. Stock quantities are printed as strings to show that the
issued and invoiced quantities match.

    python backfill_costs.py [--product 12] [--product 13]
"""
import argparse
import json
import sys
from decimal import Decimal

from app.core.db import SessionLocal
from app.services.costing import attribution_plan, backfill_plan


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
                        help="limit the report to one product id (repeatable)")
    parser.add_argument("--apply", action="store_true",
                        help="not available in this phase")
    args = parser.parse_args()
    if args.apply:
        print("Refused: the backfill is dry-run only in this phase.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        plan = backfill_plan(db, args.product)
        attribution = None if args.product else attribution_plan(db)
    report = {
        "mode": "dry-run",
        "products": len(plan["products"]),
        "movements": plan["movements"],
        "would_set_cost": plan["would_set_cost"],
        "affected_invoices": plan["affected_invoices"],
        "detail": [
            {"product_id": row["product_id"], "movements": row["movements"],
             "would_set_cost": row["would_set_cost"],
             "would_change_source": row["would_change_source"],
             "uncosted_on_hand": row["uncosted_on_hand"],
             "affected_invoice_ids": [i["invoice_id"] for i in row["affected_invoices"]]}
            for row in plan["products"]
        ],
        "attribution": attribution if attribution is not None
        else {"skipped": "the --product filter applies to costs only"},
    }
    print(json.dumps(_json(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
