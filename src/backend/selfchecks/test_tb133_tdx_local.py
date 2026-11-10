# ruff: noqa: S101, ANN401, E501, PT018, C408
"""T-B133：通达信 .day / .lc1 / .lc5 解析、清单、过滤与重叠只对账（不连库）。

契约只读参照 ``git show 362ad41:docs/contracts/daily-bars-tdx.md`` §3、§5、§8 与
``git show 362ad41:docs/contracts/intraday-bars.md`` §1.2–§1.3、§5.1 M2。

- 合成样本：在 tmp_path 里按公开格式构造的虚构二进制记录，只做边界用例。
- 真实样本：只读，经环境变量 ``TB133_TDX_SAMPLES``（目录结构 sh|sz|bj/lday|minline|fzline）指向，
  不复制、不入库、不提交；目录不存在时 skip 并写明原因。同级 ``tdx.sha256`` 存在时先核对。
不连库、不出网、不调用麦蕊。
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import os
import struct
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.api.v1.trades import normalize_code
from app.cli import tdx_import
from app.ingest import tdx_local
from app.ingest.tdx_local import (
    BEIJING,
    ExistingBar,
    Kind,
    RunReport,
    TdxBar,
    decode_lc_date,
    encode_lc_date,
    parse_day_bytes,
    parse_lc_bytes,
)

APP_DIR = Path(__file__).resolve().parents[1] / "app"
NOW = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)  # 北京时间 20:00，今天 2026-11-10
SAMPLES_ENV = "TB133_TDX_SAMPLES"


# ---------------------------------------------------------------- 合成样本工具（虚构）


def day_rec(day: dt.date, o: int, h: int, low: int, c: int, amount: float, volume: int) -> bytes:
    return struct.pack("<IIIIIfII", int(day.strftime("%Y%m%d")), o, h, low, c, amount, volume, 0)


def lc_rec(
    day: dt.date, minute: int, o: float, h: float, low: float, c: float, amount: float, volume: int
) -> bytes:
    return struct.pack("<HHfffffII", encode_lc_date(day), minute, o, h, low, c, amount, volume, 0)


def good_day(day: dt.date, base: int = 1000) -> bytes:
    # 价格 ÷100 为元；额 = 均价 × 量（股），满足单位自检。
    volume = 100_000
    return day_rec(day, base, base + 20, base - 20, base + 10, (base + 5) / 100 * volume, volume)


def make_root(tmp: Path, kind: Kind = "day") -> Path:
    root = tmp / "root"
    for market in ("sh", "sz", "bj"):
        (root / market / tdx_local.KIND_DIR[kind]).mkdir(parents=True, exist_ok=True)
    return root


def write(root: Path, rel: str, data: bytes) -> Path:
    path = root / rel
    path.write_bytes(data)
    return path


def open_days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [
        start + dt.timedelta(n)
        for n in range((end - start).days + 1)
        if (start + dt.timedelta(n)).weekday() < 5
    ]


SECURITIES = {
    "600000.SH": ("stock", "listed"),
    "000001.SZ": ("stock", "listed"),
    "920000.BJ": ("stock", "listed"),
    "000001.SH": ("index", "listed"),
    "510300.SH": ("etf", "listed"),
    "880001.SH": ("index", "listed"),  # 板块（880 开头）在主数据里不是 stock
    "110001.SH": ("bond", "listed"),
    "600001.SH": ("stock", "delisted"),
}


class FakeDeps:
    """纯内存 TdxDeps：周一至周五开市；写入只进内存。"""

    def __init__(
        self,
        *,
        recommended: dt.date = dt.date(2023, 11, 9),
        owned: frozenset[str] | None = None,
        existing: Mapping[tuple[str, str], Mapping[object, ExistingBar]] | None = None,
        first_mairui: Mapping[str, dt.date] | None = None,
        securities: Mapping[str, tuple[str, str | None]] | None = None,
    ) -> None:
        self.recommended = recommended
        self.owned = owned if owned is not None else frozenset(SECURITIES)
        self._existing = dict(existing or {})
        self.first_mairui = dict(first_mairui or {})
        self.securities = dict(securities if securities is not None else SECURITIES)
        self.written: list[TdxBar] = []
        self.runs: list[dict[str, object]] = []
        self.normalized: list[str] = []

    def is_open(self, day: dt.date) -> bool | None:
        return day.weekday() < 5

    def previous_open(self, day: dt.date) -> dt.date | None:
        day -= dt.timedelta(1)
        while day.weekday() >= 5:
            day -= dt.timedelta(1)
        return day

    def recommended_daily_until(self, now_bj: dt.datetime) -> dt.date | None:
        return self.recommended

    def first_mairui_minute_day(self, code: str) -> dt.date | None:
        return self.first_mairui.get(code)

    def normalize(self, raw: str) -> str:
        self.normalized.append(raw)
        # 前缀形式（SH600000）不查库，直接走 trades.normalize_code 的规则。
        return normalize_code(None, raw)  # type: ignore[arg-type]

    def security_of(self, code: str) -> tuple[str, str | None] | None:
        return self.securities.get(code)

    def owned_codes(self, now_bj: dt.datetime) -> frozenset[str]:
        return self.owned

    def existing(
        self, kind: Kind, code: str, bars: Sequence[TdxBar]
    ) -> Mapping[object, ExistingBar]:
        return self._existing.get((kind, code), {})

    def write(self, kind: Kind, bars: Sequence[TdxBar], fetched_at: dt.datetime) -> int:
        keys = {(b.code, b.ts or b.trade_date) for b in self.written}
        fresh = [b for b in bars if (b.code, b.ts or b.trade_date) not in keys]
        self.written.extend(fresh)
        return len(fresh)

    def record_run(self, report: RunReport, run_date: dt.date) -> None:
        self.runs.append(report.stats())


def run_daily(
    deps: FakeDeps,
    root: Path,
    audit: Path,
    *extra: str,
    until: str = "2023-11-09",
    run_id: str = "r1",
    now: dt.datetime = NOW,
) -> tuple[int, dict[str, str]]:
    return _capture(
        tdx_import.daily_main,
        deps,
        ["--root", str(root), "--audit-dir", str(audit), "--until", until, *extra],
        run_id,
        now,
    )


def run_intraday(
    deps: FakeDeps, root: Path, audit: Path, kind: str, *extra: str, run_id: str = "r1"
) -> tuple[int, dict[str, str]]:
    return _capture(
        tdx_import.intraday_main,
        deps,
        ["--kind", kind, "--root", str(root), "--audit-dir", str(audit), *extra],
        run_id,
        NOW,
    )


_LAST_OUT: list[str] = []


def _capture(
    fn: Any, deps: FakeDeps, argv: list[str], run_id: str, now: dt.datetime
) -> tuple[int, dict[str, str]]:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(argv, now=now, deps=deps, run_id=run_id)
    _LAST_OUT[:] = buf.getvalue().splitlines()
    out: dict[str, str] = {}
    for line in _LAST_OUT:
        key, sep, value = line.partition("=")
        if sep:
            out[key] = value
        else:
            out[line] = ""
    return code, out


def _audit(tmp: Path) -> Path:
    audit = tmp / "audit"
    audit.mkdir()
    return audit


# ---------------------------------------------------------------- 记录解析（合成）


def test_tdx_parse_record_layout() -> None:
    day = dt.date(2024, 3, 1)
    parsed = parse_day_bytes("000001.SZ", day_rec(day, 1234, 1250, 1200, 1240, 123456.75, 10_000))
    assert not parsed.rejected
    (bar,) = parsed.bars
    assert (bar.trade_date, bar.ts) == (day, None)
    assert (bar.open, bar.high, bar.low, bar.close) == (
        Decimal("12.34"),
        Decimal("12.5"),
        Decimal("12"),
        Decimal("12.4"),
    )
    assert bar.volume == Decimal(10_000)
    assert bar.amount == Decimal("123456.7500")


def test_lc_parse_record_layout() -> None:
    day = dt.date(2026, 4, 24)
    data = lc_rec(day, 571, 12.34, 12.5, 12.25, 12.4, 1234567.0, 100_100)  # 虚构数值
    for kind in ("lc1", "lc5"):
        parsed = parse_lc_bytes("600000.SH", data, kind)  # type: ignore[arg-type]
        (bar,) = parsed.bars
        assert bar.trade_date == day
        assert bar.ts == dt.datetime(2026, 4, 24, 9, 31, tzinfo=BEIJING)
        assert (bar.open, bar.high, bar.low, bar.close) == (
            Decimal("12.34"),
            Decimal("12.5"),
            Decimal("12.25"),
            Decimal("12.4"),
        )
        assert bar.volume == Decimal(100_100)
        assert bar.amount == Decimal("1234567.0000")


def test_lc_date_encoding_boundaries() -> None:
    assert decode_lc_date(101) == dt.date(2004, 1, 1)
    assert decode_lc_date(46166) == dt.date(2026, 11, 10)
    assert decode_lc_date(43909) == dt.date(2025, 9, 1)
    for day in (dt.date(2004, 1, 1), dt.date(2024, 2, 29), dt.date(2035, 12, 31)):
        assert decode_lc_date(encode_lc_date(day)) == day
    # 月 13、日 0、分钟 0 / 超过 1440 都拒绝并计数。
    bad = struct.pack("<HHfffffII", 22 * 2048 + 1301, 571, 1, 1, 1, 1, 1, 1, 0)
    bad += struct.pack("<HHfffffII", 22 * 2048 + 1100, 571, 1, 1, 1, 1, 1, 1, 0)
    bad += lc_rec(dt.date(2026, 1, 5), 0, 1, 1, 1, 1, 1, 1)
    bad += lc_rec(dt.date(2026, 1, 5), 1441, 1, 1, 1, 1, 1, 1)
    parsed = parse_lc_bytes("600000.SH", bad, "lc1")
    assert parsed.bars == []
    assert parsed.rejected == Counter({"invalid_date": 2, "invalid_minute": 2})


def test_day_rejects_invalid_records_and_truncated_file() -> None:
    day = dt.date(2024, 3, 1)
    data = (
        day_rec(day, 1000, 1010, 990, 1000, 1.0, 1)
        + struct.pack("<IIIIIfII", 20241301, 1000, 1010, 990, 1000, 1.0, 1, 0)
        + day_rec(day, 0, 1010, 990, 1000, 1.0, 1)
        + day_rec(day, 1000, 990, 1010, 1000, 1.0, 1)
        + day_rec(day, 1020, 1010, 990, 1000, 1.0, 1)
    )
    parsed = parse_day_bytes("000001.SZ", data)
    assert len(parsed.bars) == 1
    assert parsed.rejected == Counter({"invalid_date": 1, "zero_price": 1, "high_low_conflict": 2})
    truncated = parse_day_bytes("000001.SZ", data[:-1])
    assert truncated.bars == [] and truncated.rejected == Counter({"truncated_file": 1})


# ---------------------------------------------------------------- CLI 行为（合成）


def test_tdx_cli_generates_manifest(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    days = open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 13))
    a = write(root, "sh/lday/sh600000.day", b"".join(good_day(d) for d in days))
    b = write(root, "sz/lday/sz000001.day", b"".join(good_day(d, 2000) for d in days))
    write(root, "sh/lday/sh000001.day", b"".join(good_day(d) for d in days))
    audit = _audit(tmp_path)
    deps = FakeDeps()
    code, out = run_daily(deps, root, audit)
    assert code == 0 and "dry-run" in out
    assert (
        out["files"] == "2" and out["would_insert"] == str(2 * len(days)) and out["inserted"] == "0"
    )
    assert deps.written == [] and deps.runs == []  # dry-run：库零写入，也不写 pipeline_runs
    lines = (audit / out["manifest"]).read_text().splitlines(keepends=True)
    assert len(lines) == 3
    expect = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}\t{p.stat().st_size}\t{p.relative_to(root).as_posix()}\n"
        for p in (a, b)
    ]
    assert lines[:2] == expect
    own = hashlib.sha256("".join(lines[:2]).encode()).hexdigest()
    assert lines[2] == f"files=2\tmanifest_sha256={own}\n"
    assert out["manifest_sha256"] == own
    assert out["manifest"].startswith("tdx-day-manifest-20261110T200000-r1")


def test_tdx_rerun_compares_manifest(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    days = open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 6))
    for rel in ("sh/lday/sh600000.day", "sz/lday/sz000001.day"):
        write(root, rel, b"".join(good_day(d) for d in days))
    audit = _audit(tmp_path)
    deps = FakeDeps()
    assert run_daily(deps, root, audit, run_id="a1")[0] == 0
    with (root / "sh/lday/sh600000.day").open("ab") as fh:
        fh.write(good_day(dt.date(2023, 10, 9)))
    (root / "sz/lday/sz000001.day").unlink()
    write(root, "bj/lday/bj920000.day", b"".join(good_day(d) for d in days))
    code, out = run_daily(
        deps, root, audit, "--apply", run_id="b2", now=NOW + dt.timedelta(seconds=1)
    )
    assert code == 0
    assert out["rerun"] == str({"added": 1, "removed": 1, "changed": 1})
    assert out["previous_manifest"].startswith("tdx-day-manifest-20261110T200000-a1")
    assert deps.runs and deps.runs[-1]["rerun"] == {"added": 1, "removed": 1, "changed": 1}
    assert deps.runs[-1]["status"] == "ok"


def test_tdx_file_changed_during_import_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path)
    days = open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 6))
    write(root, "sh/lday/sh600000.day", b"".join(good_day(d) for d in days))
    write(root, "sz/lday/sz000001.day", b"".join(good_day(d) for d in days))
    real = tdx_local.file_sha256
    calls: Counter[str] = Counter()

    def flaky(path: Path) -> str:
        calls[path.name] += 1
        if path.name == "sh600000.day" and calls[path.name] > 1:
            return "0" * 64  # 解析后再算一次哈希与清单不同
        return real(path)

    monkeypatch.setattr(tdx_local, "file_sha256", flaky)
    deps = FakeDeps()
    code, out = run_daily(deps, root, _audit(tmp_path), "--apply")
    assert code == 0 and out["status"] == "partial"
    assert out["rejected_files"] == str({"changed_during_import": 1})
    assert {b.code for b in deps.written} == {"000001.SZ"} and len(deps.written) == len(days)
    assert "tdx_file_changed:600000.SH" in out["issues"]


def test_tdx_root_missing_lday_rejected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    (root / "bj" / "lday").rmdir()
    audit = _audit(tmp_path)
    deps = FakeDeps()
    code, _ = run_daily(deps, root, audit, "--apply")
    assert code != 0 and _LAST_OUT[-1] == "refused: root_missing:bj/lday"
    assert deps.written == [] and deps.runs == [] and list(audit.iterdir()) == []


def test_tdx_root_dir_names_case_insensitive(tmp_path: Path) -> None:
    root = tmp_path / "root"
    for market in ("SH", "Sz", "bj"):
        (root / market / "LDAY").mkdir(parents=True)
    write(root, "SH/LDAY/sh600000.day", good_day(dt.date(2023, 10, 2)))
    code, out = run_daily(FakeDeps(), root, _audit(tmp_path))
    assert code == 0 and out["files"] == "1"


def test_tdx_audit_dir_must_be_writable_and_outside_root(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    inside = root / "audit"
    inside.mkdir()
    assert (
        run_daily(FakeDeps(), root, inside)[0] != 0
        and _LAST_OUT[-1] == "refused: audit_dir_inside_root"
    )
    assert (
        run_daily(FakeDeps(), root, root)[0] != 0
        and _LAST_OUT[-1] == "refused: audit_dir_inside_root"
    )
    assert (
        run_daily(FakeDeps(), root, tmp_path / "missing")[0] != 0
        and _LAST_OUT[-1] == "refused: audit_dir_not_writable"
    )
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("以 root 运行时 chmod 无法模拟不可写目录")
        assert (
            run_daily(FakeDeps(), root, locked)[0] != 0
            and _LAST_OUT[-1] == "refused: audit_dir_not_writable"
        )
    finally:
        locked.chmod(0o755)


def test_tdx_rows_after_until_not_imported(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    days = open_days(dt.date(2023, 11, 6), dt.date(2023, 11, 17))
    write(root, "sh/lday/sh600000.day", b"".join(good_day(d) for d in days))
    deps = FakeDeps()
    code, out = run_daily(
        deps, root, _audit(tmp_path), "--apply", "--from", "2023-11-07", until="2023-11-09"
    )
    assert code == 0
    assert max(b.trade_date for b in deps.written) == dt.date(2023, 11, 9)
    assert min(b.trade_date for b in deps.written) == dt.date(2023, 11, 7)
    assert (out["before_from"], out["after_until"], out["inserted"]) == ("1", "6", "3")


def test_tdx_until_after_mairui_window_start_rejected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    code, out = run_daily(
        FakeDeps(recommended=dt.date(2023, 11, 9)), root, _audit(tmp_path), until="2023-11-10"
    )
    assert code != 0 and out["recommended_until"] == "2023-11-09"
    assert _LAST_OUT[-1] == "refused: until_after_mairui_window_start"


def test_tdx_import_until_must_be_past_open_day(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    deps = FakeDeps(recommended=dt.date(2030, 1, 1))
    for until in ("2026-11-10", "2026-11-11", "2026-11-08", "2026/11/09"):
        code, _ = run_daily(deps, root, _fresh(tmp_path, until), until=until)
        assert code != 0, until
    assert deps.written == []
    code, out = run_daily(deps, root, _fresh(tmp_path, "ok"), until="2026-11-09")
    assert code == 0 and "dry-run" in out and deps.written == []


def _fresh(tmp: Path, name: str) -> Path:
    path = tmp / ("audit_" + name.replace("/", "_"))
    path.mkdir()
    return path


def test_tdx_import_filters_stock_listed_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_root(tmp_path)
    days = open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 6))
    payload = b"".join(good_day(d) for d in days)
    names = {
        "sh/lday/sh600000.day": "stock",
        "sh/lday/sh510300.day": "etf",
        "sh/lday/sh000001.day": "index",
        "sh/lday/sh880001.day": "board",
        "sh/lday/sh110001.day": "bond",
        "sh/lday/sh600001.day": "delisted",
        "sz/lday/sz999999.day": "not_in_master",
        "sz/lday/szABCDEF.day": "bad_name",
    }
    for rel in names:
        write(root, rel, payload)
    opened: list[str] = []
    real_hash = tdx_local.file_sha256
    real_read = Path.read_bytes

    def hash_spy(path: Path) -> str:
        opened.append(path.name)
        return real_hash(path)

    def read_spy(self: Path) -> bytes:
        opened.append(self.name)
        return real_read(self)

    monkeypatch.setattr(tdx_local, "file_sha256", hash_spy)
    monkeypatch.setattr(Path, "read_bytes", read_spy)
    deps = FakeDeps()
    code, out = run_daily(deps, root, _audit(tmp_path), "--apply")
    assert code == 0
    assert set(opened) == {"sh600000.day"}  # 被过滤的文件不打开、不算哈希
    assert out["files"] == "1"
    assert out["skipped"] == str({"name_invalid": 1, "non_a_share": 5, "not_listed": 1})
    assert {b.code for b in deps.written} == {"600000.SH"}
    manifest = (tmp_path / "audit" / out["manifest"]).read_text().splitlines()
    assert len(manifest) == 2 and manifest[0].endswith("\tsh/lday/sh600000.day")


def test_tdx_import_owned_scope_only(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write(root, "sh/lday/sh600000.day", good_day(dt.date(2023, 10, 2)))
    write(root, "sz/lday/sz000001.day", good_day(dt.date(2023, 10, 2)))
    deps = FakeDeps(owned=frozenset({"000001.SZ"}))
    code, out = run_daily(deps, root, _audit(tmp_path), "--apply")
    assert code == 0 and out["skipped"] == str({"out_of_scope": 1})
    assert {b.code for b in deps.written} == {"000001.SZ"}
    assert run_daily(deps, root, _fresh(tmp_path, "m"), "--scope", "market")[0] != 0
    assert _LAST_OUT[-1] == "refused: market_scope_disabled"


def test_tdx_import_do_nothing_on_existing(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    days = open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 6))
    write(root, "sh/lday/sh600000.day", b"".join(good_day(d) for d in days))
    same = ExistingBar(
        "mairui",
        Decimal("10.00"),
        Decimal("10.20"),
        Decimal("9.80"),
        Decimal("10.10"),
        Decimal(100000),
        Decimal("1005000.0000"),
    )
    differ = ExistingBar(
        "mairui",
        Decimal("10.00"),
        Decimal("10.20"),
        Decimal("9.80"),
        Decimal("10.11"),
        Decimal(100000),
        Decimal("1005300.0000"),
    )
    deps = FakeDeps(existing={("day", "600000.SH"): {days[0]: same, days[1]: differ}})
    audit = _audit(tmp_path)
    code, out = run_daily(deps, root, audit, "--apply")
    assert code == 0
    assert (out["overlap_rows"], out["conflicts"], out["inserted"]) == (
        "2",
        "1",
        str(len(days) - 2),
    )
    assert {b.trade_date for b in deps.written}.isdisjoint({days[0], days[1]})
    rows = [
        __import__("json").loads(x)
        for x in (audit / out["reconcile_report"]).read_text().splitlines()
    ]
    assert [(r["field"], r["kind"]) for r in rows[:-1]] == [
        ("close", "mismatch"),
        ("amount", "mismatch"),
    ]
    assert (
        rows[-1]["summary"] is True
        and rows[-1]["overlap_keys"] == 2
        and rows[-1]["mismatch_keys"] == 1
    )


def test_crosscheck_tolerance_amount_float32() -> None:
    bar = TdxBar(
        "600000.SH",
        dt.date(2024, 1, 2),
        None,
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal("1000000200"),
    )
    base = dict(
        source="mairui",
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        volume=Decimal(1),
    )
    assert (
        tdx_local.reconcile(
            bar, ExistingBar(amount=Decimal("1000000000"), **base), compare_amount=True
        )
        == []
    )
    bar300 = TdxBar(
        "600000.SH",
        dt.date(2024, 1, 2),
        None,
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal("1000000300"),
    )
    (item,) = tdx_local.reconcile(
        bar300, ExistingBar(amount=Decimal("1000000000"), **base), compare_amount=True
    )
    assert item["field"] == "amount" and item["kind"] == "mismatch"


def test_tdx_import_no_suspended_inference(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    days = [
        d
        for d in open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 6))
        if d != dt.date(2023, 10, 4)
    ]
    write(root, "sh/lday/sh600000.day", b"".join(good_day(d) for d in days))
    deps = FakeDeps()
    assert run_daily(deps, root, _audit(tmp_path), "--apply")[0] == 0
    assert dt.date(2023, 10, 4) not in {b.trade_date for b in deps.written}
    assert len(deps.written) == 4


def test_tdx_import_unit_selfcheck_rejects_file(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    days = open_days(dt.date(2023, 10, 2), dt.date(2023, 10, 13))
    # 成交量按手写入：额 ÷ 量 ≈ 100 × 价格，落不进 [low, high]。
    lots = b"".join(day_rec(d, 1000, 1020, 980, 1010, 10.05 * 100_000, 1000) for d in days)
    write(root, "sh/lday/sh600000.day", lots)
    write(root, "sz/lday/sz000001.day", b"".join(good_day(d) for d in days))
    deps = FakeDeps()
    code, out = run_daily(deps, root, _audit(tmp_path), "--apply")
    assert code == 0 and out["status"] == "partial"
    assert "tdx_unit_suspect:600000.SH" in out["issues"]
    assert {b.code for b in deps.written} == {"000001.SZ"}


def test_unit_selfcheck_threshold_five_percent() -> None:
    def bars(bad: int, total: int) -> list[TdxBar]:
        out = []
        for n in range(total):
            amount = Decimal(1000) if n < bad else Decimal(10)
            out.append(
                TdxBar(
                    "x",
                    dt.date(2024, 1, 1),
                    None,
                    Decimal(10),
                    Decimal(10),
                    Decimal(10),
                    Decimal(10),
                    Decimal(1),
                    amount,
                )
            )
        return out

    assert not tdx_local.unit_suspect(bars(5, 100))  # 5% 不超
    assert tdx_local.unit_suspect(bars(6, 100))  # 6% 超过 5%
    assert not tdx_local.unit_suspect(bars(0, 10))


def test_tdx_import_ignores_minute_files(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write(root, "sh/lday/sh600000.day", good_day(dt.date(2023, 10, 2)))
    write(
        root, "sh/lday/sh600000.lc1", lc_rec(dt.date(2023, 10, 2), 571, 10, 10, 10, 10, 1000, 100)
    )
    write(
        root, "sh/lday/sh600000.lc5", lc_rec(dt.date(2023, 10, 2), 575, 10, 10, 10, 10, 1000, 100)
    )
    deps = FakeDeps()
    code, out = run_daily(deps, root, _audit(tmp_path), "--apply")
    assert code == 0 and out["files"] == "1" and out["skipped"] == str({"not_target_file": 2})
    assert len(deps.written) == 1


def test_tdx_import_no_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for module in ("ingest/tdx_local.py", "cli/tdx_import.py"):
        tree = ast.parse((APP_DIR / module).read_text())
        names = {
            alias.name if isinstance(node, ast.Import) else f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not [
            n for n in names if "egress" in n or "transport" in n or "httpx" in n or "requests" in n
        ], module
    from app.ingest import egress

    calls: list[object] = []
    monkeypatch.setattr(egress, "mairui_get", lambda *a, **k: calls.append(a))
    root = make_root(tmp_path)
    write(root, "sh/lday/sh600000.day", good_day(dt.date(2023, 10, 2)))
    assert run_daily(FakeDeps(), root, _audit(tmp_path), "--apply")[0] == 0
    assert calls == []


def test_lc_import_a_share_only_and_manifest(tmp_path: Path) -> None:
    root = make_root(tmp_path, "lc1")
    rec = lc_rec(dt.date(2026, 4, 24), 571, 12.34, 12.5, 12.25, 12.4, 12.4 * 1000, 1000)
    for rel in (
        "sh/minline/sh600000.lc1",
        "sh/minline/sh000001.lc1",
        "sh/minline/sh510300.lc1",
        "sh/minline/sh880001.lc1",
        "sh/minline/sh600000.lc5",
    ):
        write(root, rel, rec)
    audit = _audit(tmp_path)
    deps = FakeDeps()
    code, out = run_intraday(deps, root, audit, "lc1")
    assert code == 0 and out["files"] == "1"
    assert out["skipped"] == str({"non_a_share": 3, "not_target_file": 1})
    assert out["manifest"].startswith("tdx-lc1-manifest-")
    write(root, "sz/minline/sz000001.lc1", rec)
    code, out = run_intraday(deps, root, audit, "lc1", run_id="r2")
    assert out["rerun"] == str({"added": 1, "removed": 0, "changed": 0})


def test_lc_import_until_before_first_mairui_minute(tmp_path: Path) -> None:
    root = make_root(tmp_path, "lc1")
    days = open_days(dt.date(2026, 11, 2), dt.date(2026, 11, 10))
    data = b"".join(lc_rec(d, 571, 9.5, 9.5, 9.5, 9.5, 9.5 * 100, 100) for d in days)
    write(root, "sh/minline/sh600000.lc1", data)
    write(root, "sz/minline/sz000001.lc1", data)
    # 600000.SH 已有 mairui 分钟线起于 11-05（周四）→ 只导到 11-04；000001.SZ 没有 → 前一开市日 11-09。
    deps = FakeDeps(first_mairui={"600000.SH": dt.date(2026, 11, 5)})
    code, out = run_intraday(deps, root, _audit(tmp_path), "lc1", "--apply")
    assert code == 0
    by_code = defaultdict(list)
    for bar in deps.written:
        by_code[bar.code].append(bar.trade_date)
    assert max(by_code["600000.SH"]) == dt.date(2026, 11, 4)
    assert max(by_code["000001.SZ"]) == dt.date(2026, 11, 9)
    assert out["after_until"] == str(4 + 1)


def test_lc_import_rerun_idempotent_and_readonly_root(tmp_path: Path) -> None:
    root = make_root(tmp_path, "lc5")
    path = write(
        root,
        "sh/fzline/sh600000.lc5",
        lc_rec(dt.date(2026, 11, 2), 575, 9.5, 9.5, 9.5, 9.5, 950, 100),
    )
    before = (path.stat().st_mtime_ns, path.read_bytes())
    for p in sorted(root.rglob("*"), reverse=True):
        p.chmod(0o555 if p.is_dir() else 0o444)
    root.chmod(0o555)
    deps = FakeDeps()
    try:
        assert (
            run_intraday(deps, root, _fresh(tmp_path, "a"), "lc5", "--apply")[1]["inserted"] == "1"
        )
        assert (
            run_intraday(deps, root, _fresh(tmp_path, "b"), "lc5", "--apply", run_id="r2")[1][
                "inserted"
            ]
            == "0"
        )
        assert (path.stat().st_mtime_ns, path.read_bytes()) == before
        assert sorted(p.name for p in root.rglob("*")) == [
            "bj",
            "fzline",
            "fzline",
            "fzline",
            "sh",
            "sh600000.lc5",
            "sz",
        ]
    finally:
        for p in [root, *root.rglob("*")]:
            p.chmod(0o755 if p.is_dir() else 0o644)


# ---------------------------------------------------------------- 真实样本（只读，经环境变量）


def _samples() -> Path:
    raw = os.environ.get(SAMPLES_ENV, "")
    if not raw:
        pytest.skip(f"未设置 {SAMPLES_ENV}：真实通达信样本目录未提供（样本只读，不入仓库）")
    path = Path(raw)
    if not path.is_dir():
        pytest.skip(f"{SAMPLES_ENV}={raw} 不存在：真实通达信样本未到位")
    return path


EXPECTED_SAMPLES = {
    "sh/lday/sh600000.day",
    "sz/lday/sz000001.day",
    "bj/lday/bj920000.day",
    "sh/lday/sh000001.day",
    "sh/minline/sh600000.lc1",
    "sz/minline/sz000001.lc1",
    "sh/fzline/sh600000.lc5",
    "sz/fzline/sz000001.lc5",
}
REAL_SECURITIES = {
    "600000.SH": ("stock", "listed"),
    "000001.SZ": ("stock", "listed"),
    "920000.BJ": ("stock", "listed"),
    "000001.SH": ("index", "listed"),
}


def _checksums(root: Path) -> dict[str, str]:
    sums = root.parent / (root.name + ".sha256")
    if not sums.is_file():
        return {}
    out = {}
    for line in sums.read_text().splitlines():
        digest, _, rel = line.partition("  ")
        out[rel.removeprefix(root.name + "/")] = digest
    return out


def test_real_samples_present_and_checksums() -> None:
    root = _samples()
    files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert files == EXPECTED_SAMPLES
    sums = _checksums(root)
    if sums:
        assert set(sums) == EXPECTED_SAMPLES
        for rel, digest in sums.items():
            assert tdx_local.file_sha256(root / rel) == digest, rel


def test_real_day_dry_run_filters_index_counts_and_sha(tmp_path: Path) -> None:
    root = _samples()
    deps = FakeDeps(securities=REAL_SECURITIES, owned=frozenset(REAL_SECURITIES))
    audit = _audit(tmp_path)
    code, out = run_daily(deps, root, audit, until="2023-11-09")
    assert code == 0 and "dry-run" in out and deps.written == []
    assert out["files"] == "3"
    assert out["skipped"] == str({"non_a_share": 1})  # sh000001 为指数，被过滤
    assert (
        out["parsed_rows"] == str(3 * 1277)
        and out["rejected_records"] == "{}"
        and out["rejected_files"] == "{}"
    )
    manifest = (audit / out["manifest"]).read_text().splitlines()
    rels = [line.split("\t")[2] for line in manifest[:-1]]
    assert rels == ["bj/lday/bj920000.day", "sh/lday/sh600000.day", "sz/lday/sz000001.day"]
    sums = _checksums(root)
    for line in manifest[:-1]:
        digest, size, rel = line.split("\t")
        assert size == "40864"
        if sums:
            assert digest == sums[rel]
    assert int(out["would_insert"]) + int(out["after_until"]) == 3 * 1277


def test_real_day_overlap_reconcile_only(tmp_path: Path) -> None:
    root = _samples()
    parsed = parse_day_bytes("600000.SH", (root / "sh/lday/sh600000.day").read_bytes())
    window = [b for b in parsed.bars if b.trade_date <= dt.date(2023, 11, 9)][-4:]
    existing = {
        b.trade_date: ExistingBar("mairui", b.open, b.high, b.low, b.close, b.volume, b.amount)
        for b in window[:3]
    }
    last = window[3]
    existing[last.trade_date] = ExistingBar(
        "mairui",
        last.open,
        last.high,
        last.low,
        last.close + Decimal("0.01"),
        last.volume,
        last.amount,
    )
    deps = FakeDeps(
        securities=REAL_SECURITIES,
        owned=frozenset({"600000.SH"}),
        existing={("day", "600000.SH"): existing},
    )
    audit = _audit(tmp_path)
    code, out = run_daily(deps, root, audit, "--apply", until="2023-11-09")
    assert code == 0
    assert (out["overlap_rows"], out["conflicts"]) == ("4", "1")
    assert {b.trade_date for b in deps.written}.isdisjoint(existing)  # 重叠期只对账、不写入
    rows = (audit / out["reconcile_report"]).read_text().splitlines()
    assert len(rows) == 2 and '"field": "close"' in rows[0]


def _lc(root: Path, rel: str, kind: str) -> dict[dt.date, list[TdxBar]]:
    parsed = parse_lc_bytes(rel[-12:-4], (root / rel).read_bytes(), kind)  # type: ignore[arg-type]
    assert not parsed.rejected
    out: dict[dt.date, list[TdxBar]] = defaultdict(list)
    for bar in parsed.bars:
        out[bar.trade_date].append(bar)
    return out


@pytest.mark.parametrize(
    ("day_rel", "lc_rel", "kind", "rows", "days", "per_day", "first", "last"),
    [
        (
            "sh/lday/sh600000.day",
            "sh/minline/sh600000.lc1",
            "lc1",
            31920,
            133,
            240,
            dt.time(9, 31),
            dt.time(15, 0),
        ),
        (
            "sz/lday/sz000001.day",
            "sz/minline/sz000001.lc1",
            "lc1",
            31920,
            133,
            240,
            dt.time(9, 31),
            dt.time(15, 0),
        ),
        (
            "sh/lday/sh600000.day",
            "sh/fzline/sh600000.lc5",
            "lc5",
            13776,
            287,
            48,
            dt.time(9, 35),
            dt.time(15, 0),
        ),
        (
            "sz/lday/sz000001.day",
            "sz/fzline/sz000001.lc5",
            "lc5",
            13776,
            287,
            48,
            dt.time(9, 35),
            dt.time(15, 0),
        ),
    ],
)
def test_real_lc_cross_check_against_day(
    day_rel: str,
    lc_rel: str,
    kind: str,
    rows: int,
    days: int,
    per_day: int,
    first: dt.time,
    last: dt.time,
) -> None:
    """四项分钟参数的实测核对：日期编码、bar 结束时刻、价格不缩放、成交量单位为股。"""
    root = _samples()
    daily = {b.trade_date: b for b in parse_day_bytes("x", (root / day_rel).read_bytes()).bars}
    minutes = _lc(root, lc_rel, kind)
    assert sum(len(v) for v in minutes.values()) == rows and len(minutes) == days
    for day, bars in minutes.items():
        assert day in daily  # 解码出的每个日期都在 .day 里有同日记录
        assert len(bars) == per_day
        assert bars[0].ts is not None and bars[-1].ts is not None
        assert (
            bars[0].ts.timetz().replace(tzinfo=None),
            bars[-1].ts.timetz().replace(tzinfo=None),
        ) == (first, last)
        d = daily[day]
        assert bars[-1].close == d.close and bars[0].open == d.open  # 价格为元，不缩放
        assert max(b.high for b in bars) == d.high and min(b.low for b in bars) == d.low
        total = sum(b.volume for b in bars)
        assert abs(total - d.volume) < 100  # 股；按手则相差约 100 倍
        assert all(b.volume % 100 == 0 for b in bars)


def _lc_view(samples: Path, tmp: Path) -> Path:
    """样本只有 sh、sz 的分钟目录；--root 要求 sh/sz/bj 三个目录都在（缺任一即拒绝），
    所以在 tmp 里建只含符号链接的视图并补一个空的 bj 目录。不复制样本内容。"""
    view = tmp / "lc_view"
    for market in ("sh", "sz", "bj"):
        for sub in ("minline", "fzline"):
            (view / market / sub).mkdir(parents=True)
            src = samples / market / sub
            if src.is_dir():
                for f in src.iterdir():
                    (view / market / sub / f.name).symlink_to(f)
    return view


def test_real_lc_root_without_bj_minline_refused(tmp_path: Path) -> None:
    root = _samples()
    code, _ = run_intraday(FakeDeps(securities=REAL_SECURITIES), root, _audit(tmp_path), "lc1")
    assert code != 0 and _LAST_OUT[-1] == "refused: root_missing:bj/minline"


def test_real_lc_dry_run_counts_and_index_filter(tmp_path: Path) -> None:
    root = _lc_view(_samples(), tmp_path)
    deps = FakeDeps(securities=REAL_SECURITIES, owned=frozenset(REAL_SECURITIES))
    for kind, rows in (("lc1", 31920), ("lc5", 13776)):
        code, out = run_intraday(deps, root, _fresh(tmp_path, kind), kind)
        assert code == 0 and "dry-run" in out and deps.written == []
        assert out["files"] == "2" and out["parsed_rows"] == str(2 * rows)
        assert out["rejected_files"] == "{}" and out["rejected_records"] == "{}"
