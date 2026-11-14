"""日 K 分型批次预算与 ingest 侧拉取（C2，契约 §9.3）。

日常与回填有效常量各自默认0（unset），仅接受各自硬界内的正整数。
不进Settings、不读环境或回执放宽预算；移除旧unlimited路径。
打开任一生效常量仍属单D，须用户本人批准，本模块不提供切换入口。

本模块不读证书、不调用 ``mairui_get``；出网只通过调用方注入的 transport。
未注入时 fail-closed，不打开套接字。k 未测得前，单日按每标的一段计计划调用。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import Connection

from app.common.errors import AppError
from app.ingest.daily_bars_plan import DailyBarsPlanError, segments, window_days
from app.ingest.daily_lists import STOP as LISTS_STOP
from app.ingest.daily_lists import DailyHaltError, limited
from app.ingest.egress import HALT_LIMIT, EgressDenied
from app.marketdata.daily_bars import (
    DailyBar,
    DailyBarsResult,
    _empty_stats,
    _record_run,
    daily_universe,
    upsert_daily_bars,
)
from app.reports.service import covered

# C2 effective batch gates; opening either remains a separately authorized D change.
DAILY_BARS_BATCH_LIMIT: int = 0
DAILY_BARS_BACKFILL_BATCH_LIMIT: int = 0
DAILY_BARS_BATCH_CEILING = 2000
DAILY_BARS_DAILY_BATCH_CEILING = 500
AUTHORIZATION = Path("/run/aia/receipts/mairui-daily-bars.json")
HALT = Path("/run/aia/state/halt/mairui-daily-bars.HALTED")
# 日 K 回执与日 K outbox 共用。
KIND = "mairui_daily_bars"


def persist_halt(halt: Path, payload: bytes = HALT_LIMIT) -> bool:
    """O_EXCL 0600 fsync. FileExistsError counts as success. Returns False on I/O error."""
    try:
        fd = os.open(halt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return True
    except Exception:  # noqa: BLE001
        return False


Transport = Callable[[str, dt.date, dt.date], tuple[int, DailyBar | DailyBarsResult | None]]
GrantReader = Callable[[], object | None]
Clock = Callable[[], dt.datetime]


@dataclass(frozen=True)
class DailyBarsBudget:
    kind: Literal["unset", "capped"]
    cap: int | None = None


class MairuiDailyBarsSource:
    """仅 ingest 进程可调用的麦蕊日 K 源。出网必须走注入的 transport。"""

    name = "mairui"


def daily_bars_batch_budget(value: object, batch_kind: str = "daily") -> DailyBarsBudget:
    """Reject caps outside this batch type's bound; defaults never borrow backfill quota."""
    if batch_kind not in {"daily", "backfill"}:
        return DailyBarsBudget(kind="unset")
    ceiling = DAILY_BARS_DAILY_BATCH_CEILING if batch_kind == "daily" else DAILY_BARS_BATCH_CEILING
    if type(value) is int and 0 < value <= ceiling:
        return DailyBarsBudget(kind="capped", cap=value)
    return DailyBarsBudget(kind="unset")


def _transport_disabled(code: str, start: dt.date, end: dt.date) -> tuple[int, DailyBar | None]:
    raise RuntimeError("daily bars HTTP transport is not enabled")


@dataclass(frozen=True)
class DailyBarsGrant:
    user_id: uuid.UUID
    licence_id: uuid.UUID
    receipt_id: uuid.UUID
    start: dt.datetime
    end: dt.datetime
    digest: str


def _receipt_permission_ok(path: Path) -> bool:
    """root 属主、0444 常规文件、目录不可写、拒绝符号链接目录。"""
    try:
        parent = path.parent.stat()
        if (
            path.parent.resolve() != path.parent.absolute()
            or parent.st_uid != 0
            or stat.S_IMODE(parent.st_mode) & 0o022
        ):
            return False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        st = os.fstat(fd)
        return bool(
            stat.S_ISREG(st.st_mode) and st.st_uid == 0 and stat.S_IMODE(st.st_mode) == 0o444
        )
    finally:
        os.close(fd)


