# ruff: noqa: S101
"""RV-19 independent counterexamples: synthetic arrays/archives only; no DB/network.

Matching tests supply deterministic signal features to isolate execution semantics;
Market/can_fill/_resolve/accounting remain real. Baseline implementation: 2758487.
"""
from __future__ import annotations

import importlib
import inspect
import json
import math
import struct
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pytest

from retest.t_r58 import data, prepare_tdx, sim, splice, stats
from retest.t_r58.errors import DataFormatError

N = 240


def stock(n: int = 3) -> sim.StockInput:
    shape = (n, N)
    o = np.full(shape, 10.0)
    v = np.full(shape, 10000.0)
    return sim.StockInput(
        "SZ", "000001", [date(2026, 11, 9) + timedelta(days=i) for i in range(n)],
        o, o + 0.01, o - 0.01, o.copy(), v, v * o,
        np.full(n, sim.OK), np.zeros(n, dtype=bool), [],
    )


def bar(s: sim.StockInput, d: int, t: int, price: float, *, volume: float = 10000) -> None:
    s.o[d, t] = s.c[d, t] = price
    s.h[d, t], s.l[d, t] = price + 0.01, price - 0.01
    s.v[d, t], s.a[d, t] = volume, volume * price


def market(s: sim.StockInput, delay: int = 1) -> sim.Market:
    m = sim.Market(s, sim.Params(group="B", d=0.01, stop_mult=10, fill_delay=delay))
    for day in m.days:
        day["dev"][:] = 0.02  # neither revert nor stop; individual tests set exit triggers
    return m


def segment(s: sim.StockInput, *, embargo: bool = True, end: int = -1) -> sim.Segment:
    seg = sim.Segment("fold" if embargo else "holdout", s.dates[0], s.dates[end])
    seg.embargo = embargo  # old dataclass accepts attr; old simulate ignores it (red evidence)
    return seg


@pytest.mark.parametrize("random", [False, True], ids=["real", "R-control"])
def test_rv19_01_future_1500_bar_cannot_rewrite_0931_deferred_fill(random: bool) -> None:
    outcomes = []
    for future_present in (False, True):
        s = stock(2)
        for name in "ohlcva":
            getattr(s, name)[1, :] = np.nan
        bar(s, 1, 0, 10.05)
        s.a[1, 0] *= 100  # invalid at bar END; its opening is still eligible
        if future_present:
            bar(s, 1, 239, 10.0)  # 15:00, beyond 14:56 execution cutoff
        m = market(s)
        assert m.can_fill(1, 0, 5000, True)
        assert not m.days[1]["valid"][0]
        leg = m.entry(segment(s), 0, 234, "sell_first")
        sim._resolve(m, leg, segment(s), random=random, h=5)
        outcomes.append((leg.exit_day, leg.exit_slot, leg.exit_price,
                         leg.pnl_yuan, leg.exec_anomaly))
    assert outcomes[0] == outcomes[1], "15:00 future validity rewrote 09:31 execution"
    assert outcomes[0][:3] == (1, 0, 10.05)
    assert outcomes[0][4] is True


@pytest.mark.parametrize("embargo", [True, False], ids=["fold-last-day", "holdout-last-day"])
def test_rv19_02_last_day_entry_and_no_next_day_price(embargo: bool) -> None:
    for future_price in (1.0, 100.0):
        s = stock()
        for t in range(N):
            bar(s, 2, t, future_price)
        m = market(s)
        m.params.confirm = 1
        m.params.min_edge_cost_mult = 0
        m.params.directions = ("sell_first",)
        m.params.time_stop = "15:00"  # keep qualified last-day leg unsettled
        m.days[0]["dev"][:] = 0  # signals only on the cutoff day
        legs = sim.simulate(s, m.params, [segment(s, embargo=embargo, end=1)], market=m)
        if embargo:
            assert legs == []
        else:
            assert len(legs) == 1
            leg = legs[0]
            assert leg.entry_day == 1 and leg.exit_day is None
            assert leg.reason == "unvaluable_end"
            assert leg.cons_mark_price == 10.0  # never mark with day 2 price


