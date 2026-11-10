"""Prepare verified, chronological stock inputs for the T-R58d offline runner."""

from __future__ import annotations

import csv
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from hashlib import file_digest
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import data, inputs, rules, sessions, sim, splice
from .errors import DataFormatError

CALENDAR_SHA = "af18d0298024c4e38f44aaf1ac35347d6e044a513f9cba9c26b23fdd64aa330b"
# Chief's §2.3 ruling is for these four 2026-08-07 stock-days in the local snapshot.
_SINGLE_DAY_SUSPENSIONS = frozenset(
    {("SZ", "000838"), ("SZ", "300246"), ("SZ", "300333"), ("SZ", "300862")}
)


@dataclass(frozen=True)
class ResearchPaths:
    data_root: Path
    single_package: Path | None
    main_package: Path | None
    calendar: Path
    st_history: Path | None = None
    listing_history: Path | None = None
    securities: Path | None = None
    delisting_list: Path | None = None
    live_vipdoc: Path | None = None


@dataclass(frozen=True)
class Prepared:
    dates: list[date]
    segments: list[sim.Segment]
    pool: list[data.Stock]
    hf_dir: Path
    hf_files: dict[inputs.StockKey, str]
    single: inputs.VipdocInput | None
    main: inputs.VipdocInput | inputs.LocalVipdoc
    archive: Path
    archive_sha256: str
    events: dict[inputs.StockKey, list[sim.Event]]
    index_close: dict[date, float]
    meta: data.Summary
    st_history: data.History
    listing_history: data.History
    evidence: data.Summary


def _securities(path: Path | None) -> dict[inputs.StockKey, dict[str, date | None]]:
    if path is None:
        return {}
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = csv.DictReader(file)
        required = {"exchange", "symbol", "listing_date", "delisting_date"}
        if rows.fieldnames is None or not required <= set(rows.fieldnames):
            raise DataFormatError("securities export needs exchange/symbol/listing/delisting dates")
        result = {}
        for row in rows:
            key = row["exchange"], row["symbol"]
            if splice.selected_symbol(*key):
                if key in result:
                    raise DataFormatError("duplicate securities export identity")
                result[key] = {
                    name: data._date(row[name]) for name in ("listing_date", "delisting_date")
                }
        return result


def _termination_list(
    path: Path | None, start: date, end: date
) -> dict[inputs.StockKey, date] | None:
    if path is None:
        return None
    result = {}
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = csv.DictReader(file)
        required = {"exchange", "symbol", "delisting_date"}
        if rows.fieldnames is None or not required <= set(rows.fieldnames):
            raise DataFormatError("termination list needs exchange/symbol/delisting date")
        for row in rows:
            key = row["exchange"], row["symbol"]
            if not splice.selected_symbol(*key):
                continue
            day = data._date(row["delisting_date"])
            if day is None:
                raise DataFormatError("termination date missing")
            if start <= day <= end:
                if key in result:
                    raise DataFormatError("duplicate termination-list identity")
                result[key] = day
    return result


def _stock_pool(
    hf_dir: Path,
    single: inputs.VipdocInput | None,
    main: inputs.VipdocInput | inputs.LocalVipdoc,
    expect: data.Summary,
) -> tuple[list[data.Stock], dict[inputs.StockKey, str]]:
    pool = data.pool(hf_dir)
    if (
        len(pool) != expect["pool_stocks"]
        or sum(s[2] == "D" for s in pool) != expect["pool_delisted"]
    ):
        raise DataFormatError("HF SH/SZ pool count or delisted count differs from plan")
    if any(not splice.selected_symbol(*stock[:2]) or stock[2] not in {"L", "D"} for stock in pool):
        raise DataFormatError("invalid SH/SZ identity or universe status in HF pool")
    hf = {
        (row["exchange"], row["symbol"]): row["sha256"]
        for row in data._rows(hf_dir / "manifest_files.csv")
        if row["is_bj"] == "False"
    }
    if len(hf) != len(pool):
        raise DataFormatError("duplicate identities in HF stock pool")
    minute_keys = set(main.files)
    if single is not None:
        minute_keys.update(single.files)
    vipdoc_only = minute_keys - hf.keys()
    pool.extend((*key, "vipdoc_only") for key in sorted(vipdoc_only))
    return pool, hf