def _parse_daily_bars_grant(
    raw: bytes, *, now: dt.datetime, user_id: uuid.UUID
) -> DailyBarsGrant | None:
    """按 ``read_grant`` 解析 JSON，并用注入的 clock 与 user_id 绑定校验。不读证书。"""
    if len(raw) > 8192:
        return None
    try:
        obj = json.loads(raw)
        if (
            set(obj) != {"kind", "user_id", "licence_id", "receipt_id", "not_before", "expires_at"}
            or obj["kind"] != KIND
        ):
            return None
        start, end = (
            dt.datetime.fromisoformat(obj["not_before"]),
            dt.datetime.fromisoformat(obj["expires_at"]),
        )
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            return None
        if now.tzinfo is None or not (start <= now < end):
            return None
        uid = uuid.UUID(obj["user_id"])
        if uid != user_id:
            return None
        return DailyBarsGrant(
            uid,
            uuid.UUID(obj["licence_id"]),
            uuid.UUID(obj["receipt_id"]),
            start,
            end,
            hashlib.sha256(raw).hexdigest(),
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def read_daily_bars_grant(
    path: Path = AUTHORIZATION,
    *,
    now: dt.datetime,
    user_id: uuid.UUID,
) -> DailyBarsGrant | None:
    """按 ``read_grant`` 的规则读日 K 回执：root / 0444 / 目录不可写 / JSON / 有效期 / user_id。

    不读证书。回执里的额外字段（含 limit）会使集合校验失败，不能放宽限额。
    """
    if not _receipt_permission_ok(path):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        raw = os.read(fd, 8193)
        return _parse_daily_bars_grant(raw, now=now, user_id=user_id)
    finally:
        os.close(fd)


def _stamp(clock: Clock) -> dt.datetime:
    value = clock()
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value


def fetch_mairui_daily_bars(
    conn: Connection,
    *,
    trade_date: dt.date,
    user_id: uuid.UUID,
    transport: Transport | None = None,
    stop_path: Path | None = None,
    halt_path: Path | None = None,
    grant_reader: GrantReader | None = None,
    clock: Clock | None = None,
    window_trading_days: int | None = None,
    receipt_path: Path | None = None,
    batch_kind: str = "daily",
    run_recorder: Callable[..., None] | None = None,
    code_ready: Callable[[str], bool] | None = None,
    page_days: int | None = None,
) -> int:
    """按预算与停止规则拉取一日（或窗口）日 K。不读证书，默认不出网。"""
    send = transport if transport is not None else _transport_disabled
    stop = stop_path if stop_path is not None else LISTS_STOP
    halt = halt_path if halt_path is not None else HALT
    now = clock if clock is not None else (lambda: dt.datetime.now(dt.UTC))
    receipt = receipt_path if receipt_path is not None else AUTHORIZATION

    def _default_grant_reader() -> DailyBarsGrant | None:
        return read_daily_bars_grant(receipt, now=_stamp(now), user_id=user_id)

    reader = grant_reader if grant_reader is not None else _default_grant_reader
    record_run = _record_run if run_recorder is None else run_recorder

    value = DAILY_BARS_BACKFILL_BATCH_LIMIT if batch_kind == "backfill" else DAILY_BARS_BATCH_LIMIT
    budget = daily_bars_batch_budget(value, batch_kind)
    if budget.kind == "unset":
        record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="skipped",
            stats=_empty_stats(
                user_id, window_trading_days, issues=["daily_bars_http_budget_unset"]
            ),
        )
        return 0

    grant = reader()
    if (
        not isinstance(grant, DailyBarsGrant)
        or grant.user_id != user_id
        or not isinstance(grant.licence_id, uuid.UUID)
        or not isinstance(grant.receipt_id, uuid.UUID)
        or grant.start.tzinfo is None
        or grant.end.tzinfo is None
        or not (grant.start <= _stamp(now) < grant.end)
    ):
        record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="skipped",
            stats=_empty_stats(user_id, window_trading_days, issues=["data_licence_unavailable"]),
        )
        return 0

    try:
        is_open = covered(conn, trade_date)
    except AppError as exc:
        if exc.details is not None and exc.details.get("issue") == "CALENDAR_NOT_COVERED":
            record_run(
                conn,
                trade_date,
                user_id,
                window_trading_days,
                status="skipped",
                stats=_empty_stats(user_id, window_trading_days, issues=["calendar_not_covered"]),
            )
            return 0
        raise
    if not is_open:
        record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="skipped",
            stats=_empty_stats(user_id, window_trading_days, issues=["calendar_not_covered"]),
        )
        return 0

    # The page size is verified offline by the caller; production has no default k.
    try:
        if window_trading_days not in (None, 1) and page_days is None:
            raise DailyBarsPlanError("daily_bars_history_page_size_unverified")
        days = (
            window_days(conn, trade_date, window_trading_days)
            if window_trading_days not in (None, 1)
            else (trade_date,)
        )
        pages = segments(days, page_days)
    except DailyBarsPlanError as exc:
        issue = str(exc)
        record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="failed",
            error=issue,
            stats=_empty_stats(user_id, window_trading_days, issues=[issue]),
        )
        return 0

    codes = daily_universe(conn, user_id, trade_date)
    if not codes:
        record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="ok",
            stats=_empty_stats(user_id, window_trading_days, codes=0),
        )
        return 0

    issues: list[str] = []
    bars: list[DailyBar] = []
    last_received: dt.datetime | None = None
    calls = 0
    already_ready = 0

    if halt.is_file() or stop.is_file():
        issues.extend(["daily_bars_upstream_halted"] * len(codes))
        record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="skipped",
            stats=_empty_stats(user_id, window_trading_days, codes=len(codes), issues=issues),
        )
        return 0

    cap = budget.cap or 0
    batch_halted = False
    for index, code in enumerate(codes):
        if code_ready is not None and code_ready(code):
            already_ready += 1
            continue
        if cap - calls < len(pages):
            issues.extend(["daily_bars_quota_deferred"] * (len(codes) - index))
            break
        for start, end in pages:
            if halt.exists() or stop.exists():
                batch_halted = True
                break
            try:
                http_status, payload = send(code, start, end)
            except (DailyHaltError, EgressDenied):
                batch_halted = True
                break
            last_received = _stamp(now)
            calls += 1
            if limited(http_status, payload) or (
                isinstance(payload, DailyBarsResult) and payload.halted is not None
            ):
                batch_halted = True
                break
            received = (
                (payload,)
                if isinstance(payload, DailyBar)
                else tuple(payload.bars)
                if isinstance(payload, DailyBarsResult)
                else ()
            )
            if http_status != 200 or not received:
                issues.append(f"daily_bars_missing:{code}")
                continue
            expected_days = {day for day in days if start <= day <= end}
            keys = [(bar.code, bar.trade_date, bar.adj_type) for bar in received]
            if len(set(keys)) != len(keys) or any(
                bar.code != code or bar.trade_date not in expected_days or bar.adj_type != "none"
                for bar in received
            ):
                raise ValueError("daily_bars_history_payload_outside_plan")
            bars.extend(received)
            if {bar.trade_date for bar in received} != expected_days:
                issues.append(f"daily_bars_missing:{code}")
        if batch_halted:
            persist_halt(halt, HALT_LIMIT)
            issues.extend(["daily_bars_upstream_halted"] * (len(codes) - index))
            break

    fetched_at = last_received if last_received is not None else _stamp(now)
    written = 0
    if bars:
        upsert = upsert_daily_bars(
            conn,
            DailyBarsResult(bars=tuple(bars)),
            source=MairuiDailyBarsSource.name,
            licence_id=grant.licence_id,
            fetched_at=fetched_at,
        )
        written = upsert.inserted + upsert.unchanged
        issues.extend(upsert.issues)

    run_status = (
        "partial"
        if issues
        else ("ok" if last_received is not None or bars or already_ready else "skipped")
    )
    record_run(
        conn,
        trade_date,
        user_id,
        window_trading_days,
        status=run_status,
        stats=_empty_stats(
            user_id,
            window_trading_days,
            codes=len(codes),
            inserted=written,
            issues=issues,
        ),
    )
    return written