@pytest.mark.parametrize(("trigger", "exit_trigger", "blocked", "expected_exit", "expected_h"), [
    (60, 70, (71, 72, 73, 74), 75, 14),
    (118, 120, (121, 122), 123, 4),  # lunch: count trading bars, no 90-minute gap
])
def test_rv19_03_h_includes_exit_wait_and_crosses_lunch(
    trigger: int, exit_trigger: int, blocked: tuple[int, ...], expected_exit: int, expected_h: int,
) -> None:
    s = stock()
    for t in blocked:
        bar(s, 0, t, 11.0)  # buy-to-cover locked at upper limit
    m = market(s)
    m.limits[0] = (11.0, 9.0)
    m.days[0]["dev"][exit_trigger] = 0
    leg = m.entry(segment(s), 0, trigger, "sell_first")
    sim._resolve(m, leg, segment(s))
    assert leg.exit_slot == expected_exit
    assert leg.hold_bars == expected_h


def test_rv19_03_cross_day_h_is_recorded() -> None:
    s = stock()
    m = market(s)
    leg = m.entry(segment(s), 0, 234, "sell_first")
    sim._resolve(m, leg, segment(s))
    assert (leg.exit_day, leg.exit_slot) == (1, 0)
    assert leg.hold_bars == 5  # entry slot 235 -> next session slot 0


@pytest.mark.parametrize(("trigger", "expected_h"), [(60, 14), (234, 5)])
def test_rv19_03_random_control_retains_actual_h(
    monkeypatch: pytest.MonkeyPatch, trigger: int, expected_h: int,
) -> None:
    s = stock()
    for t in range(71, 75):
        bar(s, 0, t, 11.0)
    m = market(s)
    m.limits[0] = (11.0, 9.0)
    m.days[0]["dev"][70] = 0
    seg = segment(s)
    real = m.entry(seg, 0, trigger, "sell_first")
    sim._resolve(m, real, seg)
    assert real.exit_day is not None
    # Force one R entry at 10:01 (slot 30), away from exit constraints.
    m.params.entry_start = m.params.entry_end = "10:01"
    fills = []
    settle = sim._settle

    def record(*args: Any) -> None:
        settle(*args)
        _, leg, d, slot, _ = args
        fills.append((d, slot - leg.entry_slot, leg.hold_bars))

    monkeypatch.setattr(sim, "_settle", record)
    controls = sim.simulate_random(s, m.params, [seg], [real], draws=1, market=m)
    assert controls[0].n_ok == 1
    assert fills == [(0, expected_h, expected_h)]


def test_rv19_04_entry_counts_fillable_bars_not_slots() -> None:
    s = stock()
    bar(s, 0, 61, 11.0)  # first slot locked, later two executable opens differ
    bar(s, 0, 62, 10.02)
    bar(s, 0, 63, 10.03)
    m = market(s, delay=2)
    m.limits[0] = (11.0, 9.0)
    leg = m.entry(segment(s), 0, 60, "buy_first")
    assert (leg.entry_slot, leg.entry_price) == (63, 10.03)


@pytest.mark.parametrize("reason", ["revert", "stop", "time"])
def test_rv19_04_exit_uses_second_fillable_open(reason: str) -> None:
    s = stock()
    bar(s, 0, 71, 11.0)
    bar(s, 0, 72, 10.02)
    bar(s, 0, 73, 10.03)
    m = market(s, delay=2)
    m.limits[0] = (11.0, 9.0)
    if reason == "time":
        m.params.time_stop = "10:41"  # slot 70
    else:
        m.days[0]["dev"][70] = 0 if reason == "revert" else 0.2
    leg = m.entry(segment(s), 0, 60, "sell_first")
    sim._resolve(m, leg, segment(s))
    assert (leg.exit_slot, leg.exit_price, leg.reason) == (73, 10.03, reason)


def test_rv19_04_deferred_exit_keeps_delay_rule() -> None:
    s = stock()
    bar(s, 1, 0, 10.02)
    bar(s, 1, 1, 10.03)
    m = market(s, delay=2)
    leg = m.entry(segment(s), 0, 233, "sell_first")  # entry235, no later allowed fill today
    assert leg.entry_slot == 235
    sim._resolve(m, leg, segment(s))
    assert (leg.exit_day, leg.exit_slot, leg.exit_price) == (1, 1, 10.03)


