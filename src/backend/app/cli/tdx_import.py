"""daily-bars-import-tdx / intraday-bars-import-tdx：通达信本地文件导入，默认 dry-run（T-B133）。

契约只读参照：``git show 362ad41:docs/contracts/daily-bars-tdx.md`` §3、§5 与
``git show 362ad41:docs/contracts/intraday-bars.md`` §1.2–§1.3、§2.2。

- 默认 dry-run：生成 sha256 清单与对账报告到 ``--audit-dir``，库零写入；``--apply`` 才写库。
- 与已有行同键（任何来源）的只对账、不写入；写入一律 DO NOTHING。
- 不出网、不读证书；挂载与 ``--apply`` 须用户本人同意（契约 §7 U-T0），本 CLI 不替用户决定。
"""

from __future__ import annotations

import argparse
import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row

from app.api.v1.trades import normalize_code
from app.config import Settings
from app.db.tables.market import (
    daily_bars,
    minute5_bars,
    minute_bars,
    securities,
    trading_calendar,
)
from app.db.tables.realtime import pipeline_runs
from app.ingest.tdx_local import (
    BEIJING,
    ExistingBar,
    Kind,
    RunReport,
    TdxBar,
    TdxRefused,
    run_import,
)
from app.marketdata.daily_bars import (
    TDX_LOCAL_SOURCE,
    UPSERT_BATCH_ROWS,
    DailyBar,
    DailyBarsResult,
    _approved_owners,
    _union_universe,
    upsert_daily_bars,
)
from app.workers import jobs as jobs_mod

# daily-bars-tdx §3.4：麦蕊 3 年回填窗口（源契约 backfill_window_days(conn, trade_date, 3)）。
MAIRUI_BACKFILL_YEARS = 3
_PIPELINE_KIND = "daily_batch"
_REFUSED = 1


class TdxDeps(Protocol):
    """CLI 需要的库侧能力；生产实现为 ``DbDeps``，自检注入纯内存实现。"""

    def is_open(self, day: dt.date) -> bool | None: ...  # None：日历未覆盖

    def previous_open(self, day: dt.date) -> dt.date | None: ...

    def recommended_daily_until(self, now_bj: dt.datetime) -> dt.date | None: ...

    def first_mairui_minute_day(self, code: str) -> dt.date | None: ...

    def normalize(self, raw: str) -> str: ...

    def security_of(self, code: str) -> tuple[str, str | None] | None: ...

    def owned_codes(self, now_bj: dt.datetime) -> frozenset[str]: ...

    def existing(
        self, kind: Kind, code: str, bars: Sequence[TdxBar]
    ) -> Mapping[object, ExistingBar]: ...

    def write(self, kind: Kind, bars: Sequence[TdxBar], fetched_at: dt.datetime) -> int: ...

    def record_run(self, report: RunReport, run_date: dt.date) -> None: ...


