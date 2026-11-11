"""Restore exact legacy constraints approved by Chief in PR81 comment 6805134386.

These checks complement the real merge and adjustment cases in
``test_splice_validation.py``; they do not certify the full gbbq decode chain.
All input bytes are synthetic and consumed by the real lc1 decoder.
"""

from __future__ import annotations

import datetime as dt
import struct
from pathlib import Path

import pyarrow as pa
import pytest
from retest.t_r58 import splice


def test_main_start_exact_legacy_date() -> None:
    assert splice.MAIN_START == dt.date(2026, 8, 10)


def test_overlap_start_exact_legacy_date() -> None:
    assert splice.OVERLAP_START == dt.date(2026, 4, 24)


@pytest.mark.parametrize("symbol", ["600000", "688001"])
def test_overlap_codes_retain_legacy_members(symbol: str) -> None:
    assert symbol in splice.OVERLAP_CODES


def test_decoded_open_retains_exact_float64_type(tmp_path: Path) -> None:
    day = dt.date(2026, 8, 7)
    encoded_day = (day.year - 2004) * 2048 + day.month * 100 + day.day
    content = struct.pack(
        "<HHfffffII",
        encoded_day,
        9 * 60 + 31,
        10.0,
        10.01,
        9.99,
        10.0,
        100000.0,
        10000,
        0,
    )
    path = tmp_path / "600000.lc1"
    path.write_bytes(content)
    table, _ = splice.decode_lc1(path, "SH", "600000")
    assert table.num_rows == 1
    assert table.schema.field("open").type == pa.float64()
    assert table["open"].to_pylist() == [10.0]
    assert path.read_bytes() == content
