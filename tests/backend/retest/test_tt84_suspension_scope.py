# ruff: noqa: S101
"""T-T84 four-stock suspension exception boundaries, synthetic source files only."""
from __future__ import annotations

import json
import struct
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from retest.t_r58 import data, inputs, outputs, runner, runner_data, sim, splice


def prepared(root: Path, symbol: str, *, exchange: str = "SZ", daily_days=(20260731, 20260810), shared=True):
    key = (exchange, symbol)
    raw = bytearray()
    for day, price in ((splice.SINGLE_DAY, 10.5), (splice.MAIN_START, 10.0)):
        packed = (day.year - 2004) * 2048 + day.month * 100 + day.day
        raw.extend(struct.pack("<HHfffffII", packed, 571, price, price, price, price, price * 100, 100, 0))
    source_dir = root / "vipdoc"
    source_dir.mkdir()
    path = source_dir / (exchange.lower() + symbol + ".lc1")
    path.write_bytes(raw)
    ref = inputs.Lc1Input(path, data.sha256(path))
    daily_path = root / "hsjday.zip"
    with zipfile.ZipFile(daily_path, "w") as z:
        z.writestr(f"{exchange.lower()}/lday/{exchange.lower()}{symbol}.day", b"".join(
            struct.pack("<IIIIIfII", d, 1000, 1000, 1000, 1000, 1000., 100, 0) for d in daily_days))
    dates = [splice.HF_END, splice.SINGLE_DAY, splice.MAIN_START]
    listed = date(2010, 1, 1)
    meta = {"coverage": {symbol: {"listing_date": listed}}, "confirmed_suspension": set(), "securities": {}}
    package = inputs.VipdocInput(source_dir, {key: ref}, "", "", "")
    return runner_data.Prepared(dates, [sim.Segment("holdout", dates[0], dates[-1], embargo=False)],
        [(*key, "L")], root / "hf", {}, None if shared else package,
        inputs.LocalVipdoc(source_dir, {key: ref}, ref.sha256) if shared else package,
        daily_path, data.sha256(daily_path), {}, {}, meta,
        {key: [(listed, None, False)]}, {key: [(listed, None, "listed")]}, {})


@pytest.mark.parametrize("symbol", ["000838", "300246", "300333", "300862"])
def test_tt84_only_aug7_removed_and_source_unchanged(tmp_path: Path, symbol: str) -> None:
    p = prepared(tmp_path, symbol)
    source = next(iter(p.main.files.values())).path
    original = source.read_bytes()
    stock, evidence = next(runner_data.iter_stocks(p))
    assert np.isnan(stock.o[1]).all() and stock.day_kind[1] == sim.SUSPENDED
    assert stock.o[2, 0] == 10.0
    assert evidence["splice"]["ok"]
    exclusion = evidence["splice"]["pre_splice_exclusions"]
    assert len(exclusion) == 1 and exclusion[0]["date"] == "2026-08-07" and exclusion[0]["rows"] == 1
    assert evidence["lc1"]["single"]["rows"] == 1  # source evidence retained
    assert source.read_bytes() == original


@pytest.mark.parametrize(("symbol", "exchange", "days", "shared"), [
    ("300247", "SZ", (20260731, 20260810), True),
    ("000838", "SH", (20260731, 20260810), True),
    ("300246", "SZ", (20260810,), True),
    ("300246", "SZ", (20260731,), True),
    ("300246", "SZ", (20260806, 20260810), True),
    ("300246", "SZ", (20260731, 20260807, 20260810), True),
    ("300246", "SZ", (20260731, 20260810), False),
])
def test_tt84_exception_does_not_expand(tmp_path: Path, symbol: str, exchange: str, days: tuple, shared: bool) -> None:
    p = prepared(tmp_path, symbol, exchange=exchange, daily_days=days, shared=shared)
    with pytest.raises(data.DataFormatError) as error:
        next(runner_data.iter_stocks(p))
    if exchange == "SH":
        assert "refused before reading" in str(error.value)
    else:
        assert isinstance(error.value, splice.SpliceError)
        assert error.value.summary["splice"]["failures"]
        assert "pre_splice_exclusions" not in error.value.summary["splice"]


def test_tt84_aug10_missing_anchor_remains_blocked_and_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = prepared(tmp_path, "300333", daily_days=(20260729, 20260813))
    monkeypatch.setattr(runner_data, "preflight", lambda *a, **k: p)
    def forbidden(*a, **k):
        pytest.fail("strategy must not run after missing Aug10 anchor")
    monkeypatch.setattr(runner.exp, "walk_forward", forbidden)
    target = tmp_path / "aug10-blocked"
    paths = runner_data.ResearchPaths(tmp_path, None, None, tmp_path / "calendar", live_vipdoc=p.main.root)
    with pytest.raises(splice.SpliceError):
        runner.run(paths, target)
    assert not target.exists()
    failed = outputs.failure_path(target)
    assert {f.name for f in failed.iterdir()} == {"failure.json"}
    saved = json.loads((failed / "failure.json").read_text(encoding="utf-8"))
    assert saved["stage"] == "splice"
    assert "resume_day.missing_daily_anchor" in saved["splice"]["failures"]
    assert saved["splice"]["resume_day"]["date"] == "2026-08-10"
    assert saved["splice"]["pre_splice_exclusions"][0]["date"] == "2026-08-07"
