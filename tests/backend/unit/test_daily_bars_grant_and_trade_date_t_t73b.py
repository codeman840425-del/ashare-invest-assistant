# ruff: noqa: S101
"""T-T73b：回执校验（B1）与 CLI --trade-date 须为过去开市日。

依据 git show 7234aa7:docs/contracts/daily-bars-source.md（docs/T-A128 分支头）
§8.1 :437、§4 :94、§8.4 :492–:493，以及 T-B130-review 阻断 B1 / 非阻断第 1 条。
禁用 skip / xfail / importorskip。新符号在用例内探测，缺失时以「缺实现：…」报红。

麦蕊绝对 0：env -u MAIRUI_LICENCE；假 transport；T-T70 换网探针 + egress 计数桩。
回执只写临时路径，并用伪造 root/0444 的 stat 桩走真实 read_daily_bars_grant；
不读不打印真实 licence（licence_id 为测试合成 UUID）。
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import inspect
import io
import json
import os
import stat
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import func, insert, select, text

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_bars_t70_support import (  # noqa: E402
    BEIJING,
    OPEN_10,
    _open_temp_db,
    no_egress,  # noqa: F401
)

INGEST_MOD = "app.ingest.daily_bars"
CLI_MOD = "app.cli.daily_bars_backfill"
CLOCK = dt.datetime(2026, 11, 10, 17, 20, tzinfo=BEIJING)
OWNER = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
CODES = (
    "600010.SH",
    "600011.SH",
    "600012.SH",
    "600013.SH",
    "600014.SH",
)
AT = dt.datetime(2026, 11, 10, 15, 0, tzinfo=BEIJING)
# 回执 kind 集中在此常量。编排者已确认字面量为 "mairui_daily_bars"
#（与 §4 outbox kind、日 K 回执共用）。7234aa7 未写出字面量。
RECEIPT_KIND = "mairui_daily_bars"
# 合成 id，不是真实 licence，也不打印。
_FAKE_LICENCE_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-ccccccccccc1")
_FAKE_RECEIPT_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-ddddddddddd1")
FUTURE_OPEN = dt.date(2026, 11, 11)  # 周三，开市
CLOSED_07 = dt.date(2026, 11, 7)  # 周六，休市


@pytest.fixture
def temp_db(no_egress: None) -> Iterator[SimpleNamespace]:  # noqa: F811
    from _pytest.outcomes import Failed

    gen: Any = None
    ctx: SimpleNamespace | None = None
    last: BaseException | None = None
    for attempt in range(8):
        gen = _open_temp_db()
        try:
            ctx = next(gen)
            break
        except Failed as exc:
            last = exc
            with contextlib.suppress(Exception):
                next(gen, None)
            if "无法在目标实例上创建临时库" not in str(exc) or attempt == 7:
                raise
            time.sleep(0.5)
    else:
        assert last is not None
        raise last
    assert ctx is not None and gen is not None
    try:
        yield ctx
    finally:
        with contextlib.suppress(StopIteration, Failed):
            next(gen)



def _require_ingest(*names: str) -> Any:
    spec = importlib.util.find_spec(INGEST_MOD)
    assert spec is not None, f"缺实现：模块 {INGEST_MOD} 不存在（契约 §8.1）"
    mod = importlib.import_module(INGEST_MOD)
    for name in names:
        assert hasattr(mod, name), f"缺实现：{INGEST_MOD}.{name}（契约 §8.1）"
    return mod


def _clock() -> dt.datetime:
    return CLOCK


def _seed_c_owner(conn: Any) -> None:
    from app.db.tables.accounts import (
        accounts,
        broker_position_snapshot_items,
        broker_position_snapshots,
        import_batches,
    )
    from app.db.tables.market import securities
    from app.db.tables.users import users

    conn.execute(
        insert(users).values(
            id=OWNER,
            username="tt73b_owner",
            display_name="tt73b_owner",
            role="user",
            status="approved",
            password_hash="x",
        )
    )
    for code in CODES:
        conn.execute(
            insert(securities).values(
                code=code,
                type="stock",
                name="合成" + code[:6],
                exchange="SH",
                board="main",
                listing_status="listed",
            )
        )
    account, batch, snapshot = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(insert(accounts).values(id=account, user_id=OWNER, name="tt73b"))
    conn.execute(
        insert(import_batches).values(
            id=batch, user_id=OWNER, account_id=account, status="committed", kind="positions"
        )
    )
    conn.execute(
        insert(broker_position_snapshots).values(
            id=snapshot,
            account_id=account,
            import_batch_id=batch,
            as_of=AT,
            cash_balance=Decimal("100000"),
            cash_available=Decimal("100000"),
            version_no=1,
            created_at=AT,
        )
    )
    for code in CODES:
        conn.execute(
            insert(broker_position_snapshot_items).values(
                id=uuid.uuid4(),
                snapshot_id=snapshot,
                security_code=code,
                quantity=Decimal("100"),
                sellable_quantity=Decimal("100"),
                broker_cost_price=Decimal("10"),
                last_price_ref=Decimal("10"),
            )
        )


def _bar(code: str, day: dt.date) -> Any:
    from app.marketdata.daily_bars import DailyBar

    px = Decimal("10.0000")
    return DailyBar(
        code=code,
        trade_date=day,
        adj_type="none",
        open=px,
        high=px,
        low=px,
        close=px,
        pre_close=px,
        volume=Decimal("10000"),
        amount=Decimal("100000.0000"),
        is_suspended=False,
    )


def _ok_transport(calls: list[tuple[str, dt.date, dt.date]]) -> Callable[..., Any]:
    def transport(code: str, start: dt.date, end: dt.date) -> tuple[int, Any]:
        calls.append((code, start, end))
        return 200, _bar(code, start)

    return transport


def _issues(conn: Any) -> list[str]:
    from app.db.tables.realtime import pipeline_runs

    row = conn.execute(
        select(pipeline_runs.c.stats, pipeline_runs.c.status).order_by(
            pipeline_runs.c.finished_at.desc()
        )
    ).first()
    assert row is not None
    stats = row.stats if isinstance(row.stats, dict) else json.loads(row.stats)
    return list(stats.get("issues") or [])


def _receipt_payload(
    *,
    kind: str = RECEIPT_KIND,
    user_id: uuid.UUID = OWNER,
    not_before: dt.datetime | None = None,
    expires_at: dt.datetime | None = None,
) -> dict[str, str]:
    start = not_before if not_before is not None else dt.datetime(2026, 11, 10, 0, 0, tzinfo=BEIJING)
    end = expires_at if expires_at is not None else dt.datetime(2026, 11, 11, 0, 0, tzinfo=BEIJING)
    return {
        "kind": kind,
        "user_id": str(user_id),
        "licence_id": str(_FAKE_LICENCE_ID),
        "receipt_id": str(_FAKE_RECEIPT_ID),
        "not_before": start.isoformat(),
        "expires_at": end.isoformat(),
    }


def _forge_root_readonly(monkeypatch: pytest.MonkeyPatch, receipt: Path) -> None:
    """伪造 root 属主、文件 0444、目录不可写，使 read_daily_bars_grant 能进入内容校验。不碰 /run/aia。"""
    receipt = receipt.resolve()
    parent = receipt.parent.resolve()
    real_stat = os.stat
    real_fstat = os.fstat
    rec_id = real_stat(receipt)
    par_id = real_stat(parent)

    def _replace(st: os.stat_result, *, is_dir: bool, mode: int) -> os.stat_result:
        ftype = stat.S_IFDIR if is_dir else stat.S_IFREG
        return os.stat_result(
            (
                ftype | mode,
                st.st_ino,
                st.st_dev,
                st.st_nlink,
                0,
                st.st_gid,
                st.st_size,
                st.st_atime,
                st.st_mtime,
                st.st_ctime,
            )
        )

    def fake_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        st = real_stat(path, *args, **kwargs)
        if st.st_ino == par_id.st_ino and st.st_dev == par_id.st_dev:
            return _replace(st, is_dir=True, mode=0o755)
        if st.st_ino == rec_id.st_ino and st.st_dev == rec_id.st_dev:
            return _replace(st, is_dir=False, mode=0o444)
        return st

    def fake_fstat(fd: int) -> os.stat_result:
        st = real_fstat(fd)
        if st.st_ino == rec_id.st_ino and st.st_dev == rec_id.st_dev:
            return _replace(st, is_dir=False, mode=0o444)
        return st

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(os, "fstat", fake_fstat)


def _run_fetch_with_real_grant(
    conn: Any,
    *,
    ibars: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw: bytes,
    calls: list[tuple[str, dt.date, dt.date]],
) -> int:
    receipt = tmp_path / "mairui-daily-bars.json"
    receipt.write_bytes(raw)
    _forge_root_readonly(monkeypatch, receipt)
    # 默认参数 path=AUTHORIZATION 在定义时绑定，不能靠改模块常量改路径；
    # 显式把临时回执交给真实 read_daily_bars_grant，绝不读 /run/aia。
    monkeypatch.setattr(ibars, "DAILY_BARS_BATCH_LIMIT", 5)
    kwargs: dict[str, Any] = {
        "trade_date": OPEN_10,
        "user_id": OWNER,
        "transport": _ok_transport(calls),
        "stop_path": tmp_path / "STOP",
        "halt_path": tmp_path / "HALT",
        "clock": _clock,
    }
    # 41259c0 增加 receipt_path，默认 reader 会传入 clock 与 user_id。
    # 121a17c 无此参数，且 read_daily_bars_grant 只有 path；用 grant_reader 显式传临时文件。
    sig = inspect.signature(ibars.fetch_mairui_daily_bars)
    if "receipt_path" in sig.parameters:
        kwargs["receipt_path"] = receipt
    else:
        kwargs["grant_reader"] = lambda: ibars.read_daily_bars_grant(receipt)
    return ibars.fetch_mairui_daily_bars(conn, **kwargs)


def _assert_licence_unavailable_no_net(
    conn: Any,
    calls: list[tuple[str, dt.date, dt.date]],
    written: int,
    *,
    why: str,
) -> None:
    assert written == 0, why
    assert calls == [], why
    issues = _issues(conn)
    assert "data_licence_unavailable" in issues, why + f"；实际 issues={issues!r}"
    from app.db.tables.market import daily_bars

    n = int(conn.execute(select(func.count()).select_from(daily_bars)).scalar_one())
    assert n == 0, why


# ---------------------------------------------------------------------------
# (1) 过期 / kind 错 / 非 JSON 回执：transport 0，记 data_licence_unavailable
# ---------------------------------------------------------------------------


def test_expired_receipt_no_network(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :437；read_grant 有效期 start <= now < end。过期回执不得出网。

    红因（121a17c）：缺实现：B1 read_daily_bars_grant 非空即 True，不校验 expires_at。
    """
    ibars = _require_ingest("fetch_mairui_daily_bars", "read_daily_bars_grant", "DAILY_BARS_BATCH_LIMIT")
    payload = _receipt_payload(
        not_before=dt.datetime(2026, 11, 9, 0, 0, tzinfo=BEIJING),
        expires_at=dt.datetime(2026, 11, 10, 17, 0, tzinfo=BEIJING),  # clock 17:20 已过期
    )
    why = (
        "缺实现：B1 过期回执应按 daily_delivery.read_grant 规则（start–end 有效期，"
        "对照注入 clock）拒绝，transport 0 次并记 data_licence_unavailable"
    )
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _run_fetch_with_real_grant(
            conn,
            ibars=ibars,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            raw=json.dumps(payload).encode("utf-8"),
            calls=calls,
        )
        _assert_licence_unavailable_no_net(conn, calls, written, why=why)


