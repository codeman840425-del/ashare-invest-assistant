# ruff: noqa: S101, E501, PT018
"""T-B135：T-A147 必改 M1–M3（不连库部分）。

- M1：``run_import`` 逐文件写入、逐文件写对账报告，不跨文件攒行。
- M2：float32 的 NaN / Inf 按记录拒绝并计数（``non_finite``），不让整次运行异常退出。
- M3：``recommended_until`` 纯函数：3 年窗口边界与 2 月 29 日（日历可注入）。

依据：reports/T-A147.md §五 M1–M3；``git show 1fe3ab9:docs/contracts/daily-bars-tdx.md`` §3.3–§3.4。
合成样本均为虚构数据；不连库、不出网、不调用麦蕊。
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from app.cli import tdx_import
from app.ingest import tdx_local
from app.ingest.tdx_local import (
    BEIJING,
    ExistingBar,
    TdxBar,
    parse_day_bytes,
    parse_lc_bytes,
    run_import,
)
from selfchecks.test_tb133_tdx_local import (
    FakeDeps,
    day_rec,
    good_day,
    lc_rec,
    make_root,
    open_days,
    run_daily,
    write,
)

NOW = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)
D1 = dt.date(2023, 11, 6)
D2 = dt.date(2023, 11, 7)


def _three_files(tmp: Path) -> Path:
    root = make_root(tmp)
    write(root, "sh/lday/sh600000.day", good_day(D1) + good_day(D2))
    write(root, "sz/lday/sz000001.day", good_day(D1))
    write(root, "bj/lday/bj920000.day", good_day(D1) + good_day(D2))
    return root


def _run(
    root: Path,
    audit: Path,
    writer: Callable[[Sequence[TdxBar]], int] | None,
    existing: Callable[[str, Sequence[TdxBar]], Mapping[object, ExistingBar]] | None = None,
) -> tdx_local.RunReport:
    return run_import(
        root=root,
        audit_dir=audit,
        kind="day",
        start=None,
        until_for=lambda code: dt.date(2023, 11, 9),
        normalize=FakeDeps().normalize,
        security_of=FakeDeps().security_of,
        scope_codes=None,
        existing_for=existing or (lambda code, bars: {}),
        writer=writer,
        now=NOW,
        run_id="m1",
        compare_amount=True,
    )


# ---------------------------------------------------------------- M1


def test_m1_writer_called_once_per_file_with_only_that_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _three_files(tmp_path)
    audit = tmp_path / "audit"
    audit.mkdir()
    events: list[tuple[str, object]] = []
    real_read = Path.read_bytes

    def spy_read(self: Path) -> bytes:
        if self.suffix == ".day":
            events.append(("read", self.name))
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", spy_read)

    def writer(bars: Sequence[TdxBar]) -> int:
        events.append(("write", tuple(sorted({b.code for b in bars}))))
        return len(bars)

    report = _run(root, audit, writer)
    assert [e for e in events if e[0] == "write"] == [
        ("write", ("920000.BJ",)),
        ("write", ("600000.SH",)),
        ("write", ("000001.SZ",)),
    ]
    # 每个文件读完就写，下一个文件读之前已写完：读写交替。
    assert [e[0] for e in events] == ["read", "write"] * 3
    assert report.would_insert == 5 and report.inserted == 5


def test_m1_reconcile_lines_flushed_before_next_file(tmp_path: Path) -> None:
    root = _three_files(tmp_path)
    audit = tmp_path / "audit"
    audit.mkdir()
    # 第一个文件（bj920000）D1 已有不同收盘价的行：产生一条差异。
    existing_bj = {
        D1: ExistingBar(
            "mairui",
            Decimal("10"),
            Decimal("10.2"),
            Decimal("9.8"),
            Decimal("9.99"),
            Decimal(100000),
            Decimal("1005000"),
        )
    }
    seen: list[list[str]] = []

    def existing(code: str, bars: Sequence[TdxBar]) -> dict[object, ExistingBar]:
        return existing_bj if code == "920000.BJ" else {}

    def writer(bars: Sequence[TdxBar]) -> int:
        if bars[0].code == "600000.SH":  # 第二个文件写入时，第一个文件的差异已落盘
            parts = sorted(audit.glob("tdx-day-reconcile-*"))
            assert len(parts) == 1
            seen.append(parts[0].read_text(encoding="utf-8").splitlines())
        return len(bars)

    report = _run(root, audit, writer, existing)
    assert len(seen) == 1 and len(seen[0]) == 1
    assert json.loads(seen[0][0])["code"] == "920000.BJ"
    final = (audit / report.reconcile_name).read_text(encoding="utf-8").splitlines()
    assert json.loads(final[0]) == json.loads(seen[0][0])
    summary = json.loads(final[-1])
    assert (
        summary["summary"] is True
        and summary["mismatch_keys"] == 1
        and summary["overlap_keys"] == 1
    )
    assert report.conflicts == 1 and report.inserted == 4
    assert not list(audit.glob("*.part"))


def test_m1_dry_run_writes_nothing_and_same_counts(tmp_path: Path) -> None:
    root = _three_files(tmp_path)
    audit = tmp_path / "audit"
    audit.mkdir()
    report = _run(root, audit, None)
    assert report.would_insert == 5 and report.inserted == 0
    assert (audit / report.reconcile_name).is_file()


# ---------------------------------------------------------------- M2


def test_m2_lc_nan_and_inf_rejected_per_record() -> None:
    day = dt.date(2023, 11, 6)
    good = lc_rec(day, 571, 10.0, 10.1, 9.9, 10.0, 100500.0, 10000)
    data = (
        good
        + lc_rec(day, 572, math.nan, 10.1, 9.9, 10.0, 100500.0, 10000)
        + lc_rec(day, 573, 10.0, math.inf, 9.9, 10.0, 100500.0, 10000)
        + lc_rec(day, 574, 10.0, 10.1, 9.9, 10.0, -math.inf, 10000)
        + lc_rec(day, 575, 10.0, 10.1, 9.9, 10.0, math.nan, 10000)
    )
    parsed = parse_lc_bytes("600000.SH", data, "lc1")
    assert len(parsed.bars) == 1
    assert dict(parsed.rejected) == {"non_finite": 4}


def test_m2_day_nan_amount_rejected_per_record() -> None:
    data = (
        good_day(D1)
        + day_rec(D2, 1000, 1020, 980, 1010, math.nan, 100000)
        + day_rec(D2, 1000, 1020, 980, 1010, math.inf, 100000)
    )
    parsed = parse_day_bytes("600000.SH", data)
    assert [b.trade_date for b in parsed.bars] == [D1]
    assert dict(parsed.rejected) == {"non_finite": 2}


def test_m2_cli_run_survives_nan_record(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write(
        root,
        "sh/lday/sh600000.day",
        good_day(D1) + day_rec(D2, 1000, 1020, 980, 1010, math.nan, 100000),
    )
    audit = tmp_path / "audit"
    audit.mkdir()
    code, out = run_daily(FakeDeps(), root, audit, "--apply")
    assert code == 0
    assert json.loads(out["rejected_records"].replace("'", '"')) == {"non_finite": 1}
    assert out["inserted"] == "1"


# ---------------------------------------------------------------- M3


def _weekdays(
    start: dt.date, end: dt.date, closed: frozenset[dt.date] = frozenset()
) -> list[dt.date]:
    return [d for d in open_days(start, end) if d not in closed]


def test_m3_start_is_open_day_is_d() -> None:
    # 2026-11-10 → 窗口起点 2023-11-10（开市，不在 (start, td] 内）；第一个开市日 11-13，D=11-10。
    cal = _weekdays(dt.date(2023, 10, 1), dt.date(2026, 11, 10))
    assert tdx_import.recommended_until(dt.date(2026, 11, 10), cal) == dt.date(2023, 11, 10)


def test_m3_start_closed_takes_previous_open() -> None:
    cal = _weekdays(dt.date(2023, 10, 1), dt.date(2026, 11, 10), frozenset({dt.date(2023, 11, 10)}))
    assert tdx_import.recommended_until(dt.date(2026, 11, 10), cal) == dt.date(2023, 11, 9)
    # 起点落在周六：2026-11-11 → 2023-11-11；第一个开市日 11-13，D=11-10。
    cal2 = _weekdays(dt.date(2023, 10, 1), dt.date(2026, 11, 11))
    assert tdx_import.recommended_until(dt.date(2026, 11, 11), cal2) == dt.date(2023, 11, 10)


def test_m3_feb29_trade_date_falls_back_to_feb28() -> None:
    # 2028-02-29 → 起点 2025-02-28（与 backfill_window_days 的 day=28 回退一致），开市 → D=2025-02-28。
    cal = _weekdays(dt.date(2025, 1, 1), dt.date(2028, 2, 29))
    assert tdx_import.recommended_until(dt.date(2028, 2, 29), cal) == dt.date(2025, 2, 28)


def test_m3_d_can_be_feb29() -> None:
    # 2027-03-01 → 起点 2024-03-01（设为休市）；第一个开市日 2024-03-04，D=2024-02-29。
    cal = _weekdays(dt.date(2024, 1, 1), dt.date(2027, 3, 1), frozenset({dt.date(2024, 3, 1)}))
    assert tdx_import.recommended_until(dt.date(2027, 3, 1), cal) == dt.date(2024, 2, 29)


def test_m3_no_open_day_unknown() -> None:
    td = dt.date(2026, 11, 10)
    # 窗口内没有开市日，或起点之前没有开市日：未知（None，调用方拒绝）。
    assert tdx_import.recommended_until(td, [dt.date(2023, 11, 9)]) is None
    assert tdx_import.recommended_until(td, _weekdays(dt.date(2023, 11, 11), td)) is None
    # 晚于 trade_date 的开市日不参与。
    assert tdx_import.recommended_until(td, [dt.date(2023, 11, 9), dt.date(2026, 11, 11)]) is None


def test_m3_years_matches_contract() -> None:
    # daily-bars-tdx §3.4：backfill_window_days(conn, trade_date, 3)。
    assert tdx_import.MAIRUI_BACKFILL_YEARS == 3
