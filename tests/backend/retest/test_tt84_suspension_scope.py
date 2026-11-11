"""T-15 adapts T-T84 to the adjudicated interval/coverage policy.

Authority: T-R58 §2.3/§2.7 at f3bcfbd and Chief's interval ruling (f14a454,
coverage classification finalized in the assigned #81 baseline d4405a8).
A missing in-range daily session is suspended, regardless of the old four-code
list/package shape. Outside coverage is data-insufficient, never suspension.
Covered price/volume errors, invalid codes/records and changed inputs still stop.
All lc1/day records below are synthetic and consumed by the real decoder/runner.
"""
from __future__ import annotations

import json
import struct
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from retest.t_r58 import data, inputs, outputs, runner, runner_data, sim, splice

MINUTES = (*range(571, 691), *range(781, 901))
GAP_DATES = [date(2026, 8, d) for d in (6, 7, 10, 11, 12, 13)]


def prepared(
    root: Path,
    symbol: str,
    *,
    exchange: str = "SZ",
    daily_days: tuple[int, ...] = (20260731, 20260810),
    shared: bool = True,
    minute_prices: tuple[tuple[date, float], ...] | None = None,
    dates: list[date] | None = None,
    daily_volume: int = 24000,
) -> runner_data.Prepared:
    key = (exchange, symbol)
    prices = minute_prices or ((splice.SINGLE_DAY, 10.5), (splice.MAIN_START, 10.0))

    def write_source(folder: str, rows: tuple[tuple[date, float], ...]) -> inputs.Lc1Input:
        directory = root / folder
        directory.mkdir()
        path = directory / (exchange.lower() + symbol + ".lc1")
        raw = bytearray()
        for day, price in rows:
            packed = (day.year - 2004) * 2048 + day.month * 100 + day.day
            for minute in MINUTES:
                raw.extend(struct.pack(
                    "<HHfffffII", packed, minute, price, price, price, price,
                    price * 100, 100, 0,
                ))
        path.write_bytes(raw)
        return inputs.Lc1Input(path, data.sha256(path))

    main = write_source("vipdoc-main", prices)
    if shared:
        single_package = None
        main_package = inputs.LocalVipdoc(main.path.parent, {key: main}, main.sha256)
    else:
        single = write_source("vipdoc-single", tuple(row for row in prices if row[0] == splice.SINGLE_DAY))
        single_package = inputs.VipdocInput(single.path.parent, {key: single}, "", "", "")
        main_package = inputs.VipdocInput(main.path.parent, {key: main}, "", "", "")
    daily_path = root / "hsjday.zip"
    with zipfile.ZipFile(daily_path, "w") as archive:
        archive.writestr(
            f"{exchange.lower()}/lday/{exchange.lower()}{symbol}.day",
            b"".join(struct.pack(
                "<IIIIIfII", day, 1000, 1000, 1000, 1000, 240000.0, daily_volume, 0,
            ) for day in daily_days),
        )
    sessions = dates or [splice.HF_END, splice.SINGLE_DAY, splice.MAIN_START]
    listed = date(2010, 1, 1)
    meta = {"coverage": {symbol: {"listing_date": listed}}, "confirmed_suspension": set(), "securities": {}}
    return runner_data.Prepared(
        sessions, [sim.Segment("holdout", sessions[0], sessions[-1], embargo=False)],
        [(*key, "L")], root / "hf", {}, single_package, main_package,
        daily_path, data.sha256(daily_path), {}, {}, meta,
        {key: [(listed, None, False)]}, {key: [(listed, None, "listed")]}, {},
    )


def source_bytes(p: runner_data.Prepared) -> dict[Path, bytes]:
    refs = [*p.main.files.values(), *(p.single.files.values() if p.single else [])]
    return {ref.path: ref.path.read_bytes() for ref in refs} | {p.archive: p.archive.read_bytes()}


