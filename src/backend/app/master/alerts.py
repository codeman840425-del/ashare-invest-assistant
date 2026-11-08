"""§7.9 五个 master.* 告警，仅由已提交的主数据事实派生，不建告警表。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, any_, func, select

from app.config_files import SecuritiesMaster
from app.db.tables.market import master_runs, master_snapshots
from app.db.tables.market import security_reconciliation_diffs as diffs
from app.master.sync import snapshot_trade_date

MESSAGES = {
    "snapshot_rejected": "证券名单更新失败，暂时沿用上一版",
    "vendor_stale_listed": "行情源仍列着已退市的证券",
    "vendor_unknown": "行情源出现交易所名单里没有的证券，暂不收录",
    "quote_missing": "部分证券在行情源中暂时没有数据",
    "field_mismatch": "部分证券的名称或上市信息与其他来源不一致，待核对",
}


def master_alerts(conn: Connection, cfg: SecuritiesMaster) -> list[dict[str, str]]:
    counts = {
        r.kind: (r.n, r.days)
        for r in conn.execute(
            select(diffs.c.kind, func.count().label("n"), func.max(diffs.c.seen_days).label("days"))
            .where(diffs.c.status == "open")
            .group_by(diffs.c.kind)
        )
    }
    rejected = None
    # 不能只数快照条数：同 sha 被复用，两个时段必须用 master_runs 的实际引用作证。
    by_source: dict[str, list[Any]] = {}
    rows = conn.execute(
        select(
            master_snapshots.c.source,
            master_snapshots.c.parse_status,
            master_runs.c.trigger,
            master_runs.c.started_at,
        )
        .select_from(
            master_runs.join(
                master_snapshots, master_snapshots.c.id == any_(master_runs.c.snapshot_ids)
            )
        )
        .where(
            master_runs.c.trigger.in_(["beat_1800", "beat_0730", "manual", "bootstrap"]),
            master_snapshots.c.source.in_(
                [
                    "sse_list",
                    "sse_delist",
                    "szse_list",
                    "szse_delist",
                    "bse_list",
                    "bse_delist",
                    "mairui_list",
                ]
            ),
        )
        .order_by(master_runs.c.started_at.desc(), master_runs.c.id.desc())
    )
    for row in rows:
        by_source.setdefault(row.source, []).append(row)
    for items in by_source.values():
        latest = items[0]
        if latest.parse_status != "rejected":
            continue
        level = "warning"
        td = snapshot_trade_date(latest.started_at)
        triggers = {
            r.trigger
            for r in items
            if r.parse_status == "rejected" and snapshot_trade_date(r.started_at) == td
        }
        if {"beat_1800", "beat_0730"} <= triggers:
            level = "critical"
        if rejected != "critical":
            rejected = level
    out = []
    for key, message in MESSAGES.items():
        count, days = counts.get(key, (0, 0))
        active = (
            (key == "snapshot_rejected" and rejected is not None)
            or (key == "vendor_stale_listed" and days > cfg.vendor_stale_alert_days)
            or (key in {"vendor_unknown", "quote_missing"} and count > 0)
            or (key == "field_mismatch" and count >= cfg.field_mismatch_alert_rows)
        )
        if active:
            out.append(
                {
                    "level": (rejected or "warning") if key == "snapshot_rejected" else "warning",
                    "key": "master." + key,
                    "message": message,
                }
            )
    return sorted(out, key=lambda x: x["level"] != "critical")
