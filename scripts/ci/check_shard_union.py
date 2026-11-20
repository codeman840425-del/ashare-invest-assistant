"""Fail closed unless shard reports form an exact partition of collection."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from collections import Counter

from junit_validation import validate_junit


UUID = re.compile(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})(?![0-9a-fA-F])")

# Only this schemathesis test expands after collection. Exact operations come from
# tests/backend/contract/openapi_v1_stub.json; pytest run 43802901765 shard 4
# recorded these children (see scripts/ci/tests/fixtures/contract-runtime-junit.xml).
# Keep this explicit: an arbitrary selected parent must never authorize children.
RUNTIME_CHILDREN = {
    ("backend.contract.test_contract_stub", "test_stub_conforms_to_contract"): {
        ("backend.contract.test_contract_stub", "test_stub_conforms_to_contract[GET /health]"),
        ("backend.contract.test_contract_stub", "test_stub_conforms_to_contract[GET /me]"),
    },
}


def stable_id(nodeid: str) -> str:
    """Normalize only UUID values in parameters; preserve every other parameter."""
    function, bracket, params = nodeid.partition("[")
    return function + bracket + UUID.sub("<uuid>", params)


def junit_node(nodeid: str) -> tuple[str, str]:
    """Map a nodeid like pytest 9.2's mangle_test_address, without pytest."""
    path, separator, tail = nodeid.partition("::")
    names = [re.sub(r"\.py$", "", path.replace("/", "."))]
    if separator:
        name, bracket, params = tail.partition("[")
        names.extend(name.split("::"))
        if bracket:
            names[-1] += "[" + params.removesuffix("]") + "]"
    return ".".join(names[:-1]), names[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--groups", type=Path, help="tests/ci-groups.yaml (T-T93); every shard file must be listed")
    parser.add_argument("reports", type=Path, nargs="*")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        baseline_ids = [line.strip() for line in args.baseline.read_text(encoding="utf-8").splitlines()
                        if "::" in line]
        baseline = Counter(map(stable_id, baseline_ids))
        reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
        total = config["shards"]
        if len(reports) != total or sorted(r["shard"] for r in reports) != list(range(1, total + 1)):
            raise ValueError("expected exactly one report for each shard 1..N")
        if not baseline:
            raise ValueError("baseline collection is empty")
        union = Counter()
        owners = {}
        for report in reports:
            if report["total"] != total or report.get("workers") != 1:
                raise ValueError(f"shard {report['shard']}: wrong total or not single-worker")
            if Counter(map(stable_id, report["collected"])) != baseline:
                raise ValueError(f"shard {report['shard']}: collection differs from baseline")
            for path in report["files"]:
                if path in owners:
                    raise ValueError(f"{path} selected by shards {owners[path]} and {report['shard']}")
                owners[path] = report["shard"]
            union.update(map(stable_id, report["selected"]))
        for group in config.get("colocate", []):
            if len({owners[path] for path in group if path in owners}) > 1:
                raise ValueError(f"colocated files split across shards: {group}")
        if union != baseline:
            diff = (union - baseline) + (baseline - union)
            raise ValueError(f"selected union differs from baseline: {sorted(diff)[:5]}")
        if args.groups:
            import yaml  # only the --groups check needs PyYAML

            listed = {row["file"] for row in yaml.safe_load(args.groups.read_text(encoding="utf-8"))["tests"]}
            unknown = sorted(set(owners) - listed)
            if unknown:
                raise ValueError(f"files missing from {args.groups}: {unknown[:5]}")
        lines = ["Shard union: OK", "", "| Shard | Tests | JUnit seconds |", "| --- | ---: | ---: |"]
        seen = set()
        for report in sorted(reports, key=lambda r: r["shard"]):
            seconds = "—"
            if args.junit:
                paths = list(args.junit.rglob(f"backend-pytest-shard-{report['shard']}.xml"))
                if len(paths) != 1:
                    raise ValueError(f"shard {report['shard']}: expected exactly one JUnit")
                root = ET.parse(paths[0]).getroot()
                counts = (f"shard {report['shard']}: selected={len(report['selected'])} "
                          f"junit={sum(1 for _ in root.iter('testcase'))}")
                try:
                    cases = validate_junit(root, seen)
                except ValueError as error:
                    raise ValueError(f"{counts}: {error}") from error
                selected = {junit_node(node) for node in report["selected"]}
                expanded = selected & RUNTIME_CHILDREN.keys()
                required = selected - expanded
                for parent in expanded:
                    required.update(RUNTIME_CHILDREN[parent])
                actual = {(case.get("classname", ""), case.get("name", "")) for case in cases}
                # Pytest may retain the container parent; all children are mandatory.
                missing = sorted(required - actual)
                extra = sorted(actual - required - expanded)
                if missing or extra:
                    raise ValueError(f"{counts}: missing selected nodes={missing[:5]}; "
                                     f"unaccounted JUnit nodes={extra[:5]}")
                seconds = f"{sum(float(c.get('time', '0')) for c in cases):.1f}"
            lines.append(f"| {report['shard']} | {len(report['selected'])} | {seconds} |")
        summary = "\n".join(lines) + "\n"
        print(summary, end="")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
                output.write(summary)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        print(f"::error title=shard union::{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
