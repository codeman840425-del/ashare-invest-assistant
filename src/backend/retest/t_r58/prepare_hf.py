"""T-B136 public HF preparation gates; run only after the pinned download succeeds."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REVISION = "ba589a11534825044fe5a6b84838f50ba8d8d188"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_raw(raw: Path, expected: Path, workers: int = 8) -> dict[str, int]:
    root = raw.resolve()
    tasks: list[tuple[Path, str]] = []
    for line in expected.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(None, 1)
        path = (root / relative.strip()).resolve()
        if not path.is_relative_to(root):
            raise ValueError("raw SHA list path outside its root")
        tasks.append((path, digest))
    if len(tasks) != 5801 or len({path for path, _ in tasks}) != 5801:
        raise ValueError("expected raw SHA list must contain exactly 5801 unique files")

    def check(task: tuple[Path, str]) -> str:
        path, digest = task
        if not path.is_file():
            return "missing"
        return "ok" if sha256(path) == digest else "mismatch"

    result = dict.fromkeys(("ok", "mismatch", "missing"), 0)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for status in executor.map(check, tasks):
            result[status] += 1
    print(json.dumps({"stage": "raw_sha", **result}), flush=True)
    if result != {"ok": 5801, "mismatch": 0, "missing": 0}:
        raise ValueError("raw SHA gate failed; conversion forbidden")
    return result


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def semantic_sample(raw: Path, out: Path, row: dict[str, str]) -> None:
    import pandas as pd

    relative = Path(row["exchange"]) / f"{row['symbol']}.parquet"
    source = pd.read_parquet(raw / "data" / "stock_1m" / relative)
    source = source.loc[
        (source["timestamp"] >= pd.Timestamp("2022-01-01"))
        & (source["timestamp"].dt.normalize() != pd.Timestamp("2026-08-07"))
    ].sort_values("timestamp").copy()
    auction = (source["timestamp"].dt.hour == 9) & (source["timestamp"].dt.minute == 30)
    source.loc[auction, "timestamp"] += pd.Timedelta(minutes=1)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "turnover": "sum"}
    expected = source.groupby("timestamp", sort=True).agg(agg).reset_index()
    expected["timestamp"] = expected["timestamp"].dt.tz_localize("Asia/Shanghai")
    columns = ["timestamp", *agg]
    actual = pd.read_parquet(out / relative, columns=columns)
    try:
        pd.testing.assert_frame_equal(expected[columns], actual[columns], check_dtype=False,
                                      check_exact=True)
    except AssertionError:
        # Never expose sampled market rows in a traceback or an issue comment.
        raise ValueError("converted semantic sample mismatch") from None


def compare_manifest(kit: Path, raw: Path, out: Path) -> dict[str, Any]:
    reference = json.loads((kit / "manifest.json").read_text(encoding="utf-8"))
    actual = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    fields = ("source_repo", "revision", "source_files", "files", "stocks",
              "stocks_by_exchange", "delisted_stocks", "empty_files", "failed_files",
              "total_rows", "first_ts", "last_ts", "bj_files", "duplicate_rows")
    mismatch = [key for key in fields if actual.get(key) != reference.get(key)]
    for key in ("start", "drop_dates", "revision"):
        if actual["parameters"].get(key) != reference["parameters"].get(key):
            mismatch.append(f"parameters.{key}")
    if mismatch:
        raise ValueError(f"converted manifest gate failed: {mismatch}")
    expected_rows, actual_rows = rows(kit / "manifest_files.csv"), rows(out / "manifest_files.csv")
    expected = {(r["exchange"], r["symbol"]): r for r in expected_rows}
    observed = {(r["exchange"], r["symbol"]): r for r in actual_rows}
    if len(expected) != 5714 or len(observed) != 5714 or len(actual_rows) != 5714:
        raise ValueError("converted manifest_files must contain 5714 unique files")
    if expected.keys() != observed.keys():
        raise ValueError("converted manifest file identities differ")
    same_sha = 0
    for key, wanted in expected.items():
        got = observed[key]
        for field in ("exchange", "symbol", "is_bj", "universe_status", "rows", "days",
                      "first_ts", "last_ts", "bars_per_day_min", "bars_per_day_max"):
            if got[field] != wanted[field]:
                raise ValueError(f"converted manifest_files gate failed: {field}")
        path = out / got["exchange"] / f"{got['symbol']}.parquet"
        if sha256(path) != got["sha256"]:
            raise ValueError("converted file does not match its own manifest SHA")
        same_sha += got["sha256"] == wanted["sha256"]
    # Arrow serialization may differ; README explicitly allows semantic verification.
    samples = [next(r for r in actual_rows if r["exchange"] == exchange
                    and r["universe_status"] == status)
               for exchange in ("SH", "SZ") for status in ("L", "D")]
    for row in samples:
        semantic_sample(raw, out, row)
    result = {"ok": True, "files": len(observed), "reference_sha_equal": same_sha,
              "semantic_samples": len(samples), "manifest_sha256": sha256(out / "manifest.json"),
              "manifest_files_sha256": sha256(out / "manifest_files.csv"),
              "reference_manifest_sha256": sha256(kit / "manifest.json"),
              "raw_expected_sha256": sha256(kit / "raw_expected_sha256.txt"),
              "converter_sha256": sha256(kit / "scripts" / "convert.py"),
              "revision": REVISION}
    print(json.dumps({"stage": "converted_manifest", **result}), flush=True)
    return result


def wait_for_inputs(raw: Path, expected: Path, timeout_seconds: int = 14400) -> None:
    """Background pipeline only: keep the download untouched; hash before any conversion."""
    paths = [(raw / line.split(None, 1)[1].strip()).resolve()
             for line in expected.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(paths) != 5801 or any(not p.is_relative_to(raw.resolve()) for p in paths):
        raise ValueError("invalid raw input list")
    paths += [raw / "metadata" / name for name in (
        "coverage_by_instrument.csv", "market_calendar.csv",
        "no_bar_day_classification.csv", "absent_instruments.csv",
    )]
    deadline = time.monotonic() + timeout_seconds
    print(json.dumps({"stage": "waiting_for_download_inputs"}), flush=True)
    while not all(path.is_file() for path in paths):
        if time.monotonic() >= deadline:
            raise TimeoutError("download inputs still incomplete; preserve all partial files")
        time.sleep(30)
    print(json.dumps({"stage": "download_inputs_present"}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--wait-for-download", action="store_true")
    args = parser.parse_args()
    root, kit = args.data_root.resolve(), args.kit.resolve()
    raw, out = root / "hf-1min" / "raw", root / "hf-1min" / "2022plus"
    if (
        root == kit or kit.is_relative_to(raw) or kit.is_relative_to(out)
        or not 1 <= args.workers <= 8
    ):
        raise ValueError("invalid preparation roots or worker count")
    if args.wait_for_download:
        wait_for_inputs(raw, kit / "raw_expected_sha256.txt")
    check = verify_raw(raw, kit / "raw_expected_sha256.txt", args.workers)
    if (out / "manifest.json").exists() or any(out.glob("*/*.parquet")):
        raise ValueError("conversion destination already populated; preserve and inspect first")
    # Exact approved output is resolved above before the converter's target unlink calls.
    command = [sys.executable, str(kit / "scripts" / "convert.py"),
               "--raw", str(raw), "--out", str(out), "--start", "2022-01-01",
               "--drop-dates", "2026-08-07", "--workers", str(args.workers),
               "--revision", REVISION]
    subprocess.run(command, check=True)  # noqa: S603 - fixed local reviewed converter, no shell
    result = {"raw": check, "converted": compare_manifest(kit, raw, out)}
    (root / "hf-1min" / "T-B136-hf-ready.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
