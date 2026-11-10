"""本地数据与时点状态，方案 §2.1、§2.2、§2.4、§2.5。"""

from __future__ import annotations

import csv
import hashlib
import json
import struct
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from . import features, sim


class DataFormatError(ValueError):
    """§2.2：格式不符必须停止。"""


def load_config(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _date(value):
    return date.fromisoformat(str(value)[:10]) if value else None


def calendar(meta_dir, start, end) -> list[date]:
    start, end = _date(start), _date(end)
    return sorted({_date(r["date"]) for r in _rows(Path(meta_dir) / "market_calendar.csv")
                   if r["is_trading_day"] == "True" and start <= _date(r["date"]) <= end})


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file(task):
    path, expected = task
    try:
        actual = sha256(path)
        return None if actual == expected else {"path": str(path), "sha256": actual,
                                                "expected": expected}
    except OSError as e:
        return {"path": str(path), "error": str(e)}


def check_manifest(hf_dir, expect, verify_sha=True, workers=8) -> dict:
    # §2.1：核对文件清单、汇总和实际目录；SHA 流式读取，不加载整份行情。
    root = Path(hf_dir)
    with open(root / "manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    rows = _rows(root / "manifest_files.csv")
    actual = {"files": len(rows), "stocks_by_exchange": dict(Counter(r["exchange"] for r in rows)),
              "bj_files": sum(r["is_bj"] == "True" for r in rows),
              "delisted_stocks": sum(r["universe_status"] == "D" for r in rows),
              "total_rows": sum(int(r["rows"]) for r in rows),
              "first_ts": min((r["first_ts"] for r in rows), default=None),
              "last_ts": max((r["last_ts"] for r in rows), default=None)}
    mismatches = []
    for key, value in actual.items():
        target = manifest.get(key)
        equal = value == target
        if key in ("first_ts", "last_ts") and value and target:
            equal = datetime.fromisoformat(value) == datetime.fromisoformat(target)
        if not equal:
            mismatches.append({"field": key, "csv": value, "manifest": target})
    for field, key in (("files", "manifest_files"), ("bj_files", "bj_files"),
                       ("delisted_stocks", "delisted_all")):
        if actual[field] != expect[key]:
            mismatches.append({"field": key, "actual": actual[field], "expected": expect[key]})
    listed = {f"{r['exchange']}/{r['symbol']}.parquet" for r in rows}
    disk = {str(p.relative_to(root)) for p in root.glob("*/*.parquet")}
    if disk != listed or len(listed) != len(rows):
        mismatches.append({"field": "paths", "missing": sorted(listed - disk),
                           "extra": sorted(disk - listed), "duplicate_rows": len(rows) - len(listed)})
    if verify_sha:
        tasks = [(root / r["exchange"] / (r["symbol"] + ".parquet"), r["sha256"]) for r in rows]
        with ProcessPoolExecutor(max_workers=workers) as executor:
            mismatches.extend(x for x in executor.map(_verify_file, tasks) if x is not None)
    return {"ok": not mismatches, "mismatches": mismatches, "actual": actual,
            "manifest": manifest, "sha_verified": verify_sha,
            "manifest_sha256": sha256(root / "manifest.json"),
            "manifest_files_sha256": sha256(root / "manifest_files.csv")}


def pool(hf_dir) -> list[tuple[str, str, str]]:
    return [(r["exchange"], r["symbol"], r["universe_status"])
            for r in _rows(Path(hf_dir) / "manifest_files.csv") if r["is_bj"] == "False"]


def load_stock(path, dates):
    required = ["symbol", "exchange", "timestamp", "open", "high", "low", "close",
                "volume", "turnover", "is_bj"]
    schema = pq.read_schema(path)
    missing = sorted(set(required) - set(schema.names))
    if missing:
        raise DataFormatError(f"{path}: 缺字段 {missing}")
    dtype = schema.field("timestamp").type
    if not pa.types.is_timestamp(dtype) or dtype.tz != "Asia/Shanghai":
        raise DataFormatError(f"{path}: timestamp 时区必须为 Asia/Shanghai，实际 {dtype}")
    table = pq.read_table(path, columns=required)
    grid = {k: np.full((len(dates), len(features.SLOT_END)), np.nan) for k in "ohlcva"}
    present = np.zeros((len(dates), len(features.SLOT_END)), dtype=bool)
    day_index = {d: i for i, d in enumerate(dates)}
    slot_index = {s: i for i, s in enumerate(features.SLOT_END)}
    di, ti, ri = [], [], []
    outside = 0
    for row, stamp in enumerate(table["timestamp"].to_pylist()):
        if stamp is None or stamp.strftime("%H:%M") not in slot_index or stamp.second or stamp.microsecond:
            raise DataFormatError(f"{path}: 非法时刻 {stamp}")
        if stamp.date() not in day_index:
            outside += 1
            continue
        d, t = day_index[stamp.date()], slot_index[stamp.strftime("%H:%M")]
        if present[d, t]:
            raise DataFormatError(f"{path}: 重复 timestamp {stamp}")
        present[d, t] = True
        di.append(d)
        ti.append(t)
        ri.append(row)
    for key, col in zip("ohlcva", ("open", "high", "low", "close", "volume", "turnover"), strict=True):
        grid[key][di, ti] = table[col].to_numpy(zero_copy_only=False)[ri]
    bad = present & ~features.bar_ok(*(grid[k] for k in "ohlcva"))
    checks = {"rows": table.num_rows, "outside_dates": outside,
              "missing_bars": int((~present).sum()),
              "missing_stock_days": int((~present).any(axis=1).sum()),
              "bar_ok_failed": int(bad.sum()), "by_year": {}}
    for year in sorted({d.year for d in dates}):
        ix = [i for i, d in enumerate(dates) if d.year == year]
        b, p = bad[ix], present[ix]
        checks["by_year"][str(year)] = {
            "missing_bars": int((~p).sum()), "missing_stock_days": int((~p).any(axis=1).sum()),
            "bar_ok_failed": int(b.sum()), "bad_by_slot": {
                "09:31": int(b[:, 0].sum()), "15:00": int(b[:, -1].sum()),
                "other": int(b[:, 1:-1].sum())}}
    grid["present"] = present
    return grid, checks


def load_meta(meta_dir):
    root = Path(meta_dir)
    coverage = {r["symbol"]: {"listing_date": _date(r["listing_date"]),
                              "delisting_date": _date(r["delisting_date"])}
                for r in _rows(root / "coverage_by_instrument.csv")}
    suspension = {(r["symbol"], r["exchange"], _date(r["date"]))
                  for r in _rows(root / "no_bar_day_classification.csv")
                  if r["classification"] == "confirmed_suspension"}
    return {"coverage": coverage, "confirmed_suspension": suspension,
            "absent_instruments": _rows(root / "absent_instruments.csv")}


def load_status_history(path, kind):
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
        for a, b in zip(intervals, intervals[1:]):
            if a[1] is None or a[1] > b[0]:
                raise DataFormatError(f"{path}: 重叠状态区间 {key}")
            gaps.append((b[0] - a[0]).days)
    flat = [x for intervals in history.values() for x in intervals]
    return dict(history), {
        "start": min((x[0] for x in flat), default=None),
        "end": None if any(x[1] is None for x in flat) else max((x[1] for x in flat), default=None),
        "open_ended": any(x[1] is None for x in flat), "rows": len(rows),
        "stocks": len(history), "snapshot_gap_n": len(gaps),
        "snapshot_gap_median_days": float(np.median(gaps)) if gaps else None,
        "snapshot_gap_max_days": max(gaps, default=None)}


def _status(history, stock, d):
    for start, end, value in history.get(tuple(stock[:2]), []):
        if start <= d and (end is None or d < end):
            return value
    return None


def day_kinds(stock, dates, meta, st_hist, listing_hist, grid, smoke=False):
    config = meta.get("config") or load_config(Path(__file__).with_name("config.yaml"))
    start = _date(config["segments"]["folds"][0][0])
    listing = meta["coverage"].get(stock[1], {}).get("listing_date")
    new_days = set([d for d in dates if listing and d >= listing][:config["rules"]["new_listing_days"]])
    # §2.3：已在样本起点之前上市的股票不能重新算作新股。
    if listing and listing < dates[0]:
        new_days = set()
    kinds, st = np.full(len(dates), sim.OK, dtype=np.int8), np.zeros(len(dates), dtype=bool)
    reasons = {"first": {}, "all": {}, "stock_days": {}, "ok_by_year": {}}
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
        present = grid.get("present", ~np.isnan(grid["o"]))[i]
        if not present.any() or not np.any(grid["v"][i] > 0) or (stock[1], stock[0], d) in meta["confirmed_suspension"]:
            hits.append("suspended")
        if d in new_days:
            hits.append("new_listing")
        if listing_status == "delisting_period":
            hits.append("delisting_period")
        if listing_status is None and not smoke:
            hits.append("listing_status_unknown")
        if st_status is True:
            hits.append("st")
        if st_status is None and not smoke:
            hits.append("st_unknown")
        for reason in hits:
            reasons["all"][year][reason] = reasons["all"][year].get(reason, 0) + 1
        if hits:
            first = hits[0]
            reasons["first"][year][first] = reasons["first"][year].get(first, 0) + 1
            kinds[i] = {"warmup": sim.WARMUP, "suspended": sim.SUSPENDED}.get(first, sim.EXCLUDED)
        else:
            reasons["ok_by_year"][year] += 1
    return kinds, st, reasons


def load_gbbq(tdx_dir):
    # §2.4：仅借用公开格式表常量，逐块解码；代码字段按 GBK。
    from pytdx.reader.gbbq_reader import GbbqReader

    keys = struct.unpack("<" + "I" * (len(bytes.fromhex(GbbqReader.hexdump_keys)) // 4),
                         bytes.fromhex(GbbqReader.hexdump_keys))
    with zipfile.ZipFile(Path(tdx_dir) / "gbbq_20261110.zip") as z:
        content = z.read("gbbq")
    count, = struct.unpack_from("<I", content)
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
                f = (keys[0x448 // 4 + ((left >> 16) & 255)] + keys[0x48 // 4 + (left >> 24)]) & mask
                f ^= keys[0x848 // 4 + ((left >> 8) & 255)]
                f = (f + keys[0xC48 // 4 + (left & 255)]) & mask
                left, right = (right ^ f ^ keys[j]) & mask, left
            clear.extend(struct.pack("<II", right ^ keys[0], left))
            offset += 8
        clear.extend(content[offset:offset + 5])
        offset += 5
        market, code, exdate, category, cash, pp, s, r = struct.unpack("<B7sIBffff", clear)
        symbol = code.rstrip(b"\0").decode("gbk")
        if category == 1 and market in (0, 1):
            d = datetime.strptime(str(exdate), "%Y%m%d").date()
            result[("SH" if market == 1 else "SZ", symbol)].append(sim.Event(d, cash / 10, pp, s / 10, r / 10))
    return {key: sorted(events, key=lambda e: e.ex_date) for key, events in result.items()}


def _day_records(tdx_zip, exchange, symbol, required=False):
    # §2.1、§2.6 D5：包内使用反斜线，兼容重复的路径分隔符。
    target = f"{exchange.lower()}/lday/{exchange.lower()}{symbol}.day"
    with zipfile.ZipFile(tdx_zip) as z:
        name = next((n for n in z.namelist() if "/".join(n.replace("\\", "/").split()) == target), None)
        if name is None:
            name = next((n for n in z.namelist() if "/".join(p for p in n.replace("\\", "/").split("/") if p) == target), None)
        if name is None:
            if required:
                raise DataFormatError(f"§2.6 D5 缺失 {target}")
            return {}
        content = z.read(name)
    if len(content) % 32:
        raise DataFormatError(f"{target}: .day 记录截断")
    return {datetime.strptime(str(r[0]), "%Y%m%d").date(): (r[4] / 100, r[6])
            for r in struct.iter_unpack("<IIIIIfII", content)}


def load_index_close(tdx_dir, symbol="sh000300"):
    return {d: row[0] for d, row in _day_records(Path(tdx_dir) / "hsjday_20261110.zip",
                                                symbol[:2], symbol[2:], required=True).items()}


def day_crosscheck(tdx_zip, exchange, symbol, grid, dates):
    daily = _day_records(tdx_zip, exchange, symbol)
    result = {"days": 0, "close_eq": 0, "vol_eq": 0}
    for i, d in enumerate(dates):
        present = np.flatnonzero(~np.isnan(grid["c"][i]))
        if present.size and d in daily:
            result["days"] += 1
            result["close_eq"] += round(float(grid["c"][i, present[-1]]), 2) == round(daily[d][0], 2)
            result["vol_eq"] += float(np.nansum(grid["v"][i])) == daily[d][1]
    return result
