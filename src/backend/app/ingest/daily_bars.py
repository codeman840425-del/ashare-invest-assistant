"""日 K HTTP 预算与 ingest 侧拉取（T-B130 / 单 C）。

常量与 ``daily_bars_http_budget`` 是本模块的配置面，不进 Settings，不读环境
变量或回执来放宽限额。默认 ``DAILY_BARS_HTTP_LIMIT = 0``（unset）。把限额改成
``DAILY_BARS_HTTP_UNLIMITED`` 属于开放单 D，须用户本人批准，本模块不提供切换入口。

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

DAILY_BARS_HTTP_UNLIMITED = "unlimited"
DAILY_BARS_HTTP_LIMIT: int = 0
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


Transport = Callable[[str, dt.date, dt.date], tuple[int, DailyBar | None]]
GrantReader = Callable[[], object | None]
Clock = Callable[[], dt.datetime]


@dataclass(frozen=True)
class DailyBarsBudget:
    kind: Literal["unset", "unlimited", "capped"]
    cap: int | None = None


class MairuiDailyBarsSource:
    """仅 ingest 进程可调用的麦蕊日 K 源。出网必须走注入的 transport。"""

    name = "mairui"


def daily_bars_http_budget(value: object) -> DailyBarsBudget:
    """解析限额。0 / 非法值 → unset；哨兵 → unlimited；正整数 → capped（仅测试）。"""
    if value == DAILY_BARS_HTTP_UNLIMITED:
        return DailyBarsBudget(kind="unlimited")
    if type(value) is int and value > 0:
        return DailyBarsBudget(kind="capped", cap=value)
    return DailyBarsBudget(kind="unset")


def daily_bars_batch_budget(value: object, batch_kind: str = "daily") -> DailyBarsBudget:
    """Reject caps outside this batch type's bound; defaults never borrow backfill quota."""
    if batch_kind not in {"daily", "backfill"}:
        return DailyBarsBudget(kind="unset")
    ceiling = (
        DAILY_BARS_DAILY_BATCH_CEILING if batch_kind == "daily" else DAILY_BARS_BATCH_CEILING
    )
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

    budget = daily_bars_http_budget(DAILY_BARS_HTTP_LIMIT)
    if budget.kind == "unset":
        _record_run(
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
        _record_run(
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
            _record_run(
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
        _record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="skipped",
            stats=_empty_stats(user_id, window_trading_days, issues=["calendar_not_covered"]),
        )
        return 0

    codes = daily_universe(conn, user_id, trade_date)
    if not codes:
        _record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="ok",
            stats=_empty_stats(user_id, window_trading_days, codes=0),
        )
        return 0

    # k 未测得：保守按每标的一段，计划调用数 = N（单日）或 N（整段窗口一次）。
    start, end = trade_date, trade_date
    issues: list[str] = []
    bars: list[DailyBar] = []
    last_received: dt.datetime | None = None
    calls = 0

    if halt.is_file() or stop.is_file():
        issues.extend(["daily_bars_upstream_halted"] * len(codes))
        _record_run(
            conn,
            trade_date,
            user_id,
            window_trading_days,
            status="skipped",
            stats=_empty_stats(user_id, window_trading_days, codes=len(codes), issues=issues),
        )
        return 0

    cap = budget.cap if budget.kind == "capped" else None
    for index, code in enumerate(codes):
        if cap is not None and calls >= cap:
            issues.extend(["daily_bars_quota_deferred"] * (len(codes) - index))
            break
        try:
            http_status, payload = send(code, start, end)
        except (DailyHaltError, EgressDenied):
            persist_halt(halt, HALT_LIMIT)
            issues.extend(["daily_bars_upstream_halted"] * (len(codes) - index))
            break
        last_received = _stamp(now)
        calls = index + 1
        if limited(http_status, payload) or http_status in (103, 429):
            persist_halt(halt, HALT_LIMIT)
            issues.extend(["daily_bars_upstream_halted"] * (len(codes) - index))
            break
        if http_status == 200 and isinstance(payload, DailyBar):
            bars.append(payload)
        else:
            issues.append(f"daily_bars_missing:{code}")

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

    run_status = "ok" if last_received is not None or bars else "skipped"
    _record_run(
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