def preflight(paths: ResearchPaths, config: data.Summary, *, workers: int = 8) -> Prepared:
    single: inputs.VipdocInput | None
    main: inputs.VipdocInput | inputs.LocalVipdoc
    if paths.live_vipdoc is not None:
        if paths.single_package is not None or paths.main_package is not None:
            raise DataFormatError("use either local vipdoc or two packages")
        single, main = None, inputs.pin_local_vipdoc(paths.live_vipdoc)
    else:
        if paths.single_package is None or paths.main_package is None:
            raise DataFormatError("vipdoc input is required")
        single, main = inputs.verify_vipdoc_pair(paths.single_package, paths.main_package)
    hf_root = paths.data_root / "hf-1min"
    hf_dir = hf_root / "2022plus"
    hfc = inputs.verify_hf(
        hf_dir,
        hf_root / "T-B136-hf-ready.json",
        revision=config["data"]["hf_revision"],
        expect=config["expect"],
        workers=workers,
    )
    meta_dir = hf_root / "raw" / "metadata"
    if data.sha256(paths.calendar) != CALENDAR_SHA:
        raise DataFormatError("published calendar differs from the pinned plan revision")
    tdx = paths.data_root / "tdx-pack"
    archive = data._verified_archive(tdx, "hsjday", None)
    gbbq = data._verified_archive(tdx, "gbbq", None)
    with zipfile.ZipFile(archive) as daily_zip:
        daily = data.DailyArchive(daily_zip)
        dates = data.calendar(
            meta_dir,
            config["data"]["start"],
            config["data"]["end"],
            calendar_2026=paths.calendar,
            index_dates=list(daily.records("SH", "000001", required=True)),
            expected_days=config["expect"]["trading_days"],
        )
        index_close = {
            day: bar.close
            for day, bar in daily.records("SH", "000300", required=True).items()
            if dates[0] <= day <= dates[-1]
        }
    if set(index_close) != set(dates):
        raise DataFormatError("D5: sh000300 does not cover the independent calendar")
    segments, segment_evidence = sessions.segments(config, dates)
    pool, hf_files = _stock_pool(hf_dir, single, main, config["expect"])
    meta = data.load_meta(meta_dir)
    meta["config"] = config
    meta["securities"] = _securities(paths.securities)
    meta["termination_list"] = _termination_list(paths.delisting_list, dates[0], dates[-1])
    st, st_coverage = data.load_status_history(paths.st_history, "st")
    listing, listing_coverage = data.load_status_history(paths.listing_history, "listing")
    archive_sha = data.sha256(archive)
    gbbq_sha = data.sha256(gbbq)
    events = data.load_gbbq(gbbq, expected_sha256=gbbq_sha)
    evidence = {
        "hf": {
            "revision": config["data"]["hf_revision"],
            "manifest_sha256": hfc["manifest_sha256"],
            "manifest_files_sha256": hfc["manifest_files_sha256"],
            "sha_scope": hfc["sha_scope"],
        },
        "vipdoc_single": single.evidence() if single is not None else {"mode": "shared_date_use"},
        "vipdoc_main": main.evidence(),
        "hsjday_sha256": archive_sha,
        "gbbq_sha256": gbbq_sha,
        "calendar_sha256": CALENDAR_SHA,
        "metadata_sha256": {
            name: data.sha256(meta_dir / name)
            for name in (
                "market_calendar.csv",
                "coverage_by_instrument.csv",
                "no_bar_day_classification.csv",
                "absent_instruments.csv",
            )
        },
        "stock_pool": {
            "hf": len(hf_files),
            "vipdoc_only": len(pool) - len(hf_files),
            "delisted_hf": sum(stock[2] == "D" for stock in pool),
            "bj": 0,
        },
        "segments": segment_evidence,
        "st_coverage": st_coverage,
        "listing_coverage": listing_coverage,
        "termination_list_sha256": data.sha256(paths.delisting_list)
        if paths.delisting_list
        else None,
        "gbbq_revision_bias": "unable_to_verify",
    }
    return Prepared(
        dates,
        segments,
        pool,
        hf_dir,
        hf_files,
        single,
        main,
        archive,
        archive_sha,
        events,
        index_close,
        meta,
        st,
        listing,
        evidence,
    )


