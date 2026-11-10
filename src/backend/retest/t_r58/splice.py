"""T-R58d §2.7: read-only lc1 decoding and fail-closed source validation.

The offline namespace remains ``retest.t_r58``. No application settings, database,
credentials or network client is imported. Decoding returns (Arrow table, counts);
``check_splice`` returns {"splice": ...}, consumed by the grid loader and summary.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from . import features, rules
from .errors import DataFormatError
from .sim import Event

Summary = dict[str, Any]
HF_END = date(2026, 8, 6)
SINGLE_DAY = date(2026, 8, 7)
MAIN_START = date(2026, 8, 10)
OVERLAP_START = date(2026, 4, 24)
OVERLAP_CODES = {"600000", "000001", "688001", "300001"}
PREFIXES = {
    "SH": ("600", "601", "603", "605", "688", "689"),
    "SZ": ("000", "001", "002", "003", "300", "301", "302"),
}
SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("exchange", pa.string()),
        ("timestamp", pa.timestamp("us", tz="Asia/Shanghai")),
        *[(column, pa.float64()) for column in ("open", "high", "low", "close")],
        ("volume", pa.float64()),
        ("turnover", pa.float64()),
        ("is_bj", pa.bool_()),
    ]
)
MINUTE_US = 60_000_000
DAY_US = MINUTE_US * 1440
CST_US = MINUTE_US * 480
VALID_MINUTES = np.array([int(s[:2]) * 60 + int(s[3:]) for s in features.SLOT_END])
LC1_DTYPE = np.dtype(
    [
        ("day", "<u2"),
        ("minute", "<u2"),
        *[(column, "<f4") for column in ("open", "high", "low", "close", "turnover")],
        ("volume", "<u4"),
        ("reserved", "<u4"),
    ]
)


@dataclass(frozen=True)
class DailyBar:
    open: float
    close: float
    volume: int


class SpliceError(DataFormatError):
    """Retain counts for a failed validation; never allow exclusion and continuation."""

    def __init__(self, symbol: str, result: Summary) -> None:
        super().__init__(f"{symbol}: splice validation failed: {result['failures']}")
        self.summary = {"splice": result}


def selected_symbol(exchange: str, symbol: str) -> bool:
    return (
        exchange in PREFIXES
        and len(symbol) == 6
        and symbol.isascii()
        and symbol.isdigit()
        and symbol.startswith(PREFIXES[exchange])
    )


def selected_lc1(root: Path) -> dict[tuple[str, str], Path]:
    """Only sh/sz minline names are inspected; no bj, lc5, index, ETF or B share reads."""
    result: dict[tuple[str, str], Path] = {}
    for exchange in PREFIXES:
        directory = root / exchange.lower() / "minline"
        for path in sorted(directory.glob("*.lc1")):
            symbol = path.stem.removeprefix(exchange.lower())
            if not selected_symbol(exchange, symbol):
                continue
            key = exchange, symbol
            if key in result:
                raise DataFormatError(f"duplicate lc1 file identity: {key}")
            result[key] = path
    return result


def empty_table() -> pa.Table:
    return pa.Table.from_pylist([], schema=SCHEMA)


def _clock(table: pa.Table, *, allow_1300: bool = False) -> tuple[np.ndarray, np.ndarray]:
    timestamp = table["timestamp"]
    dtype = timestamp.type
    if not pa.types.is_timestamp(dtype) or dtype.tz != "Asia/Shanghai" or timestamp.null_count:
        raise DataFormatError("timestamp must be non-null and use Asia/Shanghai")
    stamps = timestamp.cast(SCHEMA.field("timestamp").type).cast(pa.int64()).to_numpy()
    local = stamps + CST_US
    minutes = local % DAY_US // MINUTE_US
    allowed = np.r_[VALID_MINUTES, 780] if allow_1300 else VALID_MINUTES
    if np.any(local % MINUTE_US) or not np.isin(minutes, allowed).all():
        raise DataFormatError("illegal bar-end label; validation precedes date filtering")
    if len(np.unique(stamps)) != len(stamps):
        raise DataFormatError("duplicate timestamp")
    return stamps, local // DAY_US


def canonical_table(table: pa.Table, exchange: str, symbol: str) -> pa.Table:
    if not selected_symbol(exchange, symbol):
        raise DataFormatError(f"non-SH/SZ-A identity refused: {exchange}/{symbol}")
    if set(SCHEMA.names) - set(table.column_names):
        raise DataFormatError("missing required raw bar columns, including turnover")
    _clock(table)
    if table.num_rows:
        if pc.unique(table["symbol"]).to_pylist() != [symbol]:
            raise DataFormatError("bar symbol differs from file identity")
        if pc.unique(table["exchange"]).to_pylist() != [exchange]:
            raise DataFormatError("bar exchange differs from file identity")
        if table["is_bj"].null_count or pc.any(table["is_bj"]).as_py():
            raise DataFormatError("BJ row cannot enter the SH/SZ research pool")
    return table.select(SCHEMA.names).cast(SCHEMA).sort_by([("timestamp", "ascending")])


def relabel_1300(table: pa.Table) -> tuple[pa.Table, dict[str, int]]:
    """Repair only a complete 239+13:00 day; otherwise discard the unconfirmed bar.

    Other illegal labels, duplicates and simultaneous 11:30/13:00 always stop.
    All labels are inspected before a caller filters the main-package start date.
    """
    stamps, days = _clock(table, allow_1300=True)
    stamps = stamps.copy()
    minutes = (stamps + CST_US) % DAY_US // MINUTE_US
    keep = np.ones(table.num_rows, dtype=bool)
    repaired = dropped = 0
    wanted = set(VALID_MINUTES) - {690}
    for day in np.unique(days[minutes == 780]):
        indexes = np.flatnonzero(days == day)
        labels = set(minutes[indexes])
        if 690 in labels:
            raise DataFormatError("11:30 and 13:00 coexist on one stock-day")
        anomaly = indexes[minutes[indexes] == 780]
        if len(indexes) == 240 and labels - {780} == wanted:
            stamps[anomaly] -= 90 * MINUTE_US
            repaired += 1
        else:
            keep[anomaly] = False
            dropped += len(anomaly)
    column = table.schema.get_field_index("timestamp")
    result = table.set_column(
        column, "timestamp", pa.array(stamps, type=SCHEMA.field("timestamp").type)
    )
    result = result.take(pa.array(np.flatnonzero(keep))).sort_by([("timestamp", "ascending")])
    _clock(result)
    return result, {"relabelled_1300": repaired, "dropped_unconfirmed_1300": dropped}


def decode_lc1(path: Path, exchange: str, symbol: str) -> tuple[pa.Table, Summary]:
    """Decode <HHfffffII, float32 yuan, uint32 shares; never modify the source."""
    exchange = exchange.upper()
    if not selected_symbol(exchange, symbol):
        raise DataFormatError(f"non-SH/SZ-A lc1 refused before reading: {exchange}/{symbol}")
    path = Path(path)
    if path.suffix.lower() != ".lc1":
        raise DataFormatError("only lc1 minute files are accepted")
    before = path.stat()
    content = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise DataFormatError("lc1 source changed during read; snapshot not reproducible")
    if len(content) % 32:
        raise DataFormatError(f"{symbol}: truncated lc1 record")
    records = np.frombuffer(content, dtype=LC1_DTYPE)
    if np.any(records["minute"] >= 1440):
        raise DataFormatError(f"{symbol}: lc1 minute outside its encoded date")
    encoded = records["day"].astype(np.int64)
    days = np.zeros(len(records), dtype=np.int64)
    for value in np.unique(encoded):
        try:
            parsed = date(
                int(value // 2048 + 2004), int(value % 2048 // 100), int(value % 2048 % 100)
            )
        except ValueError as exc:
            raise DataFormatError(f"{symbol}: invalid lc1 date") from exc
        days[encoded == value] = (parsed - date(1970, 1, 1)).days
    stamps = days * DAY_US + records["minute"].astype(np.int64) * MINUTE_US - CST_US
    # Vectorized ROUND_HALF_UP for finite IEEE float32 prices; no banker rounding.
    prices = {}
    for column in ("open", "high", "low", "close"):
        values = records[column].astype(np.float64)
        prices[column] = np.sign(values) * np.floor(np.abs(values) * 100 + 0.5) / 100
    table = pa.table(
        {
            "symbol": pa.array([symbol] * len(records)),
            "exchange": pa.array([exchange] * len(records)),
            "timestamp": pa.array(stamps, type=SCHEMA.field("timestamp").type),
            **prices,
            "volume": records["volume"].astype(np.float64),
            "turnover": records["turnover"].astype(np.float64),
            "is_bj": pa.array(np.zeros(len(records), dtype=bool)),
        },
        schema=SCHEMA,
    )
    table, checks = relabel_1300(table)
    table = canonical_table(table, exchange, symbol)
    _, normalized_days = _clock(table)
    _, counts = np.unique(normalized_days, return_counts=True)
    return table, {
        **checks,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "source_rows": len(records),
        "rows": table.num_rows,
        "stock_days": len(counts),
        "non_240_stock_days": int((counts != 240).sum()),
        "single_bar_days": int((counts == 1).sum()),
    }


def _take_dates(table: pa.Table, start: date, end: date) -> pa.Table:
    _, days = _clock(table)
    lo, hi = ((value - date(1970, 1, 1)).days for value in (start, end))
    return table.take(pa.array(np.flatnonzero((days >= lo) & (days <= hi))))


def _day(table: pa.Table, day: date) -> pa.Table:
    return _take_dates(table, day, day)


def _price_equal(actual: float, expected: float) -> bool:
    return bool(
        np.isfinite(actual) and np.isfinite(expected) and abs(actual - expected) <= 0.005 + 1e-10
    )


def _volume_equal(actual: float, expected: int) -> bool:
    return actual == 0 if expected == 0 else abs(actual / expected - 1) <= 0.001 + 1e-12


def _anchor_check(table: pa.Table, anchor: DailyBar | None, *, first_open: bool) -> Summary:
    if not table.num_rows:
        return {"state": "no_bars"}
    if anchor is None:
        return {"state": "missing_daily_anchor", "failures": ["missing_daily_anchor"]}
    failures = []
    if not _price_equal(table["close"][-1].as_py(), anchor.close):
        failures.append("daily_close")
    if first_open and not _price_equal(table["open"][0].as_py(), anchor.open):
        failures.append("daily_open")
    volume_state = "incomplete_day"
    if table.num_rows == 240:
        volume_state = "checked"
        if not _volume_equal(pc.sum(table["volume"]).as_py(), anchor.volume):
            failures.append("daily_volume")
    return {
        "state": "checked",
        "rows": table.num_rows,
        "volume_state": volume_state,
        "failures": failures,
    }


def _same_package_day(single: pa.Table, main: pa.Table) -> bool:
    # Compare decoded prices/amount/quantity/timestamps, never combine two sources.
    if single.num_rows != main.num_rows:
        return False
    return all(single[column].equals(main[column]) for column in SCHEMA.names)


def _overlap(hf: pa.Table, main: pa.Table) -> Summary:
    hf = _take_dates(hf, OVERLAP_START, HF_END)
    main = _take_dates(main, OVERLAP_START, HF_END)
    hs, _ = _clock(hf)
    ms, _ = _clock(main)
    common, hi, mi = np.intersect1d(hs, ms, assume_unique=True, return_indices=True)
    total = len(np.union1d(hs, ms))
    if not total or not len(common):
        return {"ok": False, "state": "missing_overlap", "compared": 0}
    matches = np.ones(len(common), dtype=bool)
    by_price = {}
    for column in ("open", "high", "low", "close"):
        a, b = hf[column].to_numpy()[hi], main[column].to_numpy()[mi]
        agree = np.isfinite(a) & np.isfinite(b) & (np.abs(a - b) <= 0.005 + 1e-10)
        matches &= agree
        by_price[column] = float(agree.sum() / total)
    volume = hf["volume"].to_numpy()[hi] == main["volume"].to_numpy()[mi]
    price_share, volume_share = float(matches.sum() / total), float(volume.sum() / total)
    return {
        "ok": price_share >= 0.98 and volume_share >= 0.98,
        "state": "checked",
        "compared": len(common),
        "union_bars": total,
        "ohlc_share": price_share,
        "volume_share": volume_share,
        "by_price": by_price,
    }


def check_splice(
    hf: pa.Table,
    single: pa.Table,
    main: pa.Table,
    daily: Mapping[date, DailyBar],
    *,
    exchange: str,
    symbol: str,
    events: Sequence[Event] = (),
    price_limit: float | None = None,
    require_overlap: bool | None = None,
) -> Summary:
    """Validate one stock, returning {"splice": counts}; any checkable failure stops.

    The caller supplies two independently pinned vipdoc packages. It must never
    supply a view of one file twice to simulate the dual-package assertion.
    """
    hf, single, main = [canonical_table(t, exchange, symbol) for t in (hf, single, main)]
    failures: list[str] = []
    if price_limit is None:
        price_limit = rules.limit_pct(rules.board(exchange, symbol), False, SINGLE_DAY)
    left, right = _day(hf, HF_END), _day(single, SINGLE_DAY)
    result: Summary = {
        "symbol": symbol,
        "exchange": exchange,
        "ok": False,
        "failures": failures,
        "paired": bool(left.num_rows and right.num_rows),
        "hf_end": _anchor_check(left, daily.get(HF_END), first_open=False),
        "single_day": _anchor_check(right, daily.get(SINGLE_DAY), first_open=True),
        "incomplete_volume_days": 0,
    }
    for key in ("hf_end", "single_day"):
        check = result[key]
        failures.extend(f"{key}.{reason}" for reason in check.get("failures", []))
        result["incomplete_volume_days"] += check.get("volume_state") == "incomplete_day"
    if left.num_rows and right.num_rows:
        reference = float(left["close"][-1].as_py())
        for event in events:
            if event.ex_date == SINGLE_DAY:
                reference = rules.ref_price(reference, event.cash, event.pp, event.s, event.r)
        opening = float(right["open"][0].as_py())
        if reference <= 0 or not np.isfinite(reference) or not np.isfinite(opening):
            failures.append("invalid_reference")
        elif abs(opening / reference - 1) > price_limit + 0.005 + 1e-12:
            failures.append("overnight_price_limit")
    if not right.num_rows:
        # Resume/IPO first observed day: report unilateral price/volume checks.
        resumed = _take_dates(main, MAIN_START, date.max)
        if resumed.num_rows:
            resume_day = resumed["timestamp"][0].as_py().date()
            check = _anchor_check(_day(resumed, resume_day), daily.get(resume_day), first_open=True)
            result["resume_day"] = {"date": resume_day.isoformat(), **check}
            failures.extend(f"resume_day.{reason}" for reason in check.get("failures", []))
            result["incomplete_volume_days"] += check.get("volume_state") == "incomplete_day"
    repeated = _day(main, SINGLE_DAY)
    result["dual_package"] = {"state": "no_main_0807"}
    if repeated.num_rows:
        same = _same_package_day(right, repeated)
        result["dual_package"] = {"state": "checked", "ok": same}
        if not same:
            failures.append("dual_package_mismatch")
    overlap_required = symbol in OVERLAP_CODES if require_overlap is None else require_overlap
    result["overlap"] = {"state": "not_sampled"}
    if overlap_required:
        result["overlap"] = _overlap(hf, main)
        if not result["overlap"]["ok"]:
            failures.append("overlap_below_98pct")
        if not repeated.num_rows:
            failures.append("sample_main_missing_0807")
    result["ok"] = not failures
    if failures:
        raise SpliceError(symbol, result)
    return {"splice": result}


def merge_sources(
    hf: pa.Table,
    single: pa.Table,
    main: pa.Table,
    *,
    exchange: str,
    symbol: str,
) -> tuple[pa.Table, Summary]:
    """Return one source per stock-day, after validating all pre-filter labels."""
    hf, single, main = [canonical_table(t, exchange, symbol) for t in (hf, single, main)]
    pieces = [
        _take_dates(hf, date.min, HF_END),
        _day(single, SINGLE_DAY),
        _take_dates(main, MAIN_START, date.max),
    ]
    table = pa.concat_tables(pieces).sort_by([("timestamp", "ascending")])
    _clock(table)
    return table, {
        "source_rows": {
            "HF": pieces[0].num_rows,
            "vipdoc_single": pieces[1].num_rows,
            "vipdoc_main": pieces[2].num_rows,
        },
        "one_source_per_stock_day": True,
    }
