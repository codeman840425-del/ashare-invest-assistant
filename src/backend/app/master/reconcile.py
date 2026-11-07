"""已成功取得的供应商三列表与主表对账（plan 4.6.1/4.6.4）。

本模块不采集、不读取凭据、不提交事务、不改证券主表。调用方必须提供同一
账户作用域三份完整成功快照；缺任何一份则拒绝，不能用局部快照关闭差异。
返回的 alert_ids 只是阈值跨越候选，须由调用方提交后交管理端告警链路；
此数据层函数不冒充尚未注册的 master.reconcile_vendor 任务或信号流水线。
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import Connection, func, insert, select, text, update

from app.db.tables.market import securities, security_reconciliation_diffs

REQUIRED_LISTS = frozenset({"hslt_list", "bj_list_all", "kc_list_all"})
LIST_KINDS = frozenset({"vendor_stale_listed", "vendor_unknown", "quote_missing"})


@dataclass
class ReconcileResult:
    opened: int = 0
    updated: int = 0
    resolved: int = 0
    alert_ids: list[int] = field(default_factory=list)
    weekend_skipped: bool = False


def reconcile_vendor_lists(
    conn: Connection,
    snapshots: Mapping[str, Mapping[str, str]],
    *,
    source_licence_id: UUID,
    as_of: dt.date,
    stale_alert_days: int = 5,
) -> ReconcileResult:
    """按作用域串行入库；seen_days 只累计实际成功对账的不同工作日。

    不替未观察到的日期增加天数；失败/部分快照不调用本函数。周末无写入，
    重跑同日不增天数。差异只在下一次相同来源/作用域完整对账消失时关闭。
    """
    if set(snapshots) != REQUIRED_LISTS:
        raise ValueError("对账必须提供三份完整成功快照（hslt/bj/kc），不能使用局部列表")
    if stale_alert_days < 1 or not isinstance(source_licence_id, UUID):
        raise ValueError("非法阈值或作用域")
    vendor: dict[str, str] = {}
    for key in sorted(snapshots):
        for code, name in snapshots[key].items():
            if not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code) or not isinstance(name, str):
                raise ValueError("供应商快照必须先规范化代码和简称")
            vendor[code] = name
    result = ReconcileResult()
    if as_of.weekday() >= 5:
        result.weekend_skipped = True
        return result
    # Same scope cannot concurrently create duplicate open rows or count a day twice.
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
        {"scope": "master.mairui_lists:" + str(source_licence_id)},
    )
    master = {
        r.code: r.listing_status
        for r in conn.execute(
            select(securities.c.code, securities.c.listing_status).where(
                securities.c.type.in_({"stock", "cdr"})
            )
        )
    }
    wanted: dict[tuple[str, str], str | None] = {}
    for code, name in vendor.items():
        state = master.get(code)
        if state == "delisted":
            wanted[("vendor_stale_listed", code)] = name
        elif state not in {"listed", "delisting_period"}:
            wanted[("vendor_unknown", code)] = name
    for code, state in master.items():
        if state in {"listed", "delisting_period"} and code not in vendor:
            wanted[("quote_missing", code)] = None
    table = security_reconciliation_diffs
    base_scope = (
        table.c.source == "mairui_lists",
        table.c.source_licence_id == source_licence_id,
        table.c.kind.in_(LIST_KINDS),
    )
    latest = conn.execute(
        select(func.max(func.greatest(table.c.last_seen_on, table.c.resolved_on))).where(
            *base_scope
        )
    ).scalar()
    if latest is not None and as_of < latest:
        raise ValueError("拒绝用早于最近对账日的快照更新或关闭差异")
    scope = (*base_scope, table.c.status == "open")
    opened = {
        (r["kind"], r["security_code"]): r
        for r in conn.execute(select(table).where(*scope)).mappings()
    }
    if any(as_of < r["last_seen_on"] for r in opened.values()):
        raise ValueError("拒绝用早于最近对账日的快照更新或关闭差异")
    for key, old in opened.items():
        if key not in wanted:
            conn.execute(
                update(table)
                .where(table.c.id == old["id"])
                .values(status="resolved", resolved_on=as_of)
            )
            result.resolved += 1
    for (kind, code), name in sorted(wanted.items()):
        old = opened.get((kind, code))
        if old is None:
            ident = conn.execute(
                insert(table)
                .values(
                    kind=kind,
                    source="mairui_lists",
                    security_code=code,
                    source_name=name,
                    source_licence_id=source_licence_id,
                    first_seen_on=as_of,
                    last_seen_on=as_of,
                    seen_days=1,
                )
                .returning(table.c.id)
            ).scalar_one()
            result.opened += 1
            if kind in {"vendor_unknown", "quote_missing"}:
                result.alert_ids.append(ident)
        else:
            days = old["seen_days"] + int(as_of > old["last_seen_on"])
            conn.execute(
                update(table)
                .where(table.c.id == old["id"])
                .values(
                    source_name=name,
                    last_seen_on=as_of,
                    seen_days=days,
                )
            )
            result.updated += 1
            if kind == "vendor_stale_listed" and old["seen_days"] <= stale_alert_days < days:
                result.alert_ids.append(old["id"])
    return result