class DbDeps:
    """生产实现：只在传入的连接上读；``write`` / ``record_run`` 仅 ``--apply`` 时调用。"""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self._securities: dict[str, tuple[str, str | None]] | None = None

    def is_open(self, day: dt.date) -> bool | None:
        value = self.conn.execute(
            select(trading_calendar.c.is_open).where(trading_calendar.c.date == day)
        ).scalar_one_or_none()
        return None if value is None else bool(value)

    def previous_open(self, day: dt.date) -> dt.date | None:
        return self.conn.execute(
            select(trading_calendar.c.date)
            .where(trading_calendar.c.date < day, trading_calendar.c.is_open.is_(True))
            .order_by(trading_calendar.c.date.desc())
            .limit(1)
        ).scalar_one_or_none()

    def recommended_daily_until(self, now_bj: dt.datetime) -> dt.date | None:
        from app.cli.daily_bars_backfill import _default_trade_date
        from app.marketdata.daily_bars import backfill_window_days

        trade_date = _default_trade_date(self.conn, now_bj)
        if trade_date is None:
            return None
        if backfill_window_days(self.conn, trade_date, MAIRUI_BACKFILL_YEARS) is None:
            return None
        try:
            start = trade_date.replace(year=trade_date.year - MAIRUI_BACKFILL_YEARS)
        except ValueError:
            start = trade_date.replace(year=trade_date.year - MAIRUI_BACKFILL_YEARS, day=28)
        # backfill_window_days 的窗口是 (start, trade_date]：第一个开市日即麦蕊回填起点。
        first = self.conn.execute(
            select(func.min(trading_calendar.c.date)).where(
                trading_calendar.c.date > start,
                trading_calendar.c.date <= trade_date,
                trading_calendar.c.is_open.is_(True),
            )
        ).scalar_one_or_none()
        return None if first is None else self.previous_open(first)

    def first_mairui_minute_day(self, code: str) -> dt.date | None:
        ts = self.conn.execute(
            select(func.min(minute_bars.c.ts)).where(
                minute_bars.c.code == code, minute_bars.c.source == "mairui"
            )
        ).scalar_one_or_none()
        return None if ts is None else ts.astimezone(BEIJING).date()

    def normalize(self, raw: str) -> str:
        return normalize_code(self.conn, raw)

    def security_of(self, code: str) -> tuple[str, str | None] | None:
        if self._securities is None:
            rows = self.conn.execute(
                select(securities.c.code, securities.c.type, securities.c.listing_status)
            ).all()
            self._securities = {r.code: (r.type, r.listing_status) for r in rows}
        return self._securities.get(code)

    def owned_codes(self, now_bj: dt.datetime) -> frozenset[str]:
        from app.cli.daily_bars_backfill import _default_trade_date

        day = _default_trade_date(self.conn, now_bj)
        if day is None:
            raise TdxRefused("calendar_not_covered")
        return frozenset(_union_universe(self.conn, _approved_owners(self.conn), day))

    def existing(
        self, kind: Kind, code: str, bars: Sequence[TdxBar]
    ) -> Mapping[object, ExistingBar]:
        if kind == "day":
            days = [b.trade_date for b in bars]
            rows = self.conn.execute(
                select(daily_bars).where(
                    daily_bars.c.code == code,
                    daily_bars.c.adj_type == "none",
                    daily_bars.c.trade_date >= min(days),
                    daily_bars.c.trade_date <= max(days),
                )
            ).all()
            return {r.trade_date: _existing(r) for r in rows}
        table = minute_bars if kind == "lc1" else minute5_bars
        stamps = [b.ts for b in bars if b.ts is not None]
        rows = self.conn.execute(
            select(table).where(
                table.c.code == code, table.c.ts >= min(stamps), table.c.ts <= max(stamps)
            )
        ).all()
        return {r.ts: _existing(r) for r in rows}

    def write(self, kind: Kind, bars: Sequence[TdxBar], fetched_at: dt.datetime) -> int:
        if kind == "day":
            result = DailyBarsResult(
                bars=[
                    DailyBar(
                        code=b.code,
                        trade_date=b.trade_date,
                        adj_type="none",
                        open=b.open,
                        high=b.high,
                        low=b.low,
                        close=b.close,
                        pre_close=None,
                        volume=b.volume,
                        amount=b.amount,
                        is_suspended=None,
                    )
                    for b in bars
                ]
            )
            stats = upsert_daily_bars(
                self.conn, result, source=TDX_LOCAL_SOURCE, licence_id=None, fetched_at=fetched_at
            )
            return stats.inserted
        table = minute_bars if kind == "lc1" else minute5_bars
        inserted = 0
        for offset in range(0, len(bars), UPSERT_BATCH_ROWS):
            chunk = bars[offset : offset + UPSERT_BATCH_ROWS]
            ret = self.conn.execute(
                pg_insert(table)
                .values(
                    [
                        {
                            "code": b.code,
                            "ts": b.ts,
                            "open": b.open,
                            "high": b.high,
                            "low": b.low,
                            "close": b.close,
                            "volume": b.volume,
                            "amount": b.amount,
                            "source": TDX_LOCAL_SOURCE,
                            "source_licence_id": None,
                            "fetched_at": fetched_at,
                        }
                        for b in chunk
                    ]
                )
                .on_conflict_do_nothing(index_elements=["code", "ts"])
                .returning(table.c.code)
            ).all()
            inserted += len(ret)
        return inserted

    def record_run(self, report: RunReport, run_date: dt.date) -> None:
        self.conn.execute(
            insert(pipeline_runs).values(
                kind=_PIPELINE_KIND,
                run_date=run_date,
                step=f"tdx_local.import_{report.kind}",
                status=report.status,
                finished_at=dt.datetime.now(dt.UTC),
                stats=report.stats(),
            )
        )


def _existing(row: Row[Any]) -> ExistingBar:
    m = row._mapping
    return ExistingBar(
        source=m["source"],
        open=m["open"],
        high=m["high"],
        low=m["low"],
        close=m["close"],
        volume=m["volume"],
        amount=m["amount"],
    )


def _scope(raw: str) -> tuple[str, frozenset[str]]:
    parts = raw.split(",")
    if parts[0] not in ("owned", "market") or parts[1:] not in ([], ["exclude-bj"]):
        raise argparse.ArgumentTypeError(
            "expected owned or market, optionally followed by ,exclude-bj"
        )
    return parts[0], frozenset({"bj"}) if parts[1:] else frozenset()