def _hf_stock(prepared: Prepared, key: inputs.StockKey) -> pa.Table:
    expected = prepared.hf_files.get(key)
    if expected is None:
        return splice.empty_table()
    exchange, symbol = key
    path = prepared.hf_dir / exchange / f"{symbol}.parquet"
    with path.open("rb") as stream:
        # Hash and parse the same file handle; never parse a replacement by path.
        if file_digest(stream, "sha256").hexdigest() != expected:
            raise DataFormatError(f"HF stock changed since input gate: {exchange}/{symbol}")
        stream.seek(0)
        return pq.read_table(stream)


def _minute_stock(
    package: inputs.VipdocInput | inputs.LocalVipdoc | None,
    key: inputs.StockKey,
    *,
    inventory_end: date | None = None,
) -> tuple[pa.Table, data.Summary]:
    source = package.files.get(key) if package is not None else None
    if source is None:
        return splice.empty_table(), {}
    table, checks = inputs.decode_verified(source, key, inventory_end=inventory_end)
    if inventory_end is not None:
        checks["source_path"] = source.path.relative_to(package.root).as_posix()
    return table, checks


def _listing_check(
    stock: data.Stock, prepared: Prepared, single: pa.Table, main: pa.Table
) -> data.Summary:
    key = stock[:2]
    securities = prepared.meta["securities"].get(key)
    if stock[2] != "vipdoc_only":
        hf = prepared.meta["coverage"].get(stock[1], {})
        mismatches = [
            field
            for field in ("listing_date", "delisting_date")
            if securities is not None and hf.get(field) != securities[field]
        ]
        return {"state": "unknown" if securities is None else "checked", "mismatches": mismatches}
    first_days = [(t["timestamp"][0].as_py().date(), t) for t in (single, main) if t.num_rows]
    if not first_days:
        raise DataFormatError(f"vipdoc-only code has no normalized records: {key}")
    first, source = min(first_days, key=lambda item: item[0])
    listed = securities["listing_date"] if securities else None
    first_rows = splice._day(source, first).num_rows
    if listed is not None and (listed > first or (first_rows == 1 and listed != first)):
        raise DataFormatError(f"vipdoc-only listing date conflicts with first bars: {key}")
    return {
        "state": "checked" if listed else "unknown",
        "first": first,
        "rows": first_rows,
        "listing_date": listed,
    }


def _exrights_audit(
    stock: data.Stock,
    grid: data.Grid,
    dates: list[date],
    st: np.ndarray,
    events: list[sim.Event],
) -> data.Summary:
    index = {day: i for i, day in enumerate(dates)}
    selected = {e.ex_date for e in events if e.ex_date in index}
    result: data.Summary = {"checked": 0, "uncheckable": 0, "outside_limit_dates": []}
    if not selected:
        return result
    valid = grid["valid"]
    last_slot = np.where(valid, np.arange(valid.shape[1]), -1).max(axis=1)
    prior_days = np.maximum.accumulate(np.where(last_slot >= 0, np.arange(len(dates)), -1))
    board = rules.board(*stock[:2])
    for day in sorted(selected):
        d = index[day]
        prev = prior_days[d - 1] if d else -1
        if prev < 0 or not valid[d].any():
            result["uncheckable"] += 1
            continue
        reference = float(grid["c"][prev, last_slot[prev]])
        for e in events:
            if e.ex_date == day:
                reference = rules.ref_price(reference, e.cash, e.pp, e.s, e.r)
        if not np.isfinite(reference) or reference <= 0:
            result["uncheckable"] += 1
            continue
        up, down = rules.limit_prices(reference, rules.limit_pct(board, bool(st[d]), day))
        result["checked"] += 1
        if (
            np.max(grid["h"][d, valid[d]]) > up + 1e-9
            or np.min(grid["l"][d, valid[d]]) < down - 1e-9
        ):
            result["outside_limit_dates"].append(day.isoformat())
    return result


