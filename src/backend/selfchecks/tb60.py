"""T-B60 独立主表保护的真实 PG 写入边界验证，不是 market.updated 全链路。

仅用固定 tb58_isolated 本机隔离库；全部 DDL/夹具/写入最终回滚。
使用真实表元数据及外键/P1约束，固定合成候选不是 DSL 求值结果。
"""

from __future__ import annotations

import argparse
import datetime as dt
import secrets
import sys
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Connection, Table, create_engine, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.base import metadata
from app.db.tables.market import securities
from app.db.tables.realtime import signal_events
from app.db.tables.signals import candidate_signal_events, candidate_signals
from app.db.tables.strategy import strategies, strategy_instances, strategy_versions
from app.db.tables.users import users
from app.schemas.enums import Action, ReasonCode
from app.signals.admission import assess_master, run_with_master_guard


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-dir", type=Path, required=True)
    socket = parser.parse_args().socket_dir.resolve()
    if socket != Path(tempfile.gettempdir()) / "tb58-pg3-socket":
        parser.error("只允许既有任务专用隔离套接字")
    engine = create_engine(f"postgresql+psycopg://tb58@/tb58_isolated?host={socket}")
    results = []

    def check(ok: object, name: str) -> None:
        results.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name)

    with engine.connect() as conn:
        tx = conn.begin()
        try:
            check(
                conn.execute(text("SELECT current_database()")).scalar() == "tb58_isolated",
                "固定专用隔离库",
            )
            if conn.execute(
                text("SELECT count(*) FROM pg_namespace WHERE nspname IN ('app','market')")
            ).scalar():
                raise RuntimeError("业务schema已存在，拒绝修改已有数据")
            for schema in ("app", "market"):
                conn.execute(text(f"CREATE SCHEMA {schema}"))
            needed = {securities, candidate_signals, candidate_signal_events, signal_events}
            while True:
                expanded = needed | {
                    fk.column.table for table in needed for fk in table.foreign_keys
                }
                if expanded == needed:
                    break
                needed = expanded
            metadata.create_all(conn, tables=list(needed))
            conn.execute(
                text(
                    "CREATE TABLE app.candidate_signals_offline "
                    "PARTITION OF app.candidate_signals DEFAULT"
                )
            )
            user, strategy, version = uuid4(), uuid4(), uuid4()
            conn.execute(
                users.insert().values(
                    id=user,
                    username="tb60_offline",
                    password_hash=secrets.token_hex(32),
                    role="user",
                    status="approved",
                )
            )
            conn.execute(
                strategies.insert().values(id=strategy, key="tb60_offline", name="离线边界夹具")
            )
            conn.execute(
                strategy_versions.insert().values(
                    id=version,
                    strategy_id=strategy,
                    version_no=1,
                    config={},
                    config_hash="offline",
                    lifecycle="published",
                )
            )
            day = dt.date(2026, 11, 6)
            fixtures = {
                "609980.SH": ("listed", None, "stock"),
                "609981.SH": ("delisted", day - dt.timedelta(days=1), "stock"),
                "609982.SH": ("listed", day, "stock"),
                "609983.SH": ("delisting_period", None, "stock"),
                "609984.SH": ("listed", day + dt.timedelta(days=1), "stock"),
                "609985.SH": ("missing_from_list", None, "stock"),
                "609986.SH": (None, None, "stock"),
                "609987.SH": ("listed", None, "etf"),
                "609988.SH": ("listed", None, "cdr"),
                "609989.SH": ("delisted", day + dt.timedelta(days=1), "stock"),
                "609990.SH": ("listed", day - dt.timedelta(days=2), "stock"),
            }
            for code, (status, end, kind) in fixtures.items():
                conn.execute(
                    securities.insert().values(
                        code=code,
                        name="虚构离线证券",
                        type=kind,
                        exchange="SH",
                        listing_status=status,
                        delist_date=end,
                    )
                )

            def count(table: Table, code: str | None = None) -> int:
                query = select(func.count()).select_from(table)
                if code is not None:
                    query = query.where(table.c.security_code == code)
                return int(conn.execute(query).scalar_one())

            def exercise(
                code: str, action: Action, *, allowed: bool, reason: ReasonCode | None = None
            ) -> None:
                before = (
                    count(candidate_signals),
                    count(signal_events),
                    count(candidate_signal_events),
                )
                called = []

                def write(db: Connection) -> UUID:
                    called.append(True)
                    sid, instance = uuid4(), uuid4()
                    db.execute(
                        strategy_instances.insert().values(
                            id=instance,
                            user_id=user,
                            strategy_version_id=version,
                            scope="security",
                            security_code=code,
                            origin="user",
                            status="active",
                            horizon="short",
                        )
                    )
                    # 固定合法合成候选；不冒充实际行情规则求值，也不实现生命周期算法。
                    db.execute(
                        candidate_signals.insert().values(
                            id=sid,
                            user_id=user,
                            instance_id=instance,
                            strategy_version_id=version,
                            security_code=code,
                            horizon="short",
                            proposed_action=action.value,
                            state="open",
                            rule_refs=[
                                {
                                    "rule_id": "offline-rule",
                                    "role": "exit"
                                    if action in {Action.SELL, Action.REDUCE}
                                    else "entry",
                                    "dimension": "technical",
                                    "passed": True,
                                }
                            ],
                            evidence=[{"id": "offline-fact", "provider": "system"}],
                            counter_evidence=[{"text": "离线合成反证"}],
                            invalidation=[{"text": "离线合成失效条件"}],
                            model_refs=[],
                        )
                    )
                    db.execute(
                        candidate_signal_events.insert().values(
                            signal_id=sid,
                            from_state=None,
                            to_state="open",
                            cause="executability_check",
                        )
                    )
                    db.execute(
                        signal_events.insert().values(
                            security_code=code,
                            scope="shared",
                            trigger_kind="flip",
                            from_state="false",
                            to_state="true",
                            tick_id="offline-boundary-only",
                        )
                    )
                    return sid

                decision, value = run_with_master_guard(
                    conn, security_code=code, action=action, trade_date=day, operation=write
                )
                after = (
                    count(candidate_signals),
                    count(signal_events),
                    count(candidate_signal_events),
                )
                check(
                    decision.allowed == allowed
                    and bool(called) == allowed
                    and (value is not None) == allowed,
                    f"{code}/{action}真实写入器调用与主表判定一致",
                )
                check(
                    after == tuple(n + int(allowed) for n in before),
                    f"{code}/{action}候选/规则事件/初始候选事件实际增量={'1' if allowed else '0'}",
                )
                if reason:
                    check(
                        decision.reason_code == reason,
                        "退市整理买入沿用ST_OR_DELISTING，不新增公开原因码",
                    )

            exercise("609980.SH", Action.BUY, allowed=True)
            exercise("609981.SH", Action.BUY, allowed=False)
            exercise("609981.SH", Action.SELL, allowed=False)
            exercise("609982.SH", Action.ADD, allowed=False)
            exercise("609983.SH", Action.BUY, allowed=False, reason=ReasonCode.ST_OR_DELISTING)
            exercise("609983.SH", Action.ADD, allowed=False, reason=ReasonCode.ST_OR_DELISTING)
            exercise("609983.SH", Action.SELL, allowed=True)
            exercise("609983.SH", Action.REDUCE, allowed=True)
            exercise("609984.SH", Action.BUY, allowed=True)
            exercise("609985.SH", Action.BUY, allowed=False)
            exercise("609987.SH", Action.BUY, allowed=False)
            exercise("609988.SH", Action.BUY, allowed=True)
            exercise("609989.SH", Action.SELL, allowed=False)
            exercise("609990.SH", Action.BUY, allowed=False)
            exercise("000000.SH", Action.BUY, allowed=False)
            exercise("609980.SH", Action.HOLD, allowed=False)
            exercise("609980.SH", Action.WAIT, allowed=False)
            check(
                count(candidate_signals, "609981.SH") == count(signal_events, "609981.SH") == 0,
                "已退市证券两方向实际零写入，有正常证券正对照，不因流水线未跑取巧",
            )
            check(
                count(candidate_signals, "609983.SH") == 2,
                "退市整理只放行卖出/减仓方向，未生成买入候选",
            )
            try:
                exercise("609986.SH", Action.BUY, allowed=False)
            except ValueError:
                check(True, "上市状态未知明确报错，不臆定状态或生命周期")
            else:
                check(False, "未知上市状态必须报错")
            try:
                assess_master(None, action=Action.BUY, trade_date=dt.datetime(2026, 11, 6))
            except ValueError:
                check(True, "拒绝把无市场时区的datetime冒充交易日")
            else:
                check(False, "错误交易日类型未拒绝")
            before = count(signal_events)

            def broken(db: Connection) -> None:
                db.execute(
                    signal_events.insert().values(
                        security_code="609980.SH", scope="shared", trigger_kind="flip"
                    )
                )
                raise RuntimeError("离线故障注入")

            try:
                run_with_master_guard(
                    conn,
                    security_code="609980.SH",
                    action=Action.BUY,
                    trade_date=day,
                    operation=broken,
                )
            except RuntimeError:
                check(
                    count(signal_events) == before,
                    "真实写入后故障仅回滚保护操作savepoint，先前正对照行仍保留",
                )
            check(tx.is_active, "保护组件未commit或结束调用者事务")
            check(count(candidate_signals, "609980.SH") == 1, "正常候选真实存在，非空跑")
        finally:
            tx.rollback()
    with engine.connect() as conn:
        check(
            conn.execute(
                text("SELECT count(*) FROM pg_namespace WHERE nspname IN ('app','market')")
            ).scalar()
            == 0,
            "所有DDL/合成数据最终回滚，无共享库或持久业务数据",
        )
    engine.dispose()
    print(f"{sum(results)} passed, {len(results) - sum(results)} failed")
    return int(not all(results))


if __name__ == "__main__":
    raise SystemExit(main())