@pytest.mark.parametrize("symbol,exchange", [
    ("000838", "SZ"), ("300246", "SZ"), ("300333", "SZ"),
    ("300862", "SZ"), ("300247", "SZ"), ("600247", "SH"),
])
@pytest.mark.parametrize("shared", [True, False], ids=["shared", "independent"])
def test_tt84_interval_not_four_code_or_shared_package_exception(
    tmp_path: Path, symbol: str, exchange: str, shared: bool,
) -> None:
    p = prepared(tmp_path, symbol, exchange=exchange, shared=shared)
    original = source_bytes(p)
    stock, evidence = next(runner_data.iter_stocks(p))
    assert np.isnan(stock.o[1]).all()
    assert stock.day_kind[1] == sim.SUSPENDED
    assert np.all(stock.o[2] == 10.0) and stock.day_kind[2] == sim.OK
    checks = evidence["splice"]
    assert checks["ok"] and checks["failures"] == []
    assert checks["resume_day"]["date"] == "2026-08-10"
    exclusions = checks["pre_splice_exclusions"]
    assert len(exclusions) == 1
    row = exclusions[0]
    assert row["date"] == "2026-08-07" and row["reason"] == "suspension_residual_minutes"
    assert (row["prior_daily_date"], row["next_daily_date"]) == ("2026-07-31", "2026-08-10")
    expected = {"vipdoc": 240} if shared else {"vipdoc_single": 240, "vipdoc_main": 240}
    assert row["rows_by_source"] == expected and row["rows"] == sum(expected.values())
    assert source_bytes(p) == original


def test_tt84_adjacent_daily_anchor_may_be_hf_end(tmp_path: Path) -> None:
    p = prepared(tmp_path, "300246", daily_days=(20260806, 20260810))
    stock, report = next(runner_data.iter_stocks(p))
    assert stock.day_kind[1] == sim.SUSPENDED
    assert report["splice"]["pre_splice_exclusions"][0]["prior_daily_date"] == "2026-08-06"


@pytest.mark.parametrize("days", [(20260810,), (20260731,), ()], ids=["no-left", "no-right", "no-anchors"])
def test_tt84_outside_coverage_is_excluded_not_suspended(tmp_path: Path, days: tuple[int, ...]) -> None:
    p = prepared(tmp_path, "300246", daily_days=days)
    original = source_bytes(p)
    stock, report = next(runner_data.iter_stocks(p))
    assert np.isnan(stock.o[1]).all() and stock.day_kind[1] == sim.EXCLUDED
    rows = report["splice"]["pre_splice_exclusions"]
    assert rows and all(row["reason"] == "daily_anchor_outside_coverage" for row in rows)
    aug7 = next(row for row in rows if row["date"] == "2026-08-07")
    assert aug7["rows_by_source"] == {"vipdoc": 240}
    assert aug7["prior_daily_date"] == ("2026-07-31" if days == (20260731,) else None)
    assert aug7["next_daily_date"] == ("2026-08-10" if days == (20260810,) else None)
    if days == (20260810,):
        assert np.all(stock.o[2] == 10.0) and stock.day_kind[2] == sim.OK
    else:
        assert np.isnan(stock.o[2]).all() and stock.day_kind[2] == sim.EXCLUDED
    assert source_bytes(p) == original


def gap_fixture(root: Path, *, resume_price: float = 10.0, shared: bool = True) -> runner_data.Prepared:
    return prepared(
        root, "300333", daily_days=(20260729, 20260813), shared=shared,
        minute_prices=tuple((day, price) for day, price in [
            (date(2026, 8, 7), 10.5), (date(2026, 8, 10), 17.0),
            (date(2026, 8, 11), 3.0), (date(2026, 8, 13), resume_price),
        ]), dates=GAP_DATES,
    )


@pytest.mark.parametrize("shared", [True, False], ids=["shared", "independent"])
def test_tt84_aug10_aug11_gap_residues_removed_resume_checked(tmp_path: Path, shared: bool) -> None:
    p = gap_fixture(tmp_path, shared=shared)
    original = source_bytes(p)
    stock, report = next(runner_data.iter_stocks(p))
    assert np.isnan(stock.o[:5]).all()
    assert np.all(stock.day_kind[:5] == sim.SUSPENDED)
    assert np.all(stock.o[5] == 10.0) and stock.day_kind[5] == sim.OK
    checks = report["splice"]
    assert checks["ok"] and checks["failures"] == []
    assert checks["resume_day"]["date"] == "2026-08-13"
    assert checks["resume_day"]["state"] == "checked"
    assert checks["resume_day"]["rows"] == 240
    assert checks["resume_day"]["volume_state"] == "checked"
    assert checks["resume_day"]["failures"] == []
    assert np.all(stock.c[5] == 10.0) and np.sum(stock.v[5]) == 24000
    rows = checks["pre_splice_exclusions"]
    assert [row["date"] for row in rows] == ["2026-08-07", "2026-08-10", "2026-08-11"]
    for row in rows:
        assert row["reason"] == "suspension_residual_minutes"
        assert (row["prior_daily_date"], row["next_daily_date"]) == ("2026-07-29", "2026-08-13")
        counts = {"vipdoc": 240} if shared else {"vipdoc_main": 240}
        if not shared and row["date"] == "2026-08-07":
            counts["vipdoc_single"] = 240
        assert row["rows_by_source"] == counts and row["rows"] == sum(counts.values())
    assert source_bytes(p) == original


