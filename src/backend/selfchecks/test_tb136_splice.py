# ruff: noqa: S101
"""Product-facing splice checks using T-T81's committed synthetic generators only."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType

import numpy as np
import pyarrow as pa
import pytest

from retest.t_r58 import data, sim, splice
from retest.t_r58.errors import DataFormatError


@pytest.fixture(scope="module")
def builders(pytestconfig: pytest.Config) -> ModuleType:
    pytestconfig.addinivalue_line("markers", "pending_impl: T-T81 generator-module metadata")
    path = Path(__file__).resolve().parents[3] / "tests/backend/retest/test_splice_validation.py"
    spec = importlib.util.spec_from_file_location("tb136_synthetic_builders", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("committed T-T81 synthetic generator unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tables(builders: ModuleType, tmp_path: Path) -> tuple[pa.Table, pa.Table, pa.Table]:
    hf = builders.HfBuilder()
    hf.add_day(splice.HF_END, "600001")
    single, main = builders.Lc1Builder(), builders.Lc1Builder()
    single.add_day(splice.SINGLE_DAY)
    main.add_day(splice.MAIN_START)
    a = splice.decode_lc1(single.write(tmp_path / "single", "sh", "600001"), "SH", "600001")[0]
    b = splice.decode_lc1(main.write(tmp_path / "main", "sh", "600001"), "SH", "600001")[0]
    return pa.Table.from_pylist(hf.rows, schema=splice.SCHEMA), a, b


def anchors() -> dict[date, splice.DailyBar]:
    return {
        day: splice.DailyBar(10.0, 10.0, 2_400_000)
        for day in (splice.HF_END, splice.SINGLE_DAY, splice.MAIN_START)
    }


def changed(table: pa.Table, column: str, index: int, value: float) -> pa.Table:
    values = table[column].to_numpy().copy()
    values[index] = value
    return table.set_column(table.schema.get_field_index(column), column, pa.array(values))


def test_tb136_decode_units_timestamp_and_source_unchanged(
    builders: ModuleType, tmp_path: Path
) -> None:
    builder = builders.Lc1Builder()
    builder.add_day(splice.SINGLE_DAY)
    path = builder.write(tmp_path, "sh", "600001")
    original = path.read_bytes()
    table, checks = splice.decode_lc1(path, "SH", "600001")
    assert table["open"][0].as_py() == 10.0
    assert table["volume"][0].as_py() == 10000
    assert table["turnover"][0].as_py() == 100000.0
    assert table["timestamp"][0].as_py().strftime("%Y-%m-%d %H:%M") == "2026-08-07 09:31"
    assert table["timestamp"].type.tz == "Asia/Shanghai"
    assert checks["non_240_stock_days"] == 0
    assert path.read_bytes() == original


def test_tb136_price_half_up_not_bankers(builders: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "600001.lc1"
    path.write_bytes(
        builders._encode_min_line(
            splice.SINGLE_DAY, 571, 10.125, 10.125, 10.125, 10.125, 101250.0, 10000
        )
    )
    table, _ = splice.decode_lc1(path, "SH", "600001")
    assert table["open"][0].as_py() == 10.13


def test_tb136_truncated_lc1_stops(tmp_path: Path) -> None:
    path = tmp_path / "600001.lc1"
    path.write_bytes(b"x" * 31)
    with pytest.raises(DataFormatError, match="truncated"):
        splice.decode_lc1(path, "SH", "600001")


def test_tb136_out_of_date_minute_stops(builders: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "600001.lc1"
    path.write_bytes(
        builders._encode_min_line(splice.SINGLE_DAY, 1440 + 571, 10, 10, 10, 10, 100000, 10000)
    )
    with pytest.raises(DataFormatError, match="outside its encoded date"):
        splice.decode_lc1(path, "SH", "600001")


def test_tb136_bj_refused_before_file_read(tmp_path: Path) -> None:
    with pytest.raises(DataFormatError, match="before reading"):
        splice.decode_lc1(tmp_path / "does-not-exist.lc1", "BJ", "920001")


def test_tb136_file_selection_reads_only_authorized_prefixes(tmp_path: Path) -> None:
    for exchange, symbol in (
        ("sh", "600001"),
        ("sz", "300001"),
        ("sh", "510300"),
        ("sh", "000001"),
        ("sz", "200001"),
        ("bj", "920001"),
    ):
        directory = tmp_path / exchange / "minline"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{exchange}{symbol}.lc1").write_bytes(b"must not be decoded here")
    assert set(splice.selected_lc1(tmp_path)) == {("SH", "600001"), ("SZ", "300001")}


def test_tb136_1300_repair_requires_all_other_239_labels(
    builders: ModuleType, tmp_path: Path
) -> None:
    builder = builders.Lc1Builder()
    builder.add_day(splice.SINGLE_DAY)
    builder.relabel_last_morning_to_1300(splice.SINGLE_DAY)
    table, checks = splice.decode_lc1(builder.write(tmp_path, "sh", "600001"), "SH", "600001")
    labels = [stamp.strftime("%H:%M") for stamp in table["timestamp"].to_pylist()]
    assert len(labels) == 240
    assert "11:30" in labels
    assert "13:00" not in labels
    assert checks["relabelled_1300"] == 1
    assert checks["dropped_unconfirmed_1300"] == 0


def test_tb136_incomplete_1300_is_missing_bar(builders: ModuleType, tmp_path: Path) -> None:
    builder = builders.Lc1Builder()
    builder.add_day(
        splice.SINGLE_DAY, labels=[*builders.MORNING[:-2], "13:00", *builders.AFTERNOON]
    )
    table, checks = splice.decode_lc1(builder.write(tmp_path, "sh", "600001"), "SH", "600001")
    assert table.num_rows == 238
    assert checks["relabelled_1300"] == 0
    assert checks["dropped_unconfirmed_1300"] == 1
    assert checks["non_240_stock_days"] == 1


def test_tb136_1130_and_1300_coexist_stops(builders: ModuleType, tmp_path: Path) -> None:
    builder = builders.Lc1Builder()
    builder.add_day(splice.SINGLE_DAY, labels=[*builders.MORNING, "13:00", *builders.AFTERNOON])
    with pytest.raises(DataFormatError, match="coexist"):
        splice.decode_lc1(builder.write(tmp_path, "sh", "600001"), "SH", "600001")


def test_tb136_pre_filter_illegal_label_stops(builders: ModuleType, tmp_path: Path) -> None:
    builder = builders.Lc1Builder()
    builder.add_day(date(2026, 4, 24), labels=["09:30"])
    builder.add_day(splice.MAIN_START)
    with pytest.raises(DataFormatError, match="illegal bar-end label"):
        splice.decode_lc1(builder.write(tmp_path, "sh", "600001"), "SH", "600001")


def test_tb136_duplicate_timestamp_stops(builders: ModuleType, tmp_path: Path) -> None:
    builder = builders.Lc1Builder()
    builder.add_day(splice.SINGLE_DAY, labels=["09:31", "09:31"])
    with pytest.raises(DataFormatError, match="duplicate"):
        splice.decode_lc1(builder.write(tmp_path, "sh", "600001"), "SH", "600001")


def test_tb136_missing_bar_not_whole_day_exclusion(builders: ModuleType, tmp_path: Path) -> None:
    hf, single, main = tables(builders, tmp_path)
    single = single.slice(1)
    grid, checks = data.load_spliced_stock(
        hf,
        single,
        main,
        [splice.HF_END, splice.SINGLE_DAY, splice.MAIN_START],
        anchors(),
        exchange="SH",
        symbol="600001",
    )
    assert checks["splice"]["ok"]
    assert checks["splice"]["incomplete_volume_days"] == 1
    assert checks["missing_bars"] == 1
    assert not grid["present"][1, 0]
    assert grid["present"][1, 1:].all()


@pytest.mark.parametrize("kind", ["close", "volume", "open"])
def test_tb136_one_stock_splice_failure_stops_instead_of_exclusion(
    builders: ModuleType,
    tmp_path: Path,
    kind: str,
) -> None:
    hf, single, main = tables(builders, tmp_path)
    if kind == "close":
        hf = changed(hf, "close", 239, 9.0)
    elif kind == "volume":
        single = changed(single, "volume", 30, 9e8)
    else:
        single = changed(single, "open", 0, 11.0)
    with pytest.raises(splice.SpliceError) as error:
        data.load_spliced_stock(
            hf,
            single,
            main,
            [splice.HF_END, splice.SINGLE_DAY],
            anchors(),
            exchange="SH",
            symbol="600001",
        )
    assert "600001" in str(error.value)
    assert error.value.summary["splice"]["failures"]
    assert not error.value.summary["splice"]["ok"]


def test_tb136_unpaired_stock_unilateral_checks(builders: ModuleType, tmp_path: Path) -> None:
    _, single, main = tables(builders, tmp_path)
    result = splice.check_splice(
        splice.empty_table(), single, main, anchors(), exchange="SH", symbol="600001"
    )["splice"]
    assert result["ok"]
    assert not result["paired"]
    assert result["single_day"]["state"] == "checked"


def test_tb136_resume_day_checked_when_single_day_absent(
    builders: ModuleType, tmp_path: Path
) -> None:
    hf, _, main = tables(builders, tmp_path)
    result = splice.check_splice(
        hf, splice.empty_table(), main, anchors(), exchange="SH", symbol="600001"
    )["splice"]
    assert result["ok"]
    assert not result["paired"]
    assert result["resume_day"]["date"] == "2026-08-10"


def test_tb136_exdate_reference_not_raw_close(builders: ModuleType, tmp_path: Path) -> None:
    hf, single, main = tables(builders, tmp_path)
    for column in ("open", "high", "low", "close"):
        single = single.set_column(
            single.schema.get_field_index(column), column, pa.array(single[column].to_numpy() / 2)
        )
    daily = anchors()
    daily[splice.SINGLE_DAY] = splice.DailyBar(5.0, 5.0, 2_400_000)
    with pytest.raises(splice.SpliceError, match="overnight_price_limit"):
        splice.check_splice(hf, single, main, daily, exchange="SH", symbol="600001")
    event = sim.Event(splice.SINGLE_DAY, cash=0, pp=0, s=1, r=0)
    assert splice.check_splice(
        hf, single, main, daily, exchange="SH", symbol="600001", events=[event]
    )["splice"]["ok"]


def test_tb136_future_event_cannot_repair_bad_jump(builders: ModuleType, tmp_path: Path) -> None:
    hf, single, main = tables(builders, tmp_path)
    single = changed(single, "open", 0, 5.0)
    daily = anchors()
    daily[splice.SINGLE_DAY] = splice.DailyBar(5.0, 10.0, 2_400_000)
    with pytest.raises(splice.SpliceError, match="overnight_price_limit"):
        splice.check_splice(
            hf,
            single,
            main,
            daily,
            exchange="SH",
            symbol="600001",
            events=[sim.Event(splice.MAIN_START, 0, 0, 1, 0)],
        )


def test_tb136_dual_package_mismatch_stops(builders: ModuleType, tmp_path: Path) -> None:
    hf, single, main = tables(builders, tmp_path)
    repeated = changed(single, "turnover", 30, 123456.0)
    main = pa.concat_tables([repeated, main])
    with pytest.raises(splice.SpliceError, match="dual_package_mismatch"):
        splice.check_splice(hf, single, main, anchors(), exchange="SH", symbol="600001")


@pytest.mark.parametrize(("bad_rows", "passes"), [(4, True), (5, False)])
def test_tb136_overlap_threshold_checked_on_real_bars(
    builders: ModuleType,
    tmp_path: Path,
    bad_rows: int,
    passes: bool,
) -> None:
    hf, single, main = tables(builders, tmp_path)
    overlap = hf
    for i in range(bad_rows):
        overlap = changed(overlap, "volume", i, 20000.0)
    main = pa.concat_tables([overlap, single, main])
    if passes:
        result = splice.check_splice(
            hf, single, main, anchors(), exchange="SH", symbol="600001", require_overlap=True
        )["splice"]
        assert result["overlap"]["volume_share"] == pytest.approx(236 / 240)
    else:
        with pytest.raises(splice.SpliceError, match="overlap_below_98pct"):
            splice.check_splice(
                hf, single, main, anchors(), exchange="SH", symbol="600001", require_overlap=True
            )


def test_tb136_merge_one_source_per_day_and_summary_splice(
    builders: ModuleType, tmp_path: Path
) -> None:
    hf, single, main = tables(builders, tmp_path)
    main = pa.concat_tables([hf, single, main])
    grid, checks = data.load_spliced_stock(
        hf,
        single,
        main,
        [splice.HF_END, splice.SINGLE_DAY, splice.MAIN_START],
        anchors(),
        exchange="SH",
        symbol="600001",
    )
    assert checks["rows"] == 720
    assert grid["present"].shape == (3, 240)
    assert grid["present"].all()
    assert checks["splice"]["one_source_per_stock_day"]
    assert checks["splice"]["source_rows"] == {"HF": 240, "vipdoc_single": 240, "vipdoc_main": 240}
    np.testing.assert_array_equal(grid["o"], 10.0)


def test_tb136_splice_jump_uses_board_price_limit(builders: ModuleType, tmp_path: Path) -> None:
    hf, single, main = tables(builders, tmp_path)
    single = changed(single, "open", 0, 11.5)
    daily = anchors()
    daily[splice.SINGLE_DAY] = splice.DailyBar(11.5, 10.0, 2_400_000)
    with pytest.raises(splice.SpliceError, match="overnight_price_limit"):
        splice.check_splice(hf, single, main, daily, exchange="SH", symbol="600001")
    renamed = [
        table.set_column(
            table.schema.get_field_index("symbol"), "symbol", pa.array(["688001"] * table.num_rows)
        )
        for table in (hf, single, main)
    ]
    assert splice.check_splice(
        *renamed, daily, exchange="SH", symbol="688001", require_overlap=False
    )["splice"]["ok"]


def test_tb136_hf_timezone_and_bj_row_fail_closed(builders: ModuleType, tmp_path: Path) -> None:
    hf, single, main = tables(builders, tmp_path)
    timestamp = hf["timestamp"].cast(pa.timestamp("us", tz="UTC"))
    bad = hf.set_column(hf.schema.get_field_index("timestamp"), "timestamp", timestamp)
    with pytest.raises(DataFormatError, match="Asia/Shanghai"):
        splice.check_splice(bad, single, main, anchors(), exchange="SH", symbol="600001")
    bad = hf.set_column(hf.schema.get_field_index("is_bj"), "is_bj", pa.array([True] * 240))
    with pytest.raises(DataFormatError, match="BJ row"):
        splice.check_splice(bad, single, main, anchors(), exchange="SH", symbol="600001")
