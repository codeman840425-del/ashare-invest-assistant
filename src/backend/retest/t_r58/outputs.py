"""T-R58d §10: publish a complete offline run, or a separate failure record."""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from . import inputs
from .errors import DataFormatError
from .splice import SpliceError

TRIAL_FIELDS = (
    "trial_id",
    "group",
    "phase",
    "segment",
    "start",
    "end",
    "params",
    "holm_family",
    "n",
    "mean_bp",
    "ci_low_bp",
    "ci_high_bp",
    "selected",
    "status",
    "started_at",
    "elapsed_seconds",
)
LEG_FIELDS = (
    "trial_id",
    "group",
    "segment",
    "exchange",
    "symbol",
    "board",
    "entry_date",
    "direction",
    "data_source",
    "trigger_slot",
    "entry_slot",
    "entry_price",
    "exit_trigger_date",
    "exit_trigger_slot",
    "exit_date",
    "exit_slot",
    "exit_price",
    "reason",
    "q",
    "notional",
    "planned_amount",
    "participation_pct",
    "impact_bp_frozen",
    "theta",
    "sigma",
    "dev",
    "vr",
    "commission",
    "stamp",
    "transfer",
    "slippage",
    "impact",
    "pnl_yuan",
    "pnl_bp",
    "cons_pnl_yuan",
    "cons_pnl_bp",
    "cons_mark_price",
    "prior_anomaly",
    "exec_anomaly",
    "hold_bars",
    "mae_bp",
)
SUMMARY_FIELDS = {
    "plan",
    "data",
    "segments",
    "checks",
    "splice",
    "exclusions",
    "delisting",
    "criteria",
    "seed",
    "conclusion",
}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _csv_value(value: object) -> object:
    value = _json_value(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return value


def _csv(path: Path, fields: tuple[str, ...], rows: Iterable[Mapping[str, Any]]) -> None:
    expected = set(fields)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if row.keys() != expected:
                raise DataFormatError(f"unexpected output columns for {path.name}")
            writer.writerow({key: _csv_value(value) for key, value in row.items()})
        stream.flush()
        os.fsync(stream.fileno())


def _json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(_json_value(value), stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


DATE_FILE_FIELDS = (
    "exchange",
    "symbol",
    "source_path",
    "sha256",
    "raw_slice_sha256",
    "source_rows",
    "normalized_rows",
    "stock_days",
    "full_days",
    "single_bar_days",
)


def add_date_inventory(
    inventory: dict[str, list[dict[str, Any]]], key: inputs.StockKey, checks: dict[str, Any]
) -> None:
    for use, detail in checks.get("date_inventory", {}).items():
        inventory[use].append(
            {
                "exchange": key[0],
                "symbol": key[1],
                "source_path": checks["source_path"],
                "sha256": checks["source_sha256"],
                **detail,
            }
        )


def collect_date_inventories(
    snapshot: inputs.LocalVipdoc, end: date
) -> dict[str, list[dict[str, Any]]]:
    inventory: dict[str, list[dict[str, Any]]] = {"single": [], "main": []}
    for key, source in sorted(snapshot.files.items()):
        _, checks = inputs.decode_verified(source, key, inventory_end=end)
        checks["source_path"] = source.path.relative_to(snapshot.root).as_posix()
        add_date_inventory(inventory, key, checks)
    return inventory


def write_date_inventories(
    stage: Path,
    inventory: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    evidence = {}
    for use, rows in inventory.items():
        package = stage / f"vipdoc_{use}"
        package.mkdir()
        filelist = package / "filelist.csv"
        _csv(filelist, DATE_FILE_FIELDS, rows)
        sums = package / "SHA256SUMS"
        with sums.open("x", encoding="ascii", newline="\n") as stream:
            for row in rows:
                stream.write(f"{row['sha256']}  {row['source_path']}\n")
            stream.flush()
            os.fsync(stream.fileno())
        evidence[use] = {
            "filelist": f"vipdoc_{use}/filelist.csv",
            "sums": f"vipdoc_{use}/SHA256SUMS",
            "filelist_sha256": inputs.data.sha256(filelist),
            "sums_sha256": inputs.data.sha256(sums),
            "files": len(rows),
            "stock_days": sum(row["stock_days"] for row in rows),
            "full_days": sum(row["full_days"] for row in rows),
            "one_bar_days": [
                {"exchange": row["exchange"], "symbol": row["symbol"], **item}
                for row in rows
                for item in row["single_bar_days"]
            ],
            "sha256_basis": "source_file; raw_slice_sha256 hashes only selected records",
        }
    return evidence


def failure_path(destination: Path) -> Path:
    return destination.with_name(f"{destination.name}.failed")


def _publish(destination: Path, *, failed: bool, write: Callable[[Path], None]) -> Path:
    """A same-filesystem directory rename publishes the completed bundle in one step."""
    if (
        destination.name in {"", ".", ".."}
        or destination.name.endswith(".failed")
        or not destination.parent.is_dir()
    ):
        raise DataFormatError("output requires an existing parent and a fresh run name")
    destination = destination.parent.resolve(strict=True) / destination.name
    failed_path = failure_path(destination)
    target = failed_path if failed else destination
    lock = destination.with_name(f".{destination.name}.publishing")
    # Both success and failure publishers reserve the same name. After an
    # abrupt stop the reservation remains, so a retry cannot reuse this run.
    lock.mkdir()
    try:
        for path in (destination, failed_path):
            if path.exists() or path.is_symlink():
                raise FileExistsError("output run name already used")
        with tempfile.TemporaryDirectory(prefix=".t-r58-", dir=destination.parent) as temporary:
            stage = Path(temporary) / "bundle"
            stage.mkdir()
            write(stage)
            stage.rename(target)
    finally:
        lock.rmdir()
    return target


def publish_run(
    destination: Path,
    *,
    trials: Iterable[Mapping[str, Any]],
    legs: Iterable[Mapping[str, Any]],
    summary: Mapping[str, Any],
    date_inventories: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    if not summary.keys() >= SUMMARY_FIELDS:
        raise DataFormatError("incomplete run summary")

    def write(stage: Path) -> None:
        _csv(stage / "trials.csv", TRIAL_FIELDS, trials)
        _csv(stage / "legs.csv", LEG_FIELDS, legs)
        payload = dict(summary)
        if date_inventories is not None:
            payload["vipdoc_date_inventories"] = write_date_inventories(stage, date_inventories)
        _json(stage / "summary.json", payload)

    return _publish(destination, failed=False, write=write)


def publish_failure(destination: Path, *, stage: str, error: DataFormatError) -> Path:
    """Preserve structured splice diagnostics without publishing partial result files."""
    payload: dict[str, Any] = {"status": "blocked", "stage": stage, "kind": type(error).__name__}
    if isinstance(error, SpliceError):
        payload["splice"] = error.summary["splice"]
    return _publish(
        destination, failed=True, write=lambda directory: _json(directory / "failure.json", payload)
    )