def test_wrong_kind_receipt_no_network(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :437、§4 :91–:94；kind 须为日 K 专用值（见已确认的模块常量 RECEIPT_KIND）。错 kind 不得出网。

    红因（121a17c）：缺实现：B1 不解析 JSON、不校验 kind。
    """
    ibars = _require_ingest("fetch_mairui_daily_bars", "read_daily_bars_grant", "DAILY_BARS_BATCH_LIMIT")
    payload = _receipt_payload(kind="mairui_daily_snapshot")
    why = (
        "缺实现：B1 kind 错误的回执应按 read_grant 字段集合与日 K 专用 kind 拒绝，"
        "transport 0 次并记 data_licence_unavailable"
    )
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _run_fetch_with_real_grant(
            conn,
            ibars=ibars,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            raw=json.dumps(payload).encode("utf-8"),
            calls=calls,
        )
        _assert_licence_unavailable_no_net(conn, calls, written, why=why)


def test_non_json_receipt_no_network(
    temp_db: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.1 :437：回执须按 read_grant 解析 JSON。非 JSON 内容不得出网。

    红因（121a17c）：缺实现：B1 非空文件即返回 True，不解析 JSON。
    """
    ibars = _require_ingest("fetch_mairui_daily_bars", "read_daily_bars_grant", "DAILY_BARS_BATCH_LIMIT")
    why = (
        "缺实现：B1 非 JSON 回执应解析失败并拒绝，transport 0 次并记 data_licence_unavailable"
    )
    with temp_db.engine.begin() as conn:
        _seed_c_owner(conn)
        calls: list[tuple[str, dt.date, dt.date]] = []
        written = _run_fetch_with_real_grant(
            conn,
            ibars=ibars,
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            raw=b"this is not json {",
            calls=calls,
        )
        _assert_licence_unavailable_no_net(conn, calls, written, why=why)


# ---------------------------------------------------------------------------
# (2) --trade-date 不是过去开市日 → 被拒
# ---------------------------------------------------------------------------


class _MemRedis:
    def __init__(self) -> None:
        self._lists: dict[str, list[bytes]] = {}

    def lpush(self, key: str, value: Any) -> int:
        raw = value if isinstance(value, bytes) else str(value).encode()
        buf = self._lists.setdefault(key, [])
        buf.insert(0, raw)
        return len(buf)

    def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    def close(self) -> None:
        return None


def _cli_settings(url: Any) -> Any:
    from app.config import Settings
    from pydantic import SecretStr

    raw = url if isinstance(url, str) else url.render_as_string(hide_password=False)
    return Settings(
        _env_file=None,
        app_env="test",
        daily_bars_source="fake",
        database_url=SecretStr(raw),
        redis_url="redis://127.0.0.1:9/0",
        session_cookie_secure=False,
    )


def _forget_jobs_engine(url: Any) -> None:
    from app.workers import jobs as jobs_mod

    raw = url if isinstance(url, str) else url.render_as_string(hide_password=False)
    cached = jobs_mod._engines.pop(raw, None)
    if cached is not None:
        cached.dispose()


def _run_cli(
    argv: list[str],
    *,
    settings: Any,
    now: dt.datetime,
    redis_client: _MemRedis,
) -> tuple[int, str]:
    spec = importlib.util.find_spec(CLI_MOD)
    assert spec is not None, f"缺实现：模块 {CLI_MOD} 不存在（契约 §8.4 :492）"
    from app.cli.daily_bars_backfill import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(argv, now=now, redis_client=redis_client, settings=settings)
    return code, buf.getvalue()


def _seed_calendar_span(conn: Any, start: dt.date, end: dt.date) -> None:
    from app.db.tables.market import trading_calendar

    cur = start
    rows = []
    while cur <= end:
        rows.append({"date": cur, "is_open": cur.weekday() < 5})
        cur += dt.timedelta(days=1)
    if rows:
        conn.execute(insert(trading_calendar), rows)


def test_backfill_cli_refuses_trade_date_not_past_open_day(temp_db: SimpleNamespace) -> None:
    """派单追加 / T-B130-review 非阻断第 1 条：显式 --trade-date 必须是过去的开市日。

    覆盖：未来开市日 2026-11-11、过去休市日 2026-11-07。now=2026-11-10 18:00（已过 17:45），
    日历覆盖至 2026-11-20，拒绝不得被 calendar_not_covered 掩盖。不入队，退出码非零。

    红因（121a17c）：缺实现：CLI 只拒绝「显式今天且早于 17:45」，不拒绝未来开市日或休市日。
    既有 test_backfill_cli_refuses_today_before_1745 不改、不弱化。
    """
    from app.workers import jobs as jobs_mod

    settings = _cli_settings(temp_db.url)
    now = dt.datetime(2026, 11, 10, 18, 0, tzinfo=BEIJING)
    why_future = (
        "缺实现：B1/派单追加，--trade-date 为未来开市日时应被拒（退出码非零、不入队）"
    )
    why_closed = (
        "缺实现：B1/派单追加，--trade-date 为过去休市日时应被拒（退出码非零、不入队）"
    )
    try:
        with temp_db.engine.begin() as conn:
            conn.execute(text("TRUNCATE market.trading_calendar"))
            _seed_calendar_span(conn, dt.date(2023, 11, 1), dt.date(2026, 11, 20))
        # 两个子情况都跑完再汇总断言，避免 121a17c 上第一项红就看不到休市日是否也被放行。
        client = _MemRedis()
        code, _out = _run_cli(
            ["--years", "3", "--trade-date", FUTURE_OPEN.isoformat(), "--apply"],
            settings=settings,
            now=now,
            redis_client=client,
        )
        client2 = _MemRedis()
        code2, _out2 = _run_cli(
            ["--years", "3", "--trade-date", CLOSED_07.isoformat(), "--apply"],
            settings=settings,
            now=now,
            redis_client=client2,
        )
        failures: list[str] = []
        if code == 0 or client.llen(jobs_mod.QUEUE_KEY) != 0:
            failures.append(why_future + f"（exit={code}, queued={client.llen(jobs_mod.QUEUE_KEY)}）")
        if code2 == 0 or client2.llen(jobs_mod.QUEUE_KEY) != 0:
            failures.append(why_closed + f"（exit={code2}, queued={client2.llen(jobs_mod.QUEUE_KEY)}）")
        assert not failures, "；".join(failures)
    finally:
        _forget_jobs_engine(temp_db.url)

def test_backfill_cli_today_174459_refuse_174500_allow(temp_db: SimpleNamespace) -> None:
    """§8.3 :493：显式 --trade-date 为今天（开市日）时，北京时间 17:44:59 拒绝、17:45:00 起放行。

    既有 test_backfill_cli_refuses_today_before_1745 只用 16:00，不覆盖秒级边界；
    T-T72 dry-run / apply 用 20:00 与 18:00，只覆盖「已过 17:45」，不是 17:45:00 含端点。
    本例固定时钟钉住 17:44:59 与 17:45:00。放行侧用 dry-run 断言 exit 0 且输出当天日期，
    避免与「17:00–17:45 --apply 锁窗」（实现为闭区间含 17:45:00）缠在一起。
    拒绝侧同时跑 dry-run 与 --apply，确认不入队。
    """
    from app.workers import jobs as jobs_mod

    settings = _cli_settings(temp_db.url)
    today = OPEN_10.isoformat()
    refuse_at = dt.datetime(2026, 11, 10, 17, 44, 59, tzinfo=BEIJING)
    allow_at = dt.datetime(2026, 11, 10, 17, 45, 0, tzinfo=BEIJING)
    why_refuse = (
        "缺实现：显式 --trade-date 为今天、北京时间 17:44:59 应被拒（退出码非零、不入队）"
    )
    why_allow = (
        "缺实现：显式 --trade-date 为今天、北京时间 17:45:00 应放行（dry-run 退出码 0，输出当天日期）"
    )
    try:
        with temp_db.engine.begin() as conn:
            conn.execute(text("TRUNCATE market.trading_calendar"))
            _seed_calendar_span(conn, dt.date(2023, 11, 1), dt.date(2026, 11, 20))

        dry = _MemRedis()
        code_dry, _out_dry = _run_cli(
            ["--years", "3", "--trade-date", today],
            settings=settings,
            now=refuse_at,
            redis_client=dry,
        )
        apply_client = _MemRedis()
        code_apply, _out_apply = _run_cli(
            ["--years", "3", "--trade-date", today, "--apply"],
            settings=settings,
            now=refuse_at,
            redis_client=apply_client,
        )
        allow_client = _MemRedis()
        code_allow, out_allow = _run_cli(
            ["--years", "3", "--trade-date", today],
            settings=settings,
            now=allow_at,
            redis_client=allow_client,
        )

        failures: list[str] = []
        if code_dry == 0 or dry.llen(jobs_mod.QUEUE_KEY) != 0:
            failures.append(
                why_refuse + f"（dry-run exit={code_dry}, queued={dry.llen(jobs_mod.QUEUE_KEY)}）"
            )
        if code_apply == 0 or apply_client.llen(jobs_mod.QUEUE_KEY) != 0:
            failures.append(
                why_refuse
                + f"（--apply exit={code_apply}, queued={apply_client.llen(jobs_mod.QUEUE_KEY)}）"
            )
        if (
            code_allow != 0
            or f"trade_date={today}" not in out_allow
            or allow_client.llen(jobs_mod.QUEUE_KEY) != 0
        ):
            failures.append(
                why_allow
                + f"（exit={code_allow}, queued={allow_client.llen(jobs_mod.QUEUE_KEY)}）"
            )
        assert not failures, "；".join(failures)
    finally:
        _forget_jobs_engine(temp_db.url)
