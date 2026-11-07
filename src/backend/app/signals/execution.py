"""Deterministic conservative executability, not strategy or RiskHook decisions."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from app.signals.models import MarketFacts, SignalInput

# Contract 6.1 / plan2.5.9: values are release predicates, not trading thresholds.
RELEASE = {
    "KEY_DATA_MISSING": (
        "expr",
        "required_fields_non_null",
        ["tick", "daily_close"],
        "必需字段在新快照中非空",
    ),
    "DATA_STALE": ("expr", "data_status == 'fresh'", ["tick"], "关键数据恢复fresh"),
    "LOW_CONFIDENCE": (
        "expr",
        "confidence >= threshold",
        ["tick", "daily_close"],
        "置信度达到本人阈值",
    ),
    "NON_TRADING_TIME": ("time", None, ["schedule"], "下一交易日09:30"),
    "SUSPENDED": ("event", None, ["tick", "daily_close"], "复牌且行情恢复成交"),
    "LIMIT_LOCKED": (
        "expr",
        "price < limit_up_price if buy else price > limit_down_price",
        ["tick"],
        "方向对应涨跌停打开",
    ),
    "ST_OR_DELISTING": ("event", None, ["daily_close"], "摘帽；退市整理期不可解除"),
    "NEW_LISTING": ("expr", "listed_days >= 30", ["daily_close"], "上市达到30个交易日"),
    "INSUFFICIENT_CASH": (
        "expr",
        "available_cash >= required_cash",
        ["cash_update", "import"],
        "可用现金达到一个交易单位所需现金",
    ),
    "T1_NOT_SELLABLE": (
        "expr",
        "sellable_qty > 0",
        ["schedule", "holding_change"],
        "下一交易日09:30或可卖数量满足交易单位（零股一次卖完）",
    ),
    "NO_POSITION": ("expr", "holding_qty > 0", ["holding_change", "import"], "恢复持仓"),
    "BLOCKLISTED": ("user_action", None, ["user_action"], "通过/restrictions移出禁投名单"),
    "USER_MUTED": (
        "user_action",
        None,
        ["user_action", "schedule"],
        "通过/restrictions取消屏蔽或到期",
    ),
    "COOLING_OFF": ("time", None, ["schedule"], "冷静期结束"),
}

RELEASE.update(
    {
        "POSITION_CAP_REACHED": (
            "expr",
            "position_pct < cap",
            ["tick", "holding_change"],
            "单只仓位降至本人上限以下",
        ),
        "STRATEGY_BUDGET_EXHAUSTED": (
            "expr",
            "strategy_used < budget",
            ["holding_change"],
            "策略预算恢复",
        ),
        "SECTOR_EXPOSURE_EXCEEDED": (
            "expr",
            "sector_pct < cap",
            ["holding_change", "tick"],
            "行业暴露降至本人上限以下",
        ),
        "REGIME_MISMATCH": (
            "expr",
            "regime_matches or total_exposure < regime_cap",
            ["daily_close"],
            "大盘环境恢复适用或总仓位低于环境上限",
        ),
        "LOSS_STREAK_PAUSE": (
            "user_action",
            None,
            ["user_action", "schedule"],
            "本人确认恢复或暂停期结束",
        ),
    }
)


def condition(code: str, *, at: dt.datetime | None = None) -> dict[str, Any]:
    kind, expr, check, text = RELEASE[code]
    return {
        "kind": kind,
        "expr": expr,
        "at": at.isoformat() if at else None,
        "event": "security.resumed"
        if code == "SUSPENDED"
        else "security.risk_flag_changed"
        if code == "ST_OR_DELISTING"
        else None,
        "action": "remove_restriction" if code in {"BLOCKLISTED", "USER_MUTED"} else None,
        "check_on": check,
        "human_text": text,
        "machine_checkable": code != "LOSS_STREAK_PAUSE",
    }


def assess(
    content: SignalInput,
    facts: MarketFacts,
    *,
    qty: Decimal,
    sellable: Decimal,
    cash: Decimal | None,
    min_buy: int,
    min_sell: int,
    risk_flag: str | None,
    trading: bool,
    next_open: dt.datetime | None,
) -> list[dict[str, Any]]:
    buy = content.proposed_action in {"buy", "add"}
    codes = []
    if content.data_status != "fresh":
        codes.append("DATA_STALE" if content.data_status == "stale" else "KEY_DATA_MISSING")
    if (
        facts.price is None
        or facts.is_suspended is None
        or (facts.limit_locked_up if buy else facts.limit_locked_down) is None
    ):
        codes.append("KEY_DATA_MISSING")
    if content.confidence.value < facts.confidence_min:
        codes.append("LOW_CONFIDENCE")
    if not trading:
        codes.append("NON_TRADING_TIME")
    if facts.is_suspended is True:
        codes.append("SUSPENDED")
    if (facts.limit_locked_up if buy else facts.limit_locked_down) is True:
        codes.append("LIMIT_LOCKED")
    if buy:
        if risk_flag in {"st", "star_st", "delisting"}:
            codes.append("ST_OR_DELISTING")
        if facts.list_days is None:
            codes.append("KEY_DATA_MISSING")
        elif facts.list_days < 30:
            codes.append("NEW_LISTING")
        if cash is None or facts.required_cash is None:
            codes.append("KEY_DATA_MISSING")
        if (
            facts.price is not None
            and facts.required_cash is not None
            and facts.required_cash < facts.price * min_buy
        ):
            raise ValueError("required_cash_below_minimum_notional")
        required = (
            facts.required_cash
            if facts.required_cash is not None
            else facts.price * min_buy
            if facts.price is not None
            else None
        )
        if cash is not None and required is not None and cash < required:
            codes.append("INSUFFICIENT_CASH")
    else:
        if qty <= 0:
            codes.append("NO_POSITION")
        elif sellable <= 0:
            codes.append("T1_NOT_SELLABLE")
    result: list[dict[str, Any]] = [
        {
            "code": code,
            "release_condition": condition(
                code, at=next_open if code in {"NON_TRADING_TIME", "T1_NOT_SELLABLE"} else None
            ),
        }
        for code in dict.fromkeys(codes)
    ]
    for reason in result:
        if reason["code"] == "INSUFFICIENT_CASH":
            reason["release_condition"]["expr"] = f"available_cash >= {required}"
        if reason["code"] == "LOW_CONFIDENCE":
            reason["release_condition"]["expr"] = f"confidence >= {facts.confidence_min}"
    return result