@pytest.mark.parametrize("bad", ["single-price", "single-volume", "resume-price"])
def test_tt84_covered_anchor_failure_still_blocks(tmp_path: Path, bad: str) -> None:
    if bad == "resume-price":
        p, expected = gap_fixture(tmp_path, resume_price=10.5), "resume_day.daily_open"
    else:
        p = prepared(
            tmp_path, "300246", daily_days=(20260731, 20260807, 20260810),
            daily_volume=25000 if bad == "single-volume" else 24000,
            minute_prices=((splice.SINGLE_DAY, 10.0 if bad == "single-volume" else 10.5), (splice.MAIN_START, 10.0)),
        )
        expected = "single_day.daily_volume" if bad == "single-volume" else "single_day.daily_open"
    with pytest.raises(splice.SpliceError) as error:
        next(runner_data.iter_stocks(p))
    assert expected in error.value.summary["splice"]["failures"]


def test_tt84_invalid_exchange_prefix_still_rejected_before_decode(tmp_path: Path) -> None:
    p = prepared(tmp_path, "000838", exchange="SH")
    with pytest.raises(data.DataFormatError, match="refused before reading"):
        next(runner_data.iter_stocks(p))


def test_tt84_duplicate_on_excluded_day_cannot_evade_format_check(tmp_path: Path) -> None:
    p = gap_fixture(tmp_path)
    key = ("SZ", "300333")
    ref = p.main.files[key]
    raw = ref.path.read_bytes()
    ref.path.write_bytes(raw[:32] + raw)
    updated = inputs.Lc1Input(ref.path, data.sha256(ref.path))
    p = replace(p, main=replace(p.main, files={key: updated}))
    with pytest.raises(data.DataFormatError, match="duplicate timestamp"):
        next(runner_data.iter_stocks(p))


def test_tt84_changed_archive_cannot_evade_input_hash(tmp_path: Path) -> None:
    p = gap_fixture(tmp_path)
    p.archive.write_bytes(p.archive.read_bytes() + b"synthetic-changed")
    with pytest.raises(data.DataFormatError, match="hsjday archive changed after preflight"):
        next(runner_data.iter_stocks(p))


def test_tt84_bad_covered_resume_persists_failure_and_never_simulates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = gap_fixture(tmp_path, resume_price=10.5)
    monkeypatch.setattr(runner_data, "preflight", lambda *a, **k: p)

    def forbidden(*a, **k):
        pytest.fail("strategy must not run after covered resume price failure")

    monkeypatch.setattr(runner.exp, "walk_forward", forbidden)
    target = tmp_path / "covered-resume-blocked"
    paths = runner_data.ResearchPaths(tmp_path, None, None, tmp_path / "calendar", live_vipdoc=p.main.root)
    with pytest.raises(splice.SpliceError) as error:
        runner.run(paths, target)
    assert not target.exists()
    failed = outputs.failure_path(target)
    assert {path.name for path in failed.iterdir()} == {"failure.json"}
    saved = json.loads((failed / "failure.json").read_text(encoding="utf-8"))
    assert saved["stage"] == "splice" and saved["status"] == "blocked"
    assert saved["splice"] == error.value.summary["splice"]
    assert "resume_day.daily_open" in saved["splice"]["failures"]
    assert [row["date"] for row in saved["splice"]["pre_splice_exclusions"]] == [
        "2026-08-07", "2026-08-10", "2026-08-11",
    ]
    assert not list(tmp_path.glob(".t-r58-*"))
    assert not list(tmp_path.glob(".*.publishing"))
