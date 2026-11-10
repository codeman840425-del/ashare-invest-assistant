# ruff: noqa: S101
"""RV-19 archive preparation-to-loading and pre-announced calendar isolation."""

from __future__ import annotations

import csv
import json
import struct
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from retest.t_r58 import data, prepare_tdx, sessions, sim, splice
from retest.t_r58.errors import DataFormatError
from selfchecks import tb136_retest as synthetic


def calendar_files(tmp_path: Path) -> tuple[Path, list[date]]:
    days = [date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11)]
    with (tmp_path / "market_calendar.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["date", "is_trading_day"])
        writer.writeheader()
        for day in days[:2]:
            writer.writerow({"date": str(day), "is_trading_day": True})
    path = tmp_path / "announced.json"
    path.write_text(
        json.dumps(
            {
                "coverage_start": "2026-01-01",
                "coverage_end": "2026-12-31",
                "open_days": [str(day) for day in days],
                "source": "synthetic",
            }
        ),
        encoding="utf-8",
    )
    return path, days


def test_tb136_calendar_uses_published_tail_then_independent_index(tmp_path: Path) -> None:
    path, wanted = calendar_files(tmp_path)
    result = data.calendar(
        tmp_path, wanted[0], wanted[-1], calendar_2026=path, index_dates=wanted, expected_days=4
    )
    assert result == wanted


def test_tb136_index_never_defines_calendar_by_itself(tmp_path: Path) -> None:
    path, days = calendar_files(tmp_path)
    with pytest.raises(DataFormatError, match="independently defined"):
        data.calendar(
            tmp_path, days[0], days[-1], calendar_2026=path, index_dates=days[:-1], expected_days=3
        )


def test_tb136_hf_published_calendar_mismatch_stops(tmp_path: Path) -> None:
    path, days = calendar_files(tmp_path)
    config = json.loads(path.read_text(encoding="utf-8"))
    config["open_days"].remove("2026-08-07")
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(DataFormatError, match="calendars disagree"):
        data.calendar(
            tmp_path, days[0], days[-1], calendar_2026=path, index_dates=days, expected_days=4
        )


def test_tb136_calendar_count_is_hard_gate(tmp_path: Path) -> None:
    path, days = calendar_files(tmp_path)
    with pytest.raises(DataFormatError, match="differs from 1174"):
        data.calendar(tmp_path, days[0], days[-1], calendar_2026=path, index_dates=days)


def test_tb136_published_tail_enters_grid_and_simulation(tmp_path: Path) -> None:
    path, days = calendar_files(tmp_path)
    for i in range(1, 7):
        days.insert(0, date(2026, 8, 6) - timedelta(days=i))
    with (tmp_path / "market_calendar.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["date", "is_trading_day"])
        writer.writeheader()
        for day in days[:-2]:
            writer.writerow({"date": str(day), "is_trading_day": True})
    config = json.loads(path.read_text(encoding="utf-8"))
    config["open_days"] = [str(day) for day in days]
    path.write_text(json.dumps(config), encoding="utf-8")
    dates = data.calendar(
        tmp_path, days[0], days[-1], calendar_2026=path, index_dates=days, expected_days=10
    )
    rows = []
    bars = [*synthetic._base(8), synthetic._sell_day(), synthetic._flat_day()]
    for day, arrays in zip(dates, bars, strict=True):
        for t, label in enumerate(splice.features.SLOT_END):
            hh, mm = (int(value) for value in label.split(":"))
            from datetime import datetime, timezone

            stamp = datetime(
                day.year, day.month, day.day, hh, mm, tzinfo=timezone(timedelta(hours=8))
            )
            values = dict(
                zip(
                    ("open", "high", "low", "close", "volume", "turnover"),
                    [float(array[t]) for array in arrays],
                    strict=True,
                )
            )
            rows.append(
                {"symbol": "600001", "exchange": "SH", "timestamp": stamp, "is_bj": False, **values}
            )
    grid, checks = data.grid_from_table(pa.Table.from_pylist(rows, schema=splice.SCHEMA), dates)
    stock = sim.StockInput(
        "SH",
        "600001",
        dates,
        *[grid[k] for k in "ohlcva"],
        np.full(10, sim.OK),
        np.zeros(10, dtype=bool),
        [],
    )
    legs = sim.simulate(
        stock,
        sim.Params(group="B", d=0.01),
        [sim.Segment("holdout", dates[0], dates[-1], embargo=False)],
    )
    assert checks["outside_dates"] == 0
    assert dates[legs[0].entry_day] == date(2026, 8, 10)


def test_tb136_segment_sizes_and_cutoff_must_match_config() -> None:
    config = data.load_config(Path(data.__file__).with_name("config.yaml"))
    bounds = [
        config["segments"]["warmup"],
        *config["segments"]["folds"],
        config["segments"]["holdout"],
    ]
    dates = []
    for (a, b), count in zip(bounds, [305, 126, 126, 125, 125, 125, 242], strict=True):
        start, end = date.fromisoformat(a), date.fromisoformat(b)
        # Artificial session spacing, used only to test fixed window validation.
        dates.extend([start + timedelta(days=i) for i in range(count - 1)])
        dates.append(end)
    segments, counts = sessions.segments(config, dates)
    assert len(dates) == 1174
    assert not segments[-1].embargo
    assert all(segment.embargo for segment in segments[:-1])
    assert counts["holdout"]["trading_days"] == 242
    with pytest.raises(DataFormatError, match="wrong size"):
        sessions.segments(config, dates[:-1])


def test_tb136_prepare_tdx_output_loads_without_manual_renaming(tmp_path: Path) -> None:
    daily = struct.pack("<IIIIIfII", 20261110, 1000, 1010, 990, 1000, 100000.0, 10000, 0)
    with zipfile.ZipFile(tmp_path / "hsjday.zip", "w") as archive:
        archive.writestr("sh\\lday\\sh000001.day", daily)
        archive.writestr("sh\\lday\\sh000300.day", daily)
    with zipfile.ZipFile(tmp_path / "gbbq.zip", "w") as archive:
        archive.writestr("gbbq", struct.pack("<I", 0))
    prepared = prepare_tdx.prepare(tmp_path)
    assert data.load_index_close(tmp_path) == {date(2026, 11, 10): 10.0}
    assert data.load_gbbq(tmp_path) == {}
    assert data.load_index_close(
        tmp_path / "hsjday.zip", expected_sha256=prepared["hsjday"]["sha256"]
    )
    assert data.load_gbbq(tmp_path / "gbbq.zip", expected_sha256=prepared["gbbq"]["sha256"]) == {}
    with (tmp_path / "hsjday.zip").open("ab") as stream:
        stream.write(b"changed snapshot")
    with pytest.raises(DataFormatError, match="SHA changed"):
        data.load_index_close(tmp_path)


def test_tb136_bad_archive_hash_blocks_even_if_zip_is_readable(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "gbbq.zip", "w") as archive:
        archive.writestr("gbbq", struct.pack("<I", 0))
    with pytest.raises(DataFormatError, match="SHA changed"):
        data.load_gbbq(tmp_path, expected_sha256="0" * 64)
