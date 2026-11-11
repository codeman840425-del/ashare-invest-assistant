# ruff: noqa: S101
"""Verified source-to-grid integration, including failure evidence isolation."""

from __future__ import annotations

import struct
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from retest.t_r58 import data, inputs, outputs, runner_data, sim, splice

KEY = ("SH", "600001")


def _lc1_bytes(day: date, price: float = 10.0) -> bytes:
    encoded = (day.year - 2004) * 2048 + day.month * 100 + day.day
    return struct.pack("<HHfffffII", encoded, 571, *([price] * 4), price * 100, 100, 0)


def _lc1(root: Path, day: date, price: float = 10.0) -> inputs.VipdocInput:
    root.mkdir()
    path = root / "sh600001.lc1"
    path.write_bytes(_lc1_bytes(day, price))
    return inputs.VipdocInput(root, {KEY: inputs.Lc1Input(path, data.sha256(path))}, "", "", "")


def _prepared(tmp_path: Path, *, price: float, listed: date | None) -> runner_data.Prepared:
    single = _lc1(tmp_path / "single", splice.SINGLE_DAY, price)
    main = _lc1(tmp_path / "main", splice.MAIN_START)
    archive = tmp_path / "hsjday.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(
            "sh\\lday\\sh600001.day",
            b"".join(
                struct.pack("<IIIIIfII", day, 1000, 1000, 1000, 1000, 1000.0, 100, 0)
                for day in (20260807, 20260810)
            ),
        )
    days = [splice.HF_END, splice.SINGLE_DAY, splice.MAIN_START]
    meta = {
        "coverage": {},
        "confirmed_suspension": set(),
        "securities": {
            KEY: {
                "listing_date": listed,
                "delisting_date": None,
            }
        },
    }
    return runner_data.Prepared(
        days,
        [sim.Segment("holdout", days[0], days[-1], embargo=False)],
        [(*KEY, "vipdoc_only")],
        tmp_path / "hf",
        {},
        single,
        main,
        archive,
        data.sha256(archive),
        {},
        {},
        meta,
        {KEY: [(days[0], None, False)]},
        {KEY: [(days[0], None, "listed")]},
        {},
    )


def test_tb136_runner_new_code_uses_verified_first_day(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path, price=10.0, listed=splice.SINGLE_DAY)
    stock, report = next(runner_data.iter_stocks(prepared))
    assert np.isnan(stock.o[0, 0])
    assert stock.o[1, 0] == stock.o[2, 0] == 10.0
    assert stock.day_kind[1:].tolist() == [sim.EXCLUDED, sim.EXCLUDED]
    assert report["splice"]["source_rows"] == {"HF": 0, "vipdoc_single": 1, "vipdoc_main": 1}
    assert report["listing"]["rows"] == 1


def test_tb136_runner_shared_snapshot_decodes_once_and_splits_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared(tmp_path, price=10.0, listed=splice.SINGLE_DAY)
    assert prepared.single is not None
    single = prepared.single.files[KEY].path.read_bytes()
    main = prepared.main.files[KEY].path
    main.write_bytes(single + main.read_bytes())
    source = inputs.Lc1Input(main, data.sha256(main))
    snapshot = inputs.LocalVipdoc(main.parent, {KEY: source}, source.sha256)
    prepare_shared = replace(prepared, single=None, main=snapshot)
    seen = []
    decode = inputs.decode_verified

    def counted(
        reference: inputs.Lc1Input, key: tuple[str, str], *, inventory_end: date | None = None
    ) -> tuple:
        seen.append(reference.path)
        return decode(reference, key, inventory_end=inventory_end)

    monkeypatch.setattr(inputs, "decode_verified", counted)
    stock, evidence = next(runner_data.iter_stocks(prepare_shared))
    assert seen == [main]
    assert stock.o[1, 0] == stock.o[2, 0] == 10
    assert evidence["splice"]["source_rows"] == {"HF": 0, "vipdoc_single": 1, "vipdoc_main": 1}
    assert evidence["splice"]["dual_package"]["state"] == "not_applicable_shared_snapshot"
    inventory = {"single": [], "main": []}
    outputs.add_date_inventory(inventory, KEY, evidence["lc1"]["main"])
    stage = tmp_path / "audit"
    stage.mkdir()
    summary = outputs.write_date_inventories(stage, inventory)
    assert summary["single"]["files"] == summary["main"]["files"] == 1
    assert inventory["single"][0]["sha256"] == inventory["main"][0]["sha256"] == source.sha256
    assert inventory["single"][0]["raw_slice_sha256"] != inventory["main"][0]["raw_slice_sha256"]
    for use in ("single", "main"):
        assert (stage / summary[use]["sums"]).read_text(encoding="ascii").startswith(source.sha256)


