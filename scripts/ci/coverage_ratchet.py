"""Exact coverage ratios and frozen baseline validation, without percent rounding."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path, PurePosixPath

SCOPES = ("total", "domain", "importing", "signals", "advice", "llm")
SELECTION = {"directories": ["src/backend/tests", "tests/backend", "tests/replay"],
             "coverage_source": "src/backend/app"}
BOOTSTRAP_BASE = "465e02046fa8d971897603742497444f884e89a2"
BOOTSTRAP = {"head": "4c02a41ebbea1612da9c5cb53ec9a32b2342ee6f", "run": 43238057084,
             "counts": {"total": [15571, 22926], "domain": [113, 172],
                        "importing": [1092, 1406], "signals": [353, 436],
                        "advice": [0, 0], "llm": [0, 0]}}
MINIMUMS = {"total": 67, "domain": 65, "importing": 77, "signals": 81,
            "advice": None, "llm": None}


def pair(value) -> tuple[int, int]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(v) is not int for v in value)
            or not 0 <= value[0] <= value[1]):
        raise ValueError("Invalid measured coverage counts")
    return value[0], value[1]


def validate_record(record: dict) -> dict:
    if (record.get("schema") != "aia-coverage-ratchet-v1"
            or record.get("selection") != SELECTION
            or set(record.get("counts", {})) != set(SCOPES)
            or set(record.get("minimums", {})) != set(SCOPES)):
        raise ValueError("Missing measurement or changed test selection/schema")
    for scope in SCOPES:
        pair(record["counts"][scope])
        floor = record["minimums"][scope]
        if floor is not None and (type(floor) is not int or not 0 <= floor <= 100):
            raise ValueError("Invalid coverage minimum")
    if record["counts"]["total"][1] == 0:
        raise ValueError("No real overall coverage measurement")
    return record


def bootstrap_record() -> dict:
    return {"schema": "aia-coverage-ratchet-v1", "selection": SELECTION,
            "counts": BOOTSTRAP["counts"], "minimums": MINIMUMS,
            "commit": BOOTSTRAP["head"], "ratchet_passed": True,
            "source": {"kind": "approved-first-bootstrap", "run": BOOTSTRAP["run"]}}


def load_policy(path: Path, trusted: dict) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("bootstrap") != BOOTSTRAP or policy.get("selection") != SELECTION:
        raise ValueError("PR cannot rewrite the approved bootstrap or test selection")
    floors = policy.get("minimums", {})
    if set(floors) != set(SCOPES):
        raise ValueError("Incomplete minimum policy")
    for scope in SCOPES:
        value = floors[scope]
        if value is not None and (type(value) is not int or not 0 <= value <= 100):
            raise ValueError("Invalid minimum policy")
        for previous in (MINIMUMS[scope], trusted["minimums"][scope]):
            if previous is not None and (value is None or value < previous):
                raise ValueError("Minimums can only rise from trusted base")
    return floors


def measured(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files")
    if not isinstance(files, dict) or not files or not isinstance(data.get("totals"), dict):
        raise ValueError("Missing real coverage files/totals")
    counts = {scope: [0, 0] for scope in SCOPES}
    for name, info in files.items():
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if ".." in parts or "app" not in parts:
            raise ValueError("Coverage file is outside the measured app")
        index = parts.index("app")
        if len(parts) <= index + 1:
            raise ValueError("Invalid app coverage path")
        summary = info["summary"]
        covered, total = pair([summary["covered_lines"], summary["num_statements"]])
        counts["total"][0] += covered
        counts["total"][1] += total
        scope = parts[index + 1]
        if scope in SCOPES[1:] and len(parts) > index + 2:
            counts[scope][0] += covered
            counts[scope][1] += total
    reported = pair([data["totals"]["covered_lines"], data["totals"]["num_statements"]])
    if tuple(counts["total"]) != reported or reported[1] == 0:
        raise ValueError("Coverage totals disagree or contain no measurement")
    return counts


def compare(counts: dict, trusted: dict, minimums: dict) -> tuple[list[str], list[dict]]:
    validate_record(trusted)
    errors, rows = [], []
    for scope in SCOPES:
        covered, total = pair(counts[scope])
        before_covered, before_total = pair(trusted["counts"][scope])
        row = {"scope": scope, "covered": covered, "statements": total,
               "base_covered": before_covered, "base_statements": before_total,
               "denominator_delta": total - before_total, "minimum": minimums[scope]}
        rows.append(row)
        if not total:
            row["status"] = "N/A"
            if scope == "total" or before_total:
                errors.append(scope + ": measured statements disappeared")
            continue
        actual = Fraction(covered, total)
        # A newly active package has no previous ratio. Require the trusted
        # overall ratio; never inherit a fictitious 100% from previous 0/0.
        required = (Fraction(before_covered, before_total) if before_total
                    else Fraction(*trusted["counts"]["total"]))
        row["required_ratio"] = [required.numerator, required.denominator]
        row["newly_active"] = not before_total
        row["status"] = "pass" if actual >= required else "fail"
        if actual < required:
            errors.append(scope + ": exact coverage decreased from trusted base")
        floor = minimums[scope]
        if floor is not None:
            effective = Fraction(floor, 100)
            # 353/436 is 80.9633%, reported as 81.0% by the original CI.
            # The explicitly approved exact bootstrap is authoritative over
            # its rounded label; raising the configured 81 later is strict.
            seed_covered, seed_total = BOOTSTRAP["counts"][scope]
            if floor == MINIMUMS[scope] and seed_total:
                effective = min(effective, Fraction(seed_covered, seed_total))
            row["effective_minimum"] = [effective.numerator, effective.denominator]
            if actual < effective:
                row["status"] = "fail"
                errors.append(scope + ": below monotonic minimum")
    return errors, rows
