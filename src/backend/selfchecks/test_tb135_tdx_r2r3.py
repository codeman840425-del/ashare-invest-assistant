# ruff: noqa: S101, E501, PT018
"""T-B135 编排者裁定②③（tasks/T-B135.md「编排者裁定（11:55）」）。

- ②：float32 有限但极大的值（量化抛 InvalidOperation，或超出写库列 ``app.db.base.MONEY``
  = Numeric(20,4) 的整数位）与 M2 一致，按记录拒绝并计数，其余记录照常处理，整次运行不退出。
  「极大」只以量化/写库类型实际会不会出错为准，不引入新阈值。
- ③：运行中途出错时删除审计目录里对账报告的 ``.part`` 临时文件，并记一条日志。

合成样本均为虚构数据；不连库、不出网、不调用麦蕊。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import struct
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.db.base import MONEY
from app.ingest import tdx_local
from app.ingest.tdx_local import TdxBar, parse_day_bytes, parse_lc_bytes, run_import
from selfchecks.test_tb133_tdx_local import (
    FakeDeps,
    day_rec,
    good_day,
    lc_rec,
    make_root,
    run_daily,
    write,
)
from selfchecks.test_tb135_tdx_m1_m3 import D1, D2, NOW, _three_files

REASON = "out_of_range"


def _f32(x: float) -> float:
    """float32 往返后的实际值（文件里存的就是它）。"""
    return float(struct.unpack("<f", struct.pack("<f", x))[0])


# 写库列整数位上限取自 MONEY 类型本身（Numeric(20,4) → 16 位整数）。
INT_DIGITS = MONEY.precision - MONEY.scale
FITS = _f32(9e15)  # 9000000202358784：16 位整数，可写入
OVERFLOW = _f32(1e16)  # 10000000272564224：17 位整数，写库溢出（量化本身不报错）


def test_r2_boundary_values_are_what_the_test_claims() -> None:
    assert INT_DIGITS == 16
    assert len(str(int(FITS))) == 16 and len(str(int(OVERFLOW))) == 17


# ---------------------------------------------------------------- ②


def test_r2_lc_huge_finite_rejected_per_record() -> None:
    day = dt.date(2023, 11, 6)
    good = lc_rec(day, 571, 10.0, 10.1, 9.9, 10.0, 100500.0, 10000)
    data = (
        good
        + lc_rec(day, 572, 1e30, 1e30, 1e30, 1e30, 100500.0, 10000)  # 价格量化 InvalidOperation
        + lc_rec(day, 573, 10.0, 10.1, 9.9, 10.0, 1e30, 10000)  # 额量化 InvalidOperation
        + lc_rec(day, 574, 10.0, 10.1, 9.9, 10.0, OVERFLOW, 10000)  # 额超 Numeric(20,4)
        + lc_rec(day, 575, OVERFLOW, OVERFLOW, OVERFLOW, OVERFLOW, 100500.0, 10000)  # 价超列
        + lc_rec(day, 576, 10.0, 10.1, 9.9, 10.0, FITS, 10000)  # 16 位整数：保留
    )
    parsed = parse_lc_bytes("600000.SH", data, "lc1")
    assert [b.ts.minute if b.ts else None for b in parsed.bars] == [31, 36]
    assert dict(parsed.rejected) == {REASON: 4}


def test_r2_day_huge_amount_rejected_per_record() -> None:
    data = (
        good_day(D1)
        + day_rec(D2, 1000, 1020, 980, 1010, 1e30, 100000)
        + day_rec(D2, 1000, 1020, 980, 1010, OVERFLOW, 100000)
        + day_rec(dt.date(2023, 11, 8), 1000, 1020, 980, 1010, FITS, 100000)
    )
    parsed = parse_day_bytes("600000.SH", data)
    assert [b.trade_date for b in parsed.bars] == [D1, dt.date(2023, 11, 8)]
    assert dict(parsed.rejected) == {REASON: 2}


def test_r2_cli_run_survives_huge_record(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write(
        root,
        "sh/lday/sh600000.day",
        good_day(D1) + day_rec(D2, 1000, 1020, 980, 1010, 1e30, 100000),
    )
    audit = tmp_path / "audit"
    audit.mkdir()
    code, out = run_daily(FakeDeps(), root, audit, "--apply")
    assert code == 0
    assert json.loads(out["rejected_records"].replace("'", '"')) == {REASON: 1}
    assert out["inserted"] == "1"


# ---------------------------------------------------------------- ③


def _run(root: Path, audit: Path, writer: object) -> tdx_local.RunReport:
    return run_import(
        root=root,
        audit_dir=audit,
        kind="day",
        start=None,
        until_for=lambda code: dt.date(2023, 11, 9),
        normalize=FakeDeps().normalize,
        security_of=FakeDeps().security_of,
        scope_codes=None,
        existing_for=lambda code, bars: {},
        writer=writer,  # type: ignore[arg-type]
        now=NOW,
        run_id="r3",
        compare_amount=True,
    )


def test_r3_part_removed_and_logged_on_midrun_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = _three_files(tmp_path)
    audit = tmp_path / "audit"
    audit.mkdir()
    calls: list[int] = []

    def writer(bars: Sequence[TdxBar]) -> int:
        calls.append(len(bars))
        if len(calls) == 2:
            assert len(list(audit.glob("tdx-day-reconcile-*.part"))) == 1
            raise RuntimeError("boom")
        return len(bars)

    caplog.set_level(logging.WARNING, logger="app.ingest.tdx_local")
    with pytest.raises(RuntimeError, match="boom"):
        _run(root, audit, writer)
    assert not list(audit.glob("*.part"))
    assert not list(audit.glob("tdx-day-reconcile-*"))
    # 清单照常保留（与 latest_manifest 口径一致，不受影响）。
    assert len(list(audit.glob("tdx-day-manifest-*.txt"))) == 1
    hits = [r for r in caplog.records if r.name == "app.ingest.tdx_local" and ".part" in r.getMessage()]
    assert len(hits) == 1
    assert str(tmp_path) not in hits[0].getMessage()  # 日志只写文件名，不写宿主路径


def test_r3_existing_part_not_owned_is_not_deleted(tmp_path: Path) -> None:
    # 防护：.part 若已存在（不是本次创建的），open("x") 失败时不得把它删掉。
    root = _three_files(tmp_path)
    audit = tmp_path / "audit"
    audit.mkdir()
    stamp = NOW.astimezone(tdx_local.BEIJING).strftime("%Y%m%dT%H%M%S")
    foreign = audit / f"tdx-day-reconcile-{stamp}-r3.jsonl.part"
    foreign.write_text("foreign", encoding="utf-8")
    with pytest.raises(FileExistsError):
        _run(root, audit, lambda bars: len(bars))
    assert foreign.read_text(encoding="utf-8") == "foreign"
