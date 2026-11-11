"""本地数据与时点状态，方案 §2.1、§2.2、§2.4、§2.5。"""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from . import features, sessions, sim, splice
from .errors import DataFormatError

Summary = dict[str, Any]
Grid = dict[str, np.ndarray]
Stock = tuple[str, str, str]
History = dict[tuple[str, str], list[tuple[date, date | None, bool | str]]]


def load_config(path: str | Path) -> Summary:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rows(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _date(value: str | date | None) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def calendar(
    meta_dir: str | Path,
    start: str | date,
    end: str | date,
    *,
    calendar_2026: str | Path,
    index_dates: list[date],
    expected_days: int | None = 1174,
) -> list[date]:
    beginning, ending = _date(start), _date(end)
    if beginning is None or ending is None:
        raise DataFormatError("calendar boundaries must be explicit")
    days, _ = sessions.merged_calendar(
        Path(meta_dir) / "market_calendar.csv",
        Path(calendar_2026),
        beginning,
        ending,
        index_dates,
        expected_days=expected_days,
    )
    return days


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file(task: tuple[Path, str]) -> dict[str, str] | None:
    path, expected = task
    try:
        actual = sha256(path)
        return (
            None
            if actual == expected
            else {"path": str(path), "sha256": actual, "expected": expected}
        )
    except OSError as e:
        return {"path": str(path), "error": str(e)}


def check_manifest(
    hf_dir: str | Path,
    expect: Summary,
    verify_sha: bool = True,
    workers: int = 8,
    *,
    verify_bj: bool = True,
) -> Summary:
    # §2.1：核对文件清单、汇总和实际目录；SHA 流式读取，不加载整份行情。
    root = Path(hf_dir)
    with open(root / "manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    rows = _rows(root / "manifest_files.csv")
    resolved_root = root.resolve()
    for row in rows:
        exchange, symbol = row["exchange"], row["symbol"]
        if (
            exchange not in {"SH", "SZ", "BJ"}
            or len(symbol) != 6
            or not symbol.isascii()
            or not symbol.isdigit()
        ):
            raise DataFormatError("unsafe HF manifest identity")
        candidate = root / exchange / f"{symbol}.parquet"
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(resolved_root):
            raise DataFormatError("HF manifest path leaves verified snapshot")
    actual = {
        "files": len(rows),
        "stocks_by_exchange": dict(Counter(r["exchange"] for r in rows)),
        "bj_files": sum(r["is_bj"] == "True" for r in rows),
        "delisted_stocks": sum(r["universe_status"] == "D" for r in rows),
        "total_rows": sum(int(r["rows"]) for r in rows),
        "first_ts": min((r["first_ts"] for r in rows), default=None),
        "last_ts": max((r["last_ts"] for r in rows), default=None),
    }
    mismatches = []
    for key, value in actual.items():
        target = manifest.get(key)
        equal = value == target
        if key in ("first_ts", "last_ts") and value and target:
            equal = datetime.fromisoformat(value) == datetime.fromisoformat(target)
        if not equal:
            mismatches.append({"field": key, "csv": value, "manifest": target})
    for field, key in (
        ("files", "manifest_files"),
        ("bj_files", "bj_files"),
        ("delisted_stocks", "delisted_all"),
    ):
        if actual[field] != expect[key]:
            mismatches.append({"field": key, "actual": actual[field], "expected": expect[key]})
    listed = {f"{r['exchange']}/{r['symbol']}.parquet" for r in rows}
    disk = {p.relative_to(root).as_posix() for p in root.glob("*/*.parquet")}
    if disk != listed or len(listed) != len(rows):
        mismatches.append(
            {
                "field": "paths",
                "missing": sorted(listed - disk),
                "extra": sorted(disk - listed),
                "duplicate_rows": len(rows) - len(listed),
            }
        )
    if verify_sha:
        tasks = [
            (root / r["exchange"] / (r["symbol"] + ".parquet"), r["sha256"])
            for r in rows
            if verify_bj or r["exchange"] != "BJ"
        ]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            mismatches.extend(x for x in executor.map(_verify_file, tasks) if x is not None)
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "actual": actual,
        "manifest": manifest,
        "sha_verified": verify_sha,
        "sha_scope": ("all" if verify_bj else "SH/SZ") if verify_sha else None,
        "manifest_sha256": sha256(root / "manifest.json"),
        "manifest_files_sha256": sha256(root / "manifest_files.csv"),
    }


def pool(hf_dir: str | Path) -> list[Stock]:
    return [
        (r["exchange"], r["symbol"], r["universe_status"])
        for r in _rows(Path(hf_dir) / "manifest_files.csv")
        if r["is_bj"] == "False"
    ]


def load_stock(path: str | Path, dates: list[date]) -> tuple[Grid, Summary]:
    return grid_from_table(pq.read_table(path), dates)


def grid_from_table(table: pa.Table, dates: list[date]) -> tuple[Grid, Summary]:
    """The existing grid contract, shared by HF and normalized/spliced lc1 rows."""
    if set(splice.SCHEMA.names) - set(table.column_names):
        raise DataFormatError("missing required raw bar columns, including turnover")
    if table.num_rows:
        table = splice.canonical_table(
            table,
            table["exchange"][0].as_py(),
            table["symbol"][0].as_py(),
        )
    else:
        dtype = table.schema.field("timestamp").type
        if not pa.types.is_timestamp(dtype) or dtype.tz != "Asia/Shanghai":
            raise DataFormatError("timestamp must use Asia/Shanghai")
    grid = {k: np.full((len(dates), len(features.SLOT_END)), np.nan) for k in "ohlcva"}
    present = np.zeros((len(dates), len(features.SLOT_END)), dtype=bool)
    # Use Asia/Shanghai minute ordinals. Materializing Python datetime objects
    # per bar would dominate the full 1.39-billion-row preparation pass.
    if any(a >= b for a, b in pairwise(dates)):
        raise DataFormatError("grid trading dates must be strictly increasing")
    calendar_ord = np.array([(d - date(1970, 1, 1)).days for d in dates], dtype=np.int64)
    stamps, source_days = splice._clock(table)
    day_positions = np.searchsorted(calendar_ord, source_days)
    in_calendar = day_positions < len(dates)
    in_calendar[in_calendar] = calendar_ord[day_positions[in_calendar]] == source_days[in_calendar]
    di = day_positions[in_calendar]
    local_minutes = (stamps[in_calendar] + splice.CST_US) % splice.DAY_US // splice.MINUTE_US
    ti = np.searchsorted(splice.VALID_MINUTES, local_minutes)
    ri = np.flatnonzero(in_calendar)
    outside = table.num_rows - len(ri)
    present[di, ti] = True
    for key, col in zip(
        "ohlcva", ("open", "high", "low", "close", "volume", "turnover"), strict=True
    ):
        grid[key][di, ti] = table[col].to_numpy(zero_copy_only=False)[ri]
    quantum = np.array([100 if d >= date(2026, 4, 13) else 0 for d in dates])[:, None]
    bad = present & ~features.bar_ok(*(grid[k] for k in "ohlcva"), volume_quantum=quantum)
    checks = {
        "rows": table.num_rows,
        "outside_dates": outside,
        "missing_bars": int((~present).sum()),
        "missing_stock_days": int((~present).any(axis=1).sum()),
        "bar_ok_failed": int(bad.sum()),
        "by_year": {},
    }
    for year in sorted({d.year for d in dates}):
        ix = [i for i, d in enumerate(dates) if d.year == year]
        b, p = bad[ix], present[ix]
        checks["by_year"][str(year)] = {
            "missing_bars": int((~p).sum()),
            "missing_stock_days": int((~p).any(axis=1).sum()),
            "bar_ok_failed": int(b.sum()),
            "bad_by_slot": {
                "09:31": int(b[:, 0].sum()),
                "15:00": int(b[:, -1].sum()),
                "other": int(b[:, 1:-1].sum()),
            },
        }
    grid["present"] = present
    grid["valid"] = present & ~bad
    return grid, checks


def load_spliced_stock(
    hf: pa.Table,
    single: pa.Table,
    main: pa.Table,
    dates: list[date],
    daily: dict[date, splice.DailyBar],
    *,
    exchange: str,
    symbol: str,
    events: list[sim.Event] | None = None,
    price_limit: float | None = None,
    require_overlap: bool | None = None,
    shared_vipdoc: bool = False,
    single_day_excluded: bool = False,
) -> tuple[Grid, Summary]:
    """Validate first, merge one source per stock-day, then use the shared grid loader."""
    checked = splice.check_splice(
        hf,
        single,
        main,
        daily,
        exchange=exchange,
        symbol=symbol,
        events=events or (),
        price_limit=price_limit,
        require_overlap=require_overlap,
        shared_vipdoc=shared_vipdoc,
        single_day_excluded=single_day_excluded,
    )
    table, source_checks = splice.merge_sources(hf, single, main, exchange=exchange, symbol=symbol)
    grid, checks = grid_from_table(table, dates)
    checks["splice"] = {**checked["splice"], **source_checks}
    return grid, checks


def load_meta(meta_dir: str | Path) -> Summary:
    root = Path(meta_dir)
    coverage = {
        r["symbol"]: {
            "listing_date": _date(r["listing_date"]),
            "delisting_date": _date(r["delisting_date"]),
            # T-A155：无退市整理期股票的尾部核对依据（HF 元数据认定的应有末日）
            "expected_end_date": _date(r.get("expected_end_date")),
        }
        for r in _rows(root / "coverage_by_instrument.csv")
    }
    suspension = {
        (r["symbol"], r["exchange"], _date(r["date"]))
        for r in _rows(root / "no_bar_day_classification.csv")
        if r["classification"] == "confirmed_suspension"
    }
    return {
        "coverage": coverage,
        "confirmed_suspension": suspension,
        "absent_instruments": _rows(root / "absent_instruments.csv"),
    }


def load_status_history(path: str | Path | None, kind: str) -> tuple[History, Summary | None]:
    # §2.3、S8：严格半开区间；未提供历史时不填当前状态。
    if kind not in ("st", "listing"):
        raise ValueError(kind)
    if path is None:
        return {}, None
    rows = _rows(path)
    field = "is_st" if kind == "st" else "status"
    history = defaultdict(list)
    for r in rows:
        start, end = _date(r["valid_from"]), _date(r["valid_to"])
        if start is None or (end is not None and end <= start):
            raise DataFormatError(f"{path}: 非法状态区间 {r}")
        if kind == "st" and r[field].lower() not in ("true", "false"):
            raise DataFormatError(f"{path}: 非法 is_st {r[field]}")
        value = r[field].lower() == "true" if kind == "st" else r[field]
        history[(r["exchange"], r["symbol"])].append((start, end, value))
    gaps = []
    for key, intervals in history.items():
        intervals.sort(key=lambda x: x[0])
        for a, b in pairwise(intervals):
            if a[1] is None or a[1] > b[0]:
                raise DataFormatError(f"{path}: 重叠状态区间 {key}")
            gaps.append((b[0] - a[0]).days)
    flat = [x for intervals in history.values() for x in intervals]
    return dict(history), {
        "start": min((x[0] for x in flat), default=None),
        "end": None if any(x[1] is None for x in flat) else max((x[1] for x in flat), default=None),
        "open_ended": any(x[1] is None for x in flat),
        "rows": len(rows),
        "stocks": len(history),
        "snapshot_gap_n": len(gaps),
        "snapshot_gap_median_days": float(np.median(gaps)) if gaps else None,
        "snapshot_gap_max_days": max(gaps, default=None),
    }


def _status(history: History, stock: Stock, d: date) -> bool | str | None:
    for start, end, value in history.get(tuple(stock[:2]), []):
        if start <= d and (end is None or d < end):
            return value
    return None


def day_kinds(
    stock: Stock,
    dates: list[date],
    meta: Summary,
    st_hist: History,
    listing_hist: History,
    grid: Grid,
    smoke: bool = False,
    *,
    daily_suspensions: set[date] | None = None,
    uncovered_daily_anchors: set[date] | None = None,
) -> tuple[np.ndarray, np.ndarray, Summary]:
    config = meta.get("config") or load_config(Path(__file__).with_name("config.yaml"))
    start = _date(config["segments"]["folds"][0][0])
    listing = meta["coverage"].get(stock[1], {}).get("listing_date")
    new_days = set(
        [d for d in dates if listing and d >= listing][: config["rules"]["new_listing_days"]]
    )
    # §2.3：已在样本起点之前上市的股票不能重新算作新股。
    if listing and listing < dates[0]:
        new_days = set()
    kinds, st = np.full(len(dates), sim.OK, dtype=np.int8), np.zeros(len(dates), dtype=bool)
    reasons = {"first": {}, "all": {}, "stock_days": {}, "ok_by_year": {}}
    present_grid = grid["present"] if "present" in grid else ~np.isnan(grid["o"])
    for i, d in enumerate(dates):
        year = str(d.year)
        for name in reasons:
            reasons[name].setdefault(year, {} if name in ("first", "all") else 0)
        reasons["stock_days"][year] += 1
        listing_status = _status(listing_hist, stock, d)
        st_status = _status(st_hist, stock, d)
        st[i] = st_status is True
        hits = []
        if d < start:
            hits.append("warmup")
        confirmed_daily_suspension = daily_suspensions is not None and d in daily_suspensions
        uncovered = uncovered_daily_anchors is not None and d in uncovered_daily_anchors
        if uncovered:
            hits.append("daily_anchor_outside_coverage")
        if confirmed_daily_suspension:
            hits.append("suspended")
        if d in new_days:
            hits.append("new_listing")
        if stock[2] == "vipdoc_only" and listing is None:
            hits.append("listing_date_unknown")
        if listing_status == "delisting_period":
            hits.append("delisting_period")
        if listing_status is None and not smoke:
            hits.append("listing_status_unknown")
        if st_status is True:
            hits.append("st")
        if st_status is None and not smoke:
            hits.append("st_unknown")
        # Whole-day absence is diagnostic. It must not mask an already-known
        # exclusion and change the disposition of a deferred leg at the open.
        if (
            not uncovered
            and not confirmed_daily_suspension
            and (
                not present_grid[i].any()
                or not np.any(grid["v"][i] > 0)
                or (stock[1], stock[0], d) in meta["confirmed_suspension"]
            )
        ):
            hits.append("suspended")
        for reason in hits:
            reasons["all"][year][reason] = reasons["all"][year].get(reason, 0) + 1
        if hits:
            first = hits[0]
            reasons["first"][year][first] = reasons["first"][year].get(first, 0) + 1
            kinds[i] = {"warmup": sim.WARMUP, "suspended": sim.SUSPENDED}.get(first, sim.EXCLUDED)
        else:
            reasons["ok_by_year"][year] += 1
    return kinds, st, reasons


def _verified_archive(root_or_archive: str | Path, name: str, expected_sha256: str | None) -> Path:
    root = Path(root_or_archive)
    archive = root if root.suffix.lower() == ".zip" else root / f"{name}.zip"
    if expected_sha256 is None:
        evidence = json.loads(
            (archive.parent / "T-B136-tdx-manifest.json").read_text(encoding="utf-8")
        )
        expected_sha256 = evidence[name]["sha256"]
    if sha256(archive) != expected_sha256:
        raise DataFormatError(f"{name}: verified archive SHA changed")
    return archive


def load_gbbq(
    tdx_dir: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[tuple[str, str], list[sim.Event]]:
    archive = _verified_archive(tdx_dir, "gbbq", expected_sha256)
    with zipfile.ZipFile(archive) as z:
        content = z.read("gbbq")
    if len(content) < 4:
        raise DataFormatError("§2.4 gbbq header truncated")
    (count,) = struct.unpack_from("<I", content)
    if count == 0:
        return {}
    # §2.4：仅借用公开格式表常量，逐块解码；代码字段按 GBK。
    from pytdx.reader.gbbq_reader import GbbqReader

    keys = struct.unpack(
        "<" + "I" * (len(bytes.fromhex(GbbqReader.hexdump_keys)) // 4),
        bytes.fromhex(GbbqReader.hexdump_keys),
    )
    if len(content) < 4 + count * 29:
        raise DataFormatError("§2.4 gbbq 文件截断")
    result = defaultdict(list)
    offset = 4
    mask = 0xFFFFFFFF
    for _ in range(count):
        clear = bytearray()
        for _ in range(3):
            left, right = struct.unpack_from("<II", content, offset)
            left ^= keys[0x44 // 4]
            for j in range(16, 0, -1):
                f = (
                    keys[0x448 // 4 + ((left >> 16) & 255)] + keys[0x48 // 4 + (left >> 24)]
                ) & mask
                f ^= keys[0x848 // 4 + ((left >> 8) & 255)]
                f = (f + keys[0xC48 // 4 + (left & 255)]) & mask
                left, right = (right ^ f ^ keys[j]) & mask, left
            clear.extend(struct.pack("<II", right ^ keys[0], left))
            offset += 8
        clear.extend(content[offset : offset + 5])
        offset += 5
        market, code, exdate, category, cash, pp, s, r = struct.unpack("<B7sIBffff", clear)
        symbol = code.rstrip(b"\0").decode("gbk")
        if category == 1 and market in (0, 1):
            d = datetime.strptime(str(exdate), "%Y%m%d").date()
            result[("SH" if market == 1 else "SZ", symbol)].append(
                sim.Event(d, cash / 10, pp, s / 10, r / 10)
            )
    return {key: sorted(events, key=lambda e: e.ex_date) for key, events in result.items()}


class DailyArchive:
    """One read-only ZIP index for a sequential full-pool splice pass."""

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.archive = archive
        self.names: dict[str, str] = {}
        for name in archive.namelist():
            key = "/".join(part for part in name.replace("\\", "/").split("/") if part)
            if key.endswith(".day"):
                if key in self.names:
                    raise DataFormatError(f"duplicate .day archive member: {key}")
                self.names[key] = name

    def records(
        self, exchange: str, symbol: str, *, required: bool = False
    ) -> dict[date, splice.DailyBar]:
        target = f"{exchange.lower()}/lday/{exchange.lower()}{symbol}.day"
        name = self.names.get(target)
        if name is None:
            if required:
                raise DataFormatError(f"§2.6 D5 缺失 {target}")
            return {}
        content = self.archive.read(name)
        if len(content) % 32:
            raise DataFormatError(f"{target}: .day 记录截断")
        result = {}
        for raw_day, opening, _, _, close, _, volume, _ in struct.iter_unpack("<IIIIIfII", content):
            try:
                day = date(raw_day // 10000, raw_day // 100 % 100, raw_day % 100)
            except ValueError as exc:
                raise DataFormatError(f"{target}: invalid .day date") from exc
            if day in result:
                raise DataFormatError(f"{target}: duplicate .day date")
            result[day] = splice.DailyBar(opening / 100, close / 100, volume)
        return result


def _day_records(
    tdx_zip: str | Path,
    exchange: str,
    symbol: str,
    required: bool = False,
) -> dict[date, tuple[float, int]]:
    with zipfile.ZipFile(tdx_zip) as archive:
        records = DailyArchive(archive).records(exchange, symbol, required=required)
    return {day: (bar.close, bar.volume) for day, bar in records.items()}


def load_index_close(
    tdx_dir: str | Path,
    symbol: str = "sh000300",
    *,
    expected_sha256: str | None = None,
) -> dict[date, float]:
    archive = _verified_archive(tdx_dir, "hsjday", expected_sha256)
    return {
        d: row[0] for d, row in _day_records(archive, symbol[:2], symbol[2:], required=True).items()
    }


def day_crosscheck(
    tdx_zip: str | Path,
    exchange: str,
    symbol: str,
    grid: Grid,
    dates: list[date],
) -> dict[str, int]:
    daily = _day_records(tdx_zip, exchange, symbol)
    result = {"days": 0, "close_eq": 0, "vol_eq": 0}
    for i, d in enumerate(dates):
        present = np.flatnonzero(~np.isnan(grid["c"][i]))
        if present.size and d in daily:
            result["days"] += 1
            result["close_eq"] += round(float(grid["c"][i, present[-1]]), 2) == round(
                daily[d][0], 2
            )
            result["vol_eq"] += float(np.nansum(grid["v"][i])) == daily[d][1]
    return result