def test_rv19_04_deferred_exit_preserves_one_already_counted_open() -> None:
    s = stock()
    bar(s, 0, 235, 10.02)
    bar(s, 1, 0, 10.03)
    m = market(s, delay=2)
    m.params.time_stop = "14:55"  # one eligible opening at 14:56, the next on day 1
    leg = m.entry(segment(s), 0, 60, "sell_first")
    sim._resolve(m, leg, segment(s))
    assert (leg.exit_day, leg.exit_slot, leg.exit_price) == (1, 0, 10.03)


@pytest.mark.parametrize("direction", ["sell_first", "buy_first"])
def test_rv19_05_exit_bar_close_cannot_change_mae(direction: str) -> None:
    results = []
    for exit_close in (10.0, 10.5 if direction == "sell_first" else 9.5):
        s = stock()
        bar(s, 0, 69, 10.1 if direction == "sell_first" else 9.9)
        s.c[0, 71] = exit_close
        s.h[0, 71], s.l[0, 71] = max(10, exit_close) + .01, min(10, exit_close) - .01
        s.a[0, 71] = s.v[0, 71] * (10 + exit_close) / 2
        m = market(s)
        assert m.days[0]["valid"][[69, 71]].all()
        m.days[0]["dev"][70] = 0
        leg = m.entry(segment(s), 0, 60, direction)
        sim._resolve(m, leg, segment(s))
        assert (leg.exit_day, leg.exit_slot, leg.exit_price) == (0, 71, 10.0)
        results.append((leg.pnl_yuan, leg.mae_bp))
    assert results[0] == results[1]
    assert results[0][1] == pytest.approx(-100.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), -.01, 1.01])
def test_rv19_06_holm_never_converts_invalid_trial_to_significance(bad: float) -> None:
    try:
        result = stats.holm([.01, bad])
    except ValueError:
        return  # explicit rejection is an accepted RV-19 contract
    assert len(result) == 2
    assert math.isnan(result[1]), "invalid raw p must be rejected or explicitly undefined"
    assert result[0] == pytest.approx(.02)  # retain family size, never silently drop trial


def test_rv19_06_all_nan_is_not_zero_and_family_size_is_34() -> None:
    try:
        result = stats.holm([float("nan")])
    except ValueError:
        pass
    else:
        assert len(result) == 1 and (math.isnan(result[0]) or result[0] == 1)
    corrected = stats.holm([.001] + [1.0] * 33)
    assert len(corrected) == 34
    assert corrected == pytest.approx([.034] + [1.0] * 33)


@pytest.fixture
def prepared_tdx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    def offline(*args: object, **kwargs: object) -> None:
        pytest.fail("synthetic archive fixture must never download")
    monkeypatch.setattr(prepare_tdx.urllib.request, "urlopen", offline)
    daily = struct.pack("<IIIIIfII", 20261110, 1000, 1001, 999, 1000, 100000., 10000, 0)
    with zipfile.ZipFile(tmp_path / "hsjday.zip", "w") as z:
        for code in ("sh000001", "sh000300"):
            z.writestr(f"sh/lday/{code}.day", daily)
    with zipfile.ZipFile(tmp_path / "gbbq.zip", "w") as z:
        z.writestr("gbbq", struct.pack("<I", 0))
    return tmp_path, prepare_tdx.prepare(tmp_path)


@pytest.mark.parametrize("name", ["hsjday", "gbbq"])
def test_rv19_07_prepared_names_load_directly_with_hash_evidence(prepared_tdx: tuple[Path, dict], name: str) -> None:
    root, manifest = prepared_tdx
    before = data.sha256(root / f"{name}.zip")
    assert before == manifest[name]["sha256"]
    if name == "hsjday":
        assert data.load_index_close(root) == {date(2026, 11, 10): 10.0}
    else:
        assert data.load_gbbq(root) == {}
    assert data.sha256(root / f"{name}.zip") == before