def _parser(prog: str, *, intraday: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog, description="Read-only TDX import; dry-run by default."
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--audit-dir", dest="audit_dir", required=True, type=Path)
    parser.add_argument("--until", required=not intraday, default=None)
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--scope", type=_scope, default="owned")
    if intraday:
        parser.add_argument("--kind", choices=("lc1", "lc5"), required=True)
    parser.add_argument("--apply", action="store_true", help="write rows; default is dry-run")
    return parser


def _iso(raw: str | None, name: str) -> dt.date | None:
    if raw is None:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise TdxRefused(f"{name}_invalid") from exc


def _past_open(deps: TdxDeps, day: dt.date, today: dt.date, name: str) -> None:
    """--until 须为过去的开市日：今天、未来、休市日、日历未覆盖都拒绝。"""
    if day >= today or deps.is_open(day) is not True:
        raise TdxRefused(f"{name}_must_be_past_open_day")


def _run(
    argv: list[str] | None,
    *,
    prog: str,
    intraday: bool,
    now: dt.datetime | None,
    deps: TdxDeps | None,
    settings: Settings | None,
    run_id: str | None,
) -> int:
    args = _parser(prog, intraday=intraday).parse_args(argv)
    stamp = now if now is not None else dt.datetime.now(dt.UTC)
    if stamp.tzinfo is None:
        print("refused: now must be timezone-aware")
        return _REFUSED
    if deps is not None:
        return _execute(args, intraday=intraday, now=stamp, deps=deps, run_id=run_id)
    engine = jobs_mod._engine(settings if settings is not None else Settings())
    if args.apply:
        with engine.begin() as conn:
            return _execute(args, intraday=intraday, now=stamp, deps=DbDeps(conn), run_id=run_id)
    with engine.connect() as conn:
        try:
            return _execute(args, intraday=intraday, now=stamp, deps=DbDeps(conn), run_id=run_id)
        finally:
            conn.rollback()


def _execute(
    args: argparse.Namespace,
    *,
    intraday: bool,
    now: dt.datetime,
    deps: TdxDeps,
    run_id: str | None,
) -> int:
    bj = now.astimezone(BEIJING)
    today = bj.date()
    kind: Kind = cast(Kind, args.kind) if intraday else "day"
    try:
        start = _iso(args.start, "from")
        until = _iso(args.until, "until")
        scope_name, exclude = args.scope
        if exclude and not intraday:
            raise TdxRefused("scope_exclude_bj_intraday_only")
        if scope_name == "market":
            # 源契约 §9.6 的 RESEARCH_MARKET_SCOPE_ENABLED 在本基线未实现：保守拒绝。
            raise TdxRefused("market_scope_disabled")
        if until is not None:
            _past_open(deps, until, today, "until")
        recommended: dt.date | None = None
        if intraday:
            fallback = deps.previous_open(today)
            if fallback is None:
                raise TdxRefused("calendar_not_covered")

            def until_for(code: str) -> dt.date | None:
                # intraday-bars §1.3：该代码最早 mairui 分钟日的前一开市日；没有则取前一开市日。
                first = deps.first_mairui_minute_day(code)
                cutoff = deps.previous_open(first) if first is not None else fallback
                if cutoff is not None and until is not None:
                    cutoff = min(cutoff, until)
                return cutoff

        else:
            recommended = deps.recommended_daily_until(bj)
            print(f"recommended_until={recommended.isoformat() if recommended else 'unknown'}")
            if recommended is None:
                raise TdxRefused("calendar_not_covered")
            if until is None or until > recommended:
                raise TdxRefused("until_after_mairui_window_start")
            fixed_until = until

            def until_for(code: str) -> dt.date | None:
                return fixed_until

        if start is not None and until is not None and start > until:
            raise TdxRefused("from_after_until")
        scope = deps.owned_codes(bj)
        ident = run_id or uuid.uuid4().hex[:12]

        def writer(bars: Sequence[TdxBar]) -> int:
            return deps.write(kind, bars, now)

        report = run_import(
            root=args.root,
            audit_dir=args.audit_dir,
            kind=kind,
            start=start,
            until_for=until_for,
            normalize=deps.normalize,
            security_of=deps.security_of,
            scope_codes=scope,
            exclude=exclude,
            existing_for=lambda code, bars: deps.existing(kind, code, bars),
            writer=writer if args.apply else None,
            now=now,
            run_id=ident,
            # 分钟线金额容差无出处（日线 §5 只针对日线）：未验证，默认不比对金额。
            compare_amount=kind == "day",
        )
    except TdxRefused as exc:
        # T-B133 11:07 裁定②：分钟线缺 bj 目录时提示可显式排除 bj（排除后清单记缺口）。
        bj_missing = intraday and exc.reason.startswith("root_missing:bj/")
        hint = "; hint: --scope owned,exclude-bj" if bj_missing else ""
        print(f"refused: {exc.reason}{hint}")
        return _REFUSED
    if args.apply:
        deps.record_run(report, today)
    for key, value in report.stats().items():
        print(f"{key}={value}")
    print("applied" if args.apply else "dry-run")
    return 0


def daily_main(
    argv: list[str] | None = None,
    *,
    now: dt.datetime | None = None,
    deps: TdxDeps | None = None,
    settings: Settings | None = None,
    run_id: str | None = None,
) -> int:
    return _run(
        argv,
        prog="daily-bars-import-tdx",
        intraday=False,
        now=now,
        deps=deps,
        settings=settings,
        run_id=run_id,
    )


def intraday_main(
    argv: list[str] | None = None,
    *,
    now: dt.datetime | None = None,
    deps: TdxDeps | None = None,
    settings: Settings | None = None,
    run_id: str | None = None,
) -> int:
    return _run(
        argv,
        prog="intraday-bars-import-tdx",
        intraday=True,
        now=now,
        deps=deps,
        settings=settings,
        run_id=run_id,
    )
