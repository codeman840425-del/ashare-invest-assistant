#!/usr/bin/env python3
"""Gate exact coverage against the frozen trusted base; 80/90 remain goals only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from coverage_ratchet import SELECTION, compare, load_policy, measured, validate_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("coverage-baseline.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        trusted = validate_record(json.loads(args.base.read_text(encoding="utf-8")))
        if trusted.get("ratchet_passed") is not True:
            raise ValueError("Trusted base did not pass its coverage ratchet")
        floors = load_policy(args.policy, trusted)
        counts = measured(args.coverage_json)
        errors, rows = compare(counts, trusted, floors)
        for row in rows:
            value = (f"{100 * row['covered'] / row['statements']:.4f}%"
                     if row["statements"] else "N/A (zero statements)")
            print(f"{row['scope']}: {value} ({row['covered']}/{row['statements']}); "
                  f"base={row['base_covered']}/{row['base_statements']}; "
                  f"denominator_delta={row['denominator_delta']:+d}; "
                  f"minimum_ratio={row.get('effective_minimum', 'N/A')}; "
                  f"required_ratio={row.get('required_ratio', 'N/A')}; {row['status']}")
        result = {"schema": "aia-coverage-ratchet-v1", "selection": SELECTION,
                  "counts": counts, "minimums": floors, "commit": os.environ.get("GITHUB_SHA"),
                  "run_id": os.environ.get("GITHUB_RUN_ID"),
                  "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                  "base_commit": trusted.get("commit"), "base_source": trusted.get("source"),
                  "ratchet_passed": not errors, "rows": rows}
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        for error in errors:
            print("::error title=coverage-ratchet::" + error)
        return 1 if errors else 0
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        print("::error title=coverage-ratchet::Missing or invalid real measurement/trusted baseline", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
