"""T-B60 独立证券主表保护，不是完整 G-01 或 market.updated 消费器。

依据 plan T-B60、§2.5.11 及契约 §5.2。这里只读权威证券主表，不读 vendor 列表。
调用者提供市场交易日及已经确定的动作；不推断 DSL、生命周期、停牌或 universe。
operation 是未来真实写入器的事务边界，不在这里伪造特征、规则或事件字段。
本组件尚无生产流水线调用点，离线通过不代表 signal-rt 已运行。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.db.tables.market import securities
from app.schemas.enums import Action, ListingStatus, ReasonCode
from app.strategy.eligibility import is_strategy_eligible


@dataclass(frozen=True)
class MasterAdmission:
    allowed: bool
    # 内部诊断标签，不新增公开 reason_code 或响应字段。
    diagnostic: str | None = None
    reason_code: ReasonCode | None = None


def assess_master(
    row: Mapping[str, Any] | None, *, action: Action, trade_date: dt.date
) -> MasterAdmission:
    """检查当前主表，不用于历史回测；未知状态报错，不替调用者决定生命周期。"""
    action = Action(action)
    if type(trade_date) is not dt.date:
        raise ValueError("必须显式传入市场交易日 date")
    if action in {Action.HOLD, Action.WAIT}:
        return MasterAdmission(False, "no_candidate_action")
    if row is None:
        return MasterAdmission(False, "unknown_security")
    if not is_strategy_eligible(row["type"]):
        return MasterAdmission(False, "not_strategy_eligible")
    # 状态即使滞后，交易所已经给定且到期的退市日也必须阻止新的候选。
    if row["listing_status"] == ListingStatus.DELISTED or (
        row["delist_date"] is not None and row["delist_date"] <= trade_date
    ):
        return MasterAdmission(False, "delisted")
    if row["listing_status"] == ListingStatus.MISSING_FROM_LIST:
        return MasterAdmission(False, "missing_from_list")
    if row["listing_status"] not in {ListingStatus.LISTED, ListingStatus.DELISTING_PERIOD}:
        raise ValueError("证券上市状态未确认，不能决定候选写入")
    # T-B60 的具体方向限定与 §2.5.11 一致：退市整理只阻断买入，不抹掉卖出。
    if row["listing_status"] == ListingStatus.DELISTING_PERIOD and action in {
        Action.BUY, Action.ADD
    }:
        return MasterAdmission(False, "delisting_buy", ReasonCode.ST_OR_DELISTING)
    return MasterAdmission(True)


def run_with_master_guard[T](
    conn: Connection,
    *,
    security_code: str,
    action: Action,
    trade_date: dt.date,
    operation: Callable[[Connection], T],
) -> tuple[MasterAdmission, T | None]:
    """同一事务锁住主表后才执行写入；不 commit，操作失败回滚局部写入。

    operation 必须使用传入连接、只处理 security_code/action 所指的对象；这是内部
    可信调用边界，不是接收用户自定义 SQL 的接口，也不替代完整候选 P1/归属校验。
    """
    with conn.begin_nested():
        row = conn.execute(
            select(securities)
            .where(securities.c.code == security_code)
            .with_for_update(read=True)
        ).mappings().one_or_none()
        decision = assess_master(
            dict(row) if row is not None else None, action=action, trade_date=trade_date
        )
        if not decision.allowed:
            return decision, None
        return decision, operation(conn)
