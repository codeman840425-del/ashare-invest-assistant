"""Deterministic, file-level pytest shards weighted by the trusted baseline."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "scripts/ci/test-shards.json"


def plan(files, config):
    """Return (files, estimated seconds) for each shard, in shard order."""
    # Whole files only. Every shard is its own runner and runs one worker, so serial_* files
    # from tests/ci-groups.yaml never share PG, ports or files with a concurrent test.
    remaining = set(files)
    units = []
    for group in config.get("colocate", []):  # hidden cross-file dependencies stay in one shard
        members = sorted(remaining.intersection(group))
        if members:
            units.append(members)
            remaining.difference_update(members)
    units.extend([path] for path in sorted(remaining))
    weighted = [(sum(config["weights"].get(path, 1.0) for path in unit), unit)
                for unit in units]
    overhead = config.get("shard_overhead_seconds", {})
    shards = [([], float(overhead.get(str(i), 0.0))) for i in range(1, config["shards"] + 1)]
    for weight, unit in sorted(weighted, key=lambda row: (-row[0], row[1])):
        index = min(range(len(shards)), key=lambda i: (shards[i][1], i))
        members, seconds = shards[index]
        shards[index] = (members + unit, seconds + weight)
    return [(sorted(members), seconds) for members, seconds in shards]


def pytest_collection_modifyitems(config, items):
    index = os.environ.get("AIA_SHARD_INDEX")
    total = os.environ.get("AIA_SHARD_TOTAL")
    if index is None or total is None:
        return
    settings = json.loads(CONFIG.read_text(encoding="utf-8"))
    try:
        index, total = int(index), int(total)
    except ValueError as error:
        raise pytest.UsageError("AIA_SHARD_INDEX/TOTAL must be integers") from error
    if total != settings["shards"] or not 1 <= index <= total:
        raise pytest.UsageError("AIA_SHARD_INDEX/TOTAL does not match test-shards.json")
    if os.environ.get("PYTEST_XDIST_WORKER") or getattr(getattr(config, "option", None), "numprocesses", None):
        raise pytest.UsageError("shards must run with a single worker (serial_* groups)")
    paths = {item: Path(item.path).resolve().relative_to(ROOT).as_posix() for item in items}
    files, _ = plan(paths.values(), settings)[index - 1]
    chosen = set(files)
    selected = [item for item in items if paths[item] in chosen]
    deselected = [item for item in items if paths[item] not in chosen]
    report = os.environ.get("AIA_SHARD_REPORT")
    if report:
        Path(report).write_text(json.dumps({
            "shard": index, "total": total,
            "collected": [item.nodeid for item in items],
            "selected": [item.nodeid for item in selected], "files": files,
            "workers": 1,
        }, indent=2) + "\n", encoding="utf-8")
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected


def main():
    if sys.argv[1:] != ["plan"]:
        raise SystemExit("usage: python scripts/ci/pytest_shard.py plan")
    settings = json.loads(CONFIG.read_text(encoding="utf-8"))
    files = [path.relative_to(ROOT).as_posix()
             for directory in ("src/backend/tests", "tests/backend", "tests/replay")
             for path in (ROOT / directory).rglob("test_*.py")]
    for index, (members, seconds) in enumerate(plan(files, settings), 1):
        print(f"shard {index}/{settings['shards']}: {seconds:.1f}s ({len(members)} files)")
        for path in members:
            print(f"  {path}")


if __name__ == "__main__":
    main()
else:
    # The plan CLI needs only the standard library; pytest loads this as a plugin.
    import pytest

    pytest_collection_modifyitems = pytest.hookimpl(trylast=True)(pytest_collection_modifyitems)
