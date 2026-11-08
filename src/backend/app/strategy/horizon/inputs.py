"""周期分类器输入组装 + 证据（GET /horizon-assessments，T-B47 / T-B30）。

输入来源（``horizon_classifier.yaml`` ``features``）：

- ``profile.*``：最新一版 ``user_profiles``（未填写 → null → 画像类 hint 规则跳过）。
- ``user.has_position``：该用户任一账户 ``holdings.quantity > 0``；``user.has_t_trades``：有同日
  买卖（未作废成交）；无任何成交时为 null。``user.avg_holding_days``：持有期口径待 plan 第 9 节
  （交易日 FIFO 配对）确认，暂为 null（null 只是不计分，不触发数据不足）。
- ``sec.type`` / ``sec.board``：证券公开主数据；主数据缺失时 ``sec.board`` 按代码段推断
  （``epistemic_type: estimate``），``sec.type`` 为 null。
- ``f.*``：特征库（feature_catalog / feature_bars_daily）由行情任务落库，尚未接入 → 全部 null，
  计入 ``inputs_missing`` 并按 ``data_missing_cap`` 封顶。``f.is_st`` / ``f.is_delisting_period``
  可由主数据的 ``risk_flag`` / ``listing_status`` 得到（主数据有该行时）。

``snapshot_id``：输入快照的确定性 UUIDv5（分类器版本 + 规范化输入），同输入同 ID；
尚未写入 ``data_snapshots``（purpose 枚举无 horizon，见报告 T-B47 给架构师的问题）。
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, and_, exists, func, select
from sqlalchemy.orm import aliased

from app.auth.service import bj, latest_profile, now_utc
from app.db.tables.accounts import accounts, holdings, trades
from app.db.tables.market import securities
from app.importing.preview import infer_board, infer_market

#: UUIDv5 命名空间（固定值；只用于把输入快照映射成稳定 ID）
SNAPSHOT_NS = uuid.UUID("6f1d2b1e-4c7a-5d1e-9a51-1b0c0d7e0b47")

_UNITS = {"f.list_days": "trading_days"}


@dataclass
class Inputs:
    values: dict[str, Any] = field(default_factory=dict)
    #: 输入键 → Evidence（契约 §5.1 结构，不含 id；id 由 :func:`evidence` 分配）
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)


def _src(
    key: str,
    value: Any,  # noqa: ANN401
    provider: str,
    as_of: dt.datetime | None,
    fetched: dt.datetime,
    epistemic: str = "fact",
) -> dict[str, Any]:
    if isinstance(value, list):
        value = ",".join(str(x) for x in value)
    return {
        "key": key,
        "value": value,
        "unit": _UNITS.get(key),
        "provider": provider,
        "endpoint": None,
        "data_as_of": bj(as_of or fetched),
        "fetched_at": bj(fetched),
        "epistemic_type": epistemic,
    }


def collect(conn: Connection, user_id: uuid.UUID, code: str, features: list[str]) -> Inputs:
    now = now_utc()
    out = Inputs(values=dict.fromkeys(features))
    vals, srcs = out.values, out.sources

    prof = latest_profile(conn, user_id)
    if prof is not None:
        p_at = prof.confirmed_at or prof.created_at
        pref = list(prof.horizon_pref) if prof.horizon_pref else None
        for key, value in (
            ("profile.horizon_pref", pref),
            ("profile.effort", prof.effort),
            ("profile.risk_tolerance", prof.risk_tolerance),
            ("profile.experience", prof.experience),
        ):
            if key in vals and value is not None:
                vals[key] = value
                srcs[key] = _src(key, value, "user_input", p_at, now)

    sec = conn.execute(select(securities).where(securities.c.code == code)).first()
    bare, _, market = code.partition(".")
    if sec is not None:
        s_at = sec.master_as_of or sec.updated_at
        for key, value in (("sec.type", sec.type), ("sec.board", sec.board)):
            if key in vals and value is not None:
                vals[key] = value
                srcs[key] = _src(key, value, "exchange", s_at, now)
    # T-A22: current master flags are NOT historical evidence. Require an exact
    # prior trading-day delivery; failed/absent membership stays unknown.
    if {"f.is_st", "f.is_delisting_period"}.intersection(vals):
        from app.master.mairui_snapshot import latest_visible_flags

        flags = latest_visible_flags(conn, code, as_of=now)
        for key in ("f.is_st", "f.is_delisting_period"):
            value = flags[key]
            if key in vals and value is not None:
                vals[key] = value
                srcs[key] = _src(
                    key, value, "mairui_list", flags["data_as_of"], flags["fetched_at"]
                )
    if vals.get("sec.board") is None and "sec.board" in vals:
        board = infer_board(bare, market or infer_market(bare))
        vals["sec.board"] = board
        srcs["sec.board"] = _src("sec.board", board, "system", now, now, "estimate")

    acc_ids = select(accounts.c.id).where(accounts.c.user_id == user_id)
    live = and_(
        trades.c.user_id == user_id,
        trades.c.security_code == code,
        trades.c.voided_at.is_(None),
    )
    n_trades, last_trade = conn.execute(
        select(func.count(), func.max(trades.c.created_at)).where(live)
    ).one()
    held = conn.execute(
        select(func.max(holdings.c.rebuilt_at), func.count()).where(
            holdings.c.account_id.in_(acc_ids),
            holdings.c.security_code == code,
            holdings.c.quantity > 0,
        )
    ).one()
    if "user.has_position" in vals:
        vals["user.has_position"] = bool(held[1])
        srcs["user.has_position"] = _src(
            "user.has_position", bool(held[1]), "user_import", held[0] or last_trade, now
        )
    if "user.has_t_trades" in vals and n_trades:
        other = aliased(trades)
        has_t = bool(
            conn.execute(
                select(
                    exists().where(
                        live,
                        trades.c.side == "buy",
                        exists().where(
                            other.c.user_id == user_id,
                            other.c.security_code == code,
                            other.c.voided_at.is_(None),
                            other.c.side == "sell",
                            other.c.account_id == trades.c.account_id,
                            other.c.trade_date == trades.c.trade_date,
                        ),
                    )
                )
            ).scalar()
        )
        vals["user.has_t_trades"] = has_t
        srcs["user.has_t_trades"] = _src("user.has_t_trades", has_t, "user_import", last_trade, now)
    return out


def snapshot_id(classifier_version: str, code: str, values: dict[str, Any]) -> str:
    canon = json.dumps(
        {"v": classifier_version, "code": code, "in": values},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(SNAPSHOT_NS, canon))


def evidence(inputs: Inputs, used: set[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """被理由引用的输入 → ``Evidence[]``（id 在本响应内唯一：``e1``、``e2``…，按键名排序）。"""
    items: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    for n, key in enumerate(sorted(k for k in used if k in inputs.sources), start=1):
        ids[key] = f"e{n}"
        items.append({"id": f"e{n}", **inputs.sources[key]})
    return items, ids