def test_tb136_runner_unknown_listing_is_not_eligible(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path, price=10.0, listed=None)
    stock, report = next(runner_data.iter_stocks(prepared))
    assert stock.day_kind.tolist() == [sim.EXCLUDED] * 3
    assert report["listing"]["state"] == "unknown"
    assert report["exclusions"]["all"]["2026"]["listing_date_unknown"] == 3


def test_tb136_runner_splice_error_stops_grid_and_keeps_failure_separate(tmp_path: Path) -> None:
    prepared = _prepared(tmp_path, price=10.5, listed=splice.SINGLE_DAY)
    target = tmp_path / "run"
    with pytest.raises(splice.SpliceError) as error:
        next(runner_data.iter_stocks(prepared))
    failure = outputs.publish_failure(target, stage="splice", error=error.value)
    assert not target.exists()
    assert {p.name for p in failure.iterdir()} == {"failure.json"}
    assert "single_day.daily_open" in error.value.summary["splice"]["failures"]


def _suspension_fixture(
    tmp_path: Path,
    symbol: str,
    *,
    archive_days: tuple[int, ...] = (20260731, 20260810),
    main_days: tuple[date, ...] = (splice.MAIN_START,),
    shared: bool = True,
) -> runner_data.Prepared:
    listed = date(2010, 1, 1)
    original = _prepared(tmp_path, price=10.5, listed=listed)
    key = ("SZ", symbol)
    root = tmp_path / "vipdoc"
    root.mkdir()
    lc1 = root / f"sz{symbol}.lc1"
    lc1.write_bytes(_lc1_bytes(splice.SINGLE_DAY, 10.5) + b"".join(map(_lc1_bytes, main_days)))
    source = inputs.Lc1Input(lc1, data.sha256(lc1))
    with zipfile.ZipFile(original.archive, "w") as z:
        z.writestr(
            f"sz/lday/sz{symbol}.day",
            b"".join(
                struct.pack("<IIIIIfII", day, 1000, 1000, 1000, 1000, 1000.0, 100, 0)
                for day in archive_days
            ),
        )
    return replace(
        original,
        dates=[splice.HF_END, splice.SINGLE_DAY, *main_days],
        pool=[(*key, "L")],
        single=None if shared else inputs.VipdocInput(root, {key: source}, "", "", ""),
        main=inputs.LocalVipdoc(root, {key: source}, source.sha256)
        if shared
        else inputs.VipdocInput(root, {key: source}, "", "", ""),
        archive_sha256=data.sha256(original.archive),
        meta={**original.meta, "securities": {}, "coverage": {symbol: {"listing_date": listed}}},
        st_history={key: [(listed, None, False)]},
        listing_history={key: [(listed, None, "listed")]},
    )


@pytest.mark.parametrize("symbol", ["000838", "300246", "300333", "300862"])
def test_tb136_runner_confirmed_suspension_removes_one_day_and_keeps_source_evidence(
    tmp_path: Path, symbol: str
) -> None:
    stock, evidence = next(runner_data.iter_stocks(_suspension_fixture(tmp_path, symbol)))
    assert np.isnan(stock.o[1]).all()
    assert stock.day_kind[1] == sim.SUSPENDED
    assert stock.o[2, 0] == 10
    checks = evidence["splice"]
    assert checks["ok"]
    assert checks["failures"] == []
    assert checks["single_day"]["state"] == "no_bars"
    assert checks["pre_splice_exclusions"] == [
        {
            "date": "2026-08-07",
            "reason": "suspension_residual_minutes",
            "label": "停牌期分钟残留",
            "rows": 1,
            "rows_by_source": {"vipdoc": 1},
            "prior_daily_date": "2026-07-31",
            "next_daily_date": "2026-08-10",
        }
    ]
    assert checks["source_rows"] == {"HF": 0, "vipdoc_single": 0, "vipdoc_main": 1}
    assert evidence["lc1"]["single"]["rows"] == 1
    assert evidence["lc1"]["main"]["date_inventory"]["single"]["normalized_rows"] == 1


