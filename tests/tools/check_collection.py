"""Collection-only CI gate; no test bodies or fixtures are executed.

Run from any directory: python tests/tools/check_collection.py --output collection.json
Historical T-T35 baseline: at least 1350 items, zero collection errors. Skips are
reported separately and never described as passed tests. Requires pytest >= 8.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pytest


class CollectionStats:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.skips: list[str] = []
        self.collected = 0

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.errors.append(report.nodeid)
        elif report.skipped:
            self.skips.append(report.nodeid)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.collected = len(session.items)


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("min-collected must be at least 1")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--min-collected", type=positive_int, default=1350)
    parser.add_argument(
        "--output", type=Path, help="JSON summary (relative to invocation directory)"
    )
    parser.add_argument("paths", nargs="*", default=["tests"], help="Paths relative to root")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error("root must be an existing directory")
    output = args.output.resolve() if args.output else None
    for path in args.paths:
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root) or not resolved.exists():
            parser.error("collection paths must exist inside root")
    # A CI shell's -k/-m/--ignore must not silently shrink the guarded tree.
    os.environ["PYTEST_ADDOPTS"] = ""
    os.environ["MAIRUI_MODE"] = "replay"
    os.environ["MAIRUI_LICENCE"] = ""
    os.chdir(root)
    sys.path.insert(0, str(root / "src" / "backend"))
    stats = CollectionStats()
    native_exit = int(
        pytest.main(
            [
                "--collect-only",
                "--continue-on-collection-errors",
                "-q",
                "--strict-config",
                "--strict-markers",
                "--import-mode=importlib",
                "-p",
                "no:cacheprovider",
                "-o",
                "addopts=",
                *args.paths,
            ],
            plugins=[stats],
        )
    )
    passed = native_exit == 0 and not stats.errors and stats.collected >= args.min_collected
    summary = {
        "schema": "aia-collection/v1",
        "paths": args.paths,
        "collected": stats.collected,
        "minimum_collected": args.min_collected,
        "collection_errors": len(stats.errors),
        "error_nodes": stats.errors,
        "skipped_collectors": stats.skips,
        "pytest_exit_code": native_exit,
        "passed": passed,
        "test_bodies_executed": False,
    }
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print("COLLECTION_GUARD " + text)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