def _exclude_single_day_suspension(
    key: inputs.StockKey, single: pa.Table, daily: dict[date, splice.DailyBar]
) -> tuple[pa.Table, list[data.Summary]]:
    """Only the adjudicated local-snapshot days qualify; missing anchors alone do not."""
    if key not in _SINGLE_DAY_SUSPENSIONS or not single.num_rows or splice.SINGLE_DAY in daily:
        return single, []
    prior = max((day for day in daily if day < splice.SINGLE_DAY), default=None)
    following = min((day for day in daily if day > splice.SINGLE_DAY), default=None)
    if prior is None or prior >= splice.HF_END or following is None:
        return single, []
    return splice.empty_table(), [
        {
            "date": splice.SINGLE_DAY.isoformat(),
            "reason": "suspension_residual_minutes",
            "label": "停牌期分钟残留",
            "rows": single.num_rows,
            "prior_daily_date": prior.isoformat(),
            "next_daily_date": following.isoformat(),
        }
    ]


def iter_stocks(prepared: Prepared) -> Iterator[tuple[sim.StockInput, data.Summary]]:
    """Decode each verified stock, check the splice before handing off its grid."""
    if data.sha256(prepared.archive) != prepared.archive_sha256:
        raise DataFormatError("hsjday archive changed after preflight")
    with zipfile.ZipFile(prepared.archive) as archive:
        daily = data.DailyArchive(archive)
        for stock in prepared.pool:
            exchange, symbol, _ = stock
            key = exchange, symbol
            hf = _hf_stock(prepared, key)
            shared_vipdoc = isinstance(prepared.main, inputs.LocalVipdoc)
            main, mc = _minute_stock(
                prepared.main, key, inventory_end=prepared.dates[-1] if shared_vipdoc else None
            )
            anchors = daily.records(*key)
            exclusions = []
            if shared_vipdoc:
                single = splice._day(main, splice.SINGLE_DAY)
                sc = {"mode": "derived_date_use", "rows": single.num_rows}
                single, exclusions = _exclude_single_day_suspension(key, single, anchors)
            else:
                single, sc = _minute_stock(prepared.single, key)
            listing = _listing_check(stock, prepared, single, main)
            events = prepared.events.get(key, [])
            try:
                grid, checks = data.load_spliced_stock(
                    hf,
                    single,
                    main,
                    prepared.dates,
                    anchors,
                    exchange=exchange,
                    symbol=symbol,
                    events=events,
                    shared_vipdoc=shared_vipdoc,
                )
            except splice.SpliceError as exc:
                if exclusions:
                    exc.summary["splice"]["pre_splice_exclusions"] = exclusions
                raise
            if exclusions:
                checks["splice"]["pre_splice_exclusions"] = exclusions
            checks["lc1"] = {"single": sc, "main": mc}
            checks["listing"] = listing
            meta = prepared.meta
            if stock[2] == "vipdoc_only":
                meta = {**meta, "coverage": {symbol: {"listing_date": listing["listing_date"]}}}
            kinds, st, reasons = data.day_kinds(
                stock,
                prepared.dates,
                meta,
                prepared.st_history,
                prepared.listing_history,
                grid,
            )
            checks["exclusions"] = reasons
            checks["exrights"] = _exrights_audit(stock, grid, prepared.dates, st, events)
            yield (
                sim.StockInput(
                    exchange,
                    symbol,
                    prepared.dates,
                    *[grid[key] for key in "ohlcva"],
                    kinds,
                    st,
                    events,
                ),
                checks,
            )
