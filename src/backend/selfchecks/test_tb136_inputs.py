# ruff: noqa: S101
"""T-R58 input gates: synthetic snapshots, no external data or credentials."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from retest.t_r58 import data, inputs, sim
from retest.t_r58.errors import DataFormatError
from selfchecks import tb136_retest as synthetic

SINGLE = "tdx_min_20260807_manifest.json"
MAIN = "tdx_min_manifest.json"
RELATIVE = "sh/minline/sh600000.lc1"


def vipdoc(root: Path, manifest: str, content: bytes | Path) -> Path:
    path = root / "vipdoc" / RELATIVE
    path.parent.mkdir(parents=True)
    if isinstance(content, Path):
        path.hardlink_to(content)
    else:
        path.write_bytes(content)
    digest = data.sha256(path)
    (root / manifest).write_text('{"files":1}', encoding="utf-8")
    (root / "SHA256SUMS").write_text(f"{digest}  vipdoc/{RELATIVE}\n", encoding="utf-8")
    (root / "filelist.csv").write_text(f"path,sha256\n{RELATIVE},{digest}\n", encoding="utf-8")
    return path


def test_tb136_input_pair_verified_from_two_inventories(tmp_path: Path) -> None:
    single, main = tmp_path / "single", tmp_path / "main"
    left, right = vipdoc(single, SINGLE, b"single"), vipdoc(main, MAIN, b"main")
    # An excluded board path must never be opened even if inventory names it.
    with (main / "SHA256SUMS").open("a", encoding="utf-8") as stream:
        stream.write("0" * 64 + "  vipdoc/bj/minline/bj920001.lc1\n")
    a, b = inputs.verify_vipdoc_pair(single, main)
    assert a.files[("SH", "600000")].path == left
    assert b.files[("SH", "600000")].sha256 == data.sha256(right)
    assert a.evidence()["files"] == b.evidence()["files"] == 1


@pytest.mark.parametrize(
    "failure", ["same_root", "hardlink", "copy", "missing", "bad_sha", "escape"]
)
def test_tb136_input_pair_rejects_invalid_provenance(tmp_path: Path, failure: str) -> None:
    single, main = tmp_path / "single", tmp_path / "main"
    left = vipdoc(single, SINGLE, b"single")
    if failure == "hardlink":
        vipdoc(main, MAIN, left)
        message = "physical lc1"
    elif failure == "same_root":
        main, message = single, "distinct"
    elif failure == "missing":
        main.mkdir()
        message = "missing or unsafe"
    elif failure == "copy":
        vipdoc(main, MAIN, b"single")
        message = "identical file inventories"
    else:
        right = vipdoc(main, MAIN, b"main")
        if failure == "bad_sha":
            right.write_bytes(b"changed")
            message = "SHA mismatch"
        else:
            (main / "filelist.csv").write_text(
                "path,sha256\n../outside," + "0" * 64 + "\n", encoding="utf-8"
            )
            message = "unsafe path"
    with pytest.raises(DataFormatError, match=message):
        inputs.verify_vipdoc_pair(single, main)


def hf_input(tmp_path: Path, symbol: str = "600000") -> tuple[Path, Path]:
    root = tmp_path / "hf"
    stock = root / "SH" / "600000.parquet"
    stock.parent.mkdir(parents=True)
    stock.write_bytes(b"synthetic bytes: the manifest gate only hashes")
    stamp = "2022-01-04T09:31:00+08:00"
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": 1,
                "stocks_by_exchange": {"SH": 1},
                "bj_files": 0,
                "delisted_stocks": 0,
                "total_rows": 1,
                "first_ts": stamp,
                "last_ts": stamp,
                "revision": "pinned",
            }
        ),
        encoding="utf-8",
    )
    files = root / "manifest_files.csv"
    with files.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "exchange",
                "symbol",
                "is_bj",
                "universe_status",
                "rows",
                "first_ts",
                "last_ts",
                "sha256",
            ]
        )
        writer.writerow(["SH", symbol, "False", "L", 1, stamp, stamp, data.sha256(stock)])
    ready = root / "ready.json"
    ready.write_text(
        json.dumps(
            {
                "raw": {"ok": 5801, "missing": 0, "mismatch": 0},
                "converted": {
                    "ok": True,
                    "revision": "pinned",
                    "files": 1,
                    "semantic_samples": 4,
                    "manifest_sha256": data.sha256(manifest),
                    "manifest_files_sha256": data.sha256(files),
                },
            }
        ),
        encoding="utf-8",
    )
    return root, ready


@pytest.mark.parametrize("failure", [None, "manifest", "parquet", "traversal", "marker"])
def test_tb136_input_hf_requires_current_pinned_sha(tmp_path: Path, failure: str | None) -> None:
    root, ready = hf_input(tmp_path, "../../x" if failure == "traversal" else "600000")
    expect = {"manifest_files": 1, "bj_files": 0, "delisted_all": 0}
    if failure is None:
        assert inputs.verify_hf(root, ready, revision="pinned", expect=expect, workers=1)["ok"]
        return
    if failure == "manifest":
        with (root / "manifest.json").open("a", encoding="utf-8") as stream:
            stream.write("\n")
        message = "differs from preparation"
    elif failure == "parquet":
        (root / "SH/600000.parquet").write_bytes(b"replacement")
        message = "current manifest/SHA"
    elif failure == "marker":
        ready.write_text("{}", encoding="utf-8")
        message = "raw SHA gate"
    else:
        message = "unsafe HF manifest identity"
    with pytest.raises(DataFormatError, match=message):
        inputs.verify_hf(root, ready, revision="pinned", expect=expect, workers=1)


@pytest.mark.parametrize("late_bar", [False, True])
def test_tb136_exclusion_is_not_masked_by_whole_day_absence(late_bar: bool) -> None:
    stock = synthetic._lock_stock(sim.OK, tail=3)
    for array in (stock.o, stock.h, stock.l, stock.c, stock.v, stock.a):
        array[7, : 239 if late_bar else 240] = np.nan
    grid = dict(zip("ohlcva", (stock.o, stock.h, stock.l, stock.c, stock.v, stock.a), strict=True))
    key = stock.exchange, stock.symbol
    st = {key: [(stock.dates[0], stock.dates[7], False), (stock.dates[8], None, False)]}
    listing = {key: [(stock.dates[0], None, "listed")]}
    meta = {"coverage": {}, "confirmed_suspension": set()}
    stock.day_kind, stock.st, reasons = data.day_kinds(
        (*key, "L"), stock.dates, meta, st, listing, grid
    )
    assert stock.day_kind[7] == sim.EXCLUDED
    assert reasons["all"]["2024"]["st_unknown"] == 1
    leg = sim.simulate(stock, synthetic.PB, synthetic._seg(stock))[0]
    assert leg.reason == "unvaluable_excluded"
    assert leg.exit_day is None
    assert leg.cons_mark_price == 9.0