@pytest.mark.parametrize("shared", [True, False])
def test_tb136_runner_suspension_gap_uses_anchors_across_source_boundary(
    tmp_path: Path, shared: bool
) -> None:
    main_days = tuple(date(2026, 8, day) for day in (10, 11, 13))
    prepared = _suspension_fixture(
        tmp_path, "300247", archive_days=(20260729, 20260813), main_days=main_days, shared=shared
    )
    stock, evidence = next(runner_data.iter_stocks(replace(prepared, st_history={})))
    assert np.isnan(stock.o[1:4]).all()
    assert stock.day_kind[1:4].tolist() == [sim.SUSPENDED] * 3
    assert stock.o[4, 0] == 10
    checks = evidence["splice"]
    assert checks["resume_day"]["date"] == "2026-08-13"
    assert [row["date"] for row in checks["pre_splice_exclusions"]] == [
        "2026-08-07",
        "2026-08-10",
        "2026-08-11",
    ]
    assert all(row["next_daily_date"] == "2026-08-13" for row in checks["pre_splice_exclusions"])


@pytest.mark.parametrize("archive_days", [(20260810,), (20260731,), ()])
def test_tb136_runner_excludes_uncovered_days_without_calling_them_suspended(
    tmp_path: Path, archive_days: tuple[int, ...]
) -> None:
    prepared = _suspension_fixture(tmp_path, "300246", archive_days=archive_days)
    stock, report = next(runner_data.iter_stocks(prepared))
    assert np.isnan(stock.o[1]).all()
    assert stock.day_kind[1] == sim.EXCLUDED
    exclusion = report["splice"]["pre_splice_exclusions"][0]
    assert exclusion["reason"] == "daily_anchor_outside_coverage"
    assert exclusion["prior_daily_date"] == ("2026-07-31" if archive_days == (20260731,) else None)
    assert exclusion["next_daily_date"] == ("2026-08-10" if archive_days == (20260810,) else None)


def test_tb136_runner_in_coverage_price_failure_still_blocks(tmp_path: Path) -> None:
    prepared = _suspension_fixture(tmp_path, "300246", archive_days=(20260731, 20260807, 20260810))
    with pytest.raises(splice.SpliceError) as error:
        next(runner_data.iter_stocks(prepared))
    checks = error.value.summary["splice"]
    assert "single_day.daily_open" in checks["failures"]
    assert "pre_splice_exclusions" not in checks


def test_tb136_runner_vipdoc_only_retains_first_covered_day(tmp_path: Path) -> None:
    key = ("SZ", "001246")
    prepared = _suspension_fixture(tmp_path, key[1], archive_days=(20260810,))
    prepared = replace(
        prepared,
        pool=[(*key, "vipdoc_only")],
        meta={**prepared.meta, "securities": {key: {"listing_date": splice.SINGLE_DAY}}},
    )
    stock, report = next(runner_data.iter_stocks(prepared))
    assert np.isnan(stock.o[1]).all()
    assert stock.o[2, 0] == 10
    assert report["listing"]["first"] == splice.SINGLE_DAY
    assert report["splice"]["resume_day"]["date"] == "2026-08-10"
    assert report["splice"]["pre_splice_exclusions"][0]["label"] == "新股日线归档延迟，无锚可校"


def test_tb136_runner_suspension_gap_counts_hf_and_vipdoc_and_rejects_duplicate(
    tmp_path: Path,
) -> None:
    key = ("SZ", "300247")
    prepared = _suspension_fixture(tmp_path, key[1])
    table, _ = splice.decode_lc1(prepared.main.files[key].path, *key)
    day = splice.SINGLE_DAY
    residual = splice._day(table, day)
    left, right = date(2026, 7, 31), splice.MAIN_START
    anchors = dict.fromkeys((left, right), splice.DailyBar(10, 10, 100))
    bad = {"HF": pa.concat_tables([residual, residual])}
    with pytest.raises(data.DataFormatError, match="duplicate timestamp"):
        runner_data._filter_unanchored_minutes(key, bad, anchors, {day})
    sources = {"HF": residual, "vipdoc": table}
    suspended, uncovered, evidence = runner_data._filter_unanchored_minutes(
        key, sources, anchors, {day}
    )
    assert suspended == {day}
    assert not uncovered
    assert sources["HF"].num_rows == 0
    assert sources["vipdoc"].num_rows == 1
    assert evidence[0]["rows_by_source"] == {"HF": 1, "vipdoc": 1}
    assert evidence[0]["rows"] == 2