@pytest.mark.parametrize("name", ["hsjday", "gbbq"])
def test_rv19_07_changed_archive_is_rejected(prepared_tdx: tuple[Path, dict], name: str) -> None:
    root, manifest = prepared_tdx
    path = root / f"{name}.zip"
    with zipfile.ZipFile(path, "a") as archive:
        archive.comment = b"synthetic post-verification mutation"
    assert data.sha256(path) != manifest[name]["sha256"]
    loader = data.load_index_close if name == "hsjday" else data.load_gbbq
    with pytest.raises(DataFormatError, match="SHA"):
        loader(root)


def calendars(tmp_path: Path) -> tuple[Path, Path, list[date]]:
    dates = [date(2026, 8, 7), date(2026, 8, 10), date(2026, 11, 10)]
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "market_calendar.csv").write_text("date,is_trading_day\n2026-08-07,True\n", encoding="utf-8")
    announced = tmp_path / "calendar_2026.json"
    announced.write_text(json.dumps({
        "coverage_start": "2026-01-01", "coverage_end": "2026-12-31",
        "open_days": [d.isoformat() for d in dates], "source": "synthetic pre-announced fixture",
    }), encoding="utf-8")
    return meta, announced, dates


def merged(meta: Path, announced: Path, dates: list[date], *, expected: int = 3) -> list[date]:
    # Preserve the old call to expose silent truncation; new contract adds independent inputs.
    kwargs = ({"calendar_2026": announced, "index_dates": dates, "expected_days": expected}
              if "calendar_2026" in inspect.signature(data.calendar).parameters else {})
    return data.calendar(meta, date(2026, 8, 7), date(2026, 11, 10), **kwargs)


def test_rv19_08_announced_tail_enters_grid_and_simulation(tmp_path: Path) -> None:
    meta, announced, expected = calendars(tmp_path)
    dates = merged(meta, announced, expected)
    assert dates == expected, "HF end must not silently truncate holdout tail"
    rows = [{"symbol": "000001", "exchange": "SZ",
             "timestamp": datetime.combine(d, time(9, 31), tzinfo=ZoneInfo("Asia/Shanghai")),
             "open": 10., "high": 10.01, "low": 9.99, "close": 10.,
             "volume": 10000., "turnover": 100000., "is_bj": False} for d in expected]
    grid, checks = data.grid_from_table(pa.Table.from_pylist(rows, schema=splice.SCHEMA), dates)
    assert checks["outside_dates"] == 0 and grid["present"][:, 0].all()
    s = stock(3)
    s.dates = dates
    for key in "ohlcva":
        setattr(s, key, grid[key])
    m = market(s)
    m.params.entry_start, m.params.entry_end = "09:31", "09:31"
    m.params.confirm, m.params.sigma_warmup = 1, 1
    m.params.min_edge_cost_mult = 0
    counts: dict[str, int] = {}
    sim.simulate(s, m.params, [segment(s, embargo=False)], counts, market=m)
    assert counts["signals"] == 2  # both 08-10 and 11-10 reach simulation, not just grid


@pytest.mark.parametrize("corruption", ["index-missing-tail", "count-not-1174"])
def test_rv19_08_calendar_disagreement_stops(tmp_path: Path, corruption: str) -> None:
    meta, announced, dates = calendars(tmp_path)
    if corruption == "index-missing-tail":
        dates = dates[:-1]
        expected = 3
    else:
        expected = 1174
    with pytest.raises(DataFormatError):
        merged(meta, announced, dates, expected=expected)


def test_rv19_08_fold_or_holdout_boundary_mismatch_stops() -> None:
    sessions = importlib.import_module("retest.t_r58.sessions")
    days = [date(2022, 1, 1) + timedelta(days=i) for i in range(1174)]
    windows, offset = [], 0
    for count in (305, 126, 126, 125, 125, 125, 242):
        windows.append([days[offset].isoformat(), days[offset + count - 1].isoformat()])
        offset += count
    cfg = {"segments": {"warmup": windows[0], "folds": windows[1:6], "holdout": windows[6]}}
    segments, _ = sessions.segments(cfg, days)
    assert len(segments) == 6
    assert [s.embargo for s in segments] == [True] * 5 + [False]
    for window in windows[1:]:
        old = window[1]
        window[1] = (date.fromisoformat(old) - timedelta(days=1)).isoformat()
        with pytest.raises(DataFormatError):
            sessions.segments(cfg, days)
        window[1] = old
