"""T-B58：既有交易所退市合并实现的隔离 PG 验证，不代替缺失的对账/信号链路验收。

只接受本任务创建的 /tmp/tb58-*-socket，固定新库 tb58_isolated；不从环境读取数据库或证书。
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import RowMapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.base import metadata
from app.db.tables.market import (
    master_snapshots,
    securities,
    security_listing_status_history,
    security_reconciliation_diffs,
)
from app.master.reconcile import reconcile_vendor_lists
from app.master.sources import DelistRow, ListRow
from app.master.sync import Snap, Stats, merge_delists


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-dir", type=Path, required=True)
    socket = parser.parse_args().socket_dir.resolve()
    if socket != Path(tempfile.gettempdir()) / "tb58-pg3-socket":
        parser.error("只允许本任务专用套接字")
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
                "专用隔离数据库",
            )
            # A fresh schema is required; fail closed rather than touching pre-existing data.
            if conn.execute(
                text("SELECT count(*) FROM pg_namespace WHERE nspname='market'")
            ).scalar():
                raise RuntimeError("market 已存在，拒绝修改")
            conn.execute(text("CREATE SCHEMA market"))
            conn.execute(text("CREATE EXTENSION btree_gist"))
            metadata.create_all(
                conn,
                tables=[
                    master_snapshots,
                    securities,
                    security_listing_status_history,
                    security_reconciliation_diffs,
                ],
            )
            day = dt.date(2026, 11, 6)
            row = DelistRow(
                "609991", "虚构退市证券", dt.date(2020, 1, 2), dt.date(2026, 10, 30), "SH"
            )
            snap = Snap("sse_delist", "ok", rows=[row])
            merge_delists(conn, {"sse_delist": snap}, trade_date=day, stats=Stats())

            def read() -> RowMapping:
                return (
                    conn.execute(select(securities).where(securities.c.code == "609991.SH"))
                    .mappings()
                    .one()
                )

            check(
                read()["listing_status"] == "delisted" and read()["master_source"] == "exchange",
                "现有 merge_delists 按交易所写 delisted",
            )
            merge_delists(
                conn, {"sse_delist": snap}, trade_date=day + dt.timedelta(days=3), stats=Stats()
            )
            check(read()["listing_status"] == "delisted", "重复终止上市快照保持 delisted")
            check(
                conn.execute(
                    select(text("count(*)")).select_from(security_listing_status_history)
                ).scalar()
                == 1,
                "重复快照不重复写状态历史",
            )
            # A rejected exchange snapshot cannot create a delisted security.
            rejected = Snap(
                "sse_delist",
                "rejected",
                rows=[DelistRow("609992", "虚构拒收证券", None, day, "SH")],
            )
            merge_delists(conn, {"sse_delist": rejected}, trade_date=day, stats=Stats())
            check(
                conn.execute(
                    select(securities.c.code).where(securities.c.code == "609992.SH")
                ).scalar()
                is None,
                "拒收快照不改主数据",
            )
            listed = ListRow("609993", "虚构在市证券", day, "SH", "sh_main", "stock")
            merge_delists(
                conn,
                {
                    "sse_delist": Snap(
                        "sse_delist",
                        "ok",
                        rows=[DelistRow("609993", "虚构在市证券", day, day, "SH")],
                    ),
                    "sse_list": Snap("sse_list", "ok", rows=[listed]),
                },
                trade_date=day,
                stats=Stats(),
            )
            check(
                conn.execute(
                    select(securities.c.code).where(securities.c.code == "609993.SH")
                ).scalar()
                is None,
                "当前交易所在市名单优先，不被终止名单提前覆盖",
            )
            # Exercise the real transactional reconciliation core, not SQL reimplementation.
            scope = UUID("00000000-0000-4000-8000-000000000058")
            other = UUID("00000000-0000-4000-8000-000000000059")
            snapshots = {
                "hslt_list": {"609991.SH": "供应商滞后简称"},
                "bj_list_all": {},
                "kc_list_all": {},
            }
            table = security_reconciliation_diffs
            start = dt.date(2026, 11, 2)
            before = dict(read())
            for offset in range(5):
                result = reconcile_vendor_lists(
                    conn,
                    snapshots,
                    source_licence_id=scope,
                    as_of=start + dt.timedelta(days=offset),
                )
                check(not result.alert_ids, f"第{offset + 1}工作日尚不产生滞后告警候选")

            def active() -> RowMapping:
                return (
                    conn.execute(
                        select(table).where(
                            table.c.source_licence_id == scope, table.c.status == "open"
                        )
                    )
                    .mappings()
                    .one()
                )

            check(
                active()["kind"] == "vendor_stale_listed" and active()["seen_days"] == 5,
                "真实差异表入库且工作日累计5次",
            )
            reconcile_vendor_lists(
                conn, snapshots, source_licence_id=scope, as_of=start + dt.timedelta(days=4)
            )
            check(active()["seen_days"] == 5, "同工作日重复快照不加天数")
            for offset in (5, 6):
                result = reconcile_vendor_lists(
                    conn,
                    snapshots,
                    source_licence_id=scope,
                    as_of=start + dt.timedelta(days=offset),
                )
                check(
                    result.weekend_skipped and active()["seen_days"] == 5 and not result.alert_ids,
                    "周末不增加seen_days或产生滞后告警候选",
                )
            sixth = start + dt.timedelta(days=7)
            result = reconcile_vendor_lists(conn, snapshots, source_licence_id=scope, as_of=sixth)
            check(
                active()["seen_days"] == 6 and result.alert_ids == [active()["id"]],
                "第6工作日跨过>5阈值才返回告警候选（非管理端投递）",
            )
            result = reconcile_vendor_lists(conn, snapshots, source_licence_id=scope, as_of=sixth)
            check(not result.alert_ids, "重跑第6工作日不重复告警候选")
            check(dict(read()) == before, "供应商滞后不改证券主表，保持交易所delisted")
            try:
                reconcile_vendor_lists(
                    conn, {"hslt_list": {}}, source_licence_id=scope, as_of=sixth
                )
            except ValueError:
                check(active()["status"] == "open", "部分列表拒绝关闭差异")
            else:
                check(False, "部分列表必须拒绝")
            try:
                reconcile_vendor_lists(conn, snapshots, source_licence_id=scope, as_of=start)
            except ValueError:
                check(active()["seen_days"] == 6, "过期快照不回滚计数或关闭差异")
            else:
                check(False, "过期快照必须拒绝")
            reconcile_vendor_lists(conn, snapshots, source_licence_id=other, as_of=sixth)
            # Keep an unrelated source's diff open, as required by same-class closure.
            conn.execute(
                table.insert().values(
                    kind="quote_conflict",
                    source="mairui_real_all",
                    security_code="609991.SH",
                    source_licence_id=scope,
                    first_seen_on=sixth,
                    last_seen_on=sixth,
                    seen_days=1,
                )
            )
            empty = {"hslt_list": {}, "bj_list_all": {}, "kc_list_all": {}}
            result = reconcile_vendor_lists(
                conn, empty, source_licence_id=scope, as_of=sixth + dt.timedelta(days=1)
            )
            check(result.resolved == 1, "下一次同类完整对账不再出现才关闭差异")
            old = (
                conn.execute(
                    select(table).where(
                        table.c.source_licence_id == scope, table.c.kind == "vendor_stale_listed"
                    )
                )
                .mappings()
                .one()
            )
            check(
                old["status"] == "resolved" and old["resolved_on"] == sixth + dt.timedelta(days=1),
                "关闭日期已持久化",
            )
            try:
                reconcile_vendor_lists(conn, snapshots, source_licence_id=scope, as_of=start)
            except ValueError:
                check(
                    conn.execute(select(table.c.status).where(table.c.id == old["id"])).scalar()
                    == "resolved",
                    "全已关闭后仍拒绝过期快照重开差异",
                )
            else:
                check(False, "已关闭差异不能被旧快照重开")
            check(
                conn.execute(
                    select(table.c.status).where(table.c.source_licence_id == other)
                ).scalar()
                == "open",
                "不关闭其他作用域差异",
            )
            check(
                conn.execute(
                    select(table.c.status).where(table.c.source == "mairui_real_all")
                ).scalar()
                == "open",
                "不关闭其他来源差异",
            )
            conn.execute(
                securities.insert().values(
                    code="609994.SH",
                    name="虚构在市证券",
                    type="stock",
                    exchange="SH",
                    listing_status="listed",
                )
            )
            snapshots["hslt_list"] = {"609995.SH": "虚构未知证券"}
            result = reconcile_vendor_lists(
                conn, snapshots, source_licence_id=scope, as_of=sixth + dt.timedelta(days=2)
            )
            kinds = set(
                conn.execute(
                    select(table.c.kind).where(
                        table.c.source_licence_id == scope,
                        table.c.source == "mairui_lists",
                        table.c.status == "open",
                    )
                ).scalars()
            )
            check(
                kinds == {"vendor_unknown", "quote_missing"} and len(result.alert_ids) == 2,
                "未知/缺失按既有枚举入库并立即返回告警候选",
            )
            check(
                conn.execute(
                    select(securities.c.code).where(securities.c.code == "609995.SH")
                ).scalar()
                is None,
                "供应商未知证券不能新建主数据",
            )
        finally:
            tx.rollback()
    engine.dispose()
    print(
        f"{sum(results)} passed, {len(results) - sum(results)} failed；隔离合并/对账核心通过；"
        "未验收采集任务、管理端告警投递或信号流水线"
    )
    return int(not all(results))


if __name__ == "__main__":
    raise SystemExit(main())
